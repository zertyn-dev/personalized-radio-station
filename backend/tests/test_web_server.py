from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import Request, urlopen
import json
import threading
import time
import unittest

from personalized_radio_station.config import DEFAULT_RSS_FEEDS
from personalized_radio_station.news import NewsItem
from personalized_radio_station.weather import WeatherReport
from personalized_radio_station.web_server import create_server


class WebServerTests(unittest.TestCase):
    def test_api_creates_episode_streams_events_and_serves_audio(self) -> None:
        with TemporaryDirectory() as temp_dir:
            server = create_server(
                host="127.0.0.1",
                port=0,
                output_dir=Path(temp_dir) / "episodes",
                demo_delay=0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"

            try:
                index = _get_text(f"{base_url}/")
                self.assertIn("Console-7", index)
                api_info = _get_json(f"{base_url}/api")
                self.assertEqual(api_info["status"], "ok")
                self.assertEqual(api_info["ui"], "/")

                job = _post_json(
                    f"{base_url}/api/episodes",
                    {
                        "station_name": "Test FM",
                        "topics": ["ai", "weather"],
                        "duration_minutes": 3,
                    },
                )
                self.assertIn("episode_id", job)
                self.assertIn("/events", job["events_url"])

                events = _read_events(f"{base_url}{job['events_url']}")
                event_types = [event["event"] for event in events]
                self.assertIn("script_ready", event_types)
                self.assertIn("segment_ready", event_types)
                self.assertIn("complete", event_types)
                self.assertTrue(
                    all(
                        "elapsed_seconds" in json.loads(event["data"])
                        for event in events
                    )
                )

                status = _get_json(f"{base_url}{job['status_url']}")
                self.assertEqual(status["status"], "complete")
                self.assertIn("elapsed_seconds", status)
                ready_segments = [
                    segment for segment in status["segments"] if segment["status"] == "ready"
                ]
                self.assertGreaterEqual(len(ready_segments), 4)
                episode = json.loads(
                    (Path(temp_dir) / "episodes" / job["episode_id"] / "episode.json").read_text()
                )
                self.assertEqual(episode["timing"]["target_duration"], "3 minutes")

                segment_audio = _get_bytes(f"{base_url}{ready_segments[0]['audio_url']}")
                self.assertEqual(segment_audio[:4], b"RIFF")

                final_audio = _get_bytes(f"{base_url}{status['audio_url']}")
                self.assertEqual(final_audio[:4], b"RIFF")
            finally:
                server.shutdown()
                server.server_close()

    def test_real_mode_uses_sources_script_and_tts_without_mock_api_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
station_name: "Config FM"
style: "brief"
duration: "1 minute"

news:
  topics:
    - "ai"

weather:
  name: "Lisbon"
  latitude: 38.7
  longitude: -9.1

ai:
  model: "mock"

tts:
  enabled: true
  provider: "mock"
""".strip()
                + "\n"
            )
            server = create_server(
                host="127.0.0.1",
                port=0,
                output_dir=root / "episodes",
                config_path=config_path,
                env_path=root / "missing.env",
                demo_delay=0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            news_items = [
                NewsItem(
                    topic="ai",
                    title="Real source test",
                    link="https://example.com/story",
                    published_at=None,
                    source="Example News",
                    summary="Summary",
                )
            ]
            weather = WeatherReport(
                location="Lisbon",
                temperature_c=21.0,
                apparent_temperature_c=21.0,
                precipitation_mm=0.0,
                wind_speed_kmh=8.0,
                weather_code=1,
            )
            episode = {
                "title": "Real Mode Test",
                "segments": [
                    {"type": "intro", "voice": "host", "text": "Real intro."},
                    {"type": "news", "voice": "host", "text": "Real source item."},
                ],
            }

            try:
                with patch(
                    "personalized_radio_station.web_server.assert_runtime_ready"
                ) as ready_mock, patch(
                    "personalized_radio_station.web_server.fetch_news",
                    return_value=news_items,
                ) as news_mock, patch(
                    "personalized_radio_station.web_server.fetch_weather",
                    return_value=weather,
                ) as weather_mock, patch(
                    "personalized_radio_station.web_server.generate_script",
                    return_value=episode,
                ) as script_mock:
                    job = _post_json(
                        f"{base_url}/api/episodes",
                        {
                            "mode": "real",
                            "station_name": "Request FM",
                            "topics": ["markets"],
                            "rss_feeds": [
                                "https://example.com/custom.xml",
                                "file:///tmp/not-rss.xml",
                            ],
                            "weather_name": "Porto",
                        },
                    )
                    events = _read_events(f"{base_url}{job['events_url']}")

                ready_mock.assert_called_once()
                news_mock.assert_called_once()
                fetched_config = news_mock.call_args.args[0]
                self.assertEqual(fetched_config.rss_feeds[: len(DEFAULT_RSS_FEEDS)], DEFAULT_RSS_FEEDS)
                self.assertIn("https://example.com/custom.xml", fetched_config.rss_feeds)
                self.assertNotIn("file:///tmp/not-rss.xml", fetched_config.rss_feeds)
                weather_mock.assert_called_once()
                script_mock.assert_called_once()
                statuses = [
                    json.loads(event["data"])["status"]
                    for event in events
                    if event["event"] == "status"
                ]
                self.assertIn("checking_runtime", statuses)
                status = _get_json(f"{base_url}{job['status_url']}")
                self.assertEqual(status["mode"], "real")
                self.assertEqual(status["status"], "complete")
                self.assertEqual(len(status["segments"]), 2)
                self.assertTrue(status["audio_url"])
                self.assertEqual(_get_bytes(f"{base_url}{status['segments'][0]['audio_url']}")[:4], b"RIFF")
            finally:
                server.shutdown()
                server.server_close()

    def test_api_creates_vibe_and_uses_it_for_episode_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            server = create_server(
                host="127.0.0.1",
                port=0,
                output_dir=root / "episodes",
                db_path=root / "vibes.sqlite3",
                demo_delay=0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"

            try:
                created = _post_json(
                    f"{base_url}/api/vibes",
                    {
                        "name": "Builder Radio",
                        "source_preset_ids": ["hacker_news"],
                        "custom_rss_feeds": ["https://example.com/builders.xml"],
                        "tone": "professional",
                        "voice_gender": "male",
                        "host_format": "duo",
                    },
                )
                vibe = created["vibe"]
                self.assertEqual(vibe["name"], "Builder Radio")
                self.assertEqual(vibe["rss_feeds"][0], "https://hnrss.org/frontpage")

                vibes = _get_json(f"{base_url}/api/vibes")
                self.assertEqual(len(vibes["vibes"]), 1)
                self.assertIn("Hacker News", [preset["label"] for preset in vibes["presets"]])

                job = _post_json(
                    f"{base_url}/api/episodes",
                    {"vibe_id": vibe["id"], "duration_minutes": 1},
                )
                self.assertEqual(job["vibe"]["name"], "Builder Radio")
                _read_events(f"{base_url}{job['events_url']}")

                status = _get_json(f"{base_url}{job['status_url']}")
                self.assertEqual(status["status"], "complete")
                self.assertEqual(status["vibe"]["id"], vibe["id"])
                self.assertEqual(status["title"], "Builder Radio Test Signal")
                sources = json.loads(
                    (root / "episodes" / job["episode_id"] / "sources.json").read_text()
                )
                self.assertEqual(
                    sources["rss_feeds"],
                    [
                        "https://hnrss.org/frontpage",
                        "https://example.com/builders.xml",
                    ],
                )
                self.assertEqual(
                    [item["topic"] for item in sources["news"]],
                    ["hnrss.org", "example.com"],
                )
                self.assertEqual(sources["vibe"]["host_format"], "duo")
                episode = json.loads(
                    (root / "episodes" / job["episode_id"] / "episode.json").read_text()
                )
                self.assertEqual(len(episode["segments"]), 5)
            finally:
                server.shutdown()
                server.server_close()

    def test_audio_returns_accepted_before_generation_is_complete(self) -> None:
        with TemporaryDirectory() as temp_dir:
            server = create_server(
                host="127.0.0.1",
                port=0,
                output_dir=Path(temp_dir) / "episodes",
                demo_delay=0.1,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_address[1]}"

            try:
                job = _post_json(f"{base_url}/api/episodes", {})
                status_code, body = _get_status_and_json(f"{base_url}{job['audio_url']}")
                self.assertEqual(status_code, 202)
                self.assertEqual(body["error"], "Audio is not ready")
                self.assertTrue(_read_events(f"{base_url}{job['events_url']}"))
            finally:
                server.shutdown()
                server.server_close()


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict:
    return json.loads(_get_text(url))


def _get_status_and_json(url: str) -> tuple[int, dict]:
    with urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _get_bytes(url: str) -> bytes:
    with urlopen(url, timeout=5) as response:
        return response.read()


def _read_events(url: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    deadline = time.time() + 5

    with urlopen(url, timeout=5) as response:
        while time.time() < deadline:
            line = response.readline().decode("utf-8")
            if line == "":
                break
            line = line.rstrip("\n")
            if not line:
                if current:
                    events.append(current)
                    if current.get("event") in {"complete", "failed"}:
                        return events
                    current = {}
                continue
            if line.startswith("event: "):
                current["event"] = line.removeprefix("event: ")
            elif line.startswith("data: "):
                current["data"] = line.removeprefix("data: ")

    return events


if __name__ == "__main__":
    unittest.main()
