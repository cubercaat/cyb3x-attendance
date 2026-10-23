"""Telegram bot — rollar, menyular, super admin buyruqlari.

Rollar:
  super_admin  — HAMMASI: guruh yaratish, ustoz biriktirish, rol berish, global hisobot,
                 xavfsizlik jurnali. Faqat super admin barcha guruhlarni ko'radi.
  admin        — qo'lda belgilash, yordam, cheklangan boshqaruv.
  teacher      — faqat o'ziga biriktirilgan guruh(lar). Ustozlar bir-biridan BEXABAR.
  starosta     — web login/parol orqali kiradi (alohida panel).
  student      — Face ID + QR/kod orqali davomat belgilaydi.
"""
from __future__ import annotations

import html

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.config import settings
from app.database import SessionLocal
from app import models as m
from app import services as svc

bot = Bot(token=settings.bot_token)
dp = Dispatcher()

U = settings.public_url.rstrip("/")


# --------------------------------------------------------------------------- #
#  Menyular
# --------------------------------------------------------------------------- #
def student_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Davomat belgilash", web_app=WebAppInfo(url=f"{U}/app/student"))],
        [InlineKeyboardButton(text="📖 Qo'llanma", web_app=WebAppInfo(url=f"{U}/app/help"))],
        [InlineKeyboardButton(text="🆘 Asosiy admin bilan bog'lanish", callback_data="contact_admin")],
    ])


def teacher_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Davomatni boshlash (QR)", web_app=WebAppInfo(url=f"{U}/app/teacher"))],
        [InlineKeyboardButton(text="📊 Hisobotlarim", web_app=WebAppInfo(url=f"{U}/app/teacher#reports"))],
        [InlineKeyboardButton(text="📖 Qo'llanma", web_app=WebAppInfo(url=f"{U}/app/help"))],
    ])


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 SUPER ADMIN panel", web_app=WebAppInfo(url=f"{U}/app/admin"))],
        [InlineKeyboardButton(text="🎬 Davomat (QR)", web_app=WebAppInfo(url=f"{U}/app/teacher"))],
        [InlineKeyboardButton(text="📖 Qo'llanma", web_app=WebAppInfo(url=f"{U}/app/help"))],
    ])


def menu_for(user: m.User) -> InlineKeyboardMarkup:
    if user.role in (m.Role.super_admin.value, m.Role.admin.value):
        return admin_menu()
    if user.role == m.Role.teacher.value:
        return teacher_menu()
    return student_menu()


ROLE_TITLE = {
    "super_admin": "👑 SUPER ADMIN",
    "admin": "🛡 Admin",
    "teacher": "🎓 Ustoz",
    "starosta": "📋 Starosta",
    "student": "🧑‍🎓 Talaba",
}


# --------------------------------------------------------------------------- #
#  /start
# --------------------------------------------------------------------------- #
@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = message.from_user
    async with SessionLocal() as db:
        user = await svc.get_or_create_user(
            db, u.id, full_name=u.full_name or "", username=u.username
        )
        await svc.audit(db, u.id, "start", f"role={user.role}")
    role = ROLE_TITLE.get(user.role, user.role)
    text = (
        f"<b>CYB3X DAVOMAT</b> 🔒\n"
        f"Rolingiz: {role}\n\n"
        f"Xavfsiz davomat tizimi — Face ID, aylanuvchi QR va anti-forward himoyasi bilan.\n"
    )
    if user.role == m.Role.super_admin.value:
        text += (
            "\n<b>Super admin buyruqlari:</b>\n"
            "/guruh_yarat <i>nom</i>\n"
            "/guruhlar\n"
            "/ustoz_biriktir <i>guruh_id ustoz_tg_id [fan]</i>\n"
            "/talaba_qosh <i>guruh_id talaba_tg_id</i>\n"
            "/rol <i>tg_id super_admin|admin|teacher|student</i>\n"
            "/starosta_yarat <i>guruh_id login parol</i>\n"
            "/xavfsizlik — shubhali hodisalar\n"
            "/kim <i>tg_id</i> — foydalanuvchi haqida\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=menu_for(user))


# --------------------------------------------------------------------------- #
#  Super admin huquqi tekshiruvi
# --------------------------------------------------------------------------- #
async def _require_super(message: Message) -> bool:
    async with SessionLocal() as db:
        user = await svc.user_by_tg(db, message.from_user.id)
    if not user or user.role != m.Role.super_admin.value:
        await message.answer("⛔️ Bu buyruq faqat SUPER ADMIN uchun.")
        return False
    return True


@dp.message(Command("guruh_yarat"))
async def cmd_create_group(message: Message) -> None:
    if not await _require_super(message):
        return
    name = message.text.partition(" ")[2].strip()
    if not name:
        await message.answer("Foydalanish: /guruh_yarat 21-14 guruh")
        return
    async with SessionLocal() as db:
        g = await svc.create_group(db, name, message.from_user.id)
        await svc.audit(db, message.from_user.id, "group_create", f"{g.id}:{name}")
    await message.answer(f"✅ Guruh yaratildi: <b>{html.escape(name)}</b> (id={g.id})", parse_mode="HTML")


@dp.message(Command("guruhlar"))
async def cmd_groups(message: Message) -> None:
    if not await _require_super(message):
        return
    async with SessionLocal() as db:
        groups = await svc.list_groups(db)
        lines = []
        for g in groups:
            studs = await svc.group_students(db, g.id)
            lines.append(f"• id={g.id} — <b>{html.escape(g.name)}</b> ({len(studs)} talaba)")
    await message.answer("📚 Guruhlar:\n" + ("\n".join(lines) or "yo'q"), parse_mode="HTML")


@dp.message(Command("ustoz_biriktir"))
async def cmd_assign_teacher(message: Message) -> None:
    if not await _require_super(message):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Foydalanish: /ustoz_biriktir <guruh_id> <ustoz_tg_id> [fan]")
        return
    try:
        gid, tg = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("guruh_id va tg_id son bo'lishi kerak.")
        return
    subject = " ".join(parts[3:]) or None
    async with SessionLocal() as db:
        teacher = await svc.get_or_create_user(db, tg)
        await svc.set_role(db, tg, m.Role.teacher.value)
        await svc.assign_teacher(db, gid, teacher.id, subject)
        await svc.audit(db, message.from_user.id, "assign_teacher", f"g={gid} t={tg} {subject}")
    await message.answer(f"✅ Ustoz biriktirildi (guruh {gid}). Ustoz /start bossin.")


@dp.message(Command("talaba_qosh"))
async def cmd_add_student(message: Message) -> None:
    if not await _require_super(message):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Foydalanish: /talaba_qosh <guruh_id> <talaba_tg_id>")
        return
    try:
        gid, tg = int(parts[1]), int(parts[2])
    except ValueError:
        await message.answer("Raqamlar noto'g'ri.")
        return
    async with SessionLocal() as db:
        st = await svc.get_or_create_user(db, tg)
        await svc.add_student(db, gid, st.id)
        await svc.audit(db, message.from_user.id, "add_student", f"g={gid} s={tg}")
    await message.answer(f"✅ Talaba qo'shildi (guruh {gid}).")


@dp.message(Command("rol"))
async def cmd_role(message: Message) -> None:
    if not await _require_super(message):
        return
    parts = message.text.split()
    if len(parts) != 3 or parts[2] not in {r.value for r in m.Role}:
        await message.answer("Foydalanish: /rol <tg_id> <super_admin|admin|teacher|starosta|student>")
        return
    tg = int(parts[1])
    async with SessionLocal() as db:
        await svc.get_or_create_user(db, tg)
        await svc.set_role(db, tg, parts[2])
        await svc.audit(db, message.from_user.id, "set_role", f"{tg}->{parts[2]}")
    await message.answer(f"✅ {tg} roli: {parts[2]}")


@dp.message(Command("starosta_yarat"))
async def cmd_create_starosta(message: Message) -> None:
    if not await _require_super(message):
        return
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Foydalanish: /starosta_yarat <guruh_id> <login> <parol>")
        return
    from app.security import hash_password
    gid, login, pwd = int(parts[1]), parts[2], parts[3]
    async with SessionLocal() as db:
        from sqlalchemy import select
        exists = (await db.execute(select(m.Starosta).where(m.Starosta.login == login))).scalar_one_or_none()
        if exists:
            await message.answer("⛔️ Bu login band.")
            return
        db.add(m.Starosta(login=login, password_hash=hash_password(pwd), group_id=gid, created_by=message.from_user.id))
        await db.commit()
        await svc.audit(db, message.from_user.id, "starosta_create", f"g={gid} login={login}")
    await message.answer(
        f"✅ Starosta yaratildi.\nLogin: <code>{html.escape(login)}</code>\n"
        f"Kirish: {U}/app/starosta", parse_mode="HTML")


@dp.message(Command("xavfsizlik"))
async def cmd_security(message: Message) -> None:
    if not await _require_super(message):
        return
    from sqlalchemy import select
    async with SessionLocal() as db:
        evs = list((await db.execute(
            select(m.SecurityEvent).order_by(m.SecurityEvent.created_at.desc()).limit(15)
        )).scalars())
    if not evs:
        await message.answer("✅ Shubhali hodisa yo'q.")
        return
    lines = [f"⚠️ <b>Oxirgi xavfsizlik hodisalari:</b>"]
    for e in evs:
        lines.append(f"• {e.created_at.strftime('%m-%d %H:%M')} — <b>{e.kind}</b> (uid={e.user_id}) {html.escape(e.detail or '')}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("kim"))
async def cmd_whois(message: Message) -> None:
    if not await _require_super(message):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Foydalanish: /kim <tg_id>")
        return
    async with SessionLocal() as db:
        u = await svc.user_by_tg(db, int(parts[1]))
    if not u:
        await message.answer("Topilmadi.")
        return
    await message.answer(
        f"👤 <b>{html.escape(u.full_name or '')}</b>\n"
        f"tg_id: <code>{u.tg_id}</code>\nrol: {u.role}\n"
        f"Face ID: {'✅' if u.faceid_registered else '❌'}\n"
        f"Qurilma: {'bog`langan' if u.device_fp else 'yo`q'}\n"
        f"Bloklangan: {'ha' if u.is_blocked else 'yo`q'}",
        parse_mode="HTML")


# --------------------------------------------------------------------------- #
#  "Asosiy admin bilan bog'lanish" — super adminga yo'naltirish
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "contact_admin")
async def contact_admin(cb) -> None:
    await cb.message.answer(
        "✍️ Savolingizni yozing — men uni asosiy adminga yetkazaman.\n"
        "Xabaringiz oldiga <code>#admin</code> yozing.\nMisol: <code>#admin Face ID ishlamayapti</code>",
        parse_mode="HTML")
    await cb.answer()


@dp.message(F.text.startswith("#admin"))
async def forward_to_admin(message: Message) -> None:
    q = message.text.partition(" ")[2].strip()
    if not q:
        await message.answer("Xabar matnini yozing: #admin <savolingiz>")
        return
    u = message.from_user
    if settings.super_admin_id:
        try:
            await bot.send_message(
                settings.super_admin_id,
                f"🆘 <b>Yangi murojaat</b>\nKim: {html.escape(u.full_name or '')} "
                f"(@{u.username or '—'}, id=<code>{u.id}</code>)\n\n{html.escape(q)}",
                parse_mode="HTML")
        except Exception:
            pass
    await message.answer("✅ Xabaringiz asosiy adminga yuborildi. Tez orada javob beradi.")


# --------------------------------------------------------------------------- #
#  Boshqaruvchilar uchun bildirishnoma yuborish (API chaqiradi)
# --------------------------------------------------------------------------- #
async def notify(tg_id: int, text: str) -> None:
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except Exception:
        pass


async def run_bot() -> None:
    """VPS / lokal — polling rejimi."""
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, handle_signals=False)


async def setup_webhook() -> None:
    """Shared hosting — webhook rejimi. Telegramga PUBLIC_URL/tg/<secret> ni o'rnatadi."""
    url = settings.public_url.rstrip("/") + settings.webhook_path
    await bot.set_webhook(url, drop_pending_updates=True)


async def feed_update(update: dict) -> None:
    """Webhook kelgan update ni aiogram ga uzatish (api.py chaqiradi)."""
    from aiogram.types import Update
    await dp.feed_update(bot, Update.model_validate(update, context={"bot": bot}))
