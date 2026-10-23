"""Ma'lumotlar bazasi — SQLAlchemy async engine va sessiya."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    from app import models  # noqa: F401 — modellarni ro'yxatdan o'tkazish uchun
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Yengil migratsiya — eski bazaga yangi ustun qo'shish (bo'lmasa)
        try:
            await conn.execute(text("ALTER TABLE group_members ADD COLUMN confirmed BOOLEAN DEFAULT 1"))
        except Exception:
            pass  # ustun allaqachon mavjud


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
