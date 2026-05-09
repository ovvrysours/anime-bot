import asyncio
import logging
import aiohttp
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, Boolean, select

# ══════════════════════════════════════════
#  SOZLAMALAR (CONFIG)
# ══════════════════════════════════════════
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

API_TOKEN   = os.getenv("API_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "XXXX XXXX XXXX XXXX")
DATABASE_URL = "sqlite+aiosqlite:///./anime_bot.db"
JIKAN_API_URL = "https://api.jikan.moe/v4"

# ══════════════════════════════════════════
#  MA'LUMOTLAR BAZASI (DATABASE)
# ══════════════════════════════════════════
Base = declarative_base()
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username    = Column(String, nullable=True)
    full_name   = Column(String, nullable=True)
    balance     = Column(Float, default=0.0)
    is_vip      = Column(Boolean, default=False)


class AnimeVideo(Base):
    __tablename__ = "anime_videos"
    id      = Column(Integer, primary_key=True)
    title   = Column(String, nullable=False)
    file_id = Column(String, nullable=False)


class Request(Base):
    __tablename__ = "requests"
    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, nullable=False)
    user_name = Column(String, nullable=True)
    prompt    = Column(String, nullable=True)
    status    = Column(String, default="pending")  # pending | approved | rejected


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Ma'lumotlar bazasi tayyor.")


# ══════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ══════════════════════════════════════════
async def get_or_create_user(session: AsyncSession, tg_user) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id)
    )
    user = result.scalars().first()
    if not user:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        session.add(user)
        await session.commit()
        logger.info(f"Yangi foydalanuvchi: {tg_user.full_name} (ID: {tg_user.id})")
    return user


def request_action_kb(req_id: int) -> InlineKeyboardMarkup:
    """Ariza uchun Tasdiqlash / Rad etish tugmalari."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{req_id}"),
        InlineKeyboardButton(text="❌ Rad etish",  callback_data=f"reject_{req_id}"),
    ]])


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🔍 Anime izlash"),
         KeyboardButton(text="🖥 Anime malumot qidiruv")],
        [KeyboardButton(text="💎 VIP")],
        [KeyboardButton(text="📚 Qo'llanma"),
         KeyboardButton(text="💵 Reklama va Homiylik")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📤 Video Yuklash"),
         KeyboardButton(text="📨 Arizalar")],
        [KeyboardButton(text="📢 Broadcast"),
         KeyboardButton(text="🏠 Bosh menyu")],
    ], resize_keyboard=True)


# ══════════════════════════════════════════
#  HOLATLAR (FSM STATES)
# ══════════════════════════════════════════
class SearchState(StatesGroup):
    waiting_for_name = State()
    waiting_for_info = State()


class AdminState(StatesGroup):
    waiting_for_video       = State()
    waiting_for_video_title = State()
    waiting_for_broadcast   = State()
    waiting_for_comment     = State()   # ← tasdiqlash/rad izoh


class RequestState(StatesGroup):
    waiting_for_prompt = State()


# ══════════════════════════════════════════
#  BOT VA DISPATCHER
# ══════════════════════════════════════════
bot = Bot(token=API_TOKEN)
dp  = Dispatcher()


# ──────────────────────────────────────────
#  /start  |  Bosh menyu
# ──────────────────────────────────────────
@dp.message(Command("start"))
@dp.message(F.text == "🏠 Bosh menyu")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        await get_or_create_user(session, message.from_user)
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        f"Salom, *{message.from_user.full_name}!* 👋\n"
        f"🎌 Anime botga xush kelibsiz!",
        reply_markup=main_menu(is_admin),
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────
#  💎 VIP
# ──────────────────────────────────────────
@dp.message(F.text == "💎 VIP")
async def show_vip(message: types.Message):
    async with async_session() as session:
        user = await get_or_create_user(session, message.from_user)

    vip_status = "✅ Faol" if user.is_vip else "❌ Faol emas"
    text = (
        f"💎 *VIP OBUNA*\n"
        f"━━━━━━━━━━━━━━\n"
        f"Sizning holatingiz: {vip_status}\n"
        f"💰 Balansingiz: `{user.balance:.0f}` so'm\n\n"
        f"📋 *To'lov qilish uchun:*\n"
        f"💳 Karta raqami: `{CARD_NUMBER}`\n"
        f"👤 Karta egasi: D.X\n\n"
        f"To'lov qilgach, pastdagi tugmani bosib chek ma'lumotlarini yuboring."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 To'lov chekini yuborish", callback_data="fill_balance")
    ]])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data == "fill_balance")
async def fill_balance_cb(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📝 To'lov haqida ma'lumot yuboring:\n"
        "_(Masalan: 15 000 so'm o'tkazdim, chek raqami: 1234)_",
        parse_mode="Markdown",
    )
    await state.set_state(RequestState.waiting_for_prompt)
    await callback.answer()


@dp.message(RequestState.waiting_for_prompt)
async def process_prompt(message: types.Message, state: FSMContext):
    async with async_session() as session:
        req = Request(
            user_id=message.from_user.id,
            user_name=message.from_user.full_name,
            prompt=message.text,
        )
        session.add(req)
        await session.commit()
        req_id = req.id

    await message.answer(
        "✅ *Arizangiz muvaffaqiyatli yuborildi!*\n"
        "⏳ Admin ko'rib chiqqandan so'ng natija sizga yuboriladi.",
        parse_mode="Markdown",
    )

    # ── Adminga bildirishnoma + tugmalar ──
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔔 *Yangi ariza #{req_id}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"👤 Kimdan: *{message.from_user.full_name}*\n"
            f"🆔 ID: `{message.from_user.id}`\n"
            f"📝 Ma'lumot:\n_{message.text}_",
            reply_markup=request_action_kb(req_id),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Adminga xabar yuborishda xato: {e}")

    await state.clear()


# ──────────────────────────────────────────
#  ADMIN: Tasdiqlash tugmasi bosilganda
# ──────────────────────────────────────────
@dp.callback_query(F.data.startswith("approve_"))
async def approve_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return

    req_id = int(callback.data.split("_")[1])
    await state.update_data(req_id=req_id, action="approve")
    await callback.message.answer(
        f"✅ *Ariza #{req_id}* tasdiqlanmoqda.\n\n"
        f"💬 Foydalanuvchiga *izoh* yozing:\n"
        f"_(O'tkazib yuborish uchun «—» yozing)_",
        parse_mode="Markdown",
    )
    await state.set_state(AdminState.waiting_for_comment)
    await callback.answer()


# ──────────────────────────────────────────
#  ADMIN: Rad etish tugmasi bosilganda
# ──────────────────────────────────────────
@dp.callback_query(F.data.startswith("reject_"))
async def reject_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Siz admin emassiz!", show_alert=True)
        return

    req_id = int(callback.data.split("_")[1])
    await state.update_data(req_id=req_id, action="reject")
    await callback.message.answer(
        f"❌ *Ariza #{req_id}* rad etilmoqda.\n\n"
        f"💬 Rad etish *sababini* yozing:\n"
        f"_(O'tkazib yuborish uchun «—» yozing)_",
        parse_mode="Markdown",
    )
    await state.set_state(AdminState.waiting_for_comment)
    await callback.answer()


# ──────────────────────────────────────────
#  ADMIN: Izoh kiritilgandan keyin yakunlash
# ──────────────────────────────────────────
@dp.message(AdminState.waiting_for_comment)
async def process_admin_comment(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    data      = await state.get_data()
    req_id    = data.get("req_id")
    action    = data.get("action")
    raw_comment = message.text.strip()
    # "—" kiritilsa izoh bo'sh qoladi
    comment = "" if raw_comment == "—" else raw_comment

    async with async_session() as session:
        result = await session.execute(
            select(Request).where(Request.id == req_id)
        )
        req = result.scalars().first()

        if not req:
            await message.answer("⚠️ Ariza topilmadi yoki allaqachon ko'rib chiqilgan.")
            await state.clear()
            return

        if req.status != "pending":
            await message.answer("⚠️ Bu ariza allaqachon ko'rib chiqilgan.")
            await state.clear()
            return

        # ── TASDIQLASH ──
        if action == "approve":
            req.status = "approved"
            user_result = await session.execute(
                select(User).where(User.telegram_id == req.user_id)
            )
            db_user = user_result.scalars().first()
            if db_user:
                db_user.is_vip = True
            await session.commit()

            user_msg = (
                f"🎉 *Tabriklaymiz, {req.user_name}!*\n"
                f"✅ To'lovingiz tasdiqlandi va VIP obuna faollashtirildi!\n"
            )
            if comment:
                user_msg += f"\n💬 *Admin izohi:*\n_{comment}_"

            try:
                await bot.send_message(req.user_id, user_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Foydalanuvchiga (ID:{req.user_id}) xabar yuborishda xato: {e}")

            admin_confirm = (
                f"✅ *Ariza #{req_id} tasdiqlandi.*\n"
                f"👤 {req.user_name} (ID: `{req.user_id}`) — VIP berildi."
            )
            if comment:
                admin_confirm += f"\n💬 Sizning izohingiz: _{comment}_"

            await message.answer(admin_confirm, parse_mode="Markdown")

        # ── RAD ETISH ──
        elif action == "reject":
            req.status = "rejected"
            await session.commit()

            user_msg = (
                f"❌ *{req.user_name}, kechirasiz!*\n"
                f"To'lov arizangiz rad etildi.\n"
                f"Ma'lumotlarni tekshirib qayta yuboring.\n"
            )
            if comment:
                user_msg += f"\n💬 *Admin izohi:*\n_{comment}_"

            try:
                await bot.send_message(req.user_id, user_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Foydalanuvchiga (ID:{req.user_id}) xabar yuborishda xato: {e}")

            admin_confirm = (
                f"❌ *Ariza #{req_id} rad etildi.*\n"
                f"👤 {req.user_name} (ID: `{req.user_id}`)"
            )
            if comment:
                admin_confirm += f"\n💬 Sabab: _{comment}_"

            await message.answer(admin_confirm, parse_mode="Markdown")

    await state.clear()


# ──────────────────────────────────────────
#  ADMIN: Barcha kutilayotgan arizalar
# ──────────────────────────────────────────
@dp.message(F.text == "📨 Arizalar")
async def admin_requests(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session() as session:
        result = await session.execute(
            select(Request).where(Request.status == "pending")
        )
        reqs = result.scalars().all()

    if not reqs:
        await message.answer("📭 Hozircha yangi arizalar yo'q.")
        return

    await message.answer(f"📋 *{len(reqs)} ta kutilayotgan ariza:*", parse_mode="Markdown")
    for r in reqs:
        await message.answer(
            f"📋 *Ariza #{r.id}*\n"
            f"👤 User: *{r.user_name}*\n"
            f"🆔 ID: `{r.user_id}`\n"
            f"📝 Ma'lumot:\n_{r.prompt}_",
            reply_markup=request_action_kb(r.id),
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────
#  ADMIN: Broadcast
# ──────────────────────────────────────────
@dp.message(F.text == "📢 Broadcast")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:")
    await state.set_state(AdminState.waiting_for_broadcast)


@dp.message(AdminState.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    async with async_session() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = result.scalars().all()

    total   = len(user_ids)
    success = 0
    failed  = 0

    status_msg = await message.answer(f"🚀 Yuborilmoqda... (0/{total})")

    for i, uid in enumerate(user_ids, 1):
        try:
            await bot.send_message(uid, message.text)
            success += 1
        except Exception as e:
            logger.warning(f"Broadcast xato (ID:{uid}): {e}")
            failed += 1

        # Har 10 ta yoki oxirgisida progress yangilanadi
        if i % 10 == 0 or i == total:
            try:
                await status_msg.edit_text(f"🚀 Yuborilmoqda... ({i}/{total})")
            except Exception:
                pass

        await asyncio.sleep(0.05)   # Telegram rate-limit

    await status_msg.edit_text(
        f"✅ *Broadcast yakunlandi!*\n"
        f"📤 Muvaffaqiyatli: {success} ta\n"
        f"❌ Xato: {failed} ta",
        parse_mode="Markdown",
    )
    await state.clear()


# ──────────────────────────────────────────
#  🖥 Anime ma'lumot qidiruv (Jikan API)
# ──────────────────────────────────────────
@dp.message(F.text == "🖥 Anime malumot qidiruv")
async def info_search_start(message: types.Message, state: FSMContext):
    await message.answer("🎌 Anime nomini kiriting:")
    await state.set_state(SearchState.waiting_for_info)


@dp.message(SearchState.waiting_for_info)
async def process_info_search(message: types.Message, state: FSMContext):
    await state.clear()
    loading = await message.answer("🔍 Qidirilmoqda...")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"{JIKAN_API_URL}/anime",
                params={"q": message.text, "limit": 5},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    await loading.edit_text("⚠️ API bilan muammo. Keyinroq urinib ko'ring.")
                    return
                data   = await resp.json()
                animes = data.get("data", [])

        await loading.delete()

        if not animes:
            await message.answer("❌ Hech narsa topilmadi. Boshqa nom bilan urinib ko'ring.")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=a["title"][:40],
                callback_data=f"info_{a['mal_id']}"
            )] for a in animes
        ])
        await message.answer("🔎 Topilgan animelar. Keraklisini tanlang:", reply_markup=kb)

    except asyncio.TimeoutError:
        await loading.edit_text("⏱ So'rov vaqti tugadi. Qayta urinib ko'ring.")
    except Exception as e:
        logger.error(f"Anime qidirishda xato: {e}")
        await loading.edit_text("⚠️ Texnik muammo yuz berdi.")


@dp.callback_query(F.data.startswith("info_"))
async def show_anime_info(callback: types.CallbackQuery):
    anime_id = callback.data.split("_")[1]
    await callback.answer("⏳ Ma'lumot yuklanmoqda...")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"{JIKAN_API_URL}/anime/{anime_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    await callback.message.answer("⚠️ Ma'lumot olishda xato yuz berdi.")
                    return
                data  = await resp.json()
                anime = data["data"]

        genres   = ", ".join(j["name"] for j in anime.get("genres", [])) or "N/A"
        synopsis = anime.get("synopsis") or "Ma'lumot yo'q"
        if len(synopsis) > 500:
            synopsis = synopsis[:497] + "..."

        caption = (
            f"📺 *{anime['title']}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🎬 Janr: {genres}\n"
            f"⭐ Reyting: {anime.get('score', 'N/A')}\n"
            f"📅 Yil: {anime.get('year', 'N/A')}\n"
            f"🎞 Qismlar: {anime.get('episodes', 'N/A')}\n"
            f"📊 Status: {anime.get('status', 'N/A')}\n\n"
            f"📝 *Tavsif:*\n{synopsis}"
        )

        image_url = anime.get("images", {}).get("jpg", {}).get("large_image_url")
        if image_url:
            await callback.message.answer_photo(
                image_url, caption=caption, parse_mode="Markdown"
            )
        else:
            await callback.message.answer(caption, parse_mode="Markdown")

    except asyncio.TimeoutError:
        await callback.message.answer("⏱ So'rov vaqti tugadi. Qayta urinib ko'ring.")
    except Exception as e:
        logger.error(f"Anime ma'lumot olishda xato: {e}")
        await callback.message.answer("⚠️ Texnik muammo yuz berdi.")


# ──────────────────────────────────────────
#  🔍 Anime video izlash (bazadan)
# ──────────────────────────────────────────
@dp.message(F.text == "🔍 Anime izlash")
async def search_video_start(message: types.Message, state: FSMContext):
    await message.answer("🔍 Anime nomini kiriting:")
    await state.set_state(SearchState.waiting_for_name)


@dp.message(SearchState.waiting_for_name)
async def process_video_search(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        result = await session.execute(
            select(AnimeVideo).where(AnimeVideo.title.ilike(f"%{message.text}%"))
        )
        videos = result.scalars().all()

    if not videos:
        await message.answer(
            "❌ Kechirasiz, ushbu anime bazada topilmadi.\n"
            "💡 Boshqacha yozilgan bo'lishi mumkin, qayta urinib ko'ring."
        )
        return

    await message.answer(f"✅ *{len(videos)} ta natija topildi:*", parse_mode="Markdown")
    for v in videos:
        try:
            await message.answer_video(
                v.file_id,
                caption=f"🎬 *{v.title}*",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Video yuborishda xato (ID:{v.id}): {e}")
            await message.answer(f"⚠️ *'{v.title}'* videosini yuborishda xato.", parse_mode="Markdown")


# ──────────────────────────────────────────
#  ⚙️ Admin Panel
# ──────────────────────────────────────────
@dp.message(F.text == "⚙️ Admin Panel")
async def admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("⚙️ *Admin Panelga xush kelibsiz!*", reply_markup=admin_menu(), parse_mode="Markdown")


@dp.message(F.text == "📤 Video Yuklash")
async def upload_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("📹 Videoni yuboring:")
    await state.set_state(AdminState.waiting_for_video)


@dp.message(AdminState.waiting_for_video, F.video)
async def video_received(message: types.Message, state: FSMContext):
    await state.update_data(file_id=message.video.file_id)
    await message.answer("✏️ Endi anime nomini kiriting:")
    await state.set_state(AdminState.waiting_for_video_title)


@dp.message(AdminState.waiting_for_video)
async def video_wrong_type(message: types.Message):
    """Video emas, boshqa narsa yuborilsa."""
    await message.answer("⚠️ Iltimos, *video fayl* yuboring.", parse_mode="Markdown")


@dp.message(AdminState.waiting_for_video_title)
async def video_title_received(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    async with async_session() as session:
        video = AnimeVideo(title=message.text, file_id=data["file_id"])
        session.add(video)
        await session.commit()
    await message.answer(
        f"✅ *'{message.text}'* muvaffaqiyatli yuklandi!",
        parse_mode="Markdown",
    )
    await state.clear()


# ──────────────────────────────────────────
#  Statik sahifalar
# ──────────────────────────────────────────
@dp.message(F.text == "💵 Reklama va Homiylik")
async def ads(message: types.Message):
    await message.answer(
        "📢 *Reklama va Homiylik*\n"
        "━━━━━━━━━━━━━━\n"
        "Biz bilan hamkorlik qilish uchun adminlarga murojaat qiling:\n\n"
        "👤 @byliebert\n"
        "👤 @ovvry",
        parse_mode="Markdown",
    )


@dp.message(F.text == "📚 Qo'llanma")
async def guide(message: types.Message):
    await message.answer(
        "📚 *Qo'llanma*\n"
        "━━━━━━━━━━━━━━\n"
        "🔍 *Anime izlash* — bazadagi anime videolarini qidiring\n"
        "🖥 *Anime malumot qidiruv* — MyAnimeList'dan ma'lumot oling\n"
        "💎 *VIP* — premium obuna olish va holatingizni tekshiring\n\n"
        "❓ Savollar bo'lsa: @byliebert yoki @ovvry",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════
#  ISHGA TUSHIRISH
# ══════════════════════════════════════════
async def main():
    await init_db()
    logger.info("🤖 Bot ishga tushdi!")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
