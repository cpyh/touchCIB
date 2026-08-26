from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "智能财富管理运营平台 API")
    app_env: str = os.getenv("APP_ENV", "development")
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "touch_cib")
    db_connect_timeout: int = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
    profile_as_of_date: date = date.fromisoformat(
        os.getenv("PROFILE_AS_OF_DATE", "2026-03-31")
    )
    cors_origins: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        ).split(",")
        if value.strip()
    )
    ai_summary_mode: str = os.getenv("AI_SUMMARY_MODE", "template").lower()
    ai_api_url: str | None = os.getenv("AI_API_URL")
    ai_api_key: str | None = os.getenv("AI_API_KEY")
    ai_model: str = os.getenv("AI_MODEL", "")
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))


settings = Settings()
