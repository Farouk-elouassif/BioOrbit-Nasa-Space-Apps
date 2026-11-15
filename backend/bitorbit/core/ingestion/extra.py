"""Typed supplementary measurement definitions; independent of simulator runtime."""
import json
import math
from pathlib import Path

SPECS=json.loads(Path(__file__).with_name("additional_metrics.json").read_text())


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

