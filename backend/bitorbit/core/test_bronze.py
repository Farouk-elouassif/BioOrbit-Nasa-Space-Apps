"""Real filesystem safety tests; PostgreSQL export transaction tests are separate."""
from datetime import date
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from .bronze.exporter import claim_batches, export_one, export_pending
from .bronze.files import BronzeFileError, partition_path, write_batch
from .ingestion.service import ingest
from .ingestion.validation import Conflict, validate_payload
from .models import BronzeExportBatch, MeasurementEvent
from .test_ingestion import cabin, observation, profile


class BronzeFileTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'bronze'
        self.payloads = [observation(metric='bp_systolic', unit='mmHg', value=112), cabin()]
        self.relative = partition_path('demo-001', 'astronaut', 'inflight', date(2026,11,14), uuid4())

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_json_values_and_aliases_are_preserved(self):
        target = write_batch(self.root, self.relative, self.payloads)
        records = json.loads(target.read_text())
        self.assertEqual(records, self.payloads)
        self.assertEqual(records[0]['metric'], 'bp_systolic')
        self.assertIs(records[1]['value'], False)
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def test_identical_retry_reuses_immutable_file(self):
        target = write_batch(self.root, self.relative, self.payloads)
        contents, modified = target.read_bytes(), target.stat().st_mtime_ns
        self.assertEqual(write_batch(self.root,self.relative,self.payloads),target)
        self.assertEqual(target.read_bytes(), contents)
        self.assertEqual(target.stat().st_mtime_ns, modified)
        self.assertEqual(len(list(self.root.rglob('*.json'))), 1)

    def test_conflicting_file_is_never_overwritten(self):
        target = write_batch(self.root,self.relative,self.payloads)
        contents = target.read_bytes()
        with self.assertRaises(BronzeFileError):
            write_batch(self.root,self.relative,[{**self.payloads[0],'value':999}])
        self.assertEqual(target.read_bytes(), contents)
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def test_path_traversal_and_absolute_paths_rejected(self):
        for path in ('../outside.json','/tmp/outside.json','partition/../../outside.json'):
            with self.subTest(path=path), self.assertRaises(BronzeFileError):
                write_batch(self.root,path,self.payloads)

    def test_external_run_codes_are_escaped(self):
        path = partition_path('../../other/mission', 'cabin', 'inflight', date(2026,11,14), uuid4())
        self.assertIn('%2F', path)
        target=write_batch(self.root,path,self.payloads)
        self.assertTrue(target.resolve().is_relative_to(self.root.resolve()))

    def test_long_unicode_run_ids_fit_filesystem_component_limits(self):
        run='🚀'*100
        path=partition_path(run,'astronaut','inflight',date(2026,11,14),uuid4())
        self.assertTrue(path.startswith('run_hash='))
        self.assertTrue(all(len(part.encode('utf-8'))<=255 for part in Path(path).parts))
        self.assertTrue(write_batch(self.root,path,self.payloads).exists())

    def test_empty_duplicate_nonfinite_and_invalid_records_rejected(self):
        for records in ([], [self.payloads[0],self.payloads[0]], [{}], ['bad'],
                        [{**self.payloads[0],'value':float('nan')}],
                        [{**self.payloads[0],'event_id':'not-a-uuid'}]):
            with self.assertRaises(BronzeFileError):write_batch(self.root,self.relative,records)
        self.assertFalse(self.root.exists())

    def test_publish_failure_leaves_no_partial_final_file(self):
        with patch('core.bronze.files.os.link',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):write_batch(self.root,self.relative,self.payloads)
        self.assertEqual(list(self.root.rglob('*.json')), [])
        self.assertEqual(list(self.root.rglob('*.tmp')), [])
        self.assertTrue(write_batch(self.root,self.relative,self.payloads).exists())

    def test_profiles_remain_raw_json_objects(self):
        payload=profile()
        target=write_batch(self.root,self.relative,[payload])
        self.assertEqual(json.loads(target.read_text())[0]['profile'],payload['profile'])


class BronzeOrchestrationTests(SimpleTestCase):
    @patch('core.bronze.exporter.claim_batches',side_effect=[1,0])
    @patch('core.bronze.exporter.export_one',side_effect=[None,{'event_count':2},None])
    def test_claimed_work_is_drained(self, export, claim):
        self.assertEqual(list(export_pending('/unused',100)),[{'event_count':2}])
        self.assertEqual(export.call_count,3)
        self.assertEqual(claim.call_count,2)

    @patch('core.bronze.exporter.export_one')
    def test_stop_and_invalid_limits(self, export):
        self.assertEqual(list(export_pending('/unused',stopping=lambda:True)),[])
        self.assertFalse(export.called)
        with self.assertRaises(ValueError):list(export_pending('/unused',batch_size=0))
        with self.assertRaises(ValueError):list(export_pending('/unused',max_batches=0))

    @patch('core.bronze.exporter.export_one',return_value={'event_count':2})
    def test_max_batches_bounds_work(self, export):
        self.assertEqual(len(list(export_pending('/unused',max_batches=1))),1)
        self.assertEqual(export.call_count,1)

    @patch('core.management.commands.export_bronze.export_pending',return_value=iter([{'event_count':2,'path':'/bronze/batch.json'}]))
    def test_one_shot_command(self, export):
        output=io.StringIO()
        call_command('export_bronze','--root','/unused','--batch-size','10',stdout=output)
        self.assertIn('Exported 2 events',output.getvalue())
        self.assertEqual(export.call_args.args[1],10)

    @patch('core.management.commands.export_bronze.export_pending',side_effect=OSError('disk full'))
    def test_one_shot_failure_is_explicit(self, export):
        with self.assertRaises(CommandError):
            call_command('export_bronze','--root','/unused',stdout=io.StringIO())


class BronzeDatabaseTests(TestCase):
    """Run with the project's PostgreSQL test database, never by the offline checker."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'bronze'

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, records):
        return ingest(validate_payload({'schema_version':'1.0','events':records}))

    def test_committed_journal_export_and_partitioning(self):
        records=[observation(),cabin(),profile()]
        self.ingest(records)
        self.assertFalse(self.root.exists())
        receipts=list(export_pending(self.root))
        self.assertEqual(len(receipts),3)
        exported=[]
        for path in self.root.rglob('*.json'):exported.extend(json.loads(path.read_text()))
        self.assertEqual({x['event_id'] for x in exported},{x['event_id'] for x in records})
        self.assertEqual(MeasurementEvent.objects.filter(bronze_status='exported',bronze_exported_at__isnull=False).count(),3)
        self.assertEqual(BronzeExportBatch.objects.filter(exported_at__isnull=False).count(),3)
        self.assertTrue(any('domain=cabin' in r['path'] for r in receipts))
        self.assertTrue(any('phase=preflight' in r['path'] for r in receipts))

    def test_old_pending_events_and_restart_do_not_duplicate_files(self):
        event=observation(metric='bp_systolic',unit='mmHg',value=112)
        self.ingest([event])
        claim_batches()
        original=BronzeExportBatch.objects.get().relative_path
        self.assertEqual(len(list(export_pending(self.root))),1)
        self.assertEqual(list(export_pending(self.root)),[])
        self.ingest([event])
        self.assertEqual(list(export_pending(self.root)),[])
        self.assertEqual(BronzeExportBatch.objects.get().relative_path,original)
        self.assertEqual(len(list(self.root.rglob('*.json'))),1)
        self.assertEqual(json.loads(next(self.root.rglob('*.json')).read_text())[0]['metric'],'bp_systolic')

    def test_file_error_keeps_batch_and_events_pending(self):
        self.ingest([observation()]);claim_batches()
        with patch('core.bronze.exporter.write_batch',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):export_one(self.root)
        self.assertEqual(MeasurementEvent.objects.get().bronze_status,'pending')
        self.assertIsNone(BronzeExportBatch.objects.get().exported_at)
        self.assertEqual(len(list(export_pending(self.root))),1)

    def test_failure_after_publication_reuses_same_file(self):
        self.ingest([observation()]);claim_batches()
        with patch.object(BronzeExportBatch,'save',side_effect=RuntimeError('interrupted before database commit')):
            with self.assertRaises(RuntimeError):export_one(self.root)
        file=next(self.root.rglob('*.json'));before=file.read_bytes()
        self.assertEqual(MeasurementEvent.objects.get().bronze_status,'pending')
        self.assertIsNone(BronzeExportBatch.objects.get().exported_at)
        self.assertEqual(len(list(export_pending(self.root))),1)
        self.assertEqual(len(list(self.root.rglob('*.json'))),1)
        self.assertEqual(file.read_bytes(),before)

    def test_batch_size_and_limit_leave_retryable_work(self):
        self.ingest([observation() for _ in range(5)])
        self.assertEqual(len(list(export_pending(self.root,batch_size=2,max_batches=1))),1)
        self.assertEqual(MeasurementEvent.objects.filter(bronze_status='exported').count(),2)
        list(export_pending(self.root,batch_size=2))
        self.assertEqual(MeasurementEvent.objects.filter(bronze_status='exported').count(),5)
        self.assertEqual(len(list(self.root.rglob('*.json'))),3)

    def test_corrupt_existing_file_is_not_overwritten_or_marked_exported(self):
        self.ingest([observation()]);claim_batches()
        batch=BronzeExportBatch.objects.get();target=self.root/batch.relative_path
        target.parent.mkdir(parents=True);target.write_text('corrupt')
        with self.assertRaises(BronzeFileError):export_one(self.root)
        self.assertEqual(target.read_text(),'corrupt')
        self.assertEqual(MeasurementEvent.objects.get().bronze_status,'pending')

    def test_failed_ingestion_produces_no_export(self):
        record=observation()
        with self.assertRaises(Conflict):self.ingest([record,{**record,'value':99}])
        self.assertEqual(list(export_pending(self.root)),[])
        self.assertFalse(self.root.exists())
