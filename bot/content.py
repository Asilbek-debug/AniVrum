"""Katalog, media sahifalari va kanal e'lonlari uchun Telegram oqimlari."""

import asyncio
import logging
import unicodedata
from html import escape
from pathlib import PurePath
from secrets import token_hex

from aiogram import F, Router
from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from database import db
from database import catalog as store

log = logging.getLogger(__name__)
BRAND_NAME = "AniVrum | Anime"
PAGE_SIZE = 12
CAPTION_DESCRIPTION_LENGTH = 230
PHOTO_CAPTION_LIMIT = 1024
COUNTRY_HINT = "Davlat nomlarini vergul bilan ajratib yozing (1–100 belgi). Masalan: Yaponiya, Xitoy"
DIVIDER = "━━━━━━━━━━━━━━━━"


class ContentForm(StatesGroup):
    poster = State()
    seasons = State()
    edit_media = State()
    reconcile = State()
    channel_post = State()
    channel_confirm = State()


def button(*, text, callback_data=None, url=None):
    action = callback_data or ""
    style = None
    if not text.startswith(("⬅", "🏠", "❌ Bekor", "❌ Yo")):
        if text.startswith("🗑") or action.startswith((
            "manage_delete_", "manage_confirmdelete_", "season_delete_", "season_confirmdelete_",
            "episode_delete_", "episode_confirmdelete_", "p_admin_askposter_", "p_admin_deleteposter_",
            "p_admin_askreset_", "p_admin_reset_", "p_fav_remove_", "fav_remove_",
            "x_deletevideo_", "x_confirmvideo_", "x_delnews_", "x_dropnews_",
            "x_delcomment_", "x_dropcomment_",
        )):
            style = "danger"
        elif text.startswith(("➕", "✅")) or action.startswith((
            "admin_add_", "addseason_", "p_fav_add_", "x_add_", "x_newnews_0",
        )):
            style = "success"
        elif text.startswith("📥") or action.startswith((
            "check_subscription", "anime_detail_", "season_detail_", "episode_detail_",
            "choose_parts_", "numbered_parts_", "watchpart_", "download_seasons_", "downloadall_",
            "uploadseason_", "x_kind_", "x_video_", "x_videos_", "x_readnews_",
            "p_compose_text", "p_compose_photo", "p_compose_video", "p_admin_link_",
            "episode_replace_",
        )) or text.startswith(("Keyingi faslni", "🔗 Kanalga obuna")):
            style = "primary"
    return InlineKeyboardButton(text=text, callback_data=callback_data, url=url, style=style)


def buttons(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(text=label, callback_data=value) for label, value in row]
        for row in rows
    ])


def pick_media(message):
    if message.video:
        return message.video, "video"
    if message.document:
        mime = message.document.mime_type or ""
        extension = PurePath(message.document.file_name or "").suffix.lower()
        if mime.startswith("video/") or (
            mime in ("", "application/octet-stream") and extension in (".mp4", ".mkv", ".webm", ".mov", ".avi")
        ):
            return message.document, "document"
    return None, None


async def send_media(bot, chat_id, file_id, media_type, caption, *, protect_content, retry=True):
    if media_type == "document":
        method = bot.send_document
        fields = {"document": file_id}
    else:
        method = bot.send_video
        fields = {"video": file_id}
    try:
        return await method(chat_id=chat_id, caption=caption, protect_content=protect_content, **fields)
    except TelegramRetryAfter as error:
        if not retry:
            raise
        await asyncio.sleep(error.retry_after)
        return await method(chat_id=chat_id, caption=caption, protect_content=protect_content, **fields)


async def clear_buttons(message):
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        log.info("Avvalgi xabarning tugmalari yopilmadi.")


async def edit_text(message, text, **kwargs):
    if message.photo:
        await message.answer(text, **kwargs)
        await clear_buttons(message)
        return
    await message.edit_text(text, **kwargs)


def numeric_id(value):
    return value.isascii() and value.isdigit() and len(value) <= 18


def limited(value, limit):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def normalize_country(value):
    value = unicodedata.normalize("NFC", value or "")
    names = [" ".join(part.split()) for part in value.split(",")]
    if not all(name and any(char.isalpha() for char in name) for name in names):
        return None
    country = ", ".join(names)
    if len(country) > 100 or any(
        not (char.isalpha() or unicodedata.category(char).startswith("M") or char in " ,-'’‘ʻʼ–")
        for char in country
    ):
        return None
    return country


def caption_units(value):
    return len(value.encode("utf-16-le")) // 2


def truncate_caption(value, units):
    if caption_units(value) <= units:
        return value
    prefix = value.encode("utf-16-le")[:2 * (units - 1)].decode("utf-16-le", errors="ignore")
    return prefix.rstrip() + "…"


def caption(item, suffix=""):
    header = f"🎬 {BRAND_NAME.upper()}"
    title = limited(" ".join(item["title"].split()).upper(), 100)
    rows = [(icon, label, value) for icon, label, value in (
        ("🎭", "Janr", limited(" ".join((item["genre"] or "").split()), 160)),
        ("🌍", "Davlat", limited((item["country"] or "").strip(), 100)),
        ("📅", "Yil", str(item["release_year"] or "")),
    ) if value]
    if item["season_count"]:
        rows.extend([("📺", "Fasllar", f"{item['season_count']} ta"),
                     ("🎞", "Qismlar", f"{item['episode_count']} ta")])
    keys = item.keys()
    for key, icon, label in (("film_count", "🎞", "Filmlar"), ("ova_count", "⭐", "OVA")):
        if key in keys and item[key]:
            rows.append((icon, label, f"{item[key]} ta"))
    rows.append(("🔢", "Kod", limited(item["code"], 58)))
    description = " ".join((item["description"] or "").split())
    description_header = f"\n\n📖 QISQACHA TAVSIF\n\n" if description else ""
    footer = f"\n\n{DIVIDER}\n📢 @AniVrum{suffix}"
    plain_rows = "\n".join(f"{icon} {label}: {value}" for icon, label, value in rows)
    plain_prefix = f"{header}\n\n{title}\n\n{DIVIDER}\n{plain_rows}{description_header}"
    remaining = PHOTO_CAPTION_LIMIT - caption_units(plain_prefix + footer)
    formatted_rows = "\n".join(
        f"{icon} <b>{label}:</b> {escape(value)}" for icon, label, value in rows
    )
    formatted_description = description_header.replace("QISQACHA TAVSIF", "<b>QISQACHA TAVSIF</b>")
    return (
        f"<b>{header}</b>\n\n<b>{escape(title)}</b>\n\n{DIVIDER}\n{formatted_rows}"
        f"{formatted_description}{escape(truncate_caption(description, remaining))}{footer}"
    )


def video_caption(item, season_number=None, episode_number=None, standalone=None):
    mode = item["caption_mode"]
    if mode == "none":
        return None
    if standalone:
        icon = "🎞" if standalone["kind"] == "film" else "⭐"
        label = "Film" if standalone["kind"] == "film" else "OVA"
        text = f"{item['title']}\n{icon} {label} {standalone['number']} ? {standalone['title']}"
    else:
        text = f"{item['title']}\n📺 {season_number}-fasl\n🎬 {episode_number}-qism"
    if mode == "custom" and item["caption_text"]:
        text += f"\n\n{item['caption_text']}"
    footer = {"channel": "📢 @AniVrum", "bot": "https://t.me/AniVrum_bot"}.get(item["caption_link"])
    if footer:
        text = truncate_caption(text, PHOTO_CAPTION_LIMIT - caption_units(footer) - 2)
        return f"{text}\n\n{footer}" if text else footer
    return truncate_caption(text, PHOTO_CAPTION_LIMIT) or None


def channel_keyboard(item):
    return InlineKeyboardMarkup(inline_keyboard=[[button(
        text="📥 YUKLAB OLISH",
        url=f"https://t.me/AniVrum_bot?start=animeid_{item['id']}",
    )]])


def detail_buttons(item, user_id):
    anime_id = item["id"]
    actions = [
        (("▶️ Qismlarni tanlash", f"choose_parts_{anime_id}"),),
        (("📥 Butun faslni olish", f"download_seasons_{anime_id}"),),
    ]
    if not item["season_count"]:
        actions.clear()
    standalone = store.standalone_videos(anime_id, limit=9)
    for video in standalone[:8]:
        icon = "🎞" if video["kind"] == "film" else "⭐"
        actions.append(((f"{icon} {video['number']} ? {limited(video['title'], 42)}",
                         f"x_video_{video['id']}"),))
    if len(standalone) > 8:
        actions.append((("🎞 Barcha film va OVA", f"x_videos_{anime_id}_0"),))
    actions.append((("💬 Anime haqida izoh qoldirish", f"x_comment_{anime_id}"),))
    back = "anime_az"
    if db.is_favorite(user_id, anime_id):
        favorite = ("❤️ Sevimlilardan olib tashlash", f"p_fav_remove_{anime_id}")
    else:
        favorite = ("⭐ Sevimlilarga qo‘shish", f"p_fav_add_{anime_id}")
    description = item["description"] or ""
    if len(description) > CAPTION_DESCRIPTION_LENGTH or caption_units(description) > 320:
        actions.append((("To‘liq tavsif", f"p_desc_{anime_id}"),))
    return buttons(*actions, (favorite,), (("Sevimlilarim", "favorites"), ("⬅️ Orqaga", back)))


async def show_detail(message, user_id, anime_id, replace=False, *, protect_content=True):
    item = store.anime_content(anime_id)
    if not item or not item["visible"]:
        await message.answer("Kontent topilmadi.")
        return
    try:
        store.metric("open", anime_id)
    except db.DATABASE_ERRORS:
        log.warning("Anime ochilishi statistikaga yozilmadi.")
    markup = detail_buttons(item, user_id)
    suffix = f"\n\nYuborilgan videolar: {item['views']}"
    await show_content(message, item, caption(item, suffix=suffix), markup, replace,
                       protect_content=protect_content)


async def show_content(message, item, text, markup, replace=False, *, protect_content=False):
    if item["poster_file_id"]:
        try:
            await message.answer_photo(item["poster_file_id"], caption=text, parse_mode="HTML",
                                       protect_content=protect_content,
                                       reply_markup=markup)
            if replace:
                await clear_buttons(message)
            return
        except TelegramBadRequest:
            log.info("Poster bilan ishlashda Telegram so‘rovni rad etdi.")
    if replace:
        await edit_text(message, text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def publish(bot, channel, anime_id, previous_post=None):
    status, item = store.claim_announcement(anime_id, previous_post)
    if status != "claimed":
        return status
    try:
        options = dict(parse_mode="HTML", reply_markup=channel_keyboard(item), protect_content=False)
        if item["poster_file_id"]:
            post = await bot.send_photo(channel, item["poster_file_id"], caption=caption(item), **options)
        else:
            post = await bot.send_message(channel, caption(item), **options)
    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
        if previous_post is None:
            store.finish_announcement(anime_id, "failed")
        else:
            store.restore_announcement(anime_id, previous_post)
        log.warning("Kanal e’loni rad etildi. Kontent ID: %s", anime_id)
        return "failed"
    except TelegramAPIError:
        log.warning("Kanal e’loni natijasi noma’lum. Kontent ID: %s", anime_id)
        return "sending"
    store.finish_announcement(anime_id, "sent", post.chat.id, post.message_id, item["poster_file_id"],
                              is_text=not item["poster_file_id"])
    return "sent"


def admin_menu():
    return buttons(
        (("➕ Anime qo‘shish", "admin_add_anime"), ("➕ Fasl qo‘shish", "admin_add_season")),
        (("🎞 Film / ⭐ OVA", "x_manage_0"), ("📰 Anime yangiliklari", "x_adminnews_0")),
        (("💬 Izohlar", "x_comments_0"), ("📊 Bot statistikasi", "x_stats")),
        (("📋 Kontent", "p_admin_list_manage_0"), ("📺 Fasllar", "p_admin_list_seasons_0")),
        (("▶️ Qismlar", "p_admin_list_parts_0"), ("🖼 Posterlar", "p_admin_list_poster_0")),
        (("📢 E’lonlar", "p_admin_list_post_0"), ("📊 Statistika", "p_admin_stats")),
        (("📤 Kanalga post yuborish", "p_compose_menu"),),
        (("⚙️ Sozlamalar", "p_admin_settings"),),
    )


async def send_channel_post(bot, chat_id, draft, reply_markup=None):
    options = dict(chat_id=chat_id, parse_mode=None, protect_content=False, reply_markup=reply_markup)
    if draft["kind"] == "text":
        return await bot.send_message(text=draft["text"], **options)
    if draft["kind"] == "photo":
        return await bot.send_photo(photo=draft["file_id"], caption=draft["text"], **options)
    return await bot.send_video(video=draft["file_id"], caption=draft["text"], **options)


def channel_post_error(error):
    if isinstance(error, TelegramRetryAfter):
        return f"Telegram yuborishni vaqtincha chekladi. {error.retry_after} soniyadan keyin urinib ko‘ring."
    if isinstance(error, TelegramForbiddenError):
        return "Botda kanalga post yuborish huquqi yo‘q."
    if isinstance(error, TelegramBadRequest):
        reason = error.message.lower()
        if "identifier" in reason or "file" in reason or "media" in reason:
            return "Telegram media faylini qabul qilmadi. Rasm yoki videoni qayta yuboring."
        if "too long" in reason:
            return "Telegram matn uzunligi chegarasidan oshildi."
        if "chat" in reason or "rights" in reason:
            return "Telegram kanalga kirishni rad etdi. Kanal manzili va bot huquqlarini tekshiring."
        return "Telegram post formatini rad etdi. Matn yoki media faylini tekshiring."
    return "Yuborish natijasi noma’lum. Qayta urinishdan oldin kanalni qo‘lda tekshiring."


def install(router: Router, admin_id, channel, is_subscribed, add_anime_state):
    active_publications = set()

    async def channel_admin(callback):
        if callback.from_user.id == admin_id():
            return True
        await callback.answer("Bu bo‘lim administrator uchun.", show_alert=True)
        return False

    async def prepare_channel_confirmation(state, draft, confirm_label):
        nonce = token_hex(8)
        await state.set_data({"channel_draft": draft, "channel_nonce": nonce})
        await state.set_state(ContentForm.channel_confirm)
        return buttons(((confirm_label, f"p_channel_send_{nonce}"),
                        ("❌ Bekor qilish", f"p_channel_cancel_{nonce}")),)

    @router.callback_query(F.data.regexp(r"^p_compose_(menu|text|photo|video)$"))
    async def compose(callback, state):
        if not await channel_admin(callback):
            return
        await state.clear()
        kind = callback.data.rsplit("_", 1)[-1]
        await callback.answer()
        if kind == "menu":
            await edit_text(callback.message, "Kanal posti turini tanlang.", reply_markup=buttons(
                (("📝 Matn", "p_compose_text"), ("🖼 Rasm", "p_compose_photo"), ("🎬 Video", "p_compose_video")),
                (("⬅️ Admin panel", "p_admin_home"),),
            ))
            return
        await state.set_data({"channel_kind": kind})
        await state.set_state(ContentForm.channel_post)
        prompt = {
            "text": "Post matnini yuboring.",
            "photo": "Rasm yuboring. Rasm ostidagi izoh ixtiyoriy.",
            "video": "Video yuboring. Video ostidagi izoh ixtiyoriy.",
        }[kind]
        await callback.message.answer(f"{prompt}\nBekor qilish: /cancel")

    @router.message(ContentForm.channel_post)
    async def preview_post(message, state, bot):
        if message.from_user.id != admin_id():
            return
        data = await state.get_data()
        kind = data["channel_kind"]
        file_id = None
        if kind == "text" and message.text and message.text.strip():
            text = message.text
        elif kind == "photo" and message.photo:
            file_id, text = message.photo[-1].file_id, message.caption
        elif kind == "video" and message.video:
            file_id, text = message.video.file_id, message.caption
        else:
            await message.answer("Tanlangan turdagi xabarni yuboring yoki /cancel yozing.")
            return
        limit = 4096 if kind == "text" else PHOTO_CAPTION_LIMIT
        if caption_units(text or "") > limit:
            await message.answer(f"Matnni {limit} belgigacha qisqartiring.")
            return
        draft = {"kind": kind, "text": text, "file_id": file_id}
        markup = await prepare_channel_confirmation(state, draft, "✅ Kanalga joylash")
        try:
            await send_channel_post(bot, message.chat.id, draft, markup)
        except TelegramAPIError as error:
            await state.set_data({"channel_kind": kind})
            await state.set_state(ContentForm.channel_post)
            await message.answer(channel_post_error(error))

    @router.callback_query(F.data.regexp(r"^p_repeat_[0-9]{1,18}$"))
    async def preview_repeat(callback, state):
        if not await channel_admin(callback):
            return
        anime_id = int(callback.data.rsplit("_", 1)[-1])
        record = store.announcement(anime_id)
        item = store.anime_content(anime_id)
        if not item or not record or record["status"] not in ("sent", "missing"):
            await callback.answer("E’lon holati o‘zgargan. E’lonlar bo‘limini qayta oching.", show_alert=True)
            return
        if not item["poster_file_id"]:
            await callback.answer("Qayta yuborish uchun poster qo‘shing.", show_alert=True)
            return
        draft = {"kind": "repeat", "anime_id": anime_id, "status": record["status"],
                 "message_id": record["message_id"]}
        markup = await prepare_channel_confirmation(state, draft, "✅ Kanalga yuborish")
        await callback.answer()
        await show_content(callback.message, item, caption(item), markup)

    @router.callback_query(F.data.regexp(r"^p_channel_(send|cancel)_[0-9a-f]{16}$"))
    async def finish_channel_post(callback, state, bot):
        if not await channel_admin(callback):
            return
        _, _, action, nonce = callback.data.split("_")
        data = await state.get_data()
        if await state.get_state() != ContentForm.channel_confirm.state or data.get("channel_nonce") != nonce:
            await callback.answer("Bu tasdiqlash tugmasi eskirgan.", show_alert=True)
            return
        draft = data["channel_draft"]
        await state.clear()
        await callback.answer()
        await clear_buttons(callback.message)
        if action == "cancel":
            await callback.message.answer("Post yuborish bekor qilindi.")
            return
        if draft["kind"] != "repeat":
            try:
                await send_channel_post(bot, channel, draft)
            except TelegramAPIError as error:
                await callback.message.answer(channel_post_error(error))
            else:
                await callback.message.answer("Post kanalga joylandi.")
            return
        anime_id = draft["anime_id"]
        if anime_id in active_publications:
            await callback.message.answer("Bu e’lon hozir yuborilmoqda. Natijasini e’lonlar bo‘limida tekshiring.")
            return
        active_publications.add(anime_id)
        try:
            status = await publish(bot, channel, anime_id, (draft["status"], draft["message_id"]))
        finally:
            active_publications.discard(anime_id)
        outcome = {
            "sent": "Kanalga yangi post yuborildi.",
            "failed": "Telegram yangi postni qabul qilmadi. Poster va botning kanal huquqlarini tekshiring.",
            "sending": "Yuborish natijasi noma’lum. Qayta urinishdan oldin kanalni qo‘lda tekshiring.",
            "incomplete": "E’lon uchun yaroqli kod, poster va video kerak.",
            "stale": "E’lon holati o‘zgargan. E’lonlar bo‘limini qayta oching.",
        }[status]
        await callback.message.answer(outcome, reply_markup=buttons(
            (("E’lon holati", f"p_admin_post_{anime_id}"),)))

    async def require_subscription(callback, bot):
        if await is_subscribed(bot, callback.from_user.id):
            return True
        await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
        return False

    @router.callback_query(F.data.regexp(r"^anime_detail_[0-9]{1,18}$"))
    async def detail(callback, bot):
        if await require_subscription(callback, bot):
            await callback.answer()
            await show_detail(callback.message, callback.from_user.id,
                              int(callback.data.split("_")[-1]), replace=True,
                              protect_content=callback.from_user.id != admin_id())

    @router.callback_query(F.data.regexp(r"^p_desc_[0-9]{1,18}$"))
    async def full_description(callback, bot):
        if not await require_subscription(callback, bot):
            return
        item = store.anime_content(int(callback.data.split("_")[-1]))
        if not item or not item["visible"]:
            await callback.answer("Kontent topilmadi.", show_alert=True)
            return
        await callback.answer()
        text = item["description"] or "Tavsif kiritilmagan."
        for offset in range(0, len(text), 1900):
            await callback.message.answer(text[offset:offset + 1900])

    @router.callback_query(F.data.regexp(r"^p_fav_(add|remove)_[0-9]{1,18}$"))
    async def favorite(callback, bot):
        if not await require_subscription(callback, bot):
            return
        _, _, action, value = callback.data.split("_")
        item = store.anime_content(int(value))
        if not item or not item["visible"]:
            await callback.answer("Kontent topilmadi.", show_alert=True)
            return
        operation = db.add_favorite if action == "add" else db.remove_favorite
        changed = operation(callback.from_user.id, item["id"])
        await callback.answer("Sevimlilar yangilandi." if changed else "Sevimlilar ro‘yxati tayyor.")
        if changed:
            await callback.message.edit_reply_markup(reply_markup=detail_buttons(item, callback.from_user.id))

    @router.callback_query(F.data.regexp(r"^(movies|p_movie_[0-9]+|p_cat_movie_.*)$"))
    async def retired_section(callback):
        await callback.answer("Bu bo‘lim hozircha mavjud emas.", show_alert=True)

    @router.callback_query(F.data.regexp(r"^(anime_(az|new|popular|genres|years)|p_cat_anime_(az|new|popular|genre|year)_[0-9]{1,18}_[0-9]{1,18})$"))
    async def catalog(callback, bot):
        if not await require_subscription(callback, bot):
            return
        data = callback.data
        categories = None
        category = None
        index = 0
        page = 0
        kind = "anime"
        if data.startswith("p_cat_"):
            _, _, kind, order, raw_index, raw_page = data.split("_")
            index, page = int(raw_index), int(raw_page)
            if page > 1_000_000:
                await callback.answer("Sahifa topilmadi.", show_alert=True)
                return
        else:
            order = data.split("_")[1]
        if order in ("genre", "genres", "year", "years"):
            is_genre = order.startswith("genre")
            order = "genre" if is_genre else "year"
            records = store.catalog(kind, limit=-1)
            if is_genre:
                values = {}
                for row in records:
                    for genre in (row["genre"] or "").split(","):
                        genre = genre.strip()
                        if genre:
                            values.setdefault(genre.casefold(), genre)
                categories = [values[key] for key in sorted(values)]
            else:
                categories = sorted({row["release_year"] for row in records if row["release_year"]}, reverse=True)
            if index:
                if index > len(categories):
                    await callback.answer("Bo‘lim topilmadi.", show_alert=True)
                    return
                category = categories[index - 1]
        if categories is not None and index == 0:
            entries = [(str(value), f"p_cat_{kind}_{order}_{number}_0")
                       for number, value in enumerate(categories, 1)]
            entries = entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE + 1]
        else:
            records = store.catalog(kind, order, category, page * PAGE_SIZE)
            entries = [
                (limited(f"{item['title']} · {item['country']}" if item["country"] else item["title"], 60),
                 f"anime_detail_{item['id']}")
                for item in records
            ]
        labels = {"az": "🔤 Alifbo bo‘yicha", "new": "🆕 Yangi qo‘shilganlar", "popular": "Mashhur animelar",
                  "genre": "Janrlar", "year": "Yillar"}
        heading = f"{BRAND_NAME} · {category or labels[order]}"
        rows = [(entry,) for entry in entries[:PAGE_SIZE]]
        nav = []
        if page:
            nav.append(("⬅️ Oldingi", f"p_cat_{kind}_{order}_{index}_{page - 1}"))
        if len(entries) > PAGE_SIZE:
            nav.append(("Keyingi ➡️", f"p_cat_{kind}_{order}_{index}_{page + 1}"))
        if nav:
            rows.append(tuple(nav))
        rows.append((("⬅️ Orqaga", f"p_cat_{kind}_{order}_0_0" if category is not None
                      else "anime"),))
        await callback.answer()
        await edit_text(callback.message, heading if entries else f"{heading}\n\nHozircha ma’lumot yo‘q.",
                        reply_markup=buttons(*rows))

    @router.message(ContentForm.poster)
    async def add_poster(message, state):
        if message.from_user.id != admin_id():
            return
        if not message.photo and message.text != "/skip":
            await message.answer("Posterni rasm shaklida yuboring yoki /skip yuboring.")
            return
        poster = message.photo[-1].file_id if message.photo else None
        data = await state.get_data()
        if data.get("initial_video"):
            await create_draft(message, state, data, poster, 0)
            return
        await state.update_data(poster=poster)
        await state.set_state(ContentForm.seasons)
        await message.answer("Fasllar sonini kiriting (1–99).")

    async def create_draft(message, state, data, poster, seasons):
        try:
            anime_id = store.create_draft(data, poster, seasons)
        except db.INTEGRITY_ERRORS:
            await state.set_state(add_anime_state.code)
            await message.answer("Kod band. Yangi kodni kiriting.")
            return
        await state.clear()
        if data.get("initial_video"):
            await message.answer("Anime qoralamasi yaratildi. Film yoki OVA videosini kiriting.",
                                 reply_markup=buttons((("➕ Video qo‘shish", f"x_add_{data['initial_video']}_{anime_id}"),),
                                                      (("📋 Kontent", f"x_manageanime_{anime_id}_0"),)))
            return
        rows = [( (f"📥 {season['season_number']}-faslga video yuklash", f"uploadseason_{season['id']}"), )
                for season in db.get_anime_seasons(anime_id)[:10]]
        await message.answer("Qoralama saqlandi. Fasllarga qismlarni yuklang.",
                             reply_markup=buttons(*rows, (("Barcha fasllar", f"p_admin_upload_{anime_id}"),),
                                                  (("E’lonni ko‘rib chiqish", f"p_admin_post_{anime_id}"),)))

    @router.message(ContentForm.seasons)
    async def add_seasons(message, state):
        if message.from_user.id != admin_id():
            return
        value = message.text or ""
        if not value.isascii() or not value.isdigit() or len(value) > 2 or not int(value):
            await message.answer("1 dan 99 gacha fasl sonini kiriting.")
            return
        data = await state.get_data()
        await create_draft(message, state, data, data["poster"], int(value))

    @router.message(ContentForm.edit_media)
    async def save_media(message, state):
        if message.from_user.id != admin_id():
            return
        data = await state.get_data()
        anime_id = data["anime_id"]
        if not message.photo:
            await message.answer("Poster rasmini yuboring.")
            return
        changed = store.update_media(anime_id, "poster", message.photo[-1].file_id)
        await state.clear()
        await message.answer("Media saqlandi." if changed else "Kontent topilmadi.",
                             reply_markup=buttons((("E’lonni ko‘rib chiqish", f"p_admin_post_{anime_id}"),),
                                                  (("⬅️ Admin panel", "p_admin_home"),)))

    @router.message(ContentForm.reconcile)
    async def reconcile(message, state):
        if message.from_user.id != admin_id():
            return
        data = await state.get_data()
        anime_id = data["anime_id"]
        value = message.text or ""
        if not value.isascii() or not value.isdigit() or len(value) > 10 or not int(value):
            await message.answer("Kanaldagi xabar ID raqamini kiriting.")
            return
        await state.clear()
        changed = store.finish_announcement(anime_id, "sent", channel, int(value))
        await message.answer("Post ID saqlandi." if changed else "E’lon holati o‘zgargan.",
                             reply_markup=buttons((("E’lon holati", f"p_admin_post_{anime_id}"),)))

    @router.callback_query(F.data.regexp(r"^p_admin_[a-z_0-9]+$"))
    async def admin(callback, state, bot):
        if callback.from_user.id != admin_id():
            await callback.answer("Bu bo‘lim administrator uchun.", show_alert=True)
            return
        action = callback.data.removeprefix("p_admin_")
        if action == "home":
            await callback.answer()
            await callback.message.answer(f"{BRAND_NAME} · Admin panel", reply_markup=admin_menu())
            return
        if action == "stats":
            periods, popular, favorite, season = store.statistics()
            text = f"{BRAND_NAME} · Video yuborish statistikasi\n\n"
            for days, label in ((0, "Umumiy"), (7, "Oxirgi 7 kun"), (30, "Oxirgi 30 kun")):
                row = periods[days]
                text += f"{label}: {row['total']} yuborish · {row['users']} noyob foydalanuvchi\n"
            for label, row in (("Eng mashhur anime", popular), ("Eng ko‘p saqlangan anime", favorite),
                               ("Eng ko‘p so‘ralgan fasl", season)):
                text += f"\n{label}: {limited(row['title'], 100) if row else '—'}"
            await callback.answer()
            await edit_text(callback.message, text, reply_markup=buttons((("⬅️ Admin panel", "p_admin_home"),)))
            return
        if action == "settings":
            await callback.answer()
            await edit_text(callback.message, f"{BRAND_NAME} · Sozlamalar\n\nE’lon kanali: {channel}\n"
                            "Kontentni tasdiqlashdan oldin tarqatish ruxsatini tekshiring.",
                            reply_markup=buttons((("Kanal huquqlarini tekshirish", "p_admin_permissions"),),
                                                 (("⬅️ Admin panel", "p_admin_home"),)))
            return
        if action == "permissions":
            await callback.answer()
            try:
                member = await bot.get_chat_member(channel, bot.id)
                can_post = member.status == "creator" or getattr(member, "can_post_messages", False)
                can_edit = member.status == "creator" or getattr(member, "can_edit_messages", False)
                text = f"E’lon yuborish: {'bor' if can_post else 'yo‘q'}\nE’lon tahrirlash: {'bor' if can_edit else 'yo‘q'}"
            except TelegramAPIError:
                text = "Kanal huquqlarini tekshirib bo‘lmadi."
            await callback.message.answer(text, reply_markup=buttons((("⬅️ Sozlamalar", "p_admin_settings"),)))
            return
        if action.startswith("list_"):
            fields = action.split("_")
            if len(fields) != 3 or fields[1] not in ("manage", "seasons", "parts", "poster", "post") or not numeric_id(fields[2]):
                await callback.answer("Tugma eskirgan.", show_alert=True)
                return
            _, mode, raw_page = fields
            page = int(raw_page)
            if page > 1_000_000:
                await callback.answer("Sahifa topilmadi.", show_alert=True)
                return
            with store.connection() as conn:
                items = conn.execute("""SELECT id,title,visible FROM animes
                    WHERE kind='anime'
                    ORDER BY id DESC LIMIT 13 OFFSET ?""", (page * PAGE_SIZE,)).fetchall()
            target = {"manage": "manage_anime_", "seasons": "manage_seasons_", "parts": "p_admin_upload_",
                      "poster": "p_admin_poster_", "post": "p_admin_post_"}[mode]
            rows = [
                ((limited(item["title"], 55) + (" · Qoralama" if not item["visible"] else ""),
                  f"{target}{item['id']}"),) for item in items[:PAGE_SIZE]
            ]
            if page:
                rows.append((("⬅️ Oldingi", f"p_admin_list_{mode}_{page - 1}"),))
            if len(items) > PAGE_SIZE:
                rows.append((("Keyingi ➡️", f"p_admin_list_{mode}_{page + 1}"),))
            rows.append((("⬅️ Admin panel", "p_admin_home"),))
            await callback.answer()
            await edit_text(callback.message, "Kontentni tanlang." if items else "Bo‘lim bo‘sh.",
                            reply_markup=buttons(*rows))
            return
        name, _, val = action.rpartition("_")
        missing_message_id = None
        if name.startswith("repost_"):
            raw_message_id = name.removeprefix("repost_")
            if not numeric_id(raw_message_id) or not int(raw_message_id):
                await callback.answer("Tasdiqlash tugmasi eskirgan.", show_alert=True)
                return
            name, missing_message_id = "publish", int(raw_message_id)
        upload_page = 0
        if action.startswith("upload_") and action.count("_") == 2:
            _, val, raw_page = action.split("_")
            if not numeric_id(raw_page) or int(raw_page) > 1_000_000:
                await callback.answer("Sahifa topilmadi.", show_alert=True)
                return
            name, upload_page = "upload", int(raw_page)
        item = store.anime_content(int(val)) if numeric_id(val) else None
        if not item:
            await callback.answer("Kontent topilmadi.", show_alert=True)
            return
        anime_id = item["id"]
        if name in ("reconcile", "askreset", "reset") and anime_id in active_publications:
            await callback.answer("E’lon hali yuborilmoqda.", show_alert=True)
            return
        if name in ("editposter", "reconcile"):
            if name == "reconcile":
                await state.set_state(ContentForm.reconcile)
                prompt = "Kanaldagi mavjud postning xabar ID raqamini yuboring."
            else:
                await state.set_state(ContentForm.edit_media)
                prompt = "Yangi poster yuboring."
            await state.update_data(anime_id=anime_id)
            await callback.answer()
            await callback.message.answer(f"{prompt}\nBekor qilish: /cancel")
            return
        if name == "publish":
            await callback.answer("E’lon yuborilmoqda.")
            if anime_id in active_publications:
                return
            active_publications.add(anime_id)
            try:
                previous_post = ("missing", missing_message_id) if missing_message_id else None
                status = await publish(bot, channel, anime_id, previous_post)
            finally:
                active_publications.discard(anime_id)
            messages = {
                "sent": "E’lon kanalda saqlangan.", "failed": "Kanal e’lonni qabul qilmadi. Botning kanal huquqlarini tekshiring va qayta urinib ko‘ring.",
                "sending": "Natija noma’lum. Kanalni qo‘lda tekshirib, e’lon holatini tasdiqlang.",
                "incomplete": "E’lon uchun yaroqli kod va kamida bitta video kerak.",
                "missing": "Avvalgi post o‘chirilgan. Qayta e’lon qilishni tasdiqlang.",
                "stale": "E’lon holati o‘zgargan. Davom etish uchun e’lon holatini oching.",
            }
            await callback.message.answer(messages[status], reply_markup=buttons(
                (("E’lon holati", f"p_admin_post_{anime_id}"),)))
            return
        if name == "link":
            record = store.announcement(anime_id)
            if not record or record["status"] != "sent":
                await callback.answer("Kanal posti topilmadi.", show_alert=True)
                return
            await callback.answer()
            await callback.message.answer(f"https://t.me/{channel.lstrip('@')}/{record['message_id']}")
            return
        if name == "update":
            await callback.answer()
            record = store.announcement(anime_id)
            markup = None
            if record and record["status"] == "sent" and record["message_id"] and store.valid_code(item["code"]):
                chat_id = record["chat_id"] or channel
                if str(chat_id).lstrip("-").isdigit():
                    chat_id = int(chat_id)
                message_id = record["message_id"]
                poster = item["poster_file_id"]
                new_caption = caption(item)
                markup = channel_keyboard(item)
                try:
                    if record["is_text"]:
                        await bot.edit_message_text(
                            chat_id=chat_id, message_id=message_id, text=new_caption,
                            parse_mode="HTML", reply_markup=markup,
                        )
                    elif poster and poster != record["poster_file_id"]:
                        await bot.edit_message_media(
                            chat_id=chat_id, message_id=message_id,
                            media=InputMediaPhoto(media=poster, caption=new_caption, parse_mode="HTML"),
                            reply_markup=markup,
                        )
                        store.remember_announcement_poster(anime_id, message_id, poster)
                    else:
                        await bot.edit_message_caption(
                            chat_id=chat_id, message_id=message_id, caption=new_caption,
                            parse_mode="HTML", reply_markup=markup,
                        )
                    outcome = "Kanal e’loni yangilandi."
                except TelegramBadRequest as error:
                    error_text = error.message.lower().strip()
                    if "message is not modified" in error_text:
                        if poster and not record["is_text"]:
                            store.remember_announcement_poster(anime_id, message_id, poster)
                        outcome = "Kanal e’loni dolzarb."
                    elif error_text.split(": ")[-1] in ("message to edit not found", "message not found"):
                        if store.mark_announcement_missing(anime_id, message_id):
                            outcome = "Avvalgi post kanalda topilmadi. Yangisini qayta e’lon qilishingiz mumkin."
                            markup = buttons((("📢 Qayta e’lon qilish", f"p_admin_askrepost_{anime_id}"),))
                        else:
                            outcome = "E’lon holati o‘zgargan. E’lonlar bo‘limini qayta oching."
                    else:
                        outcome = "Telegram tahrirlashni rad etdi. Postni va botning tahrirlash huquqini tekshiring."
                except TelegramForbiddenError:
                    outcome = "Botda kanal postini tahrirlash huquqi yo‘q."
                except TelegramRetryAfter as error:
                    outcome = f"Telegram vaqtincha chekladi. {error.retry_after} soniyadan keyin urinib ko‘ring."
                except TelegramAPIError:
                    outcome = "Tahrirlash natijasi noma’lum. Qayta e’lon qilishdan oldin kanalni qo‘lda tekshiring."
            else:
                outcome = "Yangilash uchun saqlangan kanal posti va yaroqli kontent kodi kerak."
                if record and record["status"] == "missing":
                    outcome = "Avvalgi post kanalda topilmadi."
                    markup = buttons((("📢 Qayta e’lon qilish", f"p_admin_askrepost_{anime_id}"),))
            await callback.message.answer(outcome, reply_markup=markup)
            return
        if name == "reset":
            await callback.answer()
            changed = store.finish_announcement(anime_id, "failed")
            await callback.message.answer("Qayta e’lon qilish mumkin." if changed else "E’lon holati o‘zgargan.",
                                          reply_markup=buttons((("E’lon holati", f"p_admin_post_{anime_id}"),)))
            return
        if name == "deleteposter":
            await callback.answer()
            store.update_media(anime_id, "poster", None)
            await callback.message.answer("Poster olib tashlandi.")
            return
        rows = []
        text = limited(item["title"], 100)
        if name == "upload":
            seasons = db.get_anime_seasons(anime_id)
            first = upload_page * PAGE_SIZE
            for season in seasons[first:first + PAGE_SIZE]:
                number = season["season_number"]
                season_id = season["id"]
                rows.append(((f"📥 {number}-fasl · Yuklash", f"uploadseason_{season_id}"),
                             (f"{number}-fasl · Boshqarish", f"manage_episodes_{season_id}")))
            navigation = []
            if upload_page:
                navigation.append(("⬅️ Oldingi", f"p_admin_upload_{anime_id}_{upload_page - 1}"))
            if first + PAGE_SIZE < len(seasons):
                navigation.append(("Keyingi ➡️", f"p_admin_upload_{anime_id}_{upload_page + 1}"))
            if navigation:
                rows.append(tuple(navigation))
            rows.append((("➕ Fasl qo‘shish", f"addseason_{anime_id}"),))
        elif name == "poster":
            rows.append((("🖼 Poster qo‘shish yoki almashtirish", f"p_admin_editposter_{anime_id}"),))
            if item["poster_file_id"]:
                rows.append((("🗑 Posterni o‘chirish", f"p_admin_askposter_{anime_id}"),))
        elif name == "askposter":
            text = "Posterni olib tashlashni tasdiqlaysizmi?"
            rows.append((("🗑 O‘chirishni tasdiqlash", f"p_admin_deleteposter_{anime_id}"),))
        elif name == "askreset":
            text = "Kanalni tekshiring. Post mavjud bo‘lmasa, qayta e’lon qilishga ruxsat bering."
            rows.append((("Kanalda post yo‘qligini tasdiqlash", f"p_admin_reset_{anime_id}"),))
        elif name == "askupdate":
            text = "Kanaldagi mavjud postni yangilashni tasdiqlaysizmi?"
            rows.append((("✅ Yangilashni tasdiqlash", f"p_admin_update_{anime_id}"),))
        elif name == "askrepost":
            record = store.announcement(anime_id)
            if not record or record["status"] != "missing":
                await callback.answer("E’lon holati o‘zgargan.", show_alert=True)
                return
            text = "Kanalga yangi post yuborishni tasdiqlaysizmi?"
            rows.append((("✅ Qayta e’lon qilishni tasdiqlash",
                          f"p_admin_repost_{record['message_id']}_{anime_id}"),))
            rows.append((("⬅️ E’lon holati", f"p_admin_post_{anime_id}"),))
        elif name == "post":
            record = store.announcement(anime_id)
            status = record["status"] if record else "new"
            label = {"new": "E’lon qilinmagan", "failed": "Telegram so‘rovni rad etdi",
                     "sent": "E’lon qilingan", "sending": "Kanalda tekshirish kerak",
                     "missing": "Avvalgi post kanalda topilmadi"}[status]
            suffix = f"\n\n<b>E’lon holati:</b> {label}"
            if status == "sent":
                suffix += f" · Xabar ID: {record['message_id']}"
                rows.append((("📢 E’lonni yangilash", f"p_admin_askupdate_{anime_id}"),))
                rows.append((("Post havolasi", f"p_admin_link_{anime_id}"),))
                rows.append((("📤 Kanalga qayta yuborish", f"p_repeat_{anime_id}"),))
            elif status == "sending":
                rows.extend([
                    (("Mavjud post ID sini kiritish", f"p_admin_reconcile_{anime_id}"),),
                    (("Qayta e’lon qilishga ruxsat berish", f"p_admin_askreset_{anime_id}"),),
                ])
            elif status == "missing":
                rows.append((("📢 Qayta e’lon qilish", f"p_admin_askrepost_{anime_id}"),))
                rows.append((("📤 Kanalga qayta yuborish", f"p_repeat_{anime_id}"),))
            else:
                suffix += "\nTasdiqlash bilan kontentni tarqatish huquqini tasdiqlaysiz."
                rows.append((("✅ Tasdiqlash va e’lon qilish", f"p_admin_publish_{anime_id}"),))
            text = caption(item, suffix=suffix)
            rows.append((("▶️ Fasllar va videolar", f"p_admin_upload_{anime_id}"),))
        else:
            await callback.answer("Tugma eskirgan.", show_alert=True)
            return
        rows.append((("⬅️ Admin panel", "p_admin_home"),))
        await callback.answer()
        if name == "post":
            await show_content(callback.message, item, text, buttons(*rows))
        else:
            await edit_text(callback.message, text, reply_markup=buttons(*rows))
