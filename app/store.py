"""Vaqtinchalik (in-memory) do'kon — WebAuthn challenge'lari va tezkor replay keshi.

Ishlab chiqarishda ko'p instansli bo'lsa Redis ga o'tkazish mumkin;
bitta instans (test/kichik hajm) uchun bu yetarli va tez.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_data: dict[str, tuple[float, bytes]] = {}  # key -> (expiry_ts, value)


def put(key: str, value: bytes, ttl: int = 300) -> None:
    with _lock:
        _data[key] = (time.time() + ttl, value)


def pop(key: str) -> bytes | None:
    with _lock:
        item = _data.pop(key, None)
    if not item:
        return None
    exp, val = item
    if exp < time.time():
        return None
    return val


def cleanup() -> None:
    now = time.time()
    with _lock:
        dead = [k for k, (exp, _) in _data.items() if exp < now]
        for k in dead:
            _data.pop(k, None)
