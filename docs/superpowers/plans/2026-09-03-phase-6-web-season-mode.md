# Phase 6 — Season Mode on the Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the three season commands into pages of the existing Dash app, launched from the terminal on localhost, behind a homepage that also routes to the draft board.

**Architecture:** Extract the fetch-and-compute half of `_lineup` / `_waivers` / `_trades` into `ffhelper/pipeline.py` returning frozen view dataclasses, so the CLI's text renderers and the new HTML renderers consume one computation. Add routes with `dash.register_page`, which `app.py` already uses. Nothing runs unattended; nothing writes to `season.db`.

**Tech Stack:** Python 3.12, `dash`, `requests`, stdlib (`sqlite3`, `xml.etree.ElementTree`, `tomllib`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-web-season-mode-design.md`

## Global Constraints

Copied from `CLAUDE.md` and the spec. Every task's requirements implicitly include this section.

- **Dependencies are `requests`, `yfpy`, `dash`. Nothing else.** No pandas, no scipy, no feedparser, no PyYAML.
- **`season.py` and `value.py` are pure.** No I/O, no network, no globals. Do not add fetching to either.
- **`store.py` is the only stateful module.** This phase reads from it and never writes.
- **No module-level league state.** Every function takes league context.
- **Never join load-bearing data on player name.** Integer/string IDs only.
- **Never blend projection rank with ADP rank into one number.**
- **Unmatched players are printed, never silently dropped.**
- **Degrade to "column absent", never to a fabricated number.** A sort value of `0.0` must never be written where a measured `0.0` would be read later.
- **Never introduce a hand-picked discount, multiplier, or weight.**
- **No test may reach the network or the real database.** Both are guarded autouse in `tests/conftest.py`. Loaders take an explicit `fetcher`.
- **A new test must be shown to fail before the fix**, via `git stash push -u -- ffhelper && pytest -k <name>`. The `-u` is not optional for a test covering a new file.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.**
- **Mark deliberate shortcuts with a `ponytail:` comment** naming the ceiling and the upgrade path.
- **Agents never touch `main`.** Work on `phase-6-web-season-mode`. Never `git push`, `merge`, or `rebase`.
- **`lineup_value()` / `optimal_lineup()` are shared primitives.** Never inline a second greedy assignment.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `ffhelper/pipeline.py` (create) | Fetch + compute for the three season commands; returns view dataclasses. Impure, no rendering, no DB write, no dash import. | 1–3 |
| `ffhelper/cli.py` (modify) | `_lineup`/`_waivers`/`_trades` shrink to build → render text → print. | 1–3 |
| `ffhelper/app.py` (modify) | Routes, homepage, season pages. | 4–9, 11 |
| `ffhelper/news.py` (create) | RSS headlines via stdlib XML. | 10 |
| `ffhelper/data.py` (modify) | `fetch_text` sibling to `fetch_json`. | 10 |
| `tests/test_pipeline.py` (create) | Builder tests, offline. | 1–3 |
| `tests/test_app.py` (modify) | Route, strip and renderer tests. | 4–9, 11 |
| `tests/test_news.py` (create) | RSS parser tests. | 10 |
| `scripts/mutate.py` (modify) | Mutations for the strip predicate and RSS parser. | 5, 10 |

---

### Task 1: `build_lineup` — extract the lineup pipeline

**Files:**
- Create: `ffhelper/pipeline.py`
- Create: `tests/test_pipeline.py`
- Modify: `ffhelper/cli.py:1535-1580` (`_lineup`)

**Interfaces:**
- Consumes: `cli.resolve_settings`, `cli._resolve_week`, `cli._resolve_my_roster`, `cli._practice_status`, `cli._matchup_context`, `data.load_players`, `data.load_weekly_projections`, `season.weekly_points`, `season.with_practice_status`, `season.with_weekly_points`, `season.start_sit`
- Produces: `pipeline.LineupView` with fields `state: season.StartSit`, `week: int`, `season_str: str`, `state_week: int | None`, `league_name: str`, `owner: str | None`, `notes: list[str]`, `matchups: dict`, `matchup_line: str`, `practice_line: str`, `projected_ids: set[str]`, `error: str | None`. Function `pipeline.build_lineup(league, tunables, week=None) -> LineupView`.

**Why `error` rather than an exception:** `_lineup` returns exit code 1 with a printed message when no week can be resolved. A web page needs the same message as text, not a traceback. `error` non-None means every other field is unusable and the caller renders only the message.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
import pytest
from ffhelper import pipeline
from ffhelper.config import League, Tunables


def test_build_lineup_reports_error_when_week_unresolvable(monkeypatch):
    """No week from /state/nfl and none passed: a message, not a traceback.

    Guessing a week is the fabrication the design forbids, so the builder must
    surface the same refusal the CLI prints.
    """
    monkeypatch.setattr(pipeline, "_resolve_week", lambda w: (None, "2026", [], None))
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    view = pipeline.build_lineup(league, Tunables(), week=None)
    assert view.error is not None
    assert "--week" in view.error
    assert view.state is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest tests/test_pipeline.py -v; git stash pop`
Expected: FAIL with `ModuleNotFoundError: No module named 'ffhelper.pipeline'`. The `-u` is required — without it the new module stays on disk and the run proves nothing.

- [ ] **Step 3: Create `ffhelper/pipeline.py` with `build_lineup`**

Move the body of `cli._lineup` verbatim, replacing each `print(...)` with a field. Import the helpers from `cli` (they already live there and moving them is a separate change).

```python
"""Fetch-and-compute for the season commands. The layer between loaders and renderers.

Impure by design: this is where the network lives, which is why `season.py` and
`value.py` can stay pure. Holds no league state, writes no database, imports no
dash -- the CLI's text renderers and the web app's HTML renderers both consume
what these builders return, so the two surfaces cannot disagree about what this
week's advice is. That is `CLAUDE.md`'s rule for `lineup_value()`/`optimal_lineup()`
applied one level up.
"""
from dataclasses import dataclass, field

from ffhelper import season as season_mod
from ffhelper.cli import (
    _matchup_context, _practice_status, _resolve_my_roster, _resolve_week,
    resolve_settings,
)
from ffhelper.config import League, Tunables
from ffhelper.data import load_players, load_weekly_projections

NO_WEEK = ("no NFL week available: /state/nfl is unreachable and --week "
           "was not given -- pass e.g. '--week 1' to run without it")


@dataclass(frozen=True)
class LineupView:
    """Everything both renderers need for one week's lineup.

    `error` non-None means nothing else on this object is usable: the caller
    renders the message and stops. It carries a string rather than raising
    because a web page needs the refusal as text, not a traceback.
    """
    league_name: str
    error: str | None = None
    state: "season_mod.StartSit | None" = None
    week: int | None = None
    season_str: str = ""
    state_week: int | None = None
    owner: str | None = None
    notes: list[str] = field(default_factory=list)
    matchups: dict = field(default_factory=dict)
    matchup_line: str = ""
    practice_line: str = ""
    projected_ids: set[str] = field(default_factory=set)


def build_lineup(league: League, tunables: Tunables,
                 week: int | None = None) -> LineupView:
    """This week's optimal lineup, fetched and computed. No printing, no DB write."""
    settings = resolve_settings(league)
    week, season_str, notes, state_week = _resolve_week(week)
    if week is None:
        return LineupView(league_name=league.name, error=NO_WEEK)

    players = load_players()
    weekly_rows = load_weekly_projections(season_str, week)
    weekly = season_mod.weekly_points(weekly_rows, settings.scoring)

    roster, owner, notes_r, _rosters, _rid = _resolve_my_roster(league, settings, players)
    notes = notes + notes_r

    practice, practice_line = _practice_status(season_str, week)
    roster = season_mod.with_practice_status(roster, practice)

    scored = season_mod.with_weekly_points(roster, weekly)
    state = season_mod.start_sit(scored, settings.roster_slots,
                                 tunables.close_call_points,
                                 projected_ids=set(weekly))
    matchups, matchup_line = _matchup_context(
        season_str, week, players, settings.scoring,
        season_mod.opponents(weekly_rows), roster)

    return LineupView(
        league_name=league.name, state=state, week=week, season_str=season_str,
        state_week=state_week, owner=owner, notes=notes, matchups=matchups,
        matchup_line=matchup_line, practice_line=practice_line,
        projected_ids=set(weekly),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Rewire `_lineup` to use the builder**

Replace the body of `cli._lineup` (keeping its signature and its snapshot write):

```python
def _lineup(league: League, tunables: Tunables, week: int | None = None) -> int:
    """Print this week's optimal lineup. One shot -- no loop, no polling."""
    from ffhelper.pipeline import build_lineup      # local: pipeline imports cli
    view = build_lineup(league, tunables, week)
    if view.error:
        print(view.error)
        return 1
    print(render_lineup(view.state, view.week, view.league_name, view.owner,
                        view.notes, view.matchups))
    print(view.matchup_line)
    print(view.practice_line)
    # After the lineup, not inside `notes`: notes render as "!!" alarms, and a
    # snapshot that worked is not an alarm.
    print(_record_snapshot(league, view.season_str, view.week, view.state_week,
                           view.state, view.projected_ids))
    return 0
```

The import is local because `pipeline` imports from `cli`. A module-level import would be circular.

- [ ] **Step 6: Run the whole suite — the existing lineup tests are the proof**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, with the pre-existing `test_cli.py` lineup tests unchanged. **If any of them needed editing, the extraction changed behaviour and is wrong.** Revert and redo rather than adjusting the test.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/pipeline.py ffhelper/cli.py tests/test_pipeline.py
git commit -m "refactor(pipeline): extract build_lineup from _lineup

The CLI now renders from a view object rather than computing inline, so the
web surface can consume the same computation. Existing lineup tests pass
unchanged, which is the evidence the extraction altered no behaviour."
```

---

### Task 2: `build_waivers` — extract the waiver pipeline

**Files:**
- Modify: `ffhelper/pipeline.py`
- Modify: `ffhelper/cli.py:1583-1667` (`_waivers`)
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `pipeline.NO_WEEK`, plus `season.last_scoring_week`, `season.week_weights`, `season.free_agent_pool`, `season.waiver_targets`, `season.waiver_position`, `data.load_trending`
- Produces: `pipeline.WaiverView` with fields `league_name: str`, `error: str | None`, `this_week: list[season.WaiverTarget]`, `ros: list[season.WaiverTarget]`, `week: int | None`, `last_week: int | None`, `owner: str | None`, `position: int | None`, `teams: int`, `trending: dict[str, int]`, `notes: list[str]`, `weeks_scored: int`. Function `pipeline.build_waivers(league, tunables, week=None, limit=10) -> WaiverView`.
- Also produces: `pipeline.platform_refusal(league, command, needs) -> str`, shared by tasks 2 and 3; and `pipeline._horizon(season_str, week, last_week, settings)` / `pipeline._horizon_note(failed, scored, week, last_week, label)`, which task 3 reuses.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pipeline.py
def test_build_waivers_refuses_non_sleeper_platform():
    """Yahoo serves no rosters, so the free-agent pool cannot be built.

    A pool derived from one hand-entered roster would be silently wrong, which
    is worse than absent -- so this is a refusal, not a degradation.
    """
    league = League(name="yahoo-main", platform="yahoo", league_id="9")
    view = pipeline.build_waivers(league, Tunables())
    assert view.error is not None
    assert "yahoo" in view.error
    assert "Sleeper-only" in view.error
    assert view.this_week == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py::test_build_waivers_refuses_non_sleeper_platform -v`
Expected: FAIL with `AttributeError: module 'ffhelper.pipeline' has no attribute 'build_waivers'`

- [ ] **Step 3: Add the shared refusal helper and `WaiverView`**

```python
def platform_refusal(league: League, command: str, needs: str) -> str:
    """The one wording for 'this command needs rosters this platform will not serve'.

    Shared by waivers and trades so the two cannot drift into two explanations
    of one limitation -- the same reason `_resolve_my_roster` was extracted.
    """
    return (f"{command} needs {needs}, and {league.platform} has no API access "
            f"-- so this command is Sleeper-only. `lineup` still works for "
            f"{league.name}.")


@dataclass(frozen=True)
class WaiverView:
    league_name: str
    error: str | None = None
    this_week: list = field(default_factory=list)
    ros: list = field(default_factory=list)
    week: int | None = None
    last_week: int | None = None
    owner: str | None = None
    position: int | None = None
    teams: int = 0
    trending: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    weeks_scored: int = 0
```

- [ ] **Step 4: Add `build_waivers`**

Move `cli._waivers`' body verbatim, replacing each early-`print`+`return 1` with a `WaiverView(error=...)` and the final `print` with the populated view. The horizon loop, the `failed` note, the unweighted `this_week` horizon and the `weights` call are copied unchanged — none of that logic changes here.

```python
def build_waivers(league: League, tunables: Tunables, week: int | None = None,
                  limit: int = 10) -> WaiverView:
    """Rank the free-agent pool. No printing, no DB write."""
    if league.platform != "sleeper":
        return WaiverView(league_name=league.name, error=platform_refusal(
            league, "waivers", "every team's roster to know who is free"))

    settings = resolve_settings(league)
    week, season_str, notes, _state_week = _resolve_week(week)
    if week is None:
        return WaiverView(league_name=league.name, error=NO_WEEK)

    last_week, cal_note = season_mod.last_scoring_week(settings)
    if cal_note is not None:
        notes.append(cal_note)

    players = load_players()
    roster, owner, notes_r, rosters, rid = _resolve_my_roster(league, settings, players)
    notes += notes_r
    if not roster:
        return WaiverView(league_name=league.name, notes=notes,
                          error="no roster resolved, so there is nothing to "
                                "upgrade -- " + "; ".join(notes))

    weekly_by_week, failed = _horizon(season_str, week, last_week, settings)
    if not weekly_by_week:
        return WaiverView(league_name=league.name, notes=notes,
                          error="no weekly projections could be fetched "
                                "-- nothing can be ranked")
    if failed:
        notes.append(_horizon_note(failed, weekly_by_week, week, last_week,
                                   "rest-of-season"))

    weights = season_mod.week_weights(settings, weekly_by_week, tunables.playoff_weight)
    projected = set().union(*(set(wk) for wk in weekly_by_week.values()))
    pool = season_mod.free_agent_pool(players, rosters, projected)

    # `this_week` is the week already in front of you, so it is scored
    # unweighted -- passing `weights` would raise its own significance floor on
    # exactly the playoff weeks where an immediate one-week call matters most.
    this_week_horizon = {week: weekly_by_week[week]} if week in weekly_by_week else {}
    this_week = season_mod.waiver_targets(
        roster, pool, settings.roster_slots, this_week_horizon,
        tunables.close_call_points, limit) if this_week_horizon else []
    ros = season_mod.waiver_targets(
        roster, pool, settings.roster_slots, weekly_by_week,
        tunables.close_call_points, limit, weights=weights)

    try:
        trending = data_mod.load_trending("add")
    except Exception as exc:                  # noqa: BLE001 - degrade, never fabricate
        trending = {}
        notes.append(f"could not reach Sleeper's trending endpoint ({exc}) -- "
                     f"the trending column is absent")

    position, teams = season_mod.waiver_position(rosters, rid) if rid else (None, 0)
    return WaiverView(
        league_name=league.name, this_week=this_week, ros=ros, week=week,
        last_week=last_week, owner=owner, position=position, teams=teams,
        trending=trending, notes=notes, weeks_scored=len(weekly_by_week),
    )
```

Add the two helpers the horizon loop becomes — `_waivers` and `_trades` build it identically today, and copying it a third time is how two views start disagreeing:

```python
def _horizon(season_str: str, week: int, last_week: int,
             settings) -> tuple[dict[int, dict[str, float]], list[int]]:
    """Weekly league-scored points for every week from `week` to `last_week`.

    Returns the weeks that could be scored and the weeks that could not. A
    shorter horizon is a smaller total, and a total that shrank for an
    unexplained reason is exactly the silent wrongness this project keeps
    finding -- so the failures are returned, never swallowed.
    """
    scored: dict[int, dict[str, float]] = {}
    failed: list[int] = []
    for w in range(week, last_week + 1):
        try:
            rows = load_weekly_projections(season_str, w)
        except Exception:                     # noqa: BLE001 - degrade, never fabricate
            failed.append(w)
            continue
        scored[w] = season_mod.weekly_points(rows, settings.scoring)
    return scored, failed


def _horizon_note(failed: list[int], scored: dict, week: int, last_week: int,
                  label: str) -> str:
    return (f"{len(failed)} week(s) of projections could not be scored "
            f"({', '.join(str(w) for w in failed)}) -- the {label} total covers "
            f"{len(scored)} weeks, not {last_week - week + 1}")
```

Add `from ffhelper import data as data_mod` to the imports.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 6: Rewire `_waivers`**

```python
def _waivers(league: League, tunables: Tunables, week: int | None = None,
             limit: int = 10) -> int:
    """Rank the free-agent pool. One shot -- no loop, no polling."""
    from ffhelper.pipeline import build_waivers
    view = build_waivers(league, tunables, week, limit)
    if view.error:
        print(view.error)
        return 1
    print(render_waivers(view.this_week, view.ros, view.week, view.last_week,
                         view.league_name, view.owner, view.position, view.teams,
                         view.trending, view.notes, view.weeks_scored))
    return 0
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS with `test_cli.py`'s waiver tests unchanged. Any edit needed there means the extraction changed behaviour.

- [ ] **Step 8: Commit**

```bash
git add ffhelper/pipeline.py ffhelper/cli.py tests/test_pipeline.py
git commit -m "refactor(pipeline): extract build_waivers, share the horizon loop

_waivers and _trades built the weekly horizon identically; it is now one
helper, so a third copy cannot drift. Existing waiver tests pass unchanged."
```

---

### Task 3: `build_trades` — extract the trade pipeline

**Files:**
- Modify: `ffhelper/pipeline.py`
- Modify: `ffhelper/cli.py:1669-1805` (`_trades`)
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `pipeline.NO_WEEK`, `pipeline.platform_refusal`, `pipeline._horizon`, `pipeline._horizon_note`, plus `season.effective_weeks`, `trade.trade_options`, `cli.find_players`, `data.load_league_users`
- Produces: `pipeline.TradeView` with fields `league_name: str`, `error: str | None`, `best: list[trade.Proposal]`, `week: int | None`, `owner: str | None`, `names: dict[int, str]`, `notes: list[str]`, `weeks_scored: int`, `pinned: Player | None`, `deadline_passed: bool`. Function `pipeline.build_trades(league, tunables, week=None, player=None, limit=20, progress=None) -> TradeView`.

**`progress`:** an optional `Callable[[str], None]`. `_trades` prints `"  scanning {name}..."` to stderr during a ~330s sweep. The CLI passes a stderr writer; the web passes `None`. Without this the builder either prints from a web request or loses the CLI's only sign of life during a five-minute wait.

**`deadline_passed`:** the CLI returns exit code **0** for a passed deadline (a legal state, not an error) but exit code 1 for the other refusals. Collapsing them into `error` alone would change the exit code, so the flag is carried separately.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_pipeline.py
def test_build_trades_past_deadline_is_not_an_error(monkeypatch):
    """A passed deadline is a legal state: exit 0, not 1.

    Printing proposals you are not allowed to make is worse than printing none,
    but it is not a failure -- and the CLI's exit code must stay 0.
    """
    class S:
        trade_deadline = 5
        roster_slots = {"QB": 1}
        scoring = {}
    monkeypatch.setattr(pipeline, "resolve_settings", lambda lg: S())
    monkeypatch.setattr(pipeline, "_resolve_week", lambda w: (9, "2026", [], 9))
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    view = pipeline.build_trades(league, Tunables(), week=9)
    assert view.deadline_passed is True
    assert view.error is not None
    assert "week 5" in view.error
    assert view.best == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py::test_build_trades_past_deadline_is_not_an_error -v`
Expected: FAIL with `AttributeError: module 'ffhelper.pipeline' has no attribute 'build_trades'`

- [ ] **Step 3: Add `TradeView` and `build_trades`**

```python
@dataclass(frozen=True)
class TradeView:
    league_name: str
    error: str | None = None
    deadline_passed: bool = False
    best: list = field(default_factory=list)
    week: int | None = None
    owner: str | None = None
    names: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    weeks_scored: int = 0
    pinned: "Player | None" = None


def build_trades(league: League, tunables: Tunables, week: int | None = None,
                 player: str | None = None, limit: int = 20,
                 progress: "Callable[[str], None] | None" = None) -> TradeView:
    """Search every opponent for a mutually-beneficial trade. No printing.

    `progress` exists because the full sweep is ~330s and the CLI's only sign
    of life is a per-opponent line. The web passes None: a page cannot consume
    a stream, and printing from a request handler is the wrong place for it.
    """
    if league.platform != "sleeper":
        return TradeView(league_name=league.name, error=platform_refusal(
            league, "trades", "every team's roster to know what they hold"))

    settings = resolve_settings(league)
    week, season_str, notes, _state_week = _resolve_week(week)
    if week is None:
        return TradeView(league_name=league.name, error=NO_WEEK)

    deadline = settings.trade_deadline
    if deadline is not None and week > deadline:
        return TradeView(
            league_name=league.name, week=week, deadline_passed=True,
            error=(f"the trade deadline for {league.name} passed in week "
                   f"{deadline} -- no proposal can be made now"))
    if deadline is None:
        notes.append("trade_deadline is unknown for this league -- proceeding "
                     "without one")
    ...
```

Then copy the rest of `cli._trades` verbatim from the `last_scoring_week` call onward, substituting: `_horizon(...)` for the inline loop, `_horizon_note(..., "horizon")` for the inline note, `progress(f"  scanning {names[opp_rid]}...")` guarded by `if progress:` for the `print(..., file=sys.stderr)`, and a returned `TradeView` for the final `print`. The `pin` resolution, the ambiguity refusal, the `floor` computation, the per-opponent loop, the missing-player note and both sort branches are unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Rewire `_trades`**

```python
def _trades(league: League, tunables: Tunables, week: int | None = None,
            player: str | None = None, limit: int = 20) -> int:
    """Search every opponent for a mutually-beneficial trade. One shot."""
    from ffhelper.pipeline import build_trades
    view = build_trades(league, tunables, week, player, limit,
                        progress=lambda line: print(line, file=sys.stderr))
    if view.error:
        print(view.error)
        return 0 if view.deadline_passed else 1
    print(render_trades(view.best, view.week, view.league_name, view.owner,
                        view.names, view.notes, view.weeks_scored, view.pinned))
    return 0
```

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS with `test_cli.py`'s trade tests unchanged.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/pipeline.py ffhelper/cli.py tests/test_pipeline.py
git commit -m "refactor(pipeline): extract build_trades

`progress` is a callback rather than a print so the ~330s sweep keeps its
only sign of life in the CLI without printing from a web request.
`deadline_passed` is carried separately because a passed deadline exits 0."
```

---

### Task 4: Routes and the league query string

**Files:**
- Modify: `ffhelper/app.py:348-356` (`build_app`), `ffhelper/app.py:1808` area (`main`)
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `dash.register_page`, existing `_layout(league_names, default_league, poll_ms)`
- Produces: `app.league_from_search(search: str, names: list[str], default: str) -> str`, `app.nav(active: str, league: str) -> html.Div`, and registered routes `/`, `/draft`, `/lineup`, `/waivers`, `/trades`.

**Note:** `app.py` already calls `dash.Dash(__name__, use_pages=True, pages_folder="")` and `dash.register_page(...)`. Adding a route is one more `register_page`. Do **not** build a `dcc.Location` router.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
import pytest
from ffhelper.app import league_from_search


@pytest.mark.parametrize("search,expected", [
    ("?league=yahoo-main", "yahoo-main"),
    ("?league=sleeper-main&x=1", "sleeper-main"),
    ("", "sleeper-main"),
    ("?league=", "sleeper-main"),
    ("?league=not-a-league", "sleeper-main"),
])
def test_league_from_search(search, expected):
    """An unknown or absent league falls back to the default, never raises.

    The query string is user-editable, so a typo must not 500 the page. It
    falls back rather than guessing at a near-match: a silently wrong league
    would advise on someone else's team.
    """
    names = ["sleeper-main", "yahoo-main"]
    assert league_from_search(search, names, "sleeper-main") == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_league_from_search -v`
Expected: FAIL with `ImportError: cannot import name 'league_from_search'`

- [ ] **Step 3: Implement `league_from_search` and `nav`**

```python
from urllib.parse import parse_qs

ROUTES = [("/", "home"), ("/draft", "draft"), ("/lineup", "lineup"),
          ("/waivers", "waivers"), ("/trades", "trades")]


def league_from_search(search: str, names: list[str], default: str) -> str:
    """The league named in `?league=`, or the default.

    Falls back rather than raising: the query string is user-editable and a
    typo must not 500 the page. Falls back rather than fuzzy-matching, too --
    silently advising on the wrong league is the failure this refuses.
    """
    got = parse_qs((search or "").lstrip("?")).get("league", [""])[0]
    return got if got in names else default


def nav(active: str, league: str) -> html.Div:
    """The same five links on every page, with the league carried across."""
    return html.Div([
        dcc.Link(label.upper(), href=f"{path}?league={league}",
                 style={"marginRight": "18px",
                        "fontWeight": "700" if label == active else "400"})
        for path, label in ROUTES
    ], style={"padding": "12px 0"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_league_from_search -v`
Expected: PASS

- [ ] **Step 5: Register the routes**

In `build_app`, keep the board on `/draft` and add the four others. Each season page's layout is a function of `search`, which Dash supplies to a layout callable:

```python
def build_app(league_names: list[str], default_league: str,
              poll_ms: int = 5000) -> dash.Dash:
    app = dash.Dash(__name__, use_pages=True, pages_folder="")
    dash.register_page(
        "draft", path="/draft",
        layout=_layout(league_names, default_league, poll_ms))
    dash.register_page("home", path="/", layout=lambda **kw: home_layout(
        league_from_search(kw.get("league", ""), league_names, default_league),
        league_names))
    for path, name in [("/lineup", "lineup"), ("/waivers", "waivers"),
                       ("/trades", "trades")]:
        dash.register_page(name, path=path, layout=_season_layout_for(name))
    app.layout = html.Div([dash.page_container])
    return app
```

`home_layout` and `_season_layout_for` are stubs returning `html.Div(nav(name, league))` for now; tasks 5–9 fill them.

- [ ] **Step 5b: Add the draft page's local-only notice**

The spec requires `/draft` to say **on the page** that it is local-only and
single-process. `app.py`'s `main()` already prints this to the terminal, where
nobody browsing will see it. Add it to the draft layout:

```python
DRAFT_NOTICE = ("LOCAL ONLY -- one process at a time. Do NOT run "
                "`ffhelper.cli run` for this league while this page is open: "
                "the CLI replays the journal once at ITS startup, so it would "
                "quietly show a stale board.")
```

Render it as a bordered banner above the board. The journal file IS the
database, and the CLI-takeover fallback works only because both processes read
the same local disk -- which is also why hosting the draft board is out of
scope.

- [ ] **Step 6: Verify the app starts and every route responds**

Run: `.venv/bin/python -m ffhelper.app --league sleeper-main` in one terminal, then in another:
```bash
for p in / /draft /lineup /waivers /trades; do
  printf "%s -> " "$p"; curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8050$p"
done
```
Expected: `200` for all five. Stop the server afterwards.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): five routes, league carried in the query string

Reuses the register_page pattern already in build_app -- the spec's
hand-rolled dcc.Location router was written against a problem this codebase
had already solved with pages_folder=''."
```

---

### Task 5: Homepage status strip

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `store.connect`, `store.DB_PATH`, `data.load_nfl_state`
- Produces: `app.snapshot_recorded(conn, league, season, week) -> bool | None`, `app.roster_file_age(path) -> str | None`, `app.status_strip(league, names) -> html.Div`

**The rule this task exists to honour:** `snapshot_recorded` returns `None` — not `False` — when the database cannot be read. `False` means "checked, no rows"; `None` means "could not check". The caller omits the line entirely on `None`. Reporting "not recorded" for an unreadable database is a fabricated value where a measured one is expected, which non-negotiable #7 bars.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
import sqlite3
from ffhelper.app import snapshot_recorded
from ffhelper import store


def test_snapshot_recorded_true_when_rows_exist():
    conn = store.connect(":memory:")
    conn.execute(
        "INSERT INTO snapshot (league, season, week, player_id, taken_at, started)"
        " VALUES ('sleeper-main','2026',3,'4046','2026-09-20T11:00:00',1)")
    conn.commit()
    assert snapshot_recorded(conn, "sleeper-main", "2026", 3) is True


def test_snapshot_recorded_false_when_week_empty():
    conn = store.connect(":memory:")
    assert snapshot_recorded(conn, "sleeper-main", "2026", 3) is False


def test_snapshot_recorded_none_when_unreadable():
    """None, not False. 'Could not check' is a different fact from 'no rows'.

    The strip omits the line on None. Reporting 'not recorded' for a database
    it cannot read is a fabricated value where a measured one is expected --
    non-negotiable #7. This is the case a suite skips because nothing happens.
    """
    class Broken:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("no such table: snapshot")
    assert snapshot_recorded(Broken(), "sleeper-main", "2026", 3) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_app.py -k snapshot_recorded -v`
Expected: FAIL with `ImportError: cannot import name 'snapshot_recorded'`

- [ ] **Step 3: Implement**

```python
def snapshot_recorded(conn, league: str, season: str, week: int) -> bool | None:
    """Whether this week is in the snapshot table. None means 'could not check'.

    Three-valued on purpose. False is a measurement -- the table was read and
    the week is not in it, so a snapshot is due. None is the absence of a
    measurement, and the caller must omit the line rather than print False's
    wording. Non-negotiable #7: degrade to absent, never to a fabricated value.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM snapshot WHERE league=? AND season=? AND week=? LIMIT 1",
            (league, season, week)).fetchone()
    except Exception:                        # noqa: BLE001 - absent, not fabricated
        return None
    return row is not None


def roster_file_age(path) -> str | None:
    """How old the hand-entered Yahoo roster is, or None if there is no file.

    TODO item 3: there is no Yahoo API, so this file is the roster and it goes
    stale silently after every add/drop. `lineup` and `preflight` both print
    its age for exactly this reason; the homepage is the third place a human
    will actually look.
    """
    try:
        days = (time.time() - Path(path).stat().st_mtime) / 86400
    except OSError:
        return None
    return f"{days:.0f}d old"
```

`status_strip` assembles: the current NFL week from `load_nfl_state` (degrading to "week unavailable" on failure), the snapshot line **only when `snapshot_recorded` is not None**, and the roster age line **only for a Yahoo league and only when the file exists**.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -k "snapshot_recorded or roster_file_age" -v`
Expected: PASS

- [ ] **Step 5: Add the mutation**

In `scripts/mutate.py`, add to the `app.py` entry:

```python
{"label": "snapshot_recorded returns False instead of None when unreadable",
 "target": "        return None\n    return row is not None",
 "replacement": "        return False\n    return row is not None"},
```

- [ ] **Step 6: Run the mutation — green suite first, foreground, alone**

```bash
git status --porcelain > /tmp/pre.txt
.venv/bin/python -m pytest tests/ -q          # must be green BEFORE mutating
.venv/bin/python scripts/mutate.py
git status --porcelain > /tmp/post.txt && diff /tmp/pre.txt /tmp/post.txt
```
Expected: the new mutation is KILLED, and the `git status` diff is empty. A survivor is evidence about the test — fix the test, never weaken the mutation. Do not run a subagent concurrently; two concurrent runs corrupted results before.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/app.py tests/test_app.py scripts/mutate.py
git commit -m "feat(app): homepage status strip, three-valued snapshot check

None means 'could not read the database' and omits the line; False means
'read it, week is missing' and prompts a run. Collapsing them would print a
fabricated value where a measured one is expected."
```

---

### Task 6: Season pages as text — the app becomes usable

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `pipeline.build_lineup`, `pipeline.build_waivers`, `pipeline.build_trades`, `cli.render_lineup`, `cli.render_waivers`, `cli.render_trades`
- Produces: `app.season_page_children(name, view) -> html.Div | html.Pre`

This is the milestone: at the end of this task the site works end to end from a phone on the same machine. Pages render the CLI's exact text inside `html.Pre`. Tasks 7–9 replace that with tables one page at a time.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
from ffhelper.app import season_page_children
from ffhelper import pipeline


def test_season_page_renders_error_without_calling_renderer():
    """A view carrying an error renders the message, not an empty table.

    The refusal text IS the deliverable for a Yahoo waiver page -- an empty
    table would read as 'nothing available', which is a different claim.
    """
    view = pipeline.WaiverView(league_name="yahoo-main",
                               error="waivers needs every team's roster")
    children = season_page_children("waivers", view)
    rendered = str(children)
    assert "waivers needs every team's roster" in rendered
    assert "Table" not in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_season_page_renders_error_without_calling_renderer -v`
Expected: FAIL with `ImportError: cannot import name 'season_page_children'`

- [ ] **Step 3: Implement**

```python
_MONO = {"fontFamily": "ui-monospace, SFMono-Regular, Menlo, monospace",
         "fontSize": "13px", "whiteSpace": "pre", "overflowX": "auto",
         "margin": "0"}


def season_page_children(name: str, view):
    """One season view as page content. Text for now; tables in tasks 7-9.

    ponytail: html.Pre of the CLI's own renderer. Ceiling is that 80-column
    output needs horizontal scrolling on a phone, which is the whole reason
    tasks 7-9 exist. Upgrade path is to replace this function per page; the
    text renderers stay as the CLI's output either way.
    """
    if view.error:
        return html.Div(view.error, style={"padding": "16px", "maxWidth": "60ch"})
    if name == "lineup":
        text = render_lineup(view.state, view.week, view.league_name,
                             view.owner, view.notes, view.matchups)
        text += f"\n{view.matchup_line}\n{view.practice_line}"
    elif name == "waivers":
        text = render_waivers(view.this_week, view.ros, view.week, view.last_week,
                              view.league_name, view.owner, view.position,
                              view.teams, view.trending, view.notes,
                              view.weeks_scored)
    else:
        text = render_trades(view.best, view.week, view.league_name, view.owner,
                             view.names, view.notes, view.weeks_scored, view.pinned)
    return html.Pre(text, style=_MONO)
```

`/lineup` and `/waivers` build their view in the page layout. **`/trades` does not** — see task 9. For this task `/trades` shows a button that is wired in task 9; until then it renders the caveat text only.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Verify against real data**

Run `.venv/bin/python -m ffhelper.app --league sleeper-main`, open `http://127.0.0.1:8050/lineup?league=sleeper-main`, and confirm the page matches `.venv/bin/python -m ffhelper.cli lineup --league sleeper-main` line for line. **A green suite is not evidence here** — every significant defect this project found late was found by a human running the code against real data.

- [ ] **Step 6: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): season pages render the CLI's text

Milestone: the site works end to end. html.Pre of the existing renderers, so
one computation and one wording feed both surfaces. Tables follow per page."
```

---

### Task 7: `/lineup` as HTML

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `pipeline.LineupView`, `season.StartSit`
- Produces: `app.lineup_rows(view) -> list[dict]` and `app.simple_table(headers, rows) -> html.Table`

**The rule this task must not break:** an unprojected starter renders `--`, never `0.0`. `render_lineup` carries a long comment explaining that the `0.0` is an invented sort value and printing it as a projection is the fabrication the whole design exists to prevent. The HTML renderer must reproduce that, and the test below is what holds it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
from ffhelper.app import lineup_rows
from ffhelper.season import StartSit


def test_lineup_rows_show_dash_for_unprojected_starter():
    """An unprojected starter renders '--', never '0.0'.

    The 0.0 is a sort value this code invented. Printing it as a projection is
    the fabrication non-negotiable #7 bars, arriving in the one place a user is
    most likely to trust it.
    """
    p = Player(sleeper_id="99", name="Stash Guy", position="TE", team="CHI",
               proj_pts=0.0)
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3,
        state=StartSit(lineup=[("TE", p)], bench=[], close_calls=[],
                       unprojected=[p]))
    rows = lineup_rows(view)
    assert rows[0]["proj"] == "--"
    assert "0.0" not in str(rows[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_lineup_rows_show_dash_for_unprojected_starter -v`
Expected: FAIL with `ImportError: cannot import name 'lineup_rows'`

- [ ] **Step 3: Implement `lineup_rows` and `simple_table`**

`lineup_rows` returns one dict per row with keys `slot`, `player`, `pos`, `team`, `proj`, `flags`, mirroring `render_lineup`'s branches exactly: `EMPTY` for a `None` player, `--` for an id in `view.state.unprojected`, otherwise `f"{p.proj_pts:.1f}"`. The projected total carries the same `(floor -- N starters unprojected)` caveat when any starter is unprojected.

`simple_table(headers, rows)` builds `html.Table` from plain dicts — no `DataTable`. Wrap it in `html.Div(..., style={"overflowX": "auto"})` so a wide table scrolls inside its own container rather than the page body.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Verify against real data on a narrow viewport**

Load `/lineup?league=sleeper-main`, narrow the window to ~390px, and confirm the table scrolls inside its container and the page body does not scroll sideways. Compare every number against the CLI's output.

- [ ] **Step 6: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): /lineup as an HTML table

html.Table, not DataTable -- read-only rows, no cell interaction, and it
proves the pattern before the board depends on it in 3.7. Unprojected
starters render '--'; the test is what holds that."
```

---

### Task 8: `/waivers` as HTML

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `pipeline.WaiverView`, `app.simple_table`
- Produces: `app.waiver_rows(view, section) -> list[dict]` where `section` is `"this_week"` or `"ros"`

**Two things that must survive the port:** the empty board is a result, not a blank — `render_waivers` prints *"nothing on the wire beats what you already have"* plus the floor caveat, and that wording is the deliverable. And the trending count must stay labelled `NATIONALLY -- NOT your league`; `load_trending`'s docstring is emphatic that these counts say nothing about your leaguemates.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
from ffhelper.app import waivers_children


def test_waivers_empty_board_states_the_result():
    """An empty board is a result, not a blank. Never lower a bar to fill it."""
    view = pipeline.WaiverView(league_name="sleeper-main", week=3, last_week=17,
                               this_week=[], ros=[], weeks_scored=15)
    rendered = str(waivers_children(view))
    assert "nothing on the wire beats what you already have" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_waivers_empty_board_states_the_result -v`
Expected: FAIL with `ImportError: cannot import name 'waivers_children'`

- [ ] **Step 3: Implement**

Two `simple_table` sections — `THIS WEEK` and `REST OF SEASON` — with columns `pos`, `player`, `gain`, `drop`, `starts`, `trending`. Omit a section with no targets. When both are empty, render the two-line result text instead of an empty table. Append `DROP_CAVEAT` whenever any target is shown.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Verify both leagues**

Load `/waivers?league=sleeper-main` and `/waivers?league=yahoo-main`. The Yahoo page must show the refusal text, not an empty table.

- [ ] **Step 6: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): /waivers as HTML tables

Empty board keeps its wording -- it is a result, not a blank. Trending stays
labelled national, per load_trending's docstring."
```

---

### Task 9: `/trades` — button-triggered, because the sweep is ~330s

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `pipeline.build_trades`, `app.simple_table`
- Produces: `app.trades_children(view) -> html.Div`, plus a `dcc.Loading`-wrapped callback on `Input("trades-run", "n_clicks")`

**Why a button:** `_trades` carries a measured `ponytail:` note of ~330 seconds for the full sweep — eleven opponents times three shapes — and records that pruning was rejected after measuring it drop 22 of 49 real trades. Five and a half minutes is fine for a command a human runs; as a page render the browser gives up, and navigating to `/trades` by accident costs the full sweep. **Nothing in this phase makes it faster.** The page states the expected wait before you commit to it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
from ffhelper.app import trades_landing


def test_trades_landing_warns_before_running():
    """The page must not start a five-minute sweep on navigation."""
    rendered = str(trades_landing("sleeper-main"))
    assert "minutes" in rendered
    assert "trades-run" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py::test_trades_landing_warns_before_running -v`
Expected: FAIL with `ImportError: cannot import name 'trades_landing'`

- [ ] **Step 3: Implement the landing state and the callback**

`trades_landing` renders `TRADE_CAVEAT`, a line naming the expected wait ("the full sweep takes about five minutes -- eleven opponents, three shapes each"), and `html.Button("RUN THE SEARCH", id="trades-run")`. The callback fires on `n_clicks`, calls `build_trades(..., progress=None)`, and returns `trades_children(view)`, all wrapped in `dcc.Loading`. Guard `n_clicks` being `None` on first render and return the landing state unchanged.

`trades_children` renders one block per proposal: opponent, `you +X / them +Y`, shape, give, get, and the `they must also drop ...` line when `their_drop` is set. That line is part of the offer, not a footnote — the counterparty notices the cut before the gain.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Verify the wait is survivable**

Load `/trades?league=sleeper-main`, confirm nothing runs on navigation, click the button, and time it. If the browser drops the connection before it returns, **stop and report** — the fallback is to keep `/trades` as a link to the CLI command rather than to invent a pruning heuristic that was already measured to lose trades.

- [ ] **Step 6: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): /trades runs on a button, not on page load

The sweep is a measured ~330s. Fine for a command a human runs; fatal as a
page render, and an accidental navigation should not cost five minutes."
```

---

### Task 10: `news.py` — RSS headlines

**Files:**
- Create: `ffhelper/news.py`
- Create: `tests/test_news.py`
- Modify: `ffhelper/data.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `data.fetch_text(url, key, ttl_seconds, cache_dir, fetcher) -> str` (new, sibling to `fetch_json`)
- Produces: `news.Headline(title: str, url: str, source: str, published: str | None)` and `news.parse_rss(xml_text: str, source: str) -> list[Headline]`, `news.load_headlines(feeds, fetcher=None) -> tuple[list[Headline], list[str]]` returning headlines and per-feed failure notes.

**Verify the feed URLs by fetching them before hardcoding any.** The spec records ESPN NFL, ProFootballTalk and the Bears' official site as candidates and explicitly marks the URLs unverified.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news.py
from ffhelper.news import parse_rss

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `git stash push -u -- ffhelper && .venv/bin/python -m pytest tests/test_news.py -v; git stash pop`
Expected: FAIL with `ModuleNotFoundError: No module named 'ffhelper.news'`

- [ ] **Step 3: Add `fetch_text` to `data.py`**

Mirror `fetch_json` exactly — same cache path, same TTL handling, same stale-cache fallback — but return the body as text instead of parsing JSON. Do not duplicate the caching logic; factor the shared part if that is cleaner than a flag.

- [ ] **Step 4: Implement `news.py`**

```python
"""NFL headlines from RSS. Decorative: nothing here feeds a number.

Parsed with stdlib xml.etree -- a feed reader is not worth a dependency for
three sources and one element shape. An unreachable or malformed feed yields
no headlines and a note; it never raises into the page, and it never renders
as a silently empty box.

NOT an input to any advice. `start_sit` sees projections, practice status and
injury designation, and nothing else. The panel sits apart from the advisory
sections on purpose, so its presence cannot imply the advice read it.
"""
```

`parse_rss` walks `.//item`, skips any item without both a `title` and a `link`, and returns `Headline`s. `load_headlines` calls `fetch_text` per feed with a one-hour TTL, catches per-feed failures into notes, and returns both.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_news.py -v`
Expected: PASS

- [ ] **Step 6: Verify the real feeds resolve**

```bash
.venv/bin/python -c "
from ffhelper.news import load_headlines, FEEDS
hs, notes = load_headlines(FEEDS)
print(len(hs), 'headlines;', len(notes), 'failures')
for n in notes: print(' !!', n)
for h in hs[:3]: print(' -', h.source, h.title[:60])
"
```
Expected: headlines from each feed. **Any feed in `notes` must be replaced or removed, not left in.** A permanently failing feed is a note printed forever.

- [ ] **Step 7: Add the mutation and run it**

Add to `scripts/mutate.py`: flip `parse_rss`'s link guard so items without a link are kept. Then, on a green suite, foreground, alone:

```bash
git status --porcelain > /tmp/pre.txt
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/mutate.py
git status --porcelain > /tmp/post.txt && diff /tmp/pre.txt /tmp/post.txt
```
Expected: KILLED, empty diff.

- [ ] **Step 8: Commit**

```bash
git add ffhelper/news.py ffhelper/data.py tests/test_news.py scripts/mutate.py
git commit -m "feat(news): RSS headlines via stdlib xml.etree

No dependency for three feeds and one element shape. A broken feed yields a
note, never a crash and never a silently empty box."
```

---

### Task 11: Headlines and trending panels on the homepage

**Files:**
- Modify: `ffhelper/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `news.load_headlines`, `data.load_trending`, `data.load_players`
- Produces: `app.headlines_panel(headlines, notes) -> html.Div`, `app.trending_panel(counts, players) -> html.Div`

**Two constraints from the spec:** an unreachable feed renders "feed unavailable", never an empty box. And the trending panel must repeat on screen that the counts are national and say nothing about this league — `load_trending`'s docstring requires it, and a count sitting unlabelled beside waiver advice reads as a prediction that a claim will win.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_app.py
from ffhelper.app import headlines_panel, trending_panel


def test_headlines_panel_says_unavailable_rather_than_showing_nothing():
    """An empty box reads as 'no news'. The truth is 'could not fetch'."""
    rendered = str(headlines_panel([], ["espn: connection refused"]))
    assert "unavailable" in rendered.lower()


def test_trending_panel_labels_counts_as_national():
    """These counts are national and must never read as a claim prediction."""
    players = {"4046": Player(sleeper_id="4046", name="Some Guy",
                              position="RB", team="CHI")}
    rendered = str(trending_panel({"4046": 12345}, players))
    assert "NATIONALLY" in rendered or "national" in rendered.lower()
    assert "NOT your league" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_app.py -k "headlines_panel or trending_panel" -v`
Expected: FAIL with `ImportError: cannot import name 'headlines_panel'`

- [ ] **Step 3: Implement both panels and add them to `home_layout`**

Each panel is a bordered section under the status strip, visually separated from the nav and carrying its own heading. Headlines are `dcc.Link` items opening in a new tab. Trending shows the top ten by count with the national label as a sub-line, resolving ids through `load_players` and **printing an unresolved id rather than dropping it** (non-negotiable #3).

Both panels catch their own fetch failures. **A dead feed must not take down the homepage** — the status strip is the part that has to work.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and the mutation sweep**

```bash
.venv/bin/python -m pytest tests/ -q
git status --porcelain > /tmp/pre.txt
.venv/bin/python scripts/mutate.py
git status --porcelain > /tmp/post.txt && diff /tmp/pre.txt /tmp/post.txt
```
Expected: suite green, all mutations killed, empty `git status` diff.

- [ ] **Step 6: Verify the homepage against real data**

Load `/` and confirm: the strip shows the current week; the snapshot line matches what is actually in `season.db`; headlines are current and clickable; trending names resolve. Then break a feed URL temporarily and confirm the panel says unavailable while the rest of the page still renders.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): headlines and trending panels

Separated from anything advisory: start_sit never saw a headline, and a panel
beside the advice would imply otherwise. Trending stays labelled national."
```

---

## Done means

- `.venv/bin/python -m ffhelper.app --league sleeper-main` serves `/`, `/draft`, `/lineup`, `/waivers`, `/trades` on localhost.
- Every page matches its CLI command's numbers, checked by hand against real data.
- `yahoo-main` shows the refusal text on `/waivers` and `/trades`, and a working `/lineup`.
- The full suite is green and every mutation is killed, with `git status` unchanged before and after.
- Nothing runs unattended. Nothing new writes to `season.db`.

## Deliberately not done

Hosting, Tailscale, `0.0.0.0` binding, scheduled jobs, alerting, notifications, the `taken_at` schema change, and the Phase 3.7 `DataTable` swap. All are recorded in the spec — most under "Deferred, with the research intact", which is where the alerting design, the measured 24-hour TTL defect, the inactives timing and the four candidate homes for a scheduled job already live. **None of it should be re-derived.**
