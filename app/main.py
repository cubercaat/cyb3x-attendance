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


@app.on_event("startup")
async def _start_bot():
    global _bot_task
    if settings.bot_token and not settings.bot_token.startswith("TEST"):
        from app.bot import run_bot
        _bot_task = asyncio.create_task(run_bot())
        log.info("Bot polling ishga tushdi (@%s)", settings.bot_username)
    else:
        log.warning("BOT_TOKEN o'rnatilmagan — faqat web server ishlaydi (bot o'chiq).")


@app.on_event("shutdown")
async def _stop_bot():
    if _bot_task:
        _bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _bot_task


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
