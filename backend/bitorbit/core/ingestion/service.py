"""Atomic event journal + preflight projection + timestamp-ordered live projection."""
from itertools import groupby

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.models import (
    Astronaut, Habitat, LatestMeasurement, MeasurementEvent, MetricCatalog,
    Mission, MissionCrew, PreflightBaseline, PreflightProfile, SimulationRun,
)
from .catalogue import metric_spec
from .validation import Conflict, normalize_identifiers, utc


def latest_key(run_id, domain, astronaut_id, habitat_id, zone_id, metric_id):
    subject = (astronaut_id,) if domain == 'astronaut' else (habitat_id, zone_id)
    return run_id, domain, subject, metric_id


def supersedes(item, latest):
    """Deterministic UUID tie break; late backfill cannot regress the live view."""
    return (item.measured_at, item.event_id.int) > (latest.measured_at, latest.source_event_id.int)


@transaction.atomic
def ingest(items):
    # Sort lock acquisition to serialize batches for a run without deadlocking two mixed-run batches.
    unique = {}
    for item in items:
        unique.setdefault(item.event_id, item)
    run_missions = {}
    for item in items:
        data = item.payload
        old = run_missions.setdefault(data['run_id'], data['mission_id'])
        if old != data['mission_id']:
            raise Conflict('A run_id cannot refer to different missions')
    missions = {}
    for code in sorted(set(run_missions.values())):
        missions[code], _ = Mission.objects.get_or_create(mission_code=code)
    runs = {}
    for run_id in sorted(run_missions):
        mission = missions[run_missions[run_id]]
        first = next(item for item in items if item.payload['run_id'] == run_id)
        SimulationRun.objects.get_or_create(run_id=run_id, defaults={'mission': mission, 'environment': first.payload['environment']})
        run = SimulationRun.objects.select_for_update().get(run_id=run_id)
        if run.mission_id != mission.pk:
            raise Conflict('Existing run_id belongs to a different mission')
        runs[run_id] = run
    existing = MeasurementEvent.objects.in_bulk(unique)
    new = []
    for identity, item in unique.items():
        if identity in existing:
            if normalize_identifiers(existing[identity].raw_payload) != item.payload:
                raise Conflict(f'event_id {identity} already exists with different contents')
        else:
            new.append(item)
    if not new:
        return {'accepted_event_ids': [str(i.event_id) for i in items], 'created_count': 0, 'duplicate_count': len(items)}

    habitats, astronauts, metrics = {}, {}, {}
    for mission_code, code in sorted({(i.payload['mission_id'], i.payload['habitat_id']) for i in new}):
        habitats[(mission_code, code)], _ = Habitat.objects.get_or_create(mission=missions[mission_code], habitat_code=code)
    for code in sorted({i.payload['astronaut_id'] for i in new if i.payload['astronaut_id'] is not None}):
        astronauts[code], _ = Astronaut.objects.get_or_create(astronaut_code=code)
    codes = set()
    for item in new:
        if item.payload['kind'] == 'measurement':
            codes.add(item.payload['metric'])
        else:
            codes.update(item.payload['profile']['baseline_statistics'])
    for code in sorted(codes):
        spec = metric_spec(code)
        metric, _ = MetricCatalog.objects.get_or_create(code=code, defaults=spec)
        if any(getattr(metric, key) != value for key, value in spec.items()):
            raise Conflict(f'Existing metric catalogue definition conflicts with {code}')
        metrics[code] = metric

    # The first observed habitat is the crew assignment; event habitat/zone records subsequent locations.
    assignments = set()
    for item in new:
        data = item.payload
        if data['astronaut_id'] is not None:
            key = data['mission_id'], data['astronaut_id']
            if key not in assignments:
                MissionCrew.objects.get_or_create(mission=missions[key[0]], astronaut=astronauts[key[1]],
                    defaults={'habitat': habitats[(data['mission_id'], data['habitat_id'])]})
                assignments.add(key)

    # Read the existing maximum before inserting: stale history must not change current environment.
    previous_times = dict(MeasurementEvent.objects.filter(run_id__in=runs).values('run_id')
                          .annotate(latest=Max('measured_at')).values_list('run_id', 'latest'))
    journal = []
    for item in new:
        data = item.payload
        is_measurement = data['kind'] == 'measurement'
        value = data.get('value')
        journal.append(MeasurementEvent(
            event_id=item.event_id, run=runs[data['run_id']], mission=missions[data['mission_id']],
            habitat=habitats[(data['mission_id'], data['habitat_id'])],
            astronaut=astronauts.get(data['astronaut_id']), zone_id=data['zone_id'],
            kind=data['kind'], phase=data['phase'], domain=data['domain'],
            metric=metrics.get(data.get('metric')),
            numeric_value=value if is_measurement and type(value) is not bool else None,
            boolean_value=value if is_measurement and type(value) is bool else None,
            measured_at=item.measured_at, emitted_at=item.emitted_at,
            context=data['context'], raw_payload=item.raw_payload,
        ))
    MeasurementEvent.objects.bulk_create(journal)

    profiles = {(p.run_id, p.astronaut_id): p for p in PreflightProfile.objects.filter(run_id__in=runs)}
    for item in new:
        data = item.payload
        if data['kind'] != 'preflight_profile':
            continue
        astronaut = astronauts[data['astronaut_id']]
        key = data['run_id'], astronaut.pk
        if key in profiles:
            raise Conflict('Preflight profile is immutable for this run/astronaut; replay the original event_id')
        source = data['profile']
        profile = PreflightProfile.objects.create(
            run=runs[data['run_id']], astronaut=astronaut, source_event_id=item.event_id,
            preflight_radiation_level=source['preflight_radiation_level'], career_radiation_dose=source['career_radiation_dose'],
            window_start=utc(source['window_start'], 'window_start'), window_end=utc(source['window_end'], 'window_end'))
        profiles[key] = profile
        PreflightBaseline.objects.bulk_create([
            PreflightBaseline(profile=profile, metric=metrics[code], mean=stats['mean'], stddev=stats['stddev'],
                              min_value=stats['min'], max_value=stats['max'], sample_count=stats['count'])
            for code, stats in source['baseline_statistics'].items()
        ])

    latest_rows = list(LatestMeasurement.objects.filter(run_id__in=runs))
    latest = {latest_key(row.run_id, row.domain, row.astronaut_id, row.habitat_id, row.zone_id, row.metric_id): row for row in latest_rows}
    from core.alerts.service import evaluate_run, project_rule_inputs
    journal_by_id = {event.event_id: event for event in journal}
    evaluated = set()
    # Publish each mission-time instant before evaluating it. Simultaneous vital
    # readings and supplemental facts must be visible together, while later
    # readings in this batch must not hide an intermediate trigger or recovery.
    ordered = sorted(new, key=lambda item: (item.measured_at, item.event_id.int))
    for at, observations in groupby(ordered, key=lambda item: item.measured_at):
        observations = list(observations)
        changed = {}
        for item in observations:
            data = item.payload
            if data['kind'] != 'measurement' or data['phase'] != 'inflight':
                continue
            astronaut = astronauts.get(data['astronaut_id'])
            habitat = habitats[(data['mission_id'], data['habitat_id'])]
            key = latest_key(data['run_id'], data['domain'], astronaut.pk if astronaut else None, habitat.pk, data['zone_id'], data['metric'])
            current = latest.get(key)
            if current is not None and not supersedes(item, current):
                continue
            if current is None:
                current = LatestMeasurement(run=runs[data['run_id']], domain=data['domain'], astronaut=astronaut, metric=metrics[data['metric']])
            value = data['value']
            current.habitat = habitat
            current.zone_id = data['zone_id']
            current.numeric_value = None if type(value) is bool else value
            current.boolean_value = value if type(value) is bool else None
            current.context = data['context']
            current.measured_at = item.measured_at
            current.source_event_id = item.event_id
            current.updated_at = timezone.now()
            latest[key] = current
            changed[key] = current
        creates = [row for row in changed.values() if row.pk is None]
        updates = [row for row in changed.values() if row.pk is not None]
        LatestMeasurement.objects.bulk_create(creates)
        if updates:
            LatestMeasurement.objects.bulk_update(updates, ['habitat', 'zone_id', 'numeric_value', 'boolean_value',
                                                            'context', 'measured_at', 'source_event', 'updated_at'])
        # Keep environment and independent facts on the same timeline as values.
        # Already-stored future values are never rewound for a late history batch.
        group_runs = {}
        inflight_runs = set()
        for item in observations:
            data = item.payload
            group_runs[data['run_id']] = item
            if data['kind'] == 'measurement' and data['phase'] == 'inflight':
                inflight_runs.add(data['run_id'])
        for run_id, item in group_runs.items():
            run = runs[run_id]
            if run_id not in previous_times or at >= previous_times[run_id]:
                if run.environment != item.payload['environment']:
                    run.environment = item.payload['environment']
                    run.save(update_fields=['environment'])
        project_rule_inputs([journal_by_id[item.event_id] for item in observations])
        for run_id in sorted(inflight_runs):
            if run_id not in previous_times or at >= previous_times[run_id]:
                evaluate_run(runs[run_id])
                evaluated.add(run_id)
    # A late-only batch can complete historical coverage or add a preflight
    # reference. Reassess the current state without replaying old transitions.
    for run_id in sorted(set(runs) - evaluated):
        evaluate_run(runs[run_id])
    return {'accepted_event_ids': [str(i.event_id) for i in items], 'created_count': len(new), 'duplicate_count': len(items)-len(new)}
