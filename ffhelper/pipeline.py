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
from math import sqrt
from typing import Callable

from ffhelper import cli
from ffhelper import season as season_mod
from ffhelper import trade as trade_mod
from ffhelper.config import League, Tunables
from ffhelper.data import Player

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


def platform_refusal(league: League, command: str, needs: str) -> str:
    """The one wording for 'this command needs rosters this platform will not serve'.

    Shared by waivers and trades so the two cannot drift into two explanations
    of one limitation -- the same reason `_resolve_my_roster` was extracted.
    """
    return (f"{command} needs {needs}, and {league.platform} has no API access "
            f"-- so this command is Sleeper-only. `lineup` still works for "
            f"{league.name}.")


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
            rows = cli.load_weekly_projections(season_str, w)
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


def build_waivers(league: League, tunables: Tunables, week: int | None = None,
                  limit: int = 10) -> WaiverView:
    """Rank the free-agent pool. No printing, no DB write."""
    if league.platform != "sleeper":
        return WaiverView(league_name=league.name, error=platform_refusal(
            league, "waivers", "every team's roster to know who is free"))

    settings = cli.resolve_settings(league)
    week, season_str, notes, _state_week = cli._resolve_week(week)
    if week is None:
        return WaiverView(league_name=league.name, error=NO_WEEK)

    last_week, cal_note = season_mod.last_scoring_week(settings)
    if cal_note is not None:
        notes.append(cal_note)

    players = cli.load_players()
    roster, owner, notes_r, rosters, rid = cli._resolve_my_roster(league, settings, players)
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
        trending = cli.load_trending("add")
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
        # Same reasoning as `waivers`: the search needs to know what all
        # eleven other rosters hold, and Yahoo serves no rosters at all.
        return TradeView(league_name=league.name, error=platform_refusal(
            league, "trades", "every team's roster to know what they hold"))

    settings = cli.resolve_settings(league)
    week, season_str, notes, _state_week = cli._resolve_week(week)
    if week is None:
        return TradeView(league_name=league.name, error=NO_WEEK)

    deadline = settings.trade_deadline
    if deadline is not None and week > deadline:
        # A legal state, not an error: printing proposals you are not allowed
        # to make is worse than printing none.
        return TradeView(
            league_name=league.name, week=week, deadline_passed=True,
            error=(f"the trade deadline for {league.name} passed in week "
                   f"{deadline} -- no proposal can be made now"))
    if deadline is None:
        notes.append("trade_deadline is unknown for this league -- proceeding "
                     "without one")

    last_week, cal_note = season_mod.last_scoring_week(settings)
    if cal_note is not None:
        notes.append(cal_note)

    players = cli.load_players()
    roster, owner, notes_r, rosters, rid = cli._resolve_my_roster(league, settings, players)
    notes += notes_r
    if not roster:
        return TradeView(league_name=league.name, notes=notes,
                         error="no roster resolved, so there is nothing to "
                               "trade -- " + "; ".join(notes))

    weekly_by_week, failed = _horizon(season_str, week, last_week, settings)
    if not weekly_by_week:
        return TradeView(league_name=league.name, notes=notes,
                         error="no weekly projections could be fetched -- "
                               "nothing can be ranked")
    if failed:
        notes.append(_horizon_note(failed, weekly_by_week, week, last_week, "horizon"))

    weights = season_mod.week_weights(settings, weekly_by_week, tunables.playoff_weight)
    floor = tunables.close_call_points * sqrt(season_mod.effective_weeks(weekly_by_week, weights))

    pin: Player | None = None
    if player:
        matches = cli.find_players(players, player)
        if not matches:
            return TradeView(league_name=league.name, notes=notes,
                             error=f"no player matches '{player}'")
        if len(matches) > 1:
            # Never guess -- Bijan and Brian Robinson are both ATL RBs, and
            # picking one silently would search for a trade nobody asked for.
            return TradeView(
                league_name=league.name, notes=notes,
                error=f"'{player}' is ambiguous -- matches: "
                      + ", ".join(f"{p.name} ({p.position} {p.team})" for p in matches))
        pin = matches[0]

    try:
        users = {u["user_id"]: u.get("display_name")
                 for u in cli.load_league_users(league.league_id)}
    except Exception as exc:                          # noqa: BLE001 - degrade, never fabricate
        # The exact sibling a previous fix wave missed on the happy path: this
        # is the last unguarded fetch, and the cheapest thing to lose is a name.
        users = {}
        notes.append(f"could not reach Sleeper's league users endpoint ({exc}) -- "
                     f"opponent names are unavailable")
    names = {r.get("roster_id"): users.get(r.get("owner_id"))
                                 or f"roster {r.get('roster_id')}"
             for r in rosters}

    best: list[trade_mod.Proposal] = []
    # ponytail: the full sweep is ~330s (11 opponents x three shapes) because
    # 2-for-1 searches the counterparty's forced cut. Accepted: a weekly
    # one-shot command may be slow, and the alternative is pruning, which was
    # measured dropping 22 of 49 real trades. If this ever needs to be fast,
    # memoise horizon_total on a frozenset of player ids -- do NOT prefilter.
    for r in rosters:
        opp_rid = r.get("roster_id")
        if opp_rid is None or opp_rid == rid:
            continue
        their_ids = r.get("players") or []
        theirs = [players[i] for i in their_ids if i in players]
        missing = [i for i in their_ids if i not in players]
        if missing:
            # Same degradation `_resolve_my_roster` already prints for MY
            # roster -- an opponent roster shortened by an unresolvable id
            # understates their baseline and can make a trade look better for
            # them than it is.
            notes.append(f"{len(missing)} of {names[opp_rid]}'s rostered players are "
                         f"not in the player pool: {', '.join(missing)}")
        if progress:
            progress(f"  scanning {names[opp_rid]}...")
        options = trade_mod.trade_options(roster, theirs, opp_rid, settings.roster_slots,
                                          weekly_by_week, floor, weights, pin)
        if pin is not None:
            best.extend(options)
        elif options:
            best.append(max(options, key=lambda p: p.gain_me))

    if pin is not None:
        mine = any(p.sleeper_id == pin.sleeper_id for p in roster)
        best.sort(key=lambda p: -p.gain_me if mine else -p.gain_them)
        # Unlike Mode 1 (one row per opponent, bounded by construction), a
        # pin enumerates every qualifying shape against every opponent --
        # ~1,695 per opponent at real scale. The spec gives Mode 2 no
        # collapse rule of its own, so cap rather than invent a diversity
        # heuristic.
        best = best[:limit]
    else:
        best.sort(key=lambda p: -p.gain_me)

    return TradeView(league_name=league.name, best=best, week=week, owner=owner,
                     names=names, notes=notes, weeks_scored=len(weekly_by_week),
                     pinned=pin)
