from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unittest.mock

from personalized_radio_station.config import load_config
from personalized_radio_station.news import NewsItem
from personalized_radio_station.script import _build_prompt, generate_script
from personalized_radio_station.weather import WeatherReport


class ScriptTests(unittest.TestCase):
    def test_prompt_requests_time_of_day_greeting_and_single_voice(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """
station_name: "Test Station"
style: "brief"
duration: "18 minutes"

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
  single_voice: true
  primary_voice: "host"
""".strip()
                + "\n"
            )
            config = load_config(config_path)

        prompt = _build_prompt(
            [
                NewsItem(
                    topic="ai",
                    title="A story",
                    link="https://example.com",
                    published_at=None,
                    source="Example",
                    summary=None,
                )
            ],
            WeatherReport(
                location="Lisbon",
                temperature_c=20,
                apparent_temperature_c=20,
                precipitation_mm=0,
                wind_speed_kmh=5,
                weather_code=1,
                local_time="2025-05-09T08:30",
                time_of_day="morning",
            ),
            config,
        )

        self.assertNotIn("already_on_air_listener_just_tuned_in", prompt)
        self.assertNotIn("already mid-conversation", prompt)
        self.assertIn("DO NOT produce an `intro` segment", prompt)
        self.assertIn("pre-recorded station ID", prompt)
        self.assertIn("Welcome to Test Station.", prompt)
        self.assertIn("NATURAL DJ ROLL-IN", prompt)
        self.assertIn("DO NOT greet the listener again", prompt)
        self.assertIn("DO NOT say 'welcome'", prompt)
        self.assertIn('"type": "news|outro"', prompt)
        self.assertIn('"time_of_day": "morning"', prompt)
        self.assertIn('Use the voice label \\"host\\" for every segment.', prompt)
        self.assertIn("Casual tone = warm, vibey", prompt)
        self.assertIn("Professional = crisper framing", prompt)
        self.assertIn('"target_duration": "18 minutes"', prompt)
        self.assertIn('"speech_rate_words_per_minute": 155', prompt)
        self.assertIn('"target_word_count": 2790', prompt)
        self.assertIn('"min": 2567', prompt)
        self.assertIn('"max": 3013', prompt)
        self.assertIn("EVERY spoken news claim must trace", prompt)
        self.assertIn("DO NOT invent news, businesses", prompt)
        self.assertIn(
            "One news segment per item in `news[]`, in the order provided.", prompt
        )
        self.assertIn("DO NOT produce a weather segment", prompt)
        self.assertIn("BANNED outros:", prompt)

    def test_generate_script_revises_once_when_word_count_is_outside_range(
        self,
    ) -> None:
        config = _config(
            """
station_name: "Test Station"
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
  model: "openrouter/openrouter/auto"

tts:
  enabled: true
  provider: "mock"
  single_voice: true
  primary_voice: "host"
  words_per_minute: 10
""".strip()
        )

        responses = [
            '{"title":"Test","segments":[{"type":"intro","voice":"host","text":"one two"}]}',
            '{"title":"Test","segments":[{"type":"intro","voice":"host","text":"one two three four five six seven eight nine ten"}]}',
        ]
        calls = []

        def fake_generate_text(messages, ai_config, api_keys=None):
            calls.append(messages)
            return responses.pop(0)

        with unittest.mock.patch(
            "personalized_radio_station.script.generate_text",
            side_effect=fake_generate_text,
        ):
            episode = generate_script(_news(), _weather(), config)

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            episode["generation"]["word_budget_revision"]["reason"],
            "too_short",
        )
        self.assertEqual(
            episode["generation"]["word_budget_revision"]["initial_word_count"],
            2,
        )
        self.assertEqual(
            episode["generation"]["word_budget_revision"]["revised_word_count"],
            10,
        )

    def test_generate_script_skips_revision_when_within_range(self) -> None:
        config = _config(
            """
station_name: "Test Station"
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
  model: "openrouter/openrouter/auto"

tts:
  enabled: true
  provider: "mock"
  single_voice: true
  primary_voice: "host"
  words_per_minute: 10
""".strip()
        )
        response = (
            '{"title":"Test","segments":[{"type":"intro","voice":"host",'
            '"text":"one two three four five six seven eight nine ten"}]}'
        )

        with unittest.mock.patch(
            "personalized_radio_station.script.generate_text",
            return_value=response,
        ) as generate_mock:
            episode = generate_script(_news(), _weather(), config)

        self.assertEqual(generate_mock.call_count, 1)
        self.assertFalse(episode["generation"]["word_budget_revision"]["revised"])
        self.assertEqual(
            episode["generation"]["word_budget_revision"]["reason"],
            "within_range",
        )

    def test_generate_script_skips_revision_for_unlimited_duration(self) -> None:
        config = _config(
            """
station_name: "Test Station"
style: "brief"
duration: "unlimited"

news:
  topics:
    - "ai"

weather:
  name: "Lisbon"
  latitude: 38.7
  longitude: -9.1

ai:
  model: "openrouter/openrouter/auto"

tts:
  enabled: true
  provider: "mock"
""".strip()
        )

        with unittest.mock.patch(
            "personalized_radio_station.script.generate_text",
            return_value='{"title":"Test","segments":[{"type":"intro","voice":"host","text":"one"}]}',
        ) as generate_mock:
            episode = generate_script(_news(), _weather(), config)

        self.assertEqual(generate_mock.call_count, 1)
        self.assertEqual(
            episode["generation"]["word_budget_revision"]["reason"],
            "unlimited_duration",
        )


def _config(text: str):
    with TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        config_path.write_text(text + "\n")
        return load_config(config_path)


def _news() -> list[NewsItem]:
    return [
        NewsItem(
            topic="ai",
            title="A story",
            link="https://example.com",
            published_at=None,
            source="Example",
            summary=None,
        )
    ]


def _weather() -> WeatherReport:
    return WeatherReport(
        location="Lisbon",
        temperature_c=20,
        apparent_temperature_c=20,
        precipitation_mm=0,
        wind_speed_kmh=5,
        weather_code=1,
    )


if __name__ == "__main__":
    unittest.main()
