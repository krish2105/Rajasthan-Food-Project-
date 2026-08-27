"""Application settings, loaded from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = ""

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "plate-photos"

    supabase_jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 3600

    # "rls": Storage calls carry the caller's JWT so Supabase Storage policies
    # are load-bearing. "service": fallback for projects that no longer expose a
    # legacy HS256 secret -- backend-mediated, app-level scope check only.
    # See docs/phase1-supabase-setup.md.
    storage_mode: Literal["rls", "service"] = "rls"

    seed_random_seed: int = 20260828
    seed_upload_photos: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def storage_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
