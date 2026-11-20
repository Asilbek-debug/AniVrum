"""Ordered delivery for private-chat season downloads."""

import asyncio
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter

from bot import content
from database import catalog as store, db

log = logging.getLogger(__name__)


class SeasonDownloads:
    def __init__(self, *, clock=None, wait=asyncio.sleep):
        self.clock = clock
        self.wait = wait
        self.jobs = {}
        self.next_request = 0
        self.paused_until = 0

    async def send(self, request, earliest, attempts=4):
        clock = self.clock or asyncio.get_running_loop().time
        for attempt in range(attempts):
            while True:
                now = clock()
                delay = max(earliest, self.next_request, self.paused_until) - now
                if delay <= 0:
                    # Keep budget for interactive traffic.
                    self.next_request = now + 1 / 20
                    break
                await self.wait(delay)
            try:
                await request()
                return now + 1
            except TelegramRetryAfter as error:
                self.paused_until = max(self.paused_until, clock() + error.retry_after)
                if attempt == attempts - 1:
                    raise

    async def deliver(self, bot, message, user_id, item, season, episodes, protected):
        earliest = await self.send(
            lambda: message.answer(f"📥 {len(episodes)} ta qism yuborish boshlandi."), 0
        )
        sent = 0
        rejected = []
        stopped = None
        for episode in episodes:
            try:
                earliest = await self.send(
                    lambda: content.send_media(
                        bot, message.chat.id, episode["video_file_id"], episode["media_type"],
                        content.video_caption(item, season["season_number"], episode["episode_number"]),
                        protect_content=protected, retry=False,
                    ), earliest
                )
            except TelegramBadRequest:
                rejected.append(episode["episode_number"])
                continue
            except TelegramAPIError as error:
                stopped = f"{episode['episode_number']}-qismda yuborish to‘xtadi."
                log.warning("Fasl %s, qism %s: %s", season["id"], episode["id"], type(error).__name__)
                break

            sent += 1
            try:
                await asyncio.to_thread(db.add_anime_views, item["id"], user_id, season["id"],
                                        [episode["id"]])
            except db.DATABASE_ERRORS:
                log.warning("Fasl %s yuborish statistikasi saqlanmadi.", season["id"])

        summary = f"✅ {sent}/{len(episodes)} ta qism yuborildi."
        if rejected:
            numbers = ", ".join(map(str, rejected[:20]))
            suffix = f" va yana {len(rejected) - 20} ta" if len(rejected) > 20 else ""
            summary += f"\nYuborilmagan qismlar ({len(rejected)} ta): {numbers}{suffix}."
        if stopped:
            summary += "\n" + stopped
        errors = len(rejected) + bool(stopped)
        if errors:
            try:
                await asyncio.to_thread(store.metric, "error", count=errors)
            except db.DATABASE_ERRORS:
                log.warning("Fasl yuborish xatolari statistikaga yozilmadi.")
        await self.send(lambda: message.answer(summary), earliest)
