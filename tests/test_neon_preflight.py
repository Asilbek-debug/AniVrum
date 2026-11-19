import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, call, patch

from database import neon_preflight


FAKE_URL = (
    "postgresql://neondb_owner:synthetic-password@ep-ani.us-east-2.aws.neon.tech"
    "/neondb?sslmode=require&channel_binding=require"
)


class NeonPreflightTests(unittest.TestCase):
    def test_direct_endpoint_requires_certificate_and_channel_binding(self):
        options = neon_preflight.connection_options(FAKE_URL)
        self.assertEqual(options["sslmode"], "verify-full")
        self.assertEqual(options["channel_binding"], "require")
        self.assertEqual(neon_preflight.connection_options(
            FAKE_URL.replace("postgresql://", "postgres://")
        )["password"], "synthetic-password")
        for url in (FAKE_URL.replace("ep-ani.", "ep-ani-pooler."),
                    FAKE_URL.replace("/neondb?", "/other?"), FAKE_URL + "&hostaddr=127.0.0.1",
                    FAKE_URL.replace("sslmode=require&", ""),
                    FAKE_URL.replace("sslmode=require", "sslmode=disable"), "x"):
            with self.assertRaises(neon_preflight.PreflightError):
                neon_preflight.connection_options(url)

    def test_connection_checks_only_read_only_catalog(self):
        with patch.object(neon_preflight.psycopg, "connect") as connect:
            conn = connect.return_value.__enter__.return_value
            conn.pgconn.ssl_in_use = True
            conn.execute.side_effect = [
                None, None, MagicMock(**{"fetchone.return_value": ("neondb", "neondb_owner", "on")}),
                MagicMock(**{"fetchone.return_value": (2,)}),
            ]
            self.assertEqual(neon_preflight.check(FAKE_URL), 2)
            self.assertEqual(conn.execute.call_args_list[:2], [
                call("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"),
                call("SET LOCAL statement_timeout = '10s'"),
            ])
            self.assertEqual(conn.execute.call_args_list[-1], call(neon_preflight.RELATION_COUNT))

    def test_cli_codes_and_redacts_driver_errors(self):
        for value, expected in ((0, 0), (1, 2), (RuntimeError(FAKE_URL), 1)):
            with self.subTest(expected=expected), patch.dict(os.environ, {
                "ANIVRUM_IMPORT_DATABASE_URL": FAKE_URL,
            }), redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()) as stderr, patch.object(
                neon_preflight, "check", side_effect=[value]
            ):
                self.assertEqual(neon_preflight.main(), expected)
                self.assertNotIn("synthetic-password", stdout.getvalue() + stderr.getvalue())
                self.assertNotIn("ANIVRUM_IMPORT_DATABASE_URL", os.environ)
