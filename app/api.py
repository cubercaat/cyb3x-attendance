"""FastAPI — mini app backend. Barcha himoya qatlamlari shu yerda birlashadi."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, select

from app import models as m
from app import services as svc
from app import store
from app import webauthn_utils as wa
from app.config import settings
from app.database import SessionLocal, init_db
from app.miniapp_auth import validate_init_data
from app.reports import build_xlsx
from app.security import (
    current_counter,
    device_fingerprint,
    hash_password,
    make_code,
    make_token,
    parse_and_verify_token,
    verify_code,
    verify_password,
)

app = FastAPI(title="CYB3X Davomat")
WEB = Path(__file__).resolve().parent.parent / "web"
signer = URLSafeTimedSerializer(settings.secret_key, salt="cyb3x")

from fastapi.staticfiles import StaticFiles  # noqa: E402

if (WEB / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


# --------------------------------------------------------------------------- #
#  Yordamchilar
# --------------------------------------------------------------------------- #
def client_ip(req: Request) -> str:
    return (req.headers.get("x-forwarded-for", "") or (req.client.host if req.client else "")).split(",")[0].strip()


async def auth_user(x_init_data: str | None, db) -> m.User:
    """initData → ishonchli foydalanuvchi. Yaroqsiz bo'lsa 401."""
    data = validate_init_data(x_init_data or "")
    if not data:
        raise HTTPException(401, "Telegram tekshiruvi muvaffaqiyatsiz")
    user = await svc.get_or_create_user(
        db, int(data["id"]),
        full_name=f"{data.get('first_name','')} {data.get('last_name','')}".strip(),
        username=data.get("username"),
    )
    if user.is_blocked:
        raise HTTPException(403, "Hisobingiz bloklangan. Asosiy admin bilan bog'laning.")
    return user


async def user_credentials(db, user_id: int) -> list[m.Credential]:
    """Face ID ishonchnomalarini aniq yuklash (async lazy-load muammosini oldini oladi)."""
    return list((await db.execute(select(m.Credential).where(m.Credential.user_id == user_id))).scalars())


def ok(**kw):
    return JSONResponse({"ok": True, **kw})


def err(msg: str, code: int = 400):
    return JSONResponse({"ok": False, "error": msg}, status_code=code)


# --------------------------------------------------------------------------- #
#  Startup
# --------------------------------------------------------------------------- #
@app.on_event("startup")
async def _startup():
    await init_db()
    os.makedirs("reports_out", exist_ok=True)


# --------------------------------------------------------------------------- #
#  Sahifalar (mini app)
# --------------------------------------------------------------------------- #
def _page(name: str) -> HTMLResponse:
    f = WEB / name
    if not f.exists():
        raise HTTPException(404)
    return HTMLResponse(f.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
async def root():
    return _page("landing.html")


@app.get("/app/student", response_class=HTMLResponse)
async def page_student():
    return _page("student.html")


@app.get("/app/teacher", response_class=HTMLResponse)
async def page_teacher():
    return _page("teacher.html")


@app.get("/app/admin", response_class=HTMLResponse)
async def page_admin():
    return _page("admin.html")


@app.get("/app/starosta", response_class=HTMLResponse)
async def page_starosta():
    return _page("starosta.html")


@app.get("/app/help", response_class=HTMLResponse)
async def page_help():
    return _page("help.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ts": dt.datetime.utcnow().isoformat()}


# Telegram webhook (shared hosting rejimi) — maxfiy yo'l orqali
@app.post(settings.webhook_path)
async def telegram_webhook(req: Request):
    if not settings.bot_token or settings.bot_token.startswith("TEST"):
        return err("bot off", 503)
    try:
        update = await req.json()
        from app.bot import feed_update
        await feed_update(update)
    except Exception as e:  # Telegram qayta yubormasligi uchun 200 qaytaramiz
        import logging
        logging.getLogger("cyb3x").warning("webhook error: %s", e)
    return {"ok": True}


# --------------------------------------------------------------------------- #
#  Umumiy: men kimman?
# --------------------------------------------------------------------------- #
@app.post("/api/me")
async def api_me(x_init_data: str = Header(None, alias="X-Init-Data")):
    async with SessionLocal() as db:
        u = await auth_user(x_init_data, db)
        return ok(user={
            "id": u.id, "tg_id": u.tg_id, "name": u.full_name, "role": u.role,
            "faceid": u.faceid_registered, "device_bound": bool(u.device_fp),
        })


# =========================================================================== #
#  TALABA — Face ID ro'yxatdan o'tish
# =========================================================================== #
@app.post("/api/student/register/options")
async def reg_options(x_init_data: str = Header(None, alias="X-Init-Data")):
    async with SessionLocal() as db:
        u = await auth_user(x_init_data, db)
    opts_json = wa.registration_options(u.id, u.full_name or f"user{u.tg_id}")
    challenge = json.loads(opts_json)["challenge"]
    store.put(f"reg:{u.id}", challenge.encode(), ttl=300)
    return Response(opts_json, media_type="application/json")


@app.post("/api/student/register/verify")
async def reg_verify(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        u = await auth_user(x_init_data, db)
        ch = store.pop(f"reg:{u.id}")
        if not ch:
            return err("Challenge eskirdi, qaytadan urinib ko'ring")
        from webauthn.helpers import base64url_to_bytes
        try:
            v = wa.verify_registration(json.dumps(body["credential"]), base64url_to_bytes(ch.decode()))
        except Exception as e:
            await svc.security_event(db, u.tg_id, "faceid_register_fail", str(e)[:200], client_ip(req))
            return err("Face ID ro'yxatdan o'tmadi: " + str(e)[:120])

        # Qurilmaga bog'lash
        device_raw = body.get("device", "")
        fp = device_fingerprint(device_raw) if device_raw else None

        db.add(m.Credential(
            user_id=u.id,
            credential_id=v.credential_id,
            public_key=v.credential_public_key,
            sign_count=v.sign_count,
            device_label=body.get("label", "Qurilma"),
        ))
        u.faceid_registered = True
        if fp:
            u.device_fp = fp
        await db.commit()
        await svc.audit(db, u.tg_id, "faceid_register", f"device={fp}", client_ip(req))
    return ok(message="Face ID muvaffaqiyatli o'rnatildi")


# =========================================================================== #
#  TALABA — davomat belgilash (QR/kod + Face ID + qurilma + replay)
# =========================================================================== #
async def _resolve_session(db, u: m.User, token: str | None, code: str | None):
    """Token yoki kod bo'yicha faol sessiyani va counter ni aniqlaydi.
    Natija: (session, counter, reason). session=None bo'lsa reason — xato.
    """
    if token:
        try:
            sid = int(token.split(".")[0])
        except Exception:
            return None, -1, "bad_token"
        s = await svc.get_session(db, sid)
        if not s or s.status != m.SessionStatus.active.value:
            return None, -1, "no_session"
        good, counter, reason = parse_and_verify_token(s.session_secret, sid, token)
        return (s if good else None), counter, reason
    if code:
        # Kod sid tashimaydi — talabaning guruhidagi faol sessiyani topamiz
        gm = (await db.execute(select(m.GroupMember).where(m.GroupMember.user_id == u.id))).scalars().all()
        for g in gm:
            s = await svc.active_session_for_group(db, g.group_id)
            if s:
                good, counter, reason = verify_code(s.session_secret, s.id, code)
                if good:
                    return s, counter, "ok"
        return None, -1, "stale_or_wrong_code"
    return None, -1, "no_input"


@app.post("/api/student/prepare")
async def student_prepare(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    """1-qadam: QR/kod ni tekshiradi, Face ID so'rovi (challenge) qaytaradi."""
    body = await req.json()
    ip = client_ip(req)
    async with SessionLocal() as db:
        u = await auth_user(x_init_data, db)
        if not u.faceid_registered:
            return err("Avval Face ID o'rnating", 428)

        s, counter, reason = await _resolve_session(db, u, body.get("token"), body.get("code"))
        if not s:
            if reason == "stale_token":
                await svc.security_event(db, u.tg_id, "stale_token", "eski QR (forward?)", ip)
                return err("QR eskirdi — doskadagi YANGI QR ni skanerlang", 409)
            return err("Sessiya topilmadi yoki kod/QR noto'g'ri", 404)

        # Faqat o'z guruhining talabasi
        in_group = (await db.execute(select(m.GroupMember).where(
            m.GroupMember.group_id == s.group_id, m.GroupMember.user_id == u.id))).scalar_one_or_none()
        if not in_group:
            await svc.security_event(db, u.tg_id, "wrong_group", f"sid={s.id}", ip)
            return err("Siz bu guruh talabasi emassiz", 403)

        if await svc.already_marked(db, s.id, u.id):
            return err("Siz allaqachon belgilangansiz ✔", 409)
        if await svc.token_reused(db, s.id, counter, u.id):
            await svc.security_event(db, u.tg_id, "replay", f"sid={s.id} c={counter}", ip)
            return err("Bu QR allaqachon ishlatilgan", 409)

        # Face ID so'rovi
        creds = await user_credentials(db, u.id)
        cred_ids = [c.credential_id for c in creds]
        if not cred_ids:
            return err("Face ID topilmadi, qayta o'rnating", 428)
        opts_json = wa.authentication_options(cred_ids)
        challenge = json.loads(opts_json)["challenge"]
        store.put(f"auth:{u.id}", challenge.encode(), ttl=120)
        return Response(json.dumps({"ok": True, "session_id": s.id, "options": json.loads(opts_json)}),
                        media_type="application/json")


@app.post("/api/student/mark")
async def student_mark(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    """2-qadam: Face ID javobini + QR/kodni yakuniy tekshirib, davomatni yozadi."""
    body = await req.json()
    ip = client_ip(req)
    async with SessionLocal() as db:
        u = await auth_user(x_init_data, db)

        # Qurilmani tekshirish (bitta akkaunt = bitta qurilma)
        device_raw = body.get("device", "")
        fp = device_fingerprint(device_raw) if device_raw else None
        if u.device_fp and fp and fp != u.device_fp:
            await svc.security_event(db, u.tg_id, "wrong_device", "boshqa qurilma (akkaunt uzatish?)", ip)
            return err("⛔️ Bu akkaunt boshqa qurilmaga bog'langan. Akkauntni boshqaga berib bo'lmaydi.", 403)

        # QR/kod yana tekshiriladi (yangi oyna)
        s, counter, reason = await _resolve_session(db, u, body.get("token"), body.get("code"))
        if not s:
            if reason == "stale_token":
                await svc.security_event(db, u.tg_id, "stale_token", "mark bosqichida eski QR", ip)
            return err("QR/kod eskirdi — yangisini oling", 409)

        if await svc.already_marked(db, s.id, u.id):
            return err("Allaqachon belgilangansiz ✔", 409)
        if await svc.token_reused(db, s.id, counter, u.id):
            await svc.security_event(db, u.tg_id, "replay", f"sid={s.id} c={counter}", ip)
            return err("Bu QR allaqachon ishlatilgan", 409)

        # Face ID tasdiqlash
        ch = store.pop(f"auth:{u.id}")
        if not ch:
            return err("Face ID so'rovi eskirdi, qaytadan boshlang", 428)
        creds = await user_credentials(db, u.id)
        cred = creds[0] if creds else None
        if not cred:
            return err("Face ID topilmadi", 428)
        from webauthn.helpers import base64url_to_bytes
        try:
            res = wa.verify_authentication(
                json.dumps(body["assertion"]),
                base64url_to_bytes(ch.decode()),
                cred.public_key, cred.sign_count,
            )
        except Exception as e:
            await svc.security_event(db, u.tg_id, "faceid_fail", str(e)[:150], ip)
            return err("Face ID tasdiqlanmadi", 401)
        cred.sign_count = res.new_sign_count
        cred.last_used = m.now()

        # Kech / keldi (SQLite naive, Postgres aware — ikkalasiga bardoshli)
        opened = s.opened_at if s.opened_at.tzinfo else s.opened_at.replace(tzinfo=dt.timezone.utc)
        mins = (dt.datetime.now(dt.timezone.utc) - opened).total_seconds() / 60
        status = m.AttStatus.late.value if mins > s.late_after_min else m.AttStatus.present.value
        method = m.Method.code.value if body.get("code") else m.Method.qr.value

        if fp and not u.device_fp:
            u.device_fp = fp  # birinchi marta bog'lanadi

        await svc.mark_attendance(
            db, s.id, u.id, status=status, method=method,
            counter=counter, device_fp=fp,
            flags={"ip": ip, "mins": round(mins, 1)},
        )
        await svc.audit(db, u.tg_id, "mark", f"sid={s.id} {status}", ip)

    # Ustozga bildirishnoma (ixtiyoriy)
    try:
        from app.bot import notify
        await notify(s.opened_by, f"✅ {u.full_name} belgilandi ({'kech' if status=='late' else 'keldi'})")
    except Exception:
        pass
    return ok(status=status, message=("⏰ Kech belgilandingiz" if status == "late" else "✅ Davomat belgilandi"))


# =========================================================================== #
#  USTOZ / ADMIN — sessiya va QR
# =========================================================================== #
async def _staff(db, x_init_data):
    u = await auth_user(x_init_data, db)
    if not svc.is_staff(u):
        raise HTTPException(403, "Ruxsat yo'q")
    return u


@app.post("/api/teacher/groups")
async def teacher_groups(x_init_data: str = Header(None, alias="X-Init-Data")):
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        if u.role == m.Role.super_admin.value:
            groups = await svc.list_groups(db)
        else:
            groups = await svc.groups_for_teacher(db, u.id)  # ustoz faqat o'zinikini ko'radi
        out = [{"id": g.id, "name": g.name} for g in groups]
        return ok(groups=out)


@app.post("/api/teacher/open")
async def teacher_open(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        gid = int(body["group_id"])
        para = int(body.get("para", 1))
        # Ustoz faqat o'z guruhini ocha oladi
        if u.role == m.Role.teacher.value:
            mine = {g.id for g in await svc.groups_for_teacher(db, u.id)}
            if gid not in mine:
                return err("Bu guruh sizga biriktirilmagan", 403)
        s = await svc.open_session(db, gid, u.tg_id, para, body.get("subject"))
        await svc.audit(db, u.tg_id, "session_open", f"sid={s.id} g={gid} para={para}")
        return ok(session_id=s.id, para=s.para)


@app.post("/api/teacher/token")
async def teacher_token(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    """Doskadagi QR — har chaqiruvda joriy oyna tokeni (har TTL soniyada o'zgaradi)."""
    body = await req.json()
    async with SessionLocal() as db:
        await _staff(db, x_init_data)
        s = await svc.get_session(db, int(body["session_id"]))
        if not s:
            return err("Sessiya yo'q", 404)
        counter = current_counter()
        tok = make_token(s.session_secret, s.id, counter)
        code = make_code(s.session_secret, s.id, counter)
        import time
        remaining = settings.token_ttl_seconds - int(time.time()) % settings.token_ttl_seconds
        return ok(token=tok, code=code, ttl=settings.token_ttl_seconds, remaining=remaining, status=s.status)


@app.post("/api/teacher/live")
async def teacher_live(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        await _staff(db, x_init_data)
        s = await svc.get_session(db, int(body["session_id"]))
        if not s:
            return err("Sessiya yo'q", 404)
        g = (await db.execute(select(m.Group).where(m.Group.id == s.group_id))).scalar_one()
        summ = await svc.session_summary(db, s.id)
        return ok(group=g.name, para=s.para, status=s.status,
                  present=summ["present"], late=summ["late"], absent=summ["absent"],
                  total=summ["total"], rows=summ["rows"])


@app.post("/api/teacher/manual")
async def teacher_manual(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    """Ustoz/admin qo'lda belgilaydi (Face ID talab qilinmaydi — xodim mas'ul)."""
    body = await req.json()
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        s = await svc.get_session(db, int(body["session_id"]))
        if not s:
            return err("Sessiya yo'q", 404)
        student = (await db.execute(select(m.User).where(m.User.id == int(body["student_id"])))).scalar_one_or_none()
        if not student:
            return err("Talaba yo'q", 404)
        status = body.get("status", m.AttStatus.present.value)
        if await svc.already_marked(db, s.id, student.id):
            # yangilash
            att = (await db.execute(select(m.Attendance).where(
                m.Attendance.session_id == s.id, m.Attendance.student_id == student.id))).scalar_one()
            att.status = status
            att.method = m.Method.manual.value
            att.marked_by = u.tg_id
            await db.commit()
        else:
            await svc.mark_attendance(db, s.id, student.id, status=status,
                                      method=m.Method.manual.value, marked_by=u.tg_id)
        await svc.audit(db, u.tg_id, "manual_mark", f"sid={s.id} s={student.id} {status}")
        return ok()


@app.post("/api/teacher/close")
async def teacher_close(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        st = body.get("status", m.SessionStatus.closed.value)
        await svc.set_session_status(db, int(body["session_id"]), st)
        await svc.audit(db, u.tg_id, "session_" + st, f"sid={body['session_id']}")
        return ok()


@app.post("/api/teacher/students")
async def teacher_students(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        await _staff(db, x_init_data)
        s = await svc.get_session(db, int(body["session_id"]))
        studs = await svc.group_students(db, s.group_id)
        return ok(students=[{"id": x.id, "name": x.full_name or (x.username or str(x.tg_id))} for x in studs])


@app.post("/api/teacher/sessions")
async def teacher_sessions(x_init_data: str = Header(None, alias="X-Init-Data")):
    """Ustozning oxirgi sessiyalari (hisobotlar uchun)."""
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        if u.role == m.Role.super_admin.value:
            gids = [g.id for g in await svc.list_groups(db)]
        else:
            gids = [g.id for g in await svc.groups_for_teacher(db, u.id)]
        if not gids:
            return ok(sessions=[])
        rows = list((await db.execute(
            select(m.AttSession, m.Group.name)
            .join(m.Group, m.Group.id == m.AttSession.group_id)
            .where(m.AttSession.group_id.in_(gids))
            .order_by(m.AttSession.opened_at.desc()).limit(30)
        )).all())
        out = [{"id": s.id, "group": gname, "para": s.para, "status": s.status,
                "when": s.opened_at.strftime("%m-%d %H:%M")} for s, gname in rows]
        return ok(sessions=out)


@app.post("/api/teacher/report/build")
async def report_build(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    body = await req.json()
    async with SessionLocal() as db:
        u = await _staff(db, x_init_data)
        sid = int(body["session_id"])
        token = signer.dumps({"sid": sid, "by": u.tg_id})
    return ok(url=f"/dl/{token}")


@app.get("/dl/{token}")
async def report_download(token: str):
    try:
        data = signer.loads(token, max_age=3600)
    except BadSignature:
        raise HTTPException(403, "Yaroqsiz havola")
    sid = int(data["sid"])
    async with SessionLocal() as db:
        s = await svc.get_session(db, sid)
        if not s:
            raise HTTPException(404)
        g = (await db.execute(select(m.Group).where(m.Group.id == s.group_id))).scalar_one()
        summ = await svc.session_summary(db, sid)
    content = build_xlsx(summ, g.name)
    fn = f"davomat_{g.name}_{s.para}para_{s.opened_at.strftime('%Y%m%d')}.xlsx".replace(" ", "_")
    return Response(content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


# =========================================================================== #
#  SUPER ADMIN panel
# =========================================================================== #
async def _super(db, x_init_data):
    u = await auth_user(x_init_data, db)
    if u.role != m.Role.super_admin.value:
        raise HTTPException(403, "Faqat super admin")
    return u


@app.post("/api/admin/overview")
async def admin_overview(x_init_data: str = Header(None, alias="X-Init-Data")):
    async with SessionLocal() as db:
        await _super(db, x_init_data)
        groups = await svc.list_groups(db)
        glist = []
        for g in groups:
            studs = await svc.group_students(db, g.id)
            tcount = (await db.execute(select(func.count()).select_from(m.TeacherAssignment)
                                       .where(m.TeacherAssignment.group_id == g.id))).scalar()
            glist.append({"id": g.id, "name": g.name, "students": len(studs), "teachers": tcount})
        users_total = (await db.execute(select(func.count()).select_from(m.User))).scalar()
        faceid_total = (await db.execute(select(func.count()).select_from(m.User)
                                         .where(m.User.faceid_registered == True))).scalar()  # noqa: E712
        sec = list((await db.execute(select(m.SecurityEvent)
                    .order_by(m.SecurityEvent.created_at.desc()).limit(20))).scalars())
        sessions = list((await db.execute(select(m.AttSession)
                    .order_by(m.AttSession.opened_at.desc()).limit(15))).scalars())
        return ok(
            groups=glist, users_total=users_total, faceid_total=faceid_total,
            security=[{"when": e.created_at.strftime("%m-%d %H:%M"), "kind": e.kind,
                       "uid": e.user_id, "detail": e.detail} for e in sec],
            sessions=[{"id": s.id, "group_id": s.group_id, "para": s.para,
                       "status": s.status, "when": s.opened_at.strftime("%m-%d %H:%M")} for s in sessions],
        )


@app.post("/api/admin/action")
async def admin_action(req: Request, x_init_data: str = Header(None, alias="X-Init-Data")):
    """Universal super admin amallari."""
    body = await req.json()
    act = body.get("action")
    async with SessionLocal() as db:
        u = await _super(db, x_init_data)
        try:
            if act == "create_group":
                g = await svc.create_group(db, body["name"], u.tg_id)
                res = {"id": g.id}
            elif act == "assign_teacher":
                t = await svc.get_or_create_user(db, int(body["tg_id"]))
                await svc.set_role(db, t.tg_id, m.Role.teacher.value)
                await svc.assign_teacher(db, int(body["group_id"]), t.id, body.get("subject"))
                res = {}
            elif act == "add_student":
                st = await svc.get_or_create_user(db, int(body["tg_id"]))
                await svc.add_student(db, int(body["group_id"]), st.id)
                res = {}
            elif act == "set_role":
                await svc.get_or_create_user(db, int(body["tg_id"]))
                await svc.set_role(db, int(body["tg_id"]), body["role"])
                res = {}
            elif act == "block":
                usr = await svc.user_by_tg(db, int(body["tg_id"]))
                if usr:
                    usr.is_blocked = bool(body.get("value", True))
                    await db.commit()
                res = {}
            elif act == "reset_device":
                # Telefon almashtirgan talaba uchun — Face ID va qurilmani tozalash
                usr = await svc.user_by_tg(db, int(body["tg_id"]))
                if usr:
                    usr.device_fp = None
                    usr.faceid_registered = False
                    for c in await user_credentials(db, usr.id):
                        await db.delete(c)
                    await db.commit()
                res = {}
            elif act == "starosta_create":
                from sqlalchemy import select as sel
                if (await db.execute(sel(m.Starosta).where(m.Starosta.login == body["login"]))).scalar_one_or_none():
                    return err("Login band")
                db.add(m.Starosta(login=body["login"], password_hash=hash_password(body["password"]),
                                  group_id=int(body["group_id"]), full_name=body.get("full_name", ""),
                                  created_by=u.tg_id))
                await db.commit()
                res = {}
            elif act == "starosta_passwd":
                from sqlalchemy import select as sel
                stz = (await db.execute(sel(m.Starosta).where(m.Starosta.login == body["login"]))).scalar_one_or_none()
                if not stz:
                    return err("Starosta topilmadi")
                stz.password_hash = hash_password(body["password"])
                await db.commit()
                res = {}
            elif act == "starosta_toggle":
                from sqlalchemy import select as sel
                stz = (await db.execute(sel(m.Starosta).where(m.Starosta.login == body["login"]))).scalar_one_or_none()
                if stz:
                    stz.is_active = not stz.is_active
                    await db.commit()
                res = {}
            elif act == "purge_now":
                from app.cleanup import purge_old
                days = int(body.get("days", settings.retention_days))
                res = await purge_old(days)
            else:
                return err("Noma'lum amal")
            await svc.audit(db, u.tg_id, "admin:" + act, json.dumps(body)[:200])
            return ok(**res)
        except KeyError as e:
            return err(f"Maydon yetishmaydi: {e}")


@app.post("/api/admin/starostas")
async def admin_starostas(x_init_data: str = Header(None, alias="X-Init-Data")):
    async with SessionLocal() as db:
        await _super(db, x_init_data)
        rows = list((await db.execute(select(m.Starosta))).scalars())
        return ok(starostas=[{"login": s.login, "group_id": s.group_id,
                              "name": s.full_name, "active": s.is_active} for s in rows])


# =========================================================================== #
#  STAROSTA — web login (Telegramsiz), login/parol
# =========================================================================== #
def _starosta_cookie(login: str) -> str:
    return signer.dumps({"starosta": login})


async def _starosta_from(req: Request, db) -> m.Starosta:
    tok = req.headers.get("X-Starosta") or req.cookies.get("starosta")
    if not tok:
        raise HTTPException(401, "Kirmagansiz")
    try:
        data = signer.loads(tok, max_age=86400)
    except BadSignature:
        raise HTTPException(401, "Sessiya eskirdi")
    stz = (await db.execute(select(m.Starosta).where(m.Starosta.login == data["starosta"]))).scalar_one_or_none()
    if not stz or not stz.is_active:
        raise HTTPException(403, "Starosta faol emas")
    return stz


@app.post("/api/starosta/login")
async def starosta_login(req: Request):
    body = await req.json()
    async with SessionLocal() as db:
        stz = (await db.execute(select(m.Starosta).where(m.Starosta.login == body.get("login", "")))).scalar_one_or_none()
        if not stz or not verify_password(body.get("password", ""), stz.password_hash):
            await svc.security_event(db, None, "starosta_login_fail", f"login={body.get('login')}", client_ip(req))
            return err("Login yoki parol noto'g'ri", 401)
        if not stz.is_active:
            return err("Hisob faol emas", 403)
        await svc.audit(db, None, "starosta_login", stz.login, client_ip(req))
    resp = ok(token=_starosta_cookie(stz.login), group_id=stz.group_id, name=stz.full_name or stz.login)
    return resp


@app.post("/api/starosta/live")
async def starosta_live(req: Request):
    async with SessionLocal() as db:
        stz = await _starosta_from(req, db)
        s = await svc.active_session_for_group(db, stz.group_id)
        if not s:
            return ok(active=False)
        summ = await svc.session_summary(db, s.id)
        return ok(active=True, session_id=s.id, para=s.para,
                  present=summ["present"], late=summ["late"], absent=summ["absent"],
                  total=summ["total"], rows=summ["rows"])


@app.post("/api/starosta/manual")
async def starosta_manual(req: Request):
    body = await req.json()
    async with SessionLocal() as db:
        stz = await _starosta_from(req, db)
        s = await svc.get_session(db, int(body["session_id"]))
        if not s or s.group_id != stz.group_id:
            return err("Ruxsat yo'q", 403)
        student = (await db.execute(select(m.User).where(m.User.id == int(body["student_id"])))).scalar_one_or_none()
        if not student:
            return err("Talaba yo'q", 404)
        status = body.get("status", m.AttStatus.present.value)
        if await svc.already_marked(db, s.id, student.id):
            att = (await db.execute(select(m.Attendance).where(
                m.Attendance.session_id == s.id, m.Attendance.student_id == student.id))).scalar_one()
            att.status, att.method = status, m.Method.manual.value
            await db.commit()
        else:
            await svc.mark_attendance(db, s.id, student.id, status=status, method=m.Method.manual.value)
        await svc.audit(db, None, "starosta_manual", f"{stz.login} sid={s.id} s={student.id} {status}")
        return ok()


@app.post("/api/starosta/students")
async def starosta_students(req: Request):
    async with SessionLocal() as db:
        stz = await _starosta_from(req, db)
        studs = await svc.group_students(db, stz.group_id)
        return ok(students=[{"id": x.id, "name": x.full_name or str(x.tg_id)} for x in studs])
