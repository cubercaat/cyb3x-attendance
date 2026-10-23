"""Xavfsizlik yadrosi testlari — faqat standart kutubxonalar bilan ishlaydi.

app.config pydantic_settings ga bog'liq (bu yerda yo'q), shuning uchun testda
uni soxta modul bilan almashtiramiz va REAL app.security / app.miniapp_auth
kodini sinaymiz.
"""
import hashlib
import hmac
import json
import sys
import time
import types
from urllib.parse import urlencode

# ---- app.config ni soxta sozlama bilan almashtirish ----
BOT_TOKEN = "123456:TEST-BOT-TOKEN-xyz"
cfg = types.ModuleType("app.config")


class _S:
    bot_token = BOT_TOKEN
    secret_key = "unit-test-secret-key-0123456789"
    token_ttl_seconds = 8
    campus_lat = 41.3480
    campus_lon = 69.2910
    campus_radius_m = 30
    public_url = "https://cyb3x.example.com"
    rp_id = "cyb3x.example.com"
    origin = "https://cyb3x.example.com"


cfg.settings = _S()
sys.modules["app.config"] = cfg
# app paketini ham ro'yxatga olamiz
if "app" not in sys.modules:
    pkg = types.ModuleType("app")
    pkg.__path__ = ["app"]
    sys.modules["app"] = pkg

from app import security as sec           # noqa: E402
from app.miniapp_auth import validate_init_data  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


print("\n1) Rotatsion token va 4-xonali kod")
secret = sec.new_session_secret()
sid = 42
c = sec.current_counter()
tok = sec.make_token(secret, sid, c)
code = sec.make_code(secret, sid, c)
ok, cc, reason = sec.parse_and_verify_token(secret, sid, tok)
check("to'g'ri token qabul qilinadi", ok and cc == c and reason == "ok")
check("4-xonali kod 4 raqam", code.isdigit() and len(code) == 4)
okc, ccc, rc = sec.verify_code(secret, sid, code)
check("to'g'ri kod qabul qilinadi", okc and rc == "ok")

print("\n2) ANTI-FORWARD — eski QR/kod ishlamaydi")
old_tok = sec.make_token(secret, sid, c - 5)       # 5 oyna eski (~40s oldin)
ok, _, reason = sec.parse_and_verify_token(secret, sid, old_tok)
check("eski token RAD etiladi (stale_token)", (not ok) and reason == "stale_token")
old_code = sec.make_code(secret, sid, c - 5)
okc, _, rc = sec.verify_code(secret, sid, old_code)
check("eski 4-xonali kod RAD etiladi", not okc)

print("\n3) Soxta imzo (boshqa maxfiy urug') ishlamaydi")
other = sec.new_session_secret()
forged = sec.make_token(other, sid, c)             # boshqa guruhdan nusxa
ok, _, reason = sec.parse_and_verify_token(secret, sid, forged)
check("boshqa sessiya imzosi RAD etiladi", (not ok) and reason == "bad_signature")

print("\n4) Buzilgan token")
ok, _, reason = sec.parse_and_verify_token(secret, sid, "xatolik.satr")
check("buzilgan format RAD etiladi", not ok)
ok, _, reason = sec.parse_and_verify_token(secret, 999, tok)
check("boshqa sessiya id RAD etiladi", (not ok) and reason == "wrong_session")

print("\n5) Qo'shni oyna (soat farqi) qabul qilinadi")
prev = sec.make_token(secret, sid, c - 1)
ok, _, _ = sec.parse_and_verify_token(secret, sid, prev)
check("oldingi 1 oyna qabul qilinadi (tarmoq kechikishi)", ok)

print("\n6) Masofa (haversine) — 30 m radius")
inside_ok, d_in = sec.within_campus(_S.campus_lat + 0.0001, _S.campus_lon)   # ~11 m
outside_ok, d_out = sec.within_campus(_S.campus_lat + 0.003, _S.campus_lon)  # ~333 m
check(f"yaqin nuqta ichkarida ({d_in:.0f} m)", inside_ok)
check(f"uzoq nuqta tashqarida ({d_out:.0f} m)", not outside_ok)

print("\n7) Parol hash (starosta) — PBKDF2")
h = sec.hash_password("MySecret123")
check("to'g'ri parol tasdiqlanadi", sec.verify_password("MySecret123", h))
check("noto'g'ri parol rad etiladi", not sec.verify_password("wrong", h))
check("hash tuz bilan har xil", sec.hash_password("x") != sec.hash_password("x"))

print("\n8) Qurilma barmoq izi barqaror")
fp1 = sec.device_fingerprint("UA|iPhone|uuid-1")
fp2 = sec.device_fingerprint("UA|iPhone|uuid-1")
fp3 = sec.device_fingerprint("UA|Android|uuid-2")
check("bir xil qurilma = bir xil fp", fp1 == fp2)
check("boshqa qurilma = boshqa fp", fp1 != fp3)

print("\n9) Telegram initData HMAC tekshiruvi")


def make_init_data(user: dict, token: str, auth_date=None):
    auth_date = auth_date or int(time.time())
    fields = {"auth_date": str(auth_date), "query_id": "AAE", "user": json.dumps(user, separators=(",", ":"))}
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, dcs.encode(), hashlib.sha256).hexdigest()
    fields["hash"] = h
    return urlencode(fields)


user = {"id": 777001, "first_name": "Zafar", "username": "zafarx"}
valid = make_init_data(user, BOT_TOKEN)
got = validate_init_data(valid)
check("haqiqiy initData qabul qilinadi", got and got["id"] == 777001)

tampered = make_init_data(user, "999999:WRONG-TOKEN")   # boshqa bot bilan imzolangan
check("soxta initData (boshqa token) RAD etiladi", validate_init_data(tampered) is None)

# hash ni buzish
bad = valid.replace(valid.split("hash=")[1][:4], "0000")
check("buzilgan hash RAD etiladi", validate_init_data(bad) is None)

old = make_init_data(user, BOT_TOKEN, auth_date=int(time.time()) - 7200)
check("eskirgan initData (2 soat) RAD etiladi", validate_init_data(old, max_age_sec=3600) is None)

print(f"\n{'='*44}\nNATIJA: {PASS} ✅  /  {FAIL} ❌\n{'='*44}")
sys.exit(1 if FAIL else 0)
