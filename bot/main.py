
import asyncio
import os
import logging
from pathlib import Path


from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import SimpleEventIsolation


import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from database.db import (
    get_all_animes,
    get_anime_by_id,
    get_anime_seasons,
    get_season_episodes,
    get_episode_by_id,
    add_season,
    get_season_by_id,
    get_season_by_number,
    add_episode_auto,
    update_anime_title,
    update_anime_code,
    update_anime_genre,
    update_anime_country,
    update_anime_year,
    update_anime_description,
    delete_anime,
    update_season_number,
    delete_season,
    update_episode_number,
    update_episode_video,
    delete_episode,
    search_animes,
    add_favorite,
    remove_favorite,
    is_favorite,
    get_user_favorites,
    add_anime_view,
    get_top_animes,
)


from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.token import TokenValidationError
from dotenv import load_dotenv
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject
from database import catalog as store
from database import db
from bot import activity, content, extras
from database import activity as activity_store
from bot.season_download import SeasonDownloads

log = logging.getLogger(__name__)

# .env faylidan tokenni olish
BASE_DIR = Path(__file__).resolve().parent.parent
CHANNEL = "@AniVrum"
ADMIN_ID = 0

# Anime qo'shish bosqichlari
class AddAnime(StatesGroup):
    title = State()
    code = State()
    genre = State()
    country = State()
    release_year = State()
    description = State()


# Admin fasl qo'shish bosqichlari
class AddSeason(StatesGroup):
    number = State()


# Admin video yuklash bosqichi
class UploadEpisodes(StatesGroup):
    videos = State()


class ManageAnime(StatesGroup):
    edit_value = State()


class ManageSeason(StatesGroup):
    edit_number = State()


class ManageEpisode(StatesGroup):
    edit_number = State()
    replace_video = State()


class SearchAnime(StatesGroup):
    query = State()


dp = Dispatcher(events_isolation=SimpleEventIsolation())
season_downloads = SeasonDownloads()
activity.install(dp, lambda: ADMIN_ID)


# Telegram ID raqamini ko'rsatish
@dp.message(Command("myid"))
async def my_id_handler(message: Message):
    await message.answer(
        f"🆔 Sizning Telegram ID raqamingiz: {message.from_user.id}"
    )
    await activity.observe(message, message.from_user.id, None)


# Kanalga obunani tekshirish
async def is_subscribed(bot: Bot, user_id: int):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in (
            "creator", "administrator", "member"
        ) or (
            member.status == "restricted"
            and member.is_member
        )
    except TelegramAPIError:
        log.info('Kanal obunasini tekshirib bo‘lmadi.')
        return False


# Majburiy obuna tugmalari
@dp.message(Command("cancel"))
async def cancel_form(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        await message.answer("Jarayon bekor qilindi.")


def subscription_keyboard(anime_id=None, *, target=None):
    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(text="🔗 Kanalga obuna bo‘lish", url="https://t.me/AniVrum"))
    destination = target or anime_id
    keyboard.add(content.button(
        text="✅ Obunani tekshirish",
        callback_data=f"check_subscription_{destination}" if destination else "check_subscription",
    ))
    keyboard.adjust(1)
    return keyboard.as_markup()


# ==========================================
# ANIVRUM - ASOSIY MENYU
# ==========================================


def main_keyboard():
    keyboard = content.MenuKeyboardBuilder()

    keyboard.add(content.button(
        text="🎌 Animelar",
        callback_data="anime"
    ))

    keyboard.add(content.button(
        text="🔎 Qidiruv",
        callback_data="anime_search"
    ))

    keyboard.add(content.button(
        text="⭐ Sevimlilar",
        callback_data="favorites"
    ))

    keyboard.add(content.button(
        text="🔥 TOP animelar",
        callback_data="top_animes"
    ))

    keyboard.add(content.button(
        text="📰 Anime yangiliklari", callback_data="x_news_0"
    ))
    keyboard.add(content.button(
        text="ℹ️ Bot haqida",
        callback_data="about"
    ))

    keyboard.adjust(2, 2, 2)

    return keyboard.as_markup()


# Animelar katalogi tugmalari
def anime_keyboard():
    keyboard = content.MenuKeyboardBuilder()

    keyboard.add(content.button(
        text="🔤 Alifbo bo‘yicha",
        callback_data="anime_az"
    ))
    keyboard.add(content.button(
        text="🆕 Yangi qo‘shilganlar",
        callback_data="anime_new"
    ))
    keyboard.add(content.button(
        text="🔥 Mashhur animelar",
        callback_data="anime_popular"
    ))
    keyboard.add(content.button(
        text="🎭 Janrlar",
        callback_data="anime_genres"
    ))
    keyboard.add(content.button(text="📅 Yillar", callback_data="anime_years"))
    keyboard.add(content.button(text="🎬 Mustaqil filmlar va OVA", callback_data="x_independent_0"))
    keyboard.add(content.button(
        text="⬅️ Asosiy menyu",
        callback_data="back_home"
    ))

    keyboard.adjust(2, 2, 1, 1, 1)
    return keyboard.as_markup()


# Asosiy menyuni ko'rsatish
async def show_main_menu(message: Message):
    await message.answer(
        f"🎬 {content.BRAND_NAME}\n\nXush kelibsiz! Bo‘limni tanlang.",
        reply_markup=main_keyboard()
    )
    if message.from_user:
        await activity.observe(message, message.from_user.id, "home")


# /start buyrug'i
@dp.message(CommandStart())
async def start_handler(message: Message, bot: Bot, command: CommandObject, state: FSMContext):
    await state.clear()
    await activity.maybe_notice(message)
    item = None
    target = None
    if command.args:
        prefix, _, value = command.args.partition("_")
        if prefix == "animeid" and content.numeric_id(value):
            anime = store.anime_content(int(value))
            if anime and anime["visible"]:
                item = anime
        elif prefix == "anime" and store.valid_code(value):
            item = store.by_legacy_code(value, "anime")
        elif prefix in {"season", "extra", "catalog"} and content.numeric_id(value):
            target = command.args
    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            f"{content.BRAND_NAME}\n\nDavom etish uchun kanalga obuna bo‘ling.",
            reply_markup=subscription_keyboard(item["id"] if item else None, target=target),
        )
        await activity.observe(message, message.from_user.id, "subscription")
    elif target:
        await open_announcement_target(message, bot, message.from_user.id, target)
    elif item:
        await content.show_detail(message, message.from_user.id, item["id"],
                                  protect_content=message.from_user.id != ADMIN_ID)
    elif command.args:
        await message.answer("Havoladagi kontent topilmadi.", reply_markup=main_keyboard())
    else:
        await show_main_menu(message)


@dp.callback_query(F.data.regexp(r"^check_subscription(?:_(?:(?:season|extra|catalog)_)?[0-9]{1,18})?$"))
async def check_subscription(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Siz hali kanalga obuna bo‘lmagansiz.", show_alert=True)
        return
    await callback.answer("Obuna tasdiqlandi.")
    suffix = callback.data.removeprefix("check_subscription")
    if suffix and not content.numeric_id(suffix[1:]):
        await open_announcement_target(callback.message, bot, callback.from_user.id, suffix[1:],
                                       actor=callback.from_user)
    elif suffix:
        await content.show_detail(callback.message, callback.from_user.id, int(suffix[1:]), replace=True,
                                  protect_content=callback.from_user.id != ADMIN_ID, actor=callback.from_user)
    else:
        await content.edit_text(callback.message, f"{content.BRAND_NAME} · Asosiy menyu", reply_markup=main_keyboard())
        await activity.observe_callback(callback, "home")


async def open_announcement_target(message, bot, user_id, target, *, actor=None):
    if not isinstance(message, Message) or message.chat.type != "private":
        return
    kind, _, raw_id = target.partition("_")
    target_id = int(raw_id)
    if kind == "extra":
        await extras.send_standalone(message, bot, target_id, protected=user_id != ADMIN_ID, actor=actor)
    elif kind == "season":
        error = queue_season_download(message, bot, user_id, target_id)
        if error:
            await message.answer(error)
        else:
            await activity.observe(message, user_id, "download", "season", target_id, actor=actor)
    else:
        await show_announcement_catalog(message, target_id, actor=actor)


async def show_announcement_catalog(message, anime_id, page=0, *, replace=False, actor=None):
    item = store.anime_content(anime_id)
    if not item or not item["visible"]:
        await message.answer("Kontent topilmadi.")
        return
    rows, more = content.announcement_rows(anime_id, page)
    navigation = []
    if page:
        navigation.append(content.button(text="⬅️ Oldingi", callback_data=f"content_page_{anime_id}_{page - 1}"))
    if more:
        navigation.append(content.button(text="➡️ Keyingi", callback_data=f"content_page_{anime_id}_{page + 1}"))
    if navigation:
        rows.append(navigation)
    markup = content.keyboard_markup(rows) if rows else None
    answer = message.edit_text if replace else message.answer
    await answer(item["title"] if rows else "Yuborishga tayyor kontent topilmadi.",
                 reply_markup=markup, parse_mode=None)
    actor = actor or message.from_user
    if actor:
        await activity.observe(message, actor.id, "announcement", "anime", anime_id, actor=actor)


@dp.callback_query(F.data.regexp(r"^content_page_[0-9]{1,18}_[0-9]{1,8}$"))
async def announcement_catalog_page(callback: CallbackQuery, bot: Bot):
    if not isinstance(callback.message, Message) or callback.message.chat.type != "private":
        await callback.answer()
        return
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
        return
    anime_id, page = map(int, callback.data.split("_")[-2:])
    await callback.answer()
    await show_announcement_catalog(callback.message, anime_id, page, replace=True, actor=callback.from_user)


# ==========================================
# ANIVRUM - ASOSIY MENYU TUGMALARI
# ==========================================

@dp.callback_query(F.data == "anime")
async def menu_handler(callback: CallbackQuery, bot: Bot):

    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalimizga obuna bo'ling!",
            show_alert=True
        )
        await content.edit_text(callback.message,
            "🔒 Botdan foydalanish uchun kanalga obuna bo'ling.",
            reply_markup=subscription_keyboard()
        )
        return

    await content.edit_text(
        callback.message, f"🎌 {content.BRAND_NAME} · Katalog", reply_markup=anime_keyboard()
    )
    await callback.answer()
    await activity.observe_callback(callback, "catalog")


@dp.callback_query(F.data.regexp(r"^anime_seasons_[0-9]{1,18}$"))
async def show_anime_seasons(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalimizga obuna bo'ling!",
            show_alert=True
        )
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime or not anime["visible"]:
        await callback.answer(
            "Anime topilmadi!",
            show_alert=True
        )
        return

    seasons = get_anime_seasons(anime_id)

    keyboard = content.MenuKeyboardBuilder()

    if seasons:
        text = f"📺 {anime['title']} — Fasllar\n\n👇 Faslni tanlang:"

        for season in seasons:
            keyboard.add(content.button(
                text=f"📺 {season['season_number']}-fasl",
                callback_data=f"season_detail_{season['id']}"
            ))
    else:
        text = "📭 Bu anime uchun hali fasllar qo'shilmagan."

    keyboard.add(content.button(
        text="⬅️ Anime ma'lumotlari",
        callback_data=f"anime_detail_{anime_id}"
    ))

    keyboard.adjust(1)

    await content.edit_text(callback.message,
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    await activity.observe_callback(callback, "seasons", "anime", anime_id)


# Fasl ichidagi qismlarni ko'rsatish
@dp.callback_query(F.data.regexp(r"^season_detail_[0-9]{1,18}$"))
async def show_season_episodes(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalimizga obuna bo'ling!",
            show_alert=True
        )
        return

    season_id = int(callback.data.split("_")[-1])


    season = get_season_by_id(season_id)
    anime = store.anime_content(season["anime_id"]) if season else None
    if not anime or not anime["visible"]:
        await callback.answer("Fasl topilmadi.", show_alert=True)
        return
    anime_id = anime["id"]

    episodes = get_season_episodes(season_id)

    keyboard = content.MenuKeyboardBuilder()

    if episodes:
        text = "📺 Fasldagi qismlar\n\n👇 Qismni tanlang:"

        for episode in episodes:
            keyboard.add(content.button(
                text=f"▶️ {episode['episode_number']}-qism",
                callback_data=f"episode_detail_{episode['id']}"
            ))
    else:
        text = "📭 Bu faslda hali qismlar mavjud emas."


    keyboard.add(content.button(
        text="⬅️ Fasllarga qaytish",
        callback_data=f"anime_seasons_{anime_id}"
    ))

    keyboard.adjust(1)


    await content.edit_text(callback.message,
        text,
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    await activity.observe_callback(callback, "season", "season", season_id)


# Anime qismini foydalanuvchiga yuborish


@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Bu bo‘lim administrator uchun.")
        return
    await state.clear()
    await message.answer(f"{content.BRAND_NAME} · Admin panel", reply_markup=content.admin_menu(
        include_activity=activity.enabled() and activity.private(message, message.from_user.id)
    ))


# Admin anime qo'shishni boshlaydi
@dp.callback_query(F.data == "admin_add_anime")
async def admin_add_anime(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "⛔ Siz administrator emassiz!",
            show_alert=True
        )
        return

    await state.clear()
    await state.update_data(kind="anime")
    await state.set_state(AddAnime.title)

    await callback.message.answer(
        "🎬 Yangi anime qo'shish\n\n"
        "✍️ Anime nomini yuboring yoki kontent turini tanlang:",
        reply_markup=content.buttons((("📺 Anime serial", "x_kind_anime"),
                                      ("🎞 Anime filmi", "x_kind_film"),
                                      ("⭐ OVA", "x_kind_ova")),
                                     (("❌ Bekor qilish", "v5_anime_cancel_0"),))
    )

    await callback.answer()


ANIME_FORM_STEPS = (
    (AddAnime.title, "🎬 Anime nomini yuboring."),
    (AddAnime.code, "🔢 Anime kodini yuboring."),
    (AddAnime.genre, "🎭 Anime janrini yuboring."),
    (AddAnime.country, "🌍 Davlatini kiriting. Masalan: Yaponiya"),
    (AddAnime.release_year, "📅 Chiqarilgan yilini kiriting."),
    (AddAnime.description, "📝 Anime tavsifini kiriting."),
    (content.ContentForm.poster, "🖼 Posterni rasm shaklida yuboring."),
    (content.ContentForm.seasons, "📺 Fasllar sonini yuboring."),
)
ANIME_OPTIONAL_FIELDS = {2: "genre", 3: "country", 4: "release_year", 5: "description"}


async def prompt_anime_step(message, state, index, *, prefix=""):
    step, prompt = ANIME_FORM_STEPS[index]
    await state.set_state(step)
    rows = []
    if index in ANIME_OPTIONAL_FIELDS or index == 6:
        rows.append([content.button(text="⏭ O‘tkazib yuborish", callback_data=f"v5_anime_skip_{index}")])
        prompt += " O‘tkazish uchun /skip."
    navigation = []
    if index:
        navigation.append(content.button(text="⬅️ Orqaga", callback_data=f"v5_anime_back_{index}"))
    navigation.append(content.button(text="❌ Bekor qilish", callback_data=f"v5_anime_cancel_{index}", style="danger"))
    rows.append(navigation)
    await message.answer(prefix + prompt, reply_markup=content.keyboard_markup(rows))


@dp.callback_query(F.data.regexp(r"^v5_anime_(?:skip_[2-5]|(?:back|cancel)_[0-7])$"))
async def anime_form_navigation(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID or not isinstance(callback.message, Message):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    _, _, action, raw_index = callback.data.split("_")
    index = int(raw_index)
    if await state.get_state() != ANIME_FORM_STEPS[index][0].state:
        await callback.answer("Bu bosqich tugagan.")
        return
    await callback.answer()
    if action == "cancel":
        await state.clear()
        await callback.message.answer("Jarayon bekor qilindi.", reply_markup=content.admin_menu())
    elif action == "back" and index:
        await prompt_anime_step(callback.message, state, index - 1)
    elif action == "skip" and index in ANIME_OPTIONAL_FIELDS:
        await state.update_data({ANIME_OPTIONAL_FIELDS[index]: None})
        await prompt_anime_step(callback.message, state, index + 1)


# Admin yuborgan anime nomini qabul qilish
@dp.message(AddAnime.title)
async def receive_anime_title(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if not message.text or not 1 <= len(message.text.strip()) <= 100:
        await message.answer("Nomini 1–100 belgi oralig‘ida kiriting.")
        return

    anime_title = message.text.strip()

    await state.update_data(title=anime_title)
    await prompt_anime_step(message, state, 1, prefix=f"✅ Anime nomi: {anime_title}\n\n")


# Anime kodini qabul qilish
@dp.message(AddAnime.code)
async def receive_anime_code(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if not message.text or not store.valid_code(message.text.strip()) or not content.numeric_id(message.text.strip()):
        await message.answer(
            "❗ Anime kodi faqat raqamlardan iborat bo'lsin.\n"
            "Masalan: 1002"
        )
        return

    anime_code = message.text.strip()
    if await asyncio.to_thread(store.code_exists, anime_code):
        await message.answer("Bu kod band. Boshqa kodni yuboring.")
        return

    await state.update_data(code=anime_code)
    await prompt_anime_step(message, state, 2, prefix=f"✅ Anime kodi: {anime_code}\n\n")


# Anime janrini qabul qilish
@dp.message(AddAnime.genre)
async def receive_anime_genre(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/skip":
        await state.update_data(genre=None)
        await prompt_anime_step(message, state, 3)
        return

    if not message.text or not message.text.strip():
        await message.answer("❗ Anime janrini matn shaklida yuboring.")
        return

    genre = message.text.strip()

    await state.update_data(genre=genre)
    await prompt_anime_step(message, state, 3)


@dp.message(AddAnime.country)
async def receive_anime_country(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/skip":
        await state.update_data(country=None)
        await prompt_anime_step(message, state, 4)
        return
    country = content.normalize_country(message.text)
    if country is None:
        await message.answer(content.COUNTRY_HINT)
        return
    await state.update_data(country=country)
    await prompt_anime_step(message, state, 4)


# Anime yilini qabul qilish
@dp.message(AddAnime.release_year)
async def receive_anime_year(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/skip":
        await state.update_data(release_year=None)
        await prompt_anime_step(message, state, 5)
        return

    if not message.text or not content.numeric_id(message.text.strip()):
        await message.answer(
            "❗ Yilni raqam bilan yuboring.\n"
            "Masalan: 2025"
        )
        return

    year = int(message.text.strip())

    if year < 1900 or year > 2100:
        await message.answer("❗ Yil 1900 va 2100 oralig'ida bo'lsin.")
        return

    await state.update_data(release_year=year)
    await prompt_anime_step(message, state, 5)


# Anime tavsifini qabul qilish va bazaga saqlash
@dp.message(AddAnime.description)
async def receive_anime_description(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    description = (message.text or "").strip()
    if description == "/skip":
        await state.update_data(description=None)
        await prompt_anime_step(message, state, 6)
        return
    if not description or len(description) > 2500:
        await message.answer("Tavsifni 1–2500 belgi oralig‘ida kiriting.")
        return
    await state.update_data(description=description)
    await prompt_anime_step(message, state, 6)


def admin_anime_keyboard(action):
    keyboard = content.MenuKeyboardBuilder()

    for anime in get_all_animes():
        keyboard.add(content.button(
            text=f"🎬 {anime['title']}",
            callback_data=f"{action}_{anime['id']}"
        ))

    keyboard.adjust(1)
    return keyboard.as_markup()


# Fasl qo'shish uchun anime tanlash
@dp.callback_query(F.data == "admin_add_season")
async def admin_choose_anime_for_season(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.answer(
        "📺 Qaysi animega fasl qo'shmoqchisiz?",
        reply_markup=admin_anime_keyboard("addseason")
    )
    await callback.answer()


# Tanlangan anime uchun fasl raqamini so'rash
@dp.callback_query(F.data.regexp(r"^addseason_[0-9]{1,18}$"))
async def admin_season_number(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    await state.update_data(anime_id=anime_id)
    await state.set_state(AddSeason.number)

    await callback.message.answer(
        f"🎬 {anime['title']}\n\n"
        "📺 Nechanchi faslni qo'shmoqchisiz?\n"
        "Masalan: 5"
    )
    await callback.answer()


# Fasl raqamini qabul qilish va saqlash
@dp.message(AddSeason.number)
async def admin_save_season(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if not message.text or not content.numeric_id(message.text):
        await message.answer("❗ Fasl raqamini son bilan yuboring.")
        return

    season_number = int(message.text)

    if season_number < 1:
        await message.answer("❗ Fasl raqami 1 dan boshlanadi.")
        return

    data = await state.get_data()
    anime_id = data["anime_id"]

    existing = get_season_by_number(anime_id, season_number)

    if existing:
        await message.answer(
            f"⚠️ {season_number}-fasl allaqachon mavjud."
        )
        await state.clear()
        return

    add_season(anime_id, season_number)
    await state.clear()

    await message.answer(
        f"✅ {season_number}-fasl qo'shildi!\n\n"
        "▶️ Endi /admin orqali qismlarni yuklashingiz mumkin."
    )


# Video yuklash uchun anime tanlash
@dp.callback_query(F.data == "admin_upload_episodes")
async def admin_choose_anime_for_upload(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.answer(
        "▶️ Qaysi anime qismlarini yuklamoqchisiz?",
        reply_markup=admin_anime_keyboard("uploadanime")
    )
    await callback.answer()


# Video yuklash uchun fasl tanlash
@dp.callback_query(F.data.regexp(r"^uploadanime_[0-9]{1,18}$"))
async def admin_choose_season_for_upload(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    seasons = get_anime_seasons(anime_id)
    keyboard = content.MenuKeyboardBuilder()

    for season in seasons:
        keyboard.add(content.button(
            text=f"📺 {season['season_number']}-fasl",
            callback_data=f"uploadseason_{season['id']}"
        ))

    keyboard.adjust(1)

    if not seasons:
        await callback.message.answer(
            "📭 Bu anime uchun hali fasl yaratilmagan."
        )
    else:
        await callback.message.answer(
            f"🎬 {anime['title']}\n\n"
            "📺 Video yuklash uchun faslni tanlang:",
            reply_markup=keyboard.as_markup()
        )

    await callback.answer()


# Video yuklash rejimini boshlash
@dp.callback_query(F.data.regexp(r"^uploadseason_[0-9]{1,18}$"))
async def admin_start_upload(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = await asyncio.to_thread(get_season_by_id, season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    await state.set_data({"season_id": season_id, "upload_title": season["anime_title"],
                          "upload_season": season["season_number"], "upload_saved": 0, "upload_errors": 0})
    await state.set_state(UploadEpisodes.videos)

    await callback.message.answer(
        f"🎬 {season['anime_title']}\n"
        f"📺 {season['season_number']}-fasl\n\n"
        "✅ Video yuklash rejimi yoqildi!\n\n"
        "Videolarni bittadan, ketma-ket yuboring "
        "yoki uzating.\n"
        "Bot har birini avtomatik raqamlaydi.\n\n"
        "🏁 Tugatish uchun /finish yozing."
    )
    await callback.answer()


# Video yuklashni yakunlash
@dp.message(UploadEpisodes.videos, Command("finish"))
async def admin_finish_upload(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    season = await asyncio.to_thread(get_season_by_id, data["season_id"])
    await state.clear()
    markup = content.admin_menu(include_activity=activity.enabled() and activity.private(message, message.from_user.id))
    if season:
        anime_id = season["anime_id"]
        markup = content.buttons(
            (("Keyingi faslni tanlash", f"p_admin_upload_{anime_id}"),),
            (("E’lonni ko‘rib chiqish", f"p_admin_post_{anime_id}"),),
            (("⬅️ Admin panel", "p_admin_home"),),
        )
    await message.answer(
        f"Video yuklash yakunlandi.\n✅ Saqlangan qismlar: {data.get('upload_saved', 0)}"
        f"\n⚠️ Saqlanmagan videolar: {data.get('upload_errors', 0)}",
        reply_markup=markup,
    )


# Admin yuborgan videoni qabul qilish
@dp.message(UploadEpisodes.videos, F.video | F.document)
async def admin_receive_video(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()
    season_id = data["season_id"]

    media, media_type = content.pick_media(message)
    if not media:
        await message.answer("Video yoki video hujjatini yuboring.")
        return

    clock = asyncio.get_running_loop().time
    started = clock()
    try:
        episode_number = await asyncio.to_thread(
            add_episode_auto,
            season_id,
            media.file_id, media_type, media.file_unique_id
        )
        if episode_number is None:
            await state.clear()
            await message.answer("❌ Fasl topilmadi.")
            return
    except db.INTEGRITY_ERRORS:
        await state.update_data(upload_errors=data.get("upload_errors", 0) + 1)
        await message.answer("Bu video ushbu faslda allaqachon mavjud.")
        return
    except db.DATABASE_ERRORS:
        await state.update_data(upload_errors=data.get("upload_errors", 0) + 1)
        log.warning("Qismni saqlashda baza xatosi.")
        await message.answer("❌ Videoni saqlab bo'lmadi.")
        return
    stored = clock()
    await state.update_data(upload_saved=data.get("upload_saved", 0) + 1)

    await message.answer(
        "✅ Video saqlandi!\n\n"
        f"🎬 {data['upload_title']}\n"
        f"📺 {data['upload_season']}-fasl\n"
        f"▶️ {episode_number}-qism\n\n"
        "📤 Keyingi videoni yuborishingiz mumkin.\n"
        "🏁 Tugatish: /finish"
    )
    log.info("Qism yuklash: baza %.1f ms, javob %.1f ms", (stored - started) * 1000, (clock() - stored) * 1000)


# Noto'g'ri format yuborilsa
@dp.message(UploadEpisodes.videos)
async def admin_invalid_video(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "❗ Iltimos, videoni Telegram video shaklida yuboring.\n"
        "🏁 Tugatish: /finish"
    )


# ============================================
# ANIVRUM - QISMLAR VA BUTUN FASL MENYUSI
# ============================================


# 1. Qismlarni tanlash - fasllar
@dp.callback_query(F.data.regexp(r"^choose_parts_[0-9]{1,18}$"))
async def choose_parts_season(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo'ling!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime or not anime["visible"]:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    seasons = get_anime_seasons(anime_id)
    keyboard = content.MenuKeyboardBuilder()

    for season in seasons:
        keyboard.add(content.button(
            text=f"📺 {season['season_number']}-fasl",
            callback_data=f"numbered_parts_{season['id']}"
        ))

    keyboard.adjust(2)

    keyboard.row(
        content.button(
            text="⬅️ Anime sahifasiga qaytish",
            callback_data=f"anime_detail_{anime_id}"
        )
    )

    await content.edit_text(callback.message,
        f"🎬 {anime['title']}\n\n"
        "🔢 Qismlarni tanlash uchun faslni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    await activity.observe_callback(callback, "seasons", "anime", anime_id)


# 2. Raqamli qismlar - faqat videosi bor qismlar
@dp.callback_query(F.data.regexp(r"^numbered_parts_[0-9]{1,18}(?:_[0-9]{1,6})?$"))
async def numbered_parts(callback: CallbackQuery, bot: Bot):
    clock = asyncio.get_running_loop().time
    started = clock()
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo'ling!", show_alert=True)
        return

    _, _, raw_season, *raw_page = callback.data.split("_")
    season_id = int(raw_season)
    page = int(raw_page[0]) if raw_page else 0
    season = await asyncio.to_thread(get_season_by_id, season_id)

    item = await asyncio.to_thread(store.anime_content, season["anime_id"]) if season else None
    if not item or not item["visible"]:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    page_size = 40
    available = await asyncio.to_thread(store.season_layout, season["anime_id"], season_id,
                                        offset=page * page_size, limit=page_size + 1)
    rows = []
    episode_row = []
    for entry in available[:page_size]:
        if entry["kind"] == "episode":
            episode_row.append(content.button(text=str(entry["number"]), callback_data=f"watchpart_{entry['id']}"))
            if len(episode_row) == 4:
                rows.append(episode_row)
                episode_row = []
            continue
        if episode_row:
            rows.append(episode_row)
            episode_row = []
        rows.append([content.layout_button(entry, 0)])
    if episode_row:
        rows.append(episode_row)
    navigation = []
    if page:
        navigation.append(content.button(text="⬅️ Oldingi", callback_data=f"numbered_parts_{season_id}_{page - 1}"))
    if len(available) > page_size:
        navigation.append(content.button(text="➡️ Keyingi", callback_data=f"numbered_parts_{season_id}_{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([content.button(text="⬅️ Fasllarga qaytish", callback_data=f"choose_parts_{season['anime_id']}")])

    message_text = (
        f"🎬 {season['anime_title']}\n"
        f"📺 {season['season_number']}-fasl\n\n"
    )

    if available:
        message_text += "▶️ Kerakli qism raqamini tanlang:"
    else:
        message_text += "📭 Bu faslda hozircha video yo'q."

    await content.edit_text(callback.message,
        message_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()
    log.info("Fasl menyusi: %.1f ms", (clock() - started) * 1000)
    await activity.observe_callback(callback, "season", "season", season_id)


# ==========================================
# ANIVRUM - QISMNI KO'RISH VA STATISTIKA
# ==========================================

@dp.callback_query(F.data.regexp(r"^(watchpart|episode_detail)_[0-9]{1,18}$"))
async def watch_numbered_part(callback: CallbackQuery, bot: Bot):

    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalga obuna bo'ling!",
            show_alert=True
        )
        return

    episode_id = int(callback.data.split("_")[-1])
    episode = get_episode_by_id(episode_id)

    if not episode or not episode["video_file_id"]:
        await callback.answer(
            "Bu qismning videosi mavjud emas.",
            show_alert=True
        )
        return

    await callback.answer()

    if not await deliver_episode(bot, callback, episode):
        await callback.message.answer("Qismni yuborib bo‘lmadi.")
    else:
        await activity.observe_callback(callback, "episode", "episode", episode_id)


async def deliver_episode(bot, callback, episode):
    season = get_season_by_id(episode["season_id"])
    item = store.anime_content(season["anime_id"]) if season else None
    if not item or not item["visible"]:
        return False
    try:
        await content.send_media(
            bot, callback.message.chat.id, episode["video_file_id"], episode["media_type"],
            content.video_caption(item, season["season_number"], episode["episode_number"]),
            protect_content=callback.from_user.id != ADMIN_ID,
        )
    except TelegramAPIError:
        extras.track("error")
        log.warning("Qism yuborilmadi. Qism ID: %s", episode["id"])
        return False
    try:
        add_anime_view(item["id"], callback.from_user.id, episode["id"], season["id"])
    except db.DATABASE_ERRORS:
        log.warning("Yuborish statistikasini saqlab bo‘lmadi. Qism ID: %s", episode["id"])
    return True


# 4. Butun faslni olish - fasllar
@dp.callback_query(F.data.regexp(r"^download_seasons_[0-9]{1,18}$"))
async def choose_download_season(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo'ling!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime or not anime["visible"]:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    seasons = get_anime_seasons(anime_id)
    keyboard = content.MenuKeyboardBuilder()

    for season in seasons:
        keyboard.add(content.button(
            text=f"📥 {season['season_number']}-fasl",
            callback_data=f"downloadall_{season['id']}"
        ))

    keyboard.adjust(2)

    keyboard.row(
        content.button(
            text="⬅️ Anime sahifasiga qaytish",
            callback_data=f"anime_detail_{anime_id}"
        )
    )

    await content.edit_text(callback.message,
        f"🎬 {anime['title']}\n\n"
        "📥 Barcha qismlarini olish uchun faslni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    await activity.observe_callback(callback, "seasons", "anime", anime_id)


# ==========================================
# ANIVRUM - BUTUN FASLNI YUBORISH
# TOP ANIMELAR STATISTIKASI BILAN
# ==========================================

@dp.callback_query(F.data.regexp(r"^downloadall_[0-9]{1,18}$"))
async def download_entire_season(callback: CallbackQuery, bot: Bot):

    # Kanalga obunani tekshirish
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalga obuna bo'ling!",
            show_alert=True
        )
        return

    season_id = int(callback.data.rsplit("_", 1)[1])
    error = queue_season_download(callback.message, bot, callback.from_user.id, season_id)
    await callback.answer(error or "Yuborish boshlandi.", show_alert=bool(error))
    if not error:
        await activity.observe_callback(callback, "download", "season", season_id)


def queue_season_download(message, bot, user_id, season_id):
    if not isinstance(message, Message) or message.chat.type != "private":
        return "Faslni botning shaxsiy chatida yuklang."
    season = get_season_by_id(season_id)
    item = store.anime_content(season["anime_id"]) if season else None
    if not item or not item["visible"]:
        return "Fasl topilmadi!"
    available = sorted(
        (ep for ep in get_season_episodes(season_id) if ep["video_file_id"]),
        key=lambda ep: ep["episode_number"],
    )
    if not available:
        return "Bu faslda hozircha video yo?q!"
    jobs = season_downloads.jobs
    if user_id in jobs:
        return "Fasl yuborilmoqda. Iltimos, tugashini kuting."
    if len(jobs) >= 32:
        return "Yuklash navbati band. Keyinroq urinib ko?ring."
    jobs[user_id] = asyncio.create_task(run_season_download(
        message, bot, user_id, item, season, available
    ))
    return None


async def run_season_download(message, bot, user_id, item, season, episodes):
    try:
        await season_downloads.deliver(
            bot, message, user_id, item, season, episodes, user_id != ADMIN_ID
        )
    except TelegramAPIError as error:
        extras.track("error")
        log.warning("Fasl %s: %s", season["id"], type(error).__name__)
    finally:
        season_downloads.jobs.pop(user_id, None)


def anime_manage_keyboard(anime_id):
    keyboard = content.MenuKeyboardBuilder()

    fields = [
        ("📝 Nomini o'zgartirish", "title"),
        ("🔢 Kodini o'zgartirish", "code"),
        ("🎭 Janrini o'zgartirish", "genre"),
        ("🌍 Davlatini o'zgartirish", "country"),
        ("📅 Yilini o'zgartirish", "year"),
        ("📖 Tavsifini o'zgartirish", "description"),
    ]

    for label, field in fields:
        keyboard.add(content.button(
            text=label,
            callback_data=f"manage_edit_{field}_{anime_id}"
        ))

    keyboard.adjust(2)

    keyboard.row(content.button(text="📺 Fasllarni boshqarish", callback_data=f"manage_seasons_{anime_id}"))
    keyboard.row(
        content.button(text="▶️ Qismlarni boshqarish", callback_data=f"v5_partseasons_{anime_id}"),
        content.button(text="🎬 Film va OVA", callback_data=f"x_manageanime_{anime_id}_0"),
    )
    keyboard.row(
        content.button(text="🔒 Yopish", callback_data=f"v5_visibility_0_{anime_id}", style="danger"),
        content.button(text="🔓 Ochish", callback_data=f"v5_visibility_1_{anime_id}", style="success"),
    )
    keyboard.row(content.button(text="↕️ Tartibni o‘zgartirish", callback_data=f"v5_layout_{anime_id}_0_0"))
    keyboard.row(
        content.button(text="🖼 Poster", callback_data=f"p_admin_poster_{anime_id}"),
        content.button(text="📢 E’lon", callback_data=f"p_admin_post_{anime_id}"),
    )

    keyboard.row(
        content.button(
            text="🗑 Animeni o'chirish",
            callback_data=f"manage_delete_{anime_id}"
        )
    )

    keyboard.row(
        content.button(
            text="⬅️ Animelar ro'yxati",
            callback_data="p_admin_list_manage_0"
        )
    )

    return keyboard.as_markup()


# Admin animelar ro'yxati
@dp.callback_query(F.data == "admin_manage_animes")
async def admin_manage_animes(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    animes = get_all_animes()
    keyboard = content.MenuKeyboardBuilder()

    for anime in animes:
        keyboard.add(content.button(
            text=f"🎬 {anime['title']}",
            callback_data=f"manage_anime_{anime['id']}"
        ))

    keyboard.adjust(1)

    if not animes:
        await callback.message.answer("📭 Hozircha animelar yo'q.")
    else:
        await callback.message.answer(
            "📋 Boshqarish uchun animeni tanlang:",
            reply_markup=keyboard.as_markup()
        )

    await callback.answer()


# Tanlangan anime boshqaruv sahifasi
@dp.callback_query(F.data.regexp(r"^manage_anime_[0-9]{1,18}$"))
async def manage_anime_detail(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = store.anime_content(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    announcement = await asyncio.to_thread(store.announcement, anime_id)
    status = "Ochiq" if anime["visible"] else "Yopiq"
    published = "Joylangan" if announcement and announcement["status"] == "sent" else "Joylanmagan"
    poster = "Bor" if anime["poster_file_id"] else "Yo‘q"
    await content.show_content(
        callback.message, anime, content.caption(anime, admin_status=(
            ("🔒", "Holati", status), ("📢", "Kanal", published), ("🖼", "Poster", poster),
        )), anime_manage_keyboard(anime_id), replace=True,
    )

    await callback.answer()


@dp.callback_query(F.data.regexp(r"^v5_visibility_[01]_[0-9]{1,18}$"))
async def change_anime_visibility(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not isinstance(callback.message, Message):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    _, _, visible, anime_id = callback.data.split("_")
    changed = await asyncio.to_thread(store.set_visibility, int(anime_id), int(visible))
    await callback.answer("Holat saqlandi." if changed else "Anime topilmadi.")
    if changed:
        await callback.message.answer(
            "Anime ochildi." if visible == "1" else "Anime yopildi.",
            reply_markup=content.buttons((("Anime boshqaruvi", f"manage_anime_{anime_id}"),)),
        )


@dp.callback_query(F.data.regexp(r"^v5_partseasons_[0-9]{1,18}$"))
async def manage_episode_seasons(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not isinstance(callback.message, Message):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    anime_id = int(callback.data.rsplit("_", 1)[1])
    seasons = await asyncio.to_thread(get_anime_seasons, anime_id)
    rows = [((f"📺 {season['season_number']}-fasl", f"manage_episodes_{season['id']}"),) for season in seasons]
    rows.append((("📤 Video yuklash", f"p_admin_upload_{anime_id}"),))
    rows.append((("⬅️ Orqaga", f"manage_anime_{anime_id}"),))
    await callback.answer()
    await content.edit_text(callback.message, "Qismlarni boshqarish", reply_markup=content.buttons(*rows))


async def show_layout_editor(message, anime_id, season_id, page):
    items = await asyncio.to_thread(store.season_layout, anime_id, season_id or None, offset=page * 8, limit=9)
    rows = []
    labels = {"season": "📺 Fasl", "episode": "▶️ Qism", "film": "🎬 Film", "ova": "⭐ OVA"}
    for item in items[:8]:
        kind, item_id = item["kind"], item["id"]
        label = f"{labels[kind]} {item['number']}"
        if kind in ("film", "ova"):
            label += f" · {content.limited(item['title'], 30)}"
            target = f"x_editvideo_{item_id}"
        elif kind == "season":
            target = f"v5_layout_{anime_id}_{item_id}_0"
        else:
            target = f"manage_episode_{item_id}"
        base = f"vs_{anime_id}_{season_id}_{kind[0]}_{item_id}"
        rows.append(((label, target), ("⬆️", f"{base}_u"), ("⬇️", f"{base}_d")))
    if page:
        rows.append((("⬅️ Oldingi", f"v5_layout_{anime_id}_{season_id}_{page - 1}"),))
    if len(items) > 8:
        rows.append((("Keyingi ➡️", f"v5_layout_{anime_id}_{season_id}_{page + 1}"),))
    back = f"v5_layout_{anime_id}_0_0" if season_id else f"manage_anime_{anime_id}"
    rows.append((("⬅️ Orqaga", back),))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [content.button(text=label, callback_data=target) for label, target in row] for row in rows
    ])
    await content.edit_text(message, "↕️ Kontent tartibi", reply_markup=keyboard)


@dp.callback_query(F.data.regexp(r"^v5_layout_[0-9]{1,18}_[0-9]{1,18}_[0-9]{1,6}$"))
async def manage_layout(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not isinstance(callback.message, Message):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    anime_id, season_id, page = map(int, callback.data.split("_")[2:])
    await callback.answer()
    await show_layout_editor(callback.message, anime_id, season_id, page)


@dp.callback_query(F.data.regexp(r"^vs_[0-9]{1,18}_[0-9]{1,18}_[sefo]_[0-9]{1,18}_[ud]$"))
async def move_layout_item(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not isinstance(callback.message, Message):
        await callback.answer("Ruxsat yo‘q.", show_alert=True)
        return
    _, anime_id, season_id, kind, item_id, direction = callback.data.split("_")
    anime_id, season_id, item_id = int(anime_id), int(season_id), int(item_id)
    kinds = {"s": "season", "e": "episode", "f": "film", "o": "ova"}
    changed = await asyncio.to_thread(store.reorder_layout, anime_id, season_id or None,
                                      kinds[kind], item_id, -1 if direction == "u" else 1)
    await callback.answer("Tartib saqlandi." if changed else "Bu tomonga ko‘chirib bo‘lmaydi.")
    if changed:
        await show_layout_editor(callback.message, anime_id, season_id, 0)


# Tahrirlash maydonini tanlash
@dp.callback_query(F.data.regexp(r"^manage_edit_(title|code|genre|country|year|description)_[0-9]{1,18}$"))
async def manage_edit_anime(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    _, _, field, raw_anime_id = callback.data.split("_")
    anime_id = int(raw_anime_id)

    anime = store.anime_content(anime_id)
    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    field_names = {
        "title": "anime nomini",
        "code": "anime kodini",
        "genre": "anime janrini",
        "country": "davlatini",
        "year": "anime yilini",
        "description": "anime tavsifini",
    }

    if field not in field_names:
        await callback.answer("Noto'g'ri maydon!", show_alert=True)
        return

    await state.update_data(
        manage_anime_id=anime_id,
        manage_field=field
    )
    await state.set_state(ManageAnime.edit_value)

    prompt = {
        "genre": "Yangi janrni matn shaklida yuboring.",
        "country": "Yangi davlat nomini yuboring. Masalan: Yaponiya, Xitoy",
    }.get(field, "Yangi qiymatni matn shaklida yuboring.")
    await callback.message.answer(
        f"✏️ {field_names[field].capitalize()} yangilash\n\n"
        f"{prompt}\n"
        "Bekor qilish: /cancel"
    )
    await callback.answer()


# Tahrirlangan ma'lumotni bazaga saqlash
@dp.message(ManageAnime.edit_value)
async def manage_save_anime_edit(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❎ Tahrirlash bekor qilindi.")
        return

    if not message.text or not message.text.strip():
        await message.answer("❗ Matn yuboring.")
        return

    value = message.text.strip()
    data = await state.get_data()

    anime_id = data["manage_anime_id"]
    field = data["manage_field"]

    if field == "country":
        value = content.normalize_country(message.text)
        if value is None:
            await message.answer(content.COUNTRY_HINT)
            return
    elif len(value) > {"title": 100, "genre": 160, "description": 2500}.get(field, 58):
        await message.answer("Kiritilgan matn juda uzun.")
        return

    if field == "year":
        if not value.isascii() or not value.isdigit() or len(value) != 4 or not 1900 <= int(value) <= 2100:
            await message.answer(
                "❗ Yilni 1900–2100 oralig'ida yuboring."
            )
            return

    if field == "code" and (not store.valid_code(value) or not value.isdigit()):
        await message.answer("❗ Anime kodi raqamlardan iborat bo'lsin.")
        return

    try:
        if field == "title":
            updated = update_anime_title(anime_id, value)
        elif field == "code":
            updated = update_anime_code(anime_id, value)
        elif field == "genre":
            updated = update_anime_genre(anime_id, value)
        elif field == "country":
            updated = update_anime_country(anime_id, value)
        elif field == "year":
            updated = update_anime_year(anime_id, int(value))
        elif field == "description":
            updated = update_anime_description(anime_id, value)
        else:
            await message.answer("❌ Noma'lum maydon.")
            return

    except db.INTEGRITY_ERRORS:
        await message.answer(
            "❌ Bu anime kodi allaqachon ishlatilgan.\n"
            "Boshqa kod yuboring."
        )
        return

    if not updated:
        await message.answer("❌ Anime topilmadi.")
        await state.clear()
        return

    await state.clear()

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="⬅️ Anime boshqaruviga qaytish",
        callback_data=f"manage_anime_{anime_id}"
    ))

    await message.answer(
        "✅ Anime ma'lumoti muvaffaqiyatli yangilandi!",
        reply_markup=keyboard.as_markup()
    )


# Anime o'chirishni tasdiqlash
@dp.callback_query(F.data.regexp(r"^manage_delete_[0-9]{1,18}$"))
async def manage_delete_anime_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="❌ Yo'q, qaytish",
        callback_data=f"manage_anime_{anime_id}"
    ))
    keyboard.add(content.button(
        text="🗑 Ha, o'chirish",
        callback_data=f"manage_confirmdelete_{anime_id}"
    ))
    keyboard.adjust(1)

    await content.edit_text(callback.message,
        f"⚠️ {anime['title']} animesini o'chirmoqchimisiz?\n\n"
        "Anime bilan birga uning barcha fasllari va qismlari "
        "ham bazadan o'chiriladi.\n\n"
        "Bu amalni bekor qilib bo'lmaydi!",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# Anime o'chirishni bajarish
@dp.callback_query(F.data.regexp(r"^manage_confirmdelete_[0-9]{1,18}$"))
async def manage_delete_anime_execute(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    deleted = delete_anime(anime_id)

    if deleted:
        await content.edit_text(callback.message,
            f"✅ {anime['title']} animesi bazadan o'chirildi.\n"
            "Uning fasllari va qismlari ham o'chirildi.\n\n"
            "👑 Admin panel: /admin"
        )
    else:
        await callback.answer(
            "O'chirish amalga oshmadi!",
            show_alert=True
        )
        return

    await callback.answer()


# ==========================================
# ANIVRUM - FASLLARNI BOSHQARISH
# ==========================================

# 1. Anime boshqaruv sahifasidan fasllarni ochish
@dp.callback_query(F.data.regexp(r"^manage_seasons_[0-9]{1,18}$"))
async def manage_seasons_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    anime_id = int(callback.data.split("_")[-1])
    anime = get_anime_by_id(anime_id)

    if not anime:
        await callback.answer("Anime topilmadi!", show_alert=True)
        return

    seasons = get_anime_seasons(anime_id)
    keyboard = content.MenuKeyboardBuilder()

    for season in seasons:
        keyboard.add(content.button(
            text=f"📺 {season['season_number']}-fasl",
            callback_data=f"manage_season_{season['id']}"
        ))

    keyboard.add(content.button(text="➕ Fasl qo‘shish", callback_data=f"addseason_{anime_id}"))
    keyboard.adjust(2)

    keyboard.row(
        content.button(
            text="⬅️ Anime boshqaruviga qaytish",
            callback_data=f"manage_anime_{anime_id}"
        )
    )

    await content.edit_text(callback.message,
        f"🎬 {anime['title']}\n\n"
        "📺 Boshqarish uchun faslni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 2. Tanlangan fasl boshqaruvi
@dp.callback_query(F.data.regexp(r"^manage_season_[0-9]{1,18}$"))
async def manage_season_detail(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = get_season_by_id(season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    keyboard = content.MenuKeyboardBuilder()

    keyboard.add(content.button(
        text="▶️ Qismlarni boshqarish",
        callback_data=f"manage_episodes_{season_id}"
    ))

    keyboard.add(content.button(
        text="✏️ Fasl raqamini o'zgartirish",
        callback_data=f"season_edit_{season_id}"
    ))
    keyboard.add(content.button(
        text="🗑 Faslni o'chirish",
        callback_data=f"season_delete_{season_id}"
    ))
    keyboard.adjust(1)

    keyboard.row(
        content.button(
            text="⬅️ Fasllarga qaytish",
            callback_data=f"manage_seasons_{season['anime_id']}"
        )
    )

    episodes = get_season_episodes(season_id)

    await content.edit_text(callback.message,
        f"🎬 {season['anime_title']}\n"
        f"📺 {season['season_number']}-fasl\n"
        f"▶️ Qismlar soni: {len(episodes)}\n\n"
        "Kerakli amalni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 3. Fasl raqamini o'zgartirishni boshlash
@dp.callback_query(F.data.regexp(r"^season_edit_[0-9]{1,18}$"))
async def season_edit_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = get_season_by_id(season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    await state.update_data(manage_season_id=season_id)
    await state.set_state(ManageSeason.edit_number)

    await callback.message.answer(
        f"📺 Hozirgi fasl: {season['season_number']}\n\n"
        "✏️ Yangi fasl raqamini yuboring.\n"
        "Masalan: 2\n\n"
        "Bekor qilish: /cancel"
    )
    await callback.answer()


# 4. Yangi fasl raqamini saqlash
@dp.message(ManageSeason.edit_number)
async def season_edit_save(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❎ O'zgartirish bekor qilindi.")
        return

    if not message.text or not content.numeric_id(message.text.strip()):
        await message.answer("❗ Fasl raqamini son bilan yuboring.")
        return

    new_number = int(message.text.strip())

    if new_number < 1:
        await message.answer("❗ Fasl raqami 1 dan boshlanadi.")
        return

    data = await state.get_data()
    season_id = data["manage_season_id"]
    season = get_season_by_id(season_id)

    if not season:
        await state.clear()
        await message.answer("❌ Fasl topilmadi.")
        return

    existing = get_season_by_number(season["anime_id"], new_number)

    if existing and existing["id"] != season_id:
        await message.answer(
            f"❗ {new_number}-fasl allaqachon mavjud."
        )
        return

    try:
        updated = update_season_number(season_id, new_number)
    except db.INTEGRITY_ERRORS:
        await message.answer("❗ Bunday fasl raqami mavjud.")
        return

    await state.clear()

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="⬅️ Fasl boshqaruviga qaytish",
        callback_data=f"manage_season_{season_id}"
    ))

    await message.answer(
        "✅ Fasl raqami yangilandi!" if updated
        else "❌ Faslni yangilab bo'lmadi.",
        reply_markup=keyboard.as_markup()
    )


# 5. Faslni o'chirishni tasdiqlash
@dp.callback_query(F.data.regexp(r"^season_delete_[0-9]{1,18}$"))
async def season_delete_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = get_season_by_id(season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    keyboard = content.MenuKeyboardBuilder()

    keyboard.add(content.button(
        text="❌ Yo'q, qaytish",
        callback_data=f"manage_season_{season_id}"
    ))
    keyboard.add(content.button(
        text="🗑 Ha, o'chirish",
        callback_data=f"season_confirmdelete_{season_id}"
    ))
    keyboard.adjust(1)

    await content.edit_text(callback.message,
        f"⚠️ {season['anime_title']}\n"
        f"📺 {season['season_number']}-fasl\n\n"
        "Bu fasl va uning barcha qismlari bazadan o'chiriladi!\n"
        "Davom etasizmi?",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 6. Faslni o'chirish
@dp.callback_query(F.data.regexp(r"^season_confirmdelete_[0-9]{1,18}$"))
async def season_delete_execute(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = get_season_by_id(season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    deleted = delete_season(season_id)

    if deleted:
        await content.edit_text(callback.message,
            f"✅ {season['season_number']}-fasl o'chirildi.\n\n"
            "👑 Admin panel: /admin"
        )
    else:
        await callback.answer("O'chirish amalga oshmadi!", show_alert=True)
        return

    await callback.answer()


# ==========================================
# ANIVRUM - QISMLARNI BOSHQARISH
# ==========================================

# 1. Fasldagi qismlar ro'yxati
@dp.callback_query(F.data.regexp(r"^manage_episodes_[0-9]{1,18}$"))
async def manage_episodes_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    season_id = int(callback.data.split("_")[-1])
    season = get_season_by_id(season_id)

    if not season:
        await callback.answer("Fasl topilmadi!", show_alert=True)
        return

    episodes = get_season_episodes(season_id)
    keyboard = content.MenuKeyboardBuilder()

    for episode in episodes:
        keyboard.add(content.button(
            text=f"▶️ {episode['episode_number']}-qism",
            callback_data=f"manage_episode_{episode['id']}"
        ))

    keyboard.adjust(4)
    keyboard.row(
        content.button(
            text="⬅️ Fasl boshqaruviga qaytish",
            callback_data=f"manage_season_{season_id}"
        )
    )

    await content.edit_text(callback.message,
        f"🎬 {season['anime_title']}\n"
        f"📺 {season['season_number']}-fasl\n\n"
        "▶️ Boshqarish uchun qismni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 2. Bitta qismning boshqaruv sahifasi
@dp.callback_query(F.data.regexp(r"^manage_episode_[0-9]{1,18}$"))
async def manage_episode_detail(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    episode_id = int(callback.data.split("_")[-1])
    episode = get_episode_by_id(episode_id)

    if not episode:
        await callback.answer("Qism topilmadi!", show_alert=True)
        return

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="🔢 Qism raqamini o'zgartirish",
        callback_data=f"episode_editnum_{episode_id}"
    ))
    keyboard.add(content.button(
        text="🎞 Videoni almashtirish",
        callback_data=f"episode_replace_{episode_id}"
    ))
    keyboard.add(content.button(
        text="🗑 Qismni o'chirish",
        callback_data=f"episode_delete_{episode_id}"
    ))
    keyboard.adjust(1)

    keyboard.row(
        content.button(
            text="⬅️ Qismlarga qaytish",
            callback_data=f"manage_episodes_{episode['season_id']}"
        )
    )

    video_status = (
        "✅ Yuklangan" if episode["video_file_id"]
        else "❌ Yuklanmagan"
    )

    await content.edit_text(callback.message,
        f"🎬 {episode['anime_title']}\n"
        f"📺 {episode['season_number']}-fasl\n"
        f"▶️ {episode['episode_number']}-qism\n"
        f"🎞 Video: {video_status}",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 3. Qism raqamini tahrirlashni boshlash
@dp.callback_query(F.data.regexp(r"^episode_editnum_[0-9]{1,18}$"))
async def episode_edit_number_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    episode_id = int(callback.data.split("_")[-1])

    if not get_episode_by_id(episode_id):
        await callback.answer("Qism topilmadi!", show_alert=True)
        return

    await state.update_data(manage_episode_id=episode_id)
    await state.set_state(ManageEpisode.edit_number)

    await callback.message.answer(
        "🔢 Yangi qism raqamini yuboring.\n"
        "Masalan: 5\n\n"
        "Bekor qilish: /cancel"
    )
    await callback.answer()


# 4. Yangi qism raqamini saqlash
@dp.message(ManageEpisode.edit_number)
async def episode_edit_number_save(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❎ Bekor qilindi.")
        return

    if not message.text or not content.numeric_id(message.text.strip()):
        await message.answer("❗ Musbat butun son yuboring.")
        return

    new_number = int(message.text.strip())

    if new_number < 1:
        await message.answer("❗ Qism raqami 1 dan boshlanadi.")
        return

    data = await state.get_data()
    episode_id = data["manage_episode_id"]

    try:
        updated = update_episode_number(episode_id, new_number)
    except db.INTEGRITY_ERRORS:
        await message.answer(
            "❗ Bu raqamli qism shu faslda allaqachon mavjud."
        )
        return

    await state.clear()

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="⬅️ Qism boshqaruviga qaytish",
        callback_data=f"manage_episode_{episode_id}"
    ))

    await message.answer(
        "✅ Qism raqami yangilandi!" if updated
        else "❌ Qism topilmadi.",
        reply_markup=keyboard.as_markup()
    )


# 5. Videoni almashtirishni boshlash
@dp.callback_query(F.data.regexp(r"^episode_replace_[0-9]{1,18}$"))
async def episode_replace_start(
    callback: CallbackQuery,
    state: FSMContext
):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    episode_id = int(callback.data.split("_")[-1])

    if not get_episode_by_id(episode_id):
        await callback.answer("Qism topilmadi!", show_alert=True)
        return

    await state.update_data(manage_episode_id=episode_id)
    await state.set_state(ManageEpisode.replace_video)

    await callback.message.answer(
        "🎞 Yangi videoni yuboring.\n\n"
        "Bekor qilish: /cancel"
    )
    await callback.answer()


# 6. Yangi videoni saqlash
@dp.message(ManageEpisode.replace_video)
async def episode_replace_save(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❎ Bekor qilindi.")
        return

    media, media_type = content.pick_media(message)
    if not media:
        await message.answer("Video yoki video hujjatini yuboring.")
        return
    data = await state.get_data()
    episode_id = data["manage_episode_id"]
    try:
        updated = update_episode_video(episode_id, media.file_id, media_type, media.file_unique_id)
    except db.INTEGRITY_ERRORS:
        await message.answer("Bu video ushbu faslda allaqachon mavjud.")
        return

    await state.clear()

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="⬅️ Qism boshqaruviga qaytish",
        callback_data=f"manage_episode_{episode_id}"
    ))

    await message.answer(
        "✅ Video muvaffaqiyatli almashtirildi!" if updated
        else "❌ Qism topilmadi.",
        reply_markup=keyboard.as_markup()
    )


# 7. Qismni o'chirishni tasdiqlash
@dp.callback_query(F.data.regexp(r"^episode_delete_[0-9]{1,18}$"))
async def episode_delete_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    episode_id = int(callback.data.split("_")[-1])
    episode = get_episode_by_id(episode_id)

    if not episode:
        await callback.answer("Qism topilmadi!", show_alert=True)
        return

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="❌ Yo'q, qaytish",
        callback_data=f"manage_episode_{episode_id}"
    ))
    keyboard.add(content.button(
        text="🗑 Ha, o'chirish",
        callback_data=f"episode_confirmdelete_{episode_id}"
    ))
    keyboard.adjust(1)

    await content.edit_text(callback.message,
        f"⚠️ {episode['anime_title']}\n"
        f"📺 {episode['season_number']}-fasl\n"
        f"▶️ {episode['episode_number']}-qism\n\n"
        "Ushbu qismni bazadan o'chirmoqchimisiz?",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()


# 8. Qismni bazadan o'chirish
@dp.callback_query(F.data.regexp(r"^episode_confirmdelete_[0-9]{1,18}$"))
async def episode_delete_execute(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    episode_id = int(callback.data.split("_")[-1])
    episode = get_episode_by_id(episode_id)

    if not episode:
        await callback.answer("Qism topilmadi!", show_alert=True)
        return

    deleted = delete_episode(episode_id)

    if deleted:
        keyboard = content.MenuKeyboardBuilder()
        keyboard.add(content.button(
            text="⬅️ Qismlar ro'yxatiga qaytish",
            callback_data=f"manage_episodes_{episode['season_id']}"
        ))

        await content.edit_text(callback.message,
            "✅ Qism bazadan o'chirildi.",
            reply_markup=keyboard.as_markup()
        )
    else:
        await callback.answer("O'chirib bo'lmadi!", show_alert=True)
        return

    await callback.answer()


# ==========================================
# ANIVRUM - ANIME QIDIRUV TIZIMI
# ==========================================

# Qidiruvni boshlash
@dp.callback_query(F.data.in_({"anime_search", "search"}))
async def anime_search_start(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext
):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalimizga obuna bo'ling!",
            show_alert=True
        )
        return

    await state.set_state(SearchAnime.query)

    keyboard = content.MenuKeyboardBuilder()
    keyboard.add(content.button(
        text="❌ Bekor qilish",
        callback_data="search_cancel"
    ))

    await callback.message.answer(
        "🔎 Anime qidirish\n\n"
        "Anime nomini yoki kodini yuboring.\n"
        "Masalan: Bercerk yoki 1001",
        reply_markup=keyboard.as_markup()
    )
    await callback.answer()
    await activity.observe_callback(callback, "search")


# Qidiruvni bekor qilish
@dp.callback_query(F.data == "search_cancel")
async def anime_search_cancel(
    callback: CallbackQuery,
    state: FSMContext
):
    await state.clear()

    await content.edit_text(callback.message,
        "❎ Qidiruv bekor qilindi."
    )
    await callback.answer()
    await activity.observe_callback(callback, None)


# Anime nomi yoki kodi orqali qidirish
@dp.message(SearchAnime.query)
async def anime_search_result(
    message: Message,
    bot: Bot,
    state: FSMContext
):
    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            "Avval kanalimizga obuna bo'ling!"
        )
        return

    if not message.text or not message.text.strip():
        await message.answer(
            "❗ Anime nomini yoki kodini matn shaklida yuboring."
        )
        return

    query = message.text.strip()

    if query == "/cancel":
        await state.clear()
        await message.answer("❎ Qidiruv bekor qilindi.")
        return

    extras.track("search")
    results = search_animes(query)
    await state.clear()

    if not results:
        keyboard = content.MenuKeyboardBuilder()
        keyboard.add(content.button(
            text="🔎 Qayta qidirish",
            callback_data="anime_search"
        ))
        keyboard.add(content.button(
            text="⬅️ Animelar ro'yxati",
            callback_data="anime_az"
        ))
        keyboard.adjust(1)

        await message.answer(
            f"🔎 '{query}' bo'yicha anime topilmadi.",
            reply_markup=keyboard.as_markup()
        )
        await activity.observe(message, message.from_user.id, "search")
        return

    keyboard = content.MenuKeyboardBuilder()

    for anime in results:
        keyboard.add(content.button(
            text=f"🎬 {anime['title']}",
            callback_data=f"anime_detail_{anime['id']}"
        ))

    keyboard.adjust(1)

    keyboard.add(content.button(
        text="🔎 Yana qidirish",
        callback_data="anime_search"
    ))
    keyboard.add(content.button(
        text="⬅️ Animelar ro'yxati",
        callback_data="anime_az"
    ))
    keyboard.adjust(1)

    await message.answer(
        f"🔎 Qidiruv: {query}\n\n"
        f"✅ {len(results)} ta anime topildi.\n"
        "Ko'rish uchun animeni tanlang:",
        reply_markup=keyboard.as_markup()
    )
    await activity.observe(message, message.from_user.id, "search")


# Asosiy menyuga qaytish
@dp.callback_query(F.data.in_({"back_home", "back_main"}))
async def back_home(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalga obuna bo'ling!",
            show_alert=True
        )
        await content.edit_text(callback.message,
            "🔒 Botdan foydalanish uchun kanalga obuna bo'ling.",
            reply_markup=subscription_keyboard()
        )
        return

    await content.edit_text(callback.message,
        f"🎬 {content.BRAND_NAME}\n\nXush kelibsiz! Bo‘limni tanlang.",
        reply_markup=main_keyboard()
    )
    await callback.answer()
    await activity.observe_callback(callback, "home")


# ==========================================
# ANIVRUM - BOT HAQIDA
# ==========================================

@dp.callback_query(F.data == "about")
async def about_handler(callback: CallbackQuery):
    keyboard = content.MenuKeyboardBuilder()

    keyboard.add(content.button(
        text="📢 Rasmiy kanal",
        url="https://t.me/AniVrum"
    ))

    keyboard.add(content.button(
        text="🏠 Asosiy menyu",
        callback_data="back_main"
    ))

    keyboard.adjust(1)

    await content.edit_text(callback.message,
        f"ℹ️ {content.BRAND_NAME}\n\n"
        "Katalogdan anime tanlang yoki nomi va kodi bo‘yicha qidiring. "
        "Qismlarni bittalab yoki butun fasl qilib olishingiz mumkin.\n\n"
        "📢 Rasmiy kanal: @AniVrum\n\n"
        "Maxfiylik: faollik sanasi va umumiy foydalanish sonlari statistikaga yoziladi. "
        "Izoh yuborsangiz, matn va Telegram profilingiz administratorga ko‘rinadi.",
        reply_markup=keyboard.as_markup()
    )

    await callback.answer()
    await activity.observe_callback(callback, "about")


# ==========================================
# ANIVRUM - ASOSIY MENYUGA QAYTISH
# ==========================================

# ==========================================
# ANIVRUM - SEVIMLILAR TIZIMI
# ==========================================


@dp.callback_query(F.data.regexp(r"^fav_add_[0-9]{1,18}$"))
async def favorite_add_handler(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
        return

    anime_id = int(callback.data.removeprefix("fav_add_"))
    anime = store.anime_content(anime_id)

    if not anime or not anime["visible"]:
        await callback.answer(
            "Anime topilmadi!",
            show_alert=True
        )
        return

    added = add_favorite(
        callback.from_user.id,
        anime_id
    )

    await callback.answer(
        "⭐ Sevimlilarga qo'shildi!"
        if added else
        "Bu anime allaqachon sevimlilaringizda!"
    )

    # Anime sahifasini yangilash
    await callback.message.edit_reply_markup(
        reply_markup=anime_detail_keyboard(
            anime_id,
            callback.from_user.id
        )
    )


# Anime sahifasi tugmalarini yaratish
def anime_detail_keyboard(anime_id, user_id):
    item = store.anime_content(anime_id)
    return content.detail_buttons(item, user_id) if item and item["visible"] else None


# ==========================================
# ANIVRUM - SEVIMLILAR TIZIMI
# O'CHIRISH VA RO'YXATNI BOSHQARISH
# ==========================================


# Sevimlilardan olib tashlash
@dp.callback_query(F.data.regexp(r"^fav_remove_[0-9]{1,18}$"))
async def favorite_remove_handler(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
        return

    anime_id = int(callback.data.removeprefix("fav_remove_"))

    if not store.anime_content(anime_id):
        await callback.answer("Anime topilmadi.", show_alert=True)
        return

    remove_favorite(
        callback.from_user.id,
        anime_id
    )

    await callback.answer(
        "🗑 Sevimlilardan olib tashlandi!"
    )

    # Foydalanuvchi sevimlilar ro'yxatida bo'lsa
    if callback.message.text and (
        "SEVIMLI ANIMELAR" in callback.message.text
        or "SEVIMLI ANIME VA KINOLAR" in callback.message.text
        or "⭐ SEVIMLILAR" in callback.message.text
    ):
        await show_favorites(callback)

    # Foydalanuvchi anime sahifasida bo'lsa
    else:
        await callback.message.edit_reply_markup(
            reply_markup=anime_detail_keyboard(
                anime_id,
                callback.from_user.id
            )
        )


# Sevimlilar ro'yxatini ko'rsatish
async def show_favorites(callback: CallbackQuery):

    animes = get_user_favorites(callback.from_user.id)

    keyboard = content.MenuKeyboardBuilder()

    if not animes:
        text = (
            "⭐ SEVIMLILAR\n\n"
            "Sevimlilar ro‘yxati hozircha bo‘sh.\n\n"
            "Anime sahifasidan "
            "sevimlilarga qo‘shing."
        )

    else:
        text = (
            "⭐ SEVIMLI ANIMELAR\n\n"
            f"📚 Jami: {len(animes)} ta\n\n"
            "👇 Ko'rish uchun animeni tanlang:"
        )

        for anime in animes:

            keyboard.add(content.button(
                text=f"🎬 {anime['title']}",
                callback_data=f"anime_detail_{anime['id']}"
            ))

            keyboard.add(content.button(
                text=f"🗑 {anime['title']} — o'chirish",
                callback_data=f"fav_remove_{anime['id']}"
            ))

    # Animelar katalogiga o'tish
    keyboard.add(content.button(
        text="🎌 Animelar katalogi",
        callback_data="anime"
    ))

    # Asosiy menyuga qaytish
    keyboard.add(content.button(
        text="🏠 Asosiy menyu",
        callback_data="back_main"
    ))

    keyboard.adjust(1)

    await content.edit_text(callback.message,
        text,
        reply_markup=keyboard.as_markup()
    )
    await activity.observe_callback(callback, "favorites")


# Asosiy menyudagi sevimlilar tugmasi
@dp.callback_query(F.data == "favorites")
async def favorites_handler(callback: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer("Avval kanalga obuna bo‘ling.", show_alert=True)
        return

    await show_favorites(callback)

    await callback.answer()


# ==========================================
# ANIVRUM - TOP 10 ANIMELAR
# ==========================================

@dp.callback_query(F.data == "top_animes")
async def top_animes_handler(callback: CallbackQuery, bot: Bot):

    if not await is_subscribed(bot, callback.from_user.id):
        await callback.answer(
            "Avval kanalimizga obuna bo'ling!",
            show_alert=True
        )
        return

    animes = get_top_animes(10)
    keyboard = content.MenuKeyboardBuilder()

    if not animes:
        text = (
            f"🔥 {content.BRAND_NAME} · TOP-10\n\n"
            "📊 Hozircha ko'rishlar statistikasi yo'q.\n"
            "Birinchi tomoshabinlardan biri bo'ling!"
        )
    else:
        text = f"🔥 {content.BRAND_NAME} · TOP-10\n\n"

        medals = ["🥇", "🥈", "🥉"]

        for index, anime in enumerate(animes):
            rank = (
                medals[index]
                if index < 3
                else f"{index + 1}."
            )

            text += (
                f"{rank} {anime['title']}\n"
                f"👁 {anime['views']} ta ochilish\n\n"
            )

            keyboard.add(content.button(
                text=f"{rank} {anime['title']}",
                callback_data=f"anime_detail_{anime['id']}"
            ))

    keyboard.add(content.button(
        text="🎌 Animelar katalogi",
        callback_data="anime"
    ))

    keyboard.add(content.button(
        text="🏠 Asosiy menyu",
        callback_data="back_main"
    ))

    keyboard.adjust(1)

    await content.edit_text(callback.message,
        text,
        reply_markup=keyboard.as_markup()
    )

    await callback.answer()
    await activity.observe_callback(callback, "top")


content.install(dp, lambda: ADMIN_ID, CHANNEL, is_subscribed, AddAnime)
extras.install(dp, lambda: ADMIN_ID, CHANNEL, is_subscribed, AddAnime)


@dp.message(StateFilter(None), F.text.regexp(r"^\s*[0-9]+\s*$"))
async def open_anime_by_code(message: Message, bot: Bot):
    item = store.by_code(message.text.strip(), "anime")
    user_id = message.from_user.id
    if not await is_subscribed(bot, user_id):
        await message.answer(
            f"{content.BRAND_NAME}\n\nDavom etish uchun kanalga obuna bo‘ling.",
            reply_markup=subscription_keyboard(item["id"] if item else None),
        )
    elif item:
        await content.show_detail(message, user_id, item["id"], protect_content=user_id != ADMIN_ID)
    else:
        await message.answer("❌ Bu kod bo'yicha anime topilmadi")


@dp.errors()
async def handle_update_error(event):
    extras.track("error")
    log.error("Telegram yangilanishida xato. Turi: %s", type(event.exception).__name__)


# Botni ishga tushirish
async def main(*, load_local_env=True, handle_signals=True, database_path=None):
    global ADMIN_ID
    if load_local_env:
        load_dotenv(BASE_DIR / ".env")
    try:
        postgres_url = db.database_url()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    if database_path is not None and postgres_url:
        raise SystemExit("SQLite sinov yo‘li va DATABASE_URL birga ishlatilmaydi.")
    token = os.getenv("BOT_TOKEN")
    admin = os.getenv("ADMIN_ID", "")
    if not token or not content.numeric_id(admin) or not int(admin):
        raise SystemExit("BOT_TOKEN va ADMIN_ID muhit o‘zgaruvchilarini sozlang.")
    ADMIN_ID = int(admin)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        db.DB_PATH = database_path
    try:
        store.migrate()
        if activity.enabled():
            activity_store.migrate()
        store.prune_statistics()
    except db.DATABASE_ERRORS as error:
        log.error("Ma’lumotlar bazasi ishga tayyorlanmadi. Turi: %s", type(error).__name__)
        raise SystemExit("Ma’lumotlar bazasi ulanishi yoki sxemasini tekshiring.") from None
    try:
        bot = Bot(token=token)
    except TokenValidationError:
        raise SystemExit("BOT_TOKEN formati noto‘g‘ri.") from None
    log.info("AniVrum Telegram polling ishga tushirilmoqda.")
    activity_cleanup = asyncio.create_task(activity.prune_loop()) if activity.enabled() else None
    try:
        await dp.start_polling(bot, handle_signals=handle_signals, close_bot_session=False)
    except TelegramAPIError:
        raise SystemExit("Telegram bilan ulanishda xato.") from None
    finally:
        jobs = list(season_downloads.jobs.values())
        if activity_cleanup:
            jobs.append(activity_cleanup)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
