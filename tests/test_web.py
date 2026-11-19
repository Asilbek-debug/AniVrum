import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from bot import main, web
from database import db


class RenderWebTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"DATABASE_URL": "", "ANIVRUM_REQUIRE_POSTGRES": ""}))

    async def test_render_passes_postgres_configuration_only_when_polling_enabled(self):
        with patch.dict(os.environ, {
            "ENABLE_BOT": "false", "DATABASE_URL": "postgresql://unused.invalid/test", "ANIVRUM_DB_PATH": "",
        }), patch.object(main, "main", new_callable=AsyncMock) as bot_main:
            async with TestClient(TestServer(web.create_app())) as client:
                self.assertFalse((await (await client.get("/healthz")).json())["polling_enabled"])
            bot_main.assert_not_called()
            await web.run_polling()
            bot_main.assert_awaited_once_with(load_local_env=False, handle_signals=False)
            bot_main.reset_mock()
            with patch.dict(os.environ, {"ANIVRUM_DB_PATH": "sqlite-test.db"}):
                await web.run_polling()
            bot_main.assert_not_called()
    async def test_health_runs_without_polling_by_default(self):
        with patch.dict(os.environ, {"ENABLE_BOT": ""}), patch.object(
            web, "run_polling", new_callable=AsyncMock
        ) as polling:
            async with TestClient(TestServer(web.create_app())) as client:
                response = await client.get("/healthz")
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.json(), {"status": "ok", "polling_enabled": False})
            polling.assert_not_called()

    async def test_enabled_polling_uses_only_separate_database(self):
        fd, name = tempfile.mkstemp(suffix=".db", dir=Path(__file__).resolve().parent)
        os.close(fd)
        path = Path(name)
        self.addCleanup(path.unlink, missing_ok=True)
        started = asyncio.Event()

        async def polling(bot, **kwargs):
            try:
                started.set()
                await asyncio.Future()
            finally:
                await bot.session.close()

        with patch.dict(os.environ, {
            "ENABLE_BOT": "true", "ANIVRUM_DB_PATH": str(path),
            "BOT_TOKEN": "123456:offline", "ADMIN_ID": "100",
        }), patch.object(db, "DB_PATH", db.DEFAULT_DB_PATH), patch.object(
            main, "load_dotenv"
        ) as dotenv, patch.object(main.dp, "start_polling", side_effect=polling) as started_polling:
            async with TestClient(TestServer(web.create_app())) as client:
                await asyncio.wait_for(started.wait(), timeout=5)
                response = await client.get("/healthz")
                self.assertEqual(response.status, 200)
                self.assertTrue((await response.json())["polling_enabled"])
                self.assertEqual(db.DB_PATH, path)
                with db.connection() as conn:
                    self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
            dotenv.assert_not_called()
            self.assertIs(started_polling.call_args.kwargs["handle_signals"], False)

    async def test_render_rejects_primary_database_and_reports_unavailable(self):
        with patch.dict(os.environ, {
            "ENABLE_BOT": "true", "ANIVRUM_DB_PATH": str(db.DEFAULT_DB_PATH),
        }), patch.object(main, "main", new_callable=AsyncMock) as bot_main:
            async with TestClient(TestServer(web.create_app())) as client:
                response = await client.get("/healthz")
                self.assertEqual(response.status, 503)
            bot_main.assert_not_called()
