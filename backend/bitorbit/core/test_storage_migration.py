"""Upgrade existing PostgreSQL data without deleting the source event journal."""
from uuid import uuid4
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class PostgreSQLStorageMigrationTests(TransactionTestCase):
    def test_removing_export_metadata_preserves_events_and_latest_references(self):
        executor=MigrationExecutor(connection)
        old_target=[('core','0004_latest_rule_inputs')]
        new_target=[('core','0005_remove_bronze_export')]
        try:
            executor.migrate(old_target)
            old=executor.loader.project_state(old_target).apps
            mission=old.get_model('core','Mission').objects.create(mission_code='migration-mission')
            habitat=old.get_model('core','Habitat').objects.create(mission=mission,habitat_code='habitat')
            astronaut=old.get_model('core','Astronaut').objects.create(astronaut_code='migration-crew')
            run=old.get_model('core','SimulationRun').objects.create(run_id='migration-run',mission=mission,environment='transit_spacecraft')
            metric=old.get_model('core','MetricCatalog').objects.create(code='heart_rate',unit='bpm',domain='astronaut',value_type='numeric')
            batch=old.get_model('core','BronzeExportBatch').objects.create(relative_path='old/export.json',event_count=1)
            identity=uuid4();at=timezone.now();raw={'event_id':str(identity),'value':68,'context':{'activity':'resting'}}
            event=old.get_model('core','MeasurementEvent').objects.create(
                event_id=identity,run=run,mission=mission,habitat=habitat,astronaut=astronaut,
                zone_id='CABIN_MAIN',kind='measurement',phase='inflight',domain='astronaut',metric=metric,
                numeric_value=68,measured_at=at,emitted_at=at,context={'activity':'resting'},raw_payload=raw,
                bronze_batch=batch,bronze_status='exported',bronze_exported_at=at)
            old.get_model('core','LatestMeasurement').objects.create(run=run,habitat=habitat,astronaut=astronaut,
                zone_id='CABIN_MAIN',domain='astronaut',metric=metric,numeric_value=68,measured_at=at,source_event=event)
            executor=MigrationExecutor(connection);executor.migrate(new_target)
            new=executor.loader.project_state(new_target).apps
            saved=new.get_model('core','MeasurementEvent').objects.get(pk=identity)
            self.assertEqual(saved.raw_payload,raw);self.assertEqual(saved.numeric_value,68)
            latest=new.get_model('core','LatestMeasurement').objects.get(run_id=run.pk)
            self.assertEqual(latest.source_event_id,identity)
            self.assertNotIn('bronze_export_batches',connection.introspection.table_names())
            self.assertFalse(any(field.name.startswith('bronze_') for field in saved._meta.fields))
        finally:
            cleanup=MigrationExecutor(connection)
            cleanup.migrate(cleanup.loader.graph.leaf_nodes())
