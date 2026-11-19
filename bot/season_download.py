"""Ordered delivery for private-chat season downloads."""

import asyncio
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputMediaVideo

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

    async def send(self, request, count, earliest, attempts=4):
        clock = self.clock or asyncio.get_running_loop().time
        for attempt in range(attempts):
            while True:
                now = clock()
                delay = max(earliest, self.next_request, self.paused_until) - now
                if delay <= 0:
                    # Keep budget for interactive traffic and account for every album item.
                    self.next_request = now + count / 20
                    break
                await self.wait(delay)
            try:
                return await request(), now + count
            except TelegramRetryAfter as error:
                self.paused_until = max(self.paused_until, clock() + error.retry_after)
                if attempt == attempts - 1:
                    raise

    async def deliver(self, bot, message, user_id, item, season, episodes, protected):
        status, earliest = await self.send(
            lambda: message.answer(f"📥 {len(episodes)} ta qism yuborish boshlandi."), 1, 0
        )
        index = sent = 0
        rejected = []
        stopped = None
        albums = True
        while index < len(episodes):
            batch = episodes[index:index + 2]
            episode = batch[0]
            try:
                if albums and len(batch) == 2 and all(ep["media_type"] == "video" for ep in batch):
                    media = [
                        InputMediaVideo(media=ep["video_file_id"], caption=content.video_caption(
                            item, season["season_number"], ep["episode_number"]
                        ))
                        for ep in batch
                    ]
                    try:
                        result, earliest = await self.send(
                            lambda: bot.send_media_group(chat_id=message.chat.id, media=media,
                                                         protect_content=protected), 2, earliest, attempts=2
                        )
                    except (TelegramBadRequest, TelegramRetryAfter):
                        albums = False
                        continue
                    if len(result) != len(batch):
                        stopped = f"{episode['episode_number']}-qismdan boshlab albom holati noaniq."
                        break
                else:
                    batch = [episode]
                    _, earliest = await self.send(
                        lambda: content.send_media(
                            bot, message.chat.id, episode["video_file_id"], episode["media_type"],
                            content.video_caption(item, season["season_number"], episode["episode_number"]),
                            protect_content=protected, retry=False,
                        ), 1, earliest
                    )
            except TelegramBadRequest:
                rejected.append(episode["episode_number"])
                index += 1
                continue
            except TelegramAPIError as error:
                stopped = f"{episode['episode_number']}-qismda yuborish to‘xtadi."
                log.warning("Fasl %s, qism %s: %s", season["id"], episode["id"], type(error).__name__)
                break

            sent += len(batch)
            index += len(batch)
            try:
                await asyncio.to_thread(db.add_anime_views, item["id"], user_id, season["id"],
                                        [ep["id"] for ep in batch])
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
        try:
            await self.send(
                lambda: bot.edit_message_text(chat_id=message.chat.id, message_id=status.message_id,
                                              text=summary), 1, earliest
            )
        except TelegramBadRequest:
            await self.send(lambda: message.answer(summary), 1, earliest)
