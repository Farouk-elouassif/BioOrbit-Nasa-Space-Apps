import json
from pathlib import Path

WORKBOOK=json.loads(Path(__file__).with_name('workbook.json').read_text())
PARAMETERS={row['id']:row for row in WORKBOOK['parameters']}
TIERS=['advisory','caution','warning','emergency']
RANK={tier:i+1 for i,tier in enumerate(TIERS)}
COLORS={'advisory':'blue','caution':'amber','warning':'orange','emergency':'red'}
REGIONS={'Brain and mind':0,'Eyes':1,'Ears and balance':2,'Heart and circulation':3,'Lungs and breathing':4,
         'Blood and immune':5,'Stomach and nutrition':6,'Kidneys and bladder':7,'Muscles and joints':8,'Skin':9,'Bones':10,'Whole body and exposure':11}
# Collection intervals come from Parameters!H; continuous streams need a technical gap tolerance.
COLLECTION_SECONDS={'systolic_blood_pressure':604800,'diastolic_blood_pressure':604800,'body_temperature':604800,
    'blood_glucose':86400,'sleep_duration':86400,'mood':86400,'stress_level':86400,'body_mass':604800,'fluid_intake':86400}
