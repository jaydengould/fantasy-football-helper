"""Board derivation, shared by the web UI and (one day) the terminal.

ponytail: `board_state` is a COPY of the derivation block in
`cli._render_tick`, not an extraction. `tests/test_board_agreement.py` proves
the two agree, and is also the proof that the extraction is a no-op.

The 2026 draft freeze that originally justified the copy lifted 2026-09-01, and
the fold was then deliberately NOT taken. Two reasons, both current:

  1. It buys nothing functional. Season mode adds new commands and never touches
     this derivation, so the fold is pure debt repayment on the live draft path
     -- which may be exercised again at short notice by a mock or a fill-in
     draft.
  2. The import cycle is the real cost, not the duplication. This module imports
     four `_`-prefixed helpers from `cli`, and `_restore_marks` builds a
     `MarkDrafted`, so a clean one-way fold means moving the journal layer into
     its own module rather than moving three functions.

UPGRADE PATH, when something actually needs it: extract `MarkDrafted` and the
journal helpers into `ffhelper/marks.py`, let both `cli` and `board` import from
there, then delete the derivation block from `_render_tick` and call
`board_state`. Do it when a board change would otherwise have to be written
twice -- Phase 3.7 is the likely trigger.
"""
import json
from dataclasses import dataclass

from ffhelper.cli import (
    _claims_overruled_by_feed, _combine_my_roster, _my_roster_from_picks,
    _restore_marks,
)
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper.value import Row, build_board, detect_run, next_pick_number


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


def my_turns(seat: int, num_teams: int, through_pick: int) -> list[int]:
    """The pick numbers `seat` owns in a snake draft, up to `through_pick`.

    ponytail: bounded at `through_pick + 1` iterations rather than `while True`.
    This is the first caller that feeds `next_pick_number`'s own return value
    back in as its next `current_pick` -- every other call site (cli.py,
    app.py, calibrate.py) asks once per tick. That makes this loop the one
    place a broken "strictly after" contract in the frozen `value.py` turns
    into a hang instead of a fast test failure: found by mutate.py's existing
    "snake next-pick boundary" mutation, which crashed the whole script with
    an uncaught subprocess timeout before it ever reached this file's own
    mutations.
    """
    turns, pick = [], 0
    for _ in range(through_pick + 1):
        pick = next_pick_number(pick, seat, num_teams)
        if pick > through_pick:
            return turns
        turns.append(pick)
    raise RuntimeError("next_pick_number did not advance strictly")


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


def explicit_not_mine(log_path) -> set[str]:
    """Ids the user explicitly said are NOT theirs, via `apply_override(mine=False)`.

    That call always writes an `unmark` immediately followed by a `mark` with
    `mine: false` for the same id -- no other path produces that exact pair (a
    plain click is a single `mark`; `undo` carries no id at all). Scanning for
    it is how the statement survives `read_state` running again: `auto_mine`
    recomputes the derived set from pick POSITION on every tick, with no
    memory of the override, so without this the correction would silently
    revert within one poll interval.

    Tracks each id's own most recent relevant op, not global order --
    interleaved ops for OTHER ids never reset the pattern. A later plain claim
    (`mark ... mine: true`) for the same id overwrites it out of the result,
    because the user changed their mind back.
    """
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return set()
    last: dict[str, str] = {}          # id -> "unmark" / "mine" / "not_mine" / "mark"
    for line in lines:
        try:
            op = json.loads(line)
        except Exception:              # noqa: BLE001 - torn final line
            continue
        pid = op.get("id")
        if pid is None:
            continue
        if op.get("op") == "unmark":
            last[pid] = "unmark"
        elif op.get("op") == "mark":
            if op.get("mine"):
                last[pid] = "mine"
            elif last.get(pid) == "unmark":
                last[pid] = "not_mine"
            else:
                last[pid] = "mark"     # a plain draft click -- not a statement
    return {pid for pid, state in last.items() if state == "not_mine"}


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
