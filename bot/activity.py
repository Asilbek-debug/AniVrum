"""Private, owner-only view of the latest opt-in bot activity."""

import asyncio
import logging
import os
import re
from calendar import monthrange
from datetime import UTC, datetime, timedelta, timezone

from aiogram import F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database import activity as snapshots, db

log = logging.getLogger(__name__)
TASHKENT = timezone(timedelta(hours=5))
RECENT = timedelta(minutes=5)
PAGE = 10
UNAVAILABLE = "Ma’lumot mavjud emas"
NOTICE = (
    "AniVrum’da ixtiyoriy faoliyat qaydi. Rozilik bersangiz, bot egasi Telegram ID, "
    "botga ma’lum username, oxirgi qayd vaqti, bo‘lim va kontent tanlovini ko‘ra oladi. "
    "Bu qaydga xabar matni va shaxsiy suhbatlar kiritilmaydi. Faqat oxirgi holat saqlanadi "
    "va oxirgi faollikdan 30 kun o‘tgach o‘chiriladi. Kontent tanlovi o‘z sanasidan 30 kun saqlanadi. "
    "Istalgan payt /delete_activity orqali "
    "ushbu qaydni o‘chirishingiz mumkin. Rozilik bermasangiz ham botdan foydalanishingiz mumkin."
)
SECTIONS = {
    "home": "Asosiy menyu", "catalog": "Anime katalogi", "announcement": "E’londagi kontent",
    "anime": "Anime sahifasi", "description": "Anime tavsifi", "seasons": "Fasllar ro‘yxati",
    "season": "Fasl va qismlar", "download": "Fasl yuklamasi", "episode": "Qism videosi",
    "extras": "Film va OVA ro‘yxati", "film": "Film", "ova": "OVA",
    "search": "Anime qidiruvi", "favorites": "Sevimlilar", "top": "TOP animelar",
    "news": "Yangiliklar", "about": "Bot haqida", "subscription": "Kanalga obuna",
}
CONTENT_SECTIONS = {
    "announcement", "anime", "description", "seasons", "season", "download", "episode",
    "extras", "film", "ova",
}


class ActivityForm(StatesGroup):
    search = State()


def enabled():
    return os.getenv("ANIVRUM_ACTIVITY_ENABLED", "").strip().lower() == "true"


def private(message, user_id):
    return isinstance(message, Message) and message.chat.type == "private" and message.chat.id == user_id


async def observe(message, user_id, section, kind=None, content_id=None, *, actor=None):
    if not enabled() or not private(message, user_id):
        return
    actor = actor or message.from_user
    if not actor or actor.id != user_id or actor.is_bot:
        return
    try:
        await asyncio.to_thread(snapshots.record, user_id, actor.username, section, kind, content_id)
    except db.DATABASE_ERRORS:
        log.warning("Faoliyat holati saqlanmadi.")


async def observe_callback(callback, section, kind=None, content_id=None):
    actor = callback.from_user
    await observe(callback.message, actor.id, section, kind, content_id, actor=actor)


async def maybe_notice(message):
    if not enabled() or not message.from_user or not private(message, message.from_user.id):
        return
    try:
        if not await asyncio.to_thread(snapshots.allowed, message.from_user.id):
            await show_notice(message)
    except (TelegramAPIError, *db.DATABASE_ERRORS):
        log.warning("Faoliyat qaydi sozlamasini tekshirib bo‘lmadi.")


async def show_notice(message):
    from bot import content

    await message.answer(NOTICE, reply_markup=content.buttons(
        (("✅ Faoliyat qaydiga roziman", "privacy_allow"),),
    ), parse_mode=None)


async def prune_loop():
    while True:
        try:
            await asyncio.to_thread(snapshots.prune)
        except db.DATABASE_ERRORS:
            log.warning("Muddati o‘tgan faoliyat qaydlarini o‘chirib bo‘lmadi.")
        await asyncio.sleep(900)


def elapsed(when, now):
    now = max(when, now)
    months = (now.year - when.year) * 12 + now.month - when.month

    def anniversary(offset):
        year, month = divmod(when.year * 12 + when.month - 1 + offset, 12)
        return when.replace(year=year, month=month + 1, day=min(when.day, monthrange(year, month + 1)[1]))

    if anniversary(months) > now:
        months -= 1
    rest = now - anniversary(months)
    years, months = divmod(months, 12)
    hours, minutes = divmod(rest.seconds // 60, 60)
    return f"{years} yil, {months} oy, {rest.days} kun, {hours} soat, {minutes} daqiqa oldin"


async def profile(row, *, page_only=False):
    title = await asyncio.to_thread(snapshots.describe, row["content_kind"], row["content_id"])
    if not title and row["content_id"] is not None:
        title = f"Kontent mavjud emas (ID {row['content_id']})"
    section = SECTIONS.get(row["section"], UNAVAILABLE)
    if page_only:
        lines = [f"Oxirgi qayd etilgan sahifa\n{section}"]
        if row["section"] in CONTENT_SECTIONS and title:
            lines.append(title)
        return "\n".join(lines)
    when = datetime.fromtimestamp(row["recorded_at"], TASHKENT)
    now = datetime.now(TASHKENT)
    status = "🟢 Yaqinda faol" if now - when <= RECENT else "⚪ Hozirgi holati noma’lum"
    username = f"@{row['username']} (botda oxirgi qayd etilgan)" if row["username"] else UNAVAILABLE
    return (
        f"Telegram ID: {row['user_id']}\nUsername: {username}\n"
        f"Oxirgi bot faolligi: {when:%d.%m.%Y %H:%M:%S} (Toshkent, UTC+5)\n"
        f"{elapsed(when, now)}\n{status} · AniVrum botidagi qayd\n"
        f"Bo‘lim: {section}\nOxirgi kontent: {title or UNAVAILABLE}"
    )


def install(router, admin_id):
    from bot import content

    @router.message(Command("privacy", "delete_activity"))
    async def privacy_command(message, command):
        if not enabled() or not message.from_user or not private(message, message.from_user.id):
            return
        if command.command.lower() == "privacy":
            await show_notice(message)
        else:
            await message.answer("Faoliyat qaydingiz o‘chirilsinmi?", reply_markup=content.buttons(
                (("🗑 Qaydni o‘chirish", "privacy_delete"),),
                (("Bekor qilish", "privacy_cancel"),),
            ))

    @router.callback_query(F.data.in_({"privacy_allow", "privacy_delete", "privacy_cancel"}))
    async def privacy_action(callback):
        user_id = callback.from_user.id
        if not enabled() or not private(callback.message, user_id):
            await callback.answer()
            return
        try:
            if callback.data == "privacy_allow":
                await asyncio.to_thread(snapshots.allow, user_id)
                result = "Rozilik saqlandi. Keyingi bot harakatlari qayd etilishi mumkin."
            elif callback.data == "privacy_delete":
                await asyncio.to_thread(snapshots.delete, user_id)
                result = "Faoliyat qaydingiz o‘chirildi. Yangi qayd uchun yana rozilik kerak."
            else:
                result = "Bekor qilindi."
        except db.DATABASE_ERRORS:
            await callback.answer("Hozircha amalni bajarib bo‘lmadi.", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(result)

    def allowed(message, user_id):
        return enabled() and user_id == admin_id() and private(message, user_id)

    def results_markup(rows, page=None):
        entries = [((f"{row['user_id']} · @{row['username']}" if row["username"] else str(row["user_id"]),
                     f"activity_user_{row['user_id']}"),) for row in rows[:PAGE]]
        navigation = []
        if page:
            navigation.append(("⬅️ Oldingi", f"activity_recent_{page - 1}"))
        if page is not None and len(rows) > PAGE:
            navigation.append(("➡️ Keyingi", f"activity_recent_{page + 1}"))
        return content.buttons(*entries, navigation, (("⬅️ Orqaga", "activity_home"),))

    async def show_profile(message, row, page_only=False):
        user_id = row["user_id"]
        markup = content.buttons(
            (("⬅️ Profilga qaytish", f"activity_user_{user_id}"),) if page_only else
            (("Oxirgi sahifani ko‘rish", f"activity_page_{user_id}"),),
            (("⬅️ Foydalanuvchilar nazorati", "activity_home"),),
        )
        await message.answer(await profile(row, page_only=page_only), parse_mode=None,
                             reply_markup=markup, protect_content=True)

    @router.callback_query(F.data.regexp(r"^activity_(?:home|search|recent_[0-9]{1,6}|(?:user|page)_[0-9]{1,18})$"))
    async def admin_callback(callback, state):
        message = callback.message
        if not allowed(message, callback.from_user.id):
            await callback.answer("Bu bo‘lim bot egasining shaxsiy chatida ishlaydi.", show_alert=True)
            return
        await callback.answer()
        await state.clear()
        action, _, value = callback.data.removeprefix("activity_").partition("_")
        try:
            if action == "home":
                await message.answer("👥 Foydalanuvchilar nazorati", reply_markup=content.buttons(
                    (("🔎 ID yoki username orqali qidirish", "activity_search"),),
                    (("Oxirgi faol foydalanuvchilar", "activity_recent_0"),),
                    (("⬅️ Admin panel", "p_admin_home"),),
                ), protect_content=True)
            elif action == "search":
                await state.set_state(ActivityForm.search)
                await message.answer("Telegram ID yoki @username yuboring.", reply_markup=content.buttons(
                    (("Bekor qilish", "activity_home"),),
                ), protect_content=True)
            elif action == "recent":
                page = int(value)
                rows = await asyncio.to_thread(snapshots.find, page=page)
                await message.answer("Oxirgi faol foydalanuvchilar" if rows else UNAVAILABLE,
                                     reply_markup=results_markup(rows, page), protect_content=True)
            else:
                rows = await asyncio.to_thread(snapshots.find, user_id=int(value))
                if rows:
                    await show_profile(message, rows[0], page_only=action == "page")
                else:
                    await message.answer(UNAVAILABLE, protect_content=True)
        except db.DATABASE_ERRORS:
            await message.answer("Faoliyat qaydini hozircha o‘qib bo‘lmadi.", protect_content=True)

    @router.message(ActivityForm.search, F.text, ~F.text.startswith("/"))
    async def search(message, state):
        if not message.from_user or not allowed(message, message.from_user.id):
            return
        value = (message.text or "").strip()
        if re.fullmatch(r"[0-9]{1,18}", value):
            criteria = {"user_id": int(value)}
        elif re.fullmatch(r"@[A-Za-z0-9_]{1,32}", value):
            criteria = {"username": value[1:]}
        else:
            await message.answer("Telegram ID yoki @username yuboring.", protect_content=True)
            return
        try:
            rows = await asyncio.to_thread(snapshots.find, **criteria)
            await state.clear()
            if len(rows) == 1:
                await show_profile(message, rows[0])
            elif rows:
                await message.answer("Username bir nechta qaydda uchradi. Telegram ID bo‘yicha tanlang.",
                                     reply_markup=results_markup(rows), protect_content=True)
            else:
                await message.answer(UNAVAILABLE, protect_content=True)
        except db.DATABASE_ERRORS:
            await message.answer("Faoliyat qaydini hozircha o‘qib bo‘lmadi.", protect_content=True)
