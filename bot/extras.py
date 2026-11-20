"""Standalone videos, news, comments, and owner statistics."""

import logging
import os
from datetime import UTC, datetime

from aiogram import BaseMiddleware, F
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup

from bot import activity, content
from database import catalog as store, db

log = logging.getLogger(__name__)
LABELS = {"film": "🎞 Film", "ova": "⭐ OVA", "anime": "📺 Anime", "general": "📰 Umumiy"}
PAGE = 10


class ExtrasForm(StatesGroup):
    video = State()
    video_metadata = State()
    video_media = State()
    caption = State()
    news = State()
    news_photo = State()
    comment = State()


def track(kind, subject=0):
    try:
        store.metric(kind, subject)
    except db.DATABASE_ERRORS:
        log.warning("Bot statistikasi yozilmadi.")


class ActiveUsers(BaseMiddleware):
    last_prune = None

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user and chat and chat.type == "private" and not user.is_bot:
            try:
                store.active_user(user.id)
                today = datetime.now(UTC).date()
                if self.last_prune != today:
                    store.prune_statistics()
                    self.last_prune = today
            except db.DATABASE_ERRORS:
                log.warning("Faol foydalanuvchi statistikasi yozilmadi.")
        return await handler(event, data)


def page_markup(entries, page, prefix, back, extra=()):
    rows = [(entry,) for entry in entries[:PAGE]]
    nav = []
    if page:
        nav.append(("⬅️ Oldingi", f"{prefix}_{page-1}"))
    if len(entries) > PAGE:
        nav.append(("Keyingi ➡️", f"{prefix}_{page+1}"))
    if nav:
        rows.append(tuple(nav))
    rows.extend(extra)
    rows.append((("⬅️ Orqaga", back),))
    return content.buttons(*rows)


def video_label(video):
    return f"{LABELS[video['kind']]} {video['number']} · {content.limited(video['title'], 48)}"


def news_text(item):
    heading = f"{LABELS[item['kind']]} · {item['title']}"
    if item["anime_title"] and item["anime_visible"]:
        heading += f"\n{item['anime_title']}"
    return f"{heading}\n\n{item['body']}"


async def send_news(bot, chat_id, item):
    if item["photo"]:
        return await bot.send_photo(chat_id, item["photo"], caption=news_text(item), parse_mode=None)
    return await bot.send_message(chat_id, news_text(item), parse_mode=None)


async def send_standalone(message, bot, video_id, *, protected, actor=None):
    video = store.standalone_video(video_id)
    item = store.anime_content(video["anime_id"]) if video else None
    if not item or not item["visible"] or not video["file_id"]:
        await message.answer("Video topilmadi.")
        return
    try:
        await content.send_media(bot, message.chat.id, video["file_id"], video["media_type"],
                                 content.video_caption(item, standalone=video),
                                 protect_content=protected)
    except TelegramAPIError:
        track("error")
        await message.answer("Video yuborilmadi. Keyinroq urinib ko‘ring.")
        return
    track(video["kind"], video["id"])
    actor = actor or message.from_user
    if actor:
        await activity.observe(message, actor.id, video["kind"], video["kind"], video_id, actor=actor)
    metadata = []
    for key, label in (("release_year", "📅 Yil"), ("country", "🌍 Davlat"), ("genre", "🎭 Janr")):
        if video[key]:
            metadata.append(f"{label}: {video[key]}")
    if video["description"]:
        metadata.append(video["description"])
    if metadata:
        await message.answer("\n".join(metadata), parse_mode=None)


def install(router, admin_id, channel, is_subscribed, add_anime):
    router.update.outer_middleware(ActiveUsers())

    async def owner(callback):
        if callback.from_user.id == admin_id() and getattr(getattr(callback.message, "chat", None), "type", None) == "private":
            await callback.answer()
            return True
        await callback.answer("Bu bo‘lim bot egasi uchun.", show_alert=True)
        return False

    async def reader(callback, bot):
        if getattr(getattr(callback.message, "chat", None), "type", None) == "private" and await is_subscribed(bot, callback.from_user.id):
            await callback.answer()
            return True
        await callback.answer("Kanalga obuna bo‘ling va botning shaxsiy chatidan foydalaning.", show_alert=True)
        return False

    @router.callback_query(StateFilter(add_anime.title), F.data.regexp(r"^x_kind_(anime|film|ova)$"))
    async def choose_kind(callback, state):
        if await owner(callback):
            kind = callback.data.rsplit("_", 1)[1]
            await state.update_data(initial_video=kind if kind != "anime" else None)
            await callback.message.answer(f"{LABELS[kind]} tanlandi. Anime nomini yuboring.")

    @router.callback_query(F.data.regexp(r"^x_(videos|manageanime)_[0-9]{1,18}_[0-9]{1,8}$"))
    async def video_list(callback, bot):
        _, mode, raw_id, raw_page = callback.data.split("_")
        admin = mode == "manageanime"
        if not (await owner(callback) if admin else await reader(callback, bot)):
            return
        anime_id, page = int(raw_id), int(raw_page)
        item = store.anime_content(anime_id)
        if not item or (not admin and not item["visible"]):
            await callback.message.answer("Anime topilmadi.")
            return
        videos = store.standalone_videos(anime_id, page * PAGE, PAGE + 1)
        entries = [(video_label(video), f"x_{'editvideo' if admin else 'video'}_{video['id']}") for video in videos]
        extra = (
            (("➕ Film", f"x_add_film_{anime_id}"), ("➕ OVA", f"x_add_ova_{anime_id}")),
            (("➕ Fasl qo‘shish", f"addseason_{anime_id}"), ("✏️ Caption", f"x_caption_{anime_id}")),
            (("📢 E’lon", f"p_admin_post_{anime_id}"),),
        ) if admin else ()
        await callback.message.answer(
            item["title"] if entries else f"{item['title']} · Film va OVA yo‘q.",
            reply_markup=page_markup(entries, page, f"x_{mode}_{anime_id}",
                                    "x_manage_0" if admin else f"anime_detail_{anime_id}", extra),
        )
        if not admin:
            await activity.observe_callback(callback, "extras", "anime", anime_id)

    @router.callback_query(F.data.regexp(r"^x_manage_[0-9]{1,8}$"))
    async def manage(callback):
        if not await owner(callback):
            return
        page = int(callback.data.rsplit("_", 1)[1])
        with store.connection() as conn:
            items = conn.execute("""SELECT id,title FROM animes WHERE kind='anime'
                ORDER BY id DESC LIMIT ? OFFSET ?""", (PAGE + 1, page * PAGE)).fetchall()
        entries = [(content.limited(item["title"], 55), f"x_manageanime_{item['id']}_0") for item in items]
        await callback.message.answer("📋 Barcha kontent" if entries else "Kontent topilmadi.",
                                      reply_markup=page_markup(entries, page, "x_manage", "p_admin_home"))

    @router.callback_query(F.data.regexp(r"^x_video_[0-9]{1,18}$"))
    async def deliver_video(callback, bot):
        if not await reader(callback, bot):
            return
        await send_standalone(callback.message, bot, int(callback.data.rsplit("_", 1)[1]),
                              protected=callback.from_user.id != admin_id(), actor=callback.from_user)

    @router.callback_query(F.data.regexp(r"^x_(editvideo|deletevideo|confirmvideo)_[0-9]{1,18}$"))
    async def video_admin(callback, state):
        if not await owner(callback):
            return
        _, action, raw_id = callback.data.split("_")
        video = store.standalone_video(int(raw_id))
        if not video:
            await callback.message.answer("Video topilmadi.")
            return
        back = f"x_manageanime_{video['anime_id']}_0"
        if action == "confirmvideo":
            store.delete_video(video["id"])
            await state.clear()
            await callback.message.answer("Video o‘chirildi.", reply_markup=content.buttons((("⬅️ Orqaga", back),)))
        elif action == "deletevideo":
            await callback.message.answer(f"{video_label(video)} o‘chirilsinmi?", reply_markup=content.buttons(
                (("🗑 O‘chirish", f"x_confirmvideo_{video['id']}"), ("❌ Bekor qilish", back))))
        else:
            await state.set_data({"video_id": video["id"], "anime_id": video["anime_id"], "kind": video["kind"]})
            await state.set_state(ExtrasForm.video)
            current = f"{video['number']}\n{video['title']}\n{video['description'] or ''}"
            await callback.message.answer(
                f"✏️ Raqam, nom va ixtiyoriy tavsifni alohida satrlarda yuboring.\n\n{current}",
                reply_markup=content.buttons((("🗑 O‘chirish", f"x_deletevideo_{video['id']}"),)),
            )

    @router.callback_query(F.data.regexp(r"^x_add_(film|ova)_[0-9]{1,18}$"))
    async def add_video(callback, state):
        if not await owner(callback):
            return
        _, _, kind, raw_id = callback.data.split("_")
        if not store.anime_content(int(raw_id)):
            await callback.message.answer("Anime topilmadi.")
            return
        await state.set_data({"anime_id": int(raw_id), "kind": kind})
        await state.set_state(ExtrasForm.video)
        await callback.message.answer("Raqam, nom va ixtiyoriy tavsifni alohida satrlarda yuboring.\n\n1\nFilm nomi\nTavsif")

    @router.message(ExtrasForm.video, F.from_user.id.func(lambda value: value == admin_id()))
    async def video_fields(message, state):
        lines = (message.text or "").strip().split("\n", 2)
        if len(lines) < 2 or not content.numeric_id(lines[0]) or not int(lines[0]) or not 1 <= len(lines[1].strip()) <= 100 or (len(lines) == 3 and len(lines[2]) > 2500):
            await message.answer("Raqam, 1–100 belgili nom va ixtiyoriy tavsifni alohida satrlarda yuboring.")
            return
        await state.update_data(number=int(lines[0]), title=lines[1].strip(),
                                description=(lines[2].strip() or None) if len(lines) == 3 else None)
        await state.set_state(ExtrasForm.video_metadata)
        await message.answer("Ixtiyoriy yil, davlat va janrni uchta satrda yuboring. "
                             "Bo‘sh maydon uchun -, barchasini o‘tkazish uchun /skip yozing.")

    @router.message(ExtrasForm.video_metadata, F.from_user.id.func(lambda value: value == admin_id()))
    async def video_metadata(message, state):
        data = await state.get_data()
        raw = (message.text or "").strip()
        if raw == "/skip":
            existing = store.standalone_video(data["video_id"]) if data.get("video_id") else None
            metadata = {key: existing[key] if existing else None for key in ("release_year", "country", "genre")}
        else:
            lines = [line.strip() for line in raw.split("\n")]
            if len(lines) != 3:
                await message.answer("Yil, davlat va janrni yuboring. Masalan: 2025\nYaponiya\n-")
                return
            year, country, genre = lines
            country_value = content.normalize_country(country) if country != "-" else None
            if (year != "-" and (not content.numeric_id(year) or not 1900 <= int(year) <= 2100)
                    or country != "-" and not country_value or len(genre) > 100):
                await message.answer("Yilni 1900–2100 oralig‘ida va davlat nomini to‘g‘ri yozing.")
                return
            metadata = {"release_year": int(year) if year != "-" else None, "country": country_value,
                        "genre": genre if genre and genre != "-" else None}
        await state.update_data(**metadata)
        await state.set_state(ExtrasForm.video_media)
        await message.answer("Videoni yuboring." if not data.get("video_id") else
                             "Yangi videoni yuboring yoki eskisini saqlash uchun /skip yozing.")

    @router.message(ExtrasForm.video_media, F.from_user.id.func(lambda value: value == admin_id()))
    async def video_media(message, state):
        data = await state.get_data()
        media, media_type = content.pick_media(message)
        existing = store.standalone_video(data["video_id"]) if data.get("video_id") else None
        if media:
            file_id = media.file_id
        elif message.text == "/skip" and existing:
            file_id, media_type = existing["file_id"], existing["media_type"]
        else:
            await message.answer("Videoni yuboring.")
            return
        try:
            saved = store.save_video(**data, file_id=file_id, media_type=media_type)
        except db.INTEGRITY_ERRORS:
            await state.set_state(ExtrasForm.video)
            await message.answer("Bu tartib raqami band. Raqam, nom va tavsifni qayta yuboring.")
            return
        await state.clear()
        await message.answer("Video saqlandi." if saved else "Kontent topilmadi.", reply_markup=content.buttons(
            (("📋 Kontent", f"x_manageanime_{data['anime_id']}_0"),),
            (("📢 E’lonni ko‘rib chiqish", f"p_admin_post_{data['anime_id']}"),)))

    @router.callback_query(F.data.regexp(r"^x_caption_[0-9]{1,18}$"))
    async def caption_start(callback, state):
        if not await owner(callback):
            return
        anime_id = int(callback.data.rsplit("_", 1)[1])
        await state.set_data({"anime_id": anime_id})
        await state.set_state(ExtrasForm.caption)
        await callback.message.answer(
            "Birinchi satrda rejimni yuboring: auto, custom yoki none (faqat asosiy caption).\n"
            "Ikkinchi satrda havola: channel, bot yoki -.\n"
            "Custom rejimda keyingi satrlarga caption matnini yozing."
        )

    @router.message(ExtrasForm.caption, F.from_user.id.func(lambda value: value == admin_id()))
    async def caption_save(message, state):
        lines = (message.text or "").strip().split("\n", 2)
        if (len(lines) < 2 or lines[0] not in ("auto", "custom", "none")
                or lines[1] not in ("channel", "bot", "-")
                or (lines[0] == "custom" and (len(lines) < 3 or not lines[2].strip()))):
            await message.answer("Masalan, birinchi satrga auto, ikkinchisiga channel yozing.")
            return
        anime_id = (await state.get_data())["anime_id"]
        text = lines[2].strip() if lines[0] == "custom" else None
        saved = store.save_caption(anime_id, lines[0], text, None if lines[1] == "-" else lines[1])
        await state.clear()
        await message.answer("Caption sozlandi." if saved else "Anime topilmadi.")

    @router.callback_query(F.data.regexp(r"^x_(news|adminnews)_[0-9]{1,8}$"))
    async def news_list(callback, bot):
        _, mode, raw_page = callback.data.split("_")
        admin = mode == "adminnews"
        if not (await owner(callback) if admin else await reader(callback, bot)):
            return
        page = int(raw_page)
        items = store.news(offset=page * PAGE)
        entries = [(content.limited(item["title"], 60), f"x_{'editnews' if admin else 'readnews'}_{item['id']}") for item in items]
        extra = ((("➕ Yangilik yaratish", "x_newnews_0"),),) if admin else ()
        await callback.message.answer("📰 Anime yangiliklari" if entries else "Hozircha yangiliklar yo‘q.",
                                      reply_markup=page_markup(entries, page, f"x_{mode}",
                                                               "p_admin_home" if admin else "back_home", extra))
        if not admin:
            await activity.observe_callback(callback, "news")

    @router.callback_query(F.data.regexp(r"^x_readnews_[0-9]{1,18}$"))
    async def read_news(callback, bot):
        if await reader(callback, bot):
            item = store.news(int(callback.data.rsplit("_", 1)[1]))
            if item:
                await send_news(bot, callback.message.chat.id, item)
                await activity.observe_callback(callback, "news")
            else:
                await callback.message.answer("Yangilik topilmadi.")

    @router.callback_query(F.data.regexp(r"^x_(editnews|newnews|asknews|postnews|delnews|dropnews)_[0-9]{1,18}$"))
    async def news_admin(callback, state, bot):
        if not await owner(callback):
            return
        _, action, raw_id = callback.data.split("_")
        news_id = int(raw_id)
        item = store.news(news_id) if news_id else None
        if action != "newnews" and not item:
            await callback.message.answer("Yangilik topilmadi.")
            return
        if action == "newnews":
            await state.set_data({"news_id": news_id or None})
            await state.set_state(ExtrasForm.news)
            current = (f"\n\n{item['kind']}\n{item['anime_code'] or '-'}\n{item['title']}\n{item['body']}"
                       if item else "")
            await callback.message.answer(
                "Tur (anime, film, ova yoki general), anime kodi yoki -, sarlavha va matnni alohida satrlarda yuboring."
                + current
            )
        elif action == "editnews":
            await send_news(bot, callback.message.chat.id, item)
            await callback.message.answer("Yangilik amallari", reply_markup=content.buttons(
                (("✏️ Tahrirlash", f"x_newnews_{news_id}"), ("🗑 O‘chirish", f"x_delnews_{news_id}")),
                (("📢 Kanalga e’lon qilish", f"x_asknews_{news_id}"),)))
        elif action in ("asknews", "delnews"):
            publish = action == "asknews"
            label = "Kanalga yuborish" if publish else "O‘chirish"
            yes = f"x_{'postnews' if publish else 'dropnews'}_{news_id}"
            icon = "✅" if publish else "🗑"
            await callback.message.answer(f"{label} tasdiqlansinmi?", reply_markup=content.buttons(
                ((f"{icon} {label}", yes), ("❌ Bekor qilish", f"x_editnews_{news_id}"))))
        elif action == "dropnews":
            store.news_action(news_id, "delete")
            await callback.message.answer("Yangilik o‘chirildi.")
        elif store.news_action(news_id, "claim"):
            try:
                await send_news(bot, channel, item)
            except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
                store.news_action(news_id, "release")
                await callback.message.answer("Telegram yuborishni rad etdi.")
            except TelegramAPIError:
                await callback.message.answer("Yuborish natijasi noaniq. Kanalni tekshiring.")
            else:
                store.news_action(news_id, "sent")
                await callback.message.answer("Yangilik kanalga yuborildi.")
        else:
            await callback.message.answer("Yangilik yuborilgan yoki yuborish natijasi tekshirilmoqda.")

    @router.message(ExtrasForm.news, F.from_user.id.func(lambda value: value == admin_id()))
    async def news_fields(message, state):
        lines = (message.text or "").strip().split("\n", 3)
        if len(lines) != 4 or lines[0] not in LABELS or not 1 <= len(lines[2].strip()) <= 100 or not lines[3].strip() or content.caption_units(lines[3]) > 750:
            await message.answer("Tur, anime ID yoki -, sarlavha va 1–750 belgili matnni alohida satrlarda yuboring.")
            return
        anime_id = None
        if lines[1] != "-":
            item = store.by_code(lines[1], "anime")
            if not item:
                await message.answer("Anime kodi topilmadi.")
                return
            anime_id = item["id"]
        await state.update_data(anime_id=anime_id, kind=lines[0], title=lines[2].strip(), body=lines[3].strip())
        await state.set_state(ExtrasForm.news_photo)
        await message.answer("Rasm yuboring, rasmni olib tashlash uchun /skip yoki saqlash uchun /keep yozing.")

    @router.message(ExtrasForm.news_photo, F.from_user.id.func(lambda value: value == admin_id()))
    async def news_photo(message, state):
        data = await state.get_data()
        if message.photo:
            photo = message.photo[-1].file_id
        elif message.text in ("/skip", "/keep"):
            existing = store.news(data["news_id"]) if data["news_id"] else None
            photo = existing["photo"] if existing and message.text == "/keep" else None
        else:
            await message.answer("Rasm, /skip yoki /keep yuboring.")
            return
        saved = store.save_news(**data, photo=photo)
        await state.clear()
        await message.answer("Yangilik saqlandi." if saved else "Yangilik topilmadi.",
                             reply_markup=content.buttons((("📰 Yangiliklar", "x_adminnews_0"),)))

    @router.callback_query(F.data.regexp(r"^x_comment_[0-9]{1,18}$"))
    async def comment_start(callback, state, bot):
        if not await reader(callback, bot):
            return
        anime_id = int(callback.data.rsplit("_", 1)[1])
        item = store.anime_content(anime_id)
        if not item or not item["visible"]:
            await callback.message.answer("Anime topilmadi.")
            return
        await state.set_data({"anime_id": anime_id})
        await state.set_state(ExtrasForm.comment)
        await callback.message.answer("Izohingiz, Telegram ismingiz va mavjud username administratorga ko‘rinadi. "
                                      "Moderatorlik kanali sozlangan bo‘lsa, nusxa u yerga ham boradi. "
                                      "Rozilik bersangiz, izohni yuboring. Bekor qilish uchun /cancel yozing.")

    @router.message(ExtrasForm.comment)
    async def comment_save(message, state, bot):
        if message.chat.type != "private" or not await is_subscribed(bot, message.from_user.id):
            await state.clear()
            return
        text = (message.text or "").strip()
        if not 1 <= len(text) <= 1500:
            await message.answer("Izohni 1–1500 belgi oralig‘ida yuboring.")
            return
        anime_id = (await state.get_data())["anime_id"]
        user = message.from_user
        result = store.add_comment(anime_id, user.id, user.full_name, user.username, text)
        if result == "limited":
            await message.answer("Izohlar orasida bir daqiqa kuting.")
            return
        await state.clear()
        if result == "missing":
            await message.answer("Anime topilmadi.")
            return
        await message.answer("Izoh administrator uchun saqlandi.")
        moderator = os.getenv("COMMENT_MODERATION_CHAT_ID", "").strip()
        if moderator and moderator.casefold() not in {str(channel).casefold(), "@anivrum"}:
            item = store.anime_content(anime_id)
            heading = f"{item['title']} ({item['code']})" if item else str(anime_id)
            username = f" @{user.username}" if user.username else ""
            try:
                await bot.send_message(moderator, f"{heading}\n{user.full_name}{username}\n{text}", parse_mode=None)
            except TelegramAPIError:
                track("error")

    @router.callback_query(F.data.regexp(r"^x_(comments|viewcomment|delcomment|dropcomment)_[0-9]{1,18}$"))
    async def comment_admin(callback):
        if not await owner(callback):
            return
        _, action, raw_id = callback.data.split("_")
        value = int(raw_id)
        if action == "comments":
            items = store.comments(offset=value * PAGE)
            entries = [(content.limited(f"{item['anime_title']} · {item['name']}", 55),
                        f"x_viewcomment_{item['id']}") for item in items]
            await callback.message.answer("💬 Izohlar" if entries else "Hozircha izohlar yo‘q.",
                                          reply_markup=page_markup(entries, value, "x_comments", "p_admin_home"))
            return
        item = store.comments(value)
        if not item:
            await callback.message.answer("Izoh topilmadi.")
        elif action == "dropcomment":
            store.delete_comment(value)
            await callback.message.answer("Izoh o‘chirildi.")
        elif action == "delcomment":
            await callback.message.answer("Izoh o‘chirilsinmi?", reply_markup=content.buttons(
                (("🗑 O‘chirish", f"x_dropcomment_{value}"), ("❌ Bekor qilish", f"x_viewcomment_{value}"))))
        else:
            username = f" @{item['username']}" if item["username"] else ""
            await callback.message.answer(
                f"{item['anime_title']} · {item['anime_code']}\n{item['name']}{username}\n"
                f"{item['created_at']} UTC\n\n{item['body']}", parse_mode=None,
                reply_markup=content.buttons((("🗑 O‘chirish", f"x_delcomment_{value}"),)),
            )

    @router.callback_query(F.data == "x_stats")
    async def statistics(callback):
        if not await owner(callback):
            return
        users, metrics, opened, episodes = store.owner_statistics()
        rows = ["📊 Bot statistikasi", f"Jami foydalanuvchilar: {users[0]}", f"Bugun faol (UTC): {users[1]}"]
        rows.extend(f"{label}: {metrics.get(key, 0)}" for key, label in
                    (("film", "Yuborilgan filmlar"), ("ova", "Yuborilgan OVA"), ("search", "Qidiruvlar"), ("error", "Xatolar")))
        rows.append("\nEng ko‘p ochilgan animelar")
        rows.extend(f"{item['title']} · {item['total']}" for item in opened)
        if not opened:
            rows.append("Ma’lumot yo‘q.")
        rows.append("\nEng ko‘p yuborilgan qismlar")
        rows.extend(f"{item['title']} · {item['season_number']}-fasl · {item['episode_number']}-qism · {item['total']}"
                    for item in episodes)
        if not episodes:
            rows.append("Ma’lumot yo‘q.")
        await callback.message.answer("\n".join(rows), parse_mode=None)
