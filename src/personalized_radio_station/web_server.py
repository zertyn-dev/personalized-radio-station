from __future__ import annotations

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

from .audio import audio_duration_seconds, concatenate_wavs, write_mock_wav
from .config import AppConfig, WeatherConfig, load_config, parse_duration
from .env import load_env_file
from .news import describe_news_sources, fetch_news
from .pipeline import _add_audio_timing, _timing_metadata
from .runtime import assert_runtime_ready
from .script import generate_script, render_markdown
from .timing import count_episode_words
from .tts import synthesize_episode
from .weather import fetch_weather


TERMINAL_STATUSES = {"complete", "failed"}

STATIC_FILES = {
    "/": "radio.html",
    "/index.html": "index.html",
    "/radio.html": "radio.html",
    "/landing.html": "landing.html",
    "/vibeFM_radio.html": "vibeFM_radio.html",
    "/radio_test.html": "radio_test.html",
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
        demo_delay: float = 0.35,
        static_dir: Path | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.config_path = config_path
        self.env_path = env_path
        self.demo_delay = demo_delay
        self.static_dir = Path(static_dir) if static_dir else None
        self._jobs: dict[str, EpisodeJob] = {}
        self._lock = threading.Lock()

    def create_episode(self, payload: dict[str, Any]) -> EpisodeJob:
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
        )
        job.output_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._jobs[episode_id] = job

        self._emit(job, "status", {"status": "queued", "message": "Queued"})
        thread = threading.Thread(
            target=self._generate_real_episode
            if mode == "real"
            else self._generate_mock_episode,
            args=(job, payload),
            name=f"radio-episode-{episode_id}",
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, episode_id: str) -> EpisodeJob | None:
        with self._lock:
            return self._jobs.get(episode_id)

    def _generate_real_episode(self, job: EpisodeJob, payload: dict[str, Any]) -> None:
        try:
            load_env_file(self.env_path)
            config_path = _resolve_config_path(self.config_path)
            config = _apply_payload_to_config(load_config(config_path), payload)

            self._set_status(job, "checking_runtime", "Checking runtime requirements")
            assert_runtime_ready(config, include_tts=True)

            self._set_status(
                job,
                "fetching_sources",
                f"Fetching sources: {describe_news_sources(config.news)}",
            )
            news_items = fetch_news(config.news)
            weather = fetch_weather(config.weather)
            (job.output_dir / "sources.json").write_text(
                json.dumps(
                    {
                        "mode": "real",
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
            episode = generate_script(news_items, weather, config)
            script_words = count_episode_words(episode)
            episode["timing"] = _timing_metadata(config, script_words)
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

            if config.tts.enabled:
                self._set_status(
                    job,
                    "rendering_audio",
                    f"Rendering audio with {config.tts.provider}: {config.tts.model}",
                )
                tts_result = synthesize_episode(
                    episode,
                    config,
                    job.output_dir,
                    on_segment_ready=lambda index, segment, path: (
                        self._mark_segment_ready(job, index, segment, path)
                    ),
                )
                if tts_result.episode_file:
                    episode["audio_file"] = tts_result.episode_file.name
                    _add_audio_timing(
                        episode, tts_result.episode_file, script_words, config
                    )
                    with job.condition:
                        job.final_audio_path = tts_result.episode_file
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

    def _generate_mock_episode(self, job: EpisodeJob, payload: dict[str, Any]) -> None:
        try:
            self._set_status(job, "fetching_sources", "Collecting test sources")
            self._sleep()

            station_name = _clean_string(payload.get("station_name"), "VibeFM")
            style = _clean_string(payload.get("style"), "warm, concise, already on air")
            topics = _clean_topics(payload.get("topics"))
            duration = _duration_from_payload(payload, "2 minutes")
            weather_name = _clean_string(payload.get("weather_name"), "Lisbon")

            sources = {
                "mode": "mock",
                "weather": {
                    "location": weather_name,
                    "temperature_c": 21,
                    "summary": "Clear enough for a local demo.",
                },
                "news": [
                    {
                        "topic": topic,
                        "source": "Mock Wire",
                        "title": f"{topic.title()} gets a useful development",
                    }
                    for topic in topics
                ],
            }
            (job.output_dir / "sources.json").write_text(
                json.dumps(sources, indent=2) + "\n"
            )

            self._set_status(job, "generating_script", "Writing a test script")
            self._sleep()

            episode = _build_mock_episode(
                station_name, style, duration, weather_name, topics
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
    demo_delay: float = 0.35,
    static_dir: Path | str | None = None,
) -> ThreadingHTTPServer:
    service = EpisodeService(
        Path(output_dir),
        config_path=Path(config_path),
        env_path=Path(env_path),
        demo_delay=demo_delay,
        static_dir=Path(static_dir) if static_dir is not None else None,
    )

    class RadioRequestHandler(_RadioRequestHandler):
        pass

    RadioRequestHandler.service = service
    return ThreadingHTTPServer((host, port), RadioRequestHandler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    output_dir: Path | str = Path("episodes"),
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    static_dir: Path | str | None = None,
) -> None:
    server = create_server(
        host=host,
        port=port,
        output_dir=output_dir,
        config_path=config_path,
        env_path=env_path,
        static_dir=static_dir,
    )
    address, actual_port = server.server_address
    print(f"[vibefm] API listening on http://{address}:{actual_port}", flush=True)
    if static_dir:
        print(f"[vibefm] UI served from {Path(static_dir).resolve()} at /", flush=True)
    print(
        "[vibefm] Demo mode is free; real mode uses configured model and TTS APIs.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[vibefm] Shutting down.", flush=True)
    finally:
        server.server_close()


class _RadioRequestHandler(BaseHTTPRequestHandler):
    service: EpisodeService
    server_version = "VibeFMHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        static_name = STATIC_FILES.get(path)
        if static_name and self._serve_static(static_name):
            return

        if path in {"/", "/api", "/api/"}:
            self._send_json(
                {
                    "name": "VibeFM API",
                    "status": "ok",
                    "ui": "Open radio.html (or radio_test.html) in your browser.",
                }
            )
            return

        parts = _path_parts(path)
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

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/episodes":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        payload = self._read_json_body()
        job = self.service.create_episode(payload)
        self._send_json(
            {
                "episode_id": job.id,
                "status_url": f"/api/episodes/{job.id}",
                "events_url": f"/api/episodes/{job.id}/events",
                "audio_url": f"/api/episodes/{job.id}/audio",
            },
            status=HTTPStatus.ACCEPTED,
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

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

    def _serve_static(self, name: str) -> bool:
        static_dir = self.service.static_dir
        if not static_dir:
            return False
        path = (static_dir / name).resolve()
        try:
            path.relative_to(static_dir.resolve())
        except ValueError:
            return False
        if not path.is_file():
            return False
        self._send_file(path, content_type=_web_content_type(path))
        return True

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
) -> dict[str, Any]:
    segments = [
        {
            "type": "intro",
            "voice": "host",
            "text": (
                f"...and you are tuned to {station_name}, where the signal is running "
                f"{style}. This is a local no-model test for a {duration} station."
            ),
        },
        {
            "type": "weather",
            "voice": "host",
            "text": (
                f"The weather check for {weather_name}: clear demo skies, twenty one "
                "degrees Celsius, and a light breeze in the mix."
            ),
        },
    ]
    for topic in topics:
        segments.append(
            {
                "type": "news",
                "voice": "host",
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


def _clean_string(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _clean_topics(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["artificial intelligence", "startups", "music technology"]
    topics = [str(item).strip() for item in value if str(item).strip()]
    return topics[:5] or ["artificial intelligence", "startups", "music technology"]


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
    if "topics" in payload:
        news = replace(news, topics=_clean_topics(payload.get("topics")))
    rss_feeds = _clean_rss_feeds(
        payload.get("rss_feeds", payload.get("rss_urls", payload.get("rss")))
    )
    if rss_feeds:
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

    return replace(config, **updates)


def _resolve_config_path(path: Path) -> Path:
    if not path.exists() and path == Path("config.yaml"):
        return Path("config.example.yaml")
    return path


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
        feeds.append(url)
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


def _web_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"


def _slug(value: Any) -> str:
    text = "".join(char.lower() if char.isalnum() else "-" for char in str(value))
    return "-".join(part for part in text.split("-") if part) or "segment"


def _mock_segment_seconds(text: str) -> float:
    return min(6.0, max(1.4, len(text) / 42))
