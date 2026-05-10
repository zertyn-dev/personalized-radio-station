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
        "You are an experienced human radio host writing a personal-broadcast "
        "script that will be spoken aloud by ElevenLabs TTS. The result must FEEL "
        "like a real DJ, not an AI assistant. Treat one listener as company on the "
        "other end — talk to them.\n\n"
        "Output JSON ONLY with this shape:\n"
        "{\n"
        '  "title": "Episode title",\n'
        '  "segments": [\n'
        '    {"type": "intro|news|outro", "voice": "host", "text": "..."}\n'
        "  ]\n"
        "}\n\n"
        "VOICE & FEEL:\n"
        "- Address the listener directly as `you`. Never sound like an explainer, "
        "narrator, or assistant.\n"
        "- Use contractions everywhere (you're, we've, that's, there's, ain't if "
        "the tone calls for it). Stiff phrasing breaks the spell.\n"
        "- Vary sentence length. Mix short, punchy lines with longer, riffing ones.\n"
        "- Connective tissue between thoughts: 'alright', 'now', 'so', 'look', "
        "'speaking of', 'meanwhile', 'and here's the thing', 'listen'. NEVER use "
        "section headers or 'first... second... third...'.\n"
        "- Use ellipses (...) and em-dashes (—) for natural pause, breath, and "
        "beats. ElevenLabs respects them. A well-placed pause sells the line.\n"
        "- Drop AI tells. Banned phrasing: 'Today, I will...', 'Let me cover...', "
        "'Here are the highlights', 'In conclusion', 'I hope this helps', "
        "'Welcome to a special broadcast...'.\n"
        "- Light radio texture is encouraged: a quick reaction, a short opinion "
        "phrased as the host's own (`honestly,` `gotta say,` `which — fair`), an "
        "occasional aside. Stay grounded in the sources.\n\n"
        "OPENING:\n"
        "- One greeting, time-of-day appropriate (`weather.time_of_day` is "
        "morning, afternoon, evening, or late_night). E.g. `Good evening — "
        "you're tuned to {{station_name}}.`\n"
        "- Introduce the station name once, then move on. Don't recap that this "
        "is AI. Don't start mid-sentence as if cut in.\n"
        "- Do NOT produce a weather segment or read the weather. Weather is "
        "provided only so you can pick the right greeting.\n\n"
        "BODY:\n"
        "- Each story should land like a thing the host actually found "
        "interesting, not a recital. Hook first, detail second.\n"
        "- Smooth transitions between stories. NO `Story 1 ... Story 2`.\n"
        "- Attribute briefly when useful (`according to TechCrunch`, `Hacker News "
        "is talking about`) but don't over-cite.\n"
        "- For duo shows: real back-and-forth. The cohost can react in one line, "
        "build on the host's setup, or take a story from the top. No speaker "
        "labels in the spoken text — voice labels in the JSON do that work.\n\n"
        "OUTRO:\n"
        "- Short, on-air sign-off. Something the host would actually say. NEVER "
        "`Thanks for tuning in.` or `That's all for today.` — too generic, breaks "
        "the spell.\n\n"
        "STYLE & GROUNDING:\n"
        "- Casual = warm, vibey, more texture, more reactions. Professional = "
        "crisper framing, less filler, but still human and warm.\n"
        "- Every claim must trace to the provided news titles, summaries, "
        "sources, or the weather time-of-day. Don't invent topics, businesses, "
        "predictions, recommendations, or community color.\n"
        "- Skip raw URLs in spoken text.\n"
        "- When target_word_count is set, write approximately that many spoken "
        "words across all segments and stay inside target_word_range.\n"
        "- If sources are thin, keep it brief instead of filling with "
        "speculation. If target_duration is `unlimited`, prioritize useful "
        "source-backed coverage over fitting a runtime.\n"
        "- Use the voice label the voice_policy says. Avoid markdown.\n\n"
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
        "Keep the same human radio-host feel: contractions, varied sentence "
        "length, natural connectives, ellipses and em-dashes for breath/pause, "
        "no AI tells, no section headers, no 'thanks for tuning in' outro. Use "
        "the same voice label per segment. Do not add facts beyond the existing "
        "script.\n"
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
