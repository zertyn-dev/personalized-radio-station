from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from personalized_radio_station.config import load_config
from personalized_radio_station.hosts import apply_host_profile, host_style


class HostProfileTests(unittest.TestCase):
    def test_professional_duo_links_style_segment_labels_and_tts_voices(self) -> None:
        config = _config()

        configured = apply_host_profile(config, "professional", "male", "duo")

        self.assertIn("slightly more expert", configured.style)
        self.assertFalse(configured.tts.single_voice)
        self.assertEqual(configured.tts.primary_voice, "host")
        self.assertEqual(configured.voices["intro"], "host")
        self.assertEqual(configured.voices["news"], "cohost")
        self.assertEqual(configured.tts.voices["host"].voice, "pNInz6obpgDQGcFmaJgB")
        self.assertEqual(configured.tts.voices["cohost"].voice, "ErXwobaYiN019PkySvjV")
        self.assertIn("male radio host", configured.tts.voices["host"].instructions)

    def test_casual_solo_links_to_vibe_forward_single_voice(self) -> None:
        config = _config()

        configured = apply_host_profile(config, "casual", "female", "solo")

        self.assertIn("vibe-forward", configured.style)
        self.assertTrue(configured.tts.single_voice)
        self.assertEqual(configured.voices["news"], "host")
        self.assertEqual(configured.tts.voices["host"].voice, "21m00Tcm4TlvDq8ikWAM")
        self.assertNotIn("cohost", configured.voices.values())

    def test_host_style_names_the_shape(self) -> None:
        style = host_style("professional", "female", "duo")

        self.assertIn("slightly more expert", style)
        self.assertIn("female-led", style)
        self.assertIn("two-host handoff", style)


def _config():
    with TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        config_path.write_text(
            """
station_name: "Test"
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
        return load_config(config_path)


if __name__ == "__main__":
    unittest.main()
