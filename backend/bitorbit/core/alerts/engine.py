"""Explicit workbook rules; missing observations never become normal readings."""
from dataclasses import dataclass,field
from datetime import timedelta
import math
import statistics

from core.ingestion.catalogue import canonical_metric
from .spec import PARAMETERS,REGIONS

DAY=86400


@dataclass
class Point:
    value: object
    at: object
    event_id: str
    context: dict=field(default_factory=dict)


def valid(point):
    if point is None:return False
    c=point.context
    if c.get('sensor_fault') or c.get('motion_artefact') or c.get('perfusion_ok') is False:return False
    if c.get('signal_quality') in ('bad','poor','invalid','fault'):return False
    return not isinstance(point.value,float) or math.isfinite(point.value)


def average(points,start,end,max_gap=900,logarithmic=False):
    """Time-weighted zero-order hold with full coverage and explicit gap rejection."""
    ordered=sorted((p for p in points if p.at<=end),key=lambda p:p.at)
    before=[p for p in ordered if p.at<=start]
    if not before:return None
    samples=[before[-1]]+[p for p in ordered if p.at>start]
    if (start-samples[0].at).total_seconds()>max_gap:return None
    total=0.
    for i,p in enumerate(samples):
        finish=samples[i+1].at if i+1<len(samples) else end
        seconds=(finish-max(start,p.at)).total_seconds()
        if not valid(p) or type(p.value) not in (int,float) or (finish-p.at).total_seconds()>max_gap:return None
        total+=(10**(p.value/10) if logarithmic else p.value)*max(0,seconds)
    duration=(end-start).total_seconds()
    if duration<=0:return None
    result=total/duration
    return 10*math.log10(result) if logarithmic and result>0 else result


def sustained(points,start,end,predicate,max_gap=60):
    ordered=sorted((p for p in points if p.at<=end),key=lambda p:p.at)
    before=[p for p in ordered if p.at<=start]
    if not before:return None
    samples=[before[-1]]+[p for p in ordered if p.at>start]
    for i,p in enumerate(samples):
        stop=samples[i+1].at if i+1<len(samples) else end
        if not valid(p) or (stop-p.at).total_seconds()>max_gap:return None
        if not predicate(p):return False
    return True


def band_score(metric,value,reference=None):
    if metric in ('heart_rate','respiratory_rate','spo2','systolic_blood_pressure'):
        value=math.floor(value+.5)  # NEWS2 integer bands; keep the original value in evidence.
    if metric=='heart_rate':
        if value<=40 or value>=131:return 3
        if 41<=value<=50:return 0 if reference and reference['min']<=value<=reference['max'] else 1
        return 2 if value>=111 else 1 if value>=91 else 0
    if metric=='respiratory_rate':return 3 if value<=8 or value>=25 else 2 if value>=21 else 1 if value<12 else 0
    if metric=='spo2':return 3 if value<=91 else 2 if value<=93 else 1 if value<=95 else 0
    if metric=='systolic_blood_pressure':
        if value<=90 or value>=220:return 3
        if value<=100:return 2
        return (0 if reference and reference['min']<=value<=reference['max'] else 1) if value<=110 else 0
    if metric=='body_temperature':
        if value<=35:return 3
        if value>=39.1:return 2
        if value<36.1:return 1
        if reference:return 1 if value>=reference['mean']+1 else 0
        return None  # Space-adjusted scoring needs an actual in-flight reference.


class Frame:
    def __init__(self,anchor,latest,history,baselines=None,inflight_baseline=None,environment='transit_spacecraft',mission_start=None,domain='astronaut'):
        self.anchor,self.latest,self._history=anchor,latest,history
        self.baselines=baselines or {};self.inflight=inflight_baseline or {}
        self.environment,self.mission_start,self.domain=environment,mission_start,domain
        self.decisions={};self._cache={}
    def point(self,code,max_age=None):
        p=self.latest.get(code) or self.latest.get(canonical_metric(code,self.domain))
        if not valid(p):return None
        if max_age is not None and (self.anchor-p.at).total_seconds()>max_age:return None
        return p
    def history(self,code,seconds):
        key=(code,seconds)
        if key not in self._cache:self._cache[key]=self._history(canonical_metric(code,self.domain),self.anchor-timedelta(seconds=seconds),self.anchor)
        return self._cache[key]
    def mean(self,code,seconds,logarithmic=False):
        if self.point(code,900) is None:return None
        return average(self.history(code,seconds+900),self.anchor-timedelta(seconds=seconds),self.anchor,logarithmic=logarithmic)
    def daily(self,code,days,total=False):
        if self.point(code) is None:return None
        groups={};coverage={}
        for p in self.history(code,(days+2)*DAY):
            if not valid(p) or type(p.value) not in (int,float):continue
            if code=='sleep_duration' and self.mission_start and (p.at-self.mission_start).total_seconds()<DAY:continue
            if total:
                duration=p.context.get('interval_seconds')
                if duration is None and p.context.get('window')=='since_previous_fluid_summary' and p.context.get('_source')=='bioorbit-simulator':duration=21600
                if type(duration) not in (int,float) or duration<=0 or duration>DAY:continue
                begin=p.at-timedelta(seconds=duration)
                if self.mission_start and begin<self.mission_start:continue
                day=(p.at-timedelta(microseconds=1)).date()
                if begin.date()!=day:continue
                groups[day]=groups.get(day,0)+p.value
                coverage.setdefault(day,[]).append((begin,p.at))
            else:
                day=p.at.date()
                if day not in groups or p.at>groups[day].at:groups[day]=p
        dates=sorted(groups)
        if total:
            complete=[]
            for day in dates:
                intervals=sorted(coverage[day]);seconds=sum((end-start).total_seconds() for start,end in intervals)
                if day<self.anchor.date() and seconds==DAY and all(a[1]==b[0] for a,b in zip(intervals,intervals[1:])):complete.append(day)
            dates=complete
        if len(dates)<days:return None
        dates=dates[-days:]
        if any((b-a).days!=1 for a,b in zip(dates,dates[1:])) or (self.anchor.date()-dates[-1]).days>1:return None
        return [groups[d] if total else groups[d].value for d in dates]
    def decide(self,code,tier=None,message=None,*,state='normal',missing=None,evidence=None,point=None):
        p=point or self.point(code)
        if p is None and state=='normal':state='insufficient_data';missing=missing or [code]
        decision={'rule_code':code,'state':'triggered' if tier else state,'tier':tier,
                  'message':message or ('Within implemented workbook conditions' if state=='normal' else 'Required observations unavailable'),
                  'observed_at':p.at if p else self.anchor,'evidence':evidence or {},'missing':missing or []}
        self.decisions[code]=decision
        return decision
    def flag(self,name,max_age=3600):
        p=self.point(name,max_age)
        return p is not None and p.value is True


def evaluate(frame):
    f=frame
    scores={};score_points={}
    vital_ids={'heart_rate':'heart_rate','bp_systolic':'systolic_blood_pressure','resp_rate':'respiratory_rate','spo2':'spo2','core_temp':'body_temperature'}
    for rule,metric in vital_ids.items():
        p=f.point(metric,3600 if metric in ('systolic_blood_pressure','body_temperature') else 900)
        if p is None or type(p.value) not in (int,float) or p.value<=0:
            f.decide(rule,state='insufficient_data',missing=[metric]);continue
        if p.context.get('activity') not in ('resting','sleeping'):
            f.decide(rule,state='insufficient_data',missing=['resting observation'],point=p);continue
        reference=f.inflight.get(metric) if metric in ('body_temperature','systolic_blood_pressure') else f.baselines.get(metric)
        score=band_score(metric,p.value,reference)
        if score is None:
            f.decide(rule,state='insufficient_data',missing=['in-flight resting baseline'],point=p);continue
        drift=bool(metric=='heart_rate' and reference and reference.get('median') is not None and reference['stddev']>0 and abs(p.value-reference['median'])>=3*reference['stddev'])
        urgent=metric=='spo2' and p.value<=91 and f.flag('breathlessness')
        if (score or drift) and metric in ('heart_rate','spo2') and not urgent:
            seconds=300 if metric=='heart_rate' else 120
            held=sustained(f.history(metric,seconds+60),p.at-timedelta(seconds=seconds),p.at,
                           lambda sample:sample.context.get('activity') in ('resting','sleeping') and ((abs(sample.value-reference['median'])>=3*reference['stddev']) if drift and score==0 else (band_score(metric,sample.value,reference) or 0)>=score))
            if held is not True:
                f.decide(rule,state='pending',missing=[f'{seconds}s persistence with valid readings and gaps ≤60s'],point=p);continue
        scores[metric]=score;score_points[metric]=p
        tier='caution' if score==3 else 'advisory' if score or drift else None
        if metric=='spo2' and p.value<=91 and f.flag('breathlessness'):tier='emergency'
        elif metric=='respiratory_rate' and f.flag('breathlessness_at_rest'):tier='emergency'
        elif metric=='systolic_blood_pressure' and p.value<=90 and (f.flag('lightheadedness') or f.flag('fainting')):tier='warning'
        elif metric=='body_temperature' and p.value>=39.1 and f.flag('symptoms_present'):tier='warning'
        f.decide(rule,tier,f'{metric}: {p.value:g}; space-adjusted component score {score}',point=p,evidence={'value':p.value,'score':score,'baseline_drift':drift,'event_id':p.event_id})
    consciousness=f.point('consciousness',300)
    abnormal=consciousness is not None and consciousness.value in ('new_confusion','new confusion','voice','pain','unresponsive')
    f.decide('consciousness','emergency' if abnormal else None,point=consciousness,
             state='normal' if consciousness and consciousness.value=='alert' else 'insufficient_data')
    oxygen=f.point('supplemental_oxygen',300)
    required=set(vital_ids.values())
    coherent=len(score_points)==5 and (max(p.at for p in score_points.values())-min(p.at for p in score_points.values())).total_seconds()<=300
    if coherent and consciousness and oxygen and type(oxygen.value) is bool and consciousness.value in ('alert','new_confusion','new confusion','voice','pain','unresponsive'):
        total=sum(scores.values())+(3 if abnormal else 0)+(2 if oxygen.value else 0)
        tier='emergency' if total>=7 else 'warning' if total>=5 else 'caution' if 3 in scores.values() else 'advisory' if total else None
        f.decide('news2',tier,f'Space-adjusted NEWS2 prototype total {total}',point=max(score_points.values(),key=lambda p:p.at),evidence={'total':total,'components':scores,'supplemental_oxygen':oxygen.value,'consciousness':consciousness.value})
    else:f.decide('news2',state='insufficient_data',missing=sorted(required-set(scores))+(['consciousness'] if not consciousness else [])+(['supplemental_oxygen'] if not oxygen else [])+(['coherent spot-check within 5 minutes'] if not coherent else []))

    p=f.point('blood_glucose',24*3600)
    if p and p.context.get('meal_context')=='fasting':
        outside=p.context.get('meal_context')=='fasting' and (p.value<65 or p.value>110)
        f.decide('glucose','caution' if outside and any(f.flag(s) for s in ('sweating','shaking','confusion')) else 'advisory' if outside else None,
                 'Fasting glucose outside 65–110 mg/dL' if outside else None,point=p,evidence={'value':p.value,'meal_context':p.context.get('meal_context')})
    for code,metric,direction in [('sleep_hours','sleep_duration',-1),('mood','mood',-1),('stress','stress_level',1)]:
        p=f.point(metric,2*DAY);values=f.daily(metric,3);reference=f.baselines.get(metric)
        triggered=False
        if code=='sleep_hours':
            week=f.daily(metric,7)
            triggered=bool(values and all(v<6 for v in values)) or bool(week and statistics.mean(week)<6)
            awake=f.point('hours_awake',86400)
            triggered=triggered or bool(awake and awake.value>16)
            enough=values is not None or week is not None or awake is not None
        else:
            enough=values is not None and reference is not None and reference.get('median') is not None
            triggered=bool(enough and all(direction*(v-reference['median'])>=2 for v in values))
        tier='advisory' if triggered else None
        if triggered and code=='mood' and any(f.flag(s) for s in ('withdrawal','loss_of_appetite','loss_of_interest')):tier='caution'
        if triggered and code=='stress' and (f.decisions.get('sleep_hours',{}).get('tier') or f.decisions.get('mood',{}).get('tier')):tier='caution'
        f.decide(code,tier,f'{code}: workbook multi-day deviation rule',point=p,state='normal' if enough else 'insufficient_data',missing=[] if enough else ['consecutive daily observations / personal median'],evidence={'daily_values':values})
    fluid=f.daily('fluid_intake',3,total=True)
    f.decide('fluid_intake','advisory' if fluid and all(v<2 for v in fluid) else None,point=f.point('fluid_intake'),state='normal' if fluid else 'insufficient_data',missing=[] if fluid else ['three complete daily intake totals'],evidence={'daily_liters':fluid})
    p=f.point('body_mass',8*DAY);base=f.baselines.get('body_mass')
    if p and base:f.decide('body_mass','advisory' if p.value<=base['mean']*.95 else None,'Body mass at least 5% below preflight reference',point=p)
    p=f.point('total_career_radiation_dose',900)
    if p:f.decide('rad_cumulative','caution' if p.value>=450 else 'advisory' if p.value>=300 else None,f'Total career dose {p.value:g} mSv',point=p,evidence={'career_dose_msv':p.value,'reference_limit_msv':600})
    limit=.9 if f.environment in ('rover','surface_base') else 1.3
    metric='radiation_level' if 'radiation_level' in f.latest else 'personal_radiation_dose_rate'
    rate=f.mean(metric,DAY)
    f.decide('rad_rate','advisory' if rate is not None and rate>limit else None,f'24-hour mean rate compared with {limit:g} mSv/day design reference',point=f.point(metric),state='normal' if rate is not None else 'insufficient_data',missing=[] if rate is not None else ['24-hour dose-rate coverage'],evidence={'mean_msv_per_day':rate,'design_rate':limit})
    noaa=f.point('noaa_s_level',3600);projected=f.point('projected_event_dose_msv',3600)
    if noaa or projected:
        warning=(projected and projected.value>=200) or (f.flag('is_solar_storm') and (f.flag('nausea') or f.flag('vomiting')))
        caution=(noaa and noaa.value>=1) or (projected and projected.value>50)
        f.decide('solar_storm','warning' if warning else 'caution' if caution else None,'Solar-event severity from explicit NOAA/projection observations',point=projected or noaa)

    for code,metric,bounds,tier in [('cabin_temp','cabin_temperature',(18,27),'advisory'),('cabin_pressure','total_cabin_pressure',(34.5,103),'caution')]:
        p=f.point(metric,900)
        if p:
            level=tier if p.value<bounds[0] or p.value>bounds[1] else None
            if code=='cabin_pressure' and (p.context.get('rapid_pressure_loss') is True or f.flag('rapid_pressure_loss')):level='emergency'
            f.decide(code,level,f'{metric}: {p.value:g} outside {bounds[0]}–{bounds[1]}' if level else None,point=p)
    p=f.point('o2_partial_pressure',900)
    if p:
        mean=f.mean('o2_partial_pressure',3600)
        tier='emergency' if p.value<122 else 'caution' if mean is not None and mean<127 else 'advisory' if p.value<145 or p.value>155 else None
        f.decide('cabin_o2',tier,'Cabin oxygen target / one-hour floor / absolute floor',point=p,state='normal' if mean is not None else 'insufficient_data',missing=[] if mean is not None else ['one-hour oxygen coverage'],evidence={'value_mmhg':p.value,'hour_mean_mmhg':mean})
    p=f.point('co2_partial_pressure',900)
    if p:
        hour,week=f.mean('co2_partial_pressure',3600),f.mean('co2_partial_pressure',7*DAY)
        tier='warning' if hour is not None and hour>4.5 else 'caution' if hour is not None and hour>3 else 'advisory' if week is not None and week>=2.5 else None
        f.decide('cabin_co2',tier,'Cabin CO₂ duration-based exposure rule',point=p,state='normal' if hour is not None and week is not None else 'insufficient_data',missing=[] if week is not None else ['seven-day coverage for advisory'],evidence={'one_hour_mean_mmhg':hour,'seven_day_mean_mmhg':week})
    p=f.point('relative_humidity',900)
    if p:
        mean=f.mean('relative_humidity',3600)
        f.decide('cabin_humidity','advisory' if p.value>60 or (mean is not None and mean<25) else None,'Humidity: >60% or average <25% (prototype average window: 1 hour)',point=p,state='normal' if mean is not None else 'insufficient_data',evidence={'value_percent':p.value,'hour_mean_percent':mean,'assumption':'Workbook average duration unspecified; 1-hour prototype window'})
    p=f.point('noise_level',900)
    if p:
        sleeping=p.context.get('sleep_period')
        if sleeping is None:
            period=f.point('crew_sleep_period',900)
            if period is None:
                f.decide('noise',state='insufficient_data',missing=['explicit work/sleep exposure period'],point=p)
                sleeping=None
            else:sleeping=period.value if type(period.value) is bool else None
        mean=f.mean('noise_level',8*3600 if sleeping else 16*3600,logarithmic=True) if sleeping is not None else None
        f.decide('noise',('advisory' if mean>50 else None) if sleeping and mean is not None else ('caution' if mean>=72 else 'advisory' if mean>60 else None) if mean is not None else None,
                 'Energy-averaged cabin noise for sleep/work period',point=p,state='normal' if mean is not None else 'insufficient_data',missing=[] if mean is not None else ['complete 8h sleep or 16h work noise coverage'],evidence={'leq_dba':mean,'period':'sleep' if sleeping else 'work'})
    p=f.point('dust_concentration',900)
    if p and f.environment in ('rover','surface_base'):
        body=p.context.get('surface_body')
        if body in ('moon','mars'):f.decide('dust','caution' if p.value>(.3 if body=='moon' else .1) else None,'Surface dust threshold',point=p)
        else:f.decide('dust',state='insufficient_data',point=p,missing=['surface_body: moon or mars'])
    evaluate_additional(f)
    for code in PARAMETERS:
        if code not in f.decisions:f.decide(code,state='insufficient_data',missing=[code])
    return f.decisions


def evaluate_additional(f):
    """Optional workbook observations arrive as typed context.rule_inputs entries."""
    ranges={'serum_calcium':(2,2.6,'caution'),'sodium':(135,145,'advisory'),'potassium':(3.5,5,'advisory'),
            'platelets':(150,400,'advisory'),'etco2':(35,45,'caution')}
    for code,(lo,hi,tier) in ranges.items():
        p=f.point(code,DAY)
        if p and type(p.value) in (int,float):
            outside=p.value<lo or p.value>hi
            if code=='etco2':
                co2=f.point('co2_partial_pressure',900) or (getattr(f,'cabin',None).point('co2_partial_pressure',900) if getattr(f,'cabin',None) else None)
                if not co2 or co2.value>3:continue
            level=tier if outside else None
            if outside and code=='sodium' and f.flag('symptoms_present'):level='caution'
            if outside and code=='potassium' and f.flag('ecg_alarm'):level='caution'
            if outside and code=='platelets' and (f.flag('clot_risk') or f.flag('jugular_abnormal')):level='caution'
            f.decide(code,level,f'{code} outside {lo}–{hi}',point=p)
    thresholds={'creatinine':(lambda v:v>1.3,'caution'),'urine_volume':(lambda v:v<2.5,'advisory'),
                'water_supply':(lambda v:v<2.5,'advisory'),'urine_sg_ph':(lambda v:v>1.025,'advisory'),
                'vitamin_d':(lambda v:v<35,'advisory'),'oct_rnfl':(lambda v:v>19.4,'advisory'),
                'rad_bfo':(lambda v:v>=200,'warning'),'motion_sickness':(lambda v:v>=1,'advisory'),
                'eva_hr':(lambda v:v>=85,'advisory'),'eva_core_temp':(lambda v:v>=37.8,'advisory'),
                'fitness':(lambda v:v<80,'caution'),'strength':(lambda v:v<80,'caution')}
    for code,(condition,tier) in thresholds.items():
        p=f.point(code,DAY if code not in ('fitness','strength') else 35*DAY)
        if not p or type(p.value) not in (int,float):continue
        level=tier if condition(p.value) else None
        if code=='vitamin_d' and p.value<20:level='caution'
        if code=='oct_rnfl' and p.value>=55:level='caution'
        if code=='motion_sickness' and (p.value>=3 or f.flag('motion_sickness_past_72h')):level='caution'
        # These workbook rows contain mixed quantities; require an explicit interpretation.
        if code=='fitness' and p.context.get('quantity')!='percent_of_preflight':continue
        if code=='strength' and p.context.get('quantity')!='percent_of_baseline':continue
        if code=='rad_bfo' and p.context.get('window')!='30d':continue
        if code=='urine_sg_ph' and p.context.get('quantity')!='specific_gravity':continue
        f.decide(code,level,f'{code}: workbook numerical threshold',point=p,evidence={'value':p.value})
    # Strict booleans: an absent symptom is not treated as a negative observation.
    for code in ('flank_pain','vision_change','infection_signs','balance','amsler_acuity','dust_symptoms','ars_symptoms'):
        p=f.point(code,DAY)
        if p is None or type(p.value) is not bool:continue
        tier='caution' if code in ('flank_pain','infection_signs','amsler_acuity') else 'warning' if code=='ars_symptoms' else 'advisory'
        if code=='vision_change':
            if not f.mission_start or (f.anchor-f.mission_start).total_seconds()<=30*DAY:continue
            tier='caution'
        if code=='ars_symptoms' and not f.flag('after_solar_storm'):continue
        if code=='dust_symptoms' and not f.flag('within_24h_suit_removal'):continue
        if code=='flank_pain' and (f.flag('fever') or f.flag('cannot_urinate')):tier='warning'
        f.decide(code,tier if p.value else None,f'{code}: reported observation',point=p)
    headache=f.point('headache',DAY)
    if headache and type(headache.value) in (int,float):
        tier='emergency' if headache.value and f.flag('sudden_severe_headache') and f.flag('neurological_signs') else 'caution' if headache.value and f.flag('vision_change') else 'advisory' if headache.value else None
        f.decide('headache',tier,'Headache: review cabin context and associated symptoms',point=headache)
    pain=f.point('pain_injury',DAY)
    if pain and type(pain.value) in (int,float):f.decide('pain_injury','warning' if pain.value and f.flag('within_24h_eva') and (f.flag('tingling') or f.flag('skin_change')) else 'caution' if pain.value>=7 or f.flag('limiting_work') else 'advisory' if pain.value>0 else None,'Pain / injury report',point=pain)
    for flag in ('chest_pain','collapse','breathlessness_at_rest','new_confusion','neurological_signs'):
        if f.flag(flag):f.decide('acute_symptoms','emergency',f'Reported {flag.replace("_"," ")}',point=f.point(flag),evidence={'symptom':flag})
    signal_rules={
      'ecg_flag': [('ecg_alarm','caution'),('ecg_alarm_with_symptoms','warning'),('ecg_alarm_with_chest_pain_or_collapse','emergency')],
      'urinary_retention':[('painful_urination_with_fever','caution'),('cannot_urinate','warning')],
      'jugular_flow':[('jugular_abnormal','caution'),('thrombus','warning'),('thrombus_with_breathlessness','emergency')],
      'orthostatic':[('lightheadedness_on_standing','advisory'),('standing_systolic_le90','caution'),('fainting','warning')],
      'skin':[('new_skin_lesion','advisory'),('skin_infection_signs','caution')],
      'medication_log':[('medication_stock_below_plan','advisory')],
      'resistance_ex':[('missed_resistance_session','advisory')],
      'exercise_min':[('exercise_below_prescription','advisory')],
      'circadian':[('sleep_midpoint_drift','advisory'),('critical_task_bodyclock_low','advisory')],
      'suit_status':[('suit_outside_flight_rule','caution'),('suit_alarm','warning'),('suit_pressure_loss','emergency')],
      'dcs':[('dcs_type1_within24h','warning'),('dcs_type2_symptoms','emergency')],
      'combustion':[('combustion_above_smac','warning'),('smoke_or_fire','emergency')],
    }
    for rule,signals in signal_rules.items():
        present=[(name,tier,f.point(name,DAY)) for name,tier in signals if f.point(name,DAY) is not None]
        if not present:continue
        triggered=[(name,tier,p) for name,tier,p in present if p.value is True]
        picked=triggered[-1] if triggered else present[-1]
        f.decide(rule,picked[1] if triggered else None,f'{rule}: explicit observed signal {picked[0]}',point=picked[2])
    # Non-numeric prose ("sustained", "falling", etc.) is never given an invented cutoff.
    explicit={
      'hrv':'sustained_hrv_drop','sphb':'sustained_sphb_shift_ge2','hemoglobin':'hemoglobin_below_sex_reference',
      'hematocrit':'hematocrit_outside_inflight_band','ferritin':'ferritin_outside_sex_reference',
      'cortisol_dhea':'sustained_cortisol_ratio_rise','urinary_calcium':'urinary_calcium_rising',
      'ntx':'ntx_rising_despite_exercise','hearing':'hearing_shift_from_preflight',
      'reaction_ms':'reaction_slower_two_tests','cognition':'cognition_decline',
      'team_cohesion':'team_cohesion_decline_or_conflict','energy_intake':'seven_day_energy_below80percent',
      'workload':'repeated_workload_above_context_limit','bone_density':'postflight_bone_below_site_limit',
      'herpes_dna':'herpes_detected_with_symptoms','spco':'spco_rise_after_cabin_event','spmet':'spmet_rise_after_cabin_event',
    }
    for rule,signal in explicit.items():
        p=f.point(signal,DAY)
        if p is None or type(p.value) is not bool:continue
        tier='caution' if rule in ('hemoglobin','bone_density','herpes_dna','spco','spmet') else 'advisory'
        if rule in ('spco','spmet') and f.flag('cabin_event_last24h'):tier='warning'
        if rule=='urinary_calcium' and f.flag('flank_pain'):tier='caution'
        f.decide(rule,tier if p.value else None,'Source-supplied reviewed trend flag; no undocumented numerical cutoff inferred',point=p,evidence={'signal':signal})
    for rule,signal,tier in [('bp_diastolic','diastolic_drift_from_baseline','advisory'),
                             ('wbc','wbc_outside_reference','advisory'),
                             ('wbc_infection','wbc_abnormal_with_infection','caution'),
                             ('wbc_radiation','lymphocytes_falling_after_large_dose','warning')]:
        p=f.point(signal,DAY)
        if p is not None and type(p.value) is bool:f.decide(rule,tier if p.value else None,'Explicit reviewed observation supplied by source',point=p)
    p=f.point('urine_colour',DAY);fluid=f.daily('fluid_intake',1,total=True)
    if p and p.value in ('pale','yellow','dark') and fluid is not None:
        f.decide('urine_colour','advisory' if p.value=='dark' and fluid[-1]<2 else None,'Urine colour reviewed with complete daily fluid intake',point=p)
    perfusion=f.point('perfusion_index',3600)
    f.decide('perfusion_index',state='quality_gate',point=perfusion,missing=[] if perfusion else ['perfusion_index'],message='Signal-quality gate only; not a standalone medical alert')


def patterns(person,cabin=None):
    p=person;c=cabin
    if c:
        co2=c.mean('co2_partial_pressure',7*DAY)
        headache=p.point('headache',DAY);sleep=p.point('sleep_duration',2*DAY)
        if co2 is not None and co2>=2.5 and ((headache and type(headache.value) in (int,float) and headache.value>=1) or (sleep and sleep.value<6)):
            c.decide('pattern_cabin_first','advisory','Review habitat conditions before personal interpretation',point=c.point('co2_partial_pressure'),evidence={'seven_day_co2_mmhg':co2})
    sleep=p.daily('sleep_duration',3);reaction=p.point('reaction_ms',5*DAY);base=p.baselines.get('reaction_ms')
    slow=bool(reaction and base and reaction.value>base['mean']) or p.flag('reaction_slower_two_tests')
    if sleep is not None and slow:
        p.decide('pattern_fatigue','caution' if all(v<6 for v in sleep) else None,'Short sleep plus slower reaction; higher explicit Parameters tier takes precedence',point=p.point('sleep_duration'))
    fluids=p.daily('fluid_intake',1,total=True);urine=p.point('urine_volume',DAY);colour=p.point('urine_colour',DAY);calcium=p.point('urinary_calcium',35*DAY)
    if fluids is not None or urine:
        low=(fluids is not None and fluids[-1]<2) or bool(urine and urine.value<2.5)
        contributor=bool(colour and colour.value=='dark') or bool(calcium and calcium.value>300) or p.flag('urinary_calcium_rising')
        if contributor:p.decide('pattern_stone_risk','caution' if low and p.flag('flank_pain') else 'advisory' if low else None,'Hydration / urinary observation combination',point=p.point('fluid_intake') or urine)
    if p.mission_start and (p.anchor-p.mission_start).total_seconds()>30*DAY:
        point=p.point('vision_change',DAY) or p.point('amsler_acuity',DAY)
        if point:p.decide('pattern_eye_change','caution' if point.value is True else None,'Visual change after flight day 30',point=point)
    if p.flag('cabin_event_last24h'):
        for key in ('spco_rise_after_cabin_event','spmet_rise_after_cabin_event'):
            point=p.point(key,DAY)
            if point:p.decide('pattern_smoke_toxic','warning' if point.value is True else None,'Reported blood-gas change after cabin event',point=point)
    if p.flag('within_24h_eva',DAY):
        severe=any(p.flag(key) for key in ('numbness','weakness','new_confusion','breathing_trouble'))
        mild=any(p.flag(key) for key in ('joint_pain','tingling','skin_change'))
        if severe or mild:p.decide('pattern_after_eva','emergency' if severe else 'warning','Post-EVA symptoms require the matching approved checklist',point=p.point('within_24h_eva'))
    noaa=p.point('noaa_s_level',3600);projected=p.point('projected_event_dose_msv',3600)
    if noaa and noaa.value>=1 and p.flag('dose_rate_rising'):
        p.decide('pattern_solar_storm','warning' if projected and projected.value>=200 else 'caution','Rising dose rate and explicit NOAA space-weather alert',point=projected or noaa)
    fitness=p.point('fitness',35*DAY)
    if fitness and fitness.context.get('quantity')=='percent_of_preflight' and p.point('exercise_below_plan_7days',DAY):
        p.decide('pattern_deconditioning','caution' if fitness.value<80 and p.flag('exercise_below_plan_7days') else None,'Exercise plan adherence combined with fitness reference',point=fitness)
