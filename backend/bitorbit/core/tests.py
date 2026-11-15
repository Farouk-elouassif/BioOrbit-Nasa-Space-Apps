"""Offline model checks plus database constraint tests for the operational schema."""
from uuid import uuid4

from django.apps import apps
from django.core import checks
from django.db import IntegrityError, models, transaction
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import (
    Astronaut, Habitat, LatestMeasurement, MeasurementEvent, MetricCatalog,
    Mission, MissionCrew, PreflightBaseline, PreflightProfile, SimulationRun,
)


class OperationalModelDefinitionTests(SimpleTestCase):
    def test_model_checks(self):
        self.assertEqual(checks.run_checks(app_configs=[apps.get_app_config('core')], databases=[]), [])

    def test_tables_and_primary_keys_match_contract(self):
        expected = {
            Mission: ('missions', 'id'), Habitat: ('habitats', 'id'),
            Astronaut: ('astronauts', 'id'), MissionCrew: ('mission_crew', 'pk'),
            SimulationRun: ('simulation_runs', 'run_id'), MetricCatalog: ('metric_catalog', 'code'),
            MeasurementEvent: ('measurement_events', 'event_id'),
            PreflightProfile: ('preflight_profiles', 'id'),
            PreflightBaseline: ('preflight_baselines', 'pk'),
            LatestMeasurement: ('latest_measurements', 'id'),
        }
        for model, (table, pk) in expected.items():
            self.assertEqual(model._meta.db_table, table)
            self.assertEqual(model._meta.pk.name, pk)
            if pk == 'id':
                self.assertIsInstance(model._meta.pk, models.BigAutoField)
        self.assertEqual(MissionCrew(mission_id=2, astronaut_id=3).pk, (2, 3))
        self.assertEqual(PreflightBaseline(profile_id=7, metric_id='heart_rate').pk, (7, 'heart_rate'))

    def test_journal_keeps_raw_payload_without_export_metadata(self):
        fields={field.name for field in MeasurementEvent._meta.fields}
        self.assertIn('raw_payload',fields)
        self.assertFalse(any(name.startswith('bronze_') for name in fields))

    def test_foreign_key_columns_and_deletion_policy(self):
        for model in (MeasurementEvent, LatestMeasurement, PreflightProfile):
            self.assertEqual(model._meta.get_field('run').column, 'run_id')
        for model in (MeasurementEvent, LatestMeasurement, PreflightBaseline):
            self.assertEqual(model._meta.get_field('metric').column, 'metric_code')
        for model in apps.get_app_config('core').get_models():
            for field in model._meta.fields:
                if isinstance(field, models.ForeignKey):
                    self.assertIs(field.remote_field.on_delete, models.PROTECT)

    def test_partial_indexes_and_uniqueness(self):
        indexes = {i.name: i for i in MeasurementEvent._meta.indexes}
        self.assertEqual(indexes['idx_measurement_history'].fields, ['run', 'astronaut', 'metric', '-measured_at'])
        constraints = {c.name: c for c in LatestMeasurement._meta.constraints}
        self.assertEqual(constraints['uq_latest_astronaut'].fields, ('run', 'astronaut', 'metric'))
        self.assertEqual(constraints['uq_latest_cabin'].fields, ('run', 'habitat', 'zone_id', 'metric'))
        self.assertEqual(constraints['uq_latest_astronaut'].condition, models.Q(domain='astronaut'))
        self.assertEqual(constraints['uq_latest_cabin'].condition, models.Q(domain='cabin'))

    def test_defaults_and_json_objects_are_independent(self):
        self.assertEqual(Mission().status, 'planned')
        self.assertTrue(SimulationRun().is_active)
        first, second = MeasurementEvent(), MeasurementEvent()
        first.context['activity'] = 'resting'
        self.assertEqual(second.context, {})
        for model, name in ((Mission, 'status'), (SimulationRun, 'created_at'),
                            (MeasurementEvent, 'context'), (LatestMeasurement, 'updated_at')):
            self.assertTrue(model._meta.get_field(name).has_db_default())
        self.assertFalse(LatestMeasurement._meta.get_field('updated_at').auto_now)

    def test_migration_state_matches_models(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        self.assertIn(('core', '0001_initial'), loader.disk_migrations)
        changes = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps)).changes(graph=loader.graph)
        self.assertNotIn('core', changes, 'Model changes require a committed migration')


class OperationalDatabaseTests(TestCase):
    """Run against PostgreSQL via `manage.py test core`; never run by check_models.py."""
    @classmethod
    def setUpTestData(cls):
        cls.mission = Mission.objects.create(mission_code='MARS_001')
        cls.habitat = Habitat.objects.create(mission=cls.mission, habitat_code='HAB_001')
        cls.astronaut = Astronaut.objects.create(astronaut_code='AST_001')
        cls.simulation_run = SimulationRun.objects.create(run_id='run-001', mission=cls.mission, environment='transit_spacecraft')
        cls.numeric = MetricCatalog.objects.create(code='heart_rate', domain='astronaut', unit='bpm', value_type='numeric')
        cls.boolean = MetricCatalog.objects.create(code='is_solar_storm', domain='cabin', unit='boolean', value_type='boolean', aggregation_kind='boolean')

    def event(self, **overrides):
        values = dict(event_id=uuid4(), run=self.simulation_run, mission=self.mission, habitat=self.habitat,
                      astronaut=self.astronaut, zone_id='CABIN_MAIN', kind='measurement',
                      phase='inflight', domain='astronaut', metric=self.numeric, numeric_value=68,
                      measured_at=timezone.now(), emitted_at=timezone.now(), raw_payload={'simulated': True})
        values.update(overrides)
        return MeasurementEvent.objects.create(**values)

    def assert_rejected(self, operation):
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()

    def test_numeric_boolean_and_profile_events(self):
        self.assertEqual(self.event().numeric_value, 68)
        event = self.event(domain='cabin', astronaut=None, metric=self.boolean, numeric_value=None, boolean_value=False)
        self.assertIs(event.boolean_value, False)
        profile = self.event(kind='preflight_profile', phase='preflight', metric=None, numeric_value=None)
        self.assertIsNone(profile.metric)

    def test_event_value_exclusivity_and_shape(self):
        for updates in ({'numeric_value': None}, {'boolean_value': True}, {'metric': None},
                        {'kind': 'preflight_profile', 'phase': 'inflight', 'metric': None, 'numeric_value': None},
                        {'kind': 'preflight_profile', 'phase': 'preflight'}):
            self.assert_rejected(lambda updates=updates: self.event(**updates))

    def test_event_subject_and_enumerations(self):
        for updates in ({'domain': 'cabin'}, {'astronaut': None}, {'domain': 'invalid'},
                        {'kind': 'invalid'}, {'phase': 'invalid'}):
            self.assert_rejected(lambda updates=updates: self.event(**updates))

    def test_event_id_is_unique(self):
        event = self.event()
        self.assert_rejected(lambda: self.event(event_id=event.event_id))

    def test_mission_crew_composite_key_and_nullable_habitat(self):
        row = MissionCrew.objects.create(mission=self.mission, astronaut=self.astronaut)
        self.assertEqual(row.pk, (self.mission.pk, self.astronaut.pk))
        self.assert_rejected(lambda: MissionCrew.objects.create(mission=self.mission, astronaut=self.astronaut))

    def test_habitat_unique_within_mission(self):
        self.assert_rejected(lambda: Habitat.objects.create(mission=self.mission, habitat_code='HAB_001'))
        other = Mission.objects.create(mission_code='OTHER')
        Habitat.objects.create(mission=other, habitat_code='HAB_001')

    def test_preflight_profile_and_baseline_keys(self):
        source = self.event(kind='preflight_profile', phase='preflight', metric=None, numeric_value=None)
        profile = PreflightProfile.objects.create(run=self.simulation_run, astronaut=self.astronaut, source_event=source)
        self.assert_rejected(lambda: PreflightProfile.objects.create(run=self.simulation_run, astronaut=self.astronaut))
        data = dict(profile=profile, metric=self.numeric, mean=68, stddev=2, min_value=64, max_value=72, sample_count=14)
        row = PreflightBaseline.objects.create(**data)
        self.assertEqual(row.pk, (profile.pk, 'heart_rate'))
        self.assert_rejected(lambda: PreflightBaseline.objects.create(**data))
        PreflightBaseline.objects.filter(pk=row.pk).delete()
        self.assert_rejected(lambda: PreflightBaseline.objects.create(**{**data, 'sample_count': 1}))

    def latest(self, **overrides):
        source = self.event()
        data = dict(run=self.simulation_run, domain='astronaut', astronaut=self.astronaut, habitat=self.habitat,
                    zone_id='CABIN_MAIN', metric=self.numeric, numeric_value=68,
                    measured_at=source.measured_at, source_event=source)
        data.update(overrides)
        return LatestMeasurement.objects.create(**data)

    def test_latest_partial_unique_indexes(self):
        self.latest()
        self.assert_rejected(lambda: self.latest())
        # Astronaut uniqueness intentionally does not include zone.
        self.assert_rejected(lambda: self.latest(zone_id='OTHER_ZONE'))
        cabin = dict(domain='cabin', astronaut=None, metric=self.boolean, numeric_value=None, boolean_value=False)
        self.latest(**cabin)
        self.assert_rejected(lambda: self.latest(**cabin))
        self.latest(**{**cabin, 'zone_id': 'OTHER_ZONE'})

    def test_latest_value_and_subject_constraints(self):
        for updates in ({'numeric_value': None}, {'boolean_value': True}, {'astronaut': None}, {'domain': 'cabin'}):
            self.assert_rejected(lambda updates=updates: self.latest(**updates))

    def test_catalogue_enumerations(self):
        for updates in ({'domain': 'invalid'}, {'value_type': 'string'}, {'aggregation_kind': 'average'}):
            data = dict(code='invalid', domain='cabin', unit='x', value_type='numeric')
            data.update(updates)
            self.assert_rejected(lambda data=data: MetricCatalog.objects.create(**data))

    def test_referenced_records_are_protected(self):
        self.event()
        with self.assertRaises(ProtectedError):
            self.simulation_run.delete()
