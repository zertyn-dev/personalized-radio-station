from __future__ import annotations

from dataclasses import replace

from .config import AppConfig, TtsVoiceConfig


TONE_STYLES = {
    "casual": (
        "casual, vibe-forward, loose but useful radio with warm pacing, quick "
        "reactions, and a little texture between source-backed facts"
    ),
    "professional": (
        "professional, slightly more expert radio with crisp framing, clear "
        "context, and confident analysis without sounding stiff"
    ),
}

# Defaults pull from ElevenLabs' newer conversational voice library; legacy
# voices like Rachel/Adam (2022) are well-known but trained on more formal
# audiobook content and sound stiffer through current models.
#
# Settings tuned for natural radio talk:
# - stability 0.30: more emotional variation (avoids monotone)
# - similarity_boost 0.75: voice stays recognizable without rigid mimicry
# - style 0.55: personality / inflection on top of the base voice
# - use_speaker_boost False: speaker_boost actually flattens prosody and adds
#   a "produced" sheen; off feels closer to a person at a mic.
_RADIO_SETTINGS = {
    "stability": 0.30,
    "similarity_boost": 0.75,
    "style": 0.55,
    "use_speaker_boost": False,
}

VOICE_PRESETS = {
    "female": {
        "host": TtsVoiceConfig(
            voice="9BWtsMINqrJLrRacOk9x",  # Aria — expressive, conversational
            instructions="Warm, expressive female radio host with natural momentum.",
            words_per_minute=150,
            settings=dict(_RADIO_SETTINGS),
        ),
        "cohost": TtsVoiceConfig(
            voice="pFZP5JQG7iQjIQuC4Bku",  # Lily — warm, friendly British
            instructions="Friendly female co-host, conversational and quick.",
            words_per_minute=152,
            settings=dict(_RADIO_SETTINGS),
        ),
    },
    "male": {
        "host": TtsVoiceConfig(
            voice="nPczCjzI2devNBz1zQrb",  # Brian — natural casual American narrator
            instructions="Calm, confident male radio host with grounded delivery.",
            words_per_minute=148,
            settings=dict(_RADIO_SETTINGS),
        ),
        "cohost": TtsVoiceConfig(
            voice="TX3LPaxmHKxFdv7VOQHJ",  # Liam — articulate, modern male
            instructions="Clear male co-host, lightly energetic and direct.",
            words_per_minute=150,
            settings=dict(_RADIO_SETTINGS),
        ),
    },
}

DUO_SEGMENT_VOICES = {
    "intro": "host",
    "weather": "host",
    "news": "cohost",
    "outro": "host",
}


def host_style(tone: str, voice_gender: str, host_format: str) -> str:
    tone_style = TONE_STYLES.get(tone, TONE_STYLES["casual"])
    host_label = "solo host" if host_format == "solo" else "two-host handoff"
    voice_label = "female-led" if voice_gender == "female" else "male-led"
    return f"{tone_style}; {voice_label}; {host_label}"


def apply_host_profile(
    config: AppConfig,
    tone: str | None,
    voice_gender: str | None,
    host_format: str | None,
) -> AppConfig:
    tone = tone if tone in TONE_STYLES else None
    voice_gender = voice_gender if voice_gender in VOICE_PRESETS else None
    host_format = host_format if host_format in {"solo", "duo"} else None
    if not tone and not voice_gender and not host_format:
        return config

    resolved_tone = tone or "casual"
    resolved_gender = voice_gender or "female"
    resolved_format = host_format or "solo"
    preset = VOICE_PRESETS[resolved_gender]

    tts_voices = dict(config.tts.voices)
    tts_voices.update({"host": preset["host"]})
    if resolved_format == "duo":
        tts_voices["cohost"] = preset["cohost"]

    tts = replace(
        config.tts,
        single_voice=resolved_format == "solo",
        primary_voice="host",
        voices=tts_voices,
    )
    voices = (
        dict(DUO_SEGMENT_VOICES)
        if resolved_format == "duo"
        else {segment: "host" for segment in DUO_SEGMENT_VOICES}
    )

    return replace(
        config,
        style=host_style(resolved_tone, resolved_gender, resolved_format),
        tts=tts,
        voices=voices,
    )
