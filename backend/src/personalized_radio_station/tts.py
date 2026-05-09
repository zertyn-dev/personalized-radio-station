from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import os
import re
import subprocess

from .audio import concatenate_audio_files, concatenate_wavs, write_mock_wav
from .config import AppConfig, TtsVoiceConfig


@dataclass(frozen=True)
class TtsResult:
    segment_files: list[Path]
    episode_file: Path | None


SegmentReadyCallback = Callable[[int, dict[str, Any], Path], None]
ApiKeys = dict[str, str]


def _resolve_api_key(env_name: str | None, api_keys: ApiKeys | None) -> str | None:
    if not env_name:
        return None
    if api_keys:
        value = api_keys.get(env_name)
        if value:
            return value
    return os.environ.get(env_name)


def synthesize_episode(
    episode: dict[str, Any],
    config: AppConfig,
    episode_dir: Path,
    on_segment_ready: SegmentReadyCallback | None = None,
    api_keys: ApiKeys | None = None,
) -> TtsResult:
    if not config.tts.enabled:
        return TtsResult(segment_files=[], episode_file=None)

    provider = config.tts.provider.lower()
    audio_dir = episode_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    segment_files: list[Path] = []
    for index, segment in enumerate(episode.get("segments", [])):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue

        voice_name = _voice_name_for_segment(segment, config)
        voice_name, voice = _resolve_voice(voice_name, config)
        segment["voice"] = voice_name
        extension = _extension_for_provider(provider, config.tts.response_format)
        segment_path = (
            audio_dir
            / f"{index:02d}-{_slug(segment.get('type', 'segment'))}.{extension}"
        )

        if provider == "mock":
            _synthesize_mock(text, voice_name, segment_path)
        elif provider in {"elevenlabs", "litellm", "openai"}:
            _synthesize_litellm_speech(text, voice, config, segment_path, api_keys)
        elif provider == "piper":
            _synthesize_piper(text, voice, config, segment_path)
        else:
            raise ValueError(f"Unsupported TTS provider: {config.tts.provider}")

        segment["audio_file"] = str(segment_path.relative_to(episode_dir))
        segment_files.append(segment_path)
        if on_segment_ready:
            on_segment_ready(index, segment, segment_path)

    episode_file = None
    if segment_files and all(path.suffix == ".wav" for path in segment_files):
        episode_file = concatenate_wavs(segment_files, episode_dir / "episode.wav")
    elif segment_files and all(path.suffix == ".mp3" for path in segment_files):
        episode_file = concatenate_audio_files(
            segment_files, episode_dir / "episode.mp3"
        )

    return TtsResult(segment_files=segment_files, episode_file=episode_file)


def _voice_name_for_segment(segment: dict[str, Any], config: AppConfig) -> str:
    if config.tts.single_voice:
        return config.tts.primary_voice

    explicit_voice = segment.get("voice")
    if explicit_voice:
        return str(explicit_voice)

    segment_type = str(segment.get("type", "news"))
    return config.voices.get(segment_type, "host")


def _resolve_voice(voice_name: str, config: AppConfig) -> tuple[str, TtsVoiceConfig]:
    voice = config.tts.voices.get(voice_name)
    if voice:
        return voice_name, voice

    fallback_name, fallback_voice = next(iter(config.tts.voices.items()))
    return fallback_name, fallback_voice


def _synthesize_mock(text: str, voice_name: str, output_path: Path) -> None:
    duration = min(8.0, max(0.7, len(text) / 55))
    frequency = 360 + (sum(ord(char) for char in voice_name) % 260)
    write_mock_wav(output_path, duration_seconds=duration, frequency_hz=frequency)


def _synthesize_litellm_speech(
    text: str,
    voice: TtsVoiceConfig,
    config: AppConfig,
    output_path: Path,
    api_keys: ApiKeys | None = None,
) -> None:
    try:
        from litellm import speech
    except ImportError as exc:
        raise RuntimeError(
            "LiteLLM is not installed. From backend/, install dependencies with `uv sync`."
        ) from exc

    api_key = (
        _resolve_api_key(config.tts.api_key_env, api_keys)
        if config.tts.api_key_env
        else None
    )
    if config.tts.api_key_env and not api_key:
        raise RuntimeError(f"Missing {config.tts.api_key_env} for LiteLLM TTS.")

    kwargs: dict[str, Any] = {
        "model": _litellm_tts_model(config),
        "input": text,
        "voice": voice.voice,
        "api_key": api_key,
        "api_base": config.tts.api_base,
        "response_format": config.tts.response_format,
        "speed": voice.speed,
        "instructions": voice.instructions,
    }
    if voice.settings:
        kwargs["voice_settings"] = voice.settings

    response = speech(**kwargs)
    _write_litellm_binary_response(response, output_path)


def _synthesize_piper(
    text: str, voice: TtsVoiceConfig, config: AppConfig, output_path: Path
) -> None:
    if not config.tts.piper_model_path:
        raise RuntimeError("Missing `tts.piper_model_path` for Piper TTS.")

    command = [
        config.tts.piper_path,
        "--model",
        config.tts.piper_model_path,
        "--output_file",
        str(output_path),
    ]
    if voice.speaker:
        command.extend(["--speaker", voice.speaker])

    try:
        subprocess.run(
            command,
            input=text,
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Piper executable not found: {config.tts.piper_path}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Piper TTS failed: {exc.stderr}") from exc


def _slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return slug or "segment"


def _extension_for_provider(provider: str, response_format: str) -> str:
    provider = provider.lower()
    if provider in {"mock", "piper"}:
        return "wav"
    if provider == "elevenlabs":
        return response_format.split("_", 1)[0]
    if response_format == "pcm":
        return "pcm"
    return response_format


def _litellm_tts_model(config: AppConfig) -> str:
    model = config.tts.model
    if config.tts.provider.lower() == "elevenlabs" and not model.startswith(
        "elevenlabs/"
    ):
        return f"elevenlabs/{model}"
    if config.tts.provider.lower() == "openai" and "/" not in model:
        return f"openai/{model}"
    return model


def _write_litellm_binary_response(response: Any, output_path: Path) -> None:
    if hasattr(response, "stream_to_file"):
        response.stream_to_file(output_path)
        return
    if hasattr(response, "read"):
        output_path.write_bytes(response.read())
        return
    if isinstance(response, bytes):
        output_path.write_bytes(response)
        return
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        output_path.write_bytes(content)
        return
    raise RuntimeError("LiteLLM TTS returned an unsupported response type.")
