#!/usr/bin/env bash
# Lokal ishga tushirish (test uchun)
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  .env yaratildi — BOT_TOKEN, SUPER_ADMIN_ID, PUBLIC_URL ni to'ldiring!"
fi

echo "🚀 Ishga tushmoqda: http://localhost:8080"
python -m app.main
