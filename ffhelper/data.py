"""Fetching, caching, and joining of all external data into list[Player]."""
import csv
import io
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
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


def _write_cache_atomic(path: Path, text: str) -> None:
    """tempfile.mkstemp + os.replace so a reader never sees a partial cache file."""
    cache_dir = path.parent
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
    stale_ok: bool = True,
) -> Any:
    """Fetch JSON with a write-through disk cache and stale-on-failure fallback.

    Draft night depends on this: a failed refresh must degrade to stale data,
    never to an exception, whenever any cached copy exists.

    `stale_ok=False` turns that off for live data, where a silently-stale answer
    is WORSE than an error: the pick list must raise on a failed poll so the
    caller can show the feed is dead. Returning yesterday's picks looks healthy
    and is wrong -- the same class of bug as a frozen pick counter.
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
        if not stale_ok:
            raise
        return _stale_fallback(path, exc, cache_key)

    _write_cache_atomic(path, text)
    return json.loads(text)


SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
CROSSWALK_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
)
DRAFTABLE = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Sentinel for "no ADP data at all", not "goes at pick 999". A third of the real
# pool carries it. Survival treats it correctly (those players genuinely do not
# get drafted), but anything that RANKS by adp must exclude it -- see
# value.divergence.
ADP_UNKNOWN = 999.0


@dataclass
class Player:
    sleeper_id: str
    name: str
    position: str
    team: str | None
    yahoo_id: str | None = None
    # nflverse's key. Same crosswalk, same job it already does for yahoo_id --
    # direct from Sleeper the coverage is 3/15 on a real roster, through the
    # crosswalk it is 14/15, the miss being a team defense (which has no injury
    # report at all).
    gsis_id: str | None = None
    injury_status: str | None = None
    injury_body_part: str | None = None
    practice_participation: str | None = None
    depth_chart_order: int | None = None
    proj_pts: float = 0.0
    adp: float = ADP_UNKNOWN
    adp_stdev: float | None = None
    bye: int | None = None

    @property
    def match_key(self) -> str:
        """Key for the FFC fuzzy join ONLY. Never used for ID-keyed sources."""
        return f"{norm_name(self.name)}|{norm_position(self.position)}|{self.team or ''}"


# Generational suffixes, stripped as whole trailing TOKENS (never substrings) so a
# surname that merely ends in these letters (e.g. "Ridley") is left alone.
_SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv", "v"}

# FFC position codes that differ from Sleeper's. PK->K is the real, measured bug
# (every kicker failed to match); DST/D-ST are defensive since FFC's DEF rows
# already match on team code, not this alias.
_POSITION_ALIASES = {"PK": "K", "DST": "DEF", "D/ST": "DEF"}


def norm_position(pos: str | None) -> str:
    pos = (pos or "").upper()
    return _POSITION_ALIASES.get(pos, pos)


def norm_name(s: str) -> str:
    # Fold accented characters to their ASCII base (Piñeiro -> Pineiro) instead of
    # dropping them, then tokenize on letters so trailing suffix tokens can be
    # detected and stripped without touching names that merely end in those letters.
    folded = unicodedata.normalize("NFKD", (s or ""))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z]+", folded.lower())
    if tokens and tokens[-1] in _SUFFIX_TOKENS:
        tokens = tokens[:-1]
    return "".join(tokens)


def build_players(raw: dict, crosswalk: dict[str, str],
                  gsis: dict[str, str] | None = None) -> dict[str, Player]:
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
            gsis_id=(gsis or {}).get(pid),
            injury_status=p.get("injury_status"),
            injury_body_part=p.get("injury_body_part"),
            practice_participation=p.get("practice_participation"),
            # int() not `or 0`: a missing depth chart must stay None, because 0
            # would read as "first string" for everyone Sleeper has no data on.
            depth_chart_order=(int(p["depth_chart_order"])
                               if p.get("depth_chart_order") is not None else None),
        )
    return out


def load_crosswalk(cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None,
                   field: str = "yahoo_id") -> dict[str, str]:
    """sleeper_id -> `field`. Fetches the DynastyProcess CSV, transforms it into a
    mapping, and caches that mapping as JSON using the same atomic-write / tolerant-read
    / stale-on-failure cache mechanics as fetch_json.

    `field` because the same 12484-row file carries `gsis_id` alongside
    `yahoo_id`, and nflverse's injury report joins on that. One parameter beats
    a second loader over the same CSV; the cache key carries the field, or the
    second caller would be served the first one's mapping and every id would be
    silently wrong."""
    fetcher = fetcher or _requests_get
    cache_dir = Path(cache_dir)
    path = cache_dir / f"crosswalk_{field}.json"

    fresh, value = _try_read_cache(path, 86_400)
    if fresh:
        return value

    try:
        text = fetcher(CROSSWALK_URL)
    except Exception as exc:
        return _stale_fallback(path, exc, f"crosswalk_{field}")

    rows = csv.DictReader(io.StringIO(text))
    mapping = {
        r["sleeper_id"]: r[field]
        for r in rows
        if r.get("sleeper_id", "").strip() and r.get(field, "").strip() not in ("", "NA")
    }
    _write_cache_atomic(path, json.dumps(mapping))
    return mapping


def load_players(cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> dict[str, Player]:
    raw = fetch_json(SLEEPER_PLAYERS_URL, "sleeper_players", cache_dir=cache_dir, fetcher=fetcher)
    crosswalk = load_crosswalk(cache_dir=cache_dir, fetcher=fetcher)
    gsis = load_crosswalk(cache_dir=cache_dir, fetcher=fetcher, field="gsis_id")
    return build_players(raw, crosswalk, gsis)


SLEEPER_LEAGUE_URL = "https://api.sleeper.app/v1/league/{league_id}"
SLEEPER_PROJ_URL = (
    "https://api.sleeper.com/projections/nfl/{season}"
    "?season_type=regular&position[]={pos}&order_by=pts_ppr"
)
SLEEPER_WEEKLY_PROJ_URL = (
    "https://api.sleeper.com/projections/nfl/{season}/{week}"
    "?season_type=regular&position[]={pos}&order_by=pts_ppr"
)
SLEEPER_WEEKLY_STATS_URL = (
    "https://api.sleeper.com/stats/nfl/{season}/{week}"
    "?season_type=regular&position[]={pos}&order_by=pts_ppr"
)
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_USERS_URL = "https://api.sleeper.app/v1/league/{league_id}/users"
SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"


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


def rosters_cache_key(league_id: str) -> str:
    """The `.cache/<key>.json` key `load_league_rosters` writes under.

    Exported so `cli.cache_age_minutes` can name the exact same key instead of
    composing the literal by hand a second time -- a rename here would
    otherwise silently stop the CLI's stale-roster warning from ever firing.
    """
    return f"rosters_{league_id}"


def load_league_rosters(
    league_id: str, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> list[dict]:
    """Every team's roster. Public: Sleeper needs no auth for this."""
    return fetch_json(
        SLEEPER_ROSTERS_URL.format(league_id=league_id), rosters_cache_key(league_id),
        ttl_seconds=300, cache_dir=cache_dir, fetcher=fetcher,
    )


def load_league_users(
    league_id: str, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> list[dict]:
    """Managers, so a derived roster can be shown with its owner's name."""
    return fetch_json(
        SLEEPER_USERS_URL.format(league_id=league_id), f"users_{league_id}",
        ttl_seconds=3600, cache_dir=cache_dir, fetcher=fetcher,
    )


def load_nfl_state(
    cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> dict:
    """Current week and season. Short TTL: this is what makes a Tuesday run
    ask about the right week without the user typing one."""
    return fetch_json(
        SLEEPER_STATE_URL, "nfl_state", ttl_seconds=600,
        cache_dir=cache_dir, fetcher=fetcher,
    )


SLEEPER_TRENDING_URL = (
    "https://api.sleeper.app/v1/players/nfl/trending/{kind}"
    "?lookback_hours={hours}&limit={limit}"
)


def load_trending(
    kind: str, lookback_hours: int = 24, limit: int = 100,
    cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None,
) -> dict[str, int]:
    """Adds or drops across all of Sleeper in the last `lookback_hours`.

    NATIONAL counts, across millions of leagues -- they say nothing about
    whether your own leaguemates want a player, and must never be used to
    predict whether a claim wins. Price description only; see the spec.

    The cache key carries the kind. Without it the second caller is served the
    first one's answer and every drop count is silently an add count -- the same
    defect the weekly-projection key was fixed for.
    """
    if kind not in ("add", "drop"):
        raise ValueError(f"trending kind must be 'add' or 'drop', got {kind!r}")
    rows = fetch_json(
        SLEEPER_TRENDING_URL.format(kind=kind, hours=lookback_hours, limit=limit),
        f"trending_{kind}_{lookback_hours}h",
        ttl_seconds=3600,
        cache_dir=cache_dir,
        fetcher=fetcher,
    )
    return {r["player_id"]: r.get("count", 0) for r in rows if r.get("player_id")}


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


def load_weekly_projections(
    season: str, week: int, cache_dir: Path = CACHE_DIR,
    fetcher: Callable[[str], str] | None = None,
) -> list[dict]:
    """One week's projections, same row shape as `load_projections`.

    The SEASON endpoint is frozen preseason -- `backtest.py` proves it, every
    player carries gp=18 regardless of what happened -- so it is useless once
    anyone is hurt. The weekly endpoint IS revised: verified on 2025, where
    Ekeler reads 12.1, 10.4, then 0.0 for every week after his week-3 injury.

    The cache key carries the week. Without it, week 2 would be served week 1's
    numbers for the rest of the season and the board would look healthy.
    """
    rows: list[dict] = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        rows.extend(
            fetch_json(
                SLEEPER_WEEKLY_PROJ_URL.format(season=season, week=week, pos=pos),
                f"proj_{season}_wk{week}_{pos}",
                ttl_seconds=3600,
                cache_dir=cache_dir,
                fetcher=fetcher,
            )
        )
    return rows


def load_weekly_actuals(
    season: str, week: int, cache_dir: Path = CACHE_DIR,
    fetcher: Callable[[str], str] | None = None,
) -> list[dict]:
    """One week's ACTUAL stat lines -- the mirror of `load_weekly_projections`.

    Same row shape, plus two fields the projections also carry and this is the
    only consumer of: `team` and `opponent`. That pair is the entire join for
    matchup strength -- who a player faced, and therefore what each defense
    gave up -- which is why Phase 4 needs no `nflreadpy`.

    Scored through `score_stats` like everything else, so "points allowed" is
    points under THIS league's rules, not a generic fantasy-points-against.

    Cached a day, not an hour: every caller asks only about COMPLETED weeks,
    and a played week never changes. A caller wanting the current week's numbers
    while games are running must pass a shorter `ttl_seconds` -- there is no
    such caller today, and inventing one for it would be inventing a
    requirement.
    """
    rows: list[dict] = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        rows.extend(
            fetch_json(
                SLEEPER_WEEKLY_STATS_URL.format(season=season, week=week, pos=pos),
                f"stats_{season}_wk{week}_{pos}",
                cache_dir=cache_dir,
                fetcher=fetcher,
            )
        )
    return rows


NFLVERSE_INJURIES_URL = ("https://github.com/nflverse/nflverse-data/releases/"
                         "download/injuries/injuries_{season}.csv")

# The report is filed in prose. These are the three values nflverse emits for
# `practice_status`, shortened for a terminal column. An unrecognised value is
# passed through rather than dropped -- a new designation must show up on
# screen looking odd, not vanish.
PRACTICE_DISPLAY = {
    "Did Not Participate In Practice": "DNP",
    "Limited Participation in Practice": "Limited",
    "Full Participation in Practice": "Full",
}


def load_nfl_injuries(
    season: str, week: int, cache_dir: Path = CACHE_DIR,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """gsis_id -> practice status, for one week. The one gap Sleeper does not fill.

    Sleeper carries `injury_status` for 256 players and `practice_participation`
    for **zero of 3231** -- measured, after the spec claimed otherwise off a
    single populated row. nflverse's weekly injury report has practice status on
    99% of its rows, joins on `gsis_id` through the crosswalk already fetched,
    and needs no new dependency: it is a plain CSV on a GitHub release, read
    with `requests` and stdlib `csv`.

    Only the practice half is returned. `injury_status` stays Sleeper's, which
    is updated continuously, where this file is the official Wed-Fri report --
    fresher beats more official for a Sunday morning lineup.

    **`injuries_<season>.csv` does not exist until week 1 has been played**, so
    the whole of the preseason this raises and the caller shows no practice
    column. That is the designed degradation, not a failure.
    """
    fetcher = fetcher or _requests_get
    cache_dir = Path(cache_dir)
    path = cache_dir / f"injuries_{season}_wk{week}.json"

    fresh, value = _try_read_cache(path, 3600)
    if fresh:
        return value

    try:
        text = fetcher(NFLVERSE_INJURIES_URL.format(season=season))
    except Exception as exc:
        return _stale_fallback(path, exc, f"injuries_{season}_wk{week}")

    mapping = {
        r["gsis_id"]: PRACTICE_DISPLAY.get(r["practice_status"], r["practice_status"])
        for r in csv.DictReader(io.StringIO(text))
        if r.get("gsis_id", "").strip() and r.get("practice_status", "").strip()
        and r.get("week", "").strip() == str(week)
    }
    _write_cache_atomic(path, json.dumps(mapping))
    return mapping


FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams={teams}&year={year}"

# Fitted from FFC 12-team PPR data on 2026-08-24: stdev = 0.287 * adp^0.809,
# R^2 = 0.574. Used only as a fallback when FFC has no row for a player.
# ponytail: refit if it drifts; a constant here would be worse than a bad fit.
_STDEV_A, _STDEV_B = 0.287, 0.809


def curve_stdev(adp: float) -> float:
    return _STDEV_A * max(adp, 0.1) ** _STDEV_B


# Sleeper's own key names, NOT derivable from the FFC format string: FFC says
# "standard" where Sleeper's key is `adp_std`. Deriving the key by string
# munging produced `adp_standard`, which Sleeper does not emit, so every player
# in a standard-scoring league silently kept adp 999 -- a fabricated board that
# renders as if healthy. Explicit map, and apply_sleeper_adp warns on 0 matches.
SLEEPER_ADP_FIELD = {
    "ppr": "adp_ppr",
    "half-ppr": "adp_half_ppr",
    "standard": "adp_std",
}


def apply_sleeper_adp(
    players: dict[str, Player], projections: list[dict], adp_field: str
) -> None:
    """ID-keyed ADP. Runs BEFORE the FFC join so every player has a value.

    Degrade, never fabricate: a field name that matches nothing leaves every
    player at adp 999, which looks like a working board. Say so instead.
    """
    matched = 0
    for row in projections:
        pid = row.get("player_id")
        stats = row.get("stats") or {}
        if not pid or pid not in players:
            continue
        adp = stats.get(adp_field)
        if adp is None or adp >= ADP_UNKNOWN:
            continue
        players[pid].adp = float(adp)
        players[pid].adp_stdev = curve_stdev(float(adp))
        matched += 1
    if not matched:
        log.warning(
            "no projection row carried ADP field %r -- every player keeps adp 999, "
            "so survival and VONA are meaningless. Known Sleeper fields: %s",
            adp_field, sorted(SLEEPER_ADP_FIELD.values()),
        )


_AMBIGUOUS_PREFIX = "AMBIGUOUS: "


def apply_ffc_adp(
    players: dict[str, Player], ffc_rows: list[dict], set_adp: bool = True
) -> list[str]:
    """Non-load-bearing enrichment. Supplies adp/adp_stdev/bye where matched.

    `set_adp=False` takes ONLY the bye week and leaves adp/adp_stdev alone --
    for leagues whose ADP source is not FFC. Bye weeks come from nowhere else
    (Sleeper's player DB has no bye field), so this join always runs; only the
    ADP overwrite is optional.

    FFC carries no cross-platform ID, so this is the one fuzzy join in the
    system. It runs LAST, on an already-complete ID-keyed board, so the blast
    radius of a miss is three fields on one player. Returns names for the
    caller to print -- never silently dropped, and never guessed: a
    match_key shared by two or more players is ambiguous and is excluded
    from matching entirely (neither player is touched). Ambiguous rows are
    reported with an "AMBIGUOUS: " prefix so the caller can tell "matched
    nothing" apart from "matched an unresolvable key" without a type change.
    """
    by_key: dict[str, list[Player]] = {}
    for p in players.values():
        by_key.setdefault(p.match_key, []).append(p)
    # Sleeper DEF entries have full_name == "" and player_id == team code, so name
    # matching can never work for them; join on team code instead. Group by team
    # and apply the same ambiguity guard: a team code shared by 2+ DEF entries
    # is ambiguous and is excluded from matching entirely.
    by_def_team: dict[str, list[Player]] = {}
    for p in players.values():
        if p.position == "DEF" and p.team:
            by_def_team.setdefault(p.team, []).append(p)
    unmatched: list[str] = []
    for row in ffc_rows:
        position = norm_position(row.get("position", ""))
        team = row.get("team", "") or ""
        name = row.get("name", "<unnamed>")
        if position == "DEF":
            candidates = by_def_team.get(team, [])
            if len(candidates) > 1:
                unmatched.append(f"{_AMBIGUOUS_PREFIX}{name}")
                continue
            target = candidates[0] if candidates else None
        else:
            key = f"{norm_name(row.get('name',''))}|{position}|{team}"
            candidates = by_key.get(key, [])
            if len(candidates) > 1:
                unmatched.append(f"{_AMBIGUOUS_PREFIX}{name}")
                continue
            target = candidates[0] if candidates else None
        if target is None:
            unmatched.append(name)
            continue
        if set_adp and row.get("adp") is not None:
            target.adp = float(row["adp"])
        if set_adp and row.get("stdev"):
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
