from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import json
import re
import secrets
import threading
import time

from .audio import (
    audio_duration_seconds,
    concatenate_audio_files,
    concatenate_wavs,
    write_mock_wav,
)
from .config import (
    DEFAULT_NEWS_TOPICS,
    DEFAULT_RSS_FEEDS,
    AppConfig,
    WeatherConfig,
    load_config,
    parse_duration,
)
from .env import load_env_file
from .fragments import prepare_fragment_segments
from .hosts import apply_host_profile, host_style
from .news import (
    describe_news_sources,
    fetch_news,
    normalize_feed_url as _normalize_feed_url,
)
from .runtime import assert_runtime_ready
from .script import generate_script, render_markdown, stream_script_segments
from .timing import add_audio_timing, count_episode_words, episode_timing_metadata
from .tts import (
    _extension_for_provider,
    _resolve_voice,
    _slug as _tts_slug,
    _synthesize_litellm_speech,
    _synthesize_mock,
    _synthesize_piper,
    _voice_name_for_segment,
    synthesize_episode,
)
from .vibes import Vibe, VibeStore
from .weather import fetch_weather

from concurrent.futures import ThreadPoolExecutor
import random


TERMINAL_STATUSES = {"complete", "failed"}
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
FRONTEND_ENTRY = "index.html"
FRONTEND_FILES = {
    FRONTEND_ENTRY,
    "colors_and_type.css",
    "landing.html",
    "radio.js",
    "styles.css",
    "radio.jsx",
}


@dataclass(frozen=True)
class EpisodeEvent:
    id: int
    type: str
    data: dict[str, Any]


@dataclass
class EpisodeJob:
    id: str
    status: str
    output_dir: Path
    created_at: str
    updated_at: str
    started_at_monotonic: float = field(default_factory=time.perf_counter)
    mode: str = "mock"
    title: str = "VibeFM Test"
    vibe_id: str | None = None
    vibe_name: str | None = None
    error: str | None = None
    final_audio_path: Path | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    events: list[EpisodeEvent] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)

    def public_status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "mode": self.mode,
            "title": self.title,
            "vibe": (
                {"id": self.vibe_id, "name": self.vibe_name}
                if self.vibe_id and self.vibe_name
                else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": _elapsed_seconds(self),
            "segments": [
                {
                    "index": segment["index"],
                    "type": segment["type"],
                    "title": segment["title"],
                    "status": segment["status"],
                    "duration_seconds": segment.get("duration_seconds"),
                    "audio_url": segment.get("audio_url"),
                }
                for segment in self.segments
            ],
            "audio_url": f"/api/episodes/{self.id}/audio"
            if self.final_audio_path
            else None,
            "events_url": f"/api/episodes/{self.id}/events",
            "error": self.error,
        }


class EpisodeService:
    def __init__(
        self,
        output_dir: Path,
        config_path: Path,
        env_path: Path,
        vibe_store: VibeStore | None = None,
        demo_delay: float = 0.35,
    ) -> None:
        self.output_dir = output_dir
        self.config_path = config_path
        self.env_path = env_path
        self.vibe_store = vibe_store
        self.demo_delay = demo_delay
        self._jobs: dict[str, EpisodeJob] = {}
        self._lock = threading.Lock()
        # Used for parallel I/O within a single episode (weather + news).
        # Not bounded per-episode because each job uses ~2 short-lived tasks.
        self._io_executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="vibefm-io"
        )

    def create_episode(self, payload: dict[str, Any]) -> EpisodeJob:
        api_keys = _extract_api_keys(payload)
        payload = self._apply_vibe_to_payload(payload)
        episode_id = _new_episode_id()
        now = _now()
        mode = "real" if payload.get("mode") == "real" else "mock"
        job = EpisodeJob(
            id=episode_id,
            status="queued",
            output_dir=self.output_dir / episode_id,
            created_at=now,
            updated_at=now,
            mode=mode,
            vibe_id=_optional_string(payload.get("vibe_id")),
            vibe_name=_optional_string(payload.get("station_name")),
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._jobs[episode_id] = job

        self._emit(job, "status", {"status": "queued", "message": "Queued"})
        target = (
            self._generate_real_episode
            if mode == "real"
            else self._generate_mock_episode
        )
        thread = threading.Thread(
            target=target,
            args=(job, payload, api_keys),
            name=f"radio-episode-{episode_id}",
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, episode_id: str) -> EpisodeJob | None:
        with self._lock:
            return self._jobs.get(episode_id)

    def _apply_vibe_to_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        vibe_id = _optional_string(payload.get("vibe_id"))
        if not vibe_id:
            return payload
        if self.vibe_store is None:
            raise ValueError("Vibes are not configured for this server.")

        vibe = self.vibe_store.get_vibe(vibe_id)
        if vibe is None:
            raise ValueError("Vibe not found.")

        return _episode_payload_from_vibe(payload, vibe)

    def _generate_real_episode(
        self,
        job: EpisodeJob,
        payload: dict[str, Any],
        api_keys: dict[str, str] | None = None,
    ) -> None:
        try:
            load_env_file(self.env_path)
            config_path = _resolve_config_path(self.config_path)
            config = _apply_payload_to_config(load_config(config_path), payload)

            self._set_status(job, "checking_runtime", "Checking runtime requirements")
            assert_runtime_ready(config, include_tts=True, api_keys=api_keys)

            audio_dir = job.output_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)

            # Parallel: weather + news fetch. Intro fragment (which depends
            # on weather.time_of_day) renders inline once weather is back,
            # while news fetch keeps running in the background.
            weather_future = self._io_executor.submit(fetch_weather, config.weather)
            news_future = self._io_executor.submit(fetch_news, config.news)

            fragment_files: list[Path] = []
            fragment_segments: list[dict[str, Any]] = []
            weather = weather_future.result()
            if config.tts.enabled:
                self._set_status(job, "rendering_intro", "Rolling the opening")
                try:
                    fragments = prepare_fragment_segments(
                        config=config,
                        time_of_day=weather.time_of_day,
                        api_keys=api_keys,
                        cache_dir=self.output_dir.parent / "fragments",
                        audio_dir=audio_dir,
                        episode_dir=job.output_dir,
                        rng=random.Random(),
                    )
                    fragment_segments = [seg for seg, _ in fragments]
                    fragment_files = [path for _, path in fragments]

                    with job.condition:
                        job.title = "VibeFM"
                        job.segments = [
                            {
                                "index": index,
                                "type": str(seg.get("type", "segment")),
                                "title": str(seg.get("type", "segment")).title(),
                                "status": "pending",
                            }
                            for index, seg in enumerate(fragment_segments)
                        ]
                    for index, (segment, path) in enumerate(fragments):
                        self._mark_segment_ready(job, index, segment, path)
                except Exception as fragment_error:  # pragma: no cover
                    print(
                        f"[vibefm] fragment rendering failed, continuing without: {fragment_error}",
                        flush=True,
                    )
                    fragment_files = []
                    fragment_segments = []

            self._set_status(
                job,
                "fetching_sources",
                f"Fetching sources: {describe_news_sources(config.news)}",
            )
            news_items = news_future.result()
            (job.output_dir / "sources.json").write_text(
                json.dumps(
                    {
                        "mode": "real",
                        "vibe": _vibe_summary(payload),
                        "weather": weather.to_dict(),
                        "news": [item.to_dict() for item in news_items],
                    },
                    indent=2,
                )
                + "\n"
            )

            self._set_status(
                job, "generating_script", f"Generating script with {config.ai.model}"
            )
            if config.tts.enabled:
                self._set_status(
                    job,
                    "rendering_audio",
                    f"Rendering audio with {config.tts.provider}: {config.tts.model}",
                )

            # Stream the LLM output. Each complete segment kicks off TTS
            # and emits segment_ready immediately, so the listener hears
            # the first news beat shortly after the intro instead of
            # waiting for the entire script to finish.
            provider = config.tts.provider.lower()
            extension = (
                _extension_for_provider(provider, config.tts.response_format)
                if config.tts.enabled
                else "wav"
            )
            body_segments: list[dict[str, Any]] = []
            body_files: list[Path] = []
            for offset, segment in enumerate(
                stream_script_segments(news_items, weather, config, api_keys=api_keys)
            ):
                text = str(segment.get("text", "")).strip()
                if not text:
                    continue
                absolute_index = len(fragment_segments) + len(body_segments)
                if config.tts.enabled:
                    voice_name = _voice_name_for_segment(segment, config)
                    voice_name, voice = _resolve_voice(voice_name, config)
                    segment["voice"] = voice_name
                    segment_path = (
                        audio_dir
                        / f"{absolute_index:02d}-{_tts_slug(segment.get('type', 'segment'))}.{extension}"
                    )
                    if provider == "mock":
                        _synthesize_mock(text, voice_name, segment_path)
                    elif provider in {"elevenlabs", "litellm", "openai"}:
                        _synthesize_litellm_speech(
                            text, voice, config, segment_path, api_keys
                        )
                    elif provider == "piper":
                        _synthesize_piper(text, voice, config, segment_path)
                    else:
                        raise ValueError(
                            f"Unsupported TTS provider: {config.tts.provider}"
                        )
                    segment["audio_file"] = str(
                        segment_path.relative_to(job.output_dir)
                    )
                    body_files.append(segment_path)
                    with job.condition:
                        job.segments.append(
                            {
                                "index": absolute_index,
                                "type": str(segment.get("type", "segment")),
                                "title": str(segment.get("type", "segment")).title(),
                                "status": "pending",
                            }
                        )
                    self._mark_segment_ready(job, absolute_index, segment, segment_path)
                body_segments.append(segment)

            episode = {
                "title": "VibeFM",
                "segments": [*fragment_segments, *body_segments],
            }
            script_words = count_episode_words(episode)
            episode["timing"] = episode_timing_metadata(config, script_words)
            (job.output_dir / "episode.json").write_text(
                json.dumps(episode, indent=2) + "\n"
            )
            (job.output_dir / "script.md").write_text(render_markdown(episode))
            self._emit(
                job,
                "script_ready",
                {
                    "title": job.title,
                    "segment_count": len(job.segments),
                },
            )

            if config.tts.enabled:
                all_files = [*fragment_files, *body_files]
                final_audio: Path | None = None
                if all_files:
                    if all(path.suffix == ".wav" for path in all_files):
                        final_audio = concatenate_wavs(
                            all_files, job.output_dir / "episode.wav"
                        )
                    elif all(path.suffix == ".mp3" for path in all_files):
                        final_audio = concatenate_audio_files(
                            all_files, job.output_dir / "episode.mp3"
                        )
                if final_audio:
                    episode["audio_file"] = final_audio.name
                    add_audio_timing(episode, final_audio, script_words, config)
                    with job.condition:
                        job.final_audio_path = final_audio
            else:
                self._set_status(job, "audio_disabled", "TTS is disabled")

            (job.output_dir / "episode.json").write_text(
                json.dumps(episode, indent=2) + "\n"
            )
            (job.output_dir / "script.md").write_text(render_markdown(episode))
            self._set_status(
                job,
                "complete",
                "Complete",
                extra={
                    "audio_url": f"/api/episodes/{job.id}/audio"
                    if job.final_audio_path
                    else None
                },
            )
        except Exception as exc:  # pragma: no cover - defensive for background thread
            with job.condition:
                job.error = str(exc)
            self._set_status(
                job, "failed", "Generation failed", extra={"error": str(exc)}
            )

    def _generate_mock_episode(
        self,
        job: EpisodeJob,
        payload: dict[str, Any],
        api_keys: dict[str, str] | None = None,
    ) -> None:
        del api_keys
        try:
            self._set_status(job, "fetching_sources", "Collecting test sources")
            self._sleep()

            station_name = _clean_string(payload.get("station_name"), "VibeFM")
            style = _clean_string(payload.get("style"), "warm, concise, already on air")
            topics = _clean_topics(
                payload.get("topics"),
                [] if payload.get("replace_topics") else None,
            )
            duration = _duration_from_payload(payload, "2 minutes")
            weather_name = _clean_string(payload.get("weather_name"), "Lisbon")
            payload_rss_feeds = _clean_rss_feeds(
                payload.get("rss_feeds", payload.get("rss_urls", payload.get("rss")))
            )
            rss_feeds = (
                payload_rss_feeds
                if payload.get("replace_rss_feeds")
                else _dedupe_strings([*DEFAULT_RSS_FEEDS, *payload_rss_feeds])
            )
            source_topics = topics or _topics_from_rss_feeds(rss_feeds)

            sources = {
                "mode": "mock",
                "vibe": _vibe_summary(payload),
                "weather": {
                    "location": weather_name,
                    "temperature_c": 21,
                    "summary": "Clear enough for a local demo.",
                },
                "rss_feeds": rss_feeds,
                "news": [
                    {
                        "topic": topic,
                        "source": "Mock Wire",
                        "title": f"{topic.title()} gets a useful development",
                    }
                    for topic in source_topics
                ],
            }
            (job.output_dir / "sources.json").write_text(
                json.dumps(sources, indent=2) + "\n"
            )

            self._set_status(job, "generating_script", "Writing a test script")
            self._sleep()

            episode = _build_mock_episode(
                station_name,
                style,
                duration,
                weather_name,
                source_topics,
                host_format=_clean_host_format(payload.get("host_format")),
            )
            self._prepare_public_segments(job, episode)
            (job.output_dir / "episode.json").write_text(
                json.dumps(episode, indent=2) + "\n"
            )
            (job.output_dir / "script.md").write_text(render_markdown(episode))
            self._emit(
                job,
                "script_ready",
                {
                    "title": job.title,
                    "segment_count": len(job.segments),
                },
            )

            audio_dir = job.output_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            segment_paths: list[Path] = []
            self._set_status(job, "rendering_audio", "Rendering test audio")
            for index, segment in enumerate(episode["segments"]):
                self._sleep()
                segment_path = audio_dir / f"{index:02d}-{_slug(segment['type'])}.wav"
                seconds = _mock_segment_seconds(str(segment.get("text", "")))
                write_mock_wav(
                    segment_path,
                    duration_seconds=seconds,
                    frequency_hz=360 + (index * 70),
                )
                duration_seconds = audio_duration_seconds(segment_path)
                segment["audio_file"] = str(segment_path.relative_to(job.output_dir))
                segment_paths.append(segment_path)
                self._mark_segment_ready(
                    job, index, segment, segment_path, duration_seconds
                )

            final_audio = concatenate_wavs(
                segment_paths, job.output_dir / "episode.wav"
            )
            episode["audio_file"] = final_audio.name
            episode["timing"] = {
                "target_duration": duration,
                "audio_duration_seconds": audio_duration_seconds(final_audio),
            }
            (job.output_dir / "episode.json").write_text(
                json.dumps(episode, indent=2) + "\n"
            )
            with job.condition:
                job.final_audio_path = final_audio

            self._set_status(
                job,
                "complete",
                "Complete",
                extra={"audio_url": f"/api/episodes/{job.id}/audio"},
            )
        except Exception as exc:  # pragma: no cover - defensive for background thread
            with job.condition:
                job.error = str(exc)
            self._set_status(
                job, "failed", "Generation failed", extra={"error": str(exc)}
            )

    def _prepare_public_segments(
        self, job: EpisodeJob, episode: dict[str, Any]
    ) -> None:
        with job.condition:
            job.title = str(episode.get("title", "VibeFM"))
            job.segments = [
                {
                    "index": index,
                    "type": str(segment.get("type", "segment")),
                    "title": str(segment.get("type", "segment")).title(),
                    "status": "pending",
                }
                for index, segment in enumerate(episode.get("segments", []))
            ]

    def _mark_segment_ready(
        self,
        job: EpisodeJob,
        index: int,
        segment: dict[str, Any],
        segment_path: Path,
        duration_seconds: float | None = None,
    ) -> None:
        if duration_seconds is None:
            duration_seconds = audio_duration_seconds(segment_path)
        audio_url = f"/api/episodes/{job.id}/segments/{index}/audio"
        with job.condition:
            if index < 0 or index >= len(job.segments):
                return
            public_segment = job.segments[index]
            public_segment["status"] = "ready"
            public_segment["audio_url"] = audio_url
            public_segment["audio_path"] = str(segment_path.relative_to(job.output_dir))
            public_segment["duration_seconds"] = duration_seconds
        self._emit(
            job,
            "segment_ready",
            {
                "index": index,
                "type": segment.get("type", "segment"),
                "title": str(segment.get("type", "segment")).title(),
                "audio_url": audio_url,
                "duration_seconds": duration_seconds,
            },
        )

    def _set_status(
        self,
        job: EpisodeJob,
        status: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        with job.condition:
            job.status = status
            job.updated_at = _now()
        data = {"status": status, "message": message}
        if extra:
            data.update(extra)
        self._emit(job, "status" if status not in TERMINAL_STATUSES else status, data)

    def _emit(self, job: EpisodeJob, event_type: str, data: dict[str, Any]) -> None:
        with job.condition:
            event_data = {
                **data,
                "at": _now(),
                "elapsed_seconds": _elapsed_seconds(job),
            }
            event = EpisodeEvent(id=len(job.events), type=event_type, data=event_data)
            job.events.append(event)
            job.updated_at = _now()
            job.condition.notify_all()

    def _sleep(self) -> None:
        if self.demo_delay > 0:
            time.sleep(self.demo_delay)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: Path | str = Path("episodes"),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    db_path: Path | str | None = None,
    demo_delay: float = 0.35,
) -> ThreadingHTTPServer:
    output_path = Path(output_dir)
    vibe_store = VibeStore(
        Path(db_path) if db_path is not None else output_path.parent / "vibefm.sqlite3"
    )
    service = EpisodeService(
        output_path,
        config_path=Path(config_path),
        env_path=Path(env_path),
        vibe_store=vibe_store,
        demo_delay=demo_delay,
    )

    class RadioRequestHandler(_RadioRequestHandler):
        pass

    RadioRequestHandler.service = service
    RadioRequestHandler.vibe_store = vibe_store
    return ThreadingHTTPServer((host, port), RadioRequestHandler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: Path | str = Path("episodes"),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    db_path: Path | str | None = None,
) -> None:
    server = create_server(
        host=host,
        port=port,
        output_dir=output_dir,
        config_path=config_path,
        env_path=env_path,
        db_path=db_path,
    )
    address, actual_port = server.server_address
    print(f"[vibefm] API listening on http://{address}:{actual_port}", flush=True)
    print("[vibefm] Real episodes use configured model and TTS APIs.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[vibefm] Shutting down.", flush=True)
    finally:
        server.server_close()


def main() -> None:
    parser = ArgumentParser(description="Run the local VibeFM API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("episodes"),
        help="Directory where API-generated episode artifacts are saved.",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.yaml"), help="Path to config YAML."
    )
    parser.add_argument(
        "--env", type=Path, default=Path(".env"), help="Path to .env file."
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="SQLite database path for saved vibes."
    )
    args = parser.parse_args()

    serve(
        host=args.host,
        port=args.port,
        output_dir=args.output_dir,
        config_path=args.config,
        env_path=args.env,
        db_path=args.db,
    )


class _RadioRequestHandler(BaseHTTPRequestHandler):
    service: EpisodeService
    vibe_store: VibeStore
    server_version = "VibeFMHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api":
            self._send_json(
                {
                    "name": "VibeFM API",
                    "status": "ok",
                    "ui": "/",
                }
            )
            return

        parts = _path_parts(path)
        if len(parts) == 2 and parts == ["api", "vibes"]:
            self._send_vibes()
            return
        if len(parts) == 3 and parts[:2] == ["api", "vibes"]:
            self._send_vibe(parts[2])
            return
        if len(parts) == 3 and parts[:2] == ["api", "episodes"]:
            self._send_episode_status(parts[2])
            return
        if (
            len(parts) == 4
            and parts[:2] == ["api", "episodes"]
            and parts[3] == "events"
        ):
            self._send_episode_events(parts[2])
            return
        if len(parts) == 4 and parts[:2] == ["api", "episodes"] and parts[3] == "audio":
            self._send_final_audio(parts[2])
            return
        if (
            len(parts) == 6
            and parts[:2] == ["api", "episodes"]
            and parts[3] == "segments"
            and parts[5] == "audio"
        ):
            self._send_segment_audio(parts[2], parts[4])
            return

        frontend_path = _frontend_path(path)
        if frontend_path is not None:
            self._send_file(
                frontend_path, content_type=_static_content_type(frontend_path)
            )
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/vibes":
            payload = self._read_json_body()
            try:
                vibe = self.vibe_store.create_vibe(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"vibe": vibe.to_dict()}, status=HTTPStatus.CREATED)
            return

        if path != "/api/episodes":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        payload = self._read_json_body()
        try:
            job = self.service.create_episode(payload)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(
            {
                "episode_id": job.id,
                "vibe": (
                    {"id": job.vibe_id, "name": job.vibe_name}
                    if job.vibe_id and job.vibe_name
                    else None
                ),
                "status_url": f"/api/episodes/{job.id}",
                "events_url": f"/api/episodes/{job.id}/events",
                "audio_url": f"/api/episodes/{job.id}/audio",
            },
            status=HTTPStatus.ACCEPTED,
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_vibes(self) -> None:
        self._send_json(
            {
                "presets": self.vibe_store.preset_sources(),
                "vibes": [vibe.to_dict() for vibe in self.vibe_store.list_vibes()],
            }
        )

    def _send_vibe(self, vibe_id: str) -> None:
        vibe = self.vibe_store.get_vibe(vibe_id)
        if vibe is None:
            self._send_json({"error": "Vibe not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json({"vibe": vibe.to_dict()})

    def _send_episode_status(self, episode_id: str) -> None:
        job = self.service.get_job(episode_id)
        if not job:
            self._send_json({"error": "Episode not found"}, status=HTTPStatus.NOT_FOUND)
            return
        with job.condition:
            self._send_json(job.public_status())

    def _send_episode_events(self, episode_id: str) -> None:
        job = self.service.get_job(episode_id)
        if not job:
            self._send_json({"error": "Episode not found"}, status=HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self._send_common_headers(content_type="text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        cursor = 0
        try:
            while True:
                with job.condition:
                    while (
                        cursor >= len(job.events)
                        and job.status not in TERMINAL_STATUSES
                    ):
                        job.condition.wait(timeout=15)
                        if cursor >= len(job.events):
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                    events = job.events[cursor:]
                    cursor = len(job.events)
                    terminal = job.status in TERMINAL_STATUSES and cursor >= len(
                        job.events
                    )

                for event in events:
                    self.wfile.write(_format_sse(event).encode("utf-8"))
                    self.wfile.flush()

                if terminal:
                    break
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send_segment_audio(self, episode_id: str, index_value: str) -> None:
        job = self.service.get_job(episode_id)
        if not job:
            self._send_json({"error": "Episode not found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            index = int(index_value)
        except ValueError:
            self._send_json(
                {"error": "Invalid segment index"}, status=HTTPStatus.BAD_REQUEST
            )
            return

        with job.condition:
            if index < 0 or index >= len(job.segments):
                self._send_json(
                    {"error": "Segment not found"}, status=HTTPStatus.NOT_FOUND
                )
                return
            segment = job.segments[index]
            if segment.get("status") != "ready":
                self._send_json(
                    {"error": "Segment is not ready"}, status=HTTPStatus.ACCEPTED
                )
                return
            audio_path = segment.get("audio_path")
            if not audio_path:
                self._send_json(
                    {"error": "Segment audio is missing"}, status=HTTPStatus.NOT_FOUND
                )
                return
            segment_path = job.output_dir / str(audio_path)

        self._send_file(segment_path, content_type=_audio_content_type(segment_path))

    def _send_final_audio(self, episode_id: str) -> None:
        job = self.service.get_job(episode_id)
        if not job:
            self._send_json({"error": "Episode not found"}, status=HTTPStatus.NOT_FOUND)
            return
        with job.condition:
            final_audio_path = job.final_audio_path
        if not final_audio_path:
            self._send_json({"error": "Audio is not ready"}, status=HTTPStatus.ACCEPTED)
            return
        self._send_file(
            final_audio_path, content_type=_audio_content_type(final_audio_path)
        )

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": "File not found"}, status=HTTPStatus.NOT_FOUND)
            return

        total_size = path.stat().st_size
        range_header = self.headers.get("Range", "")
        start = 0
        end = total_size - 1
        status = HTTPStatus.OK
        if range_header.startswith("bytes="):
            requested = range_header.removeprefix("bytes=").split("-", 1)
            try:
                if requested[0]:
                    start = int(requested[0])
                if requested[1]:
                    end = int(requested[1])
                end = min(end, total_size - 1)
                if start > end:
                    raise ValueError
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{total_size}")
                self.end_headers()
                return

        content_length = end - start + 1
        self.send_response(status)
        self._send_common_headers(content_type=content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
        self.end_headers()

        with path.open("rb") as file:
            file.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = file.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value).encode("utf-8")
        self._send_bytes(body, status=status, content_type="application/json")

    def _send_bytes(
        self,
        body: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.send_response(status)
        self._send_common_headers(content_type=content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self, content_type: str | None = None) -> None:
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            return {}
        body = self.rfile.read(int(raw_length))
        if not body:
            return {}
        try:
            value = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}


def _build_mock_episode(
    station_name: str,
    style: str,
    duration: str,
    weather_name: str,
    topics: list[str],
    host_format: str = "solo",
) -> dict[str, Any]:
    del weather_name
    news_voice = "cohost" if host_format == "duo" else "host"
    segments = [
        {
            "type": "intro",
            "voice": "host",
            "text": (
                f"You are tuned to {station_name}, running {style}. "
                f"This is a local no-model test for a {duration} station — "
                "let's get straight to the briefing."
            ),
        },
    ]
    for topic in topics:
        segments.append(
            {
                "type": "news",
                "voice": news_voice,
                "text": (
                    f"On {topic}, the mock wire says there is enough movement to keep "
                    "watching, but nothing here called a paid model or external news API."
                ),
            }
        )
    segments.append(
        {
            "type": "outro",
            "voice": "host",
            "text": "That closes the test signal. The real pipeline can take this same shape next.",
        }
    )
    return {"title": f"{station_name} Test Signal", "segments": segments}


def _format_sse(event: EpisodeEvent) -> str:
    data = json.dumps(event.data)
    return f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"


def _new_episode_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ep_{timestamp}_{secrets.token_hex(4)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _elapsed_seconds(job: EpisodeJob) -> float:
    return round(time.perf_counter() - job.started_at_monotonic, 3)


def _path_parts(path: str) -> list[str]:
    return [unquote(part) for part in path.strip("/").split("/") if part]


def _resolve_under(root: Path, parts: list[str], default: str) -> Path | None:
    if not parts:
        candidate = (root / default).resolve()
    else:
        candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _frontend_path(path: str) -> Path | None:
    parts = _path_parts(path)
    dist_dir = FRONTEND_ROOT / "dist"
    if dist_dir.is_dir():
        return _resolve_under(dist_dir, parts, default="index.html")

    if not parts:
        return FRONTEND_ROOT / FRONTEND_ENTRY
    if parts == ["index.html"]:
        return FRONTEND_ROOT / FRONTEND_ENTRY
    if parts[0] == "fonts":
        candidate = (FRONTEND_ROOT / Path(*parts)).resolve()
    elif len(parts) == 1 and parts[0] in FRONTEND_FILES:
        candidate = (FRONTEND_ROOT / parts[0]).resolve()
    else:
        return None

    try:
        candidate.relative_to(FRONTEND_ROOT)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _clean_string(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _clean_topics(value: Any, fallback: list[str] | None = None) -> list[str]:
    default_topics = fallback if fallback is not None else list(DEFAULT_NEWS_TOPICS)
    if not isinstance(value, list):
        return default_topics
    topics = [str(item).strip() for item in value if str(item).strip()]
    return topics[:5] or default_topics


def _topics_from_rss_feeds(rss_feeds: list[str]) -> list[str]:
    topics: list[str] = []
    for feed_url in rss_feeds:
        host = urlparse(feed_url).netloc.lower().removeprefix("www.")
        if host:
            topics.append(host)
    return _dedupe_strings(topics)[:5]


def _episode_payload_from_vibe(payload: dict[str, Any], vibe: Vibe) -> dict[str, Any]:
    merged = dict(payload)
    merged.update(
        {
            "vibe_id": vibe.id,
            "station_name": vibe.name,
            "style": host_style(vibe.tone, vibe.voice_gender, vibe.host_format),
            "rss_feeds": vibe.rss_feeds,
            "replace_topics": True,
            "replace_rss_feeds": True,
            "host_tone": vibe.tone,
            "voice_gender": vibe.voice_gender,
            "host_format": vibe.host_format,
        }
    )
    return merged


def _vibe_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    vibe_id = _optional_string(payload.get("vibe_id"))
    if not vibe_id:
        return None
    return {
        "id": vibe_id,
        "name": _optional_string(payload.get("station_name")),
        "tone": _optional_string(payload.get("host_tone")),
        "voice_gender": _optional_string(payload.get("voice_gender")),
        "host_format": _optional_string(payload.get("host_format")),
    }


def _apply_payload_to_config(config: AppConfig, payload: dict[str, Any]) -> AppConfig:
    updates: dict[str, Any] = {}
    station_name = _optional_string(payload.get("station_name"))
    style = _optional_string(payload.get("style"))
    duration = _duration_from_payload(payload)
    if station_name:
        updates["station_name"] = station_name
    if style:
        updates["style"] = style
    if duration:
        updates["duration"] = parse_duration(duration)

    news = config.news
    if "topics" in payload or payload.get("replace_topics"):
        topic_fallback = [] if payload.get("replace_topics") else None
        news = replace(
            news, topics=_clean_topics(payload.get("topics"), topic_fallback)
        )
    custom_feeds = _clean_rss_feeds(
        payload.get("rss_feeds", payload.get("rss_urls", payload.get("rss")))
    )
    preset_feeds = _resolve_source_preset_feeds(
        payload.get("source_preset_ids", payload.get("source_presets"))
    )
    rss_feeds = _dedupe_strings([*preset_feeds, *custom_feeds])
    if payload.get("replace_rss_feeds"):
        news = replace(news, rss_feeds=rss_feeds)
    elif rss_feeds:
        news = replace(news, rss_feeds=_dedupe_strings([*news.rss_feeds, *rss_feeds]))
    language = _optional_string(payload.get("language"))
    country = _optional_string(payload.get("country"))
    if language:
        news = replace(news, language=language)
    if country:
        news = replace(news, country=country)
    updates["news"] = news

    weather = config.weather
    weather_name = _optional_string(payload.get("weather_name"))
    latitude = _optional_float(payload.get("latitude"))
    longitude = _optional_float(payload.get("longitude"))
    if weather_name:
        weather = replace(weather, name=weather_name)
    if latitude is not None and longitude is not None:
        weather = WeatherConfig(
            name=weather.name,
            latitude=latitude,
            longitude=longitude,
        )
    updates["weather"] = weather

    configured = replace(config, **updates)
    return apply_host_profile(
        configured,
        _optional_string(payload.get("host_tone")),
        _optional_string(payload.get("voice_gender")),
        _optional_string(payload.get("host_format")),
    )


def _resolve_source_preset_feeds(value: Any) -> list[str]:
    from .vibes import PRESET_RSS_SOURCES

    if value is None:
        return []
    if isinstance(value, str):
        candidates: list[Any] = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = [value]

    feeds: list[str] = []
    for raw in candidates:
        if isinstance(raw, dict):
            preset_id = str(raw.get("id", "")).strip().lower()
        else:
            preset_id = str(raw).strip().lower()
        source = PRESET_RSS_SOURCES.get(preset_id)
        if source:
            feeds.append(source["url"])
    return _dedupe_strings(feeds)


def _clean_host_format(value: Any) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in {"solo", "duo"} else "solo"


def _resolve_config_path(path: Path) -> Path:
    if not path.exists() and path == Path("config.yaml"):
        return Path("config.example.yaml")
    return path


def _extract_api_keys(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.pop("api_keys", None)
    if not isinstance(raw, dict):
        return {}
    keys: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned:
            keys[name.strip()] = cleaned
    return keys


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_rss_feeds(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = [value]

    feeds: list[str] = []
    for item in values:
        url = str(item).strip()
        if not url:
            continue
        if urlparse(url).scheme.lower() not in {"http", "https"}:
            continue
        feeds.append(_normalize_feed_url(url))
    return _dedupe_strings(feeds)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _duration_from_payload(
    payload: dict[str, Any], fallback: str | None = None
) -> str | None:
    duration_minutes = payload.get("duration_minutes")
    if duration_minutes is not None and duration_minutes != "":
        minutes = int(float(duration_minutes))
        if minutes <= 0:
            raise ValueError("Duration minutes must be greater than zero.")
        return f"{minutes} minutes"
    return _optional_string(payload.get("duration")) or fallback


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _audio_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".pcm":
        return "audio/L16"
    return "application/octet-stream"


def _static_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix in {".js", ".jsx"}:
        return "text/javascript; charset=utf-8"
    if suffix == ".woff2":
        return "font/woff2"
    return "application/octet-stream"


def _slug(value: Any) -> str:
    text = "".join(char.lower() if char.isalnum() else "-" for char in str(value))
    return "-".join(part for part in text.split("-") if part) or "segment"


def _mock_segment_seconds(text: str) -> float:
    return min(6.0, max(1.4, len(text) / 42))


if __name__ == "__main__":
    main()
