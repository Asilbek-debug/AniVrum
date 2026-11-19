import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from database import neon_import
from test_neon_preflight import FAKE_URL


class NeonImportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"ANIVRUM_IMPORT_DATABASE_URL": FAKE_URL}))
        self.enterContext(redirect_stdout(StringIO()))
        self.enterContext(redirect_stderr(StringIO()))

    def test_preflight_checks_backup_without_calling_importer(self):
        with patch.object(neon_import.neon_preflight, "check", return_value=0), patch.object(
            neon_import, "validate_backup"
        ) as validate, patch.object(neon_import.import_postgres, "main") as importer:
            self.assertEqual(neon_import.main(["check"]), 0)
            validate.assert_called_once_with(neon_import.BACKUP)
            importer.assert_not_called()

    def test_nonempty_target_blocks_even_confirmed_import(self):
        with patch.object(neon_import.neon_preflight, "check", return_value=1), patch.object(
            neon_import.import_postgres, "main"
        ) as importer:
            self.assertEqual(neon_import.main(["confirmed-import"]), 2)
            importer.assert_not_called()

    def test_apply_then_verify_with_same_source_and_hardened_tls(self):
        calls = []

        def importer(args):
            self.assertIn("sslmode=verify-full", os.environ["ANIVRUM_IMPORT_DATABASE_URL"])
            calls.append(args)

        source = Path("verified-snapshot.db")
        options = neon_import.neon_preflight.connection_options(FAKE_URL)
        with patch.object(neon_import.import_postgres, "main", side_effect=importer):
            self.assertEqual(neon_import.run_import(source, options), 0)
        self.assertEqual(calls, [["--source", str(source), "--apply"], ["--source", str(source), "--verify"]])
        self.assertNotIn("ANIVRUM_IMPORT_DATABASE_URL", os.environ)

    def test_failure_before_or_after_commit_is_reported_distinctly(self):
        options = neon_import.neon_preflight.connection_options(FAKE_URL)
        for failures, expected, calls in (([SystemExit(1)], 1, 1), ([None, SystemExit(1)], 3, 2)):
            with patch.object(neon_import.import_postgres, "main", side_effect=failures) as importer:
                self.assertEqual(neon_import.run_import(Path("verified-snapshot.db"), options), expected)
                self.assertEqual(importer.call_count, calls)
