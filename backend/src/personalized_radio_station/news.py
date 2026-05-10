from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from .config import NewsConfig


def normalize_feed_url(url: str) -> str:
    """Rewrite human-readable URLs to their RSS equivalents.

    Idempotent: applying twice is the same as applying once. Unknown URLs
    pass through unchanged.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        return raw
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path

    # TechCrunch category/tag/author pages: append /feed/ if missing.
    if host == "techcrunch.com":
        if re.match(r"^/(category|tag|author)/[^/]+/?$", path):
            new_path = path if path.endswith("/") else path + "/"
            new_path = new_path + "feed/"
            return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, ""))

    # HN Algolia search -> hnrss.org/newest?q=...
    if host == "hn.algolia.com":
        params = dict(parse_qsl(parts.query, keep_blank_values=False))
        query = params.get("q") or params.get("query")
        if query:
            return f"https://hnrss.org/newest?{urlencode({'q': query})}"

    # Google News human search URL -> RSS search URL.
    if host == "news.google.com" and path in {"/search", "/search/"}:
        return urlunsplit((parts.scheme, parts.netloc, "/rss/search", parts.query, ""))

    return raw


@dataclass(frozen=True)
class NewsItem:
    topic: str
    title: str
    link: str
    published_at: str | None
    source: str | None
    summary: str | None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class FeedRequest:
    topic: str
    url: str


def fetch_news(config: NewsConfig, limit_per_feed: int = 5) -> list[NewsItem]:
    return _fetch_feed_requests(_feed_requests(config), limit_per_feed)


def describe_news_sources(config: NewsConfig) -> str:
    parts: list[str] = []
    if config.topics:
        parts.append(f"Google News ({', '.join(config.topics)})")
    if config.rss_feeds:
        feed_count = len(config.rss_feeds)
        parts.append(f"{feed_count} RSS feed{'s' if feed_count != 1 else ''}")
    return "; ".join(parts) or "RSS feeds"


def _feed_requests(config: NewsConfig) -> list[FeedRequest]:
    requests = [
        FeedRequest(topic=f"Google News: {topic}", url=_google_news_url(topic, config))
        for topic in config.topics
    ]
    requests.extend(
        FeedRequest(topic=_topic_from_url(feed_url), url=feed_url)
        for feed_url in config.rss_feeds
        if _is_fetchable_url(feed_url)
    )
    return requests


def _fetch_feed_requests(
    requests: list[FeedRequest], limit_per_feed: int
) -> list[NewsItem]:
    if not requests:
        return []

    results: list[list[NewsItem]] = [[] for _ in requests]
    max_workers = min(8, len(requests))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_fetch_request_items, request, limit_per_feed): index
            for index, request in enumerate(requests)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception:
                results[index] = []

    items: list[NewsItem] = []
    for feed_items in results:
        items.extend(feed_items)
    return _dedupe_by_title(items)


def _fetch_request_items(request: FeedRequest, limit_per_feed: int) -> list[NewsItem]:
    feed_xml = _fetch(request.url)
    return _parse_feed(feed_xml, request.topic)[:limit_per_feed]


def _google_news_url(topic: str, config: NewsConfig) -> str:
    country = config.country.upper()
    language = config.language
    return (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(topic)}"
        f"&hl={quote_plus(language)}"
        f"&gl={quote_plus(country)}"
        f"&ceid={quote_plus(country + ':' + language.split('-')[0])}"
    )


def _fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "vibefm/0.1"})
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse_feed(feed_xml: str, topic: str) -> list[NewsItem]:
    root = ET.fromstring(feed_xml)
    channel = _child(root, "channel")
    if channel is not None and _children(channel, "item"):
        return _parse_rss_items(channel, topic)
    if _children(root, "item"):
        channel_title = _text(channel, "title") if channel is not None else None
        return _parse_rss_items(root, topic, source_title=channel_title)
    return _parse_atom_entries(root, topic)


def _parse_rss_items(
    channel: ET.Element, topic: str, source_title: str | None = None
) -> list[NewsItem]:
    channel_title = source_title or _text(channel, "title")
    parsed_items: list[NewsItem] = []

    for item in _children(channel, "item"):
        title = _text(item, "title") or "Untitled"
        parsed_items.append(
            NewsItem(
                topic=topic,
                title=title,
                link=_link(item) or "",
                published_at=_parse_date(
                    _text(item, "pubDate")
                    or _text(item, "published")
                    or _text(item, "date")
                ),
                source=_text(item, "source") or channel_title or topic,
                summary=_clean_html(
                    _text(item, "description")
                    or _text(item, "summary")
                    or _text(item, "encoded")
                ),
            )
        )

    return parsed_items


def _parse_atom_entries(root: ET.Element, topic: str) -> list[NewsItem]:
    feed_title = _text(root, "title")
    parsed_items: list[NewsItem] = []

    for entry in _children(root, "entry"):
        title = _text(entry, "title") or "Untitled"
        parsed_items.append(
            NewsItem(
                topic=topic,
                title=title,
                link=_link(entry) or "",
                published_at=_parse_date(
                    _text(entry, "published") or _text(entry, "updated")
                ),
                source=feed_title or topic,
                summary=_clean_html(_text(entry, "summary") or _text(entry, "content")),
            )
        )

    return parsed_items


def _text(node: ET.Element, child_name: str) -> str | None:
    child = _child(node, child_name)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _link(node: ET.Element) -> str | None:
    for child in _children(node, "link"):
        href = child.attrib.get("href", "").strip()
        if href:
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def _child(node: ET.Element, child_name: str) -> ET.Element | None:
    for child in list(node):
        if _local_name(child.tag) == child_name:
            return child
    return None


def _children(node: ET.Element, child_name: str) -> list[ET.Element]:
    return [child for child in list(node) if _local_name(child.tag) == child_name]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def _clean_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", unescape(text))
    return text.strip()


def _dedupe_by_title(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    deduped: list[NewsItem] = []

    for item in items:
        key = re.sub(r"\W+", "", item.title.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _topic_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc.removeprefix("www.") or url


def _is_fetchable_url(url: str) -> bool:
    return urlsplit(url).scheme.lower() in {"http", "https"}
