"""Pick feeds. Sleeper and Yahoo are interchangeable behind PickFeed.

Nothing downstream may reference a concrete feed class by name -- the engine
never knows which platform it is serving.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ffhelper.data import CACHE_DIR, fetch_json

SLEEPER_PICKS_URL = "https://api.sleeper.app/v1/draft/{draft_id}/picks"


@dataclass(frozen=True)
class Pick:
    pick_no: int
    sleeper_id: str
    roster_id: int | None = None


class PickFeed(Protocol):
    def get_picks(self) -> list[Pick]:
        ...


def parse_sleeper_picks(raw: list[dict]) -> list[Pick]:
    picks = [
        Pick(
            pick_no=int(row["pick_no"]),
            sleeper_id=str(row["player_id"]),
            roster_id=row.get("roster_id"),
        )
        for row in raw
        if row.get("player_id") and row.get("pick_no") is not None
    ]
    return sorted(picks, key=lambda p: p.pick_no)


class SleeperFeed:
    def __init__(self, draft_id: str, fetcher: Callable[[str], str] | None = None,
                 cache_dir: Path = CACHE_DIR):
        self.draft_id = draft_id
        self.fetcher = fetcher
        self.cache_dir = cache_dir

    def get_picks(self) -> list[Pick]:
        raw = fetch_json(
            SLEEPER_PICKS_URL.format(draft_id=self.draft_id),
            f"picks_{self.draft_id}",
            ttl_seconds=0,          # live data; never serve from cache on success
            cache_dir=self.cache_dir,
            fetcher=self.fetcher,
        )
        return parse_sleeper_picks(raw)
