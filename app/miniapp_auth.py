"""Telegram Mini App initData tekshiruvi.

Telegram har mini app foydalanuvchisi uchun imzolangan `initData` beradi.
Biz uni bot tokeni bilan tekshiramiz => foydalanuvchi tg_id sini ishonchli bilamiz.
Buni soxtalashtirib bo'lmaydi (HMAC bot sirига bog'langan).
Hujjat: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.config import settings


def validate_init_data(init_data: str, max_age_sec: int = 3600) -> dict | None:
    """initData ni tekshiradi. To'g'ri bo'lsa foydalanuvchi dict qaytaradi, aks holda None."""
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    # auth_date — eskirganini rad etamiz
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age_sec and auth_date and (time.time() - auth_date) > max_age_sec:
        return None

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except Exception:
        return None
    return user
