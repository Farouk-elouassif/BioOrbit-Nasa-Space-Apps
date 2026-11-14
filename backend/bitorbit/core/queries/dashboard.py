"""Local crew dashboard; freshness is relative to simulated time, not wall time."""
from collections import defaultdict
from datetime import timedelta, timezone as datetime_timezone

from django.db.models import Avg, F, Max, Min, Sum, Window
from django.db.models.functions import RowNumber, TruncDay, TruncHour
from django.utils import timezone

from core.ingestion.catalogue import CATALOGUE, canonical_metric, metric_spec
from core.models import Astronaut, Habitat, LatestMeasurement, MeasurementEvent, PreflightProfile, SimulationRun


class ReadError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


# Missing/overdue data is a collection status, never a clinical alert.
STALE_AFTER = {
    'systolic_blood_pressure':10800, 'diastolic_blood_pressure':10800,
    'blood_glucose':43200, 'body_temperature':5400,
    'sleep_duration':172800, 'mood':172800, 'stress_level':64800, 'fluid_intake':64800,
}


def reading(row, anchor):
    age = max(0., (anchor-row.measured_at).total_seconds()) if anchor else None
    raw = row.source_event.raw_payload
    return {'metric':row.metric_id, 'value':row.boolean_value if row.boolean_value is not None else row.numeric_value,
            'unit':row.metric.unit, 'measured_at':row.measured_at, 'emitted_at':row.source_event.emitted_at,
            'received_at':row.source_event.received_at, 'event_id':str(row.source_event_id),
            'context':row.context, 'source':raw.get('source'), 'simulated':raw.get('simulated') is True,
            'age_simulated_seconds':age,
            'freshness':'overdue' if age is not None and age > STALE_AFTER.get(row.metric_id,900) else 'current'}


def choose_run(code=None):
    if code:
        if len(code)>100:
            raise ReadError('run_id is too long')
        run=SimulationRun.objects.select_related('mission').filter(run_id=code).first()
        if run is None:raise ReadError('Simulation run not found',404)
        return run
    return (SimulationRun.objects.select_related('mission')
            .order_by(F('is_active').desc(nulls_last=True),F('created_at').desc(nulls_last=True),'run_id').first())


def run_clock(run):
    times=MeasurementEvent.objects.filter(run=run,phase='inflight').aggregate(start=Min('measured_at'),latest=Max('measured_at'))
    return times['start'],times['latest']


def dashboard(params):
    runs=list(SimulationRun.objects.select_related('mission')
              .order_by(F('created_at').desc(nulls_last=True),'run_id')[:100])
    run=choose_run(params.get('run_id'))
    result={'schema_version':'1.0','generated_at':timezone.now(),
            'runs':[{'id':r.pk,'mission_code':r.mission.mission_code,'environment':r.environment,'is_active':r.is_active} for r in runs],
            'run':None,'crew':[],'habitats':[],'cabin':None,'alerts_available':False}
    if run is None:return result
    start,anchor=run_clock(run)
    rows=list(LatestMeasurement.objects.filter(run=run).select_related('metric','source_event','habitat'))
    if rows:anchor=max([r.measured_at for r in rows]+([anchor] if anchor else []))
    result['run']={'id':run.pk,'environment':run.environment,'mission_code':run.mission.mission_code,
                   'mission_name':run.mission.name or run.mission.mission_code,'started_at':start,
                   'observation_time':anchor,'mission_day':int((anchor-start).total_seconds()//86400)+1 if start and anchor else None}
    habitats=list(Habitat.objects.filter(measurement_events__run=run).distinct().order_by('habitat_code'))
    result['habitats']=[{'id':h.habitat_code,'name':h.name or h.habitat_code} for h in habitats]
    habitat_code=params.get('habitat_id')
    habitat=next((h for h in habitats if h.habitat_code==habitat_code),None) if habitat_code else (habitats[0] if habitats else None)
    if habitat_code and habitat is None:raise ReadError('Habitat not found in this run',404)
    by_person=defaultdict(dict)
    by_zone=defaultdict(dict)
    for row in rows:
        if row.domain=='astronaut':by_person[row.astronaut_id][row.metric_id]=reading(row,anchor)
        elif habitat and row.habitat_id==habitat.pk:by_zone[row.zone_id][row.metric_id]=reading(row,anchor)
    zone=params.get('zone_id') or ('CABIN_MAIN' if 'CABIN_MAIN' in by_zone else next(iter(sorted(by_zone)), 'CABIN_MAIN'))
    if params.get('zone_id') and zone not in by_zone:raise ReadError('Cabin zone has no readings in this run',404)
    if habitat:
        result['cabin']={'habitat_id':habitat.habitat_code,'name':habitat.name or habitat.habitat_code,
                         'zone_id':zone,'zones':sorted(by_zone),'measurements':by_zone.get(zone,{})}
    profiles={p.astronaut_id:p for p in PreflightProfile.objects.filter(run=run).prefetch_related('baselines')}
    # Actual run participants, not all historical assignments from earlier simulation runs.
    people=list(Astronaut.objects.filter(measurement_events__run=run).distinct().order_by('astronaut_code'))
    sparks=defaultdict(list)
    heart=(MeasurementEvent.objects.filter(run=run,phase='inflight',kind='measurement',metric_id='heart_rate')
           .annotate(sample_rank=Window(RowNumber(),partition_by=[F('astronaut_id')],order_by=[F('measured_at').desc(),F('event_id').desc()]))
           .filter(sample_rank__lte=24).values('astronaut_id','numeric_value','measured_at'))
    for sample in heart:
        sparks[sample['astronaut_id']].append({'value':sample['numeric_value'],'measured_at':sample['measured_at']})
    for person in people:
        readings=by_person.get(person.pk,{})
        latest=max((r for r in rows if r.astronaut_id==person.pk),key=lambda r:r.measured_at,default=None)
        profile=profiles.get(person.pk)
        baselines={b.metric_id:{'mean':b.mean,'stddev':b.stddev,'min':b.min_value,'max':b.max_value,'count':b.sample_count}
                   for b in profile.baselines.all()} if profile else {}
        result['crew'].append({'id':person.astronaut_code,'name':person.name or person.astronaut_code,
            'habitat_id':latest.habitat.habitat_code if latest else None,
            'zone_id':latest.zone_id if latest else None,'activity':latest.context.get('activity') if latest else None,
            'latest_at':latest.measured_at if latest else None,'measurements':readings,'baselines':baselines,
            'heart_rate_history':sorted(sparks[person.pk],key=lambda s:s['measured_at'])})
    return result


def trends(params):
    run=choose_run(params.get('run_id'))
    if run is None:raise ReadError('No simulation data yet',404)
    domain=params.get('domain','astronaut')
    metric=canonical_metric(params.get('metric',''),domain)
    if not isinstance(metric,str) or metric not in CATALOGUE or CATALOGUE[metric][1]!=domain:
        raise ReadError('Unknown metric or domain mismatch')
    if metric=='is_solar_storm':raise ReadError('Numeric trends are not available for boolean metrics')
    window=params.get('window','24h').lower()
    if window not in ('24h','7d','30d'):raise ReadError('window must be 24h, 7d, or 30d')
    _,anchor=run_clock(run)
    query=MeasurementEvent.objects.filter(run=run,phase='inflight',kind='measurement',metric_id=metric,domain=domain,numeric_value__isnull=False)
    if domain=='astronaut':
        code=params.get('astronaut_id')
        if not code:raise ReadError('astronaut_id is required')
        if not Astronaut.objects.filter(astronaut_code=code,measurement_events__run=run).exists():raise ReadError('Astronaut not found in this run',404)
        query=query.filter(astronaut__astronaut_code=code)
    else:
        code=params.get('habitat_id')
        if not code:raise ReadError('habitat_id is required')
        if not Habitat.objects.filter(habitat_code=code,measurement_events__run=run).exists():raise ReadError('Habitat not found in this run',404)
        query=query.filter(habitat__habitat_code=code)
        if params.get('zone_id'):query=query.filter(zone_id=params['zone_id'])
    aggregation=metric_spec(metric)['aggregation_kind']
    operation=Sum if aggregation=='interval_total' else Max if aggregation=='cumulative' else Avg
    truncation=TruncHour if window=='24h' else TruncDay
    points=[]
    if anchor:
        days=1 if window=='24h' else 7 if window=='7d' else 30
        query=query.filter(measured_at__gt=anchor-timedelta(days=days),measured_at__lte=anchor)
        from django.db.models import Count
        points=list(query.annotate(bucket=truncation('measured_at',tzinfo=datetime_timezone.utc)).values('bucket')
                    .annotate(value=operation('numeric_value'),count=Count('event_id'))
                    .order_by('bucket').values('bucket','value','count')[:100])
    return {'schema_version':'1.0','run_id':run.pk,'metric':metric,'domain':domain,'unit':CATALOGUE[metric][0],
            'window':window,'anchor_time':anchor,'aggregation':'sum' if operation==Sum else 'max' if operation==Max else 'mean',
            'source':'postgresql_measurement_events','points':points}
