"""Independent plausible workbook fixtures, without physiology or activity coupling."""
import hashlib
import json
import math
from pathlib import Path
import random

SPECS=json.loads(Path(__file__).with_name('additional_metrics.json').read_text())
INTERVAL=3600.


def sample(spec,rng):
    if 'fields' in spec:return {key:sample(field,rng) for key,field in spec['fields'].items()}
    if 'choices' in spec:return rng.choice(spec['choices'])
    if spec.get('type')=='boolean':return rng.random()<.05
    low,high=spec['range']
    return rng.randint(int(low),int(high)) if spec.get('integer') else round(rng.uniform(low,high),4)


def validate_value(code,value):
    def check(spec,value):
        kind=spec.get('type','numeric')
        if 'fields' in spec:
            if not isinstance(value,dict) or set(value)!=set(spec['fields']):return False
            return all(check(field,value[key]) for key,field in spec['fields'].items())
        if 'choices' in spec:return any(type(value) is type(choice) and value==choice for choice in spec['choices'])
        if kind=='boolean':return type(value) is bool
        return type(value) in (int,float) and math.isfinite(value) and value>=0 and (not spec.get('integer') or type(value) is int)
    if not check(SPECS[code],value):raise ValueError(f'Invalid typed value for {code}')


def generate(engine):
    events=[];seconds=engine.state['seconds']
    for code,spec in SPECS.items():
        subjects=[None] if spec['domain']=='cabin' else engine.state['crew']
        for person in subjects:
            key=f"{engine.config.seed}/{engine.config.start}/{seconds}/{code}/{person['id'] if person else 'cabin'}"
            rng=random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(),'big'))
            value=sample(spec,rng)
            if code=='medication_log':value['item']='synthetic_medication_A' if value['taken'] else 'none'
            if code=='pain_injury':value['location']='none' if value['severity']==0 else rng.choice(['back','shoulder','knee','hand'])
            context={'synthetic_random':True,'surface_body':engine.config.surface_body,'generation':'independent_workbook_fixture',
                     'workbook_id':code,'clinical_context_modelled':False}
            if code=='news2':context['note']='Random reported score fixture; not the calculated alert-engine NEWS2.'
            events.append(engine.event(code,value,seconds,person,context=context))
    return events
