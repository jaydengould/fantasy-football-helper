"""Fetching, caching, and joining of all external data into list[Player]."""
import csv
import io
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
TIMEOUT_SECONDS = 5


def _requests_get(url: str) -> str:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.text


def fetch_json(
    url: str,
    cache_key: str,
    ttl_seconds: int = 86_400,
    cache_dir: Path = CACHE_DIR,
    fetcher: Callable[[str], str] | None = None,
) -> Any:
    """Fetch JSON with a write-through disk cache and stale-on-failure fallback.

    Draft night depends on this: a failed refresh must degrade to stale data,
    never to an exception, whenever any cached copy exists.
    """
    fetcher = fetcher or _requests_get
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache_key}.json"

    # Fresh cache path: try to load if within TTL.
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        try:
            return json.loads(path.read_text())
        except Exception as e:
            log.warning("corrupt cache for %s (%s); refetching", cache_key, e)
            # Fall through to fetch fresh data below.

    # Fetch fresh data.
    try:
        text = fetcher(url)
    except Exception as exc:
        # Stale fallback: if fetch fails and cache exists, use it despite corruption risk.
        if path.exists():
            try:
                log.warning("fetch failed for %s (%s); using stale cache", cache_key, exc)
                return json.loads(path.read_text())
            except Exception:
                # Cache is corrupt; re-raise the original fetch exception.
                log.warning("stale cache also corrupt for %s; raising original fetch error", cache_key)
                raise exc
        raise

    # Write cache atomically: write to temp file, then replace.
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=cache_key, suffix=".json")
        os.write(fd, text.encode("utf-8"))
        os.close(fd)
        fd = None
        os.replace(tmp_path, path)
    except Exception:
        if fd is not None:
            os.close(fd)
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise

    return json.loads(text)


SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
CROSSWALK_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
)
DRAFTABLE = {"QB", "RB", "WR", "TE", "K", "DEF"}


@dataclass
class Player:
    sleeper_id: str
    name: str
    position: str
    team: str | None
    yahoo_id: str | None = None
    injury_status: str | None = None
    proj_pts: float = 0.0
    adp: float = 999.0
    adp_stdev: float | None = None
    bye: int | None = None

    @property
    def match_key(self) -> str:
        """Key for the FFC fuzzy join ONLY. Never used for ID-keyed sources."""
        return f"{norm_name(self.name)}|{self.position}|{self.team or ''}"


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def build_players(raw: dict, crosswalk: dict[str, str]) -> dict[str, Player]:
    """Join the Sleeper player DB to the DynastyProcess crosswalk BY ID.

    Sleeper's own yahoo_id is unusable (0/302 rookies, 13/692 sophomores at
    design time), which is why the external crosswalk exists.
    """
    out: dict[str, Player] = {}
    for pid, p in raw.items():
        if not p.get("active") or p.get("position") not in DRAFTABLE:
            continue
        out[pid] = Player(
            sleeper_id=pid,
            name=p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            position=p["position"],
            team=p.get("team"),
            yahoo_id=crosswalk.get(pid),
            injury_status=p.get("injury_status"),
        )
    return out


def load_crosswalk(cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> dict[str, str]:
    """sleeper_id -> yahoo_id. Cached as JSON so fetch_json can own the caching."""
    fetcher = fetcher or _requests_get
    path = Path(cache_dir) / "crosswalk.json"
    if path.exists() and (time.time() - path.stat().st_mtime) < 86_400:
        return json.loads(path.read_text())
    try:
        text = fetcher(CROSSWALK_URL)
    except Exception as exc:
        if path.exists():
            log.warning("crosswalk fetch failed (%s); using stale cache", exc)
            return json.loads(path.read_text())
        raise
    rows = csv.DictReader(io.StringIO(text))
    mapping = {
        r["sleeper_id"]: r["yahoo_id"]
        for r in rows
        if r.get("sleeper_id", "").strip() and r.get("yahoo_id", "").strip() not in ("", "NA")
    }
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping))
    return mapping


def load_players(cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> dict[str, Player]:
    raw = fetch_json(SLEEPER_PLAYERS_URL, "sleeper_players", cache_dir=cache_dir, fetcher=fetcher)
    crosswalk = load_crosswalk(cache_dir=cache_dir, fetcher=fetcher)
    return build_players(raw, crosswalk)
