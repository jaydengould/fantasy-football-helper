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
