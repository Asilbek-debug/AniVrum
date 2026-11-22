"""Standalone videos, news, comments, and owner statistics."""

import asyncio
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
    video_create = State()
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
                await asyncio.to_thread(store.active_user, user.id)
                today = datetime.now(UTC).date()
                if self.last_prune != today:
                    await asyncio.to_thread(store.prune_statistics)
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
                                 protect_content=protected, cover=video["poster_file_id"])
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
                                      reply_markup=page_markup(entries, page, "x_manage", "p_admin_home",
                                                               ((("➕ Yangi film yoki OVA", "x_newextra"),),)))

    @router.callback_query(F.data == "x_newextra")
    async def choose_extra_kind(callback, state):
        if not await owner(callback):
            return
        await state.clear()
        await callback.message.answer("Qo‘shiladigan kontent turini tanlang.", reply_markup=content.buttons(
            ((LABELS["film"], "x_scope_film"), (LABELS["ova"], "x_scope_ova")),
            (("⬅️ Orqaga", "x_manage_0"),),
        ))

    @router.callback_query(F.data.regexp(r"^x_scope_(film|ova)$"))
    async def choose_extra_scope(callback):
        if not await owner(callback):
            return
        kind = callback.data.rsplit("_", 1)[1]
        await callback.message.answer("Kontent qayerda ko‘rinsin?", reply_markup=content.buttons(
            (("Mustaqil katalog elementi", f"x_indraft_{kind}"),),
            (("Mavjud anime tarkibida", f"x_link_{kind}_0"),),
            (("⬅️ Orqaga", "x_newextra"),),
        ))

    @router.callback_query(F.data.regexp(r"^x_indraft_(film|ova)$"))
    async def independent_draft(callback, state):
        if not await owner(callback):
            return
        kind = callback.data.rsplit("_", 1)[1]
        await state.set_data({"kind": "anime", "initial_video": kind})
        await state.set_state(add_anime.title)
        await callback.message.answer(f"{LABELS[kind]} nomini yuboring.", reply_markup=content.buttons(
            (("❌ Bekor qilish", "v5_anime_cancel_0"),),
        ))

    @router.callback_query(F.data.regexp(r"^x_link_(film|ova)_[0-9]{1,8}$"))
    async def choose_extra_anime(callback):
        if not await owner(callback):
            return
        _, _, kind, raw_page = callback.data.split("_")
        page = int(raw_page)
        items = await asyncio.to_thread(store.admin_catalog, "", page * PAGE, PAGE + 1)
        entries = [(content.limited(item["title"], 55), f"x_add_{kind}_{item['id']}") for item in items]
        await callback.message.answer("Animeni tanlang." if entries else "Anime topilmadi.",
                                      reply_markup=page_markup(entries, page, f"x_link_{kind}", f"x_scope_{kind}"))

    @router.callback_query(F.data.regexp(r"^x_independent_[0-9]{1,8}$"))
    async def show_independent(callback, bot):
        if not await reader(callback, bot):
            return
        page = int(callback.data.rsplit("_", 1)[1])
        items = await asyncio.to_thread(store.independent_catalog, page * PAGE, PAGE + 1)
        entries = [(content.limited(item["title"], 55), f"anime_detail_{item['id']}") for item in items]
        await content.edit_text(callback.message, "🎬 Mustaqil filmlar va OVA" if entries else "Hozircha kontent yo‘q.",
                                reply_markup=page_markup(entries, page, "x_independent", "anime"))

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
            fields = {key: video[key] for key in (*[field for field, _ in VIDEO_STEPS[:-1]],
                                                "anime_id", "kind", "media_type")}
            season = await asyncio.to_thread(db.get_season_by_id, video["season_id"]) if video["season_id"] else None
            await state.set_data({**fields, "video_id": video["id"],
                                  "season_number": season["season_number"] if season else None})
            await state.set_state(ExtrasForm.video_create)
            await video_step(callback.message, state, 1)

    @router.callback_query(F.data.regexp(r"^x_movevideo_[0-9]{1,18}$"))
    async def select_video_location(callback, state):
        if not await owner(callback):
            return
        video = await asyncio.to_thread(store.standalone_video, int(callback.data.rsplit("_", 1)[1]))
        if video:
            await state.set_data({"anime_id": video["anime_id"], "move_video_id": video["id"]})
            await state.set_state(ExtrasForm.video_create)
            await video_step(callback.message, state, 0)

    VIDEO_STEPS = (
        ("season_id", "📺 Fasl raqamini kiriting yoki fasldan tashqarida saqlang."),
        ("title", "✏️ Film yoki OVA nomini yuboring."),
        ("number", "🔢 Film yoki OVA raqamini yuboring."),
        ("genre", "🎭 Janrini yuboring."),
        ("country", "🌍 Davlatini yuboring."),
        ("release_year", "📅 Chiqarilgan yilini yuboring."),
        ("description", "📝 Tavsifini yuboring."),
        ("poster_file_id", "🖼 Poster rasmini yuboring."),
        ("file_id", "📤 Video yoki video hujjatini yuboring."),
        ("review", "Saqlashdan oldin tekshiring."),
    )

    async def video_step(message, state, step):
        data = await state.update_data(video_step=step)
        _, prompt = VIDEO_STEPS[step]
        rows = []
        if step == 0:
            rows.append((("Anime tarkibida, fasldan tashqarida", "xv_skip_0"),))
        if 2 <= step <= 7 or data.get("video_id") and 1 <= step <= 8:
            label = "⏭ Avvalgisini saqlash" if data.get("video_id") else "⏭ O‘tkazish"
            rows.append(((label, f"xv_skip_{step}"),))
        if step == 1 and data.get("video_id"):
            video_id = data["video_id"]
            rows.append((("🟠 Joyini o‘zgartirish", f"x_movevideo_{video_id}"),
                         ("🗑 O‘chirish", f"x_deletevideo_{video_id}")))
        if step == 9:
            label = LABELS[data["kind"]]
            prompt = (f"{label} · {data['title']}\n🔢 Raqam: {data.get('number') or 'Avtomatik'}"
                      f"\n📺 Joyi: {data.get('season_number') or 'Fasldan tashqarida'}"
                      f"\n🎭 Janr: {data.get('genre') or '—'}\n🌍 Davlat: {data.get('country') or '—'}"
                      f"\n📅 Yil: {data.get('release_year') or '—'}"
                      f"\n🖼 Poster: {'Bor' if data.get('poster_file_id') else 'Yo‘q'}\n✅ Video qabul qilindi.")
            if data.get("description"):
                prompt += f"\n\n{data['description']}"
            rows.append((("✅ Saqlash va tasdiqlash", "xv_save_9"),))
        if step and not (step == 1 and data.get("video_id")):
            rows.append((("⬅️ Orqaga", f"xv_back_{step}"),))
        rows.append((("❌ Bekor qilish", f"xv_cancel_{step}"),))
        await message.answer(prompt, parse_mode=None, reply_markup=content.buttons(*rows))

    async def set_video_location(message, state, season):
        data = await state.get_data()
        season_id = season["id"] if season else None
        if data.get("move_video_id"):
            changed = await asyncio.to_thread(store.move_video, data["move_video_id"], season_id)
            await state.clear()
            await message.answer("Video joyi saqlandi." if changed else "Video yoki fasl topilmadi.")
            return
        await state.update_data(season_id=season_id, season_number=season["season_number"] if season else None)
        await video_step(message, state, 1)

    @router.callback_query(F.data.regexp(r"^x_add_(film|ova)_[0-9]{1,18}$"))
    async def add_video(callback, state):
        if not await owner(callback):
            return
        _, _, kind, raw_id = callback.data.split("_")
        if not store.anime_content(int(raw_id)):
            await callback.message.answer("Anime topilmadi.")
            return
        await state.set_data({"anime_id": int(raw_id), "kind": kind})
        await state.set_state(ExtrasForm.video_create)
        await video_step(callback.message, state, 0)

    @router.callback_query(StateFilter(ExtrasForm.video_create), F.data.regexp(r"^xv_(skip|save|back|cancel)_[0-9]$"))
    async def video_create_navigation(callback, state):
        if not await owner(callback):
            return
        _, action, raw_step = callback.data.split("_")
        step = int(raw_step)
        data = await state.get_data()
        if data.get("video_step") != step:
            return
        message = callback.message
        if action == "cancel":
            await state.clear()
            await message.answer("Jarayon bekor qilindi.")
        elif action == "back" and step and not (step == 1 and data.get("video_id")):
            await video_step(message, state, step - 1)
        elif action == "skip" and step == 0:
            await set_video_location(message, state, None)
        elif action == "skip" and (2 <= step <= 7 or data.get("video_id") and 1 <= step <= 8):
            if not data.get("video_id"):
                await state.update_data({VIDEO_STEPS[step][0]: None})
            await video_step(message, state, step + 1)
        elif action == "save" and step == 9:
            args = {field: data.get(field) for field, _ in VIDEO_STEPS[:-1]}
            args.update(anime_id=data["anime_id"], kind=data["kind"], media_type=data["media_type"],
                        video_id=data.get("video_id"))
            try:
                saved = await asyncio.to_thread(store.save_video, **args)
            except db.INTEGRITY_ERRORS:
                await message.answer("Bu raqam band. Boshqa raqam kiriting.")
                await video_step(message, state, 2)
                return
            except db.DATABASE_ERRORS:
                await message.answer("Video saqlanmadi. Keyinroq qayta urinib ko‘ring.")
                return
            if not saved:
                await message.answer("Anime yoki fasl topilmadi.")
                await video_step(message, state, 0)
                return
            await state.clear()
            anime = data["anime_id"]
            await message.answer("✅ Video saqlandi.", reply_markup=content.buttons(
                (("➕ Yana film", f"x_add_film_{anime}"), ("➕ Yana OVA", f"x_add_ova_{anime}")),
                (("🏁 Yakunlash", f"x_manageanime_{anime}_0"),),
                (("📢 E’lonni ko‘rib chiqish", f"p_admin_post_{anime}"),),
            ))

    @router.message(ExtrasForm.video_create, F.from_user.id.func(lambda value: value == admin_id()))
    async def video_create_input(message, state):
        data = await state.get_data()
        step = data["video_step"]
        raw = (message.text or "").strip()
        if step == 0:
            if raw == "/skip":
                await set_video_location(message, state, None)
                return
            if content.numeric_id(raw):
                season = await asyncio.to_thread(db.get_season_by_number, data["anime_id"], int(raw))
                if season:
                    await set_video_location(message, state, season)
                    return
            await message.answer("Bunday fasl topilmadi. Fasl raqamini kiriting.")
            return
        if step == 9:
            await message.answer("Saqlash tugmasini bosing yoki orqaga qayting.")
            return
        if raw == "/skip" and data.get("video_id") and 1 <= step <= 8:
            value = data.get(VIDEO_STEPS[step][0])
        elif raw == "/skip" and 2 <= step <= 7:
            value = None
        elif step in (1, 3, 6) and 1 <= len(raw) <= (2500 if step == 6 else 100):
            value = raw
        elif step == 2 and content.numeric_id(raw) and 0 < int(raw) <= 2147483647:
            value = int(raw)
        elif step == 4 and (country := content.normalize_country(raw)):
            value = country
        elif step == 5 and content.numeric_id(raw) and 1900 <= int(raw) <= 2100:
            value = int(raw)
        elif step == 7 and message.photo:
            value = message.photo[-1].file_id
        elif step == 8 and (media := content.pick_media(message))[0]:
            value = media[0].file_id
            await state.update_data(media_type=media[1])
        else:
            await message.answer("Kiritilgan qiymat mos kelmadi.")
            await video_step(message, state, step)
            return
        await state.update_data({VIDEO_STEPS[step][0]: value})
        await video_step(message, state, step + 1)

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
        users, metrics, opened, episodes = await asyncio.to_thread(store.owner_statistics)
        rows = ["📊 AniVrum statistikasi", f"👥 Hisobda saqlangan foydalanuvchilar: {users[0]}",
                f"🟢 Bugun faol (Toshkent vaqti): {users[1]}",
                f"📅 Oxirgi 7 kunda faol: {metrics['active_7']}",
                f"📅 Oxirgi 30 kunda faol: {metrics['active_30']}", ""]
        rows.extend(f"{label}: {metrics.get(key, 0)}" for key, label in (
            ("anime_count", "🎬 Animelar"), ("season_count", "📺 Fasllar"),
            ("episode_count", "▶️ Qismlar"), ("film_count", "🎞 Filmlar"), ("ova_count", "⭐ OVA"),
            ("episode_sent", "📤 Yuborilgan qismlar"), ("film", "📤 Yuborilgan filmlar"),
            ("ova", "📤 Yuborilgan OVA"), ("search", "🔎 Qidiruvlar"), ("error", "⚠️ Qayd etilgan xatolar"),
        ))
        sent = sum(metrics.get(key, 0) for key in ("episode_sent", "film", "ova"))
        rows.append(f"📤 Jami yuborilgan videolar: {sent}")
        rows.append("\nEng ko‘p ochilgan animelar")
        rows.extend(f"{item['title']} · {item['total']}" for item in opened)
        if not opened:
            rows.append("Ma’lumot yo‘q.")
        rows.append("\nEng ko‘p yuborilgan qismlar")
        rows.extend(f"{item['title']} · {item['season_number']}-fasl · {item['episode_number']}-qism · {item['total']}"
                    for item in episodes)
        if not episodes:
            rows.append("Ma’lumot yo‘q.")
        if metrics.get("busiest_hours"):
            rows.append("\nEng ko‘p qism yuborilgan soatlar (Toshkent vaqti)")
            rows.extend(f"{hour:02d}:00–{hour:02d}:59 · {count} ta qism"
                        for hour, count in metrics["busiest_hours"])
        await callback.message.answer("\n".join(rows), parse_mode=None)
