from __future__ import annotations

from datetime import datetime
import json

from .ai import generate_text
from .config import AppConfig
from .news import NewsItem
from .timing import count_episode_words, effective_words_per_minute, word_budget
from .weather import WeatherReport


ApiKeys = dict[str, str]


def generate_script(
    news_items: list[NewsItem],
    weather: WeatherReport,
    config: AppConfig,
    api_keys: ApiKeys | None = None,
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a radio producer writing spoken-word scripts. "
                "Ground every substantive claim in the provided news and weather context. "
                "Return valid JSON only."
            ),
        },
        {
            "role": "user",
            "content": _build_prompt(news_items, weather, config),
        },
    ]

    raw = generate_text(messages, config.ai, api_keys)
    episode = _parse_episode(raw)
    return _maybe_revise_for_word_budget(episode, config, api_keys)


def render_markdown(episode: dict) -> str:
    lines = [f"# {episode.get('title', 'VibeFM Briefing')}", ""]

    for segment in episode.get("segments", []):
        segment_type = segment.get("type", "segment").title()
        voice = segment.get("voice", "host")
        text = segment.get("text", "").strip()
        lines.extend([f"## {segment_type} ({voice})", "", text, ""])

    return "\n".join(lines).strip() + "\n"


def _build_prompt(
    news_items: list[NewsItem], weather: WeatherReport, config: AppConfig
) -> str:
    budget = word_budget(config)
    context = {
        "station_name": config.station_name,
        "style": config.style,
        "target_duration": config.duration.label,
        "target_minutes": config.duration.minutes,
        "speech_rate_words_per_minute": effective_words_per_minute(config),
        "target_word_count": budget.target_words if budget else None,
        "target_word_range": (
            {"min": budget.min_words, "max": budget.max_words} if budget else None
        ),
        "voices": config.voices,
        "host_format": "solo" if config.tts.single_voice else "duo",
        "voice_policy": (
            f'Use the voice label "{config.tts.primary_voice}" for every segment.'
            if config.tts.single_voice
            else (
                "Use only the configured voice labels. Follow the voices map by "
                "segment type, with natural host/cohost handoffs."
            )
        ),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weather": weather.to_dict(),
        "news": [item.to_dict() for item in news_items],
    }

    return (
        "Create a VibeFM episode script.\n"
        "Output JSON with this shape:\n"
        "{\n"
        '  "title": "Episode title",\n'
        '  "segments": [\n'
        '    {"type": "intro|news|outro", "voice": "host", "text": "..."}\n'
        "  ]\n"
        "}\n\n"
        "Open with a clean station greeting that fits the listener's local time of "
        "day. When `weather.time_of_day` is provided (morning, afternoon, evening, "
        "late_night), match the greeting to it (e.g. `Good morning` only in the "
        "morning). Do not start mid-thought or as if the host was already talking. "
        "Introduce the station and move directly into the briefing. "
        "Do NOT produce a weather segment or read a weather report. The weather "
        "context is provided only so you can pick the right greeting.\n"
        "Follow style closely: casual should feel more like vibes and texture; "
        "professional should feel slightly more expert, with concise context and "
        "clear framing. Use the same voice label for every segment when the "
        "voice_policy says so. For duo shows, use host/cohost handoffs without "
        "writing speaker names into the spoken text. "
        "When target_word_count is provided, write approximately that many spoken "
        "words across all segment text and stay inside target_word_range. "
        "Keep it natural for TTS. Avoid markdown. Mention source names when useful, "
        "but do not include raw URLs in the spoken text.\n"
        "Grounding rules: every news claim must be supported by the provided news "
        "titles, summaries, source names, or weather fields. You may add short "
        "transitions, pacing phrases, and light radio texture, but do not add new "
        "topics, examples, local businesses, recommendations, predictions, or "
        "community color that are not present in the context. If the sources are "
        "thin, keep the script brief instead of filling with speculation. If "
        "target_duration is `unlimited`, prioritize useful source-backed coverage "
        "over fitting a fixed runtime.\n\n"
        f"Context:\n{json.dumps(context, indent=2)}"
    )


def _parse_episode(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass

    return {
        "title": "VibeFM Briefing",
        "segments": [{"type": "script", "voice": "host", "text": raw.strip()}],
    }


def _maybe_revise_for_word_budget(
    episode: dict, config: AppConfig, api_keys: ApiKeys | None = None
) -> dict:
    budget = word_budget(config)
    if not budget:
        _set_word_budget_metadata(episode, revised=False, reason="unlimited_duration")
        return episode

    word_count = count_episode_words(episode)
    if budget.min_words <= word_count <= budget.max_words:
        _set_word_budget_metadata(
            episode,
            revised=False,
            reason="within_range",
            initial_word_count=word_count,
        )
        return episode

    revised_raw = generate_text(
        [
            {
                "role": "system",
                "content": (
                    "You revise radio scripts for length. Return valid JSON only. "
                    "Preserve the same sources, facts, voice labels, and JSON shape."
                ),
            },
            {
                "role": "user",
                "content": _build_revision_prompt(episode, word_count, budget, config),
            },
        ],
        config.ai,
        api_keys,
    )
    revised_episode = _parse_episode(revised_raw)
    revised_word_count = count_episode_words(revised_episode)
    _set_word_budget_metadata(
        revised_episode,
        revised=True,
        reason=_revision_reason(word_count, budget),
        initial_word_count=word_count,
        revised_word_count=revised_word_count,
    )
    return revised_episode


def _build_revision_prompt(
    episode: dict, word_count: int, budget, config: AppConfig
) -> str:
    direction = "expand" if word_count < budget.min_words else "trim"
    return (
        f"The script is {word_count} words, outside the target range of "
        f"{budget.min_words}-{budget.max_words} words for {config.duration.label}.\n"
        f"Please {direction} it to approximately {budget.target_words} spoken words.\n"
        "Keep the same opening greeting style. Use the same voice label for "
        "every segment when present. Do not add facts beyond the existing script.\n"
        "Return valid JSON only with the same shape.\n\n"
        f"Current episode JSON:\n{json.dumps(episode, indent=2)}"
    )


def _revision_reason(word_count: int, budget) -> str:
    if word_count < budget.min_words:
        return "too_short"
    if word_count > budget.max_words:
        return "too_long"
    return "within_range"


def _set_word_budget_metadata(
    episode: dict,
    revised: bool,
    reason: str,
    initial_word_count: int | None = None,
    revised_word_count: int | None = None,
) -> None:
    generation = episode.setdefault("generation", {})
    generation["word_budget_revision"] = {
        "revised": revised,
        "reason": reason,
        "initial_word_count": initial_word_count,
        "revised_word_count": revised_word_count,
    }
