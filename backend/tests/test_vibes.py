from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from personalized_radio_station.vibes import VibeStore


class VibeStoreTests(unittest.TestCase):
    def test_creates_persistent_vibe_with_presets_and_custom_feeds(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "vibefm.sqlite3"
            store = VibeStore(db_path)

            vibe = store.create_vibe(
                {
                    "name": "Builder Radio",
                    "source_preset_ids": ["Hacker News", "product_hunt", "hacker_news"],
                    "custom_rss_feeds": [
                        "https://example.com/feed.xml",
                        "https://example.com/feed.xml",
                    ],
                    "tone": "professional",
                    "voice_gender": "male",
                    "host_format": "duo",
                }
            )

            reloaded = VibeStore(db_path).get_vibe(vibe.id)

        self.assertIsNotNone(reloaded)
        assert reloaded is not None
        self.assertEqual(reloaded.name, "Builder Radio")
        self.assertEqual(reloaded.source_preset_ids, ["hacker_news", "product_hunt"])
        self.assertEqual(reloaded.custom_rss_feeds, ["https://example.com/feed.xml"])
        self.assertEqual(
            reloaded.rss_feeds,
            [
                "https://hnrss.org/frontpage",
                "https://www.producthunt.com/feed",
                "https://example.com/feed.xml",
            ],
        )
        self.assertEqual(reloaded.tone, "professional")
        self.assertEqual(reloaded.voice_gender, "male")
        self.assertEqual(reloaded.host_format, "duo")
        self.assertIn("slightly more expert", reloaded.style)
        self.assertIn("two-host handoff", reloaded.style)

    def test_allows_vibe_without_extra_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            vibe = VibeStore(Path(temp_dir) / "vibes.sqlite3").create_vibe(
                {"name": "Morning Show"}
            )

        self.assertEqual(
            vibe.source_preset_ids,
            ["google_news", "hacker_news", "techcrunch", "product_hunt"],
        )
        self.assertEqual(vibe.rss_feeds[0], "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        self.assertIn("https://hnrss.org/frontpage", vibe.rss_feeds)

    def test_rejects_invalid_host_options_and_feed_urls(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = VibeStore(Path(temp_dir) / "vibes.sqlite3")

            with self.assertRaisesRegex(ValueError, "tone"):
                store.create_vibe({"name": "Bad Tone", "tone": "sleepy"})

            with self.assertRaisesRegex(ValueError, "RSS feed"):
                store.create_vibe({"name": "Bad Feed", "custom_rss_feeds": ["file:///tmp/rss"]})


if __name__ == "__main__":
    unittest.main()
