import asyncio
import logging

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============== SOZLAMALAR ==============
BOT_TOKEN = "8823978968:AAGDyBy20w6tZ48ODQCxZ-DhfYaTrRvp5oc"   # @BotFather dan oling
ADMIN_IDS = [8564193971]                       # @userinfobot dan o'z ID'ingizni bilib oling (bosh admin)
DB_PATH = "anime_bot.db"
PAGE_SIZE = 8
# =========================================

logging.basicConfig(level=logging.INFO)
router = Router()

ALL_MENU_BUTTONS = {
    "search": "🔍 Qidirish",
    "all": "📃 Barcha animelar",
    "random": "🎲 Tasodifiy anime",
    "top": "🏆 Top reyting",
}

CANCEL_TEXT = "❌ Bekor qilish"


# ============================================================
#                        DATABASE
# ============================================================

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    is_admin INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS animes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    poster_file_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    video_file_id TEXT NOT NULL,
    FOREIGN KEY (anime_id) REFERENCES animes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ratings (
    user_id INTEGER NOT NULL,
    anime_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    PRIMARY KEY (user_id, anime_id),
    FOREIGN KEY (anime_id) REFERENCES animes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS required_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    title TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES_SQL)
        await db.commit()
        for admin_id in ADMIN_IDS:
            await db.execute(
                "INSERT INTO users (user_id, is_admin) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET is_admin=1",
                (admin_id,),
            )
        await db.commit()


# ---------- users / admins ----------

async def add_user(user_id, full_name, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)",
            (user_id, full_name, username),
        )
        await db.execute(
            "UPDATE users SET full_name=?, username=? WHERE user_id=?",
            (full_name, username, user_id),
        )
        await db.commit()


async def is_admin_db(user_id) -> bool:
    if user_id in ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT is_admin FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return bool(row and row[0])


async def make_admin(user_id) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        if not await cur.fetchone():
            return False
        await db.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (user_id,))
        await db.commit()
        return True


async def get_users_count():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


# ---------- animes / episodes ----------

async def add_anime(title, description, poster_file_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO animes (title, description, poster_file_id) VALUES (?, ?, ?)",
            (title, description, poster_file_id),
        )
        await db.commit()
        return cur.lastrowid


async def get_all_animes():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM animes ORDER BY title")
        return await cur.fetchall()


async def count_animes():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM animes")
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_animes_page(page: int, page_size: int = PAGE_SIZE):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM animes ORDER BY title LIMIT ? OFFSET ?",
            (page_size, page * page_size),
        )
        return await cur.fetchall()


async def search_animes(query):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM animes WHERE title LIKE ? ORDER BY title", (f"%{query}%",)
        )
        return await cur.fetchall()


async def get_anime(anime_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM animes WHERE id = ?", (anime_id,))
        return await cur.fetchone()


async def get_random_anime():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM animes ORDER BY RANDOM() LIMIT 1")
        return await cur.fetchone()


async def delete_anime(anime_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM animes WHERE id = ?", (anime_id,))
        await db.commit()


async def add_episode(anime_id, episode_number, video_file_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO episodes (anime_id, episode_number, video_file_id) VALUES (?, ?, ?)",
            (anime_id, episode_number, video_file_id),
        )
        await db.commit()
        return cur.lastrowid


async def get_episodes(anime_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM episodes WHERE anime_id = ? ORDER BY episode_number", (anime_id,)
        )
        return await cur.fetchall()


async def get_episode(episode_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        return await cur.fetchone()


# ---------- ratings ----------

async def set_rating(user_id, anime_id, score):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ratings (user_id, anime_id, score) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, anime_id) DO UPDATE SET score=excluded.score",
            (user_id, anime_id, score),
        )
        await db.commit()


async def get_anime_rating(anime_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT AVG(score), COUNT(*) FROM ratings WHERE anime_id=?", (anime_id,)
        )
        row = await cur.fetchone()
        avg = round(row[0], 1) if row and row[0] else 0
        count = row[1] if row else 0
        return avg, count


async def get_top_animes(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT a.*, AVG(r.score) as avg_score, COUNT(r.score) as cnt
               FROM animes a JOIN ratings r ON r.anime_id = a.id
               GROUP BY a.id ORDER BY avg_score DESC, cnt DESC LIMIT ?""",
            (limit,),
        )
        return await cur.fetchall()


# ---------- majburiy obuna ----------

async def add_required_channel(chat_id, title):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO required_channels (chat_id, title) VALUES (?, ?)", (chat_id, title)
        )
        await db.commit()


async def remove_required_channel(channel_db_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM required_channels WHERE id=?", (channel_db_id,))
        await db.commit()


async def get_required_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM required_channels")
        return await cur.fetchall()


# ---------- menyu sozlamalari ----------

async def get_visible_buttons() -> set:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='visible_buttons'")
        row = await cur.fetchone()
        if not row:
            return set(ALL_MENU_BUTTONS.keys())
        return set(row[0].split(",")) if row[0] else set()


async def set_visible_buttons(codes: set):
    value = ",".join(codes)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('visible_buttons', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (value,),
        )
        await db.commit()


# ============================================================
#                       FSM HOLATLARI
# ============================================================

class AddAnime(StatesGroup):
    title = State()
    description = State()
    poster = State()


class AddEpisode(StatesGroup):
    episode_number = State()
    video = State()


class SearchAnime(StatesGroup):
    query = State()


class Broadcast(StatesGroup):
    message = State()


class AddAdminState(StatesGroup):
    user_id = State()


class AddChannelState(StatesGroup):
    channel = State()


# ============================================================
#              REPLY KLAVIATURALAR (ASOSIY NAVIGATSIYA)
# ============================================================

def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Anime qo'shish"), KeyboardButton(text="🗑 Anime o'chirish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="📢 Xabar yuborish")],
            [KeyboardButton(text="👤 Admin qo'shish"), KeyboardButton(text="📋 Menyu sozlash")],
            [KeyboardButton(text="🔒 Majburiy obuna"), KeyboardButton(text="👥 Foydalanuvchi menyusi")],
        ],
        resize_keyboard=True,
    )


async def user_menu_kb(admin_flag: bool = False) -> ReplyKeyboardMarkup:
    visible = await get_visible_buttons()
    keyboard = []
    row = []
    for code in ["search", "all", "random", "top"]:
        if code in visible:
            row.append(KeyboardButton(text=ALL_MENU_BUTTONS[code]))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)
    if admin_flag:
        keyboard.append([KeyboardButton(text="🛠 Admin panel")])
    if not keyboard:
        keyboard = [[KeyboardButton(text="🛠 Admin panel")]] if admin_flag else [[KeyboardButton(text="/start")]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL_TEXT)]], resize_keyboard=True)


# ============================================================
#                  INLINE KLAVIATURALAR (ICHKI BOSHQARUV)
# ============================================================

def animes_page_kb(animes, page, total):
    b = InlineKeyboardBuilder()
    for anime in animes:
        b.row(InlineKeyboardButton(text=anime["title"], callback_data=f"anime:{anime['id']}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"all:{page-1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"all:{page+1}"))
    if nav:
        b.row(*nav)
    return b.as_markup()


def simple_list_kb(animes, prefix="anime"):
    b = InlineKeyboardBuilder()
    for anime in animes:
        label = anime["title"]
        if "avg_score" in anime.keys():
            label = f"{anime['title']} ⭐{round(anime['avg_score'], 1)}"
        b.row(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{anime['id']}"))
    return b.as_markup()


def anime_detail_kb(anime_id, episodes, user_score, is_admin_user):
    b = InlineKeyboardBuilder()
    row = []
    for ep in episodes:
        row.append(InlineKeyboardButton(text=str(ep["episode_number"]), callback_data=f"episode:{ep['id']}"))
        if len(row) == 5:
            b.row(*row)
            row = []
    if row:
        b.row(*row)

    rate_row = []
    for i in range(1, 6):
        mark = "★" if user_score and i <= user_score else "☆"
        rate_row.append(InlineKeyboardButton(text=mark, callback_data=f"rate:{anime_id}:{i}"))
    b.row(*rate_row)

    if is_admin_user:
        b.row(
            InlineKeyboardButton(text="🎬 Qism qo'shish", callback_data=f"addep:{anime_id}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delan:{anime_id}"),
        )
    return b.as_markup()


def confirm_delete_kb(anime_id):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"del_confirm:{anime_id}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data="del_cancel"),
    )
    return b.as_markup()


async def menu_settings_kb():
    visible = await get_visible_buttons()
    b = InlineKeyboardBuilder()
    for code, label in ALL_MENU_BUTTONS.items():
        mark = "✅" if code in visible else "⬜️"
        b.row(InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"toggle:{code}"))
    return b.as_markup()


async def force_sub_kb():
    channels = await get_required_channels()
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(InlineKeyboardButton(text=f"🗑 {ch['title'] or ch['chat_id']}", callback_data=f"fs:remove:{ch['id']}"))
    b.row(InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="fs:add"))
    return b.as_markup()


def subscribe_check_kb(channels):
    b = InlineKeyboardBuilder()
    for ch in channels:
        cid = ch["chat_id"]
        if cid.startswith("@"):
            url = f"https://t.me/{cid[1:]}"
            b.row(InlineKeyboardButton(text=f"➕ {ch['title'] or cid}", url=url))
    b.row(InlineKeyboardButton(text="✅ Tekshirdim", callback_data="check_sub"))
    return b.as_markup()


# ============================================================
#                   MAJBURIY OBUNA TEKSHIRISH
# ============================================================

async def check_subscription(bot: Bot, user_id: int) -> bool:
    channels = await get_required_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return False
        except TelegramBadRequest:
            continue
    return True


async def send_subscription_required(message: Message):
    channels = await get_required_channels()
    await message.answer(
        "Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling, so'ng "
        "\"✅ Tekshirdim\" tugmasini bosing:",
        reply_markup=subscribe_check_kb(channels),
    )


# ============================================================
#                   BEKOR QILISH (har qanday holatda)
# ============================================================

@router.message(F.text == CANCEL_TEXT)
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    admin_flag = await is_admin_db(message.from_user.id)
    if admin_flag:
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
    else:
        await message.answer("Bekor qilindi.", reply_markup=await user_menu_kb())


# ============================================================
#                       START / MENYU
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await add_user(message.from_user.id, message.from_user.full_name, message.from_user.username)

    if not await check_subscription(message.bot, message.from_user.id):
        await send_subscription_required(message)
        return

    if await is_admin_db(message.from_user.id):
        await message.answer(
            f"Salom, Admin {message.from_user.full_name}! 👋\n\nAdmin panel:",
            reply_markup=admin_menu_kb(),
        )
    else:
        await message.answer(
            f"Salom, {message.from_user.full_name}! 👋\n\nAnime botga xush kelibsiz.",
            reply_markup=await user_menu_kb(),
        )


@router.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.bot, callback.from_user.id):
        await callback.message.delete()
        admin_flag = await is_admin_db(callback.from_user.id)
        if admin_flag:
            await callback.message.answer("✅ Obuna tasdiqlandi! Admin panel:", reply_markup=admin_menu_kb())
        else:
            await callback.message.answer("✅ Obuna tasdiqlandi!", reply_markup=await user_menu_kb())
    else:
        await callback.answer("Hali barcha kanallarga obuna bo'lmadingiz.", show_alert=True)


@router.message(F.text == "👥 Foydalanuvchi menyusi")
async def to_user_menu(message: Message):
    admin_flag = await is_admin_db(message.from_user.id)
    await message.answer("Foydalanuvchi menyusi:", reply_markup=await user_menu_kb(admin_flag))


@router.message(F.text == "🛠 Admin panel")
async def to_admin_menu(message: Message):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer("Admin panel:", reply_markup=admin_menu_kb())


# ============================================================
#                  FOYDALANUVCHI: ANIME KO'RISH
# ============================================================

@router.message(F.text == "🔍 Qidirish")
async def search_start(message: Message, state: FSMContext):
    await message.answer("Anime nomini kiriting:", reply_markup=cancel_kb())
    await state.set_state(SearchAnime.query)


@router.message(SearchAnime.query)
async def search_process(message: Message, state: FSMContext):
    await state.clear()
    admin_flag = await is_admin_db(message.from_user.id)
    results = await search_animes(message.text.strip())
    if not results:
        await message.answer("Hech narsa topilmadi 😕", reply_markup=await user_menu_kb(admin_flag))
        return
    await message.answer(
        "Topilgan natijalar:",
        reply_markup=await user_menu_kb(admin_flag),
    )
    await message.answer("Natijalar ro'yxati:", reply_markup=simple_list_kb(results))


@router.message(F.text == "📃 Barcha animelar")
async def list_animes_first(message: Message):
    total = await count_animes()
    animes = await get_animes_page(0)
    if not animes:
        await message.answer("Hozircha animelar qo'shilmagan.")
        return
    await message.answer(
        f"📃 Barcha animelar ({total} ta):", reply_markup=animes_page_kb(animes, 0, total)
    )


@router.callback_query(F.data.startswith("all:"))
async def list_animes_page(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    total = await count_animes()
    animes = await get_animes_page(page)
    if not animes:
        await callback.answer("Sahifa topilmadi.", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            f"📃 Barcha animelar ({total} ta):", reply_markup=animes_page_kb(animes, page, total)
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(F.text == "🎲 Tasodifiy anime")
async def random_anime(message: Message):
    anime = await get_random_anime()
    if not anime:
        await message.answer("Hozircha animelar yo'q.")
        return
    await send_anime_card(message, anime["id"])


@router.message(F.text == "🏆 Top reyting")
async def top_animes(message: Message):
    top = await get_top_animes()
    if not top:
        await message.answer("Hozircha reyting yo'q.")
        return
    await message.answer("🏆 Top reytingdagi animelar:", reply_markup=simple_list_kb(top))


async def get_user_score(user_id, anime_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT score FROM ratings WHERE user_id=? AND anime_id=?", (user_id, anime_id)
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def build_anime_text(anime, episodes):
    avg, count = await get_anime_rating(anime["id"])
    return (
        f"<b>{anime['title']}</b>\n\n"
        f"{anime['description'] or ''}\n\n"
        f"⭐ Reyting: {avg} ({count} ovoz)\n"
        f"🎬 Qismlar: {len(episodes)}"
    )


async def send_anime_card(message: Message, anime_id: int):
    anime = await get_anime(anime_id)
    if not anime:
        await message.answer("Anime topilmadi.")
        return
    episodes = await get_episodes(anime_id)
    text = await build_anime_text(anime, episodes)
    user_score = await get_user_score(message.from_user.id, anime_id)
    admin_flag = await is_admin_db(message.from_user.id)
    kb = anime_detail_kb(anime_id, episodes, user_score, admin_flag)

    if anime["poster_file_id"]:
        await message.answer_photo(anime["poster_file_id"], caption=text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("anime:"))
async def show_anime(callback: CallbackQuery):
    anime_id = int(callback.data.split(":")[1])
    anime = await get_anime(anime_id)
    if not anime:
        await callback.answer("Anime topilmadi.", show_alert=True)
        return
    episodes = await get_episodes(anime_id)
    text = await build_anime_text(anime, episodes)
    user_score = await get_user_score(callback.from_user.id, anime_id)
    admin_flag = await is_admin_db(callback.from_user.id)
    kb = anime_detail_kb(anime_id, episodes, user_score, admin_flag)

    if anime["poster_file_id"]:
        await callback.message.answer_photo(anime["poster_file_id"], caption=text, reply_markup=kb)
    else:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("episode:"))
async def send_episode(callback: CallbackQuery):
    episode_id = int(callback.data.split(":")[1])
    episode = await get_episode(episode_id)
    if not episode:
        await callback.answer("Qism topilmadi.", show_alert=True)
        return
    await callback.message.answer_video(
        episode["video_file_id"], caption=f"{episode['episode_number']}-qism"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rate:"))
async def rate_anime(callback: CallbackQuery):
    _, anime_id, score = callback.data.split(":")
    anime_id, score = int(anime_id), int(score)
    await set_rating(callback.from_user.id, anime_id, score)

    episodes = await get_episodes(anime_id)
    admin_flag = await is_admin_db(callback.from_user.id)
    kb = anime_detail_kb(anime_id, episodes, score, admin_flag)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass
    await callback.answer(f"Siz {score} ★ baho berdingiz!")


# ============================================================
#                       ADMIN: ANIME QO'SHISH
# ============================================================

@router.message(F.text == "➕ Anime qo'shish")
async def add_anime_start(message: Message, state: FSMContext):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer("Anime nomini kiriting:", reply_markup=cancel_kb())
    await state.set_state(AddAnime.title)


@router.message(AddAnime.title)
async def add_anime_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Anime haqida qisqacha tavsif kiriting:")
    await state.set_state(AddAnime.description)


@router.message(AddAnime.description)
async def add_anime_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("Poster (rasm) yuboring. O'tkazib yuborish uchun /skip yozing.")
    await state.set_state(AddAnime.poster)


@router.message(AddAnime.poster, Command("skip"))
async def add_anime_poster_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    anime_id = await add_anime(data["title"], data["description"], None)
    await state.clear()
    await message.answer(
        f"✅ Anime qo'shildi: {data['title']} (ID: {anime_id})", reply_markup=admin_menu_kb()
    )


@router.message(AddAnime.poster, F.photo)
async def add_anime_poster(message: Message, state: FSMContext):
    data = await state.get_data()
    poster_file_id = message.photo[-1].file_id
    anime_id = await add_anime(data["title"], data["description"], poster_file_id)
    await state.clear()
    await message.answer(
        f"✅ Anime qo'shildi: {data['title']} (ID: {anime_id})", reply_markup=admin_menu_kb()
    )


# ---------- qism qo'shish (anime kartasidan) ----------

@router.callback_query(F.data.startswith("addep:"))
async def add_episode_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin_db(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    anime_id = int(callback.data.split(":")[1])
    await state.update_data(anime_id=anime_id)
    await callback.message.answer("Qism raqamini kiriting (masalan: 1):", reply_markup=cancel_kb())
    await state.set_state(AddEpisode.episode_number)
    await callback.answer()


@router.message(AddEpisode.episode_number)
async def add_episode_number(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Iltimos, faqat raqam kiriting.")
        return
    await state.update_data(episode_number=int(message.text.strip()))
    await message.answer("Endi shu qismning videosini yuboring:")
    await state.set_state(AddEpisode.video)


@router.message(AddEpisode.video, F.video)
async def add_episode_video(message: Message, state: FSMContext):
    data = await state.get_data()
    video_file_id = message.video.file_id
    await add_episode(data["anime_id"], data["episode_number"], video_file_id)
    await state.clear()
    await message.answer(
        f"✅ {data['episode_number']}-qism qo'shildi!", reply_markup=admin_menu_kb()
    )


@router.message(AddEpisode.video)
async def add_episode_video_invalid(message: Message):
    await message.answer("Iltimos, video fayl yuboring.")


# ============================================================
#                       ADMIN: ANIME O'CHIRISH
# ============================================================

@router.message(F.text == "🗑 Anime o'chirish")
async def delete_anime_start(message: Message):
    if not await is_admin_db(message.from_user.id):
        return
    animes = await get_all_animes()
    if not animes:
        await message.answer("O'chirish uchun anime topilmadi.")
        return
    await message.answer("O'chirmoqchi bo'lgan animeni tanlang:", reply_markup=simple_list_kb(animes, prefix="delan"))


@router.callback_query(F.data.startswith("delan:"))
async def delete_anime_confirm(callback: CallbackQuery):
    if not await is_admin_db(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    anime_id = int(callback.data.split(":")[1])
    anime = await get_anime(anime_id)
    if not anime:
        await callback.answer("Topilmadi.", show_alert=True)
        return
    await callback.message.answer(
        f"<b>{anime['title']}</b> ni rostdan ham o'chirmoqchimisiz? "
        "Bu barcha qismlarni ham o'chirib tashlaydi.",
        reply_markup=confirm_delete_kb(anime_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_confirm:"))
async def delete_anime_execute(callback: CallbackQuery):
    anime_id = int(callback.data.split(":")[1])
    await delete_anime(anime_id)
    await callback.message.edit_text("🗑 Anime o'chirildi.")
    await callback.answer()


@router.callback_query(F.data == "del_cancel")
async def delete_anime_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()


# ============================================================
#                       ADMIN: STATISTIKA
# ============================================================

@router.message(F.text == "📊 Statistika")
async def stats(message: Message):
    if not await is_admin_db(message.from_user.id):
        return
    users_count = await get_users_count()
    animes = await get_all_animes()
    total_episodes = sum(len(await get_episodes(a["id"])) for a in animes)
    text = (
        f"📊 <b>Statistika</b>\n\n"
        f"👤 Foydalanuvchilar: {users_count}\n"
        f"🎞 Animelar: {len(animes)}\n"
        f"🎬 Qismlar: {total_episodes}"
    )
    await message.answer(text)


# ============================================================
#                  ADMIN: XABAR YUBORISH (BROADCAST)
# ============================================================

@router.message(F.text == "📢 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer(
        "Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring "
        "(matn, rasm, video — istalgani bo'lishi mumkin):",
        reply_markup=cancel_kb(),
    )
    await state.set_state(Broadcast.message)


@router.message(Broadcast.message)
async def broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    user_ids = await get_all_user_ids()
    sent, failed = 0, 0
    status_msg = await message.answer(f"Yuborilmoqda... 0/{len(user_ids)}")
    for uid in user_ids:
        try:
            await message.copy_to(uid)
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 25 == 0:
            try:
                await status_msg.edit_text(f"Yuborilmoqda... {sent + failed}/{len(user_ids)}")
            except TelegramBadRequest:
                pass
        await asyncio.sleep(0.05)
    await message.answer(
        f"✅ Xabar yuborildi!\nMuvaffaqiyatli: {sent}\nXatolik: {failed}",
        reply_markup=admin_menu_kb(),
    )


# ============================================================
#                       ADMIN: ADMIN QO'SHISH
# ============================================================

@router.message(F.text == "👤 Admin qo'shish")
async def add_admin_start(message: Message, state: FSMContext):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer(
        "Yangi admin qilmoqchi bo'lgan foydalanuvchi Telegram ID raqamini yuboring.\n"
        "(Foydalanuvchi avval botga /start bosgan bo'lishi kerak. ID ni @userinfobot orqali bilish mumkin)",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddAdminState.user_id)


@router.message(AddAdminState.user_id)
async def add_admin_process(message: Message, state: FSMContext):
    await state.clear()
    if not message.text.strip().isdigit():
        await message.answer("Iltimos, faqat raqamli ID kiriting.", reply_markup=admin_menu_kb())
        return
    user_id = int(message.text.strip())
    ok = await make_admin(user_id)
    if ok:
        await message.answer(f"✅ {user_id} endi admin!", reply_markup=admin_menu_kb())
    else:
        await message.answer(
            "❌ Bu foydalanuvchi hali botga /start bosmagan. Avval u botni ishga tushirsin.",
            reply_markup=admin_menu_kb(),
        )


# ============================================================
#                  ADMIN: MENYU SOZLASH
# ============================================================

@router.message(F.text == "📋 Menyu sozlash")
async def menu_settings_open(message: Message):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer(
        "Foydalanuvchilarga ko'rinadigan tugmalarni tanlang:", reply_markup=await menu_settings_kb()
    )


@router.callback_query(F.data.startswith("toggle:"))
async def menu_toggle(callback: CallbackQuery):
    if not await is_admin_db(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return
    code = callback.data.split(":")[1]
    visible = await get_visible_buttons()
    if code in visible:
        visible.discard(code)
    else:
        visible.add(code)
    await set_visible_buttons(visible)
    await callback.message.edit_reply_markup(reply_markup=await menu_settings_kb())
    await callback.answer()


# ============================================================
#                  ADMIN: MAJBURIY OBUNA
# ============================================================

@router.message(F.text == "🔒 Majburiy obuna")
async def force_sub_open(message: Message):
    if not await is_admin_db(message.from_user.id):
        return
    await message.answer(
        "🔒 Majburiy obuna kanallari.\nO'chirish uchun kanal nomini bosing:",
        reply_markup=await force_sub_kb(),
    )


@router.callback_query(F.data.startswith("fs:remove:"))
async def force_sub_remove(callback: CallbackQuery):
    channel_db_id = int(callback.data.split(":")[2])
    await remove_required_channel(channel_db_id)
    await callback.message.edit_reply_markup(reply_markup=await force_sub_kb())
    await callback.answer("O'chirildi.")


@router.callback_query(F.data == "fs:add")
async def force_sub_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Kanal username'ini yuboring (masalan: @mychannel).\n"
        "Eslatma: bot o'sha kanalda ADMIN bo'lishi kerak, aks holda obunani tekshira olmaydi.",
        reply_markup=cancel_kb(),
    )
    await state.set_state(AddChannelState.channel)
    await callback.answer()


@router.message(AddChannelState.channel)
async def force_sub_add_process(message: Message, state: FSMContext):
    await state.clear()
    text = message.text.strip()
    if not text.startswith("@"):
        await message.answer("Username @ bilan boshlanishi kerak. Masalan: @mychannel", reply_markup=admin_menu_kb())
        return
    try:
        chat = await message.bot.get_chat(text)
    except TelegramBadRequest:
        await message.answer("Kanal topilmadi yoki bot u yerga qo'shilmagan.", reply_markup=admin_menu_kb())
        return
    await add_required_channel(text, chat.title)
    await message.answer(f"✅ Kanal qo'shildi: {chat.title}", reply_markup=admin_menu_kb())


# ============================================================
#                       ISHGA TUSHIRISH
# ============================================================

async def main():
    if BOT_TOKEN == "BOT_TOKEN_NI_BU_YERGA_YOZING":
        raise RuntimeError("Fayl boshidagi BOT_TOKEN ni o'zgartiring!")

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot to'xtatildi.")
