"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

#: Not a secret. Named so that it is obvious in a config dump.
INSECURE_DEV_SECRET = "insecure-development-secret-do-not-use-in-production"


@dataclass
class Settings:
    #: SQLite by default so the module runs with no infrastructure. Point at
    #: Postgres in any real deployment: the models use JSONB and native UUIDs
    #: there automatically.
    database_url: str = field(
        default_factory=lambda: os.getenv("ANIME_DATABASE_URL", "sqlite:///./anime_pipeline.db")
    )
    echo_sql: bool = field(
        default_factory=lambda: os.getenv("ANIME_ECHO_SQL", "").lower() in {"1", "true"}
    )
    #: Provider selection stays abstract; nothing is wired until you set it.
    providers: Dict[str, Any] = field(
        default_factory=lambda: {
            "llm": {"active": os.getenv("ANIME_LLM_PROVIDER") or None},
            "image": {"active": os.getenv("ANIME_IMAGE_PROVIDER") or None},
            "video": {"active": os.getenv("ANIME_VIDEO_PROVIDER") or None},
            "music": {"active": os.getenv("ANIME_MUSIC_PROVIDER") or None},
        }
    )
    default_frame_rate: float = field(
        default_factory=lambda: float(os.getenv("ANIME_FRAME_RATE", "24"))
    )

    #: Signs bearer tokens. The insecure default keeps `pytest` and a local
    #: `uvicorn` working with no setup; `require_production_secret` refuses it
    #: when ANIME_ENV says this is not a local machine, so the default cannot
    #: reach production by being forgotten.
    secret_key: str = field(
        default_factory=lambda: os.getenv("ANIME_SECRET_KEY", INSECURE_DEV_SECRET)
    )
    access_token_expire_minutes: int = field(
        default_factory=lambda: int(os.getenv("ANIME_TOKEN_TTL_MINUTES", "1440"))
    )
    environment: str = field(default_factory=lambda: os.getenv("ANIME_ENV", "local"))

    #: Where generated media lands. `local` needs no cloud account.
    storage_provider: str = field(
        default_factory=lambda: os.getenv("ANIME_STORAGE_PROVIDER", "local")
    )
    storage_root: str = field(
        default_factory=lambda: os.getenv("ANIME_STORAGE_ROOT", "./storage")
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod", "staging"}


class InsecureSecretError(RuntimeError):
    """Raised when a non-local deployment is still using the dev signing key."""


def require_production_secret(settings: "Settings") -> None:
    """Refuse to serve production traffic with the shipped signing key.

    Anyone holding this key can mint a token for any account. A default that
    works everywhere is exactly the kind that survives into production, so the
    check is a hard failure at startup rather than a warning in a log nobody
    reads.
    """
    if settings.is_production and settings.secret_key == INSECURE_DEV_SECRET:
        raise InsecureSecretError(
            f"ANIME_ENV={settings.environment!r} but ANIME_SECRET_KEY is still the "
            "development default. Set a real secret before serving traffic."
        )


def get_settings() -> Settings:
    return Settings()
