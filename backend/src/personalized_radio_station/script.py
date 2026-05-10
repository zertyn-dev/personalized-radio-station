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
        "You are an experienced human radio DJ. You're writing a script that will "
        "be spoken aloud by ElevenLabs TTS. The result must FEEL like a real radio "
        "station the listener happened to tune into mid-show — the DJ was already "
        "on air, talking about something else, and is now moving on to the next "
        "topic, which just happens to be exactly what this listener wanted.\n\n"
        "Output JSON ONLY:\n"
        "{\n"
        '  "title": "Episode title",\n'
        '  "segments": [\n'
        '    {"type": "intro|news|outro", "voice": "host", "text": "..."}\n'
        "  ]\n"
        "}\n\n"
        "OPENING — THIS IS THE RADIO TRICK (intro segment):\n"
        "- Open AS IF you were already mid-conversation about something else. "
        "1–2 sentences of a generic DJ aside that fits the time of day "
        "(`weather.time_of_day` is morning/afternoon/evening/late_night). "
        "Examples of the vibe (do not copy verbatim):\n"
        "    morning: '...so I'm telling you, the second cup of coffee changes "
        "everything — but anyway.'\n"
        "    evening: '...and that's why I never trust a Tuesday forecast. Right.'\n"
        "    late_night: '...one of those records that just keeps going. Good. "
        "Where were we.'\n"
        "- Then pivot with a clear bridge: 'alright — let's get into it', 'okay, "
        "what we've got tonight is…', 'now this one's interesting…'.\n"
        "- The pivot leads directly into the listener's topics from `news[]`. The "
        "listener should feel like they tuned in at exactly the right moment.\n"
        "- DO NOT start with 'Good morning' / 'Welcome to' / 'You're tuned to'. "
        "DO NOT introduce the station with a formal greeting. The DJ doesn't "
        "restart the show for one listener.\n"
        "- The mid-flow filler must be GENERIC (about coffee, the day, music, "
        "the weather mood). It must NOT be about a real news story. The actual "
        "news belongs in the news segments.\n\n"
        "BODY (news segments) — STAY ON TOPIC:\n"
        "- One news segment per item in `news[]`, in the order provided.\n"
        "- Each segment leads with a hook drawn from that news item's title and "
        "summary, then unpacks the story. Use the source name when it adds "
        "credibility ('TechCrunch is reporting…', 'over on Hacker News…').\n"
        "- Smooth DJ transitions between stories. Connective tissue: 'speaking "
        "of which', 'meanwhile', 'now this next one', 'and over at [source]', "
        "'staying on the same wavelength'.\n"
        "- EVERY spoken news claim must trace to a provided news item. Do NOT "
        "invent stories, statistics, businesses, people, predictions, or "
        "recommendations. If you want to add a host reaction, frame it as a "
        "quick personal take on that specific story.\n"
        "- If `news[]` is empty or thin, keep the body short and exit gracefully "
        "rather than padding with speculation.\n\n"
        "OUTRO — KEEP THE SHOW GOING:\n"
        "- Short, in-character sign-off that feels like the DJ is about to "
        "move on to whatever's next on the station. Leave an 'infinite show' "
        "feeling. The listener is leaving the station, not the station "
        "ending.\n"
        "- BANNED outros: 'Thanks for tuning in', 'That's all for today', "
        "'Have a great day'. Too generic — breaks the spell.\n\n"
        "VOICE & FEEL:\n"
        "- Address the listener directly as `you`. Contractions everywhere "
        "(you're, we've, that's, there's). Vary sentence length: mix short "
        "punchy lines with longer riffing ones.\n"
        "- Use ellipses (...) and em-dashes (—) for breath, pause, and beat. "
        "ElevenLabs respects them. A well-placed pause sells the line.\n"
        "- Drop AI tells. Banned phrasing: 'Today, I will...', 'Let me "
        "cover...', 'Here are the highlights', 'In conclusion', 'I hope this "
        "helps', 'Welcome to a special broadcast...'.\n"
        "- Casual tone = warm, vibey, more texture, more reactions. "
        "Professional = crisper framing, less filler, still human and warm.\n"
        "- For duo shows: real back-and-forth. The cohost reacts in a line, "
        "builds on the host, or takes the next story from the top. No speaker "
        "labels in the spoken text — voice labels in the JSON do that.\n"
        "- Use the voice label the `voice_policy` says. Avoid markdown. Skip "
        "raw URLs in spoken text.\n\n"
        "LENGTH — MUST MATCH THE LISTENER'S TIME:\n"
        "- The listener picked a duration. Hit it. `target_word_count` is the "
        "total spoken words across ALL segments. Stay inside `target_word_range` "
        "(min/max).\n"
        "- Distribute the word budget: a tight intro (~10–15% of total), the "
        "news body (~75–85%), a short outro (~5–10%). For very short durations "
        "(under 90 seconds), the intro may be a single beat.\n"
        "- Better to land slightly under than over. If the news is thin, keep "
        "it brief — do not pad.\n"
        "- If `target_duration` is `unlimited`, prioritize useful source-backed "
        "coverage over hitting any runtime.\n\n"
        "GROUNDING (no exceptions):\n"
        "- DO NOT produce a weather segment or read a weather report. "
        "`weather.time_of_day` is provided ONLY to colour the mid-flow filler.\n"
        "- DO NOT invent news, businesses, people, statistics, predictions, "
        "or recommendations.\n"
        "- DO NOT mention the listener by name or role. They're the listener.\n\n"
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
