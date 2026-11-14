"""Validate complete simulator batches before touching the database."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from uuid import UUID

from .catalogue import ACTIVITIES, CATALOGUE, ENVIRONMENTS, PREFLIGHT_METRICS, canonical_metric, canonical_unit


class IngestionError(Exception):
    status = 422
    code = 'invalid_payload'

    def __init__(self, message, *, index=None):
        super().__init__(message)
        self.index = index


class Conflict(IngestionError):
    status = 409
    code = 'event_conflict'


@dataclass(frozen=True)
class ValidatedEvent:
    payload: dict
    event_id: UUID
    measured_at: datetime
    emitted_at: datetime
    raw_payload: dict


def text(value, name, maximum=None):
    if not isinstance(value, str) or not value.strip() or (maximum and len(value) > maximum):
        raise IngestionError(f'{name} must be a nonempty string' + (f' of at most {maximum} characters' if maximum else ''))
    return value


def utc(value, name):
    try:
        if not isinstance(value, str) or 'T' not in value:
            raise ValueError
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise IngestionError(f'{name} must be a UTC ISO-8601 timestamp') from None


def numeric(value, name, upper=None):
    try:
        valid = type(value) in (float, int) and math.isfinite(value) and value >= 0
    except (OverflowError, ValueError):
        valid = False
    if not valid or (upper is not None and value > upper):
        raise IngestionError(f'{name} must be a finite nonnegative number' + (f' no greater than {upper}' if upper is not None else ''))


def profile(data, measured_at):
    fields = {'baseline_statistics', 'preflight_radiation_level', 'preflight_radiation_unit',
              'career_radiation_dose', 'career_radiation_unit', 'window_start', 'window_end'}
    if not isinstance(data, dict) or set(data) != fields:
        raise IngestionError('Profile fields do not match schema 1.0')
    if data['preflight_radiation_unit'] != 'mSv/year' or data['career_radiation_unit'] != 'mSv':
        raise IngestionError('Invalid preflight radiation units')
    numeric(data['preflight_radiation_level'], 'preflight_radiation_level')
    numeric(data['career_radiation_dose'], 'career_radiation_dose')
    start, end = utc(data['window_start'], 'window_start'), utc(data['window_end'], 'window_end')
    if not start <= end <= measured_at:
        raise IngestionError('Preflight window must end on/before the profile observation time')
    stats = data['baseline_statistics']
    if not isinstance(stats, dict) or set(stats) != set(PREFLIGHT_METRICS):
        raise IngestionError('Profile must contain the twelve preflight baseline metrics')
    for code, values in stats.items():
        if not isinstance(values, dict) or set(values) != {'mean', 'stddev', 'min', 'max', 'count', 'unit'}:
            raise IngestionError(f'Invalid statistics for {code}')
        if values['unit'] != CATALOGUE[code][0]:
            raise IngestionError(f'Invalid baseline unit for {code}')
        if type(values['count']) is not int or not 2 <= values['count'] <= 2147483647:
            raise IngestionError(f'Invalid baseline sample count for {code}')
        for key in ('mean', 'stddev', 'min', 'max'):
            numeric(values[key], f'{code}.{key}')
        if not values['min'] <= values['mean'] <= values['max']:
            raise IngestionError(f'Invalid baseline range for {code}')


def normalize_identifiers(original):
    """Canonical view for projections and replay comparisons; never mutate source data."""
    data = deepcopy(original)
    if data.get('kind') == 'measurement':
        code = canonical_metric(data.get('metric'), data.get('domain'))
        if 'metric' in data:
            data['metric'] = code
        if 'unit' in data:
            data['unit'] = canonical_unit(code, data['unit'])
    elif data.get('kind') == 'preflight_profile' and isinstance(data.get('profile'), dict):
        stats = data['profile'].get('baseline_statistics')
        if isinstance(stats, dict):
            normalized = {}
            for source_code, values in stats.items():
                code = canonical_metric(source_code, 'astronaut')
                if code in normalized:
                    raise IngestionError(f'Baseline contains multiple identifiers for {code}')
                if isinstance(values, dict) and 'unit' in values:
                    values['unit'] = canonical_unit(code, values['unit'])
                normalized[code] = values
            data['profile']['baseline_statistics'] = normalized
    return data


def validate_event(original):
    if not isinstance(original, dict):
        raise IngestionError('Every event must be an object')
    raw = deepcopy(original)
    data = normalize_identifiers(original)
    common = {'schema_version', 'kind', 'event_id', 'run_id', 'mission_id', 'habitat_id',
              'zone_id', 'astronaut_id', 'domain', 'phase', 'environment', 'measured_at',
              'emitted_at', 'source', 'simulated', 'context'}
    if data.get('schema_version') != '1.0' or data.get('simulated') is not True:
        raise IngestionError('Expected schema_version 1.0 and simulated true')
    kind = data.get('kind')
    if kind not in ('measurement', 'preflight_profile'):
        raise IngestionError('Unsupported event kind')
    required = common | ({'metric', 'unit', 'value'} if kind == 'measurement' else {'profile'})
    if set(data) != required:
        raise IngestionError('Event fields do not match schema 1.0')
    for key in ('run_id', 'mission_id', 'habitat_id', 'zone_id'):
        text(data[key], key, 100)
    text(data['source'], 'source', 200)
    try:
        event_id = UUID(text(data['event_id'], 'event_id', 36))
    except (ValueError, AttributeError):
        raise IngestionError('event_id must be a UUID') from None
    data['event_id'] = str(event_id)
    raw['event_id'] = str(event_id)
    measured, emitted = utc(data['measured_at'], 'measured_at'), utc(data['emitted_at'], 'emitted_at')
    if data['environment'] not in ENVIRONMENTS:
        raise IngestionError('Unsupported mission environment')
    if data['phase'] not in ('preflight', 'inflight') or data['domain'] not in ('astronaut', 'cabin'):
        raise IngestionError('Invalid phase/domain')
    if not isinstance(data['context'], dict):
        raise IngestionError('Context must be an object')
    if data['domain'] == 'astronaut':
        text(data['astronaut_id'], 'astronaut_id', 100)
        if data['context'].get('activity') not in ACTIVITIES:
            raise IngestionError('Astronaut context must include a valid activity')
    elif data['astronaut_id'] is not None or data['phase'] != 'inflight':
        raise IngestionError('Cabin events must be in-flight and have astronaut_id null')
    if kind == 'preflight_profile':
        if data['phase'] != 'preflight' or data['domain'] != 'astronaut':
            raise IngestionError('Profile must be astronaut preflight data')
        profile(data['profile'], measured)
    else:
        code = data['metric']
        if not isinstance(code, str) or code not in CATALOGUE:
            raise IngestionError('Unknown metric')
        unit, domain = CATALOGUE[code]
        if data['unit'] != unit or data['domain'] != domain:
            raise IngestionError('Metric domain/unit mismatch')
        if code == 'is_solar_storm':
            if type(data['value']) is not bool:
                raise IngestionError('is_solar_storm requires a JSON boolean')
        else:
            numeric(data['value'], code, 100 if code in ('spo2', 'relative_humidity') else 10 if code in ('mood', 'stress_level') else None)
        if code == 'blood_glucose' and data['context'].get('meal_context') not in ('fasting', 'after_meal'):
            raise IngestionError('Blood glucose requires meal_context fasting/after_meal')
    return ValidatedEvent(data, event_id, measured, emitted, raw)


def validate_payload(payload, maximum=1000):
    if isinstance(payload, dict) and 'events' in payload:
        if set(payload) != {'schema_version', 'events'} or payload.get('schema_version') != '1.0':
            raise IngestionError('Invalid batch envelope')
        events = payload['events']
    else:
        events = [payload]
    if not isinstance(events, list) or not 1 <= len(events) <= maximum:
        raise IngestionError(f'Expected between 1 and {maximum} events')
    result, seen = [], {}
    for index, event in enumerate(events):
        try:
            item = validate_event(event)
            if item.event_id in seen and seen[item.event_id] != item.payload:
                raise Conflict('Same event_id has conflicting payloads within the batch')
            seen[item.event_id] = item.payload
            result.append(item)
        except IngestionError as exc:
            exc.index = index
            raise
    return result
