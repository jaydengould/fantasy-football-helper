"""NFL headlines from RSS. Decorative: nothing here feeds a number.

Parsed with stdlib xml.etree -- a feed reader is not worth a dependency for
three sources and one element shape. An unreachable or malformed feed yields
no headlines and a note; it never raises into the page, and it never renders
as a silently empty box.

NOT an input to any advice. `start_sit` sees projections, practice status and
injury designation, and nothing else. The panel sits apart from the advisory
sections on purpose, so its presence cannot imply the advice read it.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ffhelper.data import CACHE_DIR, fetch_text

# Verified 2026-09-03 through requests.get(url) -- the client this project's
# _requests_get actually sends (python-requests/2.x UA), not curl or a browser.
# All three: 200, plain RSS 2.0, item/title/link/pubDate as direct children,
# no Atom <entry> anywhere. The spec's PFT candidate
# (profootballtalk.nbcsports.com/feed/) 301-redirects to this one -- hardcoded
# as the resolved URL, since a redirect is a hop that can stop being served.
#
# ESPN's https://www.espn.com/espn/rss/nfl/news (and /rss/news) 403s this UA
# specifically -- verified reproducibly, not a fluke -- while a browser UA
# gets a 200. Do not re-add it and do not set a browser User-Agent on
# _requests_get to route around the refusal: that's shared fetch infra every
# other source in data.py rides on, and dressing up the client to get past a
# deliberate block works around the refusal rather than fixing anything.
# CBS replaces it; also checked and rejected: Yahoo's NFL RSS returns 200 but
# its "NFL" feed is actually college football content.
FEEDS = {
    "cbs": "https://www.cbssports.com/rss/headlines/nfl/",
    "pft": "https://www.nbcsports.com/profootballtalk.rss",
    "bears": "https://www.chicagobears.com/rss/news",
}


@dataclass
class Headline:
    title: str
    url: str
    source: str
    published: str | None


def parse_rss(xml_text: str, source: str) -> list[Headline]:
    """Every `<item>` with both a title and a link. A headline with no URL is
    not a headline -- it is an unclickable claim -- so it is skipped, not
    rendered with a dead link. Malformed XML yields no headlines at all.

    The `.strip()` calls below are load-bearing, not decorative: CBS wraps
    its <title> text in newlines and indentation, so dropping the strip would
    put literal whitespace padding around every CBS headline on the page.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.findall(".//item"):
        title = item.findtext("title")
        link = item.findtext("link")
        if not title or not link:
            continue
        published = item.findtext("pubDate")
        out.append(Headline(
            title=title.strip(),
            url=link.strip(),
            source=source,
            published=published.strip() if published else None,
        ))
    return out


def load_headlines(
    feeds: dict[str, str], fetcher: Callable[[str], str] | None = None,
    cache_dir: Path = CACHE_DIR,
) -> tuple[list[Headline], list[str]]:
    """Fetch and parse every feed. A feed that fails to fetch is dropped into
    `notes` and never takes the other feeds down with it -- one hour TTL, so a
    dead feed is retried on the next hour rather than pinned as broken."""
    headlines: list[Headline] = []
    notes: list[str] = []
    for source, url in feeds.items():
        try:
            text = fetch_text(url, f"news_{source}", ttl_seconds=3600,
                              cache_dir=cache_dir, fetcher=fetcher)
        except Exception as exc:                      # noqa: BLE001 - degrade, never crash the homepage
            notes.append(f"{source}: could not reach feed ({exc})")
            continue
        headlines.extend(parse_rss(text, source))
    return headlines, notes
