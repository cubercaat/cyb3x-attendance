"""Xavfsizlik yadrosi — anti-forward rotatsion token, 4-xonali kod, replay himoyasi, masofa, hash.

G'oya:
  * Har davomat sessiyasining o'z `session_secret` i bor.
  * Vaqt TTL soniyali oynalarga bo'linadi:  counter = unix_time // TTL
  * token = f"{sid}.{counter}.{sig}"  —  sig = HMAC(secret, "sid.counter")
  * Doskadagi QR har TTL soniyada yangilanadi => eski QR screenshot foydasiz (anti-forward).
  * 4-xonali kod ham xuddi shu HMAC dan kelib chiqadi => QR o'rniga kodni yozsa ham bo'ladi.
  * Server token oynasini faqat joriy (va bitta oldingi) oyna bilan qabul qiladi.
  * Har (sessiya, counter, talaba) kombinatsiyasi faqat bir marta => replay yo'q.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time

from app.config import settings


# --------------------------------------------------------------------------- #
#  Imzolash yordamchilari
# --------------------------------------------------------------------------- #
def _root_key() -> bytes:
    return settings.secret_key.encode("utf-8")


def new_session_secret() -> str:
    """Yangi sessiya uchun tasodifiy maxfiy urug'."""
    return secrets.token_hex(16)


def current_counter(ttl: int | None = None, at: float | None = None) -> int:
    ttl = ttl or settings.token_ttl_seconds
    at = at if at is not None else time.time()
    return int(at // ttl)


def _sig(session_secret: str, sid: int, counter: int) -> str:
    msg = f"{sid}.{counter}".encode("utf-8")
    key = _root_key() + session_secret.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
#  Token (QR ichidagi satr) va 4-xonali kod
# --------------------------------------------------------------------------- #
def make_token(session_secret: str, sid: int, counter: int | None = None) -> str:
    """Doskadagi QR ichiga yoziladigan imzolangan satr."""
    counter = counter if counter is not None else current_counter()
    sig = _sig(session_secret, sid, counter)[:16]
    return f"{sid}.{counter}.{sig}"


def make_code(session_secret: str, sid: int, counter: int | None = None) -> str:
    """QR yonidagi 4-xonali raqamli kod (qo'lda kiritish uchun). QR bilan bir xil oynadan."""
    counter = counter if counter is not None else current_counter()
    full = _sig(session_secret, sid, counter)
    num = int(full[:8], 16) % 10000
    return f"{num:04d}"


class TokenError(str):
    pass


def parse_and_verify_token(session_secret: str, sid: int, token: str) -> tuple[bool, int, str]:
    """QR tokenini tekshirish.
    Natija: (ok, counter, sabab). ok=False bo'lsa sabab xavfsizlik hodisasi sifatida yoziladi.
    """
    try:
        p_sid, p_counter, p_sig = token.strip().split(".")
        p_sid_i = int(p_sid)
        p_counter_i = int(p_counter)
    except Exception:
        return False, -1, "bad_format"

    if p_sid_i != sid:
        return False, -1, "wrong_session"

    now_counter = current_counter()
    # Soat farqi + tarmoq kechikishi uchun joriy va bitta oldingi oynani qabul qilamiz
    if p_counter_i not in (now_counter, now_counter - 1):
        return False, p_counter_i, "stale_token"  # eski QR => forward urinishi bo'lishi mumkin

    expected = _sig(session_secret, sid, p_counter_i)[:16]
    if not hmac.compare_digest(expected, p_sig):
        return False, p_counter_i, "bad_signature"

    return True, p_counter_i, "ok"


def verify_code(session_secret: str, sid: int, code: str) -> tuple[bool, int, str]:
    """4-xonali kodni tekshirish — joriy yoki oldingi oyna."""
    code = code.strip()
    if not (code.isdigit() and len(code) == 4):
        return False, -1, "bad_format"
    now_counter = current_counter()
    for c in (now_counter, now_counter - 1):
        if make_code(session_secret, sid, c) == code:
            return True, c, "ok"
    return False, -1, "stale_or_wrong_code"


# --------------------------------------------------------------------------- #
#  Masofa (ixtiyoriy — faqat super admin tekshiruvi; mini app lokatsiya SO'RAMAYDI)
# --------------------------------------------------------------------------- #
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ikki nuqta orasidagi masofa (metr)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def within_campus(lat: float, lon: float) -> tuple[bool, float]:
    d = haversine_m(lat, lon, settings.campus_lat, settings.campus_lon)
    return d <= settings.campus_radius_m, d


# --------------------------------------------------------------------------- #
#  Parol hash (starosta logini uchun) — PBKDF2, tuzsiz saqlanmaydi
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hexd = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return hmac.compare_digest(dk.hex(), hexd)


# --------------------------------------------------------------------------- #
#  Qurilma barmoq izi (bitta akkaunt = bitta qurilma)
# --------------------------------------------------------------------------- #
def device_fingerprint(raw: str) -> str:
    """Brauzer/qurilma signaturasini barqaror hash ga aylantiradi."""
    return hashlib.sha256((settings.secret_key + "|" + raw).encode()).hexdigest()[:32]
