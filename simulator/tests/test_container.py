"""Exercise the container entry command without invoking Docker."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from space_sim.container import main, prepare
from space_sim.storage import Store


class ContainerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'mission.sqlite3'
        self.env = {'SIM_STATE_PATH': str(self.path), 'SIM_HISTORY_DAYS': '.002',
                    'SIM_HISTORY_INTERVAL': '60', 'SIM_PREFLIGHT_DAYS': '2'}

    def tearDown(self):
        self.temp.cleanup()

    def test_bootstrap_backfills_once_and_preserves_live_progress(self):
        store = Store(self.path)
        try:
            self.assertTrue(prepare(store, self.env))
            before = store.count()
            self.assertAlmostEqual(store.load().state['seconds'], .002 * 86400)
            self.assertTrue(prepare(store, self.env))
            self.assertEqual(store.count(), before)
            store.advance(delta=300)
            dose = store.load().state['crew'][0]['mission_dose']
            before = store.count()
            prepare(store, self.env)
            self.assertEqual(store.count(), before)
            self.assertEqual(store.load().state['crew'][0]['mission_dose'], dose)
        finally:
            store.close()

    def test_interrupted_backfill_resumes_to_target_not_another_full_window(self):
        store = Store(self.path)
        calls = 0
        def stop():
            nonlocal calls
            calls += 1
            return calls > 2
        try:
            self.assertFalse(prepare(store, self.env, stop))
            self.assertLess(store.load().state['seconds'], .002 * 86400)
            prepare(store, self.env)
            self.assertAlmostEqual(store.load().state['seconds'], .002 * 86400)
        finally:
            store.close()

    def test_foreground_container_command_and_restart(self):
        env = {**self.env, 'SIM_HISTORY_DAYS': '0', 'SIM_EMIT_INTERVAL': '.001',
               'SIM_SPEED': '1000', 'SIM_LIVE_TICKS': '3'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(main(), 0)
            self.assertEqual(main(), 0)
        store = Store(self.path)
        try:
            self.assertEqual(store.load().state['seconds'], 6)
            self.assertEqual(len(store.load().state['crew']), 3)
        finally:
            store.close()

    def test_invalid_startup_configuration_fails_before_generation(self):
        with patch.dict(os.environ, {**self.env, 'SIM_EMIT_INTERVAL': '-1'}, clear=True):
            self.assertEqual(main(), 1)
        self.assertFalse(self.path.exists())
