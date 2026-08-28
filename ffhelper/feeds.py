"""Pick feeds. Sleeper and Yahoo are interchangeable behind PickFeed.

Nothing downstream may reference a concrete feed class by name -- the engine
never knows which platform it is serving.
"""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ffhelper.data import CACHE_DIR, fetch_json

log = logging.getLogger(__name__)

SLEEPER_PICKS_URL = "https://api.sleeper.app/v1/draft/{draft_id}/picks"


@dataclass(frozen=True)
class Pick:
    pick_no: int
    sleeper_id: str
    roster_id: int | None = None
    # The seat that made the pick, 1-indexed, snake-aware (round 2 pick 13 is
    # slot 12). This -- NOT roster_id -- is how the user's own picks are found:
    # a Sleeper MOCK draft sets roster_id to None on every single pick, so
    # matching on it left my_roster empty for an entire 180-pick draft while
    # looking healthy. draft_slot is present in both mocks and league drafts,
    # and is exactly the value already configured as `league.draft_slot`.
    draft_slot: int | None = None


class PickFeed(Protocol):
    def get_picks(self) -> list[Pick]:
        ...


def parse_sleeper_picks(raw: list[dict]) -> list[Pick]:
    picks = []
    for row in raw:
        if not row.get("player_id") or row.get("pick_no") is None:
            continue
        try:
            pick_no = int(row["pick_no"])
        except (TypeError, ValueError):
            log.warning("skipping pick with non-numeric pick_no: %r", row)
            continue
        slot = row.get("draft_slot")
        picks.append(Pick(
            pick_no=pick_no,
            sleeper_id=str(row["player_id"]),
            roster_id=row.get("roster_id"),
            draft_slot=int(slot) if slot is not None else None,
        ))
    return sorted(picks, key=lambda p: p.pick_no)


class SleeperFeed:
    def __init__(self, draft_id: str, fetcher: Callable[[str], str] | None = None,
                 cache_dir: Path = CACHE_DIR):
        self.draft_id = draft_id
        self.fetcher = fetcher
        self.cache_dir = cache_dir

    def get_picks(self) -> list[Pick]:
        # Sleeper serves this endpoint through Cloudflare as
        # `public, s-maxage=86400, stale-while-revalidate=300`, so a plain poll
        # is answered from the edge and never reaches origin: measured
        # cf-cache-status HIT on every request with `age` climbing 516/517/518
        # across consecutive polls. Sleeper's own app uses a websocket, which is
        # why its UI runs seconds ahead of a board polling this URL.
        #
        # A `Cache-Control: no-cache` REQUEST header is ignored by their edge.
        # A unique query param is not -- MISS on every request, measured.
        #
        # Cost: RTT 146ms -> 303ms, against a 1000ms poll interval, so the
        # cadence does not change. 60 req/min at a 1s poll, against the
        # ~1000 req/min that gets an IP blocked.
        #
        # The CACHE KEY stays `picks_<draft_id>`: the URL now varies per call,
        # and keying the local cache on it would write a new file every poll.
        raw = fetch_json(
            f"{SLEEPER_PICKS_URL.format(draft_id=self.draft_id)}"
            f"?_={int(time.time() * 1000)}",
            f"picks_{self.draft_id}",
            ttl_seconds=0,          # live data; never serve from cache on success
            cache_dir=self.cache_dir,
            fetcher=self.fetcher,
            stale_ok=False,         # a failed poll must raise so the STALE banner can fire
        )
        return parse_sleeper_picks(raw)
