# Phases 0–1: Yahoo Auth + Draft Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working live-draft recommendation tool — auto-synced league settings, custom-scored projections, VBD/VONA rankings, and an auto-refreshing terminal board — plus a completed Yahoo OAuth handshake that de-risks Phase 2.

**Architecture:** Sleeper is the data backbone for both leagues (projections, player DB, ADP); Yahoo and Sleeper are interchangeable pick feeds behind one protocol. All ranking logic lives in a pure `value.py` with no I/O, so it tests without a network. FFC ADP is a non-load-bearing enrichment layer applied only after the ID-keyed board is complete.

**Tech Stack:** Python 3.12, `requests`, `yfpy`, `pytest` (dev). Stdlib `tomllib`, `statistics.NormalDist`, `sqlite3`. No pandas, no scipy, no PyYAML.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12.** Stdlib first.
- **Runtime dependencies are `requests` and `yfpy` only.** `dash` arrives in Phase 3. `pytest` is dev-only. Adding anything else needs a reason stdlib cannot cover.
- **`value.py` is pure.** No I/O, no network, no module-level mutable state. If something in `value.py` wants to fetch, the design is wrong.
- **No module-level league state.** Every function takes league context explicitly.
- **Never join load-bearing data on player name.** Projections, player DB, and crosswalk join on integer IDs. FFC is the sole fuzzy join, enrichment-only, applied last. Match key is (normalized full name, position, team).
- **Never blend projection rank with ADP rank into one number.** Surface divergence as a flag.
- **Unmatched players are printed, never silently dropped.**
- **The live loop never dies.** Wrapped poll, logged exception, `continue`.
- **Never commit bulk projections or player data.** Tests use synthetic players plus two hardcoded real records.
- **GIT: commit on the feature branch only.** Work happens on `phase-0-1-draft-engine`. You **may** `git add` and `git commit` there — the "Ready to commit" steps below mean *do* commit, with the suggested message. You may **never** run `git push`, `git merge`, `git rebase`, or any command touching `main`. Pushing and merging belong to the user.

---

## Scope note

This plan covers **Phase 0 and Phase 1 only**, not Phases 0–3 as originally requested.

Phase 1 is a complete, working, independently useful tool — it is exactly the "guaranteed floor" the spec describes for Sept 1. Phases 2 and 3 get their own plans, for a concrete reason rather than convenience: **Phase 2's task detail depends on what Phase 0 discovers.** We do not yet know the Yahoo league's id, size, or scoring, nor whether `draft_results` behaves as the library docs claim during a live draft. Writing detailed Yahoo tasks now would be inventing specifics we are about to learn. Phase 3 (Dash) depends only on `value.py`, which this plan freezes, so it can be planned any time.

## File structure

| File | Responsibility |
| --- | --- |
| `pyproject.toml` | deps, pytest config (`.venv` created in Task 0; all `python`/`pytest` commands mean `.venv/bin/...`) |
| `.gitignore` | `.env`, `.cache/`, `*.db`, `__pycache__` |
| `.env.example` | Yahoo credential template |
| `config.toml` | league list + engine tunables |
| `ffhelper/config.py` | `League` dataclass, load `config.toml` + `.env` |
| `ffhelper/data.py` | HTTP + disk cache, fetch all sources, join → `list[Player]` |
| `ffhelper/value.py` | **PURE.** scoring, VBD, tiers, survival, VONA, `lineup_value`, snake math |
| `ffhelper/feeds.py` | `PickFeed` protocol + `SleeperFeed` |
| `ffhelper/cli.py` | run loop, render, manual mark-drafted, `preflight` subcommand |
| `scripts/yahoo_auth.py` | Phase 0 one-time handshake + settings dump |
| `tests/test_value.py` | pure engine tests |
| `tests/test_data.py` | join and scoring tests |

---

### Task 0: Environment setup

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: a working `.venv` with `requests`, `yfpy`, and `pytest` importable

Nothing else in this plan runs without this. There is currently no virtualenv and `yfpy` is not installed, so Task 1's script would fail at its import line.

Note the repo has a public GitHub remote (`github.com/jaydengould/fantasy-football-helper`), which makes the `.gitignore` entries below load-bearing rather than tidy — `.env` and `.yahoo_token.json` must never reach it.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "ffhelper"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["requests>=2.32", "yfpy>=17.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore` and `.env.example`**

`.gitignore`:
```
.env
.yahoo_token.json
.cache/
*.db
__pycache__/
*.egg-info/
.venv/
```

`.env.example`:
```
YAHOO_CONSUMER_KEY=your_client_id_here
YAHOO_CONSUMER_SECRET=your_client_secret_here
YAHOO_LEAGUE_ID=your_numeric_league_id_here
```

- [ ] **Step 3: Create the virtualenv and install**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 4: Verify the toolchain**

Run: `.venv/bin/python -c "import requests, yfpy, pytest; print('ok')"`
Expected: `ok`

All later `python` and `pytest` commands in this plan mean `.venv/bin/python` and `.venv/bin/pytest`.

- [ ] **Step 5: Ready to commit**

Files: `pyproject.toml`, `.gitignore`, `.env.example`
Suggested message: `chore: add project scaffolding and dependencies`

---

### Task 1: Yahoo OAuth handshake and league discovery (Phase 0)

**Files:**
- Create: `scripts/yahoo_auth.py`

**Interfaces:**
- Consumes: the `.venv` from Task 0
- Produces: a populated `.env` (gitignored), persisted token data (gitignored), and the Yahoo league's id / size / scoring settings recorded in `CLAUDE.md`

**This task requires the user's browser and cannot be completed by an agent alone.** Stop and hand off at Step 1.

**Expect to adjust the yfpy call.** `get_user_leagues_by_game_key`, `get_league_metadata`, and `get_league_settings` are confirmed to exist, but yfpy's constructor arguments have changed across versions and cannot be verified without running against a real Yahoo account. Treat the script below as a starting point, not gospel — if the constructor rejects an argument, check https://yfpy.uberfastman.com/query/ and adjust. **Discovering this is the entire point of Phase 0**; an error here on Aug 25 is the phase succeeding, not failing.

- [ ] **Step 1: Hand off to the user — Yahoo app registration and league ID**

Report these instructions and wait. Do not proceed alone.

> **1.** Go to https://developer.yahoo.com/apps/create/ and create an app:
> - Application Name: `ff-helper`
> - Application Type: **Installed Application**
> - Redirect URI: `https://localhost:8080`
> - API Permissions: **Fantasy Sports** → Read
>
> Free, instant, no review, nothing published.
>
> **2.** Open your Yahoo league in a browser. The URL looks like
> `football.fantasysports.yahoo.com/f1/123456` — that trailing number is your league ID.
>
> **3.** Copy the Client ID, Client Secret, and league ID into a new `.env` file, using `.env.example` as the template.

Reading the league ID off the URL rather than discovering it through an API call removes the one part of this task that depends on unverified library behaviour.

- [ ] **Step 2: Write the discovery script**

`scripts/yahoo_auth.py`:
```python
"""One-time Yahoo OAuth handshake + league confirmation. Phase 0.

Confirms three things: the OAuth handshake completes, the league is readable,
and its settings parse. Everything Phase 2 depends on.
"""
import os
import sys
from pathlib import Path

from yfpy.query import YahooFantasySportsQuery

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> tuple[str, str, str]:
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("No .env found. Copy .env.example and fill in your Yahoo credentials.")
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    missing = [
        k for k in ("YAHOO_CONSUMER_KEY", "YAHOO_CONSUMER_SECRET", "YAHOO_LEAGUE_ID")
        if not os.environ.get(k)
    ]
    if missing:
        sys.exit(f"missing from .env: {', '.join(missing)}")
    return (
        os.environ["YAHOO_CONSUMER_KEY"],
        os.environ["YAHOO_CONSUMER_SECRET"],
        os.environ["YAHOO_LEAGUE_ID"],
    )


def main() -> None:
    key, secret, league_id = load_env()
    q = YahooFantasySportsQuery(
        league_id=league_id,
        game_code="nfl",
        yahoo_consumer_key=key,
        yahoo_consumer_secret=secret,
        env_file_location=ROOT,
        save_token_data_to_env_file=True,
    )

    meta = q.get_league_metadata()
    print(f"\nleague       : {meta.name}")
    print(f"league_key   : {meta.league_key}")
    print(f"teams        : {meta.num_teams}")
    print(f"draft_status : {meta.draft_status}")

    settings = q.get_league_settings()
    print(f"scoring type : {getattr(settings, 'scoring_type', '?')}")
    print(f"roster slots : {[p.position for p in settings.roster_positions]}")

    # Must be empty pre-draft. Phase 2 depends on this populating DURING the draft.
    picks = q.get_league_draft_results()
    print(f"draft results: {len(picks)} picks (expected 0 before the draft)")

    print("\nAlso listing every NFL league on this account, for reference:")
    try:
        for lg in q.get_user_leagues_by_game_key("nfl"):
            print(f"  {lg.league_id}  {lg.name}  teams={lg.num_teams}")
    except Exception as exc:  # noqa: BLE001 - informational only
        print(f"  (listing unavailable: {exc})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the handshake**

Run: `.venv/bin/python scripts/yahoo_auth.py`

Expected: a browser opens for Yahoo consent; approve it and paste the verification code at the prompt. A certificate warning on the `localhost` redirect is expected — click through. Then the league metadata, settings, and `0 picks` print.

If it fails, capture the exact error and adjust per the note above.

- [ ] **Step 4: Record findings**

Update `CLAUDE.md` under Leagues, replacing "(id/size/scoring unknown — Phase 0)" with the real league id, team count, and scoring. Three things to note explicitly:

- **Team count.** If it is 10 or 14 rather than 12, the FFC `teams` parameter matters more than assumed.
- **Scoring differences from the Sleeper league**, especially passing TD value.
- **Whether `get_league_draft_results()` returned cleanly with 0 picks.** That is the strongest pre-Sept-1 signal that the Phase 2 feed will work.

- [ ] **Step 5: Ready to commit**

Files: `scripts/yahoo_auth.py`, `CLAUDE.md`
Suggested message: `feat: add Yahoo OAuth handshake and league confirmation script`
**Report to the user; do not run git.**

---

### Task 2: Config loading

**Files:**
- Create: `config.toml`, `ffhelper/__init__.py`, `ffhelper/config.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `League` dataclass with fields `name: str`, `platform: str`, `league_id: str`, `draft_slot: int | None`, `adp_format: str | None`, `adp_teams: int | None`; `Tunables` dataclass with `tier_break_sigma: float`, `divergence_flag_slots: int`, `flex_share: dict[str, float]`, `poll_seconds: dict[str, int]`; `load_config(path: Path) -> tuple[list[League], Tunables]`; `get_league(leagues: list[League], name: str) -> League`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path

from ffhelper.config import get_league, load_config


def test_loads_two_leagues_and_defaults(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[tunables]
tier_break_sigma = 1.0

[[league]]
name = "sleeper-main"
platform = "sleeper"
league_id = "1395959490938966016"
draft_slot = 3

[[league]]
name = "yahoo-main"
platform = "yahoo"
league_id = "12345"
"""
    )
    leagues, tun = load_config(cfg)
    assert [lg.name for lg in leagues] == ["sleeper-main", "yahoo-main"]
    assert get_league(leagues, "sleeper-main").draft_slot == 3
    assert get_league(leagues, "yahoo-main").draft_slot is None
    assert tun.tier_break_sigma == 1.0
    # defaults applied for unspecified tunables
    assert tun.divergence_flag_slots == 25
    assert tun.flex_share == {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    assert tun.poll_seconds == {"sleeper": 5, "yahoo": 12}


def test_unknown_league_raises(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[league]]\nname = "a"\nplatform = "sleeper"\nleague_id = "1"\n')
    leagues, _ = load_config(cfg)
    try:
        get_league(leagues, "nope")
    except KeyError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected KeyError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.config'`

- [ ] **Step 3: Write the implementation**

`ffhelper/__init__.py`: empty file.

`ffhelper/config.py`:
```python
"""Config loading. No league state lives at module level anywhere in this package."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class League:
    name: str
    platform: str          # "sleeper" | "yahoo"
    league_id: str
    draft_slot: int | None = None    # 1-indexed; None means read from platform
    adp_format: str | None = None    # None means derive from league scoring
    adp_teams: int | None = None     # None means derive from league size


@dataclass(frozen=True)
class Tunables:
    tier_break_sigma: float = 1.0
    divergence_flag_slots: int = 25
    flex_share: dict[str, float] = field(
        default_factory=lambda: {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    )
    poll_seconds: dict[str, int] = field(
        default_factory=lambda: {"sleeper": 5, "yahoo": 12}
    )


def load_config(path: Path) -> tuple[list[League], Tunables]:
    raw = tomllib.loads(Path(path).read_text())
    leagues = [League(**entry) for entry in raw.get("league", [])]
    tun_raw = raw.get("tunables", {})
    defaults = Tunables()
    tun = Tunables(
        tier_break_sigma=tun_raw.get("tier_break_sigma", defaults.tier_break_sigma),
        divergence_flag_slots=tun_raw.get("divergence_flag_slots", defaults.divergence_flag_slots),
        flex_share=tun_raw.get("flex_share", defaults.flex_share),
        poll_seconds=tun_raw.get("poll_seconds", defaults.poll_seconds),
    )
    return leagues, tun


def get_league(leagues: list[League], name: str) -> League:
    for lg in leagues:
        if lg.name == name:
            return lg
    raise KeyError(f"no league named {name!r}; have {[lg.name for lg in leagues]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Create the real `config.toml`**

```toml
[tunables]
tier_break_sigma = 1.0
divergence_flag_slots = 25

[tunables.flex_share]
RB = 0.5
WR = 0.5
TE = 0.0

[tunables.poll_seconds]
sleeper = 5
yahoo = 12

[[league]]
name = "sleeper-main"
platform = "sleeper"
league_id = "1395959490938966016"
# draft_slot: Sleeper draft_order had 11 of 12 slots at design time.
# Set this manually once the draft order is final. Never trust the API for it.
# draft_slot = 3

[[league]]
name = "yahoo-main"
platform = "yahoo"
league_id = "REPLACE_AFTER_TASK_1"
```

- [ ] **Step 6: Ready to commit**

Files: `config.toml`, `ffhelper/__init__.py`, `ffhelper/config.py`, `tests/test_config.py`
Suggested message: `feat: add multi-league config loading`

---

### Task 3: HTTP fetch with disk cache and stale fallback

**Files:**
- Create: `ffhelper/data.py`, `tests/test_data.py`

**Interfaces:**
- Consumes: nothing
- Produces: `fetch_json(url: str, cache_key: str, ttl_seconds: int = 86400, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> Any` — returns parsed JSON, writes through to disk cache, and falls back to stale cache on any fetch failure. `CACHE_DIR: Path`.

The `fetcher` parameter exists so tests never touch the network. Default is a real `requests.get` with a 5-second timeout.

- [ ] **Step 1: Write the failing test**

`tests/test_data.py`:
```python
import json
from pathlib import Path

import pytest

from ffhelper.data import fetch_json


def test_fetches_and_caches(tmp_path: Path):
    calls = []

    def fake(url: str) -> str:
        calls.append(url)
        return json.dumps({"v": 1})

    a = fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    b = fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    assert a == b == {"v": 1}
    assert len(calls) == 1, "second call should hit the disk cache"


def test_falls_back_to_stale_cache_on_failure(tmp_path: Path):
    def ok(url: str) -> str:
        return json.dumps({"v": 1})

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=ok)
    # ttl=0 forces a refetch attempt, which fails; stale cache must be returned
    got = fetch_json("http://x/y", "k", ttl_seconds=0, cache_dir=tmp_path, fetcher=boom)
    assert got == {"v": 1}


def test_raises_when_no_cache_and_fetch_fails(tmp_path: Path):
    def boom(url: str) -> str:
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=boom)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_json'`

- [ ] **Step 3: Write the implementation**

`ffhelper/data.py`:
```python
"""Fetching, caching, and joining of all external data into list[Player]."""
import json
import logging
import time
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

    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        return json.loads(path.read_text())

    try:
        text = fetcher(url)
    except Exception as exc:
        if path.exists():
            log.warning("fetch failed for %s (%s); using stale cache", cache_key, exc)
            return json.loads(path.read_text())
        raise

    path.write_text(text)
    return json.loads(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/data.py`, `tests/test_data.py`
Suggested message: `feat: add cached HTTP fetch with stale fallback`

---

### Task 4: Player database and Yahoo crosswalk join

**Files:**
- Modify: `ffhelper/data.py`, `tests/test_data.py`

**Interfaces:**
- Consumes: `fetch_json` (Task 3)
- Produces: `Player` dataclass (mutable) with fields `sleeper_id: str`, `name: str`, `position: str`, `team: str | None`, `yahoo_id: str | None`, `injury_status: str | None`, `proj_pts: float`, `adp: float`, `adp_stdev: float | None`, `bye: int | None`, `match_key: str`; `norm_name(s: str) -> str`; `load_players(cache_dir=CACHE_DIR, fetcher=None) -> dict[str, Player]` keyed by `sleeper_id`

Constants: `SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"`, `CROSSWALK_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data.py`:
```python
from ffhelper.data import Player, norm_name, build_players


def test_norm_name_strips_punctuation_and_case():
    assert norm_name("Ja'Marr Chase") == "jamarrchase"
    assert norm_name("Amon-Ra St. Brown") == "amonrastbrown"


def test_crosswalk_join_is_by_id_not_name():
    """Bijan and Brian Robinson are both ATL RBs. Name+pos+team collides;
    sleeper_id does not. This is a real bug hit during design."""
    raw = {
        "9221": {"full_name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
                 "active": True, "injury_status": None},
        "8155": {"full_name": "Bijan Robinson", "position": "RB", "team": "ATL",
                 "active": True, "injury_status": None},
        "7588": {"full_name": "Brian Robinson", "position": "RB", "team": "ATL",
                 "active": True, "injury_status": "Questionable"},
    }
    crosswalk = {"9221": "40059", "8155": "40000", "7588": "34000"}
    players = build_players(raw, crosswalk)

    assert len(players) == 3, "no player may be dropped or merged"
    assert players["8155"].name == "Bijan Robinson"
    assert players["7588"].name == "Brian Robinson"
    assert players["8155"].yahoo_id == "40000"
    assert players["7588"].yahoo_id == "34000"
    assert players["9221"].yahoo_id == "40059"
    assert players["7588"].injury_status == "Questionable"


def test_missing_crosswalk_entry_leaves_yahoo_id_none():
    raw = {"1": {"full_name": "Nobody Special", "position": "WR", "team": "SF",
                 "active": True, "injury_status": None}}
    players = build_players(raw, {})
    assert players["1"].yahoo_id is None


def test_inactive_and_irrelevant_positions_excluded():
    raw = {
        "1": {"full_name": "Active WR", "position": "WR", "team": "SF",
              "active": True, "injury_status": None},
        "2": {"full_name": "Retired Guy", "position": "WR", "team": None,
              "active": False, "injury_status": None},
        "3": {"full_name": "Some Guard", "position": "OG", "team": "SF",
              "active": True, "injury_status": None},
    }
    assert set(build_players(raw, {})) == {"1"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_players'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/data.py`:
```python
import csv
import io
import re
from dataclasses import dataclass, field

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/data.py`, `tests/test_data.py`
Suggested message: `feat: join Sleeper player DB to DynastyProcess crosswalk by ID`

---

### Task 5: League settings and custom scoring

**Files:**
- Modify: `ffhelper/data.py`, `tests/test_data.py`

**Interfaces:**
- Consumes: `Player`, `fetch_json`
- Produces: `LeagueSettings` dataclass with `num_teams: int`, `scoring: dict[str, float]`, `roster_slots: dict[str, int]`, `rounds: int`, `draft_id: str | None`; `score_stats(stats: dict[str, float], scoring: dict[str, float]) -> float`; `load_sleeper_settings(league_id: str, cache_dir=CACHE_DIR, fetcher=None) -> LeagueSettings`; `apply_projections(players: dict[str, Player], projections: list[dict], scoring: dict[str, float]) -> None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data.py`:
```python
from ffhelper.data import LeagueSettings, apply_projections, score_stats

# Josh Allen's real 2026 projection, inlined. One record for a golden value is
# de minimis; the bulk dataset is never committed.
ALLEN_STATS = {
    "pass_yd": 3650.0, "pass_td": 27.0, "pass_int": 10.0, "pass_2pt": 1.0,
    "rush_yd": 535.0, "rush_td": 11.0, "rush_2pt": 1.0, "fum_lost": 3.0,
    "pts_ppr": 361.5,
}
# The league's real scoring: full PPR with SIX-point passing TDs.
LEAGUE_SCORING = {
    "pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "pass_2pt": 2.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0, "fum_lost": -2.0,
    "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0,
}


def test_custom_scoring_golden_value():
    """6-pt passing TDs put Allen at 415.5, not Sleeper's canned 361.5."""
    assert round(score_stats(ALLEN_STATS, LEAGUE_SCORING), 1) == 415.5


def test_scoring_ignores_non_scoring_stat_keys():
    """pts_ppr, gp, cmp_pct etc. appear in stats but are not scoring categories."""
    noisy = dict(ALLEN_STATS, gp=18.0, cmp_pct=66.03, pass_att=474.0)
    assert round(score_stats(noisy, LEAGUE_SCORING), 1) == 415.5


def test_full_ppr_skill_players_match_canned_pts_ppr():
    """RB/WR/TE scoring is standard here, so custom must equal canned."""
    gibbs = {"rush_yd": 1251.0, "rush_td": 12.0, "rec": 63.0, "rec_yd": 533.0,
             "rec_td": 3.0, "fum_lost": 1.0, "rush_2pt": 1.0}
    assert round(score_stats(gibbs, LEAGUE_SCORING), 1) == 331.4


def test_apply_projections_sets_points_and_skips_unknown_ids():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET")}
    proj = [
        {"player_id": "9221", "stats": {"rush_yd": 1000.0, "rush_td": 10.0}},
        {"player_id": "0000", "stats": {"rush_yd": 500.0}},   # not in our pool
        {"player_id": "9221", "stats": None},                  # malformed, ignore
    ]
    apply_projections(players, proj, LEAGUE_SCORING)
    assert players["9221"].proj_pts == 160.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL — `ImportError: cannot import name 'score_stats'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/data.py`:
```python
SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_PROJ_URL = (
    "https://api.sleeper.com/projections/nfl/{season}"
    "?season_type=regular&position[]={pos}&order_by=pts_ppr"
)


@dataclass(frozen=True)
class LeagueSettings:
    num_teams: int
    scoring: dict[str, float]
    roster_slots: dict[str, int]   # e.g. {"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":2,"K":1,"DEF":1}
    rounds: int
    draft_id: str | None = None


def score_stats(stats: dict[str, float], scoring: dict[str, float]) -> float:
    """Dot product of a raw stat line against league scoring settings.

    Only keys present in `scoring` contribute, so descriptive stats in the
    payload (pts_ppr, gp, cmp_pct, adp_*) are ignored by construction.
    """
    return sum(
        weight * stats[key]
        for key, weight in scoring.items()
        if key in stats and isinstance(stats[key], (int, float))
    )


def apply_projections(
    players: dict[str, Player], projections: list[dict], scoring: dict[str, float]
) -> None:
    """Score projections onto players IN PLACE, joined on sleeper player_id."""
    for row in projections:
        pid = row.get("player_id")
        stats = row.get("stats")
        if not pid or not stats or pid not in players:
            continue
        players[pid].proj_pts = score_stats(stats, scoring)


def load_sleeper_settings(
    league_id: str, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> LeagueSettings:
    raw = fetch_json(
        SLEEPER_LEAGUE_URL.format(league_id=league_id),
        f"league_{league_id}",
        ttl_seconds=3600,
        cache_dir=cache_dir,
        fetcher=fetcher,
    )
    positions = raw.get("roster_positions", [])
    slots: dict[str, int] = {}
    for slot in positions:
        if slot != "BN":
            slots[slot] = slots.get(slot, 0) + 1
    return LeagueSettings(
        num_teams=raw.get("total_rosters", 12),
        scoring={k: float(v) for k, v in (raw.get("scoring_settings") or {}).items()},
        roster_slots=slots,
        rounds=len(positions),
        draft_id=raw.get("draft_id"),
    )


def load_projections(
    season: str, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> list[dict]:
    rows: list[dict] = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        rows.extend(
            fetch_json(
                SLEEPER_PROJ_URL.format(season=season, pos=pos),
                f"proj_{season}_{pos}",
                cache_dir=cache_dir,
                fetcher=fetcher,
            )
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/data.py`, `tests/test_data.py`
Suggested message: `feat: add league settings sync and custom scoring`

---

### Task 6: FFC ADP enrichment with curve fallback

**Files:**
- Modify: `ffhelper/data.py`, `tests/test_data.py`

**Interfaces:**
- Consumes: `Player`, `norm_name`, `fetch_json`
- Produces: `curve_stdev(adp: float) -> float`; `apply_ffc_adp(players: dict[str, Player], ffc_rows: list[dict]) -> list[str]` returning the list of unmatched FFC player names; `apply_sleeper_adp(players: dict[str, Player], projections: list[dict], adp_field: str) -> None`

`apply_sleeper_adp` runs FIRST and is ID-keyed, so every player has an ADP before FFC is consulted. FFC then overwrites `adp`/`adp_stdev`/`bye` where it matches. A match failure leaves the ID-keyed values intact.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_data.py`:
```python
from ffhelper.data import apply_ffc_adp, apply_sleeper_adp, curve_stdev


def test_curve_stdev_matches_fitted_parameters():
    # stdev = 0.287 * adp^0.809, fitted from FFC 12-team PPR data
    assert round(curve_stdev(1.0), 3) == 0.287
    assert curve_stdev(100.0) > curve_stdev(10.0), "variance grows with ADP"


def test_sleeper_adp_applied_by_id_before_ffc():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET")}
    proj = [{"player_id": "9221", "stats": {"adp_ppr": 1.0, "pts_ppr": 331.4}}]
    apply_sleeper_adp(players, proj, "adp_ppr")
    assert players["9221"].adp == 1.0
    assert players["9221"].adp_stdev == pytest.approx(curve_stdev(1.0))


def test_ffc_overwrites_stdev_on_match():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET", adp=1.0)}
    unmatched = apply_ffc_adp(
        players, [{"name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
                   "adp": 1.5, "stdev": 0.7, "bye": 6}]
    )
    assert unmatched == []
    assert players["9221"].adp == 1.5
    assert players["9221"].adp_stdev == 0.7
    assert players["9221"].bye == 6


def test_ffc_miss_is_reported_and_player_keeps_id_keyed_values():
    """A fuzzy-join failure must never drop or corrupt a player."""
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET",
                              adp=1.0, adp_stdev=0.287)}
    unmatched = apply_ffc_adp(
        players, [{"name": "Someone Unknown", "position": "WR", "team": "XXX",
                   "adp": 50.0, "stdev": 9.9, "bye": 7}]
    )
    assert unmatched == ["Someone Unknown"]
    assert len(players) == 1, "no player added or dropped by the fuzzy join"
    assert players["9221"].adp == 1.0, "ID-keyed ADP survives an FFC miss"
    assert players["9221"].adp_stdev == 0.287


def test_ffc_does_not_merge_bijan_and_brian():
    players = {
        "8155": Player("8155", "Bijan Robinson", "RB", "ATL"),
        "7588": Player("7588", "Brian Robinson", "RB", "ATL"),
    }
    apply_ffc_adp(players, [
        {"name": "Bijan Robinson", "position": "RB", "team": "ATL",
         "adp": 2.0, "stdev": 0.8, "bye": 5},
        {"name": "Brian Robinson", "position": "RB", "team": "ATL",
         "adp": 150.0, "stdev": 20.0, "bye": 5},
    ])
    assert players["8155"].adp == 2.0
    assert players["7588"].adp == 150.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL — `ImportError: cannot import name 'curve_stdev'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/data.py`:
```python
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={year}"

# Fitted from FFC 12-team PPR data on 2026-08-24: stdev = 0.287 * adp^0.809,
# R^2 = 0.574. Used only as a fallback when FFC has no row for a player.
# ponytail: refit if it drifts; a constant here would be worse than a bad fit.
_STDEV_A, _STDEV_B = 0.287, 0.809


def curve_stdev(adp: float) -> float:
    return _STDEV_A * max(adp, 0.1) ** _STDEV_B


def apply_sleeper_adp(
    players: dict[str, Player], projections: list[dict], adp_field: str
) -> None:
    """ID-keyed ADP. Runs BEFORE the FFC join so every player has a value."""
    for row in projections:
        pid = row.get("player_id")
        stats = row.get("stats") or {}
        if not pid or pid not in players:
            continue
        adp = stats.get(adp_field)
        if adp is None or adp >= 999:
            continue
        players[pid].adp = float(adp)
        players[pid].adp_stdev = curve_stdev(float(adp))


def apply_ffc_adp(players: dict[str, Player], ffc_rows: list[dict]) -> list[str]:
    """Non-load-bearing enrichment. Supplies adp/adp_stdev/bye where matched.

    FFC carries no cross-platform ID, so this is the one fuzzy join in the
    system. It runs LAST, on an already-complete ID-keyed board, so the blast
    radius of a miss is three fields on one player. Returns unmatched names for
    the caller to print -- never silently dropped.
    """
    by_key = {p.match_key: p for p in players.values()}
    unmatched: list[str] = []
    for row in ffc_rows:
        key = f"{norm_name(row.get('name',''))}|{row.get('position','')}|{row.get('team','') or ''}"
        target = by_key.get(key)
        if target is None:
            unmatched.append(row.get("name", "<unnamed>"))
            continue
        if row.get("adp") is not None:
            target.adp = float(row["adp"])
        if row.get("stdev"):
            target.adp_stdev = float(row["stdev"])
        if row.get("bye"):
            target.bye = int(row["bye"])
    return unmatched


def load_ffc_adp(
    fmt: str, teams: int, year: int,
    cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None,
) -> list[dict]:
    data = fetch_json(
        FFC_URL.format(fmt=fmt, teams=teams, year=year),
        f"ffc_{fmt}_{teams}_{year}",
        cache_dir=cache_dir,
        fetcher=fetcher,
    )
    return data.get("players", [])


def adp_format_for(settings: LeagueSettings) -> str:
    """Derive the FFC format parameter from synced scoring settings."""
    rec = settings.scoring.get("rec", 0.0)
    if rec >= 1.0:
        return "ppr"
    if rec >= 0.5:
        return "half-ppr"
    return "standard"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/data.py`, `tests/test_data.py`
Suggested message: `feat: add FFC ADP enrichment with fitted stdev fallback`

---

### Task 7: Replacement levels, VBD, and tiers

**Files:**
- Create: `ffhelper/value.py`, `tests/test_value.py`

**Interfaces:**
- Consumes: `Player` from `ffhelper.data` (type only — `value.py` performs no I/O)
- Produces: `replacement_ranks(roster_slots: dict[str, int], num_teams: int, flex_share: dict[str, float]) -> dict[str, int]`; `replacement_points(players: list[Player], ranks: dict[str, int]) -> dict[str, float]`; `vbd(players: list[Player], repl: dict[str, float]) -> dict[str, float]` keyed by `sleeper_id`; `assign_tiers(players: list[Player], scores: dict[str, float], sigma: float) -> dict[str, int]` keyed by `sleeper_id`, 1-indexed within position

- [ ] **Step 1: Write the failing test**

`tests/test_value.py`:
```python
"""Pure engine tests. Synthetic players only -- the engine is arithmetic and
does not care whether the numbers are real."""
import pytest

from ffhelper.data import Player
from ffhelper.value import (
    assign_tiers, replacement_points, replacement_ranks, vbd,
)

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
FLEX_SHARE = {"RB": 0.5, "WR": 0.5, "TE": 0.0}


def mk(pid: str, pos: str, pts: float, adp: float = 50.0, stdev: float = 5.0) -> Player:
    return Player(pid, f"P{pid}", pos, "SF", proj_pts=pts, adp=adp, adp_stdev=stdev)


def test_replacement_ranks_for_real_league():
    """Sleeper league: 12 teams, 1QB/2RB/2WR/1TE/2FLEX, flex split 50/50.
    RB = 12 * (2 + 0.5*2) = 36. WR the same. QB and TE take no flex share."""
    got = replacement_ranks(SLOTS, num_teams=12, flex_share=FLEX_SHARE)
    assert got["QB"] == 12
    assert got["TE"] == 12
    assert got["RB"] == 36
    assert got["WR"] == 36


def test_replacement_ranks_scale_with_league_size():
    """Yahoo league: same roster shape, 10 teams -> everything shallower."""
    got = replacement_ranks(SLOTS, num_teams=10, flex_share=FLEX_SHARE)
    assert got["QB"] == 10
    assert got["TE"] == 10
    assert got["RB"] == 30
    assert got["WR"] == 30


def test_flex_share_shifts_replacement_between_positions():
    """The flex_share knob must actually move replacement depth, or it is
    decoration. A WR-heavy flex pushes WR deeper and RB shallower."""
    wr_heavy = replacement_ranks(SLOTS, 12, {"RB": 0.25, "WR": 0.75, "TE": 0.0})
    assert wr_heavy["RB"] == 30
    assert wr_heavy["WR"] == 42


def test_vbd_is_points_over_replacement():
    players = [mk(str(i), "RB", 100.0 - i) for i in range(5)]
    repl = replacement_points(players, {"RB": 3})
    assert repl["RB"] == 98.0          # 3rd best RB
    scores = vbd(players, repl)
    assert scores["0"] == 2.0
    assert scores["4"] == -2.0


def test_replacement_uses_last_player_when_pool_is_short():
    players = [mk("0", "TE", 200.0), mk("1", "TE", 150.0)]
    repl = replacement_points(players, {"TE": 12})
    assert repl["TE"] == 150.0, "shallow pool falls back to the worst available"


def test_tiers_break_on_large_gaps():
    # 300, 295 | 200, 198 -- one huge gap, so two tiers
    players = [mk("a", "RB", 300.0), mk("b", "RB", 295.0),
               mk("c", "RB", 200.0), mk("d", "RB", 198.0)]
    scores = {p.sleeper_id: p.proj_pts for p in players}
    tiers = assign_tiers(players, scores, sigma=1.0)
    assert tiers["a"] == tiers["b"] == 1
    assert tiers["c"] == tiers["d"] == 2


def test_tiers_are_per_position():
    players = [mk("a", "RB", 300.0), mk("b", "WR", 299.0)]
    tiers = assign_tiers(players, {"a": 300.0, "b": 299.0}, sigma=1.0)
    assert tiers["a"] == 1 and tiers["b"] == 1


def test_tiers_handle_single_player_position():
    players = [mk("a", "K", 120.0)]
    assert assign_tiers(players, {"a": 120.0}, sigma=1.0) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_value.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.value'`

- [ ] **Step 3: Write the implementation**

`ffhelper/value.py`:
```python
"""PURE ranking engine. No I/O, no network, no module-level mutable state.

Everything here is a function of its arguments, which is what makes the whole
board testable without touching a network.
"""
import statistics
from statistics import NormalDist

from ffhelper.data import Player


def replacement_ranks(
    roster_slots: dict[str, int], num_teams: int, flex_share: dict[str, float]
) -> dict[str, int]:
    """How deep the league drafts each position before value hits baseline."""
    flex_slots = roster_slots.get("FLEX", 0)
    ranks: dict[str, int] = {}
    for pos, starters in roster_slots.items():
        if pos == "FLEX":
            continue
        share = flex_share.get(pos, 0.0)
        ranks[pos] = round(num_teams * (starters + share * flex_slots))
    return ranks


def replacement_points(players: list[Player], ranks: dict[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos, rank in ranks.items():
        pool = sorted(
            (p.proj_pts for p in players if p.position == pos), reverse=True
        )
        if not pool:
            out[pos] = 0.0
        else:
            out[pos] = pool[min(rank, len(pool)) - 1]
    return out


def vbd(players: list[Player], repl: dict[str, float]) -> dict[str, float]:
    return {p.sleeper_id: p.proj_pts - repl.get(p.position, 0.0) for p in players}


def assign_tiers(
    players: list[Player], scores: dict[str, float], sigma: float
) -> dict[str, int]:
    """Break a tier when the gap to the next player exceeds sigma * stdev(gaps).

    ponytail: gap-based clustering, not k-means. If tiers look wrong in a real
    draft, turn the sigma knob before reaching for a clustering library.
    """
    tiers: dict[str, int] = {}
    by_pos: dict[str, list[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)

    for pos, group in by_pos.items():
        group = sorted(group, key=lambda p: -scores.get(p.sleeper_id, 0.0))
        gaps = [
            scores.get(group[i].sleeper_id, 0.0) - scores.get(group[i + 1].sleeper_id, 0.0)
            for i in range(len(group) - 1)
        ]
        threshold = (
            sigma * statistics.pstdev(gaps) if len(gaps) > 1 else float("inf")
        )
        tier = 1
        for i, p in enumerate(group):
            tiers[p.sleeper_id] = tier
            if i < len(gaps) and gaps[i] > threshold:
                tier += 1
    return tiers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_value.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/value.py`, `tests/test_value.py`
Suggested message: `feat: add replacement levels, VBD, and tier assignment`

---

### Task 8: `lineup_value` — the function Phase 5 inherits

**Files:**
- Modify: `ffhelper/value.py`, `tests/test_value.py`

**Interfaces:**
- Consumes: `Player`
- Produces: `lineup_value(roster: list[Player], roster_slots: dict[str, int]) -> float`; `marginal_value(roster: list[Player], candidate: Player, roster_slots: dict[str, int]) -> float`

Greedy fill: dedicated slots first (best player per position), then FLEX from the best remaining RB/WR/TE. Greedy is optimal here because every eligible player contributes their own points and slots are interchangeable within eligibility.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_value.py`:
```python
from ffhelper.value import lineup_value, marginal_value


def test_lineup_value_fills_dedicated_slots_then_flex():
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}
    roster = [
        mk("q", "QB", 300.0),
        mk("r1", "RB", 250.0), mk("r2", "RB", 200.0), mk("r3", "RB", 150.0),
        mk("w1", "WR", 240.0), mk("w2", "WR", 190.0),
        mk("t", "TE", 120.0),
    ]
    # 300 + 250 + 200 + 240 + 190 + 120 + flex(best leftover = r3 150) = 1450
    assert lineup_value(roster, slots) == 1450.0


def test_lineup_value_ignores_players_beyond_slots():
    slots = {"QB": 1}
    roster = [mk("q1", "QB", 300.0), mk("q2", "QB", 290.0)]
    assert lineup_value(roster, slots) == 300.0


def test_third_rb_adds_less_than_first():
    """The core insight the trade finder inherits: lineup constraints create
    surplus, so a third RB is worth a fraction of the first."""
    slots = {"RB": 2, "FLEX": 1}
    empty: list[Player] = []
    one_rb = [mk("r1", "RB", 250.0)]
    three_rb = [mk("r1", "RB", 250.0), mk("r2", "RB", 200.0), mk("r3", "RB", 150.0)]
    cand = mk("new", "RB", 180.0)

    first = marginal_value(empty, cand, slots)
    fourth = marginal_value(three_rb, cand, slots)
    assert first == 180.0
    assert fourth == 0.0, "a 4th RB with 2RB+1FLEX filled adds nothing"
    assert marginal_value(one_rb, cand, slots) == 180.0
    assert first > fourth


def test_marginal_value_of_upgrade_is_the_difference():
    slots = {"QB": 1}
    roster = [mk("q1", "QB", 300.0)]
    assert marginal_value(roster, mk("q2", "QB", 350.0), slots) == 50.0


def test_lineup_value_of_empty_roster_is_zero():
    assert lineup_value([], {"QB": 1, "RB": 2}) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_value.py -v`
Expected: FAIL — `ImportError: cannot import name 'lineup_value'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/value.py`:
```python
FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def lineup_value(roster: list[Player], roster_slots: dict[str, int]) -> float:
    """Points scored by the optimal starting lineup drawn from `roster`.

    Phase 1 uses this for starter-slot awareness; Phase 5's trade finder uses
    the identical function. Never inline it into the board.
    """
    remaining = sorted(roster, key=lambda p: -p.proj_pts)
    used: set[str] = set()
    total = 0.0

    for pos, count in roster_slots.items():
        if pos == "FLEX":
            continue
        picked = 0
        for p in remaining:
            if picked >= count:
                break
            if p.position == pos and p.sleeper_id not in used:
                used.add(p.sleeper_id)
                total += p.proj_pts
                picked += 1

    for _ in range(roster_slots.get("FLEX", 0)):
        for p in remaining:
            if p.position in FLEX_ELIGIBLE and p.sleeper_id not in used:
                used.add(p.sleeper_id)
                total += p.proj_pts
                break

    return total


def marginal_value(
    roster: list[Player], candidate: Player, roster_slots: dict[str, int]
) -> float:
    """How much adding `candidate` improves the optimal starting lineup."""
    return lineup_value([*roster, candidate], roster_slots) - lineup_value(roster, roster_slots)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_value.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/value.py`, `tests/test_value.py`
Suggested message: `feat: add lineup_value and marginal value`

---

### Task 9: Snake math, survival, VONA, divergence, run detection

**Files:**
- Modify: `ffhelper/value.py`, `tests/test_value.py`

**Interfaces:**
- Consumes: `Player`, `curve_stdev` from `ffhelper.data`
- Produces: `next_pick_number(current_pick: int, slot: int, num_teams: int) -> int`; `survival_prob(player: Player, at_pick: int) -> float`; `vona(players: list[Player], candidate: Player, at_pick: int) -> float`; `divergence(players: list[Player], scores: dict[str, float]) -> dict[str, int]`; `detect_run(recent_positions: list[str], window: int = 8) -> dict[str, int]`

`next_pick_number` uses 1-indexed picks and slots. In a snake draft, slot `s` in an `n`-team league picks at `s`, `2n-s+1`, `2n+s`, `4n-s+1`, …

- [ ] **Step 1: Write the failing test**

Append to `tests/test_value.py`:
```python
from ffhelper.value import (
    detect_run, divergence, next_pick_number, survival_prob, vona,
)


def test_snake_pick_sequence_for_slot_3_in_12_team():
    # slot 3 picks at 3, 22, 27, 46, 51 ...
    assert next_pick_number(current_pick=1, slot=3, num_teams=12) == 3
    assert next_pick_number(current_pick=3, slot=3, num_teams=12) == 22
    assert next_pick_number(current_pick=22, slot=3, num_teams=12) == 27
    assert next_pick_number(current_pick=27, slot=3, num_teams=12) == 46


def test_snake_endpoints_turn_correctly():
    # slot 1 picks 1 then 24; slot 12 picks 12 then 13 (the turn)
    assert next_pick_number(1, 1, 12) == 24
    assert next_pick_number(12, 12, 12) == 13


def test_survival_decreases_as_pick_number_rises():
    p = mk("a", "RB", 200.0, adp=20.0, stdev=5.0)
    probs = [survival_prob(p, at_pick=k) for k in (10, 20, 30, 40)]
    assert probs == sorted(probs, reverse=True), "survival must be monotonic"
    assert probs[0] > 0.95
    assert probs[-1] < 0.05


def test_survival_at_adp_is_about_half():
    p = mk("a", "RB", 200.0, adp=20.0, stdev=5.0)
    assert survival_prob(p, at_pick=20) == pytest.approx(0.5, abs=0.01)


def test_survival_falls_back_to_curve_when_stdev_missing():
    p = Player("a", "A", "RB", "SF", proj_pts=200.0, adp=20.0, adp_stdev=None)
    assert 0.0 < survival_prob(p, at_pick=20) < 1.0


def test_vona_is_zero_when_an_equal_player_survives():
    """If someone just as good is certain to last, waiting costs nothing."""
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    clone = mk("b", "RB", 200.0, adp=300.0, stdev=1.0)   # certain to survive
    assert vona([cand, clone], cand, at_pick=20) == pytest.approx(0.0, abs=0.5)


def test_vona_is_large_when_nobody_survives():
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    other = mk("b", "RB", 100.0, adp=2.0, stdev=0.5)     # also certain to be gone
    assert vona([cand, other], cand, at_pick=50) > 190.0


def test_divergence_flags_projection_vs_market_gaps():
    # 'sleeper' is ranked 1st by projection but 3rd by ADP -> +2 divergence
    players = [
        mk("a", "RB", 300.0, adp=30.0),
        mk("b", "RB", 250.0, adp=10.0),
        mk("c", "RB", 200.0, adp=20.0),
    ]
    scores = {"a": 300.0, "b": 250.0, "c": 200.0}
    div = divergence(players, scores)
    assert div["a"] == 2, "projection rank 1, ADP rank 3"
    assert div["b"] == -1
    assert div["c"] == -1


def test_detect_run_counts_recent_positions():
    assert detect_run(["RB"] * 5 + ["WR"] * 3) == {"RB": 5, "WR": 3}
    assert detect_run(["QB"] + ["RB"] * 10, window=8)["RB"] == 8
    assert detect_run([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_value.py -v`
Expected: FAIL — `ImportError: cannot import name 'next_pick_number'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/value.py`:
```python
from collections import Counter

from ffhelper.data import curve_stdev


def next_pick_number(current_pick: int, slot: int, num_teams: int) -> int:
    """The next pick belonging to `slot` strictly after `current_pick`.

    Snake order: round r (1-indexed) gives slot s the pick
    (r-1)*n + s on odd rounds, and (r-1)*n + (n-s+1) on even rounds.
    """
    r = 1
    while True:
        offset = slot if r % 2 == 1 else (num_teams - slot + 1)
        pick = (r - 1) * num_teams + offset
        if pick > current_pick:
            return pick
        r += 1


def survival_prob(player: Player, at_pick: int) -> float:
    """P(player is still available at `at_pick`), from ADP mean and spread.

    FFC's per-player stdev cannot be synthesized -- fitting it from ADP alone
    leaves 42.6% of the variance unexplained -- so the curve is only a fallback.
    """
    stdev = player.adp_stdev or curve_stdev(player.adp)
    return 1.0 - NormalDist(player.adp, max(stdev, 0.1)).cdf(at_pick)


def vona(players: list[Player], candidate: Player, at_pick: int) -> float:
    """Value Over Next Available: what it costs to wait rather than take him now.

    Expected best-at-position at `at_pick`, computed as a survival-weighted
    walk down the position board: the best player is the first who survives.
    """
    same_pos = sorted(
        (p for p in players if p.position == candidate.position and p is not candidate),
        key=lambda p: -p.proj_pts,
    )
    expected = 0.0
    prob_all_gone = 1.0
    for p in same_pos:
        surv = survival_prob(p, at_pick)
        expected += prob_all_gone * surv * p.proj_pts
        prob_all_gone *= 1.0 - surv
        if prob_all_gone < 1e-6:
            break
    return candidate.proj_pts - expected


def divergence(players: list[Player], scores: dict[str, float]) -> dict[str, int]:
    """projection_rank - adp_rank. Positive means the model likes him more
    than the market does.

    NEVER average these two ranks. Blending pulls the board toward consensus,
    and a board that tracks consensus produces consensus results.
    """
    by_proj = sorted(players, key=lambda p: -scores.get(p.sleeper_id, 0.0))
    by_adp = sorted(players, key=lambda p: p.adp)
    proj_rank = {p.sleeper_id: i for i, p in enumerate(by_proj, 1)}
    adp_rank = {p.sleeper_id: i for i, p in enumerate(by_adp, 1)}
    return {pid: adp_rank[pid] - proj_rank[pid] for pid in proj_rank}


def detect_run(recent_positions: list[str], window: int = 8) -> dict[str, int]:
    """Position counts over the last `window` picks."""
    return dict(Counter(recent_positions[-window:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_value.py -v`
Expected: PASS, 21 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/value.py`, `tests/test_value.py`
Suggested message: `feat: add snake math, survival, VONA, divergence, run detection`

---

### Task 10: Pick feed protocol and Sleeper feed

**Files:**
- Create: `ffhelper/feeds.py`, `tests/test_feeds.py`

**Interfaces:**
- Consumes: `fetch_json`
- Produces: `Pick` dataclass with `pick_no: int`, `sleeper_id: str`, `roster_id: int | None`; `PickFeed` protocol with `get_picks() -> list[Pick]`; `SleeperFeed(draft_id: str, fetcher=None)`; `parse_sleeper_picks(raw: list[dict]) -> list[Pick]`

Phase 2 adds `YahooFeed` implementing the same protocol. Nothing downstream may reference `SleeperFeed` by name.

- [ ] **Step 1: Write the failing test**

`tests/test_feeds.py`:
```python
from ffhelper.feeds import Pick, parse_sleeper_picks


def test_parses_picks_in_order():
    raw = [
        {"pick_no": 2, "player_id": "8155", "roster_id": 4},
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1, 2]
    assert picks[0] == Pick(pick_no=1, sleeper_id="9221", roster_id=10)


def test_skips_picks_without_a_player():
    """A pick object can exist before the player is assigned."""
    raw = [
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": 2, "player_id": None, "roster_id": 4},
    ]
    assert len(parse_sleeper_picks(raw)) == 1


def test_empty_draft_returns_empty_list():
    assert parse_sleeper_picks([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_feeds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.feeds'`

- [ ] **Step 3: Write the implementation**

`ffhelper/feeds.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_feeds.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/feeds.py`, `tests/test_feeds.py`
Suggested message: `feat: add pick feed protocol and Sleeper implementation`

---

### Task 11: Board assembly

**Files:**
- Modify: `ffhelper/value.py`, `tests/test_value.py`

**Interfaces:**
- Consumes: everything in `value.py`
- Produces: `Row` dataclass with `player: Player`, `vbd: float`, `vona: float`, `marginal: float`, `tier: int`, `survival: float`, `divergence: int`; `build_board(available: list[Player], my_roster: list[Player], settings_slots: dict[str, int], num_teams: int, current_pick: int, my_slot: int | None, tunables) -> list[Row]` sorted by `vona` descending

When `my_slot` is None the board still builds: survival and VONA are computed against the immediate next pick, so the tool degrades to a VBD board rather than failing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_value.py`:
```python
from ffhelper.config import Tunables
from ffhelper.value import build_board


def test_board_sorts_by_vona_and_fills_all_fields():
    players = [
        mk("a", "RB", 300.0, adp=1.0, stdev=0.5),
        mk("b", "RB", 290.0, adp=2.0, stdev=0.5),
        mk("c", "WR", 280.0, adp=200.0, stdev=5.0),   # certain to survive
    ]
    board = build_board(
        available=players, my_roster=[], settings_slots=SLOTS, num_teams=12,
        current_pick=1, my_slot=3, tunables=Tunables(),
    )
    assert len(board) == 3
    assert board == sorted(board, key=lambda r: -r.vona)
    top = board[0]
    assert top.tier >= 1
    assert 0.0 <= top.survival <= 1.0
    assert isinstance(top.divergence, int)


def test_board_without_draft_slot_still_builds():
    """draft_slot is often unknown pre-draft; the board must not fail."""
    players = [mk("a", "RB", 300.0), mk("b", "WR", 280.0)]
    board = build_board(players, [], SLOTS, 12, current_pick=5, my_slot=None,
                        tunables=Tunables())
    assert len(board) == 2


def test_board_of_empty_pool_is_empty():
    assert build_board([], [], SLOTS, 12, 1, 3, Tunables()) == []


def test_marginal_value_reflects_existing_roster():
    slots = {"RB": 1, "FLEX": 0}
    roster = [mk("have", "RB", 300.0)]
    players = [mk("new", "RB", 100.0, adp=50.0)]
    board = build_board(players, roster, slots, 12, 1, 3, Tunables())
    assert board[0].marginal == 0.0, "a worse RB behind a filled slot adds nothing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_value.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_board'`

- [ ] **Step 3: Write the implementation**

Append to `ffhelper/value.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    player: Player
    vbd: float
    vona: float
    marginal: float
    tier: int
    survival: float
    divergence: int


def build_board(
    available: list[Player],
    my_roster: list[Player],
    settings_slots: dict[str, int],
    num_teams: int,
    current_pick: int,
    my_slot: int | None,
    tunables,
) -> list[Row]:
    """Assemble the ranked board. Pure: same inputs, same output, always."""
    if not available:
        return []

    at_pick = (
        next_pick_number(current_pick, my_slot, num_teams)
        if my_slot
        else current_pick + 1
    )
    ranks = replacement_ranks(settings_slots, num_teams, tunables.flex_share)
    repl = replacement_points(available, ranks)
    vbd_scores = vbd(available, repl)
    tiers = assign_tiers(available, vbd_scores, tunables.tier_break_sigma)
    divs = divergence(available, vbd_scores)

    rows = [
        Row(
            player=p,
            vbd=vbd_scores[p.sleeper_id],
            vona=vona(available, p, at_pick),
            marginal=marginal_value(my_roster, p, settings_slots),
            tier=tiers[p.sleeper_id],
            survival=survival_prob(p, at_pick),
            divergence=divs[p.sleeper_id],
        )
        for p in available
    ]
    return sorted(rows, key=lambda r: -r.vona)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_value.py -v`
Expected: PASS, 25 tests

- [ ] **Step 5: Ready to commit**

Files: `ffhelper/value.py`, `tests/test_value.py`
Suggested message: `feat: assemble the ranked draft board`

---

### Task 12: CLI — render, live loop, manual mode, preflight

**Files:**
- Create: `ffhelper/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces: `render(board: list[Row], limit: int, stale_seconds: float, my_roster: list[Player], runs: dict[str, int]) -> str`; `load_board_inputs(league, tunables, season) -> tuple[dict[str, Player], LeagueSettings]`; `main(argv: list[str] | None = None) -> int`

Subcommands: `run --league NAME`, `preflight --league NAME`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from ffhelper.cli import render
from ffhelper.data import Player
from ffhelper.value import Row


def row(pid: str, name: str, pos: str, vona: float, surv: float, div: int = 0,
        injury: str | None = None) -> Row:
    p = Player(pid, name, pos, "SF", injury_status=injury, adp=10.0, adp_stdev=3.0)
    return Row(player=p, vbd=vona, vona=vona, marginal=vona, tier=1,
               survival=surv, divergence=div)


def test_render_includes_players_and_headers():
    out = render([row("a", "Jahmyr Gibbs", "RB", 50.0, 0.2)], limit=10,
                 stale_seconds=0.0, my_roster=[], runs={})
    assert "Jahmyr Gibbs" in out
    assert "VONA" in out and "SURV" in out


def test_render_respects_limit():
    board = [row(str(i), f"Player {i}", "RB", 50.0 - i, 0.5) for i in range(30)]
    out = render(board, limit=5, stale_seconds=0.0, my_roster=[], runs={})
    assert "Player 4" in out
    assert "Player 5" not in out


def test_render_shows_stale_banner_only_when_stale():
    board = [row("a", "A", "RB", 1.0, 0.5)]
    assert "STALE" in render(board, 5, stale_seconds=45.0, my_roster=[], runs={})
    assert "STALE" not in render(board, 5, stale_seconds=2.0, my_roster=[], runs={})


def test_render_flags_injuries():
    out = render([row("a", "Hurt Guy", "RB", 50.0, 0.5, injury="PUP")],
                 limit=5, stale_seconds=0.0, my_roster=[], runs={})
    assert "PUP" in out


def test_render_shows_position_run():
    out = render([row("a", "A", "RB", 1.0, 0.5)], limit=5, stale_seconds=0.0,
                 my_roster=[], runs={"RB": 5, "WR": 3})
    assert "RB" in out and "5" in out


def test_render_empty_board_does_not_crash():
    assert isinstance(render([], 10, 0.0, [], {}), str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.cli'`

- [ ] **Step 3: Write the implementation**

`ffhelper/cli.py`:
```python
"""Terminal draft board. Phase 3 replaces render() with Dash; the engine is
identical either way.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import (
    LeagueSettings, Player, adp_format_for, apply_ffc_adp, apply_projections,
    apply_sleeper_adp, load_ffc_adp, load_players, load_projections,
    load_sleeper_settings,
)
from ffhelper.feeds import PickFeed, SleeperFeed
from ffhelper.value import Row, build_board, detect_run, next_pick_number

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SEASON = "2026"


def render(
    board: list[Row], limit: int, stale_seconds: float,
    my_roster: list[Player], runs: dict[str, int],
) -> str:
    lines: list[str] = []
    if stale_seconds > 15:
        lines.append(f"!!  FEED STALE {stale_seconds:.0f}s  -- board may be out of date")
    if runs:
        summary = "  ".join(f"{pos} {n}" for pos, n in sorted(runs.items(), key=lambda kv: -kv[1]))
        lines.append(f"last 8 picks:  {summary}")
    if my_roster:
        lines.append("my roster:  " + ", ".join(f"{p.name} ({p.position})" for p in my_roster))
    lines.append("")
    lines.append(f"{'#':<3} {'PLAYER':<24} {'POS':<4} {'VONA':>7} {'VBD':>7} "
                 f"{'MARG':>7} {'TIER':>4} {'SURV':>6} {'DIV':>5}  FLAGS")
    for i, r in enumerate(board[:limit], 1):
        flags = []
        if r.player.injury_status:
            flags.append(r.player.injury_status)
        if abs(r.divergence) >= 25:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        if r.player.bye:
            flags.append(f"bye{r.player.bye}")
        lines.append(
            f"{i:<3} {r.player.name[:24]:<24} {r.player.position:<4} {r.vona:>7.1f} "
            f"{r.vbd:>7.1f} {r.marginal:>7.1f} {r.tier:>4} {r.survival:>6.0%} "
            f"{r.divergence:>+5}  {' '.join(flags)}"
        )
    return "\n".join(lines)


def load_board_inputs(
    league: League, tunables: Tunables, season: str = SEASON
) -> tuple[dict[str, Player], LeagueSettings]:
    """Cold start: fetch everything, join by ID, then enrich with FFC."""
    if league.platform != "sleeper":
        raise NotImplementedError(
            "Yahoo settings arrive in Phase 2; run Phase 0's scripts/yahoo_auth.py first"
        )
    settings = load_sleeper_settings(league.league_id)
    players = load_players()
    projections = load_projections(season)

    apply_projections(players, projections, settings.scoring)
    fmt = league.adp_format or adp_format_for(settings)
    apply_sleeper_adp(players, projections, f"adp_{fmt.replace('-', '_')}")

    teams = league.adp_teams or settings.num_teams
    unmatched = apply_ffc_adp(players, load_ffc_adp(fmt, teams, int(season)))
    if unmatched:
        # Printed, never silently dropped.
        print(f"FFC: {len(unmatched)} unmatched -> {', '.join(unmatched[:15])}"
              + (" ..." if len(unmatched) > 15 else ""), file=sys.stderr)

    # Drop players with no projection: they cannot be ranked.
    return {pid: p for pid, p in players.items() if p.proj_pts > 0}, settings


def _run(league: League, tunables: Tunables, limit: int) -> int:
    players, settings = load_board_inputs(league, tunables)
    if not settings.draft_id:
        print("league has no draft_id yet", file=sys.stderr)
        return 1

    feed: PickFeed = SleeperFeed(settings.draft_id)
    manual_gone: set[str] = set()
    picks: list = []
    last_ok = time.time()
    interval = tunables.poll_seconds.get(league.platform, 5)

    while True:
        try:
            picks = feed.get_picks()
            last_ok = time.time()
        except Exception as exc:                      # noqa: BLE001 - loop must never die
            log.warning("poll failed: %s", exc)

        drafted = {p.sleeper_id for p in picks} | manual_gone
        available = [p for pid, p in players.items() if pid not in drafted]
        my_roster: list[Player] = []                  # populated in Phase 2 via roster_id
        recent = [players[p.sleeper_id].position for p in picks[-8:] if p.sleeper_id in players]

        board = build_board(
            available, my_roster, settings.roster_slots, settings.num_teams,
            current_pick=len(picks) + 1, my_slot=league.draft_slot, tunables=tunables,
        )
        print("\033[2J\033[H", end="")                # clear screen
        print(render(board, limit, time.time() - last_ok, my_roster, detect_run(recent)))
        if league.draft_slot:
            nxt = next_pick_number(len(picks) + 1, league.draft_slot, settings.num_teams)
            print(f"\npick {len(picks) + 1}   your next pick: {nxt} "
                  f"({nxt - len(picks) - 1} away)")
        print("\n(ctrl-c to stop; run `preflight` before the draft)")
        time.sleep(interval)


def _preflight(league: League, tunables: Tunables) -> int:
    """Validate everything before draft day. Run this the morning of."""
    ok = True
    players, settings = load_board_inputs(league, tunables)
    print(f"league          : {league.name} ({league.platform})")
    print(f"teams           : {settings.num_teams}")
    print(f"roster slots    : {settings.roster_slots}")
    print(f"scoring keys    : {len(settings.scoring)}  (pass_td={settings.scoring.get('pass_td')})")
    print(f"draft_id        : {settings.draft_id}")
    print(f"players w/ proj : {len(players)}")

    no_stdev = [p.name for p in players.values() if p.adp_stdev is None]
    print(f"missing stdev   : {len(no_stdev)}")
    if league.draft_slot is None:
        print("draft_slot      : NOT SET -- board will degrade to next-pick survival")
        ok = False
    else:
        print(f"draft_slot      : {league.draft_slot}")

    if settings.draft_id:
        try:
            n = len(SleeperFeed(settings.draft_id).get_picks())
            print(f"feed reachable  : yes ({n} picks so far)")
        except Exception as exc:                      # noqa: BLE001
            print(f"feed reachable  : NO -- {exc}")
            ok = False
    print("\nPREFLIGHT OK" if ok else "\nPREFLIGHT INCOMPLETE -- see above")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="ffhelper")
    ap.add_argument("command", choices=["run", "preflight"])
    ap.add_argument("--league", required=True)
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)

    leagues, tunables = load_config(args.config)
    league = get_league(leagues, args.league)
    if args.command == "preflight":
        return _preflight(league, tunables)
    try:
        return _run(league, tunables, args.limit)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS, 37 tests total

- [ ] **Step 6: Run preflight against the real league**

Run: `python -m ffhelper.cli preflight --league sleeper-main`

Expected: prints 12 teams, the roster slots, `pass_td=6.0`, a real `draft_id`, several hundred players with projections, and the FFC unmatched list. It will report `draft_slot: NOT SET` — that is correct until the draft order is final.

**This is the first contact with all four live sources at once.** Record anything surprising (unmatched count far above ~30, missing positions, scoring keys absent) in `CLAUDE.md`.

- [ ] **Step 7: Ready to commit**

Files: `ffhelper/cli.py`, `tests/test_cli.py`
Suggested message: `feat: add terminal draft board with preflight`

---

### Task 13: Integration test against a live Sleeper mock draft

**Files:**
- Modify: `CLAUDE.md`

This is the task that de-risks Phase 2. It uses no new code — it exercises everything end to end against moving picks.

- [ ] **Step 1: Create a Sleeper mock draft**

Hand off to the user: create a free mock draft in the Sleeper app, then read the `draft_id` from the mock draft URL.

- [ ] **Step 2: Point a temporary league at it**

Add to `config.toml`:
```toml
[[league]]
name = "mock"
platform = "sleeper"
league_id = "1395959490938966016"   # settings source; picks come from the mock
draft_slot = 1
```

- [ ] **Step 3: Run the board against live picks**

Run: `python -m ffhelper.cli run --league mock`

Verify while picks come in: drafted players disappear from the board; VONA reorders as position runs develop; the survival column falls for players near their ADP; the stale banner appears if you kill your wifi for 20 seconds and clears when it returns.

- [ ] **Step 4: Record results**

Update `CLAUDE.md`: set Phases 0 and 1 to complete, add a session-log entry noting what the mock draft revealed, and list anything that behaved unexpectedly.

- [ ] **Step 5: Ready to commit**

Files: `CLAUDE.md`, `config.toml`
Suggested message: `docs: record phase 0-1 completion and mock draft findings`

---

## Self-review

**Spec coverage.** Custom scoring → Task 5. VBD/replacement → Task 7. Tiers → Task 7. Survival/VONA → Task 9. `lineup_value` → Task 8. ADP divergence → Task 9. Run detection → Task 9. Crosswalk → Task 4. FFC enrichment + curve fallback → Task 6. Multi-league config → Task 2. Settings auto-sync → Task 5. Injury flags → Tasks 4 and 12. Disk cache + stale fallback → Task 3. Loop never dies → Task 12. Manual mark-drafted → **partially deferred, see below.** Preflight → Task 12. Yahoo OAuth → Task 1. Feed protocol → Task 10.

**Two known gaps, deliberate and named:**

1. **Manual mark-drafted is only half-built.** Task 12 threads a `manual_gone` set through the loop, but nothing writes to it — that needs non-blocking keyboard input, which does not fit cleanly beside a `time.sleep` poll and would bloat this plan's last task. It is a small standalone task at the top of the Phase 2 plan, and it must land before Sept 1 since it is the Yahoo fallback.
2. **`my_roster` is always empty in Phase 1**, so the `MARG` column reads 0.0 in the live board. Populating it needs the user's `roster_id`, which is Phase 2's roster-identification work. `marginal_value` itself is fully implemented and tested — only the wiring is deferred.

**SQLite draft logging is Phase 2 by design**, per the spec's phase table.

**Type consistency checked:** `Player` fields are consistent across Tasks 4–12; `Row` fields match between Tasks 11 and 12; `next_pick_number`, `survival_prob`, `vona`, `divergence`, `detect_run` signatures match their call sites in `build_board`; `Tunables.flex_share` and `.poll_seconds` are used as defined in Task 2.
