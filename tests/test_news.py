import json
from pathlib import Path

import pytest

from ffhelper.news import FEEDS, Headline, load_headlines, parse_rss

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Bears sign a kicker</title>
        <link>https://example.com/a</link>
        <pubDate>Wed, 03 Sep 2026 12:00:00 GMT</pubDate></item>
  <item><title>No link here</title></item>
</channel></rss>"""


def test_parse_rss_skips_items_without_a_link():
    """A headline with no URL is not a headline -- it is an unclickable claim."""
    out = parse_rss(SAMPLE, "espn")
    assert len(out) == 1
    assert out[0].title == "Bears sign a kicker"
    assert out[0].url == "https://example.com/a"
    assert out[0].source == "espn"


def test_parse_rss_returns_empty_on_malformed_xml():
    """A broken feed is an absent panel, never a crashed homepage."""
    assert parse_rss("<not xml", "espn") == []


def test_parse_rss_captures_pubdate():
    out = parse_rss(SAMPLE, "espn")
    assert out[0].published == "Wed, 03 Sep 2026 12:00:00 GMT"


def test_load_headlines_across_feeds(tmp_path: Path):
    """Two feeds, both good: headlines from each, tagged with their own source,
    and no failure notes."""
    feeds = {"espn": "http://espn.example/rss", "pft": "http://pft.example/rss"}

    def fetcher(url: str) -> str:
        source = "espn" if "espn" in url else "pft"
        return SAMPLE.replace("Bears sign a kicker", f"{source} headline")

    hs, notes = load_headlines(feeds, fetcher=fetcher, cache_dir=tmp_path)
    assert notes == []
    assert {h.source for h in hs} == {"espn", "pft"}
    assert len(hs) == 2


def test_load_headlines_one_feed_down_notes_it_and_keeps_the_other(tmp_path: Path):
    """A dead feed is a note, not a crash, and does not take the healthy feed
    down with it."""
    feeds = {"espn": "http://espn.example/rss", "pft": "http://pft.example/rss"}

    def fetcher(url: str) -> str:
        if "pft" in url:
            raise ConnectionError("feed unreachable")
        return SAMPLE

    hs, notes = load_headlines(feeds, fetcher=fetcher, cache_dir=tmp_path)
    assert len(hs) == 1
    assert hs[0].source == "espn"
    assert len(notes) == 1
    assert "pft" in notes[0]


def test_feeds_has_the_three_verified_sources():
    assert set(FEEDS) == {"espn", "pft", "bears"}
