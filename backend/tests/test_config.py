from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from personalized_radio_station.config import DEFAULT_RSS_FEEDS, load_config, parse_duration


class ConfigTests(unittest.TestCase):
    def test_parse_duration_values(self) -> None:
        self.assertEqual(parse_duration("18 minutes").minutes, 18)
        self.assertEqual(parse_duration("18m").label, "18 minutes")
        self.assertEqual(parse_duration("1 hour").minutes, 60)
        self.assertIsNone(parse_duration("unlimited").minutes)
        self.assertEqual(parse_duration("unlimited").label, "unlimited")

    def test_example_config_uses_openrouter_gpt_oss_nitro_by_default(self) -> None:
        example_text = Path("config.example.yaml").read_text()
        config = load_config("config.example.yaml")

        self.assertNotIn("station_name:", example_text)
        self.assertNotIn("\nduration:", example_text)
        self.assertNotIn("topics:", example_text)
        self.assertNotIn("rss_feeds:", example_text)
        self.assertEqual(config.ai.model, "openrouter/openai/gpt-oss-20b:nitro")
        self.assertEqual(config.ai.api_key_env, "OPENROUTER_API_KEY")
        self.assertEqual(config.ai.max_tokens, 4000)
        self.assertEqual(config.ai.reasoning, {"effort": "low", "exclude": True})
        self.assertEqual(config.tts.provider, "elevenlabs")
        self.assertEqual(config.tts.model, "elevenlabs/eleven_turbo_v2_5")
        self.assertEqual(config.tts.api_key_env, "ELEVENLABS_API_KEY")
        self.assertTrue(config.tts.enabled)
        self.assertTrue(config.tts.single_voice)
        self.assertEqual(config.tts.primary_voice, "host")
        self.assertEqual(config.tts.words_per_minute, 155)
        self.assertEqual(config.tts.voices["host"].words_per_minute, 155)
        self.assertEqual(config.duration.label, "5 minutes")
        self.assertEqual(config.news.rss_feeds, DEFAULT_RSS_FEEDS)

    def test_loads_ai_and_tts_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
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
  model: "openrouter/meta-llama/llama-3.1-8b-instruct"
  api_key_env: "OPENROUTER_API_KEY"

tts:
  enabled: true
  provider: "elevenlabs"
  model: "elevenlabs/eleven_multilingual_v2"
  voices:
    host:
      voice: "alloy"
      words_per_minute: 145
      settings:
        stability: 0.4
        similarity_boost: 0.8
""".strip()
                + "\n"
            )

            config = load_config(config_path)

        self.assertEqual(config.station_name, "Test Station")
        self.assertTrue(config.duration.is_unlimited)
        self.assertEqual(config.ai.api_key_env, "OPENROUTER_API_KEY")
        self.assertEqual(config.news.rss_feeds, DEFAULT_RSS_FEEDS)
        self.assertTrue(config.tts.enabled)
        self.assertEqual(config.tts.provider, "elevenlabs")
        self.assertTrue(config.tts.single_voice)
        self.assertEqual(config.tts.voices["host"].voice, "alloy")
        self.assertEqual(config.tts.voices["host"].words_per_minute, 145)
        self.assertEqual(config.tts.voices["host"].settings["stability"], 0.4)


if __name__ == "__main__":
    unittest.main()
