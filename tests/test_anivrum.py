import asyncio
import os
import re
from html import unescape
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import EditMessageCaption, EditMessageMedia, GetChatMember, SendDocument, SendMessage, SendPhoto, SendVideo
from aiogram.methods import DeleteMessage
from aiogram.types import Update

from bot import content, main
from database import catalog, db


class LocalTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.members = {11, 100}
        self.post_failure = None
        self.post_failure_message = "Sinov xatosi"
        self.edit_failure = None
        self.failed_video = None

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetChatMember):
            return SimpleNamespace(status="member" if method.user_id in self.members else "left")
        if isinstance(method, (SendMessage, SendPhoto, SendVideo)) and method.chat_id == main.CHANNEL and self.post_failure:
            raise self.post_failure(method=method, message=self.post_failure_message)
        if isinstance(method, (EditMessageCaption, EditMessageMedia)) and self.edit_failure:
            error, message = self.edit_failure
            raise error(method=method, message=message)
        if isinstance(method, SendVideo) and method.video == self.failed_video:
            raise TelegramBadRequest(method=method, message="Sinov xatosi")
        return SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=len(self.calls))

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


def form(code, kind="anime", title="Solo Leveling"):
    return dict(code=code, kind=kind, title=title, genre="Jangari, Fantastika",
                release_year=2024, description="Sinov <&>")


class AniVrumTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, name = tempfile.mkstemp(suffix=".db", dir=Path(__file__).resolve().parent)
        os.close(fd)
        path = Path(name)
        self.addCleanup(path.unlink, missing_ok=True)
        self.enterContext(patch.object(db, "DB_PATH", path))
        self.enterContext(patch.object(main, "ADMIN_ID", 100))
        self.session = LocalTelegram()
        self.bot = Bot("123456:local_test_token", session=self.session)
        self.update_id = 0
        await main.dp.storage.close()

    def migrate(self):
        catalog.migrate()

    async def update(self, user, *, text=None, data=None, photo=None, video=None, document=None, caption=None, forward_origin=None):
        self.update_id += 1
        actor = {"id": user, "is_bot": False, "first_name": "Sinov"}
        message = {"message_id": self.update_id, "date": 1700000000,
                   "chat": {"id": user, "type": "private"}, "from": actor}
        for key, value in (("text", text), ("photo", photo), ("video", video), ("document", document),
                           ("caption", caption), ("forward_origin", forward_origin)):
            if value is not None:
                message[key] = value
        if data is not None:
            message["text"] = "Sinov"
            event = {"callback_query": {"id": str(self.update_id), "from": actor,
                     "chat_instance": "local", "data": data, "message": message}}
        else:
            event = {"message": message}
        await main.dp.feed_update(self.bot, Update.model_validate({"update_id": self.update_id, **event}))

    def channel_posts(self):
        return [call for call in self.session.calls
                if isinstance(call, SendPhoto) and call.chat_id == main.CHANNEL]

    def test_migration_keeps_existing_rows(self):
        db.create_database()
        db.create_seasons_episodes_tables()
        db.create_favorites_table()
        db.create_views_table()
        with db.connection() as conn:
            conn.execute("INSERT INTO animes VALUES (23,'1001','Eski','Drama','Tavsif',2020)")
            conn.execute("INSERT INTO seasons VALUES (7,23,2)")
            conn.execute("INSERT INTO episodes VALUES (8,7,3,'Qism','old-file')")
            conn.execute("INSERT INTO favorites VALUES (9,11,23)")
            conn.execute("INSERT INTO anime_views VALUES (10,23,11,8,'2025-03-01 00:00:00')")
        self.migrate()
        self.migrate()
        self.assertEqual(catalog.by_code("1001", "anime")["id"], 23)
        self.assertIsNone(catalog.content(23)["poster_file_id"])
        self.assertIsNone(catalog.content(23)["country"])
        self.assertIn("Davlat:</b> Ko&#x27;rsatilmagan", content.caption(catalog.content(23)))
        self.assertEqual(db.get_episode_by_id(8)["media_type"], "video")
        self.assertTrue(db.is_favorite(11, 23))
        self.assertEqual(db.get_top_animes()[0]["views"], 1)
        with catalog.connection() as conn:
            self.assertEqual(tuple(conn.execute("SELECT * FROM anime_views").fetchone()),
                             (10, 23, 11, 8, "2025-03-01 00:00:00", 7))
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")

    async def test_existing_v1_announcement_and_country_edit(self):
        with db.connection() as conn:
            catalog._migrate_v1(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.execute("""INSERT INTO animes(id, code, title, poster_file_id)
                VALUES (45, '3045', 'Anime <&>', 'old-poster')""")
            conn.execute("INSERT INTO announcements VALUES (45, 'sent', '-100987', 321)")
            conn.execute("INSERT INTO seasons VALUES (15, 45, 1)")
            conn.execute("INSERT INTO episodes VALUES (31, 15, 1, 'Qism', 'video', 'video', 'unique')")
            conn.execute("INSERT INTO anime_views VALUES (22, 45, 11, 31, '2024-01-01', 15)")
        self.migrate()
        self.migrate()
        self.assertIsNone(catalog.content(45)["country"])
        self.assertEqual(catalog.content(45)["views"], 1)
        self.assertEqual(db.get_episode_by_id(31)["video_file_id"], "video")
        self.assertEqual(catalog.announcement(45)["message_id"], 321)

        await self.update(100, data="manage_anime_45")
        keyboard = self.session.calls[-3].reply_markup.inline_keyboard
        edit = next(button for row in keyboard for button in row if "Davlatini" in button.text)
        await self.update(100, data=edit.callback_data)
        self.assertIn("Yangi davlat nomini", self.session.calls[-2].text)
        await self.update(100, text="<b>Yaponiya</b>")
        self.assertIsNone(catalog.content(45)["country"])
        await self.update(100, text="  Yaponiya ,  Xitoy ")
        self.assertEqual(catalog.content(45)["country"], "Yaponiya, Xitoy")
        await self.update(11, data="anime_az")
        entries = self.session.calls[-1].reply_markup.inline_keyboard
        self.assertIn("Yaponiya, Xitoy", entries[0][0].text)
        await self.update(11, text="/start anime_3045")
        public = self.session.calls[-1]
        await self.update(100, data="manage_anime_45")
        admin = self.session.calls[-3]
        await self.update(100, data="p_admin_post_45")
        preview = self.session.calls[-1]
        for message in (public, admin, preview):
            self.assertEqual(message.photo, "old-poster")
            self.assertEqual(message.parse_mode, "HTML")
            self.assertIn(
                "🎭 <b>Janr:</b> Kiritilmagan\n🌍 <b>Davlat:</b> Yaponiya, Xitoy\n"
                "📅 <b>Yil:</b> —\n📺 <b>Fasllar:</b> 1 ta\n🎞 <b>Qismlar:</b> 1 ta\n"
                "🔢 <b>Kod:</b> 3045", message.caption,
            )

        await self.update(100, data="p_admin_askupdate_45")
        self.assertFalse(any(isinstance(call, (EditMessageCaption, EditMessageMedia))
                             for call in self.session.calls))
        await self.update(100, data="p_admin_update_45")
        media_edit = next(call for call in self.session.calls if isinstance(call, EditMessageMedia))
        self.assertEqual((media_edit.chat_id, media_edit.message_id), (-100987, 321))
        self.assertEqual(media_edit.media.media, "old-poster")
        self.assertIn("<b>ANIME &lt;&amp;&gt;</b>", media_edit.media.caption)
        self.assertIn("<b>Davlat:</b> Yaponiya, Xitoy", media_edit.media.caption)
        db.update_anime_country(45, "AQSH")
        await self.update(100, data="p_admin_update_45")
        caption_edit = next(call for call in self.session.calls if isinstance(call, EditMessageCaption))
        self.assertIn("<b>Davlat:</b> AQSH", caption_edit.caption)
        for edit in (media_edit, caption_edit):
            (row,) = edit.reply_markup.inline_keyboard
            (download,) = row
            self.assertEqual(download.text, "📥 YUKLAB OLISH")
            self.assertEqual(download.url, "https://t.me/AniVrum_bot?start=animeid_45")
        self.assertFalse(self.channel_posts())

    async def test_startup_without_real_polling(self):
        with patch.object(main, "load_dotenv") as dotenv, patch.dict(
            main.os.environ, {"BOT_TOKEN": "123456:offline", "ADMIN_ID": "100"}
        ), patch.object(main.dp, "start_polling", new_callable=AsyncMock) as polling:
            try:
                await main.main()
                polling.assert_awaited_once()
                dotenv.assert_called_once()
            finally:
                if polling.call_args:
                    await polling.call_args.args[0].session.close()
        self.assertEqual(catalog.catalog(), [])

    async def test_admin_workflow_deep_link_subscription_and_favorites(self):
        self.migrate()
        await self.update(11, text="/start")
        self.assertTrue(any(button.callback_data == "anime" for row in
                            self.session.calls[-1].reply_markup.inline_keyboard for button in row))
        await self.update(11, text="/admin")
        self.assertIn("administrator", self.session.calls[-1].text)
        await self.update(11, data="admin_add_anime")
        self.assertTrue(self.session.calls[-1].show_alert)
        await self.update(100, text="/admin")
        self.assertIn("Admin panel", self.session.calls[-1].text)
        await self.update(100, data="admin_add_anime")
        for text in ("Solo Leveling", "1001", "Jangari, Fantastika", "Yaponiya,  Xitoy", "2024", "Sinov <&>"):
            await self.update(100, text=text)
        await self.update(100, photo=[dict(file_id="poster", file_unique_id="p", width=100, height=100)])
        await self.update(100, text="2")
        self.assertFalse(catalog.by_code("1001", "anime"))
        item = catalog.content(1)
        self.assertEqual(item["season_count"], 2)
        self.assertEqual(item["country"], "Yaponiya, Xitoy")
        self.assertEqual(item["poster_file_id"], "poster")
        season_id = db.get_anime_seasons(1)[0]["id"]
        await self.update(100, data=f"uploadseason_{season_id}")
        await self.update(100, document=dict(file_id="doc", file_unique_id="d", mime_type="video/mp4"))
        await self.update(100, text="/finish")
        await self.update(100, data="p_admin_post_1")
        self.assertEqual(self.session.calls[-1].photo, "poster")
        await self.update(100, data="p_admin_publish_1")
        await self.update(100, data="p_admin_publish_1")
        self.assertEqual(len(self.channel_posts()), 1)
        post = self.channel_posts()[0]
        self.assertEqual(post.photo, "poster")
        self.assertEqual(post.parse_mode, "HTML")
        self.assertIn("<b>🎬 ANIVRUM | ANIME</b>\n\n<b>SOLO LEVELING</b>", post.caption)
        self.assertIn("<b>Davlat:</b> Yaponiya, Xitoy", post.caption)
        self.assertIn("<b>Fasllar:</b> 2 ta\n🎞 <b>Qismlar:</b> 1 ta", post.caption)
        self.assertIn("<b>QISQACHA TAVSIF</b>", post.caption.replace("📖 ", ""))
        self.assertIn("Sinov &lt;&amp;&gt;", post.caption)
        self.assertEqual(post.reply_markup.inline_keyboard[0][0].url,
                         "https://t.me/AniVrum_bot?start=animeid_1")
        await self.update(12, text="/start animeid_1")
        self.assertEqual(self.session.calls[-1].reply_markup.inline_keyboard[1][0].callback_data,
                         "check_subscription_1")
        await self.update(12, data="check_subscription_1")
        self.assertTrue(self.session.calls[-1].show_alert)
        self.session.members.add(12)
        await self.update(12, data="check_subscription_1")
        self.assertTrue(any(isinstance(call, SendPhoto) and call.chat_id == 12 and call.photo == "poster"
                            for call in self.session.calls))
        await self.update(12, data="p_fav_add_1")
        self.assertTrue(db.is_favorite(12, 1))
        await self.update(12, data="favorites")
        self.assertTrue(any(button.callback_data == "anime_detail_1" for row in
                            self.session.calls[-2].reply_markup.inline_keyboard for button in row))
        await self.update(12, data="p_fav_remove_1")
        self.assertFalse(db.is_favorite(12, 1))
        db.update_anime_code(1, "1010")
        self.assertIsNone(catalog.by_code("1001", "anime"))
        self.assertEqual(catalog.by_code("1010", "anime")["id"], 1)
        self.assertEqual(db.search_animes("jangari")[0]["id"], 1)
        self.assertEqual(db.search_animes("2024")[0]["id"], 1)
        self.assertEqual(db.search_animes("Solo Levling")[0]["id"], 1)
        for section in ("anime_az", "anime_new", "anime_popular", "anime_genres", "anime_years"):
            await self.update(12, data=section)

    async def test_season_continues_and_counts_success_only(self):
        self.migrate()
        anime = catalog.create_draft(form("1100"), "poster", 1)
        season = db.get_anime_seasons(anime)[0]["id"]
        self.assertEqual(db.add_episode_auto(season, "bad", "video", "first"), 1)
        self.assertEqual(db.add_episode_auto(season, "ok", "document", "second"), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            db.add_episode_auto(season, "new-file-id", "document", "second")
        await content.publish(self.bot, main.CHANNEL, anime)
        self.session.failed_video = "bad"
        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            await self.update(11, data=f"downloadall_{season}")
        self.assertTrue(any(isinstance(call, SendDocument) and call.document == "ok"
                            for call in self.session.calls))
        self.assertEqual(db.get_top_animes()[0]["views"], 1)
        episode = db.get_season_episodes(season)[1]
        await self.update(11, data=f"watchpart_{episode['id']}")
        periods, _, _, popular_season = catalog.statistics()
        self.assertEqual(tuple(periods[7]), (2, 1))
        self.assertEqual(tuple(periods[30]), (2, 1))
        self.assertIn("1-fasl", popular_season["title"])

    async def test_admin_edits_draft_genre_from_management_keyboard(self):
        self.migrate()
        other_id = catalog.create_draft(form("1100", title="Boshqa anime"), "other-poster", 1)
        anime_id = catalog.create_draft(form("4200", title="Yengilmas"), "poster", 1)
        self.assertFalse(catalog.content(anime_id)["visible"])

        await self.update(100, text="/admin")
        menu = self.session.calls[-1].reply_markup.inline_keyboard
        manage = next(button for row in menu for button in row if "Kontent" in button.text)
        await self.update(100, data=manage.callback_data)
        listing = self.session.calls[-1].reply_markup.inline_keyboard
        selected = next(button for row in listing for button in row if "Yengilmas" in button.text)
        await self.update(100, data=selected.callback_data)
        details = self.session.calls[-3].reply_markup.inline_keyboard
        edit_genre = next(button for row in details for button in row if "Janrini" in button.text)
        self.assertEqual(edit_genre.callback_data, f"manage_edit_genre_{anime_id}")

        await self.update(100, data=edit_genre.callback_data)
        self.assertIn("Yangi janrni", getattr(self.session.calls[-2], "text", None) or "")
        await self.update(100, text="Fantastika, Sarguzasht")
        self.assertEqual(db.get_anime_by_id(anime_id)["genre"], "Fantastika, Sarguzasht")
        self.assertEqual(db.get_anime_by_id(other_id)["genre"], "Jangari, Fantastika")
        self.assertFalse(catalog.content(anime_id)["visible"])

        await self.update(100, data=selected.callback_data)
        self.assertIn("Janr:</b> Fantastika, Sarguzasht", self.session.calls[-3].caption)
        season_id = db.get_anime_seasons(anime_id)[0]["id"]
        db.add_episode_auto(season_id, "episode")
        self.assertEqual(await content.publish(self.bot, main.CHANNEL, anime_id), "sent")
        await self.update(11, text=f"/start animeid_{anime_id}")
        self.assertIn("Janr:</b> Fantastika, Sarguzasht", self.session.calls[-1].caption)

    async def test_admin_edits_and_poster_confirmation(self):
        self.migrate()
        anime = catalog.create_draft(form("1200"), "old-poster", 1)
        season = db.get_anime_seasons(anime)[0]["id"]
        db.add_episode_auto(season, "original")
        episode = db.get_season_episodes(season)[0]["id"]
        await self.update(100, data=f"episode_editnum_{episode}")
        await self.update(100, text="5")
        self.assertEqual(db.get_episode_by_id(episode)["episode_number"], 5)
        await self.update(100, data=f"episode_replace_{episode}")
        await self.update(100, document=dict(file_id="replacement", file_unique_id="r", file_name="ep5.mp4"))
        self.assertEqual(db.get_episode_by_id(episode)["media_type"], "document")
        await self.update(100, data=f"p_admin_editposter_{anime}")
        await self.update(100, photo=[dict(file_id="updated-poster", file_unique_id="up", width=10, height=10)])
        self.assertEqual(catalog.content(anime)["poster_file_id"], "updated-poster")
        await self.update(100, data=f"p_admin_publish_{anime}")
        await self.update(100, data=f"p_admin_askupdate_{anime}")
        self.assertFalse(any(isinstance(call, EditMessageMedia) for call in self.session.calls))
        await self.update(100, data=f"p_admin_update_{anime}")
        self.assertTrue(any(isinstance(call, EditMessageCaption) for call in self.session.calls))
        catalog.update_media(anime, "poster", "new-channel-poster")
        await self.update(100, data=f"p_admin_update_{anime}")
        self.assertTrue(any(isinstance(call, EditMessageMedia) for call in self.session.calls))
        await self.update(100, data=f"p_admin_askposter_{anime}")
        self.assertIsNotNone(catalog.content(anime)["poster_file_id"])
        await self.update(100, data=f"p_admin_deleteposter_{anime}")
        self.assertIsNone(catalog.content(anime)["poster_file_id"])
        await self.update(11, text=f"/start animeid_{anime}")
        self.assertIn("SOLO LEVELING", self.session.calls[-1].text)

    def test_long_caption(self):
        self.migrate()
        data = form("5555", title="🎌" * 100)
        data.update(genre="🎬" * 100, description="🎭" * 1500)
        anime = catalog.create_draft(data, "poster", 1)
        item = dict(catalog.content(anime))
        item["season_count"] = 99
        item["episode_count"] = 9999
        text = content.caption(item)
        rendered = unescape(re.sub(r"</?b>", "", text))
        self.assertLessEqual(content.caption_units(rendered), 1024)
        self.assertIn("…\n\n━━━━━━━━━━━━━━━━", rendered)

    async def test_deleted_channel_post_requires_confirmation_and_saves_new_id(self):
        self.migrate()
        anime = catalog.create_draft(form("4201"), "poster", 1)
        season = db.get_anime_seasons(anime)[0]["id"]
        db.add_episode_auto(season, "episode")
        self.assertEqual(await content.publish(self.bot, main.CHANNEL, anime), "sent")
        old_id = catalog.announcement(anime)["message_id"]

        for error, message, expected in (
            (TelegramBadRequest, "Bad Request: message can't be edited", "tahrirlashni rad etdi"),
            (TelegramNetworkError, "timeout", "kanalni qo‘lda tekshiring"),
        ):
            self.session.edit_failure = error, message
            await self.update(100, data=f"p_admin_update_{anime}")
            self.assertIn(expected, self.session.calls[-1].text)
            self.assertEqual(catalog.announcement(anime)["status"], "sent")

        self.session.edit_failure = TelegramBadRequest, "Bad Request: message to edit not found"
        await self.update(100, data=f"p_admin_update_{anime}")
        self.assertEqual(catalog.announcement(anime)["status"], "missing")
        self.assertEqual(catalog.announcement(anime)["message_id"], old_id)
        self.assertIn("Qayta e’lon qilish", self.session.calls[-1].reply_markup.inline_keyboard[0][0].text)
        await self.update(100, data=f"p_admin_post_{anime}")
        button = self.session.calls[-1].reply_markup.inline_keyboard[0][0]
        await self.update(100, data=button.callback_data)
        confirm = self.session.calls[-1].reply_markup.inline_keyboard[0][0].callback_data
        await self.update(11, data=confirm)
        await self.update(100, data=f"p_admin_publish_{anime}")
        self.assertEqual(len(self.channel_posts()), 1)

        self.session.post_failure = TelegramBadRequest
        await self.update(100, data=confirm)
        self.assertEqual(catalog.announcement(anime)["status"], "missing")
        self.assertEqual(catalog.announcement(anime)["message_id"], old_id)
        self.session.post_failure = None
        await self.update(100, data=confirm)
        record = catalog.announcement(anime)
        self.assertEqual(record["status"], "sent")
        self.assertNotEqual(record["message_id"], old_id)
        last_post = self.channel_posts()[-1]
        self.assertEqual(record["message_id"], next(
            position for position, call in enumerate(self.session.calls, 1) if call is last_post
        ))
        await self.update(100, data=confirm)
        self.assertEqual(len(self.channel_posts()), 3)

    async def test_uncertain_repost_blocks_duplicate_until_manual_check(self):
        self.migrate()
        anime = catalog.create_draft(form("4202"), "poster", 1)
        db.add_episode_auto(db.get_anime_seasons(anime)[0]["id"], "episode")
        self.assertEqual(await content.publish(self.bot, main.CHANNEL, anime), "sent")
        old_id = catalog.announcement(anime)["message_id"]
        self.session.edit_failure = TelegramBadRequest, "Bad Request: message not found"
        await self.update(100, data=f"p_admin_update_{anime}")
        await self.update(100, data=f"p_admin_askrepost_{anime}")
        confirm = self.session.calls[-1].reply_markup.inline_keyboard[0][0].callback_data
        self.session.post_failure = TelegramNetworkError
        await self.update(100, data=confirm)
        self.assertIn("Kanalni qo‘lda tekshirib", self.session.calls[-1].text)
        self.assertEqual(catalog.announcement(anime)["status"], "sending")
        self.assertEqual(catalog.announcement(anime)["message_id"], old_id)
        self.session.post_failure = None
        await self.update(100, data=confirm)
        await self.update(100, data=f"p_admin_publish_{anime}")
        self.assertEqual(len(self.channel_posts()), 2)

    async def test_intentional_republish_with_active_or_missing_previous_post(self):
        self.migrate()
        for code, missing in (("4301", False), ("4302", True)):
            with self.subTest(missing=missing):
                anime = catalog.create_draft(form(code), "poster", 1)
                db.add_episode_auto(db.get_anime_seasons(anime)[0]["id"], "episode")
                self.assertEqual(await content.publish(self.bot, main.CHANNEL, anime), "sent")
                old_id = catalog.announcement(anime)["message_id"]
                count = len(self.channel_posts())
                await self.update(100, data=f"p_admin_post_{anime}")
                rows = self.session.calls[-1].reply_markup.inline_keyboard
                repeat = next(button.callback_data for row in rows for button in row if "Kanalga qayta" in button.text)
                await self.update(100, data=repeat)
                preview = self.session.calls[-1]
                self.assertEqual(preview.photo, "poster")
                self.assertIn("ANIVRUM | ANIME", preview.caption)
                self.assertNotIn("YANGI ANIME", preview.caption)
                confirm, cancel = preview.reply_markup.inline_keyboard[0]
                await self.update(100, data=cancel.callback_data)
                await self.update(100, data=confirm.callback_data)
                self.assertEqual(len(self.channel_posts()), count)
                if missing:
                    catalog.mark_announcement_missing(anime, old_id)
                await self.update(100, data=repeat)
                confirm = self.session.calls[-1].reply_markup.inline_keyboard[0][0]
                await self.update(11, data=confirm.callback_data)
                self.assertEqual(len(self.channel_posts()), count)
                await self.update(100, data=confirm.callback_data)
                await self.update(100, data=confirm.callback_data)
                self.assertEqual(len(self.channel_posts()), count + 1)
                self.assertFalse(any(isinstance(call, DeleteMessage) for call in self.session.calls))
                posted = self.channel_posts()[-1]
                self.assertIs(posted.protect_content, False)
                self.assertTrue(posted.reply_markup.inline_keyboard[0][0].url.endswith(f"animeid_{anime}"))
                new_id = catalog.announcement(anime)["message_id"]
                self.assertNotEqual(old_id, new_id)
                await self.update(100, data=f"p_admin_update_{anime}")
                edited = next(call for call in reversed(self.session.calls) if isinstance(call, EditMessageCaption))
                self.assertEqual(edited.message_id, new_id)

    async def test_channel_post_composer_handles_media_forwarding_and_confirmation(self):
        self.migrate()
        forward = dict(type="hidden_user", date=1700000000, sender_user_name="Sinov")
        cases = (
            ("text", {"text": "Oddiy <b>matn</b> & belgilar"}, SendMessage, "text"),
            ("photo", {"photo": [dict(file_id="shared-image", file_unique_id="pic", width=1, height=1)],
                       "caption": "Rasm <&>", "forward_origin": forward}, SendPhoto, "caption"),
            ("video", {"video": dict(file_id="shared-video", file_unique_id="vid", width=1, height=1, duration=1),
                       "forward_origin": forward}, SendVideo, "caption"),
        )
        await self.update(11, data="p_compose_menu")
        self.assertTrue(self.session.calls[-1].show_alert)
        await self.update(100, data="p_compose_menu")
        choices = self.session.calls[-1].reply_markup.inline_keyboard[0]
        for button, (kind, fields, method, text_field) in zip(choices, cases, strict=True):
            with self.subTest(kind=kind):
                await self.update(100, data=button.callback_data)
                if kind == "text":
                    await self.update(100, text="a" * 4097)
                    self.assertIn("4096", self.session.calls[-1].text)
                if kind == "photo":
                    await self.update(100, **dict(fields, caption="😀" * 513))
                    self.assertIn("1024", self.session.calls[-1].text)
                await self.update(100, **fields)
                preview = self.session.calls[-1]
                self.assertIsInstance(preview, method)
                self.assertEqual(preview.chat_id, 100)
                confirm, cancel = preview.reply_markup.inline_keyboard[0]
                start = len(self.session.calls)
                if kind == "text":
                    await self.update(100, data=cancel.callback_data)
                    await self.update(100, data=confirm.callback_data)
                    self.assertFalse(any(getattr(call, "chat_id", None) == main.CHANNEL for call in self.session.calls[start:]))
                    await self.update(100, data=button.callback_data)
                    await self.update(100, **fields)
                    confirm = self.session.calls[-1].reply_markup.inline_keyboard[0][0]
                await self.update(100, data=confirm.callback_data)
                await self.update(100, data=confirm.callback_data)
                channel = [call for call in self.session.calls[start:] if getattr(call, "chat_id", None) == main.CHANNEL]
                self.assertEqual(len(channel), 1)
                post = channel[0]
                self.assertIsInstance(post, method)
                self.assertIs(post.protect_content, False)
                self.assertIsNone(post.parse_mode)
                self.assertIsNone(post.reply_markup)
                self.assertEqual(getattr(post, text_field), fields.get(text_field))
                if kind != "text":
                    self.assertEqual(getattr(post, kind), getattr(preview, kind))

        await self.update(100, data="p_compose_photo")
        await self.update(100, **cases[1][1])
        confirm = self.session.calls[-1].reply_markup.inline_keyboard[0][0]
        self.session.post_failure = TelegramBadRequest
        self.session.post_failure_message = "Bad Request: wrong file identifier"
        await self.update(100, data=confirm.callback_data)
        self.assertIn("media faylini qabul qilmadi", self.session.calls[-1].text)

    async def test_episode_document_and_poster_protection_depends_on_recipient(self):
        self.migrate()
        anime = catalog.create_draft(form("4401"), "anime-poster", 1)
        season = db.get_anime_seasons(anime)[0]["id"]
        db.add_episode_auto(season, "episode")
        db.add_episode_auto(season, "episode-doc", media_type="document")
        episode = db.get_season_episodes(season)[0]["id"]
        await content.publish(self.bot, main.CHANNEL, anime)
        for user, protected in ((11, True), (100, False)):
            with self.subTest(user=user):
                start = len(self.session.calls)
                await self.update(user, text=f"/start animeid_{anime}")
                await self.update(user, data=f"watchpart_{episode}")
                with patch.object(asyncio, "sleep", new_callable=AsyncMock):
                    await self.update(user, data=f"downloadall_{season}")
                await self.update(user, data=f"episode_detail_{episode}")
                messages = [method for method in self.session.calls[start:]
                            if isinstance(method, (SendDocument, SendPhoto, SendVideo))]
                self.assertEqual(len(messages), 5)
                self.assertTrue(all(method.protect_content is protected for method in messages))
        self.assertTrue(all(post.protect_content is False for post in self.channel_posts()))

    async def test_rebrand_menus_search_and_archived_movies(self):
        self.migrate()
        movie = catalog.create_draft(form("2000", "movie", "Saqlangan kino"), "movie-poster")
        catalog.update_media(movie, "movie", "movie-file", "video")
        with db.connection() as conn:
            conn.execute("UPDATE animes SET visible=1 WHERE id=?", (movie,))
            conn.execute("INSERT INTO favorites(user_id, anime_id) VALUES (11, ?)", (movie,))
            conn.execute("INSERT INTO announcements VALUES (?, 'sent', '-100', 12, 'movie-poster')", (movie,))
        anime = catalog.create_draft(form("2001", title="Anime Sarguzasht"), "poster", 1)
        db.add_episode_auto(db.get_anime_seasons(anime)[0]["id"], "episode")
        self.assertEqual(await content.publish(self.bot, main.CHANNEL, anime), "sent")
        self.assertTrue(db.add_favorite(11, anime))
        movie_before = dict(catalog.content(movie))
        announcement_before = dict(catalog.announcement(movie))

        await self.update(11, text="/start")
        message = self.session.calls[-1]
        self.assertIn("AniVrum | Anime", message.text)
        self.assertEqual(
            [[button.callback_data for button in row] for row in message.reply_markup.inline_keyboard],
            [["anime", "anime_search"], ["favorites", "top_animes"], ["about"]],
        )
        await self.update(11, data="about")
        self.assertIn("AniVrum | Anime", self.session.calls[-2].text)
        await self.update(11, data="anime")
        self.assertIn("AniVrum | Anime", self.session.calls[-2].text)
        menu = self.session.calls[-2].reply_markup.inline_keyboard
        self.assertEqual(menu[0][0].text, "🔤 Alifbo bo‘yicha")
        self.assertEqual(menu[0][0].callback_data, "anime_az")
        await self.update(11, data=menu[0][0].callback_data)
        listing = self.session.calls[-1]
        self.assertIn("Alifbo bo‘yicha", listing.text)
        self.assertEqual(listing.reply_markup.inline_keyboard[0][0].callback_data, f"anime_detail_{anime}")
        await self.update(11, data="anime_search")
        await self.update(11, text="2000")
        self.assertFalse(db.search_animes("2000"))
        self.assertFalse(any(
            f"anime_detail_{movie}" == button.callback_data
            for row in self.session.calls[-1].reply_markup.inline_keyboard for button in row
        ))
        await self.update(11, data="anime_search")
        await self.update(11, text="2001")
        self.assertIn("Anime Sarguzasht", self.session.calls[-1].reply_markup.inline_keyboard[0][0].text)
        await self.update(11, data="favorites")
        self.assertEqual([item["id"] for item in db.get_user_favorites(11)], [anime])
        self.assertNotIn("KINOLAR", self.session.calls[-2].text)
        episode = db.get_season_episodes(db.get_anime_seasons(anime)[0]["id"])[0]
        await self.update(11, data=f"watchpart_{episode['id']}")
        await self.update(11, data="top_animes")
        top = self.session.calls[-2]
        self.assertIn("AniVrum | Anime · TOP-10", top.text)
        self.assertIn("Anime Sarguzasht", top.text)

        start = len(self.session.calls)
        await self.update(11, text="/start movie_2000")
        self.assertIn("Havoladagi kontent topilmadi", self.session.calls[-1].text)
        for callback in ("movies", f"p_movie_{movie}", f"anime_detail_{movie}", f"fav_remove_{movie}"):
            await self.update(11, data=callback)
        await self.update(100, text="/admin")
        menu = self.session.calls[-1].reply_markup.inline_keyboard
        self.assertFalse(any("Kino" in button.text for row in menu for button in row))
        await self.update(100, data="p_admin_list_manage_0")
        listing = self.session.calls[-1].reply_markup.inline_keyboard
        self.assertFalse(any(f"manage_anime_{movie}" == button.callback_data for row in listing for button in row))
        for callback in ("p_admin_movie", f"manage_anime_{movie}", f"manage_edit_country_{movie}",
                         f"manage_confirmdelete_{movie}", f"p_admin_publish_{movie}", f"p_repeat_{movie}"):
            await self.update(100, data=callback)
        self.assertFalse(any(isinstance(call, (SendPhoto, SendVideo)) for call in self.session.calls[start:]))
        self.assertEqual(dict(catalog.content(movie)), movie_before)
        self.assertEqual(dict(catalog.announcement(movie)), announcement_before)
        self.assertTrue(db.is_favorite(11, movie))
        await self.update(11, text=f"/start animeid_{anime}")
        self.assertIn("ANIVRUM | ANIME", self.session.calls[-1].caption)

    async def test_plain_anime_code_opens_exact_detail_after_subscription(self):
        self.migrate()
        other = catalog.create_draft(form("1001", title="Boshqa anime"), "other-poster", 1)
        anime = catalog.create_draft(dict(form("1", title="Yengilmas"), country="AQSH"), "poster", 2)
        for anime_id in (other, anime):
            db.add_episode_auto(db.get_anime_seasons(anime_id)[0]["id"], f"video-{anime_id}")
            await content.publish(self.bot, main.CHANNEL, anime_id)

        await self.update(11, text="1001")
        self.assertEqual(self.session.calls[-1].photo, "other-poster")
        await self.update(12, text=" 1 ")
        subscription = self.session.calls[-1].reply_markup.inline_keyboard[1][0]
        self.assertEqual(subscription.callback_data, f"check_subscription_{anime}")
        await self.update(12, data=subscription.callback_data)
        self.assertTrue(self.session.calls[-1].show_alert)
        self.session.members.add(12)
        await self.update(12, data=subscription.callback_data)
        page = next(call for call in reversed(self.session.calls) if isinstance(call, SendPhoto))
        self.assertEqual(page.photo, "poster")
        for field in ("YENGILMAS", "Janr:</b> Jangari, Fantastika", "Davlat:</b> AQSH",
                      "Yil:</b> 2024", "Fasllar:</b> 2 ta", "Qismlar:</b> 1 ta", "Sinov &lt;&amp;&gt;"):
            self.assertIn(field, page.caption)
        actions = [row[0].callback_data for row in page.reply_markup.inline_keyboard[:3]]
        self.assertEqual(actions, [f"choose_parts_{anime}", f"download_seasons_{anime}", f"p_fav_add_{anime}"])
        for action in actions[:2]:
            await self.update(12, data=action)
            self.assertTrue(self.session.calls[-2].reply_markup.inline_keyboard[0])
        await self.update(12, data=actions[2])
        self.assertTrue(db.is_favorite(12, anime))
        await self.update(12, text="9999")
        self.assertEqual(self.session.calls[-1].text, "❌ Bu kod bo'yicha anime topilmadi")

    async def test_plain_code_does_not_intercept_admin_or_search_state(self):
        self.migrate()
        await self.update(100, data="admin_add_anime")
        await self.update(100, text="Yangi anime")
        await self.update(100, text="1001")
        self.assertIn("Anime kodi: 1001", self.session.calls[-1].text)
        self.assertIn("janrini yuboring", self.session.calls[-1].text)
        await self.update(11, data="anime_search")
        await self.update(11, text="1001")
        message = self.session.calls[-1]
        self.assertIn("'1001' bo'yicha anime topilmadi", message.text)
        self.assertEqual(message.reply_markup.inline_keyboard[0][0].callback_data, "anime_search")

    async def test_reused_code_keeps_version_two_legacy_links_bound_to_original_id(self):
        with db.connection() as conn:
            catalog._migrate_v1(conn)
            conn.execute("ALTER TABLE animes ADD COLUMN country TEXT")
            conn.execute("ALTER TABLE announcements ADD COLUMN poster_file_id TEXT")
            conn.execute("PRAGMA user_version = 2")
            conn.execute("INSERT INTO animes(code, title, poster_file_id) VALUES ('6001', 'Eski anime', 'old')")
            conn.execute("UPDATE animes SET code='6002' WHERE id=1")
        self.migrate()
        self.migrate()
        for code in ("6001", "6002"):
            await self.update(11, text=f"/start anime_{code}")
            self.assertEqual(self.session.calls[-1].photo, "old")

        season = db.get_anime_seasons(1)
        self.assertEqual(season, [])
        db.add_season(1, 1)
        season_id = db.get_anime_seasons(1)[0]["id"]
        db.add_episode_auto(season_id, "episode")
        episode_id = db.get_season_episodes(season_id)[0]["id"]
        self.assertTrue(db.delete_episode(episode_id))
        self.assertTrue(db.delete_season(season_id))
        self.assertEqual(catalog.by_code("6002", "anime")["id"], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            catalog.create_draft(form("6002"), "duplicate", 1)

        self.assertTrue(db.delete_anime(1))
        anime = catalog.create_draft(form("6002", title="Boshqa anime"), "new", 1)
        self.assertNotEqual(anime, 1)
        db.add_episode_auto(db.get_anime_seasons(anime)[0]["id"], "new-episode")
        await content.publish(self.bot, main.CHANNEL, anime)
        post = self.channel_posts()[-1]
        self.assertTrue(post.reply_markup.inline_keyboard[0][0].url.endswith(f"animeid_{anime}"))
        await self.update(11, text="6002")
        self.assertEqual(self.session.calls[-1].photo, "new")
        for link in ("anime_6001", "anime_6002", "animeid_1"):
            await self.update(11, text=f"/start {link}")
            self.assertIn("Havoladagi kontent topilmadi", self.session.calls[-1].text)
        self.assertTrue(db.update_anime_code(anime, "6001"))
        await self.update(11, text=f"/start animeid_{anime}")
        self.assertEqual(self.session.calls[-1].photo, "new")
        self.assertIn("Kod:</b> 6001", self.session.calls[-1].caption)
        await self.update(11, text="/start anime_6001")
        self.assertIn("Havoladagi kontent topilmadi", self.session.calls[-1].text)

    async def test_admin_updates_year_and_code_and_adds_season(self):
        self.migrate()
        anime = catalog.create_draft(form("2003"), "poster", 1)
        db.add_episode_auto(db.get_anime_seasons(anime)[0]["id"], "episode")
        await content.publish(self.bot, main.CHANNEL, anime)
        for field, value in (("year", "2025"), ("code", "2004")):
            await self.update(100, data=f"manage_edit_{field}_{anime}")
            await self.update(100, text=value)
        await self.update(100, data=f"addseason_{anime}")
        await self.update(100, text="2")
        self.assertEqual(catalog.content(anime)["release_year"], 2025)
        self.assertEqual(catalog.content(anime)["code"], "2004")
        self.assertEqual(catalog.content(anime)["season_count"], 2)
        await self.update(11, text=f"/start animeid_{anime}")
        self.assertIn("Kod:</b> 2004", self.session.calls[-1].caption)


if __name__ == "__main__":
    unittest.main()
