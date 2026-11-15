"""Evaluate rules in the ingestion transaction, serialized by its existing run locks."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import math
import statistics

from django.db.models import Min
from django.core.cache import cache

from core.ingestion.catalogue import CATALOGUE,canonical_metric
from core.models import AlertAssessment,LatestMeasurement,MeasurementEvent,MonitoringAlert,PreflightProfile
from .engine import DAY,Frame,Point,evaluate,patterns,valid
from .spec import COLLECTION_SECONDS,COLORS,PARAMETERS,RANK,REGIONS,TIERS,WORKBOOK

NUMERIC_INPUTS={'hours_awake','noaa_s_level','projected_event_dose_msv','headache','pain_injury','reaction_ms',
 'serum_calcium','sodium','potassium','platelets','etco2','creatinine','urine_volume','water_supply','urine_sg_ph',
 'vitamin_d','oct_rnfl','rad_bfo','motion_sickness','eva_hr','eva_core_temp','fitness','strength','urinary_calcium'}
ENUM_INPUTS={'consciousness':{'alert','new_confusion','new confusion','voice','pain','unresponsive'},'urine_colour':{'pale','yellow','dark'}}
EXTRA_UNITS={'hours_awake':'hours','noaa_s_level':'S-level','projected_event_dose_msv':'mSv'}
PATTERN_SOURCE={'pattern_cabin_first':'cabin_co2','pattern_shared_cause':'cabin_co2','pattern_fatigue':'sleep_hours',
 'pattern_stone_risk':'fluid_intake','pattern_eye_change':'vision_change','pattern_smoke_toxic':'spco',
 'pattern_after_eva':'dcs','pattern_solar_storm':'solar_storm','pattern_deconditioning':'fitness',
 'acute_symptoms':'consciousness','wbc_infection':'wbc','wbc_radiation':'wbc'}


def extract_inputs(context,at,identity):
    result={}
    inputs=context.get('rule_inputs',{})
    if not isinstance(inputs,dict):return result
    for code,entry in inputs.items():
        if not isinstance(code,str) or not isinstance(entry,dict) or 'value' not in entry:continue
        value=entry['value'];observed=at
        if code in CATALOGUE:continue  # Supplemental facts cannot override validated measurement columns.
        if code in NUMERIC_INPUTS and type(value) not in (int,float):continue
        if code in ENUM_INPUTS and (not isinstance(value,str) or value not in ENUM_INPUTS[code]):continue
        if code not in NUMERIC_INPUTS and code not in ENUM_INPUTS and type(value) is not bool:continue
        if entry.get('observed_at'):
            try:
                observed=datetime.fromisoformat(entry['observed_at'].replace('Z','+00:00'))
                if observed.tzinfo is None or observed.utcoffset()!=timedelta(0) or observed>at:continue
            except (ValueError,TypeError,AttributeError):continue
        expected=EXTRA_UNITS.get(code) or PARAMETERS.get(code,{}).get('unit')
        if type(value) in (int,float):
            try:
                if not math.isfinite(value) or value<0:continue
            except OverflowError:continue
            if expected is None or entry.get('unit')!=expected:continue
        if type(value) not in (int,float,bool,str):continue
        tags={**context,**entry.get('context',{})} if isinstance(entry.get('context',{}),dict) else dict(context)
        tags.pop('rule_inputs',None)
        result[code]=Point(value,observed,str(identity),tags)
    return result


class History:
    def __init__(self,run,person=None,habitat=None,zone=None):
        self.run,self.person,self.habitat,self.zone=run,person,habitat,zone
    def __call__(self,code,start,end):
        query=MeasurementEvent.objects.filter(run=self.run,kind='measurement',phase='inflight',measured_at__gte=start,measured_at__lte=end)
        if self.person is not None:query=query.filter(domain='astronaut',astronaut_id=self.person)
        else:query=query.filter(domain='cabin',habitat_id=self.habitat,zone_id=self.zone)
        direct=code in CATALOGUE
        if direct:query=query.filter(metric_id=code)
        else:query=query.filter(context__rule_inputs__has_key=code)
        points=[];seen=set()
        for row in query.order_by('measured_at','event_id').values('numeric_value','boolean_value','measured_at','event_id','context','raw_payload'):
            context={**row['context'],'_source':row['raw_payload'].get('source')}
            if direct:
                point=Point(row['boolean_value'] if row['boolean_value'] is not None else row['numeric_value'],row['measured_at'],str(row['event_id']),context)
            else:point=extract_inputs(context,row['measured_at'],row['event_id']).get(code)
            if point and (point.at,point.event_id) not in seen:
                seen.add((point.at,point.event_id));points.append(point)
        return points


def references(profile,run,person,anchor):
    result={};inflight={}
    if profile:
        key=f'alert-baselines:{run.pk}:{person}:{profile.source_event_id}'
        result=cache.get(key)
        if result is None:
            result={}
            for baseline in profile.baselines.all():
                samples=list(MeasurementEvent.objects.filter(run=run,astronaut_id=person,phase='preflight',metric_id=baseline.metric_id,numeric_value__isnull=False).values_list('numeric_value',flat=True))
                result[baseline.metric_id]={'mean':baseline.mean,'median':statistics.median(samples) if samples else None,
                                          'stddev':baseline.stddev,'min':baseline.min_value,'max':baseline.max_value}
            cache.set(key,result,300)
    history=History(run,person=person)
    for code in ('body_temperature','systolic_blood_pressure'):
        samples=[p for p in history(code,anchor-timedelta(days=7),anchor-timedelta(days=1)) if valid(p) and p.context.get('activity') in ('resting','sleeping')]
        if len(samples)>=20 and (samples[-1].at-samples[0].at).total_seconds()>=DAY:
            values=[p.value for p in samples];median=statistics.median(values)
            deviations=[abs(v-median) for v in values];spread=statistics.median(deviations)
            trimmed=[v for v in values if abs(v-median)<=max(3*spread,.1 if code=='body_temperature' else 1)]
            inflight[code]={'mean':statistics.mean(trimmed),'min':min(trimmed),'max':max(trimmed),'median':median}
    return result,inflight


def frame_from_rows(run,rows,anchor,start,baselines=None,inflight=None,person=None,habitat=None,zone=None):
    latest={}
    for row in sorted(rows,key=lambda r:r.measured_at):
        context={**row.context,'_source':row.source_event.raw_payload.get('source')}
        latest[row.metric_id]=Point(row.boolean_value if row.boolean_value is not None else row.numeric_value,row.measured_at,str(row.source_event_id),context)
        for code,point in extract_inputs(context,row.measured_at,row.source_event_id).items():
            if code not in latest or point.at>=latest[code].at:latest[code]=point
    return Frame(anchor,latest,History(run,person,habitat,zone),baselines,inflight,run.environment,start,'astronaut' if person is not None else 'cabin')


def recheck_seconds(rule,tier):
    if tier=='emergency':return 0
    if rule=='glucose' and tier=='caution':return 900
    if tier in ('caution','warning'):return 3600
    return DAY if rule in ('sleep_hours','mood','stress','fluid_intake','body_mass','pattern_fatigue','pattern_deconditioning') else 14400


def persist(run,key,domain,frame,astronaut=None,habitat=None,zone=''):
    existing={a.rule_code:a for a in MonitoringAlert.objects.filter(run=run,subject_key=key)}
    for code,decision in frame.decisions.items():
        if domain=='astronaut' and code in ('cabin_co2','cabin_o2','cabin_pressure','cabin_temp','cabin_humidity','noise','dust'):continue
        active=existing.get(code);tier=decision['tier'];at=decision['observed_at']
        if not tier and (not active or not active.is_active or decision['state']!='normal'):continue
        if active and at<active.last_observation_at:continue
        source=PARAMETERS.get('heart_rate' if code=='acute_symptoms' and decision.get('evidence',{}).get('symptom')=='chest_pain' else PATTERN_SOURCE.get(code,code),{})
        if tier:
            if not active:active=MonitoringAlert(run=run,subject_key=key,rule_code=code,domain=domain,
                astronaut_id=astronaut,habitat_id=habitat,zone_id=zone,detected_at=at,last_observation_at=at,recheck_due_at=at)
            renewed=not active.pk or not active.is_active
            old_tier=active.tier if active.pk else None
            if renewed:active.detected_at=at;active.resolved_at=None
            if renewed or RANK[tier]>RANK.get(old_tier,0):
                active.acknowledged_at=None;active.acknowledged_for_at=None
            if renewed or RANK[tier]>=RANK.get(active.tier,0):active.tier=tier
            active.is_active=True;active.normal_count=0
            active.message=decision['message'];active.evidence={**decision['evidence'],'candidate_tier':tier}
            if active.tier!=tier:active.evidence['held_until_three_normal_readings']=True
            if renewed or old_tier!=active.tier or at>=active.recheck_due_at:
                active.recheck_due_at=at+timedelta(seconds=recheck_seconds(code,active.tier))
        else:
            if at<=active.last_observation_at:continue
            active.normal_count+=1
            if active.normal_count>=3:
                rank=RANK[active.tier]
                active.normal_count=0
                if rank==1:active.is_active=False;active.resolved_at=at
                else:active.tier=TIERS[rank-2]
                active.message=f'{code}: three normal observations; '+('resolved' if not active.is_active else f'stepped down to {active.tier}')
                active.evidence=decision['evidence']
                active.recheck_due_at=at+timedelta(seconds=recheck_seconds(code,active.tier))
        active.last_observation_at=at
        active.region_index=REGIONS.get(source.get('body_region'))
        active.actions=[source['actions']] if source.get('actions') else ['Check the environment and follow the approved mission medical checklist.']
        active.recipients=source.get('recipients','Crew medical officer; follow the mission escalation procedure')
        active.provenance={'version':WORKBOOK['version'],'sheet_row':source.get('sheet_row'),'basis':source.get('basis'),
                           'source':source.get('source'),'prototype':True,'sha256':WORKBOOK['sha256']}
        active.save()
    results=frame.decisions
    news=results.get('news2',{})
    coverage={'version':WORKBOOK['version'],'prototype':True,
              'evaluated_rules':sum(d['state'] in ('normal','triggered') for d in results.values()),
              'insufficient_data':[code for code,d in results.items() if d['state']=='insufficient_data'],
              'pending':{code:d['missing'] for code,d in results.items() if d['state']=='pending'},
              'news2':{'state':news.get('state'),'missing':news.get('missing',[]),'evidence':news.get('evidence',{})}}
    AlertAssessment.objects.update_or_create(run=run,subject_key=key,defaults={'evaluated_at':frame.anchor,'coverage':coverage})


def evaluate_run(run):
    rows=list(LatestMeasurement.objects.filter(run=run).select_related('source_event'))
    if not rows:return
    anchor=max(row.measured_at for row in rows)
    start=MeasurementEvent.objects.filter(run=run,phase='inflight').aggregate(start=Min('measured_at'))['start']
    people=defaultdict(list);cabins=defaultdict(list)
    for row in rows:
        if row.domain=='astronaut':people[row.astronaut_id].append(row)
        else:cabins[(row.habitat_id,row.zone_id)].append(row)
    cabin_frames={key:frame_from_rows(run,group,anchor,start,habitat=key[0],zone=key[1]) for key,group in cabins.items()}
    for f in cabin_frames.values():evaluate(f)
    profiles={p.astronaut_id:p for p in PreflightProfile.objects.filter(run=run).prefetch_related('baselines')}
    frames={};locations={}
    for person,group in people.items():
        baseline,inflight=references(profiles.get(person),run,person,anchor)
        frame=frame_from_rows(run,group,anchor,start,baseline,inflight,person=person)
        latest=max(group,key=lambda r:r.measured_at);location=(latest.habitat_id,latest.zone_id)
        frame.cabin=cabin_frames.get(location)
        evaluate(frame);patterns(frame,frame.cabin)
        frames[person]=frame;locations[person]=location
    for key,frame in cabin_frames.items():
        symptoms=defaultdict(list)
        for person,pf in frames.items():
            if locations[person]!=key:continue
            for code in ('headache','nausea','vomiting','dizziness','breathlessness'):
                point=pf.point(code,DAY)
                if point and (point.value is True or type(point.value) in (int,float) and point.value>0):symptoms[code].append(person)
        shared=next(((code,actors) for code,actors in symptoms.items() if len(set(actors))>=2),None)
        if shared:frame.decide('pattern_shared_cause','warning','Same symptom in at least two co-located crew within 24h; review shared environment',point=frame.point('co2_partial_pressure'),evidence={'symptom':shared[0],'astronaut_ids':shared[1]})
        persist(run,f'cabin:{key[0]}:{key[1]}','cabin',frame,habitat=key[0],zone=key[1])
    for person,frame in frames.items():
        location=locations[person]
        persist(run,f'astronaut:{person}','astronaut',frame,astronaut=person,habitat=location[0],zone=location[1])
