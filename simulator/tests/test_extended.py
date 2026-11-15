"""Workbook completeness, plausible types and deterministic hourly fixtures."""
import json
import unittest
from pathlib import Path
from space_sim.contracts import CATALOGUE, validate_event
from space_sim.extra import SPECS, INTERVAL
from space_sim.model import Engine, Config


class ExtendedMeasurementTests(unittest.TestCase):
    def test_every_workbook_indicator_has_a_generated_measurement(self):
        coverage=json.loads((Path(__file__).parents[1]/'schemas/workbook-coverage.json').read_text())
        self.assertEqual(len(coverage['indicators']),83)
        self.assertEqual(len(SPECS),62)
        engine=Engine(Config(astronauts=1));events=engine.preflight_events()+engine.initial_events()
        metrics={e['metric'] for e in events if e['kind']=='measurement'}
        self.assertTrue({item['metric'] for item in coverage['indicators']}<=metrics)
        self.assertEqual(metrics,set(CATALOGUE))
        for event in events:validate_event(event)

    def test_structured_results_are_logical_and_not_fake_numeric_codes(self):
        engine=Engine(Config(astronauts=1));events=engine.initial_events()
        readings={e['metric']:e for e in events}
        self.assertIsInstance(readings['jugular_flow']['value'],str)
        self.assertIs(type(readings['flank_pain']['value']),bool)
        urine=readings['urine_sg_ph']['value']
        self.assertTrue(1.005<=urine['specific_gravity']<=1.025);self.assertTrue(4.5<=urine['ph']<=8)
        medication=readings['medication_log']['value']
        self.assertEqual(medication['item']=='none',not medication['taken'])
        self.assertTrue(all(e['context'].get('synthetic_random') for e in events if e['metric'] in SPECS))

    def test_hourly_cadence_and_checkpoint_restart(self):
        engine=Engine(Config(astronauts=1));engine.initial_events()
        self.assertFalse(any(e['metric'] in SPECS for e in engine.advance(INTERVAL-1)))
        restored=Engine(engine.config,json.loads(json.dumps(engine.snapshot())))
        expected=engine.advance(1);actual=restored.advance(1)
        self.assertEqual(sum(e['metric'] in SPECS for e in actual),len(SPECS))
        self.assertEqual([{k:v for k,v in e.items() if k!='emitted_at'} for e in actual],
                         [{k:v for k,v in e.items() if k!='emitted_at'} for e in expected])

    def test_old_checkpoint_starts_new_measurements_without_reset(self):
        engine=Engine(Config(astronauts=1));engine.initial_events();engine.advance(30)
        engine.state.pop('next_extra')
        restored=Engine(engine.config,json.loads(json.dumps(engine.snapshot())))
        self.assertTrue(any(e['metric'] in SPECS for e in restored.advance(30)))

    def test_wrong_structured_and_categorical_types_are_rejected(self):
        events=Engine(Config(astronauts=1)).initial_events()
        for code,value in [('jugular_flow',1),('urine_sg_ph',3),('urine_colour','purple'),
                           ('headache',True),('flank_pain',0),('skin',{})]:
            event=next(e for e in events if e['metric']==code)
            event['value']=value
            with self.subTest(code=code),self.assertRaises(ValueError):validate_event(event)
