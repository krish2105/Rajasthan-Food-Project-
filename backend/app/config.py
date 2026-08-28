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

    # --- Phase 2: AI pipeline (Section 4, zero-paid-API constraint) --------
    # "mock" is the default on purpose: nothing should spend free-tier quota by
    # accident, and CI must never depend on a live rate-limited endpoint.
    ai_provider: Literal["mock", "gemini", "groq"] = "mock"
    ai_vision_model: str = "gemini/gemini-2.0-flash"
    ai_text_model: str = "groq/llama-3.3-70b-versatile"
    #: Master switch. When false, captures are stored and left 'pending' exactly
    #: as they were in Phase 1 -- the Section 7 guarantee that capture never
    #: depends on inference.
    ai_enabled: bool = True
    #: Read by LiteLLM from the environment; declared here so a missing key is a
    #: startup-visible configuration fact rather than a runtime surprise.
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # --- Phase 6: authentication (Sections 4, 10, 11) ----------------------
    # "console" is the default so nothing spends SMS credits by accident and CI
    # never depends on a third party being reachable.
    otp_provider: Literal["console", "msg91"] = "console"
    msg91_authkey: str = ""
    msg91_template_id: str = ""
    msg91_sender: str = ""
    #: Section 11's short-lived access token. The device holds a 30-day refresh
    #: token so the Field PWA survives days offline (Section 7).
    refresh_ttl_days: int = 30

    seed_random_seed: int = 20260828
    seed_upload_photos: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def otp_configured(self) -> bool:
        if self.otp_provider == "console":
            return True
        return bool(self.msg91_authkey and self.msg91_template_id)

    @property
    def ai_configured(self) -> bool:
        """Whether the selected provider actually has what it needs."""
        if self.ai_provider == "mock":
            return True
        if self.ai_provider == "gemini":
            return bool(self.gemini_api_key)
        return bool(self.groq_api_key)

    @property
    def storage_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
