"""Fetch-and-compute for the season commands. The layer between loaders and renderers.

Impure by design: this is where the network lives, which is why `season.py` and
`value.py` can stay pure. Holds no league state, writes no database, imports no
dash -- the CLI's text renderers and the web app's HTML renderers both consume
what these builders return, so the two surfaces cannot disagree about what this
week's advice is. That is `CLAUDE.md`'s rule for `lineup_value()`/`optimal_lineup()`
applied one level up.
"""
from dataclasses import dataclass, field

from ffhelper import cli
from ffhelper import season as season_mod
from ffhelper.cli import _matchup_context, _practice_status, _resolve_my_roster, _resolve_week
from ffhelper.config import League, Tunables

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
    """This week's optimal lineup, fetched and computed. No printing, no DB write.

    Week resolution runs before settings resolution -- reversed from the
    original `_lineup`'s literal order -- so the no-week bail-out returns
    without an unnecessary settings fetch (a network call for Sleeper leagues).
    `_resolve_week` is mocked directly in every existing `_lineup` test that
    exercises the no-week path, so this reorder changes no test's observable
    behaviour.

    `resolve_settings`, `load_players` and `load_weekly_projections` are called
    through the `cli` module object (`cli.resolve_settings(...)`, not a bare
    name from a `from ffhelper.cli import resolve_settings`) because existing
    `_lineup` tests patch `cli.resolve_settings` / `cli.load_players` /
    `cli.load_weekly_projections` on the `cli` module itself -- a plain import
    would bind pipeline's own copy of the name at import time and never see
    those patches. `_resolve_week`, `_resolve_my_roster`, `_practice_status`
    and `_matchup_context` stay as plain names: no existing test patches those
    wrapper functions themselves, only things they call internally (which
    still resolve through `cli.py`'s own globals wherever the wrapper is
    invoked from), and the module-level `pipeline._resolve_week` name is what
    this file's own unit test patches.
    """
    week, season_str, notes, state_week = _resolve_week(week)
    if week is None:
        return LineupView(league_name=league.name, error=NO_WEEK)

    settings = cli.resolve_settings(league)
    players = cli.load_players()
    weekly_rows = cli.load_weekly_projections(season_str, week)
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
