from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import json
import re
import secrets
import sqlite3
import threading

from .hosts import host_style


PRESET_RSS_SOURCES: dict[str, dict[str, str]] = {
    "google_news": {
        "label": "Google News",
        "url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    },
    "hacker_news": {
        "label": "Hacker News",
        "url": "https://hnrss.org/frontpage",
    },
    "techcrunch": {
        "label": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
    },
    "product_hunt": {
        "label": "Product Hunt",
        "url": "https://www.producthunt.com/feed",
    },
}

DEFAULT_SOURCE_PRESET_IDS = tuple(PRESET_RSS_SOURCES)

_PRESET_ALIASES = {
    "google": "google_news",
    "google_news": "google_news",
    "googlenews": "google_news",
    "hn": "hacker_news",
    "hackernews": "hacker_news",
    "hacker_news": "hacker_news",
    "techcrunch": "techcrunch",
    "tech_crunch": "techcrunch",
    "producthunt": "product_hunt",
    "product_hunt": "product_hunt",
}
_TONES = {"casual", "professional"}
_VOICE_GENDERS = {"male", "female"}
_HOST_FORMATS = {"solo", "duo"}


@dataclass(frozen=True)
class Vibe:
    id: str
    name: str
    source_preset_ids: list[str]
    custom_rss_feeds: list[str]
    tone: str
    voice_gender: str
    host_format: str
    created_at: str
    updated_at: str

    @property
    def rss_feeds(self) -> list[str]:
        preset_feeds = [
            PRESET_RSS_SOURCES[preset_id]["url"]
            for preset_id in self.source_preset_ids
            if preset_id in PRESET_RSS_SOURCES
        ]
        return _dedupe_strings([*preset_feeds, *self.custom_rss_feeds])

    @property
    def style(self) -> str:
        return host_style(self.tone, self.voice_gender, self.host_format)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_preset_ids": self.source_preset_ids,
            "source_presets": [
                {"id": preset_id, **PRESET_RSS_SOURCES[preset_id]}
                for preset_id in self.source_preset_ids
                if preset_id in PRESET_RSS_SOURCES
            ],
            "custom_rss_feeds": self.custom_rss_feeds,
            "rss_feeds": self.rss_feeds,
            "tone": self.tone,
            "voice_gender": self.voice_gender,
            "host_format": self.host_format,
            "host": {
                "tone": self.tone,
                "voice_gender": self.voice_gender,
                "format": self.host_format,
            },
            "style": self.style,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class VibeStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    def preset_sources(self) -> list[dict[str, str]]:
        return [
            {"id": preset_id, **source}
            for preset_id, source in PRESET_RSS_SOURCES.items()
        ]

    def list_vibes(self) -> list[Vibe]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, name, source_preset_ids, custom_rss_feeds, tone,
                       voice_gender, host_format, created_at, updated_at
                FROM vibes
                ORDER BY created_at DESC, name COLLATE NOCASE
                """
            ).fetchall()
        return [_row_to_vibe(row) for row in rows]

    def get_vibe(self, vibe_id: str) -> Vibe | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT id, name, source_preset_ids, custom_rss_feeds, tone,
                       voice_gender, host_format, created_at, updated_at
                FROM vibes
                WHERE id = ?
                """,
                (vibe_id,),
            ).fetchone()
        return _row_to_vibe(row) if row else None

    def create_vibe(self, payload: dict[str, Any]) -> Vibe:
        name = _clean_name(payload.get("name", payload.get("station_name")))
        custom_rss_feeds = _clean_rss_feeds(
            payload.get("custom_rss_feeds", payload.get("rss_feeds", payload.get("rss")))
        )
        preset_value = payload.get(
            "source_preset_ids",
            payload.get("source_presets", payload.get("preset_sources")),
        )
        source_preset_ids = (
            _clean_preset_ids(preset_value)
            if preset_value is not None
            else list(DEFAULT_SOURCE_PRESET_IDS)
        )

        now = _now()
        vibe = Vibe(
            id=_new_vibe_id(name),
            name=name,
            source_preset_ids=source_preset_ids,
            custom_rss_feeds=custom_rss_feeds,
            tone=_clean_choice(payload.get("tone"), _TONES, "casual", "tone"),
            voice_gender=_clean_choice(
                payload.get("voice_gender", payload.get("gender")),
                _VOICE_GENDERS,
                "female",
                "voice_gender",
            ),
            host_format=_clean_choice(
                payload.get("host_format", payload.get("format")),
                _HOST_FORMATS,
                "solo",
                "host_format",
            ),
            created_at=now,
            updated_at=now,
        )

        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO vibes (
                    id, name, source_preset_ids, custom_rss_feeds, tone,
                    voice_gender, host_format, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vibe.id,
                    vibe.name,
                    _encode_json(vibe.source_preset_ids),
                    _encode_json(vibe.custom_rss_feeds),
                    vibe.tone,
                    vibe.voice_gender,
                    vibe.host_format,
                    vibe.created_at,
                    vibe.updated_at,
                ),
            )
        return vibe

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS vibes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_preset_ids TEXT NOT NULL,
                    custom_rss_feeds TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    voice_gender TEXT NOT NULL,
                    host_format TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db


def _row_to_vibe(row: sqlite3.Row) -> Vibe:
    return Vibe(
        id=str(row["id"]),
        name=str(row["name"]),
        source_preset_ids=_decode_list(row["source_preset_ids"]),
        custom_rss_feeds=_decode_list(row["custom_rss_feeds"]),
        tone=str(row["tone"]),
        voice_gender=str(row["voice_gender"]),
        host_format=str(row["host_format"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _clean_name(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError("Vibe name is required.")
    return text[:80]


def _clean_preset_ids(value: Any) -> list[str]:
    values = _string_values(value)
    preset_ids: list[str] = []
    invalid: list[str] = []
    for raw in values:
        normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
        preset_id = _PRESET_ALIASES.get(normalized)
        if not preset_id:
            invalid.append(raw)
            continue
        preset_ids.append(preset_id)

    if invalid:
        valid = ", ".join(source["label"] for source in PRESET_RSS_SOURCES.values())
        raise ValueError(f"Unknown preset source: {', '.join(invalid)}. Valid presets: {valid}.")

    return _dedupe_strings(preset_ids)


def _clean_rss_feeds(value: Any) -> list[str]:
    feeds: list[str] = []
    for raw in _string_values(value):
        if urlparse(raw).scheme.lower() not in {"http", "https"}:
            raise ValueError(f"RSS feed must start with http:// or https://: {raw}")
        feeds.append(raw)
    return _dedupe_strings(feeds)


def _clean_choice(value: Any, allowed: set[str], fallback: str, field_name: str) -> str:
    text = str(value).strip().lower() if value is not None else ""
    if not text:
        return fallback
    if text not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {choices}.")
    return text


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _encode_json(values: list[str]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _decode_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _new_vibe_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "vibe"
    return f"{slug[:32]}-{secrets.token_hex(3)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
