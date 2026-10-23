"""Telegram bot — TO'LIQ TUGMALI interfeys (klaviatura tugmalari + guided oqimlar).

Hech kim buyruq yozmaydi — hamma narsa doimiy klaviatura tugmalari bilan.
  super_admin/admin — Super admin panel (web) + guruh/ustoz/talaba/starosta/rol tugmalari
  teacher           — Davomat boshlash (web) + hisobotlar
  student           — Davomat belgilash (web) + qo'llanma + admin bilan bog'lanish
Eski slash-buyruqlar ham ishlaydi (ixtiyoriy).
"""
from __future__ import annotations

import html

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import settings
from app.database import SessionLocal
from app import models as m
from app import services as svc
from app.security import hash_password

bot = Bot(token=settings.bot_token)
dp = Dispatcher(storage=MemoryStorage())

U = settings.public_url.rstrip("/")


# --------------------------------------------------------------------------- #
#  Tugma matnlari (konstanta)
# --------------------------------------------------------------------------- #
B_MARK = "✅ Davomat belgilash"
B_HELP = "📖 Qo'llanma"
B_CONTACT = "🆘 Asosiy admin"
B_START_ATT = "🎬 Davomat boshlash"
B_REPORTS = "📊 Hisobotlar"
B_PANEL = "🛡 Super admin panel"
B_NEW_GROUP = "➕ Guruh yaratish"
B_ASSIGN_T = "🎓 Ustoz biriktirish"
B_ADD_S = "➕ Talaba qo'shish"
B_NEW_STAROSTA = "📋 Starosta yaratish"
B_SET_ROLE = "👤 Rol berish"
B_SECURITY = "🛡 Xavfsizlik"
B_GROUPS = "📚 Guruhlar"
B_ATT = "🎬 Davomat"
B_CANCEL = "❌ Bekor qilish"


# --------------------------------------------------------------------------- #
#  Klaviaturalar (doimiy — is_persistent)
# --------------------------------------------------------------------------- #
def _wa(text: str, path: str) -> KeyboardButton:
    return KeyboardButton(text=text, web_app=WebAppInfo(url=f"{U}{path}"))


def student_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_wa(B_MARK, "/app/student")],
            [_wa(B_HELP, "/app/help"), KeyboardButton(text=B_CONTACT)],
        ],
        resize_keyboard=True, is_persistent=True,
    )


def teacher_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_wa(B_START_ATT, "/app/teacher")],
            [_wa(B_REPORTS, "/app/teacher#reports")],
            [_wa(B_HELP, "/app/help")],
        ],
        resize_keyboard=True, is_persistent=True,
    )


def admin_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [_wa(B_PANEL, "/app/admin")],
            [KeyboardButton(text=B_NEW_GROUP), KeyboardButton(text=B_ASSIGN_T)],
            [KeyboardButton(text=B_ADD_S), KeyboardButton(text=B_NEW_STAROSTA)],
            [KeyboardButton(text=B_SET_ROLE), KeyboardButton(text=B_SECURITY)],
            [_wa(B_ATT, "/app/teacher"), KeyboardButton(text=B_GROUPS)],
            [_wa(B_HELP, "/app/help")],
        ],
        resize_keyboard=True, is_persistent=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=B_CANCEL)]],
                               resize_keyboard=True, is_persistent=True)


def kb_for(user: m.User) -> ReplyKeyboardMarkup:
    if user.role in (m.Role.super_admin.value, m.Role.admin.value):
        return admin_kb()
    if user.role == m.Role.teacher.value:
        return teacher_kb()
    return student_kb()


ROLE_TITLE = {
    "super_admin": "👑 SUPER ADMIN", "admin": "🛡 Admin", "teacher": "🎓 Ustoz",
    "starosta": "📋 Starosta", "student": "🧑‍🎓 Talaba",
}


# --------------------------------------------------------------------------- #
#  FSM holatlari (tugmali oqimlar)
# --------------------------------------------------------------------------- #
class Flow(StatesGroup):
    group_name = State()
    teacher_tg = State()
    teacher_subj = State()
    student_tg = State()
    starosta_login = State()
    starosta_pass = State()
    role_tg = State()
    contact = State()
    join_name = State()   # havola orqali qo'shilayotgan talaba ism-familiyasi


# Bot username keshi (deep-link havolalari uchun)
_bot_username: str | None = None


async def get_username() -> str:
    global _bot_username
    if not _bot_username:
        me = await bot.get_me()
        _bot_username = me.username
    return _bot_username


async def join_link(group_id: int) -> str:
    uname = await get_username()
    return f"https://t.me/{uname}?start=g{group_id}"


# --------------------------------------------------------------------------- #
#  /start
# --------------------------------------------------------------------------- #
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deep(message: Message, command: CommandObject, state: FSMContext) -> None:
    """Havola orqali kirish: t.me/bot?start=g<guruh_id> — talaba ism-familiya bilan ro'yxatdan o'tadi."""
    args = (command.args or "").strip()
    if args.startswith("g") and args[1:].isdigit():
        gid = int(args[1:])
        async with SessionLocal() as db:
            g = await _group_by_id(db, gid)
        if not g:
            await message.answer("⛔️ Havola yaroqsiz yoki guruh topilmadi.")
            return
        await state.clear()
        await state.set_state(Flow.join_name)
        await state.update_data(join_group=gid)
        await message.answer(
            f"👋 Assalomu alaykum!\nSiz <b>{html.escape(g.name)}</b> guruhiga qo'shilyapsiz.\n\n"
            f"✍️ To'liq <b>Ism Familiyangizni</b> yozing (masalan: Zafar Mamatqulov):",
            parse_mode="HTML")
        return
    # Noma'lum payload — oddiy start
    await cmd_start(message, state)


async def _group_by_id(db, gid: int):
    from sqlalchemy import select as _sel
    return (await db.execute(_sel(m.Group).where(m.Group.id == gid, m.Group.is_active == True))).scalar_one_or_none()  # noqa: E712


@dp.message(Flow.join_name)
async def do_join_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 3 or name.startswith("/"):
        await message.answer("Iltimos, to'liq Ism Familiyangizni yozing:")
        return
    data = await state.get_data()
    await state.clear()
    gid = data.get("join_group")
    u = message.from_user
    async with SessionLocal() as db:
        user = await svc.get_or_create_user(db, u.id, full_name=name, username=u.username)
        # Ismni havoladagi kiritilganga yangilaymiz
        user.full_name = name
        await db.commit()
        status = await svc.add_student(db, gid, user.id, confirmed=False)
        g = await _group_by_id(db, gid)
        await svc.audit(db, u.id, "self_join", f"g={gid} name={name}")
    if status == "exists":
        await message.answer("✅ Siz allaqachon bu guruhdasiz.", reply_markup=student_kb())
        return
    if status == "pending_exists":
        await message.answer("⏳ So'rovingiz allaqachon yuborilgan — starosta tasdiqlashini kuting.",
                             reply_markup=student_kb())
        return
    await message.answer(
        f"✅ So'rovingiz yuborildi!\n<b>{html.escape(name)}</b> — <b>{html.escape(g.name)}</b> guruhiga.\n\n"
        f"⏳ Starosta tasdiqlagach, davomat belgilay olasiz. Pastdagi tugmalardan foydalaning.",
        parse_mode="HTML", reply_markup=student_kb())
    # Guruh starostalariga xabar
    await _notify_starostas(gid, f"🔔 Yangi talaba so'rovi: <b>{html.escape(name)}</b> (tasdiqlashni kutmoqda)")


async def _notify_starostas(group_id: int, text: str) -> None:
    """Guruh starostalariga (agar Telegram tg_id bo'lsa) — hozircha super adminga ham."""
    if settings.super_admin_id:
        await notify(settings.super_admin_id, text)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    async with SessionLocal() as db:
        user = await svc.get_or_create_user(db, u.id, full_name=u.full_name or "", username=u.username)
        await svc.audit(db, u.id, "start", f"role={user.role}")
    role = ROLE_TITLE.get(user.role, user.role)
    text = (
        f"<b>CYB3X DAVOMAT</b> 🔒\nRolingiz: {role}\n\n"
        f"Xavfsiz davomat — Face ID, aylanuvchi QR va anti-forward himoyasi bilan.\n\n"
        f"👇 Pastdagi <b>tugmalar</b> bilan ishlang."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb_for(user))


# --------------------------------------------------------------------------- #
#  Rol tekshiruvi
# --------------------------------------------------------------------------- #
async def _user(tg_id: int) -> m.User | None:
    async with SessionLocal() as db:
        return await svc.user_by_tg(db, tg_id)


async def _is_super(tg_id: int) -> bool:
    u = await _user(tg_id)
    return bool(u and u.role == m.Role.super_admin.value)


# --------------------------------------------------------------------------- #
#  Umumiy: Bekor qilish
# --------------------------------------------------------------------------- #
@dp.message(F.text == B_CANCEL)
async def btn_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = await _user(message.from_user.id)
    await message.answer("Bekor qilindi.", reply_markup=kb_for(u) if u else student_kb())


# --------------------------------------------------------------------------- #
#  TALABA — "Asosiy admin bilan bog'lanish" (tugma → yozish → forward)
# --------------------------------------------------------------------------- #
@dp.message(F.text == B_CONTACT)
async def btn_contact(message: Message, state: FSMContext) -> None:
    await state.set_state(Flow.contact)
    await message.answer("✍️ Savolingizni yozing — asosiy adminga yetkazaman:", reply_markup=cancel_kb())


@dp.message(Flow.contact)
async def do_contact(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    if settings.super_admin_id:
        try:
            await bot.send_message(
                settings.super_admin_id,
                f"🆘 <b>Yangi murojaat</b>\nKim: {html.escape(u.full_name or '')} "
                f"(@{u.username or '—'}, id=<code>{u.id}</code>)\n\n{html.escape(message.text or '')}",
                parse_mode="HTML")
        except Exception:
            pass
    usr = await _user(u.id)
    await message.answer("✅ Asosiy adminga yuborildi. Tez orada javob beradi.",
                         reply_markup=kb_for(usr) if usr else student_kb())


# --------------------------------------------------------------------------- #
#  SUPER ADMIN tugmalari
# --------------------------------------------------------------------------- #
async def _guard_super(message: Message) -> bool:
    if not await _is_super(message.from_user.id):
        await message.answer("⛔️ Bu amal faqat SUPER ADMIN uchun.")
        return False
    return True


async def _groups_inline(action: str) -> InlineKeyboardMarkup | None:
    async with SessionLocal() as db:
        groups = await svc.list_groups(db)
    if not groups:
        return None
    rows = [[InlineKeyboardButton(text=g.name, callback_data=f"pg:{action}:{g.id}")] for g in groups]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Guruh yaratish ----
@dp.message(F.text == B_NEW_GROUP)
async def btn_new_group(message: Message, state: FSMContext) -> None:
    if not await _guard_super(message):
        return
    await state.set_state(Flow.group_name)
    await message.answer("📝 Yangi guruh nomini yozing (masalan: 21-14):", reply_markup=cancel_kb())


@dp.message(Flow.group_name)
async def do_new_group(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = (message.text or "").strip()
    async with SessionLocal() as db:
        g = await svc.create_group(db, name, message.from_user.id)
        await svc.audit(db, message.from_user.id, "group_create", f"{g.id}:{name}")
    await message.answer(f"✅ Guruh yaratildi: <b>{html.escape(name)}</b> (id={g.id})",
                         parse_mode="HTML", reply_markup=admin_kb())


# ---- Ustoz biriktirish (guruh tanlash → tg_id → fan) ----
@dp.message(F.text == B_ASSIGN_T)
async def btn_assign_t(message: Message, state: FSMContext) -> None:
    if not await _guard_super(message):
        return
    kb = await _groups_inline("t")
    if not kb:
        await message.answer("Avval guruh yarating.", reply_markup=admin_kb())
        return
    await message.answer("🎓 Qaysi guruhga ustoz biriktiramiz?", reply_markup=kb)


# ---- Talaba qo'shish (guruh tanlash → tg_id) ----
@dp.message(F.text == B_ADD_S)
async def btn_add_s(message: Message, state: FSMContext) -> None:
    if not await _guard_super(message):
        return
    kb = await _groups_inline("s")
    if not kb:
        await message.answer("Avval guruh yarating.", reply_markup=admin_kb())
        return
    await message.answer("➕ Qaysi guruhga talaba qo'shamiz?", reply_markup=kb)


# ---- Starosta yaratish (guruh tanlash → login → parol) ----
@dp.message(F.text == B_NEW_STAROSTA)
async def btn_new_starosta(message: Message, state: FSMContext) -> None:
    if not await _guard_super(message):
        return
    kb = await _groups_inline("st")
    if not kb:
        await message.answer("Avval guruh yarating.", reply_markup=admin_kb())
        return
    await message.answer("📋 Starosta qaysi guruhга?", reply_markup=kb)


# ---- Rol berish (tg_id → rol tanlash) ----
@dp.message(F.text == B_SET_ROLE)
async def btn_set_role(message: Message, state: FSMContext) -> None:
    if not await _guard_super(message):
        return
    await state.set_state(Flow.role_tg)
    await message.answer("👤 Kimning rolini o'zgartiramiz? Telegram ID yozing:", reply_markup=cancel_kb())


@dp.message(Flow.role_tg)
async def do_role_tg(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("Raqamli Telegram ID yozing (masalan 123456789):")
        return
    await state.update_data(role_tg=int(txt))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧑‍🎓 Talaba", callback_data="rl:student"),
         InlineKeyboardButton(text="🎓 Ustoz", callback_data="rl:teacher")],
        [InlineKeyboardButton(text="🛡 Admin", callback_data="rl:admin"),
         InlineKeyboardButton(text="👑 Super admin", callback_data="rl:super_admin")],
    ])
    await message.answer("Qaysi rol?", reply_markup=kb)


# ---- Guruhlar ro'yxati ----
@dp.message(F.text == B_GROUPS)
async def btn_groups(message: Message) -> None:
    if not await _guard_super(message):
        return
    async with SessionLocal() as db:
        groups = await svc.list_groups(db)
        lines = []
        for g in groups:
            studs = await svc.group_students(db, g.id)
            lines.append(f"• id={g.id} — <b>{html.escape(g.name)}</b> ({len(studs)} talaba)")
    await message.answer("📚 Guruhlar:\n" + ("\n".join(lines) or "yo'q"),
                         parse_mode="HTML", reply_markup=admin_kb())


# ---- Xavfsizlik ----
@dp.message(F.text == B_SECURITY)
async def btn_security(message: Message) -> None:
    if not await _guard_super(message):
        return
    from sqlalchemy import select
    async with SessionLocal() as db:
        evs = list((await db.execute(
            select(m.SecurityEvent).order_by(m.SecurityEvent.created_at.desc()).limit(15))).scalars())
    if not evs:
        await message.answer("✅ Shubhali hodisa yo'q.", reply_markup=admin_kb())
        return
    lines = ["⚠️ <b>Oxirgi xavfsizlik hodisalari:</b>"]
    for e in evs:
        lines.append(f"• {e.created_at.strftime('%m-%d %H:%M')} — <b>{e.kind}</b> "
                     f"(uid={e.user_id}) {html.escape(e.detail or '')}")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=admin_kb())


# --------------------------------------------------------------------------- #
#  Inline callback'lar (guruh tanlash, rol tanlash)
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("pg:"))
async def cb_pick_group(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _is_super(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    _, action, gid = cb.data.split(":")
    await state.update_data(group_id=int(gid))
    await cb.message.edit_reply_markup(reply_markup=None)
    if action == "t":
        await state.set_state(Flow.teacher_tg)
        await cb.message.answer("🎓 Ustozning Telegram ID sini yozing:", reply_markup=cancel_kb())
    elif action == "s":
        await state.set_state(Flow.student_tg)
        await cb.message.answer("➕ Talabaning Telegram ID sini yozing:", reply_markup=cancel_kb())
    elif action == "st":
        await state.set_state(Flow.starosta_login)
        await cb.message.answer("📋 Starosta uchun <b>login</b> yozing:", parse_mode="HTML", reply_markup=cancel_kb())
    await cb.answer()


@dp.message(Flow.teacher_tg)
async def do_teacher_tg(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("Raqamli ID yozing:")
        return
    await state.update_data(teacher_tg=int(txt))
    await state.set_state(Flow.teacher_subj)
    await message.answer("📘 Fan nomini yozing (yoki '-' qo'ying):")


@dp.message(Flow.teacher_subj)
async def do_teacher_subj(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    subj = (message.text or "").strip()
    subj = None if subj in ("-", "") else subj
    async with SessionLocal() as db:
        t = await svc.get_or_create_user(db, data["teacher_tg"])
        await svc.set_role(db, t.tg_id, m.Role.teacher.value)
        await svc.assign_teacher(db, data["group_id"], t.id, subj)
        await svc.audit(db, message.from_user.id, "assign_teacher", f"g={data['group_id']} t={t.tg_id}")
    await message.answer("✅ Ustoz biriktirildi. Ustoz /start bossin — tugmalari chiqadi.",
                         reply_markup=admin_kb())


@dp.message(Flow.student_tg)
async def do_student_tg(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("Raqamli ID yozing:")
        return
    data = await state.get_data()
    await state.clear()
    async with SessionLocal() as db:
        st = await svc.get_or_create_user(db, int(txt))
        await svc.add_student(db, data["group_id"], st.id)
        await svc.audit(db, message.from_user.id, "add_student", f"g={data['group_id']} s={txt}")
    await message.answer("✅ Talaba qo'shildi.", reply_markup=admin_kb())


@dp.message(Flow.starosta_login)
async def do_starosta_login(message: Message, state: FSMContext) -> None:
    login = (message.text or "").strip()
    if not login:
        await message.answer("Login yozing:")
        return
    await state.update_data(starosta_login=login)
    await state.set_state(Flow.starosta_pass)
    await message.answer("🔑 Endi <b>parol</b> yozing:", parse_mode="HTML")


@dp.message(Flow.starosta_pass)
async def do_starosta_pass(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    pwd = (message.text or "").strip()
    login = data["starosta_login"]
    from sqlalchemy import select
    async with SessionLocal() as db:
        if (await db.execute(select(m.Starosta).where(m.Starosta.login == login))).scalar_one_or_none():
            await message.answer("⛔️ Bu login band. Boshqa tanlang.", reply_markup=admin_kb())
            return
        db.add(m.Starosta(login=login, password_hash=hash_password(pwd),
                          group_id=data["group_id"], created_by=message.from_user.id))
        await db.commit()
        await svc.audit(db, message.from_user.id, "starosta_create", f"g={data['group_id']} login={login}")
    await message.answer(
        f"✅ Starosta yaratildi.\nLogin: <code>{html.escape(login)}</code>\n"
        f"Kirish: {U}/app/starosta", parse_mode="HTML", reply_markup=admin_kb())


@dp.callback_query(F.data.startswith("rl:"))
async def cb_role(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _is_super(cb.from_user.id):
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    role = cb.data.split(":")[1]
    data = await state.get_data()
    await state.clear()
    tg = data.get("role_tg")
    if not tg:
        await cb.answer("Qaytadan boshlang", show_alert=True)
        return
    async with SessionLocal() as db:
        await svc.get_or_create_user(db, tg)
        await svc.set_role(db, tg, role)
        await svc.audit(db, cb.from_user.id, "set_role", f"{tg}->{role}")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"✅ {tg} roli: <b>{ROLE_TITLE.get(role, role)}</b>",
                            parse_mode="HTML", reply_markup=admin_kb())
    await cb.answer()


# --------------------------------------------------------------------------- #
#  Slash-buyruqlar (ixtiyoriy, tugmalardan tashqari)
# --------------------------------------------------------------------------- #
@dp.message(Command("guruh_yarat"))
async def cmd_create_group(message: Message) -> None:
    if not await _guard_super(message):
        return
    name = message.text.partition(" ")[2].strip()
    if not name:
        await message.answer("Foydalanish: /guruh_yarat 21-14  (yoki tugmadan foydalaning)")
        return
    async with SessionLocal() as db:
        g = await svc.create_group(db, name, message.from_user.id)
    await message.answer(f"✅ Guruh yaratildi (id={g.id})", reply_markup=admin_kb())


@dp.message(Command("kim"))
async def cmd_whois(message: Message) -> None:
    if not await _guard_super(message):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Foydalanish: /kim <tg_id>")
        return
    u = await _user(int(parts[1]))
    if not u:
        await message.answer("Topilmadi.")
        return
    await message.answer(
        f"👤 <b>{html.escape(u.full_name or '')}</b>\ntg_id: <code>{u.tg_id}</code>\n"
        f"rol: {u.role}\nFace ID: {'✅' if u.faceid_registered else '❌'}\n"
        f"Qurilma: {'bog`langan' if u.device_fp else 'yo`q'}\n"
        f"Bloklangan: {'ha' if u.is_blocked else 'yo`q'}", parse_mode="HTML")


# #admin orqali ham murojaat (tugmadan tashqari)
@dp.message(F.text.startswith("#admin"))
async def forward_to_admin(message: Message) -> None:
    q = message.text.partition(" ")[2].strip()
    if not q:
        await message.answer("Yozing: #admin <savolingiz>  (yoki '🆘 Asosiy admin' tugmasi)")
        return
    u = message.from_user
    if settings.super_admin_id:
        try:
            await bot.send_message(
                settings.super_admin_id,
                f"🆘 <b>Murojaat</b>\n{html.escape(u.full_name or '')} "
                f"(@{u.username or '—'}, <code>{u.id}</code>)\n\n{html.escape(q)}", parse_mode="HTML")
        except Exception:
            pass
    await message.answer("✅ Asosiy adminga yuborildi.")


# --------------------------------------------------------------------------- #
#  Boshqaruvchilarga bildirishnoma (API chaqiradi)
# --------------------------------------------------------------------------- #
async def notify(tg_id: int, text: str) -> None:
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Ishga tushirish
# --------------------------------------------------------------------------- #
async def run_bot() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)


async def setup_webhook() -> None:
    url = settings.public_url.rstrip("/") + settings.webhook_path
    await bot.set_webhook(url, drop_pending_updates=True)


async def feed_update(update: dict) -> None:
    from aiogram.types import Update
    await dp.feed_update(bot, Update.model_validate(update, context={"bot": bot}))
