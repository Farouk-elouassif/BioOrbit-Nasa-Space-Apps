"""Offline schema, request, and filesystem checks: no database connections or migrations."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'bitorbit'))

from django.conf import settings
settings.configure(
    INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','core.apps.CoreConfig'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    SECRET_KEY='offline-model-checks-only',
    USE_TZ=True,
)
import django
django.setup()

from core.test_alerts import AlertRuleTests, AlertFixRegressionTests
from core.test_checkins import InferredRuleTests
from core.test_pdf_scenarios import PdfRuleTests
from core.tests import OperationalModelDefinitionTests
from core.test_ingestion import IngestionValidationTests, IngestionRequestTests
from core.test_reads import ReadSerializationTests, ReadRequestTests

suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (PdfRuleTests, AlertRuleTests, AlertFixRegressionTests, InferredRuleTests, OperationalModelDefinitionTests, IngestionValidationTests, IngestionRequestTests, ReadSerializationTests, ReadRequestTests))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
