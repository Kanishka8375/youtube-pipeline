"""Runtime configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict


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


def get_settings() -> Settings:
    return Settings()
