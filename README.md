# 🔒 CYB3X DAVOMAT

Kiberxavfsizlikka asoslangan davomat tizimi — Telegram bot + Mini App.
Maqsad: **aldashni butunlay imkonsiz qilish**. Forward, akkauntni do'stga berish,
screenshot, soxta lokatsiya — hammasi to'siladi.

> Bu `@cyb3xbot` ning kuchaytirilgan, noldan yozilgan versiyasi.

---

## 1. Qanday qilib aldashning oldi olinadi?

| Hiyla | Eski bot | CYB3X himoyasi |
|---|---|---|
| **Forward qilish** (QR/kodni do'stga yuborish) | ishlardi | QR va 4-xonali kod **har ~8 soniyada butunlay o'zgaradi** (HMAC imzolangan oyna). Yuborilgan screenshot bir zumda eskiradi. |
| **Akkauntni do'stga berish** (telefonini/akkauntini uzatish) | ishlardi | **Face ID (WebAuthn)** — kalit qurilmaning biometrikasiga bog'langan, qurilmadan **chiqmaydi**. Boshqa telefonda bu kalit yo'q. Ustiga **bitta akkaunt = bitta qurilma** (device fingerprint). |
| **Bitta QR'ni ikki kishi ishlatishi / qayta ishlatish** | — | **Replay himoyasi** — har (sessiya, oyna, talaba) faqat **bir marta**. |
| **Soxta imzo / boshqa guruhdan nusxa** | — | Har sessiyaning o'z maxfiy urug'i bor; imzo mos kelmasa rad etiladi. |
| **Soxta "men o'qituvchi" so'rovi** | — | Telegram `initData` HMAC bilan tekshiriladi — foydalanuvchini soxtalashtirib bo'lmaydi. |
| **Lokatsiya orqali fishing** | — | Mini app **lokatsiya SO'RAMAYDI**. QR ni ko'rish uchun jismonan sinfda bo'lish shartligi — yetarli yaqinlik isboti. |

**Ikki qavatli qulf:** hatto kimdir 8 soniya ichida QR ni yuborib ulgursa ham,
qabul qiluvchida ro'yxatdan o'tgan qurilma va Face ID bo'lmaydi → baribir o'tmaydi.

Har bir shubhali urinish **Xavfsizlik jurnaliga** yoziladi va super admin ko'radi
(`/xavfsizlik` yoki admin panel).

---

## 2. Rollar

- **👑 SUPER ADMIN (siz)** — HAMMA narsani ko'radi. Guruh yaratadi, ustoz biriktiradi,
  rol beradi, starosta ochadi, global hisobot va xavfsizlik jurnalini ko'radi,
  qurilmani reset qiladi, bloklaydi. Faqat siz barcha guruhlarni ko'rasiz.
- **🛡 Admin** — qo'lda belgilash va yordam.
- **🎓 Ustoz** — faqat **o'ziga biriktirilgan** guruh(lar). **Ustozlar bir-biridan BEXABAR.**
- **📋 Starosta** — web login/parol bilan kiradi (Telegramsiz). Parolni admin paneldan
  o'zgartirish mumkin. Starostalar ham bir-biridan bexabar.
- **🧑‍🎓 Talaba** — Face ID + QR/kod bilan davomat belgilaydi.

---

## 3. To'liq funksiyalar ro'yxati (40+)

**Xavfsizlik:** aylanuvchi HMAC token · 4-xonali rotatsion kod · replay himoyasi ·
Face ID (WebAuthn, userVerification majburiy) · bitta akkaunt = bitta qurilma ·
qurilma fingerprint · Telegram initData tekshiruvi · forward/stale aniqlash ·
imzo tekshiruvi · xavfsizlik hodisalari jurnali · bloklash · qurilma reset ·
lokatsiyasiz ishlash (anti-fishing) · imzolangan hisobot havolasi.

**Davomat:** 1–6 para · sessiya ochish/pauza/yopish · QR skaner · 4-xonali kod ·
kech/keldi/kelmadi avtomatik aniqlash (vaqt bo'yicha) · qo'lda belgilash
(ustoz/admin/starosta) · jonli ro'yxat (real vaqtda) · bir martalik belgilash.

**Boshqaruv:** guruh yaratish/ro'yxat · ustoz biriktirish (izolyatsiya bilan) ·
talaba qo'shish · rol berish · starosta yaratish/parol/yoqish-o'chirish ·
foydalanuvchi haqida ma'lumot (`/kim`).

**Hisobot:** chiroyli Excel (rangli, foizli, jami) · jonli statistika kartalari ·
ustoz uchun "Hisobotlarim" · super admin global ko'rinish.

**Qulaylik:** ichki qo'llanma (sodda, yosh talabaga mos) · "Asosiy admin bilan
bog'lanish" → sizga yo'naltiriladi (`#admin ...`) · ustozga bildirishnoma ·
chiroyli dark-cyber dizayn · mobilega moslashgan.

> Bu ro'yxat kengaytiriladigan asos — yangi funksiyalarni qo'shish uchun 5-bo'limga qarang.

---

## 4. O'rnatish (3 qadam)

### Qadam 1 — Bot va ID lar
1. Telegram'da **@BotFather** → `/newbot` (yoki mavjud `@cyb3xbot`) → **token** oling.
2. O'zingizning Telegram ID ingizni **@userinfobot** dan oling (bu SUPER_ADMIN_ID).

### Qadam 2 — Deploy (bittasini tanlang)

**A) Render.com (eng oson, bepul, HTTPS bilan)**
1. Loyihani GitHub'ga yuklang.
2. render.com → **New → Blueprint** → repo ni ulang (`render.yaml` o'zi topiladi).
3. Environment: `BOT_TOKEN`, `SUPER_ADMIN_ID`, `PUBLIC_URL` (masalan
   `https://cyb3x-davomat.onrender.com`) ni kiriting. `SECRET_KEY` avtomatik.
4. Deploy. Tayyor.

**B) O'z serveringiz / VPS / orax.uz (domen bilan)**
```bash
git clone <repo> && cd cyb3x-attendance
cp .env.example .env     # qiymatlarni to'ldiring (BOT_TOKEN, SUPER_ADMIN_ID, PUBLIC_URL, SECRET_KEY)
pip install -r requirements.txt
python -m app.main
```
Oldiga HTTPS reverse-proxy qo'ying (nginx + certbot). `PUBLIC_URL` = sizning https domeningiz.

**C) Docker**
```bash
docker build -t cyb3x . && docker run -p 8080:8080 --env-file .env cyb3x
```

> ⚠️ **HTTPS majburiy** — Telegram Mini App va Face ID (WebAuthn) faqat `https://`
> domenda ishlaydi. `PUBLIC_URL` dagi domen Face ID ni shu domenga bog'laydi.

### Qadam 3 — Mini App URL ni ulash
@BotFather → `/mybots` → botni tanlang → **Bot Settings → Menu Button /
Configure Mini App** → URL: sizning `PUBLIC_URL`. Shu bilan tugma paydo bo'ladi.

---

## 5. Foydalanish (super admin ish tartibi)

Botga `/start` yozing, so'ng:
```
/guruh_yarat 21-14
/talaba_qosh 1 <talaba_tg_id>     (yoki admin paneldan)
/ustoz_biriktir 1 <ustoz_tg_id> Dasturlash
/starosta_yarat 1 starosta21 parol123
```
Yoki hammasi grafik **🛡 SUPER ADMIN panel** (Mini App) orqali.

- **Ustoz:** `/start` → 🎬 Davomatni boshlash → guruh+para → QR doskaga.
- **Talaba:** `/start` → ✅ Davomat belgilash → (bir marta Face ID) → QR skaner / kod.
- **Starosta:** `PUBLIC_URL/app/starosta` → login/parol.

Batafsil: `PUBLIC_URL/app/help` (ichki qo'llanma).

---

## 6. Face ID muhit talablari va zaxira

Face ID = **WebAuthn platform authenticator** (telefon Face ID/Touch ID).
- Ishlashi uchun: `https` domen + zamonaviy Telegram + qurilmada biometrika yoqilgan.
- Agar Telegram ichki brauzeri WebAuthn ni qo'llamasa — tizim avtomatik
  **4-xonali kod** ga tushadi (baribir rotatsion + qurilmaga bog'langan, xavfsiz).
- Talaba telefon almashtirsa — super admin **"Qurilmani reset"** bosadi,
  talaba yangi telefonda Face ID ni qayta o'rnatadi.

---

## 7. Test

```bash
python3 tests/test_security.py
```
Anti-forward, replay, imzo, masofa, parol, qurilma fingerprint va Telegram
initData HMAC — 20 ta tekshiruv. (Yadro faqat standart kutubxonalar bilan ishlaydi.)

---

## 8. Tuzilma

```
app/
  config.py          sozlamalar (.env)
  database.py        async SQLAlchemy
  models.py          barcha jadvallar
  security.py        🔑 anti-forward token, kod, replay, masofa, hash
  webauthn_utils.py  Face ID (WebAuthn)
  miniapp_auth.py    Telegram initData tekshiruvi
  services.py        DB amallar (bot + API umumiy)
  bot.py             aiogram bot, rollar, buyruqlar
  api.py             FastAPI — mini app backend
  reports.py         chiroyli Excel hisobot
  main.py            bot + web birga
web/
  student/teacher/admin/starosta/help/landing.html
  static/app.css, app.js
tests/test_security.py
```

## 9. Kengaytirish (keyingi funksiyalar uchun)

Yangi API endpoint → `app/api.py`, yangi jadval → `app/models.py`,
yangi bot buyrug'i → `app/bot.py`, yangi sahifa → `web/`.
Masalan qo'shish mumkin: davomat foizi reytingi, haftalik/oylik hisobot,
push eslatma, CSV import, bir necha fan, QR brightness animatsiyasi.

---
**Muallif:** @zafarx · CRTA (CyberWarfare Labs)
