"""cPanel / shared hosting (Phusion Passenger) kirish nuqtasi.

cPanel "Setup Python App" shu faylni topadi va `application` ni ishga tushiradi.
FastAPI (ASGI) ni a2wsgi orqali WSGI ga o'raymiz.

Eslatma: shared hosting'da .env ni USE_WEBHOOK=true qiling (polling ishlamaydi).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from a2wsgi import ASGIMiddleware  # noqa: E402
from app.api import app as asgi_app  # noqa: E402

application = ASGIMiddleware(asgi_app)
