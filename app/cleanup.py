"""Avtomatik tozalash — davomatni N kundan keyin 0 ga tushiradi.

Nima o'chadi: Attendance, AttSession, UsedToken, SecurityEvent, AuditLog —
retention_days dan eski yozuvlar.
Nima SAQLANADI: User, Group, GroupMember, TeacherAssignment, Credential (Face ID),
Starosta — ya'ni ro'yxat va sozlamalar. Talabalar qaytadan ro'yxatdan o'tmaydi.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import delete

from app import models as m
from app.config import settings
from app.database import SessionLocal

log = logging.getLogger("cyb3x.cleanup")


async def purge_old(retention_days: int | None = None) -> dict:
    days = retention_days if retention_days is not None else settings.retention_days
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    out: dict[str, int] = {}
    async with SessionLocal() as db:
        # Eski sessiyalar id lari (bog'liq yozuvlar bilan)
        for model, field in [
            (m.Attendance, m.Attendance.marked_at),
            (m.AttSession, m.AttSession.opened_at),
            (m.UsedToken, m.UsedToken.used_at),
            (m.SecurityEvent, m.SecurityEvent.created_at),
            (m.AuditLog, m.AuditLog.created_at),
        ]:
            res = await db.execute(delete(model).where(field < cutoff))
            out[model.__tablename__] = res.rowcount or 0
        await db.commit()
    log.info("Tozalash: %s dan eski — %s", cutoff.date(), out)
    return out


async def cleanup_loop() -> None:
    """Fon vazifa — har cleanup_every_hours da ishga tushadi."""
    interval = max(1, settings.cleanup_every_hours) * 3600
    while True:
        try:
            await purge_old()
        except Exception as e:  # noqa: BLE001
            log.warning("Tozalash xatosi: %s", e)
        await asyncio.sleep(interval)
