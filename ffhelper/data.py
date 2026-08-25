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


def _try_read_cache(path: Path, ttl_seconds: float | None) -> tuple[bool, Any]:
    """Read+parse path if present and parseable. ttl_seconds=None skips the freshness
    check (a stale read). Returns (usable, value); usable=False covers missing/stale/corrupt."""
    if not path.exists() or (ttl_seconds is not None and (time.time() - path.stat().st_mtime) >= ttl_seconds):
        return False, None
    try:
        return True, json.loads(path.read_text())
    except Exception:
        return False, None


def _stale_fallback(path: Path, exc: Exception, label: str) -> Any:
    """On fetch failure: return the stale cache if still parseable, else re-raise exc."""
    ok, value = _try_read_cache(path, None)
    if ok:
        log.warning("fetch failed for %s (%s); using stale cache", label, exc)
        return value
    log.warning("no usable stale cache for %s; raising original fetch error", label)
    raise exc


def _write_cache_atomic(path: Path, cache_dir: Path, text: str) -> None:
    """tempfile.mkstemp + os.replace so a reader never sees a partial cache file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=path.stem, suffix=".json")
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
    path = cache_dir / f"{cache_key}.json"

    fresh, value = _try_read_cache(path, ttl_seconds)
    if fresh:
        return value

    try:
        text = fetcher(url)
    except Exception as exc:
        return _stale_fallback(path, exc, cache_key)

    _write_cache_atomic(path, cache_dir, text)
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
    """sleeper_id -> yahoo_id. Fetches the DynastyProcess CSV, transforms it into a
    mapping, and caches that mapping as JSON using the same atomic-write / tolerant-read
    / stale-on-failure cache mechanics as fetch_json."""
    fetcher = fetcher or _requests_get
    cache_dir = Path(cache_dir)
    path = cache_dir / "crosswalk.json"

    fresh, value = _try_read_cache(path, 86_400)
    if fresh:
        return value

    try:
        text = fetcher(CROSSWALK_URL)
    except Exception as exc:
        return _stale_fallback(path, exc, "crosswalk")

    rows = csv.DictReader(io.StringIO(text))
    mapping = {
        r["sleeper_id"]: r["yahoo_id"]
        for r in rows
        if r.get("sleeper_id", "").strip() and r.get("yahoo_id", "").strip() not in ("", "NA")
    }
    _write_cache_atomic(path, cache_dir, json.dumps(mapping))
    return mapping


def load_players(cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> dict[str, Player]:
    raw = fetch_json(SLEEPER_PLAYERS_URL, "sleeper_players", cache_dir=cache_dir, fetcher=fetcher)
    crosswalk = load_crosswalk(cache_dir=cache_dir, fetcher=fetcher)
    return build_players(raw, crosswalk)
