"""Versioned wire contracts and strict boundary validation."""
import math
from datetime import datetime, timezone

CATALOGUE = {
    'heart_rate': ('bpm', 'astronaut'),
    'systolic_blood_pressure': ('mmHg', 'astronaut'),
    'diastolic_blood_pressure': ('mmHg', 'astronaut'),
    'blood_glucose': ('mg/dL', 'astronaut'),
    'body_temperature': ('°C', 'astronaut'),
    'respiratory_rate': ('breaths/min', 'astronaut'),
    'spo2': ('%', 'astronaut'),
    'sleep_duration': ('hours', 'astronaut'),
    'mood': ('0–10', 'astronaut'),
    'stress_level': ('0–10', 'astronaut'),
    'fluid_intake': ('L', 'astronaut'),
    'body_mass': ('kg', 'astronaut'),
    'preflight_radiation_level': ('mSv/year', 'astronaut'),
    'preflight_career_radiation_dose': ('mSv', 'astronaut'),
    'personal_radiation_dose_rate': ('mSv/day', 'astronaut'),
    'mission_cumulative_radiation_dose': ('mSv', 'astronaut'),
    'total_career_radiation_dose': ('mSv', 'astronaut'),
    'co2_partial_pressure': ('mmHg', 'cabin'),
    'o2_partial_pressure': ('mmHg', 'cabin'),
    'total_cabin_pressure': ('kPa', 'cabin'),
    'cabin_temperature': ('°C', 'cabin'),
    'relative_humidity': ('%', 'cabin'),
    'noise_level': ('dBA', 'cabin'),
    'dust_concentration': ('mg/m³', 'cabin'),
    'radiation_level': ('mSv/day', 'cabin'),
    'is_solar_storm': ('boolean', 'cabin'),
}
from .extra import SPECS, validate_value
CATALOGUE.update({code:(spec['unit'],spec['domain']) for code,spec in SPECS.items()})

ENVIRONMENTS = ('transit_spacecraft', 'space_station', 'rover', 'surface_base')
ACTIVITIES = ('resting', 'sleeping', 'working', 'exercising', 'eva')


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be a string')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('Timestamps must include UTC timezone')
    return result


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def validate_event(event):
    required = {'schema_version', 'kind', 'event_id', 'run_id', 'mission_id',
                'habitat_id', 'zone_id', 'astronaut_id', 'domain', 'phase', 'measured_at',
                'emitted_at', 'source', 'simulated', 'environment', 'context'}
    if not required <= event.keys():
        raise ValueError(f'Missing fields: {required - event.keys()}')
    if event['schema_version'] != '1.0' or event['simulated'] is not True:
        raise ValueError('Unsupported schema or non-simulated event')
    for key in ('event_id', 'run_id', 'mission_id', 'habitat_id', 'zone_id', 'source'):
        if not isinstance(event[key], str) or not event[key]:
            raise ValueError(f'Invalid {key}')
    if event['environment'] not in ENVIRONMENTS:
        raise ValueError('Invalid environment')
    if event['domain'] not in ('astronaut', 'cabin') or event['phase'] not in ('preflight', 'inflight'):
        raise ValueError('Invalid domain or phase')
    if event['domain'] == 'cabin':
        if event['astronaut_id'] is not None or event['phase'] != 'inflight':
            raise ValueError('Cabin observations belong to habitat only')
    elif not isinstance(event['astronaut_id'], str) or not event['astronaut_id']:
        raise ValueError('Missing astronaut ID')
    timestamp(event['measured_at']); timestamp(event['emitted_at'])
    if not isinstance(event['context'], dict):
        raise ValueError('Context must be an object')
    if event['domain'] == 'astronaut' and event['context'].get('activity') not in ACTIVITIES:
        raise ValueError('Invalid activity')
    if event['kind'] == 'preflight_profile':
        if event['phase'] != 'preflight' or event['domain'] != 'astronaut':
            raise ValueError('Profile must be astronaut preflight data')
        profile = event['profile']
        for metric, stats in profile['baseline_statistics'].items():
            if metric not in CATALOGUE or CATALOGUE[metric][0] != stats['unit']:
                raise ValueError('Invalid baseline metric/unit')
            if type(stats['count']) is not int or stats['count'] < 2 or any(type(stats[k]) not in (int, float) or not math.isfinite(stats[k]) or stats[k] < 0 for k in ('mean', 'stddev', 'min', 'max')) or stats['min'] > stats['max']:
                raise ValueError('Invalid baseline statistics')
        return event
    if event['kind'] != 'measurement':
        raise ValueError('Invalid kind')
    metric = event['metric']
    if metric not in CATALOGUE or (event['unit'], event['domain']) != CATALOGUE[metric]:
        raise ValueError('Unknown metric, domain, or unit')
    value = event['value']
    if metric in SPECS:
        validate_value(metric,value)
    elif metric == 'is_solar_storm':
        if type(value) is not bool:
            raise ValueError('Storm indicator must be boolean')
    elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Measurement must be finite and nonnegative')
    elif metric in ('spo2', 'relative_humidity') and value > 100:
        raise ValueError('Percentage exceeds 100')
    elif metric in ('mood', 'stress_level') and value > 10:
        raise ValueError('Scale exceeds 10')
    if event['domain'] == 'astronaut' and event['context'].get('activity') not in ACTIVITIES:
        raise ValueError('Invalid activity')
    if metric == 'blood_glucose' and event['context'].get('meal_context') not in ('fasting', 'after_meal'):
        raise ValueError('Missing meal context')
    return event
