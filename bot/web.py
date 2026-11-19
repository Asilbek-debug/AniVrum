"""AniVrum uchun Render sinov xizmati."""

import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path
from tempfile import gettempdir

from aiohttp import web

log = logging.getLogger(__name__)
POLLING_TASK = web.AppKey("polling_task", asyncio.Task)


async def health(request):
    task = request.app.get(POLLING_TASK)
    if task is not None and task.done():
        return web.json_response({"status": "unavailable", "polling_enabled": True}, status=503)
    return web.json_response({"status": "ok", "polling_enabled": task is not None})


async def run_polling():
    from bot.main import main as bot_main
    from database.db import DEFAULT_DB_PATH, database_url

    try:
        if database_url():
            if os.environ.get("ANIVRUM_DB_PATH"):
                log.error("DATABASE_URL va ANIVRUM_DB_PATH birga ishlatilmaydi.")
                return
            await bot_main(load_local_env=False, handle_signals=False)
            return
        default = Path(gettempdir()) / "anivrum-render-test.db"
        path = Path(os.environ.get("ANIVRUM_DB_PATH") or default).resolve()
        production_path = DEFAULT_DB_PATH.resolve()
        if path == production_path or (
            path.exists() and production_path.exists() and path.samefile(production_path)
        ):
            log.error("Sinov xizmati uchun alohida ANIVRUM_DB_PATH kiriting.")
            return
        await bot_main(load_local_env=False, handle_signals=False, database_path=path)
    except SystemExit as error:
        log.error("%s", error)
    except Exception as error:
        log.error("Bot polling xatosi. Turi: %s", type(error).__name__)


async def polling_context(app):
    task = asyncio.create_task(run_polling())
    app[POLLING_TASK] = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app():
    app = web.Application()
    app.router.add_get("/healthz", health)
    if os.getenv("ENABLE_BOT", "").strip().lower() == "true":
        app.cleanup_ctx.append(polling_context)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "10000")), access_log=None)
