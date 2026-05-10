from __future__ import annotations

import json
import os
from typing import Any

from .config import AiConfig


Message = dict[str, str]
ApiKeys = dict[str, str]


def generate_text(
    messages: list[Message],
    config: AiConfig,
    api_keys: ApiKeys | None = None,
) -> str:
    if config.model == "mock":
        return _mock_completion(messages)

    try:
        from litellm import completion
    except ImportError as exc:
        raise RuntimeError(
            "LiteLLM is not installed. From backend/, install dependencies with `uv sync`."
        ) from exc

    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
    }
    if config.api_base:
        kwargs["api_base"] = config.api_base
    if config.api_key_env:
        api_key = _resolve_api_key(config.api_key_env, api_keys)
        if not api_key:
            raise RuntimeError(f"Missing {config.api_key_env} for LiteLLM.")
        kwargs["api_key"] = api_key
    if config.max_tokens:
        kwargs["max_tokens"] = config.max_tokens
    if config.reasoning:
        _add_reasoning_options(kwargs, config)

    response = completion(**kwargs)
    content = _response_content(response)
    if not content:
        raise RuntimeError(_empty_response_message(response, config))

    return content


def stream_text(
    messages: list[Message],
    config: AiConfig,
    api_keys: ApiKeys | None = None,
):
    """Yield text deltas from a streaming LLM completion.

    Falls back to a single yield of the full mock response when the
    model is `mock`.
    """
    if config.model == "mock":
        yield _mock_completion(messages)
        return

    try:
        from litellm import completion
    except ImportError as exc:
        raise RuntimeError(
            "LiteLLM is not installed. From backend/, install dependencies with `uv sync`."
        ) from exc

    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "stream": True,
    }
    if config.api_base:
        kwargs["api_base"] = config.api_base
    if config.api_key_env:
        api_key = _resolve_api_key(config.api_key_env, api_keys)
        if not api_key:
            raise RuntimeError(f"Missing {config.api_key_env} for LiteLLM.")
        kwargs["api_key"] = api_key
    if config.max_tokens:
        kwargs["max_tokens"] = config.max_tokens
    if config.reasoning:
        _add_reasoning_options(kwargs, config)

    response = completion(**kwargs)
    for chunk in response:
        try:
            delta = chunk.choices[0].delta
            content = _get_value(delta, "content")
        except (AttributeError, IndexError, TypeError):
            content = None
        if isinstance(content, str) and content:
            yield content


def _resolve_api_key(env_name: str, api_keys: ApiKeys | None) -> str | None:
    if api_keys:
        value = api_keys.get(env_name)
        if value:
            return value
    return os.environ.get(env_name)


def _add_reasoning_options(kwargs: dict[str, Any], config: AiConfig) -> None:
    if config.model.startswith("openrouter/"):
        kwargs["extra_body"] = {"reasoning": config.reasoning}
        return

    effort = config.reasoning.get("effort")
    if effort:
        kwargs["reasoning_effort"] = effort


def _response_content(response: Any) -> str:
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""

    content = _get_value(message, "content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            text = _get_value(part, "text")
            if isinstance(text, str):
                parts.append(text)
                continue
            if isinstance(part, str):
                parts.append(part)
        return "\n".join(parts).strip()

    return ""


def _empty_response_message(response: Any, config: AiConfig) -> str:
    choice = _first_choice(response)
    message = _get_value(choice, "message") if choice is not None else None
    usage = _get_value(response, "usage")
    finish_reason = _get_value(choice, "finish_reason") if choice is not None else None
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = _usage_value(usage, "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    reasoning_present = any(
        bool(_get_value(message, name))
        for name in ("reasoning", "reasoning_content", "reasoning_details")
    )

    details = [
        f"model={config.model}",
        f"finish_reason={finish_reason or 'unknown'}",
        f"prompt_tokens={prompt_tokens if prompt_tokens is not None else 'unknown'}",
        f"completion_tokens={completion_tokens if completion_tokens is not None else 'unknown'}",
        f"total_tokens={total_tokens if total_tokens is not None else 'unknown'}",
        f"reasoning_present={reasoning_present}",
    ]
    return (
        "LiteLLM returned an empty final response "
        f"({', '.join(details)}). "
        "Try increasing ai.max_tokens or lowering ai.reasoning.effort."
    )


def _first_choice(response: Any) -> Any:
    choices = _get_value(response, "choices")
    if not choices:
        return None
    try:
        return choices[0]
    except (IndexError, TypeError):
        return None


def _usage_value(usage: Any, key: str) -> Any:
    return _get_value(usage, key) if usage is not None else None


def _get_value(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _mock_completion(messages: list[Message]) -> str:
    prompt = messages[-1]["content"] if messages else ""
    station_name = "VibeFM"
    try:
        context = json.loads(prompt.split("Context:\n", 1)[1])
        station_name = context.get("station_name", station_name)
        weather = context.get("weather", {})
        news = context.get("news", [])
    except (IndexError, json.JSONDecodeError):
        weather = {}
        news = []

    del weather
    segments = [
        {
            "type": "intro",
            "voice": "host",
            "text": (f"You're tuned to {station_name}. Here's the briefing."),
        }
    ]

    for item in news[:3]:
        source = item.get("source") or "a news source"
        segments.append(
            {
                "type": "news",
                "voice": "host",
                "text": f"{source} reports: {item.get('title', 'Untitled story')}.",
            }
        )

    segments.append(
        {
            "type": "outro",
            "voice": "host",
            "text": "That is the briefing. Thanks for listening.",
        }
    )
    return json.dumps({"title": f"{station_name} Briefing", "segments": segments})
