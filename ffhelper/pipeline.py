"""Fetch-and-compute for the season commands. The layer between loaders and renderers.

Impure by design: this is where the network lives, which is why `season.py` and
`value.py` can stay pure. Holds no league state, writes no database, imports no
dash -- the CLI's text renderers and the web app's HTML renderers both consume
what these builders return, so the two surfaces cannot disagree about what this
week's advice is. That is `CLAUDE.md`'s rule for `lineup_value()`/`optimal_lineup()`
applied one level up.

Rule for every name this module borrows from `cli.py`: call it through the
module object (`cli.resolve_settings(...)`), never via a
`from ffhelper.cli import resolve_settings`-style bare import. `cli.py`'s own
tests patch these names as attributes on the `cli` module (`monkeypatch.setattr(cli,
"resolve_settings", ...)`); a bare import binds pipeline's own copy at import
time and silently never sees those patches. A mixed style -- some names
qualified, some not -- is worse than either extreme: the next name added here
copies whichever pattern is already in the file, and only one of the two is
actually patchable, so pick the pattern that always works.
"""
from dataclasses import dataclass, field

from ffhelper import cli
from ffhelper import season as season_mod
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
    """This week's optimal lineup, fetched and computed. No printing, no DB write."""
    settings = cli.resolve_settings(league)
    week, season_str, notes, state_week = cli._resolve_week(week)
    if week is None:
        return LineupView(league_name=league.name, error=NO_WEEK)

    players = cli.load_players()
    # Kept, not discarded after scoring: the same rows carry `opponent`, which
    # is the whole schedule this command needs -- no schedule endpoint, no
    # second fetch.
    weekly_rows = cli.load_weekly_projections(season_str, week)
    weekly = season_mod.weekly_points(weekly_rows, settings.scoring)

    roster, owner, notes_r, _rosters, _rid = cli._resolve_my_roster(league, settings, players)
    notes = notes + notes_r

    # Practice status is the one thing Sleeper's player DB does not carry (zero
    # of 3231 players), so it comes from nflverse and joins on gsis_id through
    # the crosswalk already fetched. It fills the EXISTING field, which is why
    # nothing downstream -- the status note, the snapshot -- needed changing.
    practice, practice_line = cli._practice_status(season_str, week)
    roster = season_mod.with_practice_status(roster, practice)

    # Players with no projection are NOT a "!!" note: see render_lineup. They get
    # their own quiet section, because a stash can carry no number for months.
    scored = season_mod.with_weekly_points(roster, weekly)
    state = season_mod.start_sit(scored, settings.roster_slots,
                                 tunables.close_call_points,
                                 projected_ids=set(weekly))
    matchups, matchup_line = cli._matchup_context(
        season_str, week, players, settings.scoring,
        season_mod.opponents(weekly_rows), roster)

    return LineupView(
        league_name=league.name, state=state, week=week, season_str=season_str,
        state_week=state_week, owner=owner, notes=notes, matchups=matchups,
        matchup_line=matchup_line, practice_line=practice_line,
        projected_ids=set(weekly),
    )
