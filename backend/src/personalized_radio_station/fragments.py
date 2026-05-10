"""Pre-rendered intro and bridge audio fragments.

The full episode pipeline (news fetch + LLM + per-segment TTS) takes
~10–20 seconds before the listener hears anything. To make PLAY feel
instant, we render a small library of short, generic spoken fragments
once per voice and cache them on disk. Each episode picks an intro
fragment + 1–2 bridge fragments at random, plays them while the LLM
generates the actual news body, and only then plays the news.

Design constraints:
- Fragments must use the SAME voice as the rest of the episode — radio
  feel breaks if the intro voice differs from the news voice. The voice
  is resolved from `config.tts.primary_voice`.
- Templates are station-name agnostic. The station name is user-defined
  and varies per request, so we keep fragments generic and let the
  news segments mention the station inline if useful.
- Cache is shared across episodes (keyed by voice id + voice settings
  hash + text hash), so the first episode for a given voice pays the
  TTS cost once; every subsequent episode for that voice is instant.
"""

from __future__ import annotations

from pathlib import Path
from random import Random
from typing import Any
import hashlib
import json

from .config import AppConfig, TtsVoiceConfig
from .tts import (
    ApiKeys,
    _extension_for_provider,
    _resolve_voice,
    _slug,
    _synthesize_litellm_speech,
    _synthesize_mock,
    _synthesize_piper,
)


# Intros include the station name via the {station} placeholder. They're
# rendered to audio AFTER substitution (so the cache key includes the
# specific station name), giving each station its own pre-rendered
# welcome — exactly how a real station has a recorded ID.
INTRO_TEMPLATES: list[str] = [
    "Welcome to {station}.",
    "Welcome to {station} — glad you're with us.",
    "You're listening to {station}.",
    "You're tuned to {station}.",
    "This is {station}. Good to have you here.",
    "Welcome back to {station}.",
]

# Time-of-day flavored intros. Picked when weather.time_of_day is set.
INTRO_BY_TIME: dict[str, list[str]] = {
    "morning": [
        "Good morning. You're listening to {station}.",
        "Good morning, and welcome to {station}.",
        "Morning. This is {station}.",
    ],
    "afternoon": [
        "Good afternoon. You're listening to {station}.",
        "Good afternoon, and welcome to {station}.",
    ],
    "evening": [
        "Good evening. You're listening to {station}.",
        "Good evening, and welcome to {station}.",
        "Evening. This is {station}.",
    ],
    "late_night": [
        "Late-night listener — welcome to {station}.",
        "Welcome to {station}. Glad to have you up with us.",
    ],
}

# Bridge templates left in place but not used by default. The previous
# set ('Setting up the wires', etc.) didn't sound like real radio. If we
# revisit gap-filling later, replace these with naturalistic vamping.
BRIDGE_TEMPLATES: list[str] = []


def _settings_hash(voice: TtsVoiceConfig, model: str) -> str:
    blob = json.dumps(
        {
            "model": model,
            "voice": voice.voice,
            "speed": voice.speed,
            "instructions": voice.instructions,
            "settings": voice.settings,
        },
        sort_keys=True,
    )
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:10]


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:10]


def fragment_path(
    cache_dir: Path,
    voice: TtsVoiceConfig,
    model: str,
    text: str,
    ext: str,
) -> Path:
    return cache_dir / (
        f"{_slug(voice.voice)[:32]}_{_settings_hash(voice, model)}_{_text_hash(text)}.{ext}"
    )


def get_or_render_fragment(
    text: str,
    voice: TtsVoiceConfig,
    config: AppConfig,
    api_keys: ApiKeys | None,
    cache_dir: Path,
) -> Path:
    """Return a cached audio file for (voice, settings, text), rendering
    via the configured TTS provider if not yet cached.
    """
    provider = config.tts.provider.lower()
    ext = _extension_for_provider(provider, config.tts.response_format)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = fragment_path(cache_dir, voice, config.tts.model, text, ext)
    if path.exists() and path.stat().st_size > 0:
        return path

    if provider == "mock":
        _synthesize_mock(text, voice.voice, path)
    elif provider in {"elevenlabs", "litellm", "openai"}:
        _synthesize_litellm_speech(text, voice, config, path, api_keys)
    elif provider == "piper":
        _synthesize_piper(text, voice, config, path)
    else:
        raise ValueError(
            f"Unsupported TTS provider for fragments: {config.tts.provider}"
        )
    return path


def pick_intro_text(station_name: str, time_of_day: str | None, rng: Random) -> str:
    """Pick an intro template and substitute the station name."""
    pool = list(INTRO_TEMPLATES)
    if time_of_day:
        pool.extend(INTRO_BY_TIME.get(time_of_day, []))
    template = rng.choice(pool)
    name = (station_name or "VibeFM").strip() or "VibeFM"
    return template.format(station=name)


def prepare_fragment_segments(
    config: AppConfig,
    time_of_day: str | None,
    api_keys: ApiKeys | None,
    cache_dir: Path,
    audio_dir: Path,
    episode_dir: Path,
    rng: Random,
) -> list[tuple[dict[str, Any], Path]]:
    """Render the intro fragment using the host voice and the user's
    station name. The fragment is copied into the episode's audio
    directory and returned with its segment metadata.
    """
    primary_voice_name = config.tts.primary_voice or "host"
    voice_name, voice = _resolve_voice(primary_voice_name, config)
    provider = config.tts.provider.lower()
    ext = _extension_for_provider(provider, config.tts.response_format)
    audio_dir.mkdir(parents=True, exist_ok=True)

    intro_text = pick_intro_text(config.station_name, time_of_day, rng)

    out: list[tuple[dict[str, Any], Path]] = []
    cached = get_or_render_fragment(intro_text, voice, config, api_keys, cache_dir)
    target = audio_dir / f"00-intro.{ext}"
    target.write_bytes(cached.read_bytes())
    segment = {
        "type": "intro",
        "voice": voice_name,
        "text": intro_text,
        "audio_file": str(target.relative_to(episode_dir)),
    }
    out.append((segment, target))
    return out
