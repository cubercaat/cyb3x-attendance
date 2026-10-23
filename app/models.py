"""Barcha ma'lumotlar bazasi jadvallari."""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Role(str, enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    teacher = "teacher"      # ustoz
    starosta = "starosta"    # guruh sardori
    student = "student"      # talaba


class SessionStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    closed = "closed"


class AttStatus(str, enum.Enum):
    present = "present"   # keldi
    late = "late"         # kech qoldi
    absent = "absent"     # kelmadi


class Method(str, enum.Enum):
    qr = "qr"
    code = "code"
    manual = "manual"
    faceid = "faceid"


# ----------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.student.value)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Qurilmaga bog'lash — bitta akkaunt bitta qurilma (do'stga akkaunt berishni oldini oladi)
    device_fp: Mapped[str | None] = mapped_column(String(128), nullable=True)
    faceid_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

    credentials: Mapped[list["Credential"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[int] = mapped_column(BigInteger)  # super_admin tg_id
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class GroupMember(Base):
    """Talaba <-> guruh."""
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # jurnal raqami
    # Havola orqali o'zi qo'shilgan talaba starosta tasdig'ini kutadi (confirmed=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


class TeacherAssignment(Base):
    """Ustoz <-> guruh. Ustozlar bir-biridan bexabar (faqat o'z biriktirmasini ko'radi)."""
    __tablename__ = "teacher_assignments"
    __table_args__ = (UniqueConstraint("group_id", "teacher_id", name="uq_teacher_group"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Credential(Base):
    """Face ID (WebAuthn) ishonchnomasi — qurilmaning biometrikasiga bog'langan ochiq kalit."""
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_used: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="credentials")


class AttSession(Base):
    """Davomat sessiyasi — ustoz boshlaydi, para (1..6) bo'yicha."""
    __tablename__ = "att_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    opened_by: Mapped[int] = mapped_column(BigInteger)  # ustoz/admin tg_id
    para: Mapped[int] = mapped_column(Integer, default=1)  # 1..6
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default=SessionStatus.active.value)
    # Har sessiyaning o'z maxfiy urug'i — tokenlar shunga imzolanadi
    session_secret: Mapped[str] = mapped_column(String(64))
    late_after_min: Mapped[int] = mapped_column(Integer, default=10)  # shu daqiqadan keyin "kech"
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_att_once"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("att_sessions.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(10), default=AttStatus.present.value)
    method: Mapped[str] = mapped_column(String(10), default=Method.qr.value)
    marked_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # qo'lda bo'lsa — kim
    device_fp: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)  # shubhali belgilar (JSON)
    marked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsedToken(Base):
    """Replay/qayta ishlatishga qarshi — har token faqat bir marta."""
    __tablename__ = "used_tokens"
    __table_args__ = (UniqueConstraint("session_id", "counter", "student_id", name="uq_used_token"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    counter: Mapped[int] = mapped_column(Integer)
    student_id: Mapped[int] = mapped_column(Integer)
    used_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Starosta(Base):
    """Starosta — login/parol bilan kiradi. Parolni admin paneldan o'zgartirish mumkin."""
    __tablename__ = "starostas"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    """Barcha muhim amallar jurnali — kim, nima, qachon (xavfsizlik nazorati)."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class SecurityEvent(Base):
    """Shubhali hodisalar — forward urinishi, boshqa qurilma, replay, h.k."""
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(48))     # replay / wrong_device / stale_token / no_faceid ...
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
