"""Kirish nuqtasi — bot (polling) va web server (uvicorn) birga ishlaydi."""
from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn

from app.api import app
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cyb3x")

_bot_task: asyncio.Task | None = None
_cleanup_task: asyncio.Task | None = None


@app.on_event("startup")
async def _start_bot():
    global _bot_task
    if not settings.bot_token or settings.bot_token.startswith("TEST"):
        log.warning("BOT_TOKEN o'rnatilmagan — faqat web server ishlaydi (bot o'chiq).")
        return
    if settings.use_webhook:
        from app.bot import setup_webhook
        try:
            await setup_webhook()
            log.info("Bot WEBHOOK rejimida (@%s) — shared hosting", settings.bot_username)
        except Exception as e:
            log.error("Webhook o'rnatilmadi: %s", e)
    else:
        from app.bot import run_bot
        _bot_task = asyncio.create_task(run_bot())
        log.info("Bot POLLING rejimida (@%s) — VPS/lokal", settings.bot_username)


@app.on_event("startup")
async def _start_cleanup():
    global _cleanup_task
    from app.cleanup import cleanup_loop
    _cleanup_task = asyncio.create_task(cleanup_loop())
    log.info("Avto-tozalash yoqildi — davomat %s kun saqlanadi", settings.retention_days)


@app.on_event("shutdown")
async def _stop_bot():
    for t in (_bot_task, _cleanup_task):
        if t:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
