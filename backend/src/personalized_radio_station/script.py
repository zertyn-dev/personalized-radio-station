from __future__ import annotations

from datetime import datetime
import json

from .ai import generate_text, stream_text
from .config import AppConfig
from .news import NewsItem
from .timing import count_episode_words, effective_words_per_minute, word_budget
from .weather import WeatherReport


ApiKeys = dict[str, str]


def stream_script_segments(
    news_items: list[NewsItem],
    weather: WeatherReport,
    config: AppConfig,
    api_keys: ApiKeys | None = None,
):
    """Yield segment dicts as they appear in the streaming LLM output.

    Output format is NDJSON (one JSON object per line, no wrapping array).
    The first complete line yields the first segment as soon as the model
    finishes the line — usually 50-80 tokens after TTFT. Saves the 30-60
    tokens of `{"title": "...", "segments": [` envelope that nested-JSON
    output forced the model to emit before any segment could be yielded.

    Falls back to a full-buffer parse if the model emits a single nested
    JSON blob anyway (e.g. small models that ignore the format
    instruction or wrap the output in code fences).
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You write spoken-word radio scripts. Ground every substantive "
                "claim in the provided news context. Return ONE JSON object per "
                "line (NDJSON), no wrapping array, no preamble, no markdown."
            ),
        },
        {
            "role": "user",
            "content": _build_prompt(news_items, weather, config),
        },
    ]

    buffer = ""
    yielded = 0

    def parse_line(line: str) -> dict | None:
        """Parse a single line as a segment object. Returns None if it
        isn't a valid segment shape ({"type", "text"}). If it's the legacy
        envelope shape (`{title, segments: [...]}`) the caller can unwrap.
        """
        line = line.strip().rstrip(",").strip()
        if not line.startswith("{") or not line.endswith("}"):
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    def is_segment(obj: dict) -> bool:
        return "text" in obj and "type" in obj

    def unwrap_envelope(obj: dict):
        if isinstance(obj, dict) and isinstance(obj.get("segments"), list):
            for seg in obj["segments"]:
                if isinstance(seg, dict):
                    yield seg

    for chunk in stream_text(messages, config.ai, api_keys):
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            obj = parse_line(line)
            if obj is None:
                continue
            if is_segment(obj):
                yielded += 1
                yield obj
            else:
                # Legacy envelope on a single line — unwrap.
                for seg in unwrap_envelope(obj):
                    yielded += 1
                    yield seg

    obj = parse_line(buffer)
    if obj is not None:
        if is_segment(obj):
            yielded += 1
            yield obj
            return
        for seg in unwrap_envelope(obj):
            yielded += 1
            yield seg
        if yielded > 0:
            return

    # NDJSON path didn't produce anything — fall back to full-buffer parse.
    if yielded == 0:
        text = buffer.strip()
        if text.startswith("```"):
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for segment in data.get("segments", []):
                    yield segment
                return
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    for segment in data.get("segments", []):
                        yield segment
                    return
            except json.JSONDecodeError:
                pass


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
        "You are a human radio DJ writing the live spoken portion of a show "
        "for ElevenLabs TTS. A short pre-recorded station ID for "
        f"{config.station_name} just played (e.g. `Welcome to "
        f"{config.station_name}.`); you pick up the mic from there.\n\n"
        "OUTPUT FORMAT (NDJSON, ONE OBJECT PER LINE, NO ARRAY, NO MARKDOWN):\n"
        '{"type": "news", "voice": "host", "text": "..."}\n'
        '{"type": "news", "voice": "host", "text": "..."}\n'
        '{"type": "outro", "voice": "host", "text": "..."}\n\n'
        "RULES:\n"
        "- One `news` segment per item in `news[]`, in order. Final segment "
        "is `outro`. No `intro` segment — the station ID already played.\n"
        "- First news line is a natural DJ roll-in (e.g. `Alright — first "
        "story tonight comes from TechCrunch…`, `Kicking things off over at "
        "Hacker News…`). DO NOT say 'welcome' or repeat the station name.\n"
        "- Smooth transitions from segment 2 onward: 'speaking of which', "
        "'meanwhile', 'now this next one', 'over at [source]'.\n"
        "- Hook first, source attribution second, story unpacked. Use source "
        "names when they add credibility, never raw URLs.\n"
        "- EVERY claim must trace to a provided news item. No invented "
        "stories, stats, predictions, businesses, or weather report.\n"
        "- Outro: in-character sign-off. NEVER 'Thanks for tuning in' or "
        "'That's all for today' — too generic. Leave an infinite-show feel.\n\n"
        "VOICE:\n"
        "- Direct `you` address. Contractions everywhere. Vary sentence "
        "length. Use `...` and em-dashes (—) for breath/pause; ElevenLabs "
        "respects them.\n"
        "- Banned AI tells: 'Today, I will…', 'Let me cover…', 'Here are the "
        "highlights', 'In conclusion'.\n"
        "- Casual = warm/vibey/more texture; professional = crisp/less filler.\n"
        "- Duo: real back-and-forth, no speaker labels in spoken text — the "
        "JSON `voice` field handles that.\n\n"
        "WRITE FOR THE EAR:\n"
        "- Spell numbers/dates/currency how a human SAYS them: `2026` → "
        "`twenty twenty-six`, `$1.2M` → `one point two million dollars`, "
        "`90%` → `ninety percent`, `Q3` → `the third quarter`.\n"
        "- Letter acronyms stay caps (FBI, NASA, AI). Word acronyms become "
        "words (`captcha`).\n"
        "- Comma-pause where a person would breathe. Sparing natural fillers "
        "(`you know`, `I mean`, `right`) — at most one per minute.\n\n"
        "LENGTH:\n"
        "- Hit `target_word_count` across all your segments. Stay inside "
        "`target_word_range`. News ~85–95% of budget, outro ~5–10%. Better "
        "slightly under than over. Don't pad.\n\n"
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
