from unittest.mock import patch
import threading
import time
import unittest

from personalized_radio_station.config import NewsConfig
from personalized_radio_station.news import _parse_feed, fetch_news, normalize_feed_url


class NewsTests(unittest.TestCase):
    def test_fetch_news_fetches_google_and_rss_feeds_in_parallel(self) -> None:
        config = NewsConfig(
            topics=["ai"],
            rss_feeds=[
                "https://example.com/tech.xml",
                "https://example.com/products.xml",
            ],
        )
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_fetch(url: str) -> str:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            if "news.google.com" in url:
                return _rss("Google News", "Google story")
            if "tech.xml" in url:
                return _rss("Tech Feed", "Tech story")
            return _rss("Product Feed", "Product story")

        with patch("personalized_radio_station.news._fetch", side_effect=fake_fetch):
            items = fetch_news(config, limit_per_feed=1)

        self.assertGreater(max_active, 1)
        self.assertEqual(
            [item.title for item in items],
            ["Google story", "Tech story", "Product story"],
        )
        self.assertEqual(
            [item.source for item in items],
            ["Google News", "Tech Feed", "Product Feed"],
        )

    def test_parse_atom_feed(self) -> None:
        feed_xml = """
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Source</title>
  <entry>
    <title>Atom story</title>
    <link href="https://example.com/atom-story" />
    <updated>2026-05-09T12:00:00Z</updated>
    <summary>Short atom summary</summary>
  </entry>
</feed>
""".strip()

        items = _parse_feed(feed_xml, "fallback")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].topic, "fallback")
        self.assertEqual(items[0].link, "https://example.com/atom-story")
        self.assertEqual(items[0].summary, "Short atom summary")


def _rss(channel_title: str, item_title: str) -> str:
    return f"""
<rss version="2.0">
  <channel>
    <title>{channel_title}</title>
    <item>
      <title>{item_title}</title>
      <link>https://example.com/{item_title.replace(" ", "-").lower()}</link>
      <description><![CDATA[<p>Summary for {item_title}</p>]]></description>
    </item>
  </channel>
</rss>
""".strip()


class NormalizeFeedUrlTests(unittest.TestCase):
    def test_techcrunch_category_appends_feed(self) -> None:
        self.assertEqual(
            normalize_feed_url("https://techcrunch.com/category/security/"),
            "https://techcrunch.com/category/security/feed/",
        )
        self.assertEqual(
            normalize_feed_url("https://techcrunch.com/tag/openai"),
            "https://techcrunch.com/tag/openai/feed/",
        )
        self.assertEqual(
            normalize_feed_url("https://www.techcrunch.com/author/sarah/"),
            "https://www.techcrunch.com/author/sarah/feed/",
        )

    def test_techcrunch_already_feed_is_unchanged(self) -> None:
        url = "https://techcrunch.com/category/security/feed/"
        self.assertEqual(normalize_feed_url(url), url)

    def test_hn_algolia_search_rewrites_to_hnrss(self) -> None:
        self.assertEqual(
            normalize_feed_url("https://hn.algolia.com/?q=World+cup"),
            "https://hnrss.org/newest?q=World+cup",
        )
        self.assertEqual(
            normalize_feed_url("https://hn.algolia.com/?query=rust"),
            "https://hnrss.org/newest?q=rust",
        )

    def test_google_news_search_uses_rss_path(self) -> None:
        self.assertEqual(
            normalize_feed_url("https://news.google.com/search?q=potato+prices&hl=es"),
            "https://news.google.com/rss/search?q=potato+prices&hl=es",
        )

    def test_google_news_rss_url_is_unchanged(self) -> None:
        url = "https://news.google.com/rss/search?q=potato+prices"
        self.assertEqual(normalize_feed_url(url), url)

    def test_unknown_url_passes_through(self) -> None:
        url = "https://example.com/feed.xml"
        self.assertEqual(normalize_feed_url(url), url)

    def test_idempotent(self) -> None:
        for raw in [
            "https://techcrunch.com/category/security/",
            "https://hn.algolia.com/?q=World+cup",
            "https://news.google.com/search?q=hello",
            "https://example.com/feed.xml",
        ]:
            once = normalize_feed_url(raw)
            twice = normalize_feed_url(once)
            self.assertEqual(once, twice, f"not idempotent for {raw!r}")

    def test_empty_or_blank_passes_through(self) -> None:
        self.assertEqual(normalize_feed_url(""), "")
        self.assertEqual(normalize_feed_url("   "), "")


if __name__ == "__main__":
    unittest.main()
