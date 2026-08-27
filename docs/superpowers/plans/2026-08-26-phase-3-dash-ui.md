# Phase 3 Dash UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Dash web board that renders the same engine the terminal renders, and that the user drives the draft from by clicking rows instead of typing names.

**Architecture:** The `.draft/<league>-<date>.jsonl` journal is the database — every render replays it, polls the feed, and rebuilds the board, so there is no server-side mutable state and the CLI can take over at any point by replaying the same file. Board derivation is copied into a new additive module (`ffhelper/board.py`) rather than extracted out of `cli.py`, because `cli.py` is the live draft path and is frozen until Sept 6; an agreement test proves the copy matches. `my_roster` is derived from the draft seat and pick number rather than typed.

**Tech Stack:** Python 3.12, Dash (new, optional dependency), stdlib `tomllib`/`json`/`statistics`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-3-dash-ui-design.md`

## Global Constraints

- **Python 3.12.** Stdlib first. No pandas, no scipy, no PyYAML.
- **`value.py` and `data.py` are FROZEN** until both drafts are done (Sept 6 2026). No task in this plan edits either. Reading and importing them is fine.
- **`cli.py` is NOT edited by this plan.** Every task is additive. The one permitted change to an existing file is `pyproject.toml` (Task 1).
- **`app.py` imports `cli.py`. `cli.py` never imports `app.py`.** One direction, enforced by a test.
- **`dash` is an optional dependency** under the `web` extra. `python -m ffhelper.cli run` must work on a machine with no `dash` installed.
- **Never join load-bearing data on player name.** Everything here joins on `sleeper_id`.
- **Never blend projection rank with ADP rank.** Divergence stays a flag.
- **Unmatched or ambiguous data is printed, never silently dropped.**
- **Degrade, never fabricate.** A missing slot, dead feed or unknown value produces a visible labelled degradation.
- **A new test must be shown to FAIL before the fix**, via `git stash push -- ffhelper && .venv/bin/python -m pytest -k <name>` (then `git stash pop`). A test written after the code and never seen red is not evidence.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.**
- Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and the upgrade path.
- Run the suite with `.venv/bin/python -m pytest -q`. Baseline at plan start: **236 passed**.
- Commit on a feature branch. Never `git push`, `git merge`, `git rebase`, or anything touching `main`.

---

## File Structure

| File | Status | Responsibility |
| --- | --- | --- |
| `pyproject.toml` | modify | declare the `web` optional extra |
| `ffhelper/board.py` | create | board derivation + seat-based attribution. Pure, no Dash import. Consumed only by `app.py` until after Sept 6. |
| `ffhelper/app.py` | create | Dash app: layout, callbacks, row/panel building. The only file that imports `dash`. |
| `tests/test_dash_isolation.py` | create | `dash` cannot leak into the terminal path |
| `tests/test_board.py` | create | `board_state`, `marks_in_entry_order`, `auto_mine` |
| `tests/test_board_agreement.py` | create | `board_state` matches `_render_tick`'s derivation exactly |
| `tests/test_app.py` | create | row building, roster panel, banner logic — no server, no browser |
| `scripts/mutate.py` | modify | mutations for the new logic |

`board.py` holds everything testable without Dash; `app.py` holds everything that needs it. That split is what keeps the suite fast and browser-free.

---

### Task 1: `dash` as an isolated optional dependency

Nothing else can be built until it is proven that adding Dash cannot break draft night.

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_dash_isolation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the `web` extra (`pip install -e '.[web,dev]'` works); the guarantee that `ffhelper.cli` imports with `dash` absent.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dash_isolation.py`:

```python
"""dash must never become a draft-night dependency.

The terminal board is the fallback when the web board misbehaves. If importing
`ffhelper.cli` required `dash`, a broken or uninstalled dash would take the
fallback down with it -- which is precisely the moment it is needed.
"""
import importlib
import sys

import pytest


class _BlockDash:
    """A meta_path finder that makes `import dash` raise, as if it were absent."""

    def find_spec(self, name, path=None, target=None):
        if name == "dash" or name.startswith("dash."):
            raise ImportError(f"{name} is blocked for this test")
        return None


@pytest.fixture
def dash_absent(monkeypatch):
    for mod in [m for m in sys.modules if m == "dash" or m.startswith(("dash.", "ffhelper"))]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BlockDash(), *sys.meta_path])
    yield


def test_cli_imports_with_dash_absent(dash_absent):
    cli = importlib.import_module("ffhelper.cli")
    assert hasattr(cli, "main")


def test_cli_does_not_import_app(dash_absent):
    importlib.import_module("ffhelper.cli")
    assert "ffhelper.app" not in sys.modules, (
        "cli.py imported app.py -- the dependency must run one way only"
    )


def test_the_block_fixture_actually_blocks(dash_absent):
    # Guards the two tests above from passing vacuously: if this import
    # succeeds, the fixture is broken and the other assertions prove nothing.
    with pytest.raises(ImportError):
        importlib.import_module("dash")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dash_isolation.py -v`

Expected: `test_the_block_fixture_actually_blocks` FAILS with `Failed: DID NOT RAISE` if `dash` is not yet installed — that is the point of this step. Install first, then re-run:

```bash
.venv/bin/python -m pip install -e '.[web,dev]'
```

which fails with `WARNING: ffhelper 0.1.0 does not provide the extra 'web'` until Step 3 lands.

- [ ] **Step 3: Add the extra and install**

In `pyproject.toml`, replace the `[project.optional-dependencies]` block:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]
# Phase 3 only. NOT a base dependency: `python -m ffhelper.cli run` must work on
# a machine with no dash installed, because the terminal board is the fallback
# when the web board misbehaves. tests/test_dash_isolation.py enforces this.
web = ["dash>=2.17"]
```

Then:

```bash
.venv/bin/python -m pip install -e '.[web,dev]'
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dash_isolation.py -v`
Expected: 3 passed.

Run: `.venv/bin/python -m pytest -q`
Expected: 239 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_dash_isolation.py
git commit -m "build: add dash as an isolated optional 'web' extra"
```

---

### Task 2: `board_state` — the copied derivation, with an agreement test

**Files:**
- Create: `ffhelper/board.py`
- Test: `tests/test_board.py`, `tests/test_board_agreement.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `cli._my_roster_from_picks`, `cli._claims_overruled_by_feed`, `cli._combine_my_roster`; `value.build_board`, `value.detect_run`, `value.Row`; `data.Player`, `data.LeagueSettings`; `config.League`, `config.Tunables`.
- Produces:
  - `BoardState` — frozen dataclass with fields `board: list[Row]`, `current_pick: int`, `available: list[Player]`, `my_roster: list[Player]`, `overruled: set[str]`, `runs: dict[str, int]`, `drafted: set[str]`.
  - `board_state(players: dict[str, Player], picks: list, manual_gone: set[str], manual_mine: set[str], settings: LeagueSettings, league: League, tunables: Tunables) -> BoardState`.

- [ ] **Step 1: Write the failing agreement test**

Create `tests/test_board_agreement.py`. This is the guard on the duplication and the proof that October's extraction will be a no-op, so it is written before the code it guards.

```python
"""ffhelper.board.board_state must agree with cli._render_tick, exactly.

board.py holds a COPY of the derivation in _render_tick (cli.py:623-641),
because cli.py is the live draft path and is frozen until after Sept 6 2026.
A copy that drifts from its original is this project's signature failure --
Task 13 defects #1, #3 and #6 were all one component disagreeing with another
about who had been drafted. This test is what makes the copy safe.
"""
from dataclasses import dataclass

from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper import cli


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


def _pool() -> dict[str, Player]:
    # Deliberately NOT round numbers or a four-player pool: fixtures chosen for
    # arithmetic convenience are what hid seven of this project's defects.
    pool = {}
    for i in range(1, 61):
        pos = ["QB", "RB", "WR", "TE", "K", "DEF"][i % 6]
        pool[str(i)] = Player(
            sleeper_id=str(i), name=f"Player {i}", position=pos, team="KC",
            proj_pts=320.4 - i * 3.7, adp=float(i) + 0.6, adp_stdev=6.3 + i * 0.11,
            bye=(i % 14) + 1,
        )
    return pool


def _settings() -> LeagueSettings:
    return LeagueSettings(
        num_teams=12,
        scoring={"rec": 1.0, "pass_td": 6.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def test_board_state_matches_render_tick(monkeypatch):
    players = _pool()
    settings = _settings()
    league = League(name="t", platform="sleeper", league_id="1", draft_slot=5)
    tunables = Tunables()
    picks = [FakePick("3", 1, 1), FakePick("7", 2, 5), FakePick("11", 3, 9)]
    manual_gone = {"3", "7", "11", "20", "21"}
    manual_mine = {"20"}

    captured = {}

    def fake_render(board, limit, stale_seconds, my_roster, runs, divergence_flag_slots=10):
        captured["board"] = board
        captured["my_roster"] = my_roster
        captured["runs"] = runs
        return ""

    monkeypatch.setattr(cli, "render", fake_render)
    cli._render_tick(
        picks, None, players, settings, league, tunables, 20,
        manual_gone, manual_mine, league.draft_slot, "",
    )

    state = board_state(players, picks, manual_gone, manual_mine,
                        settings, league, tunables)

    assert state.board == captured["board"]
    assert state.my_roster == captured["my_roster"]
    assert state.runs == captured["runs"]


def test_board_state_agrees_when_a_claim_is_overruled(monkeypatch):
    # The path most likely to drift: the feed contradicting a self-mark.
    players = _pool()
    settings = _settings()
    league = League(name="t", platform="sleeper", league_id="1", draft_slot=5)
    tunables = Tunables()
    picks = [FakePick("20", 1, 9)]          # seat 9 took the player claimed as ours
    manual_gone = {"20"}
    manual_mine = {"20"}

    captured = {}
    monkeypatch.setattr(
        cli, "render",
        lambda board, limit, stale, my_roster, runs, div=10: captured.update(
            board=board, my_roster=my_roster) or "",
    )
    cli._render_tick(picks, None, players, settings, league, tunables, 20,
                     manual_gone, manual_mine, league.draft_slot, "")

    state = board_state(players, picks, manual_gone, manual_mine,
                        settings, league, tunables)

    assert state.overruled == {"20"}
    assert state.my_roster == captured["my_roster"] == []
    assert state.board == captured["board"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_board_agreement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.board'`

- [ ] **Step 3: Write `ffhelper/board.py`**

```python
"""Board derivation, shared by the web UI and (after Sept 6) the terminal.

ponytail: `board_state` is a COPY of the derivation block in
`cli._render_tick` (cli.py:623-641), not an extraction. cli.py is the live
draft path and is frozen until both 2026 drafts are done, and editing it six
days out buys nothing before October. `tests/test_board_agreement.py` proves
the two agree, and is also the proof that the extraction is a no-op when it
happens. UPGRADE PATH, after 2026-09-06: delete that block from `_render_tick`,
call `board_state` there, and move the three `_`-prefixed helpers imported
below into this module.
"""
from dataclasses import dataclass

from ffhelper.cli import (
    _claims_overruled_by_feed, _combine_my_roster, _my_roster_from_picks,
)
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper.value import Row, build_board, detect_run


@dataclass(frozen=True)
class BoardState:
    """Everything one frame of the board needs, and nothing about rendering it."""
    board: list[Row]
    current_pick: int
    available: list[Player]
    my_roster: list[Player]
    overruled: set[str]         # self-marks the feed attributes to another seat
    runs: dict[str, int]
    drafted: set[str]


def board_state(
    players: dict[str, Player], picks: list, manual_gone: set[str],
    manual_mine: set[str], settings: LeagueSettings, league: League,
    tunables: Tunables,
) -> BoardState:
    """Derive one frame of the draft board. Pure: no I/O, no printing."""
    # The pick count must come from the SAME set used to filter the pool, or the
    # board can disagree with itself about who is gone. In manual mode `picks`
    # is permanently empty and `len(picks) + 1` would freeze the board at pick 1
    # forever. The feed's own highest pick_no is authoritative where it exists,
    # because parse_sleeper_picks skips malformed rows and one bad row would
    # otherwise shift the horizon down by one for the rest of the draft.
    drafted = {p.sleeper_id for p in picks} | manual_gone
    highest = max((p.pick_no for p in picks), default=0)
    current_pick = max(len(drafted), highest) + 1
    available = [p for pid, p in players.items() if pid not in drafted]
    feed_roster = _my_roster_from_picks(picks, players, league.draft_slot)
    # A claim the feed contradicts leaves my_roster but NOT `drafted` -- the
    # player really is gone, just not to you.
    overruled = _claims_overruled_by_feed(picks, manual_mine, league.draft_slot)
    my_roster = _combine_my_roster(feed_roster, manual_mine - overruled, players)
    recent = [players[p.sleeper_id].position for p in picks[-8:] if p.sleeper_id in players]

    board = build_board(
        available, my_roster, settings.roster_slots, settings.num_teams,
        current_pick=current_pick, my_slot=league.draft_slot, tunables=tunables,
        # The FULL pool, not `available`: replacement level is a property of the
        # league. Drawing it from the draining pool gave a backup QB a VBD of
        # +149.0 against a true -32.5 in the Task 13 mock.
        replacement_pool=list(players.values()),
    )
    return BoardState(
        board=board, current_pick=current_pick, available=available,
        my_roster=my_roster, overruled=overruled, runs=detect_run(recent),
        drafted=drafted,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_board_agreement.py -v`
Expected: 2 passed.

- [ ] **Step 5: Add the direct unit tests**

Create `tests/test_board.py`:

```python
from dataclasses import dataclass

from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


def _pool(n: int = 40) -> dict[str, Player]:
    return {
        str(i): Player(
            sleeper_id=str(i), name=f"Player {i}",
            position=["QB", "RB", "WR", "TE", "K", "DEF"][i % 6], team="KC",
            proj_pts=310.2 - i * 4.1, adp=float(i) + 1.4, adp_stdev=5.9 + i * 0.13,
        )
        for i in range(1, n + 1)
    }


def _settings(num_teams: int = 12) -> LeagueSettings:
    return LeagueSettings(
        num_teams=num_teams, scoring={"rec": 1.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def _league(slot: int | None = 5) -> League:
    return League(name="t", platform="sleeper", league_id="1", draft_slot=slot)


def test_current_pick_counts_manual_marks_when_there_is_no_feed():
    # Manual mode: picks is permanently empty. A count derived from `picks`
    # freezes the board at pick 1 for a whole draft -- Task 13 defect, and it
    # invalidates every survival and VONA number on every tick.
    state = board_state(_pool(), [], {"1", "2", "3", "4"}, set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 5


def test_current_pick_prefers_the_feeds_highest_pick_no():
    # parse_sleeper_picks drops malformed rows, so len(picks) can understate
    # how far the draft has actually gone.
    picks = [FakePick("1", 1, 1), FakePick("2", 7, 7)]
    state = board_state(_pool(), picks, set(), set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 8


def test_drafted_players_leave_the_available_pool():
    state = board_state(_pool(), [], {"3"}, set(), _settings(), _league(), Tunables())
    assert all(r.player.sleeper_id != "3" for r in state.board)


def test_a_player_reported_by_both_feed_and_mark_is_counted_once():
    picks = [FakePick("1", 1, 1)]
    state = board_state(_pool(), picks, {"1"}, set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 2
```

- [ ] **Step 6: Verify the new tests fail against pre-fix source**

```bash
git stash push -u -- ffhelper
.venv/bin/python -m pytest tests/test_board.py tests/test_board_agreement.py -q
git stash pop
```

Expected while stashed: collection errors (`No module named 'ffhelper.board'`) for all six tests. A test never seen red is not evidence.

**`-u` is required and is not optional here.** `ffhelper/board.py` is a NEW file, and plain `git stash push -- ffhelper` does not stash untracked files — the module would stay on disk, the tests would pass, and the run would look like evidence while proving nothing. If for any reason the stash cannot be made to remove the file, cite Step 2's output as the red evidence instead (it ran before the module existed) and say so explicitly. Never report a green stash run as red evidence.

- [ ] **Step 7: Add mutations**

In `scripts/mutate.py`, add a `"ffhelper/board.py"` key to `MUTATIONS`:

```python
    "ffhelper/board.py": [
        ("pick count ignores manual marks",
         "current_pick = max(len(drafted), highest) + 1",
         "current_pick = max(len(picks), highest) + 1"),
        ("pick count off by one",
         "current_pick = max(len(drafted), highest) + 1",
         "current_pick = max(len(drafted), highest)"),
        ("overruled claims left in my_roster",
         "_combine_my_roster(feed_roster, manual_mine - overruled, players)",
         "_combine_my_roster(feed_roster, manual_mine, players)"),
        ("replacement drawn from the draining pool",
         "replacement_pool=list(players.values()),",
         "replacement_pool=available,"),
    ],
```

- [ ] **Step 8: Run the mutation check and the full suite**

Run: `.venv/bin/python scripts/mutate.py`
Expected: the four new mutations are KILLED. If any survives, the test that should have caught it is vacuous — fix the test, not the mutation.

Run: `.venv/bin/python -m pytest -q`
Expected: 245 passed.

- [ ] **Step 9: Commit**

```bash
git add ffhelper/board.py tests/test_board.py tests/test_board_agreement.py scripts/mutate.py
git commit -m "feat(board): derive board state for the web UI, with a CLI agreement test"
```

---

### Task 3: The Dash shell and a read-only board

End of 3a. Deliverable: a board you can open in a browser during a draft.

**Files:**
- Create: `ffhelper/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `board.board_state`, `board.BoardState`; `cli.load_board_inputs`, `cli._select_feed`, `cli._draft_log_path`, `cli._restore_marks`, `cli.DRAFT_LOG_DIR`, `cli.ROOT`; `config.load_config`, `config.get_league`; `value.is_bench_only`, `value.next_pick_number`.
- Produces:
  - `board_rows(state: BoardState, limit: int, divergence_flag_slots: int) -> list[dict]` — one dict per row, keys `rank`, `id`, `player`, `pos`, `vona`, `vbd`, `marg`, `tier`, `surv`, `div`, `flags`.
  - `banner_lines(state: BoardState, stale_seconds: float | None, players: dict[str, Player]) -> list[str]`.
  - `read_state(league, tunables, players, settings, feed) -> tuple[BoardState, float | None]`.
  - `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app.py`:

```python
from dataclasses import dataclass

from ffhelper.app import banner_lines, board_rows
from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


def _pool(n: int = 40) -> dict[str, Player]:
    return {
        str(i): Player(
            sleeper_id=str(i), name=f"Player {i}",
            position=["QB", "RB", "WR", "TE", "K", "DEF"][i % 6], team="KC",
            proj_pts=310.2 - i * 4.1, adp=float(i) + 1.4, adp_stdev=5.9 + i * 0.13,
            bye=(i % 14) + 1,
        )
        for i in range(1, n + 1)
    }


def _settings() -> LeagueSettings:
    return LeagueSettings(
        num_teams=12, scoring={"rec": 1.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def _state(picks=(), gone=frozenset(), mine=frozenset(), players=None):
    players = players or _pool()
    return board_state(players, list(picks), set(gone), set(mine), _settings(),
                       League(name="t", platform="sleeper", league_id="1", draft_slot=5),
                       Tunables()), players


def test_board_rows_carry_the_player_id_so_a_click_never_matches_on_name():
    # Non-negotiable #1: load-bearing joins are on integer ids. A click that
    # resolved a row back to a player by NAME would reintroduce the exact
    # ambiguity (Bijan vs Brian Robinson) the whole design forbids.
    state, _ = _state()
    rows = board_rows(state, limit=10, divergence_flag_slots=10)
    assert all(r["id"] for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)


def test_board_rows_respect_the_limit_and_are_ranked_from_one():
    state, _ = _state()
    rows = board_rows(state, limit=7, divergence_flag_slots=10)
    assert len(rows) == 7
    assert [r["rank"] for r in rows] == list(range(1, 8))


def test_unpriced_players_show_a_dash_not_a_fabricated_zero():
    # divergence is None for a player the market never priced -- a third of the
    # pool. No opinion is not agreement.
    players = _pool()
    for p in players.values():
        p.adp = 999.0
    state, _ = _state(players=players)
    rows = board_rows(state, limit=5, divergence_flag_slots=10)
    assert all(r["div"] == "-" for r in rows)


def test_a_dead_feed_produces_a_stale_banner():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=42.0, players=players)
    assert any("STALE" in line for line in lines)


def test_no_feed_says_so_rather_than_showing_a_staleness_clock():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("MANUAL MODE" in line for line in lines)
    assert not any("STALE" in line for line in lines)


def test_an_overruled_claim_raises_a_standing_banner_naming_the_player():
    players = _pool()
    picks = [FakePick("20", 1, 9)]
    state, players = _state(picks=picks, gone={"20"}, mine={"20"}, players=players)
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("CLAIM OVERRULED" in line and "Player 20" in line for line in lines)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.app'`

- [ ] **Step 3: Write `ffhelper/app.py`**

```python
"""Dash draft board. The only module in this package that imports dash.

State model: the `.draft/<league>-<date>.jsonl` journal IS the database. Every
render replays it, polls the feed, and rebuilds the board, so this process holds
no mutable draft state at all. That is what lets the terminal board take over at
any moment by replaying the same file -- ctrl-C here, `python -m ffhelper.cli
run --league <name>` there, and nothing is lost.

ONE PROCESS AT A TIME. The CLI holds MarkDrafted in memory and replays only at
startup, so it will not see writes made here while it is running. The handover
is sequential in both directions, never concurrent.
"""
import argparse
import logging
import sys
import time

import dash
from dash import Input, Output, dash_table, dcc, html

from ffhelper.board import BoardState, board_state
from ffhelper.cli import (
    DRAFT_LOG_DIR, ROOT, _draft_log_path, _restore_marks, _select_feed,
    load_board_inputs,
)
from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import Player
from ffhelper.value import is_bench_only, next_pick_number

log = logging.getLogger(__name__)
CONFIG_PATH = ROOT / "config.toml"

COLUMNS = [
    {"name": "#", "id": "rank"}, {"name": "PLAYER", "id": "player"},
    {"name": "POS", "id": "pos"}, {"name": "VONA", "id": "vona"},
    {"name": "VBD", "id": "vbd"}, {"name": "MARG", "id": "marg"},
    {"name": "TIER", "id": "tier"}, {"name": "SURV", "id": "surv"},
    {"name": "DIV", "id": "div"}, {"name": "FLAGS", "id": "flags"},
]


def board_rows(state: BoardState, limit: int, divergence_flag_slots: int) -> list[dict]:
    """One dict per displayed row. Data only -- no styling, no dash types.

    ponytail: rows are plain dicts precisely so the DataTable can be swapped for
    a hand-rolled table later without touching this function. DataTable's
    ceiling is that a row cannot contain arbitrary markup -- no sparklines, no
    per-row buttons, no true tier separator rows -- so tier grouping is done
    with background colour (Task 7) rather than header rows.
    """
    rows = []
    for i, r in enumerate(state.board[:limit], 1):
        flags = []
        if r.player.injury_status:
            flags.append(r.player.injury_status)
        # None means the market never priced him -- a third of the pool. No
        # opinion is not agreement, so no flag and a dash, never a 0.
        if r.divergence is not None and abs(r.divergence) >= divergence_flag_slots:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        if r.player.bye:
            flags.append(f"bye{r.player.bye}")
        rows.append({
            "rank": i,
            "id": r.player.sleeper_id,      # every click resolves through this
            "player": r.player.name,
            "pos": r.player.position,
            "vona": round(r.vona, 1),
            "vbd": round(r.vbd, 1),
            "marg": round(r.marginal, 1),
            "tier": r.tier,
            "surv": f"{r.survival:.0%}",
            "div": "-" if r.divergence is None else f"{r.divergence:+d}",
            "flags": " ".join(flags),
        })
    return rows


def banner_lines(
    state: BoardState, stale_seconds: float | None, players: dict[str, Player],
) -> list[str]:
    """Degrade, never fabricate: every degraded condition says so on screen."""
    lines: list[str] = []
    if stale_seconds is None:
        lines.append("MANUAL MODE: no pick feed -- picks are entered by hand only")
    elif stale_seconds > 15:
        lines.append(f"!! FEED STALE {stale_seconds:.0f}s -- board may be out of date")
    if is_bench_only(state.board):
        lines.append("STARTING LINEUP FULL: no player improves your starters. "
                     "These are BENCH picks, ordered by value over league replacement. "
                     "The tool has no model of upside or handcuffs -- trust yourself here.")
    for pid in sorted(state.overruled):
        name = players[pid].name if pid in players else pid
        lines.append(f"CLAIM OVERRULED: the feed says {name} was taken from another "
                     f"seat, not yours -- dropped from your roster.")
    if state.runs:
        summary = "  ".join(f"{pos} {n}" for pos, n in
                            sorted(state.runs.items(), key=lambda kv: -kv[1]))
        lines.append(f"last 8 picks:  {summary}")
    return lines


def clock_line(state: BoardState, league: League, num_teams: int) -> str:
    if not league.draft_slot:
        return f"pick {state.current_pick}"
    nxt = next_pick_number(state.current_pick, league.draft_slot, num_teams)
    # next_pick_number is strictly-after, so ask from one pick earlier and see
    # whether it lands here.
    if next_pick_number(state.current_pick - 1, league.draft_slot, num_teams) == state.current_pick:
        return (f">>> PICK {state.current_pick} IS YOURS -- YOU ARE ON THE CLOCK <<<"
                f"   (next after this: {nxt})")
    return (f"pick {state.current_pick}   your next pick: {nxt} "
            f"({nxt - state.current_pick} away)")


# Poll bookkeeping only -- NOT draft state. The board itself is rebuilt from the
# journal every tick and nothing about who was drafted lives in this process.
_LAST_OK: dict[str, float] = {}


def read_state(league, tunables, players, settings, feed, has_feed):
    """Replay the journal, poll the feed, derive the board. -> (state, stale_seconds)

    Every failure degrades rather than raising: a dead feed must leave the board
    on screen with an honest staleness banner, not an error page.

    `stale_seconds is None` means there is no feed at all (Yahoo), which is a
    different statement from "the feed has not answered recently" and must read
    differently on screen.
    """
    mark_state, _applied, _skipped = _restore_marks(_draft_log_path(league))
    picks, stale_seconds = [], None
    try:
        picks = feed.get_picks()
    except Exception as exc:                          # noqa: BLE001 - never fatal
        log.warning("poll failed: %s", exc)
        if has_feed:
            stale_seconds = time.time() - _LAST_OK.get(league.name, time.time())
    else:
        if has_feed:
            _LAST_OK[league.name] = time.time()
            stale_seconds = 0.0
    state = board_state(players, picks, mark_state.drafted, mark_state.mine,
                        settings, league, tunables)
    return state, stale_seconds


def build_app(league_names: list[str], default_league: str) -> dash.Dash:
    app = dash.Dash(__name__, use_pages=True, pages_folder="")
    dash.register_page("board", path="/", layout=_layout(league_names, default_league))
    app.layout = html.Div([dash.page_container])
    return app


def _layout(league_names: list[str], default_league: str):
    return html.Div([
        dcc.Dropdown(id="league", options=league_names, value=default_league,
                     clearable=False, style={"width": "20rem"}),
        html.Pre(id="banners"),
        html.Pre(id="clock"),
        dash_table.DataTable(
            id="board", columns=COLUMNS, data=[],
            style_cell={"fontFamily": "monospace", "textAlign": "left"},
        ),
        dcc.Interval(id="tick", interval=5000),
    ])


def _register_callbacks(app, leagues, tunables, cache):
    @app.callback(
        Output("board", "data"), Output("banners", "children"),
        Output("clock", "children"),
        Input("tick", "n_intervals"), Input("league", "value"),
    )
    def _refresh(_n, league_name):
        league = get_league(leagues, league_name)
        players, settings, feed, has_feed = cache(league)
        state, stale = read_state(league, tunables, players, settings, feed, has_feed)
        return (
            board_rows(state, limit=40,
                       divergence_flag_slots=tunables.divergence_flag_slots),
            "\n".join(banner_lines(state, stale, players)),
            clock_line(state, league, settings.num_teams),
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dash draft board")
    ap.add_argument("--league", required=True)
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args(argv)

    leagues, tunables = load_config(CONFIG_PATH)
    names = [lg.name for lg in leagues]
    get_league(leagues, args.league)                  # fail fast on a bad name
    DRAFT_LOG_DIR.mkdir(exist_ok=True)

    # ONE PROCESS AT A TIME. Said at startup, not only in the docstring: the
    # CLI replays the journal once, at ITS startup, so a CLI left running
    # alongside this app will quietly show a stale board.
    print("ffhelper web board. Do NOT run `ffhelper.cli run` for this league at "
          "the same time -- stop one before starting the other.")

    loaded: dict[str, tuple] = {}

    def cache(league: League):
        """Cold start once per league. The POOL is cached; the board is not."""
        if league.name not in loaded:
            players, settings = load_board_inputs(league, tunables)
            feed, has_feed = _select_feed(league, settings)
            # Seed the staleness clock at load, so the FIRST failed poll reports
            # real elapsed time instead of 0 and hides a feed that never worked.
            _LAST_OK[league.name] = time.time()
            loaded[league.name] = (players, settings, feed, has_feed)
        return loaded[league.name]

    app = build_app(names, args.league)
    _register_callbacks(app, leagues, tunables, cache)
    app.run(port=args.port)
    return 0


# NO module-level `server` for gunicorn. It was in the design as a "free line
# that keeps hosting open", and it is not free: gunicorn imports this module and
# never calls main(), so a `server` populated inside main() is always None -- a
# decorative hook that fails the moment it is used. The real retrofit is to build
# the app at import time, which means league selection has to move out of argv
# and into config or the environment. That is a genuine change, and pretending
# otherwise with a dead global is worse than admitting it. See the spec's
# "Hosting, later".


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 6 passed.

- [ ] **Step 5: Verify the new tests fail against pre-fix source**

```bash
git stash push -u -- ffhelper
.venv/bin/python -m pytest tests/test_app.py -q
git stash pop
```

Expected while stashed: collection error, `No module named 'ffhelper.app'`.

**`-u` is required**: `ffhelper/app.py` is a new file and plain stash leaves untracked files in place, which would produce a green run that looks like evidence. If the stash cannot remove it, cite Step 2 as the red evidence and say so.

- [ ] **Step 6: Run it against real data — this is the step that finds the defects**

This project's defining lesson is that a green suite proves nothing. Nine defects were found by running the code.

```bash
.venv/bin/python -m ffhelper.cli preflight --league yahoo-main
.venv/bin/python -m ffhelper.app --league yahoo-main
```

Open `http://127.0.0.1:8050`. Confirm, against a terminal running the same league side by side:

- the top 10 rows are the same players in the same order
- `MANUAL MODE` appears for `yahoo-main` (no feed) and does not say STALE
- the clock line matches the terminal's
- the board is not full of kickers (the pick-1 VONA-compression bug)

Record anything that differs. A mismatch here is a real defect, not a cosmetic one.

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: 251 passed.

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): read-only Dash draft board over the shared board state"
```

---

### Task 4: The write path — click to mark, and undo

End of 3b. This is the sub-phase where a bug corrupts state rather than merely looking wrong.

**Files:**
- Modify: `ffhelper/app.py`
- Test: `tests/test_app.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `cli.MarkDrafted`, `cli._restore_marks`, `cli._draft_log_path`.
- Produces: `apply_click(log_path, player_id) -> str`, `apply_undo(log_path) -> str` — each replays the journal, applies one op, and returns a status string.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
import json

from ffhelper.app import apply_click, apply_undo
from ffhelper.cli import _restore_marks


def test_a_click_appends_one_mark_op_to_the_journal(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    ops = [json.loads(line) for line in path.read_text().splitlines()]
    assert ops == [{"op": "mark", "id": "42", "mine": False}]


def test_clicking_the_same_player_twice_is_idempotent(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "42")
    state, _applied, _skipped = _restore_marks(path)
    assert state.drafted == {"42"}


def test_undo_takes_back_the_last_mark(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "43")
    apply_undo(path)
    state, _applied, _skipped = _restore_marks(path)
    assert state.drafted == {"42"}


def test_undo_is_journalled_so_a_restart_does_not_resurrect_the_mark(tmp_path):
    # An unlogged undo replays away: the restart brings back a pick the user
    # had already taken back, and the pool goes quietly wrong.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_undo(path)
    ops = [json.loads(line)["op"] for line in path.read_text().splitlines()]
    assert ops == ["mark", "undo"]


def test_a_click_survives_a_process_restart(tmp_path):
    # The whole point of the journal-as-database model, and the CLI handover.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "7")
    state, applied, skipped = _restore_marks(path)
    assert state.drafted == {"42", "7"}
    assert (applied, skipped) == (2, 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py -k "click or undo" -v`
Expected: FAIL — `ImportError: cannot import name 'apply_click' from 'ffhelper.app'`

- [ ] **Step 3: Implement the write path**

Add to `ffhelper/app.py`, above `build_app`:

```python
def apply_click(log_path, player_id: str) -> str:
    """Mark one player drafted. Replay, apply, append -- never hold state.

    Replaying before every write is what makes the CLI handover exact: the
    journal on disk is the only thing either process trusts, so a mark typed
    into the terminal a moment ago is already accounted for here.
    """
    state, _applied, _skipped = _restore_marks(log_path)
    state.mark(player_id)
    return f"marked {player_id}"


def apply_undo(log_path) -> str:
    state, _applied, _skipped = _restore_marks(log_path)
    if not state._history:
        return "nothing to undo"
    state.undo()
    return "undone"
```

Add the click and undo callback in `_register_callbacks`, and the controls to `_layout`.

In `_layout`, add to the children list, before `dcc.Interval`:

```python
        html.Button("undo", id="undo", n_clicks=0),
        html.Pre(id="status"),
```

and give the `DataTable` `active_cell` support by adding `cell_selectable=True` to its constructor call.

In `_register_callbacks`, add a second callback:

```python
    @app.callback(
        Output("status", "children"), Output("tick", "n_intervals"),
        Input("board", "active_cell"), Input("undo", "n_clicks"),
        dash.State("board", "data"), dash.State("league", "value"),
        dash.State("tick", "n_intervals"),
        prevent_initial_call=True,
    )
    def _write(active_cell, _undo_clicks, rows, league_name, n):
        league = get_league(leagues, league_name)
        path = _draft_log_path(league)
        trigger = dash.callback_context.triggered_id
        try:
            if trigger == "undo":
                status = apply_undo(path)
            elif active_cell and rows:
                # Resolve the click through the row's id, never its name.
                status = apply_click(path, rows[active_cell["row"]]["id"])
            else:
                status = ""
        except Exception as exc:                      # noqa: BLE001 - never fatal
            log.error("write failed: %s", exc, exc_info=True)
            status = f"could not apply that -- {exc}"
        # Bump the tick so the board redraws immediately rather than waiting for
        # the poll interval. Entry latency must never be paced by the network:
        # that coupling is what abandoned mock run 1 at 12 000 ms per keystroke.
        return status, (n or 0) + 1
```

Import `MarkDrafted` is not needed — `_restore_marks` returns one already attached to the log.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 11 passed.

- [ ] **Step 5: Verify the new tests fail against pre-fix source**

```bash
git stash push -- ffhelper
.venv/bin/python -m pytest tests/test_app.py -k "click or undo" -q
git stash pop
```

- [ ] **Step 6: Add mutations**

Add to the `"ffhelper/app.py"` key in `scripts/mutate.py` (create the key if absent):

```python
    "ffhelper/app.py": [
        ("click resolves rows by position instead of id",
         'status = apply_click(path, rows[active_cell["row"]]["id"])',
         'status = apply_click(path, rows[active_cell["row"]]["player"])'),
        ("undo not journalled",
         "        state.undo()", "        pass"),
        ("write does not force a redraw",
         "return status, (n or 0) + 1", "return status, n"),
    ],
```

Run: `.venv/bin/python scripts/mutate.py`
Expected: all three KILLED.

- [ ] **Step 7: Run it against real data — the CLI handover**

This is the check the whole state model exists for.

```bash
.venv/bin/python -m ffhelper.app --league yahoo-mock
```

Click 20 players in. Then ctrl-C and:

```bash
.venv/bin/python -m ffhelper.cli run --league yahoo-mock
```

Confirm the restore banner reports **20 marks**, the same 20 players are off the board, and the pick counter reads 21. Then ctrl-C the CLI, restart the Dash app, and confirm it still reads 20.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: 256 passed.

```bash
git add ffhelper/app.py tests/test_app.py scripts/mutate.py
git commit -m "feat(app): click-to-mark and undo, journalled for CLI handover"
```

---

### Task 5: Seat-based attribution (pure)

Start of 3c. Pure logic, tested against a real transcript, before any UI.

**Files:**
- Modify: `ffhelper/board.py`
- Test: `tests/test_board.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `value.next_pick_number`, `cli._restore_marks`.
- Produces:
  - `marks_in_entry_order(log_path) -> list[str]` — surviving marks in the order they were entered, index+1 = pick number.
  - `my_turns(seat: int, num_teams: int, through_pick: int) -> list[int]`.
  - `auto_mine(order: list[str], seat: int | None, num_teams: int) -> set[str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board.py`:

```python
import json

from ffhelper.board import auto_mine, marks_in_entry_order, my_turns


def test_my_turns_are_the_seats_snake_positions():
    assert my_turns(seat=5, num_teams=12, through_pick=30) == [5, 20, 29]


def test_my_turns_at_the_turn_are_back_to_back():
    # Seat 12 in a 12-team snake picks 12 and 13 with nobody in between. The
    # board's whole thesis -- cost of waiting -- collapses if this is wrong.
    assert my_turns(seat=12, num_teams=12, through_pick=26) == [12, 13]


def test_auto_mine_claims_only_the_seats_own_picks():
    order = [str(i) for i in range(1, 25)]           # picks 1..24, entered in order
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}


def test_auto_mine_with_no_seat_claims_nothing():
    # Degrade, never fabricate: an unset draft_slot must not guess a roster.
    order = [str(i) for i in range(1, 25)]
    assert auto_mine(order, seat=None, num_teams=12) == set()


def test_marks_in_entry_order_excludes_undone_and_taken_back_marks(tmp_path):
    path = tmp_path / "log.jsonl"
    ops = [
        {"op": "mark", "id": "a", "mine": False},
        {"op": "mark", "id": "b", "mine": False},
        {"op": "undo"},                               # takes back b
        {"op": "mark", "id": "c", "mine": False},
        {"op": "mark", "id": "d", "mine": False},
        {"op": "unmark", "id": "d"},
    ]
    path.write_text("".join(json.dumps(o) + "\n" for o in ops))
    assert marks_in_entry_order(path) == ["a", "c"]


def test_a_missed_pick_shifts_attribution_by_one(tmp_path):
    # Recorded deliberately: this is the COST of auto-attribution, and the
    # reason the on-clock banner doubles as a drift detector. If this test ever
    # starts failing, attribution has silently changed behaviour.
    order = [str(i) for i in range(1, 25)]
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}
    assert auto_mine(order[1:], seat=5, num_teams=12) == {"6", "21"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_board.py -k "turns or auto_mine or entry_order or missed" -v`
Expected: FAIL — `ImportError: cannot import name 'auto_mine' from 'ffhelper.board'`

- [ ] **Step 3: Implement**

Add to `ffhelper/board.py`. Merge the new names into the import statements
Task 2 already wrote — do not add a second `from ffhelper.cli import ...` line:

```python
import json                                    # new, top of file

from ffhelper.cli import (                     # add _restore_marks to the existing group
    _claims_overruled_by_feed, _combine_my_roster, _my_roster_from_picks,
    _restore_marks,
)
from ffhelper.value import (                   # add next_pick_number to the existing group
    Row, build_board, detect_run, next_pick_number,
)


def my_turns(seat: int, num_teams: int, through_pick: int) -> list[int]:
    """The pick numbers `seat` owns in a snake draft, up to `through_pick`."""
    turns, pick = [], 0
    while True:
        pick = next_pick_number(pick, seat, num_teams)
        if pick > through_pick:
            return turns
        turns.append(pick)


def marks_in_entry_order(log_path) -> list[str]:
    """Surviving marks in the order they were entered; index+1 is the pick number.

    The order marks were entered is the order players came off the board -- true
    only if every pick was entered, and entered in order. That assumption is what
    seat-based attribution rests on, and it is why the on-clock banner is the
    drift detector: if a pick is missed, the board claims your turn at the wrong
    moment, visibly.

    ponytail: duplicated from `scripts/calibrate.py:picks_from_journal`, which
    cannot be imported (it is a script, not a package module). Upgrade path,
    after 2026-09-06: point calibrate.py at this function.

    ponytail: first mark wins -- a player marked, taken back and re-marked keeps
    his original slot. The common correction (unmark the wrong name, mark the
    right one) touches two different players and is unaffected.
    """
    state, _applied, _skipped = _restore_marks(log_path)
    seq: list[str] = []
    seen: set[str] = set()
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    for line in lines:
        try:
            op = json.loads(line)
        except Exception:                             # noqa: BLE001 - torn final line
            continue
        pid = op.get("id")
        if op.get("op") == "mark" and pid in state.drafted and pid not in seen:
            seen.add(pid)
            seq.append(pid)
    return seq


def auto_mine(order: list[str], seat: int | None, num_teams: int) -> set[str]:
    """Which entered marks belong to `seat`, from pick number alone.

    Replaces the terminal's typed "me " prefix in the web UI. This is what
    Sleeper already does through `draft_slot`; it makes feed-less mode match
    rather than be the exception.

    Degrade, never fabricate: with no configured seat, nothing is claimed.
    """
    if seat is None:
        return set()
    turns = set(my_turns(seat, num_teams, len(order)))
    return {pid for i, pid in enumerate(order, 1) if i in turns}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_board.py -v`
Expected: 10 passed.

- [ ] **Step 5: Verify against a real transcript — ground truth, not a fixture**

`scripts/transcribe.py` records the user's own picks with `mine: true`, derived independently from the results page. That is a ground truth to check attribution against.

```bash
ls .draft/*-transcript.jsonl .draft/*results*.jsonl 2>/dev/null
```

Pick one transcript and run:

```bash
.venv/bin/python - <<'PY'
import json, sys
from pathlib import Path
from ffhelper.board import auto_mine, marks_in_entry_order
from ffhelper.cli import _restore_marks

path = Path(sys.argv[1] if len(sys.argv) > 1 else next(Path(".draft").glob("*results*.jsonl")))
state, _a, _s = _restore_marks(path)
order = marks_in_entry_order(path)
seat = (order.index(sorted(state.mine, key=order.index)[0]) + 1) if state.mine else None
derived = auto_mine(order, seat, 12)
print("transcript seat:", seat, "picks:", len(order))
print("recorded mine :", len(state.mine))
print("derived  mine :", len(derived))
print("agree         :", derived == state.mine)
print("difference    :", sorted(derived ^ state.mine))
PY
```

Expected: `agree: True`. If it disagrees, attribution is wrong — **stop and fix it before the UI is wired to it**, because a wrong roster makes MARG meaningless and does so silently.

- [ ] **Step 6: Verify the tests fail against pre-fix source**

```bash
git stash push -- ffhelper
.venv/bin/python -m pytest tests/test_board.py -k "turns or auto_mine or entry_order" -q
git stash pop
```

- [ ] **Step 7: Add mutations**

Add to the `"ffhelper/board.py"` list in `scripts/mutate.py`:

```python
        ("attribution claims every pick",
         "return {pid for i, pid in enumerate(order, 1) if i in turns}",
         "return set(order)"),
        ("attribution off by one",
         "return {pid for i, pid in enumerate(order, 1) if i in turns}",
         "return {pid for i, pid in enumerate(order, 0) if i in turns}"),
        ("attribution guesses with no seat",
         "    if seat is None:\n        return set()",
         "    if seat is None:\n        seat = 1"),
```

Run: `.venv/bin/python scripts/mutate.py`
Expected: all three KILLED.

- [ ] **Step 8: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: 262 passed.

```bash
git add ffhelper/board.py tests/test_board.py scripts/mutate.py
git commit -m "feat(board): derive my_roster from draft seat and pick number"
```

---

### Task 6: Wire attribution into the board, with the override

End of 3c. After this the board is a working draft tool and everything remaining is presentation.

**Files:**
- Modify: `ffhelper/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `board.auto_mine`, `board.marks_in_entry_order`.
- Produces: `read_state` now folds auto-attributed ids into `manual_mine`; `apply_override(log_path, player_id, mine: bool) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
from ffhelper.app import apply_override


def test_the_seats_own_picks_land_in_my_roster_without_being_typed(tmp_path):
    path = tmp_path / "log.jsonl"
    for i in range(1, 25):                            # picks 1..24, seat 5 owns 5 and 20
        apply_click(path, str(i))
    order = marks_in_entry_order(path)
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}


def test_an_override_marks_a_player_as_yours_explicitly(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_override(path, "42", mine=True)
    state, _applied, _skipped = _restore_marks(path)
    assert state.mine == {"42"}
    assert state.drafted == {"42"}


def test_an_override_can_take_a_claim_back_without_undrafting_the_player(tmp_path):
    # He really is gone -- just not to you. Removing him from `drafted` would
    # put a drafted player back on the board.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_override(path, "42", mine=True)
    apply_override(path, "42", mine=False)
    state, _applied, _skipped = _restore_marks(path)
    assert state.mine == set()
    assert state.drafted == {"42"}
```

Add to the imports at the top of `tests/test_app.py`:

```python
from ffhelper.board import auto_mine, marks_in_entry_order
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py -k override -v`
Expected: FAIL — `ImportError: cannot import name 'apply_override' from 'ffhelper.app'`

- [ ] **Step 3: Implement**

In `ffhelper/app.py`, add the import:

```python
from ffhelper.board import BoardState, auto_mine, board_state, marks_in_entry_order
```

Add `apply_override` beside `apply_click`:

```python
def apply_override(log_path, player_id: str, mine: bool) -> str:
    """Correct attribution for one player, without changing whether he is drafted.

    The only reason to need this is that entry has drifted -- a missed or
    doubled pick shifts every pick number after it -- so it is also the cue to
    re-check the pick count against the platform's own board.
    """
    state, _applied, _skipped = _restore_marks(log_path)
    if mine:
        state.mark(player_id, mine=True)
        return f"{player_id} is yours"
    # unmark then re-mark: he is still drafted, just not by you. Removing him
    # from `drafted` would put a genuinely gone player back on the board.
    state.unmark(player_id)
    state.mark(player_id, mine=False)
    return f"{player_id} is not yours"
```

Change `read_state` to fold in the derived roster:

```python
def read_state(league, tunables, players, settings, feed, has_feed):
    log_path = _draft_log_path(league)
    mark_state, _applied, _skipped = _restore_marks(log_path)
    # Seat-based attribution replaces the terminal's typed "me " prefix. An
    # explicit override (mark_state.mine) always wins over the derived set --
    # it exists precisely for the case where entry has drifted.
    derived = auto_mine(marks_in_entry_order(log_path), league.draft_slot,
                        settings.num_teams)
    manual_mine = mark_state.mine | derived

    picks, stale_seconds = [], None
    try:
        picks = feed.get_picks()
    except Exception as exc:                          # noqa: BLE001 - never fatal
        log.warning("poll failed: %s", exc)
        if has_feed:
            stale_seconds = time.time() - _LAST_OK.get(league.name, time.time())
    else:
        if has_feed:
            _LAST_OK[league.name] = time.time()
            stale_seconds = 0.0
    state = board_state(players, picks, mark_state.drafted, manual_mine,
                        settings, league, tunables)
    return state, stale_seconds
```

Add an override control. In `_layout`, beside the undo button:

```python
        html.Button("toggle 'mine' on selected", id="override", n_clicks=0),
```

and extend the `_write` callback's inputs and body:

```python
        Input("override", "n_clicks"),
```
```python
            elif trigger == "override" and active_cell and rows:
                pid = rows[active_cell["row"]]["id"]
                state, _a, _s = _restore_marks(path)
                status = apply_override(path, pid, mine=pid not in state.mine)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 15 passed.

- [ ] **Step 5: Verify against pre-fix source**

```bash
git stash push -- ffhelper
.venv/bin/python -m pytest tests/test_app.py -k override -q
git stash pop
```

- [ ] **Step 6: Run it against real data**

```bash
.venv/bin/python -m ffhelper.app --league yahoo-mock
```

Click through two full rounds of a 12-team draft (24 clicks). Confirm:

- exactly the two players at your seat's snake positions appear in your roster
- the on-clock banner says `PICK n IS YOURS` at the right moments — this is the drift detector, and it must be checked, not assumed
- the override button flips a player in and out of your roster and never puts him back on the board

- [ ] **Step 7: Run the full suite and commit**

Run: `.venv/bin/python -m pytest -q`
Expected: 265 passed.

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): seat-based roster attribution with an explicit override"
```

---

> **CUT LINE.** Everything above is a working draft tool. If Sept 1 gets close, stop here — Tasks 7 and 8 are presentation.

---

### Task 7: Tier bands, position filter, search

**Files:**
- Modify: `ffhelper/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `board_rows`.
- Produces: `tier_styles(rows: list[dict]) -> list[dict]` — `style_data_conditional` entries banding rows by tier; `filter_rows(rows: list[dict], position: str, query: str) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
from ffhelper.app import filter_rows, tier_styles


def test_tier_styles_band_adjacent_tiers_differently():
    # TODO.md section 15: no position ranks its own top 12 better than ~+0.35
    # Spearman. The gap between tiers is real; the order inside one is close to
    # noise. The band is what makes same-tier players read as interchangeable.
    rows = [
        {"rank": 1, "tier": 1}, {"rank": 2, "tier": 1},
        {"rank": 3, "tier": 2}, {"rank": 4, "tier": 2},
    ]
    styles = tier_styles(rows)
    colours = [s["backgroundColor"] for s in styles]
    assert len(styles) == 4
    assert colours[0] == colours[1]
    assert colours[2] == colours[3]
    assert colours[0] != colours[2]


def test_filter_rows_by_position():
    rows = [{"player": "A", "pos": "QB"}, {"player": "B", "pos": "RB"}]
    assert filter_rows(rows, "RB", "") == [{"player": "B", "pos": "RB"}]


def test_filter_rows_all_is_a_passthrough():
    rows = [{"player": "A", "pos": "QB"}, {"player": "B", "pos": "RB"}]
    assert filter_rows(rows, "ALL", "") == rows


def test_search_is_case_insensitive_and_partial():
    rows = [{"player": "Ja'Marr Chase", "pos": "WR"}, {"player": "Bijan Robinson", "pos": "RB"}]
    assert filter_rows(rows, "ALL", "robin") == [rows[1]]
    assert filter_rows(rows, "ALL", "CHASE") == [rows[0]]


def test_search_and_position_filter_compose():
    rows = [{"player": "Bijan Robinson", "pos": "RB"},
            {"player": "Brian Robinson", "pos": "RB"},
            {"player": "Demario Douglas", "pos": "WR"}]
    assert filter_rows(rows, "WR", "robin") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py -k "tier_styles or filter_rows or search" -v`
Expected: FAIL — `ImportError: cannot import name 'tier_styles'`

- [ ] **Step 3: Implement**

Add to `ffhelper/app.py`:

```python
# ponytail: bands are alternating background colours, not "-- TIER 2 --" header
# rows: a DataTable row cannot contain arbitrary markup. Upgrade path is to
# replace the DataTable with a hand-rolled html.Table -- board_rows() returns
# plain dicts specifically so that swap does not touch tested logic.
_BAND_A = "rgba(255,255,255,0)"
_BAND_B = "rgba(127,127,127,0.14)"


def tier_styles(rows: list[dict]) -> list[dict]:
    """One style_data_conditional entry per row, alternating on tier change."""
    styles, band, prev = [], _BAND_A, None
    for r in rows:
        if prev is not None and r["tier"] != prev:
            band = _BAND_B if band == _BAND_A else _BAND_A
        prev = r["tier"]
        styles.append({
            "if": {"row_index": len(styles)},
            "backgroundColor": band,
        })
    return styles


def filter_rows(rows: list[dict], position: str, query: str) -> list[dict]:
    """Narrow the displayed rows. Presentation only -- never changes the board."""
    out = rows
    if position and position != "ALL":
        out = [r for r in out if r["pos"] == position]
    q = (query or "").strip().lower()
    if q:
        out = [r for r in out if q in r["player"].lower()]
    return out
```

In `_layout`, add above the DataTable:

```python
        dcc.RadioItems(id="pos", value="ALL", inline=True,
                       options=["ALL", "QB", "RB", "WR", "TE", "K", "DEF"]),
        dcc.Input(id="search", type="text", placeholder="search name", debounce=False),
```

In `_register_callbacks`, extend the `_refresh` callback: add
`Output("board", "style_data_conditional")`, add `Input("pos", "value")` and
`Input("search", "value")`, and change the return:

```python
        rows = filter_rows(
            board_rows(state, limit=200,
                       divergence_flag_slots=tunables.divergence_flag_slots),
            position, query,
        )[:40]
        return (
            rows, tier_styles(rows),
            "\n".join(banner_lines(state, stale, players)),
            clock_line(state, league, settings.num_teams),
        )
```

Note the limit moves to 200 before filtering and 40 after: filtering a 40-row slice would show at most a handful of kickers when `K` is selected.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 20 passed.

- [ ] **Step 5: Verify against pre-fix source**

```bash
git stash push -- ffhelper
.venv/bin/python -m pytest tests/test_app.py -k "tier_styles or filter_rows" -q
git stash pop
```

- [ ] **Step 6: Run it against real data**

```bash
.venv/bin/python -m ffhelper.app --league sleeper-main
```

Check the board at picks 1, 27, 61 and 140 (mark players in to advance) against a terminal running the same league. Confirm tier bands change where the `TIER` column changes, and that selecting `TE` shows a full screen of tight ends rather than three.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): tier bands, position filter and name search"
```

---

### Task 8: The roster panel

**Files:**
- Modify: `ffhelper/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `BoardState.my_roster`, `LeagueSettings.roster_slots`.
- Produces: `roster_slots_view(my_roster: list[Player], roster_slots: dict[str, int]) -> list[tuple[str, str | None]]` — one `(slot_label, player_name_or_None)` per starting slot, in roster order, then bench.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
from ffhelper.app import roster_slots_view


def _p(name, pos):
    return Player(sleeper_id=name, name=name, position=pos, team="KC", proj_pts=100.0)


def test_empty_slots_are_shown_as_empty():
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
    view = roster_slots_view([_p("Allen", "QB")], slots)
    assert ("QB", "Allen") in view
    assert view.count(("RB", None)) == 2
    assert sum(1 for _label, filled in view if filled is None) == 9


def test_flex_takes_an_overflow_rb_but_never_a_quarterback():
    # value.lineup_value would start a QB at FLEX if its guard were dropped --
    # a real mutation-testing find. The picture must not disagree with MARG.
    slots = {"QB": 1, "RB": 2, "FLEX": 1}
    view = roster_slots_view(
        [_p("Allen", "QB"), _p("Purdy", "QB"),
         _p("Gibbs", "RB"), _p("Robinson", "RB"), _p("Hall", "RB")],
        slots,
    )
    assert ("FLEX", "Hall") in view
    assert ("FLEX", "Purdy") not in view


def test_slot_order_follows_the_configured_roster():
    slots = {"QB": 1, "RB": 2, "WR": 2}
    labels = [label for label, _filled in roster_slots_view([], slots)]
    assert labels == ["QB", "RB", "RB", "WR", "WR"]
```

Add `Player` to the imports at the top of `tests/test_app.py` if not already present.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app.py -k roster_slots_view -v`
Expected: FAIL — `ImportError: cannot import name 'roster_slots_view'`

- [ ] **Step 3: Implement**

Add to `ffhelper/app.py`:

```python
# Which positions each slot can start. Must match value.lineup_value's rule, or
# the panel and the MARG column will disagree about the same roster.
_FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def roster_slots_view(
    my_roster: list[Player], roster_slots: dict[str, int],
) -> list[tuple[str, str | None]]:
    """Starting slots in roster order, each filled or explicitly empty.

    Greedy by projected points within a position, FLEX last from whatever is
    left -- the same shape lineup_value uses, so the picture cannot claim a
    lineup MARG does not.
    """
    remaining = sorted(my_roster, key=lambda p: -p.proj_pts)
    view: list[tuple[str, str | None]] = []
    for slot, count in roster_slots.items():
        if slot == "FLEX":
            continue                                  # filled last, from leftovers
        for _ in range(count):
            match = next((p for p in remaining if p.position == slot), None)
            if match is not None:
                remaining.remove(match)
            view.append((slot, match.name if match else None))
    for _ in range(roster_slots.get("FLEX", 0)):
        match = next((p for p in remaining if p.position in _FLEX_ELIGIBLE), None)
        if match is not None:
            remaining.remove(match)
        view.append(("FLEX", match.name if match else None))
    return view
```

In `_layout`, add beside the board:

```python
        html.Pre(id="roster"),
```

In `_refresh`, add `Output("roster", "children")` and return:

```python
            "\n".join(f"{label:<5} {filled or '(empty)'}"
                      for label, filled in roster_slots_view(
                          state.my_roster, settings.roster_slots)),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: 23 passed.

- [ ] **Step 5: Verify against pre-fix source**

```bash
git stash push -- ffhelper
.venv/bin/python -m pytest tests/test_app.py -k roster_slots_view -q
git stash pop
```

- [ ] **Step 6: Run it against real data**

Draft a full starting lineup in `yahoo-mock`. Confirm the panel fills in the order you drafted, that FLEX takes the overflow RB/WR/TE and never a QB or kicker, and that once every slot is full the `STARTING LINEUP FULL` bench banner appears — the two must agree.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/app.py tests/test_app.py
git commit -m "feat(app): starting-lineup roster panel with explicit empty slots"
```

---

### Task 9: Rehearsal — the Task 13 equivalent (NEEDS THE USER)

Not code. This is the step that has found nine defects a green suite passed over, and it is the reason the Dash board can be trusted on Sept 1.

**Files:**
- Modify: `CLAUDE.md`, `TODO.md` (session log and outstanding work)

- [ ] **Step 1: Replay all three transcribed mocks offline**

```bash
ls .draft/*.jsonl
```

For each transcript, point the Dash board at it and step through. Confirm at minimum: bench-only mode appears once starters fill, the on-clock banner fires at exactly the seat's snake positions, and a claim overrule raises its banner.

- [ ] **Step 2: One live Sleeper mock — the feed path, nothing typed**

Create a mock draft in the Sleeper app, add a temporary `[[league]]` entry pointing at its `draft_id`, then:

```bash
.venv/bin/python -m ffhelper.cli preflight --league mock
.venv/bin/python -m ffhelper.app --league mock
```

Watch for: drafted players leaving the board, VONA reordering as position runs develop, survival falling as your pick approaches, and the STALE banner appearing if wifi is cut for ~20s and clearing when it returns.

- [ ] **Step 3: One live Yahoo mock — click entry under a real clock**

```bash
.venv/bin/python -m ffhelper.app --league yahoo-mock
```

Every pick entered by clicking. This is the Sept 1 interface. Note the lobby clock is ~30s a pick against the real draft's 90s+, so falling behind here is not a failure of the real test — but record how far behind you get.

- [ ] **Step 4: Time the ctrl-C → CLI handover**

Mid-draft, ctrl-C the Dash app and run:

```bash
.venv/bin/python -m ffhelper.cli run --league yahoo-mock
```

Record the elapsed time and confirm the restore banner reports every mark. The fallback has to be a rehearsed motion, not a plan.

- [ ] **Step 5: Record findings**

Update `CLAUDE.md`'s session log and `TODO.md` with: every defect found, the test count and mutation count, and — for any measurement — what produced it and how many samples it rests on. A vivid result from one mock is a hypothesis, not a finding.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md TODO.md
git commit -m "docs: record Phase 3 rehearsal findings"
```

---

## Deferred (recorded so they are not re-litigated)

- **`board.py` adoption by `cli.py`** — after 2026-09-06. Delete the derivation block from `_render_tick`, call `board_state`, move the three `_`-prefixed helpers into `board.py`, and point `scripts/calibrate.py` at `marks_in_entry_order`. `tests/test_board_agreement.py` is the proof it is a no-op.
- **Season-mode pages** (start/sit, waiver board, trade finder) — all three need Phase 4 data. They are why `use_pages=True` is set from the first line; they are not built here.
- **In-browser config editing** — needs a UI-owned overlay rather than rewriting the human-maintained TOML, and must re-run `preflight` and show the result.
- **Hosting** — needs auth, secrets storage, and a persistent volume (the journal is the database, and most cheap PaaS filesystems are ephemeral). `server` is exposed at module level so nothing has to be retrofitted.
- **`me` removal from the CLI** — after Sept 6, if at all.
