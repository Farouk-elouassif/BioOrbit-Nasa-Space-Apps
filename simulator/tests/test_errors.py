"""Percentage selection, replay stability and saved-volume configuration."""
import json
import tempfile
import unittest
from pathlib import Path
from space_sim.model import Config, Engine
from space_sim.container import prepare
from space_sim.storage import Store
from space_sim.contracts import validate_event


class ErrorLevelTests(unittest.TestCase):
    def test_percentage_limits_and_preflight_exclusion(self):
        for value in (-1,101,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):Config(error_level=value).validate()
        for level in (0,100):
            engine=Engine(Config(error_level=level,astronauts=1))
            preflight=engine.preflight_events()
            self.assertTrue(all('error_injection' not in e['context'] for e in preflight))
            events=engine.initial_events()+engine.advance(300)
            for event in events:
                validate_event(event)
                if level==0:self.assertNotIn('error_injection',event['context'])
                else:self.assertTrue(event['context']['error_injection']['selected'])

    def test_twenty_percent_selection_and_restart_reproducibility(self):
        engine=Engine(Config(error_level=20,astronauts=3))
        engine.preflight_events();engine.initial_events()
        restored=Engine(engine.config,json.loads(json.dumps(engine.snapshot())))
        events=[];replayed=[]
        for _ in range(120):
            events.extend(engine.advance(30));replayed.extend(restored.advance(30))
        selected=[e['context']['error_injection']['selected'] for e in events]
        self.assertGreater(sum(selected)/len(selected),.17)
        self.assertLess(sum(selected)/len(selected),.23)
        self.assertEqual(selected,[e['context']['error_injection']['selected'] for e in replayed])
        self.assertEqual([e['value'] for e in events],[e['value'] for e in replayed])

    def test_compose_setting_updates_saved_run_without_resetting_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'state.sqlite3')
            env={'SIM_HISTORY_DAYS':'0','SIM_PREFLIGHT_DAYS':'2','SIM_ERROR_LEVEL':'0'}
            try:
                prepare(store,env);count=store.count();run=store.load().config.run_id
                prepare(store,{**env,'SIM_ERROR_LEVEL':'20'})
                self.assertEqual(store.load().config.error_level,20)
                self.assertEqual(store.count(),count);self.assertEqual(store.load().config.run_id,run)
                with self.assertRaises(ValueError):prepare(store,{**env,'SIM_ERROR_LEVEL':'101'})
                self.assertEqual(store.load().config.error_level,20)
                prepare(store,env);self.assertEqual(store.load().config.error_level,0)
            finally:store.close()
