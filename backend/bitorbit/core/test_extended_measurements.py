"""Typed workbook values round-trip through the journal and current-state API."""
import json
from pathlib import Path
from uuid import uuid4
from django.test import SimpleTestCase, TestCase
from django.db import IntegrityError, transaction
from .ingestion.catalogue import CATALOGUE, metric_spec
from .ingestion.extra import SPECS
from .ingestion.validation import validate_payload, IngestionError
from .ingestion.service import ingest
from .queries.dashboard import dashboard,trends,ReadError
from .models import MeasurementEvent, LatestMeasurement, MetricCatalog
from .test_ingestion import observation


class ExtendedContractTests(SimpleTestCase):
    def test_service_catalogues_and_definitions_agree(self):
        simulator=Path(__file__).resolve().parents[3]/'simulator/space_sim/additional_metrics.json'
        self.assertEqual(SPECS,json.loads(simulator.read_text()))
        self.assertEqual(len(CATALOGUE),88)
        self.assertEqual(metric_spec('jugular_flow')['value_type'],'categorical')
        self.assertEqual(metric_spec('urine_sg_ph')['value_type'],'structured')

    def test_types_are_checked_before_database_writes(self):
        for code,value in [('jugular_flow',3),('urine_colour','purple'),('flank_pain',1),('urine_sg_ph',{'ph':7})]:
            event=observation(metric=code,unit=CATALOGUE[code][0],value=value)
            with self.subTest(code=code),self.assertRaises(IngestionError):validate_payload(event)


class ExtendedStorageTests(TestCase):
    def send(self,code,value):
        event=observation(metric=code,unit=CATALOGUE[code][0],value=value,
                          context={'activity':'resting','synthetic_random':True})
        ingest(validate_payload(event));return event

    def test_complete_simulator_workbook_batch_is_stored_and_updates(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'simulator'))
        from space_sim.model import Engine,Config
        engine=Engine(Config(astronauts=1,preflight_days=2,run_id='expanded-workbook'))
        events=engine.preflight_events()+engine.initial_events()
        result=ingest(validate_payload({'schema_version':'1.0','events':events}))
        self.assertEqual(result['created_count'],len(events))
        self.assertEqual(set(MetricCatalog.objects.values_list('code',flat=True)),set(CATALOGUE))
        snapshot=dashboard({'run_id':'expanded-workbook'})
        self.assertIsInstance(snapshot['crew'][0]['measurements']['urine_sg_ph']['value'],dict)
        # Clinical facts from the established simulator context still exist, while
        # independent random results do not manufacture a consciousness Emergency.
        from .models import LatestRuleInput,MonitoringAlert
        self.assertTrue(LatestRuleInput.objects.filter(run_id='expanded-workbook',code='consciousness',value='alert').exists())
        self.assertFalse(MonitoringAlert.objects.filter(run_id='expanded-workbook',rule_code='consciousness',is_active=True).exists())
        later=engine.advance(3600)
        ingest(validate_payload({'schema_version':'1.0','events':later}))
        latest=LatestMeasurement.objects.get(run_id='expanded-workbook',metric_id='urine_sg_ph')
        event=next(e for e in later if e['metric']=='urine_sg_ph')
        self.assertEqual(latest.json_value,event['value'])

    def test_all_value_types_round_trip_and_replay(self):
        values={'hrv':55.,'flank_pain':False,'jugular_flow':'normal',
                'urine_sg_ph':{'specific_gravity':1.015,'ph':6.5}}
        for code,value in values.items():
            event=self.send(code,value)
            self.assertEqual(MeasurementEvent.objects.get(pk=event['event_id']).raw_payload['value'],value)
            self.assertEqual(ingest(validate_payload(event))['created_count'],0)
        snapshot=dashboard({})
        for code,value in values.items():self.assertEqual(snapshot['crew'][0]['measurements'][code]['value'],value)
        self.assertEqual(MetricCatalog.objects.get(pk='jugular_flow').value_type,'categorical')
        with self.assertRaises(ReadError):trends({'metric':'jugular_flow','astronaut_id':'AST_001'})

    def test_new_values_cannot_occupy_numeric_and_json_columns_together(self):
        event=self.send('jugular_flow','normal')
        with self.assertRaises(IntegrityError),transaction.atomic():
            LatestMeasurement.objects.filter(metric_id='jugular_flow').update(numeric_value=1)
        with self.assertRaises(IntegrityError),transaction.atomic():
            MeasurementEvent.objects.filter(pk=event['event_id']).update(boolean_value=False)

    def test_random_consciousness_does_not_override_real_rule_input(self):
        event=observation(context={'activity':'resting','rule_inputs':{'consciousness':{'value':'alert'}}})
        ingest(validate_payload(event))
        self.send('consciousness','unresponsive')
        from .alerts.service import frame_from_rows
        from .models import SimulationRun
        run=SimulationRun.objects.get(pk=event['run_id'])
        rows=list(LatestMeasurement.objects.filter(run=run).select_related('source_event'))
        f=frame_from_rows(run,rows,max(r.measured_at for r in rows),min(r.measured_at for r in rows),person=rows[0].astronaut_id)
        self.assertEqual(f.point('consciousness',300).value,'alert')
