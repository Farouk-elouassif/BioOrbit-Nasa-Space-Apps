"""Atomic checkpoint + durable event journal, using SQLite only as local simulator state."""
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .contracts import validate_event
from .model import Config, Engine


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries (destination TEXT NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY(destination,event_id));
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def load(self):
        row = self.db.execute('SELECT config,state FROM checkpoint WHERE id=1').fetchone()
        if row is None:
            raise ValueError('Simulation not initialized; run init first')
        return Engine(Config(**json.loads(row[0])), json.loads(row[1]))

    def _save(self, engine, events):
        for event in events:
            validate_event(event)
            self.db.execute('INSERT INTO events(event_id,payload) VALUES (?,?)',
                            (event['event_id'], json.dumps(event, ensure_ascii=False, allow_nan=False)))
        self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?,?)',
                        (json.dumps(asdict(engine.config)), json.dumps(engine.snapshot(), allow_nan=False)))

    def initialize(self, config):
        with self.transaction():
            if self.db.execute('SELECT 1 FROM checkpoint').fetchone():
                raise ValueError('State exists; use a different --state path or explicit reset')
            engine = Engine(config)
            events = engine.preflight_events() + engine.initial_events()
            self._save(engine, events)
        return len(events)

    def advance(self, delta=None, real_interval=None):
        # Serialize load/mutate/events/checkpoint. A process crash commits all or none.
        with self.transaction():
            engine = self.load()
            elapsed = delta if delta is not None else real_interval * engine.config.speed
            events = engine.advance(elapsed)
            self._save(engine, events)
        return len(events)

    def control(self, action, **kwargs):
        with self.transaction():
            engine = self.load()
            if action == 'speed':
                engine.config.speed = kwargs['value']
                engine.config.validate()
            elif action == 'error-level':
                engine.config.error_level = kwargs['value']
                engine.config.validate()
            elif action == 'environment':
                engine.config.environment = kwargs['value']
                engine.config.validate()
            elif action == 'storm':
                engine.add_storm(engine.state['seconds'] + kwargs['after'], kwargs['duration'], kwargs['peak'], kwargs.get('noaa_s_level',1))
            elif action == 'symptom':
                from .scenarios import SYMPTOMS
                code=kwargs['symptom']
                if code not in SYMPTOMS: raise ValueError('Unsupported symptom')
                engine.add_scenario({'name':'symptom_'+code,'astronaut_id':kwargs['astronaut'],
                    'duration':engine.config.duration_days*86400-engine.state['seconds'],
                    'context':{'rule_inputs':{code:{'value':True}}}})
            elif action == 'scenario':
                engine.add_scenario(kwargs['data'])
            elif action == 'normal':
                engine.state['storms'] = []
                engine.state['scenarios'] = []
            else:
                raise ValueError('Unknown control')
            self._save(engine, [])

    def reset(self, config):
        with self.transaction():
            self.db.execute('DELETE FROM deliveries')
            self.db.execute('DELETE FROM events')
            self.db.execute('DELETE FROM checkpoint')
            engine = Engine(config)
            self._save(engine, engine.preflight_events() + engine.initial_events())

    def events(self):
        for (payload,) in self.db.execute('SELECT payload FROM events ORDER BY seq'):
            yield json.loads(payload)

    def count(self):
        return self.db.execute('SELECT count(*) FROM events').fetchone()[0]

    def export(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        # Snapshot export: never append into a partially written JSONL after restart.
        with temporary.open('w', encoding='utf-8') as handle:
            for event in self.events():
                handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def pending(self, destination, limit):
        rows = self.db.execute('''SELECT payload FROM events e WHERE NOT EXISTS
            (SELECT 1 FROM deliveries d WHERE d.destination=? AND d.event_id=e.event_id)
            ORDER BY seq LIMIT ?''', (destination, limit))
        return [json.loads(row[0]) for row in rows]

    def acknowledge(self, destination, events):
        with self.transaction():
            self.db.executemany('INSERT OR IGNORE INTO deliveries VALUES (?,?)',
                                [(destination, event['event_id']) for event in events])
