"""Konfiguratsiya — barcha sozlamalar .env dan o'qiladi."""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = "TEST:TOKEN"
    bot_username: str = "cyb3xbot"
    super_admin_id: int = 0
    public_url: str = "http://localhost:8080"
    secret_key: str = "dev-secret-change-me"

    campus_lat: float = 41.3480
    campus_lon: float = 69.2910
    campus_radius_m: int = 30

    token_ttl_seconds: int = 8
    port: int = 8080
    database_url: str = "sqlite+aiosqlite:///./cyb3x.db"

    @property
    def rp_id(self) -> str:
        """WebAuthn Relying Party ID — domen (portsiz, sxemasiz). Face ID shu domenga bog'lanadi."""
        host = urlparse(self.public_url).hostname or "localhost"
        return host

    @property
    def rp_name(self) -> str:
        return "CYB3X Davomat"

    @property
    def origin(self) -> str:
        """WebAuthn origin — to'liq sxema+host (+port)."""
        return self.public_url.rstrip("/")


settings = Settings()
