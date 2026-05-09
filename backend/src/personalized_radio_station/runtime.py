from __future__ import annotations

import os
from pathlib import Path
from shutil import which

from .config import AppConfig, AiConfig, TtsConfig


ApiKeys = dict[str, str]


def missing_runtime_requirements(
    config: AppConfig,
    include_tts: bool = True,
    allow_mock: bool = False,
    api_keys: ApiKeys | None = None,
) -> list[str]:
    missing: list[str] = []
    missing.extend(
        _missing_ai_requirements(config.ai, allow_mock=allow_mock, api_keys=api_keys)
    )

    if include_tts and config.tts.enabled:
        missing.extend(
            _missing_tts_requirements(
                config.tts, allow_mock=allow_mock, api_keys=api_keys
            )
        )

    return missing


def assert_runtime_ready(
    config: AppConfig,
    include_tts: bool = True,
    allow_mock: bool = False,
    api_keys: ApiKeys | None = None,
) -> None:
    missing = missing_runtime_requirements(
        config,
        include_tts=include_tts,
        allow_mock=allow_mock,
        api_keys=api_keys,
    )
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise RuntimeError(f"Missing runtime requirements:\n{joined}")


def _has_key(env_name: str | None, api_keys: ApiKeys | None) -> bool:
    if not env_name:
        return False
    if api_keys and api_keys.get(env_name):
        return True
    return bool(os.environ.get(env_name))


def _missing_ai_requirements(
    config: AiConfig, allow_mock: bool, api_keys: ApiKeys | None
) -> list[str]:
    if config.model == "mock":
        if allow_mock:
            return []
        return ["test-only LiteLLM model `mock` is not allowed for normal runs"]

    if config.model.startswith("ollama/"):
        return []

    env_name = config.api_key_env or _env_for_litellm_model(config.model)
    if env_name and not _has_key(env_name, api_keys):
        return [f"{env_name} for LiteLLM model `{config.model}`"]
    return []


def _missing_tts_requirements(
    config: TtsConfig, allow_mock: bool, api_keys: ApiKeys | None
) -> list[str]:
    provider = config.provider.lower()
    if provider == "none":
        return []

    if provider == "mock":
        if allow_mock:
            return []
        return ["test-only TTS provider `mock` is not allowed for normal runs"]

    if provider == "elevenlabs":
        missing: list[str] = []
        if not _has_key(config.api_key_env, api_keys):
            missing.append(
                f"{config.api_key_env or 'ELEVENLABS_API_KEY'} for ElevenLabs TTS"
            )
        if config.response_format.startswith("mp3") and which("ffmpeg") is None:
            missing.append("ffmpeg executable for assembling ElevenLabs MP3 segments")
        return missing

    if provider in {"litellm", "openai"}:
        model = config.model
        if provider == "openai" and "/" not in model:
            model = f"openai/{model}"
        env_name = config.api_key_env or _env_for_litellm_model(model)
        if env_name and not _has_key(env_name, api_keys):
            return [f"{env_name} for LiteLLM TTS model `{model}`"]
        return []

    if provider == "piper":
        missing: list[str] = []
        if which(config.piper_path) is None and not Path(config.piper_path).exists():
            missing.append(f"`{config.piper_path}` executable for Piper TTS")
        if not config.piper_model_path:
            missing.append("`tts.piper_model_path` for Piper TTS")
        elif not Path(config.piper_model_path).exists():
            missing.append(f"Piper voice model at `{config.piper_model_path}`")
        return missing

    return [f"supported TTS provider; got `{config.provider}`"]


def _env_for_litellm_model(model: str) -> str | None:
    provider = model.split("/", 1)[0]
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "azure": "AZURE_API_KEY",
        "cohere": "COHERE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "elevenlabs": "ELEVENLABS_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "together_ai": "TOGETHERAI_API_KEY",
        "xai": "XAI_API_KEY",
    }.get(provider)
