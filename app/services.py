"""Xizmat qatlami — bot va API uchun umumiy ma'lumotlar bazasi amallari."""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models as m
from app.config import settings
from app.security import new_session_secret


# --------------------------------------------------------------------------- #
#  Foydalanuvchilar / rollar
# --------------------------------------------------------------------------- #
async def get_or_create_user(db: AsyncSession, tg_id: int, full_name: str = "", username: str | None = None) -> m.User:
    u = (await db.execute(select(m.User).where(m.User.tg_id == tg_id))).scalar_one_or_none()
    if u is None:
        role = m.Role.super_admin.value if tg_id == settings.super_admin_id else m.Role.student.value
        u = m.User(tg_id=tg_id, full_name=full_name, username=username, role=role)
        db.add(u)
        await db.commit()
        await db.refresh(u)
    else:
        changed = False
        if full_name and u.full_name != full_name:
            u.full_name, changed = full_name, True
        if username and u.username != username:
            u.username, changed = username, True
        # Super adminni har doim ko'tarib turamiz
        if tg_id == settings.super_admin_id and u.role != m.Role.super_admin.value:
            u.role, changed = m.Role.super_admin.value, True
        if changed:
            await db.commit()
    return u


async def user_by_tg(db: AsyncSession, tg_id: int) -> m.User | None:
    return (await db.execute(select(m.User).where(m.User.tg_id == tg_id))).scalar_one_or_none()


async def set_role(db: AsyncSession, tg_id: int, role: str) -> bool:
    u = await user_by_tg(db, tg_id)
    if not u:
        return False
    u.role = role
    await db.commit()
    return True


def is_staff(user: m.User) -> bool:
    return user.role in (m.Role.super_admin.value, m.Role.admin.value, m.Role.teacher.value)


# --------------------------------------------------------------------------- #
#  Guruhlar
# --------------------------------------------------------------------------- #
async def create_group(db: AsyncSession, name: str, by_tg: int) -> m.Group:
    g = m.Group(name=name, created_by=by_tg)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return g


async def list_groups(db: AsyncSession) -> list[m.Group]:
    return list((await db.execute(select(m.Group).where(m.Group.is_active == True))).scalars())  # noqa: E712


async def groups_for_teacher(db: AsyncSession, teacher_user_id: int) -> list[m.Group]:
    q = (
        select(m.Group)
        .join(m.TeacherAssignment, m.TeacherAssignment.group_id == m.Group.id)
        .where(m.TeacherAssignment.teacher_id == teacher_user_id, m.Group.is_active == True)  # noqa: E712
    )
    return list((await db.execute(q)).scalars())


async def assign_teacher(db: AsyncSession, group_id: int, teacher_user_id: int, subject: str | None = None) -> None:
    exists = (
        await db.execute(
            select(m.TeacherAssignment).where(
                m.TeacherAssignment.group_id == group_id,
                m.TeacherAssignment.teacher_id == teacher_user_id,
            )
        )
    ).scalar_one_or_none()
    if not exists:
        db.add(m.TeacherAssignment(group_id=group_id, teacher_id=teacher_user_id, subject=subject))
        await db.commit()


async def add_student(db: AsyncSession, group_id: int, user_id: int, number: int | None = None,
                      confirmed: bool = True) -> str:
    """Natija: 'added' | 'exists' | 'pending_exists'."""
    exists = (
        await db.execute(
            select(m.GroupMember).where(m.GroupMember.group_id == group_id, m.GroupMember.user_id == user_id)
        )
    ).scalar_one_or_none()
    if exists:
        return "exists" if exists.confirmed else "pending_exists"
    db.add(m.GroupMember(group_id=group_id, user_id=user_id, number=number, confirmed=confirmed))
    await db.commit()
    return "added"


async def group_students(db: AsyncSession, group_id: int, only_confirmed: bool = True) -> list[m.User]:
    q = (
        select(m.User)
        .join(m.GroupMember, m.GroupMember.user_id == m.User.id)
        .where(m.GroupMember.group_id == group_id)
        .order_by(m.GroupMember.number.nulls_last(), m.User.full_name)
    )
    if only_confirmed:
        q = q.where(m.GroupMember.confirmed == True)  # noqa: E712
    return list((await db.execute(q)).scalars())


async def pending_students(db: AsyncSession, group_id: int) -> list[m.User]:
    q = (
        select(m.User)
        .join(m.GroupMember, m.GroupMember.user_id == m.User.id)
        .where(m.GroupMember.group_id == group_id, m.GroupMember.confirmed == False)  # noqa: E712
        .order_by(m.User.full_name)
    )
    return list((await db.execute(q)).scalars())


async def is_confirmed_member(db: AsyncSession, group_id: int, user_id: int) -> bool:
    gm = (await db.execute(select(m.GroupMember).where(
        m.GroupMember.group_id == group_id, m.GroupMember.user_id == user_id))).scalar_one_or_none()
    return bool(gm and gm.confirmed)


async def confirm_member(db: AsyncSession, group_id: int, user_id: int) -> bool:
    gm = (await db.execute(select(m.GroupMember).where(
        m.GroupMember.group_id == group_id, m.GroupMember.user_id == user_id))).scalar_one_or_none()
    if not gm:
        return False
    gm.confirmed = True
    await db.commit()
    return True


async def remove_member(db: AsyncSession, group_id: int, user_id: int) -> None:
    gm = (await db.execute(select(m.GroupMember).where(
        m.GroupMember.group_id == group_id, m.GroupMember.user_id == user_id))).scalar_one_or_none()
    if gm:
        await db.delete(gm)
        await db.commit()


# --------------------------------------------------------------------------- #
#  Sessiyalar (davomat ochish/yopish)
# --------------------------------------------------------------------------- #
async def open_session(db: AsyncSession, group_id: int, by_tg: int, para: int, subject: str | None = None) -> m.AttSession:
    # Ochiq sessiyani qayta ishlatish (bir guruh+para uchun bitta faol)
    existing = (
        await db.execute(
            select(m.AttSession).where(
                m.AttSession.group_id == group_id,
                m.AttSession.para == para,
                m.AttSession.status == m.SessionStatus.active.value,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    s = m.AttSession(
        group_id=group_id, opened_by=by_tg, para=para, subject=subject,
        session_secret=new_session_secret(),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def get_session(db: AsyncSession, sid: int) -> m.AttSession | None:
    return (await db.execute(select(m.AttSession).where(m.AttSession.id == sid))).scalar_one_or_none()


async def active_session_for_group(db: AsyncSession, group_id: int) -> m.AttSession | None:
    return (
        await db.execute(
            select(m.AttSession)
            .where(m.AttSession.group_id == group_id, m.AttSession.status == m.SessionStatus.active.value)
            .order_by(m.AttSession.opened_at.desc())
        )
    ).scalars().first()


async def set_session_status(db: AsyncSession, sid: int, status: str) -> None:
    s = await get_session(db, sid)
    if s:
        s.status = status
        if status == m.SessionStatus.closed.value:
            s.closed_at = m.now()
        await db.commit()


# --------------------------------------------------------------------------- #
#  Davomat yozish
# --------------------------------------------------------------------------- #
async def already_marked(db: AsyncSession, sid: int, student_id: int) -> bool:
    return (
        await db.execute(
            select(m.Attendance.id).where(
                m.Attendance.session_id == sid, m.Attendance.student_id == student_id
            )
        )
    ).scalar_one_or_none() is not None


async def token_reused(db: AsyncSession, sid: int, counter: int, student_id: int) -> bool:
    return (
        await db.execute(
            select(m.UsedToken.id).where(
                m.UsedToken.session_id == sid,
                m.UsedToken.counter == counter,
                m.UsedToken.student_id == student_id,
            )
        )
    ).scalar_one_or_none() is not None


async def mark_attendance(
    db: AsyncSession,
    sid: int,
    student_id: int,
    status: str,
    method: str,
    counter: int | None = None,
    device_fp: str | None = None,
    marked_by: int | None = None,
    flags: dict | None = None,
) -> m.Attendance:
    att = m.Attendance(
        session_id=sid, student_id=student_id, status=status, method=method,
        token_counter=counter, device_fp=device_fp, marked_by=marked_by,
        flags=json.dumps(flags) if flags else None,
    )
    db.add(att)
    if counter is not None:
        db.add(m.UsedToken(session_id=sid, counter=counter, student_id=student_id))
    await db.commit()
    await db.refresh(att)
    return att


# --------------------------------------------------------------------------- #
#  Audit / xavfsizlik hodisalari
# --------------------------------------------------------------------------- #
async def audit(db: AsyncSession, actor_id: int | None, action: str, detail: str | None = None, ip: str | None = None) -> None:
    db.add(m.AuditLog(actor_id=actor_id, action=action, detail=detail, ip=ip))
    await db.commit()


async def security_event(db: AsyncSession, user_id: int | None, kind: str, detail: str | None = None, ip: str | None = None) -> None:
    db.add(m.SecurityEvent(user_id=user_id, kind=kind, detail=detail, ip=ip))
    await db.commit()


# --------------------------------------------------------------------------- #
#  Hisobot uchun jamlovchilar
# --------------------------------------------------------------------------- #
async def session_summary(db: AsyncSession, sid: int) -> dict:
    s = await get_session(db, sid)
    if not s:
        return {}
    students = await group_students(db, s.group_id)
    marks = {
        a.student_id: a
        for a in (await db.execute(select(m.Attendance).where(m.Attendance.session_id == sid))).scalars()
    }
    rows = []
    present = late = absent = 0
    for st in students:
        a = marks.get(st.id)
        if a is None:
            status = m.AttStatus.absent.value
            absent += 1
        else:
            status = a.status
            if status == m.AttStatus.present.value:
                present += 1
            elif status == m.AttStatus.late.value:
                late += 1
            else:
                absent += 1
        rows.append({
            "name": st.full_name or (st.username or str(st.tg_id)),
            "status": status,
            "method": a.method if a else "-",
            "time": a.marked_at.strftime("%H:%M:%S") if a else "-",
        })
    return {
        "session": s, "rows": rows,
        "present": present, "late": late, "absent": absent, "total": len(students),
    }
