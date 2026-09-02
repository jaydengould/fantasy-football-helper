# Phase 4a — start/sit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m ffhelper.cli lineup --league <name>` prints the optimal starting lineup for the current NFL week, the bench, and every close start/sit call, under that league's own scoring.

**Architecture:** New pure module `ffhelper/season.py` holds all logic and imports `value.optimal_lineup`; `data.py` gains loaders only; `cli.py` gains one subcommand and the file-reading path for leagues with no API. The Sleeper roster is read from the API and the correct roster is derived from the draft, because `draft_slot` is NOT `roster_id`. Yahoo's roster is read from a hand-maintained text file.

**Tech Stack:** Python 3.12 stdlib + `requests`. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-09-01-phase-4-season-mode-design.md`

## Global Constraints

- **Python 3.12, stdlib first.** Runtime dependencies stay exactly `requests`, `yfpy`, `dash`. This slice adds none.
- **`ffhelper/season.py` is PURE.** No I/O, no network, no module-level state, no league globals. Same rule as `value.py`. If something in it wants to fetch, the design is wrong.
- **Never join on player name.** Everything joins on `sleeper_id`. The one name-based path (the Yahoo roster file) must report ambiguity rather than guess — Bijan and Brian Robinson are both ATL RBs.
- **Degrade, never fabricate.** A missing source removes a labelled column; it never becomes 0.0 or a guess.
- **Unmatched players are printed, never silently dropped.**
- **Never commit projections or roster data.** `.roster/` and `.cache/` are gitignored.
- **Every new test must be seen to FAIL first**, with `git stash push -u -- ffhelper && pytest -k <name>`. The `-u` is mandatory — `season.py` is a NEW file and plain `git stash` leaves it on disk, so the test would pass while proving nothing.
- **Add a mutation to `scripts/mutate.py`** alongside each piece of non-trivial logic. Run `.venv/bin/python scripts/mutate.py` in the FOREGROUND, and confirm the suite is green before believing its output.
- Commands are `.venv/bin/python -m ffhelper.cli ...`. There is no `ffhelper` console script and this plan does not add one.

---

### Task 1: Weekly projections loader

**Files:**
- Modify: `ffhelper/data.py` (beside `SLEEPER_PROJ_URL` and `load_projections`, ~line 220)
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: existing `fetch_json`, `SLEEPER_PROJ_URL` pattern.
- Produces: `load_weekly_projections(season: str, week: int, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> list[dict]` — same row shape as `load_projections`.

- [ ] **Step 1: Write the failing test**

```python
def test_load_weekly_projections_asks_for_the_week_and_caches_per_week(tmp_path):
    """The season endpoint is frozen preseason; only the weekly one is revised
    in-season. The cache key must carry the week, or week 2 is served week 1's
    numbers for the rest of the season while looking healthy."""
    seen = []

    def fake(url):
        seen.append(url)
        return '[{"player_id": "4034", "stats": {"pts_ppr": 21.5, "rush_yd": 88.0}}]'

    rows = data.load_weekly_projections("2026", 3, cache_dir=tmp_path, fetcher=fake)

    assert all("/2026/3?" in u for u in seen), seen
    assert len(rows) == 6          # one call per position
    assert rows[0]["stats"]["rush_yd"] == 88.0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any("wk3" in n for n in names), names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k load_weekly_projections -q; git stash pop`
Expected: FAIL with `AttributeError: module 'ffhelper.data' has no attribute 'load_weekly_projections'`

- [ ] **Step 3: Write minimal implementation**

```python
SLEEPER_WEEKLY_PROJ_URL = (
    "https://api.sleeper.com/projections/nfl/{season}/{week}"
    "?season_type=regular&position[]={pos}&order_by=pts_ppr"
)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -k load_weekly_projections -q`
Expected: PASS

- [ ] **Step 5: Add the mutation**

In `scripts/mutate.py`, under the `"data.py"` key:

```python
        ("weekly projection cache key drops the week -- every week serves week 1",
         'f"proj_{season}_wk{week}_{pos}"', 'f"proj_{season}_{pos}"'),
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; the new mutation reports `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/data.py tests/test_data.py scripts/mutate.py
git commit -m "feat(data): load weekly projections, cached per week"
```

---

### Task 2: Carry the player-status fields already being fetched

**Files:**
- Modify: `ffhelper/data.py` — `Player` dataclass (~line 121) and `build_players` (~line 182)
- Test: `tests/test_data.py`

**Interfaces:**
- Produces: `Player.practice_participation: str | None`, `Player.depth_chart_order: int | None`, `Player.injury_body_part: str | None`. `Player.injury_status` already exists.

- [ ] **Step 1: Write the failing test**

```python
def test_build_players_carries_status_fields_and_tolerates_their_absence():
    """Sleeper's player DB has 52 fields and we keep six. These four are the
    structured form of the injury news start/sit needs, and depth_chart_order is
    the waiver signal: the backup who becomes the starter on Wednesday.

    Absent fields must be None, never 0 -- depth_chart_order 0 would read as
    'first on the depth chart' for every player Sleeper has no data for."""
    raw = {
        "1": {"player_id": "1", "full_name": "Hurt Guy", "position": "RB", "team": "SEA",
              "injury_status": "Questionable", "injury_body_part": "Ankle",
              "practice_participation": "Limited", "depth_chart_order": 1},
        "2": {"player_id": "2", "full_name": "Fine Guy", "position": "RB", "team": "SEA"},
    }
    players = data.build_players(raw, crosswalk={})

    assert players["1"].injury_status == "Questionable"
    assert players["1"].injury_body_part == "Ankle"
    assert players["1"].practice_participation == "Limited"
    assert players["1"].depth_chart_order == 1
    assert players["2"].practice_participation is None
    assert players["2"].depth_chart_order is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k carries_status_fields -q; git stash pop`
Expected: FAIL with `AttributeError: 'Player' object has no attribute 'practice_participation'`

- [ ] **Step 3: Write minimal implementation**

In the `Player` dataclass, after `injury_status`:

```python
    injury_body_part: str | None = None
    practice_participation: str | None = None
    depth_chart_order: int | None = None
```

In `build_players`, beside the existing `injury_status=p.get("injury_status"),`:

```python
            injury_body_part=p.get("injury_body_part"),
            practice_participation=p.get("practice_participation"),
            # int() not `or 0`: a missing depth chart must stay None, because 0
            # would read as "first string" for everyone Sleeper has no data on.
            depth_chart_order=(int(p["depth_chart_order"])
                               if p.get("depth_chart_order") is not None else None),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -k carries_status_fields -q`
Expected: PASS

- [ ] **Step 5: Add the mutation**

```python
        ("missing depth chart reads as first string",
         'depth_chart_order=(int(p["depth_chart_order"])\n'
         '                               if p.get("depth_chart_order") is not None else None),',
         'depth_chart_order=int(p.get("depth_chart_order") or 0),'),
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; new mutation `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/data.py tests/test_data.py scripts/mutate.py
git commit -m "feat(data): carry injury, practice and depth-chart fields"
```

---

### Task 3: `season.py` — score a week onto a roster

**Files:**
- Create: `ffhelper/season.py`
- Test: `tests/test_season.py` (create)

**Interfaces:**
- Consumes: `data.Player`, `data.score_stats`.
- Produces:
  - `weekly_points(projections: list[dict], scoring: dict[str, float]) -> dict[str, float]`
  - `with_weekly_points(roster: list[Player], weekly: dict[str, float]) -> list[Player]`

- [ ] **Step 1: Write the failing test**

```python
"""ffhelper.season is PURE -- these tests never touch the network."""
import pytest
from dataclasses import dataclass

from ffhelper.data import Player
from ffhelper import season


def mk(pid: str, pos: str, pts: float = 0.0) -> Player:
    return Player(pid, f"P{pid}", pos, "SEA", proj_pts=pts)


def test_weekly_points_scores_raw_stats_under_this_leagues_rules():
    """The same stat line is worth different points in the two leagues. Scoring
    a WEEK is the identical operation as scoring a season -- score_stats is
    reused rather than reimplemented."""
    rows = [
        {"player_id": "a", "stats": {"rec": 5.0, "rec_yd": 60.0, "rec_td": 0.5}},
        {"player_id": "b", "stats": {"rec": 5.0, "rec_yd": 60.0, "rec_td": 0.5}},
    ]
    full_ppr = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0}
    half_ppr = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0}

    assert season.weekly_points(rows, full_ppr)["a"] == pytest.approx(5 + 6 + 3)
    assert season.weekly_points(rows, half_ppr)["a"] == pytest.approx(2.5 + 6 + 3)


def test_weekly_points_skips_rows_with_no_stats_rather_than_scoring_zero():
    """A player with no projection this week (bye, or not in the payload) must be
    ABSENT, not 0.0. Absent lets the caller say 'no projection'; 0.0 is a claim
    that he will score nothing, which is a fabricated number."""
    rows = [{"player_id": "a", "stats": None}, {"player_id": "b"},
            {"stats": {"rec": 1.0}}]
    assert season.weekly_points(rows, {"rec": 1.0}) == {}


def test_with_weekly_points_returns_new_players_and_never_mutates_the_pool():
    """optimal_lineup ranks on proj_pts, which holds SEASON points. Start/sit
    must rank on the WEEK. Copying rather than mutating keeps the season pool
    usable in the same process -- the draft board and this command share it."""
    roster = [mk("a", "RB", 250.0), mk("b", "RB", 200.0)]
    out = season.with_weekly_points(roster, {"a": 12.5})

    assert [p.proj_pts for p in out] == [12.5, 0.0]
    assert [p.proj_pts for p in roster] == [250.0, 200.0]
    assert out[0] is not roster[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest tests/test_season.py -q; git stash pop`
Expected: FAIL with `ModuleNotFoundError: No module named 'ffhelper.season'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Season mode: what to start, and who to add. PURE -- no I/O, no network.

Same rule as `value.py`, for the same reason: this is where the logic worth
testing lives, and it must test without a network. If something here wants to
fetch, the design is wrong -- put the loader in `data.py`.
"""
from dataclasses import dataclass, replace

from ffhelper.data import Player, score_stats


def weekly_points(projections: list[dict], scoring: dict[str, float]) -> dict[str, float]:
    """Score one week's projection rows under this league's rules.

    A row with no stats is OMITTED rather than scored 0.0. Absent means "no
    projection this week" and the caller can say so; 0.0 is a claim that the
    player will score nothing, which is a number the source never supplied.
    """
    out: dict[str, float] = {}
    for row in projections:
        pid, stats = row.get("player_id"), row.get("stats")
        if not pid or not stats:
            continue
        out[pid] = score_stats(stats, scoring)
    return out


def with_weekly_points(roster: list[Player], weekly: dict[str, float]) -> list[Player]:
    """Copies of `roster` whose `proj_pts` hold WEEKLY points.

    `optimal_lineup` ranks on `proj_pts`, which normally carries season totals.
    Rather than teach it a second field, hand it players scored for this week.
    Copies, never mutation: the season-scored pool is shared with the draft
    board in the same process, and silently rewriting it is how two views start
    disagreeing about one roster.
    """
    return [replace(p, proj_pts=weekly.get(p.sleeper_id, 0.0)) for p in roster]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_season.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the mutations**

Add a new `"season.py"` key to `MUTATIONS` in `scripts/mutate.py`. **`mutate.py` refuses to run on a duplicate key** — check no `"season.py"` key already exists before adding.

```python
    "season.py": [
        ("missing weekly projection scored as zero instead of omitted",
         "        if not pid or not stats:\n            continue",
         "        if not pid:\n            continue\n        stats = stats or {}"),
        ("weekly scoring mutates the shared season pool",
         "return [replace(p, proj_pts=weekly.get(p.sleeper_id, 0.0)) for p in roster]",
         "for p in roster:\n        p.proj_pts = weekly.get(p.sleeper_id, 0.0)\n    return roster"),
    ],
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; both new mutations `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): pure weekly scoring"
```

---

### Task 4: `season.py` — the start/sit decision

**Files:**
- Modify: `ffhelper/season.py`
- Test: `tests/test_season.py`

**Interfaces:**
- Consumes: `value.optimal_lineup`, `value.FLEX_ELIGIBLE`, Task 3's functions.
- Produces:
  - `@dataclass(frozen=True) class StartSit: lineup: list[tuple[str, Player | None]]; bench: list[Player]; close_calls: list[CloseCall]`
  - `@dataclass(frozen=True) class CloseCall: slot: str; starter: Player; challenger: Player; gap: float`
  - `start_sit(roster: list[Player], roster_slots: dict[str, int], close_call_points: float = 3.0) -> StartSit`

- [ ] **Step 1: Write the failing test**

```python
SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}


def test_start_sit_names_the_lineup_and_the_bench():
    """The lineup is value.optimal_lineup's -- imported, never re-derived. A
    second copy of the FLEX rule is what lets two views disagree about one
    roster (the Phase 3 lesson)."""
    roster = [mk("q", "QB", 20.0), mk("r1", "RB", 15.0), mk("r2", "RB", 12.0),
              mk("r3", "RB", 4.0), mk("w1", "WR", 14.0), mk("w2", "WR", 11.0),
              mk("t", "TE", 8.0), mk("k", "K", 7.0), mk("d", "DEF", 6.0)]
    got = season.start_sit(roster, SLOTS)

    assert [s for s, _ in got.lineup] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    assert [p.sleeper_id for _, p in got.lineup] == ["q", "r1", "r2", "w1", "w2", "t", "r3", "k", "d"]
    assert [p.sleeper_id for p in got.bench] == []


def test_start_sit_reports_a_close_call_and_ignores_a_blowout():
    """A 1.5-point gap is a decision; a 30-point gap is noise on the screen.
    Only the close ones are worth a human's attention."""
    roster = [mk("q", "QB", 20.0),
              mk("w1", "WR", 14.0), mk("w2", "WR", 11.0),
              mk("w3", "WR", 10.5),      # 0.5 behind w2 -- a real decision
              mk("w4", "WR", 2.0)]       # 9 behind -- not
    got = season.start_sit(roster, {"QB": 1, "WR": 2}, close_call_points=3.0)

    assert len(got.close_calls) == 1
    call = got.close_calls[0]
    assert (call.slot, call.starter.sleeper_id, call.challenger.sleeper_id) == ("WR", "w2", "w3")
    assert call.gap == pytest.approx(0.5)


def test_start_sit_never_offers_an_ineligible_challenger():
    """A kicker on the bench is not a challenger for a WR slot, however close his
    projection. FLEX_ELIGIBLE is value.py's rule and is imported, not restated."""
    roster = [mk("w1", "WR", 12.0), mk("k1", "K", 11.5), mk("k2", "K", 11.0)]
    got = season.start_sit(roster, {"WR": 1, "K": 1}, close_call_points=3.0)

    assert [(c.slot, c.challenger.sleeper_id) for c in got.close_calls] == [("K", "k2")]


def test_start_sit_reports_an_unfillable_slot_rather_than_hiding_it():
    """An empty slot is a roster problem the user must SEE -- it is the week's
    most important message and it must not be silently dropped."""
    got = season.start_sit([mk("q", "QB", 20.0)], {"QB": 1, "RB": 1})
    assert got.lineup == [("QB", got.lineup[0][1]), ("RB", None)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest tests/test_season.py -k start_sit -q; git stash pop`
Expected: FAIL with `AttributeError: module 'ffhelper.season' has no attribute 'start_sit'`

- [ ] **Step 3: Write minimal implementation**

Add to `ffhelper/season.py` (and extend the imports at the top with
`from ffhelper.value import FLEX_ELIGIBLE, optimal_lineup`):

```python
@dataclass(frozen=True)
class CloseCall:
    """A start/sit decision close enough that a human should look at it."""
    slot: str
    starter: Player
    challenger: Player
    gap: float


@dataclass(frozen=True)
class StartSit:
    lineup: list[tuple[str, Player | None]]
    bench: list[Player]
    close_calls: list[CloseCall]


def _eligible(player: Player, slot: str) -> bool:
    """Whether `player` may legally fill `slot`. FLEX is value.py's rule."""
    if slot == "FLEX":
        return player.position in FLEX_ELIGIBLE
    return player.position == slot


def start_sit(
    roster: list[Player], roster_slots: dict[str, int], close_call_points: float = 3.0
) -> StartSit:
    """The week's lineup, the bench, and the decisions worth a second look.

    The lineup is `value.optimal_lineup`'s, imported rather than re-derived --
    a second copy of that rule would let this command and the web board start
    different players from one roster.

    A close call is a bench player who is ELIGIBLE for a filled slot and within
    `close_call_points` of the man in it. The threshold exists because a
    30-point gap is not a decision, and printing it buries the 1.5-point one
    that is. It defaults to 3.0 and is expected to move once the weekly
    backtest measures the real weekly error.
    """
    lineup = optimal_lineup(roster, roster_slots)
    starting = {p.sleeper_id for _, p in lineup if p is not None}
    bench = sorted((p for p in roster if p.sleeper_id not in starting),
                   key=lambda p: -p.proj_pts)

    calls: list[CloseCall] = []
    for slot, starter in lineup:
        if starter is None:
            continue
        challenger = next((b for b in bench if _eligible(b, slot)), None)
        if challenger is None:
            continue
        gap = starter.proj_pts - challenger.proj_pts
        if gap <= close_call_points:
            calls.append(CloseCall(slot, starter, challenger, gap))
    return StartSit(lineup=lineup, bench=bench, close_calls=calls)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_season.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the mutations**

Append to the `"season.py"` list in `scripts/mutate.py`:

```python
        ("close-call challenger ignores slot eligibility (a kicker challenges a WR)",
         "challenger = next((b for b in bench if _eligible(b, slot)), None)",
         "challenger = next((b for b in bench), None)"),
        ("every gap reported, so the real decision is buried",
         "if gap <= close_call_points:", "if gap >= 0:"),
        ("bench ordered worst-first",
         "key=lambda p: -p.proj_pts)", "key=lambda p: p.proj_pts)"),
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; three new mutations `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): start/sit lineup, bench and close calls"
```

---

### Task 5: Read the Sleeper roster — and derive the RIGHT one

**Files:**
- Modify: `ffhelper/data.py` (loaders, after `load_sleeper_settings`)
- Modify: `ffhelper/season.py` (the pure derivation)
- Test: `tests/test_data.py`, `tests/test_season.py`

**Interfaces:**
- Produces:
  - `data.load_league_rosters(league_id: str, cache_dir=CACHE_DIR, fetcher=None) -> list[dict]`
  - `data.load_league_users(league_id: str, cache_dir=CACHE_DIR, fetcher=None) -> list[dict]`
  - `data.load_nfl_state(cache_dir=CACHE_DIR, fetcher=None) -> dict`
  - `season.roster_id_for_slot(picks, draft_slot: int) -> int | None` — `picks` is any sequence of `feeds.Pick`-shaped objects (`.draft_slot`, `.roster_id`); the module must NOT import `feeds`
  - `season.roster_player_ids(rosters: list[dict], roster_id: int) -> list[str]`

**MEASURED FACT this task exists for:** in the real 2026 league, `draft_slot` 5 maps to `roster_id` **3**, and `roster_id` 5 belongs to a different manager. Assuming they are the same number hands the user someone else's team, silently.

- [ ] **Step 1: Write the failing tests**

In `tests/test_season.py`:

```python
@dataclass
class FakePick:
    """Duck-types feeds.Pick. season.py must not import feeds -- that would drag
    `requests` into a module whose whole point is testing without a network.
    tests/test_board_agreement.py uses the same shape for the same reason."""
    draft_slot: int | None
    roster_id: int | None


def test_roster_id_is_derived_from_the_draft_not_assumed_equal_to_the_slot():
    """MEASURED on the real 2026 league: draft_slot 5 is roster_id 3, and
    roster_id 5 belongs to another manager. Assuming slot == roster_id hands the
    user someone else's team and every downstream number is silently wrong."""
    picks = [FakePick(5, 3), FakePick(1, 10), FakePick(5, 3)]
    assert season.roster_id_for_slot(picks, 5) == 3


def test_roster_id_is_none_when_the_draft_cannot_answer():
    """Sleeper MOCK drafts set roster_id to None on every pick. Returning a
    number anyway -- or defaulting to the slot -- is the fabrication this whole
    function exists to prevent."""
    assert season.roster_id_for_slot([FakePick(5, None)], 5) is None
    assert season.roster_id_for_slot([FakePick(1, 9)], 5) is None
    assert season.roster_id_for_slot([], 5) is None


def test_roster_id_refuses_to_choose_when_the_draft_disagrees_with_itself():
    """One slot mapping to two roster ids means the feed is malformed. Picking
    the first is a coin flip on which team you manage."""
    picks = [FakePick(5, 3), FakePick(5, 7)]
    assert season.roster_id_for_slot(picks, 5) is None


def test_roster_player_ids_returns_the_named_roster_only():
    rosters = [{"roster_id": 3, "players": ["a", "b"]},
               {"roster_id": 5, "players": ["c"]}]
    assert season.roster_player_ids(rosters, 3) == ["a", "b"]
    assert season.roster_player_ids(rosters, 99) == []
```

In `tests/test_data.py`:

```python
def test_league_loaders_hit_the_right_urls_and_cache_per_league(tmp_path):
    seen = []

    def fake(url):
        seen.append(url)
        return '[{"roster_id": 3, "players": ["a"]}]'

    got = data.load_league_rosters("123", cache_dir=tmp_path, fetcher=fake)
    assert seen == ["https://api.sleeper.app/v1/league/123/rosters"]
    assert got[0]["roster_id"] == 3
    assert any("rosters_123" in p.name for p in tmp_path.iterdir())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k "roster_id or roster_player_ids or league_loaders" -q; git stash pop`
Expected: FAIL — `season` has no `roster_id_for_slot`, `data` has no `load_league_rosters`.

- [ ] **Step 3: Write minimal implementation**

In `ffhelper/data.py`:

```python
SLEEPER_ROSTERS_URL = "https://api.sleeper.app/v1/league/{league_id}/rosters"
SLEEPER_USERS_URL = "https://api.sleeper.app/v1/league/{league_id}/users"
SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"


def load_league_rosters(
    league_id: str, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None
) -> list[dict]:
    """Every team's roster. Public: Sleeper needs no auth for this."""
    return fetch_json(
        SLEEPER_ROSTERS_URL.format(league_id=league_id), f"rosters_{league_id}",
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
```

In `ffhelper/season.py`:

```python
def roster_id_for_slot(picks, draft_slot: int) -> int | None:
    """Which `roster_id` belongs to the manager who drafted from `draft_slot`.

    THE TWO NUMBERS ARE NOT THE SAME. Measured on the real 2026 league:
    draft_slot 5 is roster_id 3, and roster_id 5 is another manager's team.
    Assuming they match hands the user someone else's roster, and every number
    downstream is then confidently wrong about the wrong team.

    Returns None rather than guessing when the draft cannot answer -- Sleeper
    mock drafts set `roster_id` to None on every pick -- or when one slot maps
    to more than one roster, which means the feed is malformed. The caller says
    so on screen; it never falls back to the slot number.
    """
    found = {p.roster_id for p in picks
             if p.draft_slot == draft_slot and p.roster_id is not None}
    return found.pop() if len(found) == 1 else None


def roster_player_ids(rosters: list[dict], roster_id: int) -> list[str]:
    """The player ids on one roster, or [] if that roster is not in the payload."""
    for r in rosters:
        if r.get("roster_id") == roster_id:
            return list(r.get("players") or [])
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Add the mutations**

```python
        ("roster_id assumed equal to draft_slot -- you manage someone else's team",
         "    found = {p.roster_id for p in picks\n"
         "             if p.draft_slot == draft_slot and p.roster_id is not None}\n"
         "    return found.pop() if len(found) == 1 else None",
         "    return draft_slot"),
        ("a contradictory draft picks the first roster_id instead of refusing",
         "return found.pop() if len(found) == 1 else None",
         "return found.pop() if found else None"),
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; both new mutations `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/data.py ffhelper/season.py tests/ scripts/mutate.py
git commit -m "feat: read league rosters and derive the user's roster_id from the draft"
```

---

### Task 6: The Yahoo roster file

**Files:**
- Modify: `ffhelper/cli.py` (beside `find_players`, ~line 41)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `cli.find_players`, `data.Player`.
- Produces: `cli.read_roster_file(path: Path, pool: dict[str, Player]) -> tuple[list[Player], list[str]]` — resolved players, and problem lines as human-readable strings.

Why here and not in `season.py`: reading a file is I/O, and `season.py` is pure. `find_players` already lives in `cli.py`, and a second name resolver is how Bijan and Brian Robinson get confused.

**Deviation from the spec, deliberate:** the spec says "`transcribe.py`'s EXISTING name resolver". `transcribe.resolve` narrows by position and team, which a transcribed draft board supplies and a bare list of names does not — and it lives in `scripts/`, which the package must not import. `cli.find_players` is the primitive `transcribe.resolve` is itself built on, so this uses the same normalisation (`norm_name`, accent folding, suffix stripping) without the narrowing that has no input here. **If a line is ambiguous, the fix is to write a fuller name in the file**, which the error message says.

- [ ] **Step 1: Write the failing test**

```python
def test_read_roster_file_resolves_names_and_reports_every_problem_line(tmp_path):
    """Yahoo has no API, so this file IS the roster. A silently dropped or
    wrongly-resolved line is a silently wrong lineup every week -- so ambiguous
    and unknown lines are REPORTED and excluded, never guessed at.

    Bijan and Brian Robinson are both ATL RBs. That is the real case."""
    pool = {
        "1": Player("1", "Bijan Robinson", "RB", "ATL"),
        "2": Player("2", "Brian Robinson", "RB", "ATL"),
        "3": Player("3", "Josh Allen", "QB", "BUF"),
    }
    path = tmp_path / "yahoo-main.txt"
    path.write_text("Josh Allen\n\n# a comment\nrobinson\nNobody At All\n")

    players, problems = cli.read_roster_file(path, pool)

    assert [p.sleeper_id for p in players] == ["3"]
    assert len(problems) == 2
    assert any("robinson" in m and "Bijan Robinson" in m and "Brian Robinson" in m
               for m in problems), problems
    assert any("Nobody At All" in m for m in problems), problems


def test_read_roster_file_is_empty_and_quiet_when_there_is_no_file(tmp_path):
    players, problems = cli.read_roster_file(tmp_path / "missing.txt", {})
    assert players == [] and problems == []


def test_roster_file_age_is_reported_so_a_stale_roster_is_visible(tmp_path):
    """A hand-maintained roster drifts the moment you make a waiver claim, and a
    stale one silently produces a wrong lineup every week -- the same failure
    class as draft-mode attribution drift. The file's mtime is the roster's age
    and it must be on screen, not inferred."""
    import os, time
    path = tmp_path / "yahoo-main.txt"
    path.write_text("Josh Allen\n")
    old = time.time() - 9 * 86400
    os.utime(path, (old, old))

    assert cli.roster_file_age_days(path) == 9
    assert cli.roster_file_age_days(tmp_path / "missing.txt") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k read_roster_file -q; git stash pop`
Expected: FAIL with `AttributeError: module 'ffhelper.cli' has no attribute 'read_roster_file'`

- [ ] **Step 3: Write minimal implementation**

```python
ROSTER_DIR = ROOT / ".roster"


def read_roster_file(path: Path, pool: dict[str, Player]) -> tuple[list[Player], list[str]]:
    """A hand-maintained roster for a league with no API. One name per line.

    Yahoo requires per-developer approval that has not arrived, so for that
    league this file IS the roster and nothing else can supply it. Blank lines
    and `#` comments are ignored.

    Ambiguous and unknown lines are REPORTED and EXCLUDED, never guessed --
    "robinson" is both Bijan and Brian, both ATL RBs, and picking one silently
    starts the wrong player every week. Anchored to ROOT, not cwd: the roster you
    read must not depend on which directory you launched from.
    """
    if not path.exists():
        return [], []
    players: list[Player] = []
    problems: list[str] = []
    for line in path.read_text().splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        matches = find_players(pool, name)
        if len(matches) == 1:
            players.append(matches[0])
        elif not matches:
            problems.append(f"no player matches {name!r}")
        else:
            shown = ", ".join(f"{p.name} ({p.position} {p.team})" for p in matches[:6])
            problems.append(f"{name!r} is ambiguous: {shown}")
    return players, problems


def cache_age_minutes(cache_key: str) -> int | None:
    """Whole minutes since `.cache/<cache_key>.json` was last written, or None.

    `fetch_json` serves a stale cached copy when a fetch fails (stale_ok=True by
    default), and says nothing. This is how the caller finds out. Same job as
    `roster_file_age_days` does for the hand-maintained file: an age on screen,
    so "healthy but wrong" is visible rather than inferred.
    """
    path = CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    return int((time.time() - path.stat().st_mtime) // 60)


def roster_file_age_days(path: Path) -> int | None:
    """Whole days since the roster file was last edited, or None if absent.

    A hand-maintained roster is stale the moment a waiver claim lands, and a
    stale roster produces a confidently wrong lineup. The age goes on screen so
    the user can see how much to trust it.
    """
    if not path.exists():
        return None
    return int((time.time() - path.stat().st_mtime) // 86400)
```

`time` is already imported in `cli.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -k "read_roster_file or roster_file_age" -q`
Expected: PASS

- [ ] **Step 5: Add the mutations**

Under the `"cli.py"` key (there must be exactly one such key — `mutate.py` refuses to run on a duplicate):

```python
        ("ambiguous roster line silently resolved to the first match",
         "        if len(matches) == 1:\n            players.append(matches[0])",
         "        if matches:\n            players.append(matches[0])"),
        ("unresolved roster lines dropped silently",
         'problems.append(f"no player matches {name!r}")', "pass"),
```

- [ ] **Step 6: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; both new mutations `killed`.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/cli.py tests/test_cli.py scripts/mutate.py
git commit -m "feat(cli): read a hand-maintained roster for leagues with no API"
```

---

### Task 7: The `lineup` command

**Files:**
- Modify: `ffhelper/cli.py` — new `_lineup` function and `main`'s argparse (~line 901)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: `cli.render_lineup(state: season.StartSit, week: int, league_name: str, owner: str | None, notes: list[str]) -> str` (pure, so it is testable without a network) and `cli._lineup(league, tunables, week: int | None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
def test_render_lineup_shows_slots_bench_close_calls_and_every_degradation():
    """One frame of the lineup screen. Pure, so it tests without a network.

    Everything degraded must be VISIBLE: an unfilled slot, a player with no
    projection this week, an injury, and the notes the caller passes in."""
    from ffhelper import season
    starter = Player("1", "Jaxon Smith-Njigba", "WR", "SEA", proj_pts=16.2)
    hurt = Player("2", "Chris Olave", "WR", "NO", proj_pts=11.0,
                  injury_status="Questionable", practice_participation="Limited")
    bench = Player("3", "Jordan Addison", "WR", "MIN", proj_pts=9.5)
    state = season.StartSit(
        lineup=[("WR", starter), ("WR", hurt), ("RB", None)],
        bench=[bench],
        close_calls=[season.CloseCall("WR", hurt, bench, 1.5)],
    )
    out = cli.render_lineup(state, week=3, league_name="sleeper-main",
                            owner="jaydenpg", notes=["projections unavailable for 2 players"])

    assert "week 3" in out and "sleeper-main" in out and "jaydenpg" in out
    assert "Jaxon Smith-Njigba" in out and "16.2" in out
    assert "Questionable" in out and "Limited" in out
    assert "EMPTY" in out                      # the unfilled RB slot
    assert "Jordan Addison" in out             # the bench
    assert "CLOSE" in out and "1.5" in out     # the close call
    assert "projections unavailable for 2 players" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k render_lineup -q; git stash pop`
Expected: FAIL with `AttributeError: module 'ffhelper.cli' has no attribute 'render_lineup'`

- [ ] **Step 3: Write minimal implementation**

```python
def _status_note(p: Player) -> str:
    """Injury and practice, where they exist. Absent means absent, not healthy."""
    bits = [b for b in (p.injury_status, p.practice_participation) if b]
    return f"  [{' / '.join(bits)}]" if bits else ""


def render_lineup(
    state: "season.StartSit", week: int, league_name: str,
    owner: str | None, notes: list[str],
) -> str:
    """One frame of the lineup screen. Pure -- no I/O, so it tests without a network."""
    who = f"  ({owner})" if owner else ""
    out = [f"{league_name}{who}   week {week}", ""]
    # Unprojected starters contribute their invented 0.0 to this total, so the
    # total is a floor when any starter has no projection. Said on screen below.
    total = sum(p.proj_pts for _, p in state.lineup if p is not None)
    out.append("STARTERS")
    unprojected_ids = {p.sleeper_id for p in state.unprojected}
    for slot, p in state.lineup:
        if p is None:
            out.append(f"  {slot:<5} -- EMPTY --   no eligible player on this roster")
        elif p.sleeper_id in unprojected_ids:
            # A starter can be unprojected when nothing else is eligible for the
            # slot. Print "--", never "0.0": the 0.0 is a sort value we invented,
            # and printing it as a projection is the fabrication this whole
            # design exists to prevent -- arriving in the one place the user is
            # most likely to trust it.
            out.append(f"  {slot:<5} {p.name:<24} {p.position:<3} {p.team or '':<3} "
                       f"{'   --':>6}  NO PROJECTION{_status_note(p)}")
        else:
            out.append(f"  {slot:<5} {p.name:<24} {p.position:<3} {p.team or '':<3} "
                       f"{p.proj_pts:6.1f}{_status_note(p)}")
    out.append(f"  {'':<5} {'projected total':<24} {'':<3} {'':<3} {total:6.1f}")

    projected_bench = [p for p in state.bench if p not in state.unprojected]
    if projected_bench:
        out += ["", "BENCH"]
        for p in projected_bench:
            out.append(f"  {'':<5} {p.name:<24} {p.position:<3} {p.team or '':<3} "
                       f"{p.proj_pts:6.1f}{_status_note(p)}")

    # NOT a "!!" note. A player can carry no projection for MONTHS -- a deliberate
    # last-round stash on the exempt list is the real case -- and an alert that
    # fires every week for the whole season is how a user learns to ignore alerts.
    # It is also the only honest rendering: the source gave no number, so we print
    # no number. "0.0" would be a projection we invented.
    if state.unprojected:
        out += ["", "NO PROJECTION THIS WEEK -- not started, and not a zero"]
        for p in state.unprojected:
            out.append(f"  {'':<5} {p.name:<24} {p.position:<3} {p.team or '':<3} "
                       f"{'   --':>6}{_status_note(p)}")

    if state.close_calls:
        out += ["", "CLOSE CALLS -- worth your own read"]
        for c in state.close_calls:
            out.append(f"  {c.slot:<5} starting {c.starter.name} over {c.challenger.name} "
                       f"by {c.gap:.1f}{_status_note(c.challenger)}")
    if notes:
        out += [""] + [f"!! {n}" for n in notes]
    return "\n".join(out)
```

And the command itself:

```python
def _lineup(league: League, tunables: Tunables, week: int | None = None) -> int:
    """Print this week's optimal lineup. One shot -- no loop, no polling."""
    settings = resolve_settings(league)
    players = load_players()
    state = load_nfl_state()
    week = week or int(state.get("week") or 1)
    season_str = str(state.get("season") or SEASON)

    weekly = season_mod.weekly_points(
        load_weekly_projections(season_str, week), settings.scoring)

    notes: list[str] = []
    owner: str | None = None
    if league.platform == "sleeper":
        rosters = load_league_rosters(league.league_id)
        # `fetch_json` defaults to stale_ok=True, so a FAILED fetch silently
        # serves whatever cached copy exists and the roster looks healthy while
        # being out of date. That is the shape of two defects this project has
        # already shipped -- the STALE banner that could never fire, and the
        # dead feed that rebuilt the board from no picks. The Yahoo file reports
        # its age; the Sleeper roster must too, and the cache file's mtime is
        # that age. A waiver claim you made this morning not showing up is the
        # symptom, and it must not be silent.
        age_min = cache_age_minutes(f"rosters_{league.league_id}")
        if age_min is not None and age_min > 30:
            notes.append(f"roster data is {age_min} minutes old -- a fetch may have "
                         f"failed and a cached copy was served; recent waiver moves "
                         f"may be missing")
        # feeds.Pick already carries roster_id AND draft_slot, so no re-fetch and
        # no reshaping: the draft is the only thing that knows which roster is
        # yours, and it is cached like everything else.
        picks = SleeperFeed(settings.draft_id).get_picks() if settings.draft_id else []
        rid = (season_mod.roster_id_for_slot(picks, league.draft_slot)
               if league.draft_slot else None)
        if rid is None:
            notes.append("could not derive your roster_id from the draft -- "
                         "set `roster_id` in config.toml for this league")
            roster = []
        else:
            ids = season_mod.roster_player_ids(rosters, rid)
            roster = [players[i] for i in ids if i in players]
            missing = [i for i in ids if i not in players]
            if missing:
                notes.append(f"{len(missing)} rostered players are not in the player pool: "
                             f"{', '.join(missing)}")
            users = {u["user_id"]: u.get("display_name") for u in load_league_users(league.league_id)}
            owner = next((users.get(r.get("owner_id")) for r in rosters
                          if r.get("roster_id") == rid), None)
    else:
        roster_path = ROSTER_DIR / f"{league.name}.txt"
        roster, problems = read_roster_file(roster_path, players)
        notes += problems
        age = roster_file_age_days(roster_path)
        if age is not None and age >= 3:
            notes.append(f"hand-entered roster is {age} days old -- check it against "
                         f"{league.platform} before trusting this lineup")
        if not roster:
            notes.append(f"no roster: write one name per line into "
                         f"{ROSTER_DIR / f'{league.name}.txt'}")

    # Players with no projection are NOT a "!!" note: see render_lineup. They get
    # their own quiet section, because a stash can carry no number for months.
    scored = season_mod.with_weekly_points(roster, weekly)
    state_ss = season_mod.start_sit(scored, settings.roster_slots,
                                    tunables.close_call_points,
                                    projected_ids=set(weekly))
    print(render_lineup(state_ss, week, league.name, owner, notes))
    return 0
```

- [ ] **Step 3b: Add the tunable**

In `ffhelper/config.py`, in `Tunables`:

```python
    # How close two players must be for a start/sit call to be worth printing.
    # A 30-point gap is not a decision and printing it buries the 1.5-point one
    # that is. 3.0 is a starting value, NOT a measured one -- it is expected to
    # move once backtest_weekly.py measures the real weekly projection error.
    close_call_points: float = 3.0
```

and in `load_config`, beside the other scalar fallbacks:

```python
        close_call_points=tun_raw.get("close_call_points", defaults.close_call_points),
```

Wire the command into `main`:

```python
    ap.add_argument("command", choices=["run", "preflight", "lineup"])
    ...
    ap.add_argument("--week", type=int, default=None,
                    help="NFL week; defaults to the current one from Sleeper")
    ...
    if args.command == "lineup":
        return _lineup(league, tunables, args.week)
```

Add `close_call_points: float = 3.0` to `Tunables` in `ffhelper/config.py`, and thread it through `load_config`'s scalar fallbacks the same way `tier_break_sigma` is.

Add imports at the top of `cli.py`: `from ffhelper import season as season_mod` and extend the `data` import with `load_league_rosters, load_league_users, load_nfl_state, load_weekly_projections`.

**Verified before writing this plan:** `feeds.Pick` already carries both `roster_id` and `draft_slot` (`feeds.py:20-30`), and `parse_sleeper_picks` populates both, so `_lineup` passes `get_picks()` straight through. Do not "simplify" this by assuming `roster_id == draft_slot` — measured on the real league, slot 5 is roster 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -k render_lineup -q`
Expected: PASS

- [ ] **Step 5: Run it against the real league**

Run: `.venv/bin/python -m ffhelper.cli lineup --league sleeper-main`

Expected: 15 players, the owner shown as `jaydenpg`, nine starters plus bench, and no `!!` notes other than genuinely missing projections. **This step is not optional** — nine of this project's defects were found by running it against real data past a fully green suite. If the owner name is wrong, stop: Task 5's derivation is broken and the roster is someone else's.

- [ ] **Step 6: Add the mutations**

```python
        ("empty lineup slots hidden, so a hole in the roster is invisible",
         '            out.append(f"  {slot:<5} -- EMPTY --   no eligible player on this roster")',
         "            pass"),
        ("degradation notes dropped from the screen",
         '        out += [""] + [f"!! {n}" for n in notes]', "        pass"),
```

- [ ] **Step 7: Run the suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; both new mutations `killed`.

- [ ] **Step 8: Commit**

```bash
git add ffhelper/ tests/ scripts/mutate.py
git commit -m "feat(cli): lineup command"
```

---

### Task 8: Extend `preflight`, and document the command

**Files:**
- Modify: `ffhelper/cli.py` — `_preflight` (~line 863)
- Modify: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1, 5.
- Produces: no new API; `_preflight` prints three more lines.

- [ ] **Step 1: Write the failing test**

```python
def test_preflight_reports_the_week_and_the_roster(monkeypatch, capsys):
    """preflight is the thing you run before trusting the output. Season mode
    adds three new ways to be silently wrong -- the wrong week, no roster, and
    someone else's roster -- so the week and the roster must both appear."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 3, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters",
                        lambda league_id: [{"roster_id": 1, "players": ["1"]},
                                           {"roster_id": 2, "players": ["2"]}])

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert result == 0
    assert "nfl week       : 3" in out
    assert "2 teams" in out
    assert "PREFLIGHT OK" in out
```

`_loop_players`, `_loop_settings`, `_loop_league` and `_FakeFeed` are the existing
helpers in `tests/test_cli.py` — use them, do not write new ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k preflight_reports_the_week -q; git stash pop`
Expected: FAIL — the strings are absent.

- [ ] **Step 3: Write minimal implementation**

In `_preflight`, after the existing `draft_slot` line:

```python
    state = load_nfl_state()
    print(f"nfl week       : {state.get('week')} ({state.get('season')} {state.get('season_type')})")
    if league.platform == "sleeper":
        rosters = load_league_rosters(league.league_id)
        print(f"rosters        : {len(rosters)} teams")
    else:
        path = ROSTER_DIR / f"{league.name}.txt"
        roster, problems = read_roster_file(path, players)
        age = roster_file_age_days(path)
        print(f"roster file    : {path} -- {len(roster)} players, "
              f"{len(problems)} unresolved, "
              f"{'missing' if age is None else f'{age}d old'}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -k preflight -q`
Expected: PASS

- [ ] **Step 5: Run it for real, both leagues**

Run:
```bash
.venv/bin/python -m ffhelper.cli preflight --league sleeper-main
.venv/bin/python -m ffhelper.cli preflight --league yahoo-main
```
Expected: `PREFLIGHT OK` for both. Yahoo will report 0 roster players until the file is written; that is correct and must be visible rather than silent.

- [ ] **Step 6: Update README**

Add `lineup` to the commands section, alongside `run` and `preflight`: what it prints, the `--week` flag, and the `.roster/<league>.txt` file for leagues with no API. **Generate the sample output by running the command**, never by hand — a hand-written sample once sat in this README showing a state the tool could not produce. Keep it short; README must not accumulate.

- [ ] **Step 7: Run the full suite and the mutation check**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python scripts/mutate.py`
Expected: all pass; only the documented equivalent mutant survives.

- [ ] **Step 8: Commit**

```bash
git add ffhelper/cli.py tests/test_cli.py README.md
git commit -m "feat(cli): preflight covers season mode; document lineup"
```

---

## Done when

- `.venv/bin/python -m ffhelper.cli lineup --league sleeper-main` prints a correct nine-slot lineup from the real roster, with the owner shown as `jaydenpg`.
- `--league yahoo-main` prints a lineup from `.roster/yahoo-main.txt`, or says clearly that the file is missing.
- Full suite green; `scripts/mutate.py` reports only the one documented equivalent mutant.
- `README.md` documents `lineup` with output generated by running it.

## Explicitly NOT in this slice

- **Matchup adjustment** — Phase 4b, and it needs `backtest_weekly.py` to validate it before it may reorder anything.
- **Waivers, the free-agent pool, trending, FAAB** — Phase 4c.
- **The snapshot table** — Phase 4b, alongside the backtest that gives it a purpose.
- **Props, `nflreadpy`** — cut from Phase 4 on measurement; see the spec.
