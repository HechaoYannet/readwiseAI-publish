"""Application runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    cors_allowed_origins: list[str]
    cors_allow_credentials: bool


def load_settings() -> Settings:
    raw_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
    return Settings(
        cors_allowed_origins=_split_csv(raw_origins),
        cors_allow_credentials=allow_credentials,
    )

