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


# Generic intros, station-name free. Short (1 sentence), TTS-friendly.
INTRO_TEMPLATES: list[str] = [
    "You're tuned in. Welcome back.",
    "Glad you're here. Let's roll.",
    "Settle in — we're rolling.",
    "Hey there. Welcome back to the show.",
    "We're back on. Glad you joined.",
    "Welcome back to the broadcast.",
    "You're with us. Let's get into it.",
]

# Time-of-day flavored intros. Picked from when weather.time_of_day is set.
INTRO_BY_TIME: dict[str, list[str]] = {
    "morning": [
        "Good morning. Glad you joined us.",
        "Morning, everyone. Let's get going.",
        "Good morning — settle in.",
    ],
    "afternoon": [
        "Good afternoon. Welcome back to the show.",
        "Hey there. Good to have you this afternoon.",
        "Afternoon — glad you're here.",
    ],
    "evening": [
        "Good evening. Welcome in.",
        "Evening, all. Glad you joined.",
        "Good evening — let's roll.",
    ],
    "late_night": [
        "Late-night listener — welcome.",
        "Glad you joined us tonight.",
        "Welcome — good to have you up with us.",
    ],
}

# Bridge fillers — short, neutral. Chained between intro and the LLM
# news body to cover the LLM's generation latency without dead air.
BRIDGE_TEMPLATES: list[str] = [
    "Putting tonight's lineup together for you...",
    "Hang tight, we're queuing up the stories.",
    "Just a moment — dialing in the latest.",
    "Setting up the wires. Almost there.",
    "Pulling the threads — back in a beat.",
    "Sorting through the wire. Won't be long.",
]


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


def pick_intro_text(time_of_day: str | None, rng: Random) -> str:
    pool = list(INTRO_TEMPLATES)
    if time_of_day:
        pool.extend(INTRO_BY_TIME.get(time_of_day, []))
    return rng.choice(pool)


def pick_bridge_texts(count: int, rng: Random) -> list[str]:
    if count <= 0:
        return []
    pool = list(BRIDGE_TEMPLATES)
    if count >= len(pool):
        return rng.sample(pool, k=len(pool))
    return rng.sample(pool, k=count)


def prepare_fragment_segments(
    config: AppConfig,
    time_of_day: str | None,
    api_keys: ApiKeys | None,
    cache_dir: Path,
    audio_dir: Path,
    episode_dir: Path,
    rng: Random,
    bridge_count: int = 1,
) -> list[tuple[dict[str, Any], Path]]:
    """Render the intro + bridge fragments using the host voice, copy
    them into the episode's audio directory, and return the (segment_dict,
    audio_path) tuples in playback order.
    """
    primary_voice_name = config.tts.primary_voice or "host"
    voice_name, voice = _resolve_voice(primary_voice_name, config)
    provider = config.tts.provider.lower()
    ext = _extension_for_provider(provider, config.tts.response_format)
    audio_dir.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[str, str]] = [("intro", pick_intro_text(time_of_day, rng))]
    for text in pick_bridge_texts(bridge_count, rng):
        plan.append(("bridge", text))

    out: list[tuple[dict[str, Any], Path]] = []
    for index, (kind, text) in enumerate(plan):
        cached = get_or_render_fragment(text, voice, config, api_keys, cache_dir)
        target = audio_dir / f"{index:02d}-{kind}.{ext}"
        target.write_bytes(cached.read_bytes())
        segment = {
            "type": kind,
            "voice": voice_name,
            "text": text,
            "audio_file": str(target.relative_to(episode_dir)),
        }
        out.append((segment, target))
    return out
