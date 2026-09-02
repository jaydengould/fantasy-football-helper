"""Season mode: what to start, and who to add. PURE -- no I/O, no network.

Same rule as `value.py`, for the same reason: this is where the logic worth
testing lives, and it must test without a network. If something here wants to
fetch, the design is wrong -- put the loader in `data.py`.
"""
from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import fmean

from ffhelper.data import Player, score_stats
from ffhelper.value import FLEX_ELIGIBLE, lineup_value, optimal_lineup


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


# The 2026 regular season. Week 18 is the last one a fantasy roster can score
# in; playoffs are league-configured and this tool does not model them.
LAST_REGULAR_WEEK = 18


def free_agent_pool(
    players: dict[str, Player], rosters: list[dict], projected_ids: set[str],
) -> list[Player]:
    """Everyone not on ANY roster who carries a projection in the horizon.

    Both halves are load-bearing. Subtracting only YOUR roster offers you
    players another team owns. Skipping the projection filter leaves 3051 of
    the 3231-player pool, nearly all retired or on a practice squad.
    """
    rostered: set[str] = set()
    for r in rosters:
        rostered |= set(r.get("players") or [])
    return [p for pid, p in players.items()
            if pid not in rostered and pid in projected_ids]


def waiver_position(rosters: list[dict], roster_id: int) -> tuple[int | None, int]:
    """(your rolling-waiver position, number of teams).

    The league is NOT FAAB -- that claim's entire provenance was `waiver_budget:
    100`, a field Sleeper returns by default whether or not bidding is on. It is
    rolling priority, so there is no bid to derive: position is a consumable
    ordering, not a currency.

    Position is None when the payload does not carry one; the caller drops the
    line rather than printing a 1.
    """
    mine = next((r for r in rosters if r.get("roster_id") == roster_id), None)
    pos = (mine or {}).get("settings", {}).get("waiver_position")
    return pos, len(rosters)


def weekly_points(projections: list[dict], scoring: dict[str, float]) -> dict[str, float]:
    """Score one week's projection rows under this league's rules.

    A row with no stats is OMITTED rather than scored 0.0. Absent means "no
    projection this week" and the caller can say so; 0.0 is a claim that the
    player will score nothing, which is a number the source never supplied.

    Real Sleeper rows for unprojected players carry only descriptive fields
    (adp_dd_ppr, etc). A row counts as projected only if stats contains at least
    one key that the league scores.

    That guard rests on an assumption worth naming: it is safe only because
    Sleeper's `scoring_settings` contains no DESCRIPTIVE keys (adp_dd_ppr and
    friends), just scored stat keys. A league whose scoring ever added a
    descriptive key would silently reclassify every row as projected, and this
    function's whole reason for existing -- keeping a genuine "no projection"
    distinct from a projection of zero -- would go quiet with it.
    """
    out: dict[str, float] = {}
    for row in projections:
        pid, stats = row.get("player_id"), row.get("stats")
        if not pid or not stats:
            continue
        if not any(k in scoring for k in stats):
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

    Players absent from `weekly` are assigned proj_pts=0.0 for sorting (correctly
    benches them), but this 0.0 is a sort value, not a projection. Caller must
    track which players actually received a projection via `set(weekly)` and pass
    that to start_sit's `projected_ids` to distinguish genuine 0.0 from absent.
    """
    return [replace(p, proj_pts=weekly.get(p.sleeper_id, 0.0)) for p in roster]


def horizon_total(
    roster: list[Player], roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]],
) -> float:
    """Points the optimal lineup scores across every week in the horizon."""
    return sum(lineup_value(with_weekly_points(roster, wk), roster_slots)
               for wk in weekly_by_week.values())


def roster_upgrade(
    roster: list[Player], candidate: Player, roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]], drop_tie_points: float = 0.5,
) -> tuple[float, Player, int]:
    """(gain, drop, weeks_started) for adding `candidate` at the cost of one cut.

    The roster is full, so an add IS an add-and-drop. An add-only number
    overstates every candidate by the value of whoever you would have cut, and
    then no two candidates are comparable.

    THE DROP IS CHOSEN ON THE WHOLE HORIZON, never one week. A one-week horizon
    happily offers to cut your backup quarterback for 1.2 points of streaming
    defense -- right arithmetic, ruinous advice.

    Ties are real and must not be broken by list order: in the real week-1 run
    five drops tied EXACTLY, and naming an arbitrary one of them is fabrication.
    Among drops within `drop_tie_points` of the best, the one with the fewest
    projected points of his own is taken, and the caller prints that rule.
    """
    base = horizon_total(roster, roster_slots, weekly_by_week)
    own = {p.sleeper_id: sum(wk.get(p.sleeper_id, 0.0) for wk in weekly_by_week.values())
           for p in roster}

    scored: list[tuple[float, Player]] = []
    for i, dropped in enumerate(roster):
        trial = [*roster[:i], *roster[i + 1:], candidate]
        scored.append((horizon_total(trial, roster_slots, weekly_by_week) - base, dropped))

    best_gain = max(g for g, _ in scored)
    tied = [(own[p.sleeper_id], g, p) for g, p in scored
            if g >= best_gain - drop_tie_points]
    # The id is the final tie-break so the answer is deterministic across runs:
    # a drop name that changes when nothing changed is a board nobody can trust.
    _, gain, drop = min(tied, key=lambda t: (t[0], t[2].sleeper_id))

    kept = [p for p in roster if p.sleeper_id != drop.sleeper_id] + [candidate]
    weeks_started = sum(
        1 for wk in weekly_by_week.values()
        if candidate.sleeper_id in wk
        and any(p is not None and p.sleeper_id == candidate.sleeper_id
                for _, p in optimal_lineup(with_weekly_points(kept, wk), roster_slots))
    )
    return gain, drop, weeks_started


def opponents(projections: list[dict]) -> dict[str, str]:
    """Who each player faces this week, from the projection rows already fetched.

    Sleeper's weekly projection row carries `opponent` alongside the stat line,
    so the upcoming schedule needs no second endpoint and no schedule loader.
    A row without one (a bye) is simply absent, which is what makes the caller
    show no matchup rather than a zero.
    """
    return {row["player_id"]: row["opponent"] for row in projections
            if row.get("player_id") and row.get("opponent")}


@dataclass(frozen=True)
class MatchupRates:
    """Fantasy points each defense has allowed, per game, per position.

    Under THIS league's scoring -- computed from weekly actuals through
    `score_stats`, never a generic "points against" from someone else's
    rulebook. `games` is how many games back each number rests on, which is
    what the shrinkage in `matchup_factor` needs and the reason it is kept.
    """
    allowed: dict[tuple[str, str], float]     # (defense, position) -> points per game
    games: dict[tuple[str, str], int]
    league_mean: dict[str, float]             # position -> mean across defenses


def points_allowed(
    actuals: list[dict], players: dict[str, Player], scoring: dict[str, float],
) -> MatchupRates:
    """Aggregate completed weeks into per-defense, per-position rates.

    One row is one player's game, and `opponent` is the defense he faced -- so
    summing every RB row that faced DEN gives what DEN's defense allowed to
    running backs, and the distinct weeks in those rows give how many games
    that rests on. Counting weeks rather than dividing by a schedule length is
    what makes byes and a mid-season run of missing rows harmless.

    A row whose player is not in the pool is skipped rather than guessed at:
    position is the grouping key, and an unknown position cannot be grouped.
    """
    totals: dict[tuple[str, str], float] = defaultdict(float)
    weeks: dict[tuple[str, str], set] = defaultdict(set)
    for row in actuals:
        pid, stats, opp, wk = (row.get("player_id"), row.get("stats"),
                               row.get("opponent"), row.get("week"))
        player = players.get(pid) if pid else None
        if not stats or not opp or player is None or wk is None:
            continue
        key = (opp, player.position)
        totals[key] += score_stats(stats, scoring)
        weeks[key].add(wk)

    allowed = {k: totals[k] / len(weeks[k]) for k in totals}
    games = {k: len(weeks[k]) for k in totals}
    by_pos: dict[str, list[float]] = defaultdict(list)
    for (_, pos), rate in allowed.items():
        by_pos[pos].append(rate)
    return MatchupRates(allowed=allowed, games=games,
                        league_mean={pos: fmean(v) for pos, v in by_pos.items()})


def matchup_factor(
    rates: MatchupRates, defense: str, position: str, shrink_k: float,
) -> float:
    """How much a position's points scale against this defense. 1.0 is neutral.

    Shrunk toward the league mean by `n / (n + shrink_k)`, where n is the games
    the defense has played. **Week 1 has no completed games at all, so n is 0,
    the weight is 0, and the factor is exactly 1.0** -- the honest adjustment
    when there is no data is none. After two games a raw points-allowed number
    is mostly noise, and over-reacting to it is the commonest fantasy error
    this tool could automate; `shrink_k` is what stops it, and it is a measured
    tunable rather than a taste (see `scripts/backtest_weekly.py`).

    Returns 1.0 for an unknown defense or position rather than raising: a
    matchup we cannot compute must remove the column, never invent a number.
    """
    mean = rates.league_mean.get(position)
    n = rates.games.get((defense, position), 0)
    if not mean or not n:
        return 1.0
    weight = n / (n + shrink_k)
    return 1.0 + weight * (rates.allowed[(defense, position)] / mean - 1.0)


def matchup_deltas(
    roster: list[Player], opponent_by_id: dict[str, str], rates: MatchupRates,
    projected_ids: set[str], shrink_k: float,
) -> dict[str, float]:
    """Points the matchup is worth to each player, as a delta on his projection.

    A DELTA, deliberately, not an adjusted total: the spec's third guard is
    that this shows as its own column and is never folded silently into the
    projection, and a delta cannot be mistaken for the projection itself.

    Only projected players get an entry. An unprojected player's `proj_pts` is
    the 0.0 SORT value `with_weekly_points` invented, and multiplying it would
    produce a 0.0 adjustment that reads in the snapshot table as "computed, and
    it came to nothing" -- the fabrication `snapshot_rows` exists to avoid.
    """
    out: dict[str, float] = {}
    for p in roster:
        if p.sleeper_id not in projected_ids:
            continue
        opp = opponent_by_id.get(p.sleeper_id)
        if not opp:
            continue
        factor = matchup_factor(rates, opp, p.position, shrink_k)
        out[p.sleeper_id] = p.proj_pts * (factor - 1.0)
    return out


@dataclass(frozen=True)
class MatchupNote:
    """Where one opponent ranks in points allowed to one position. CONTEXT ONLY.

    `rank` 1 is the STINGIEST defense, so a high rank is a soft matchup, and
    `label` says which end it is so nobody has to remember the direction.
    """
    defense: str
    position: str
    rank: int
    of: int
    label: str        # "tough" | "mid" | "soft"
    games: int


def matchup_notes(
    roster: list[Player], opponent_by_id: dict[str, str], rates: MatchupRates,
    min_games: int = 3,
) -> dict[str, MatchupNote]:
    """Rank each player's opponent against his position. A FACT, not a forecast.

    This exists instead of an adjustment, and the difference is the whole point.
    `scripts/backtest_weekly.py` scored the adjustment on 2024 and 2025 and it
    LOST at every position and every shrinkage level, so no number here touches
    a projection, a sort key, or the snapshot's `matchup` column. What it states
    is true and checkable -- what this defense has given up so far -- and the
    reader does the rest.

    Ranked among defenses with at least `min_games` games at that position, and
    silent below that: a rank built on one or two games is noise, and the early
    season is exactly when people over-react to it. Week 1 has no completed
    games at all, so this returns nothing, which is the honest output.

    Terciles rather than a raw number alone because a rank of 14 versus 19 is a
    distinction the underlying data cannot support -- the split-half stability
    of these rates flips sign between seasons.
    """
    eligible = sorted(
        (k for k, n in rates.games.items() if n >= min_games),
        key=lambda k: rates.allowed[k],
    )
    by_pos: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in eligible:
        by_pos[key[1]].append(key)

    ranked: dict[tuple[str, str], MatchupNote] = {}
    for pos, keys in by_pos.items():
        n = len(keys)
        for i, key in enumerate(keys):
            third = n / 3
            label = "tough" if i < third else ("soft" if i >= n - third else "mid")
            ranked[key] = MatchupNote(defense=key[0], position=pos, rank=i + 1,
                                      of=n, label=label, games=rates.games[key])

    out: dict[str, MatchupNote] = {}
    for p in roster:
        opp = opponent_by_id.get(p.sleeper_id)
        note = ranked.get((opp, p.position)) if opp else None
        if note is not None:
            out[p.sleeper_id] = note
    return out


def with_practice_status(roster: list[Player], practice: dict[str, str]) -> list[Player]:
    """Copies of `roster` carrying nflverse's practice status where it has one.

    Sleeper's own `practice_participation` is empty for every player in the
    league, so this fills a field that already exists rather than adding a
    second one -- which is what lets `_status_note` and `snapshot_rows` pick it
    up with no change at all.

    Sleeper's value wins if it ever starts arriving, since it is updated
    continuously while the nflverse file is the Wednesday-to-Friday report.
    Copies, never mutation, for `with_weekly_points`'s reason: the pool is
    shared, and rewriting it in place is how two views start disagreeing.
    """
    return [replace(p, practice_participation=(
        practice.get(p.gsis_id) if p.gsis_id else None) or p.practice_participation)
        for p in roster]


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
    unprojected: list[Player]


def _eligible(player: Player, slot: str) -> bool:
    """Whether `player` may legally fill `slot`. FLEX is value.py's rule."""
    if slot == "FLEX":
        return player.position in FLEX_ELIGIBLE
    return player.position == slot


def start_sit(
    roster: list[Player], roster_slots: dict[str, int], close_call_points: float = 3.0,
    projected_ids: set[str] | None = None
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

    `projected_ids` is the set of sleeper_ids that received a projection this week.
    Pass `set(weekly)` from weekly_points. Players absent from this set (e.g. on
    exempt list, bye, injured) land in `unprojected` and are excluded from close_calls.
    None means "assume everyone was projected" for backward compatibility.
    """
    lineup = optimal_lineup(roster, roster_slots)
    starting = {p.sleeper_id for _, p in lineup if p is not None}
    bench = sorted((p for p in roster if p.sleeper_id not in starting),
                   key=lambda p: -p.proj_pts)

    unprojected_ids = set() if projected_ids is None else {p.sleeper_id for p in roster if p.sleeper_id not in projected_ids}
    unprojected = [p for p in roster if p.sleeper_id in unprojected_ids]

    calls: list[CloseCall] = []
    for slot, starter in lineup:
        if starter is None:
            continue
        if starter.sleeper_id in unprojected_ids:
            continue
        challenger = next((b for b in bench if _eligible(b, slot) and b.sleeper_id not in unprojected_ids), None)
        if challenger is None:
            continue
        gap = starter.proj_pts - challenger.proj_pts
        if gap <= close_call_points:
            calls.append(CloseCall(slot, starter, challenger, gap))
    return StartSit(lineup=lineup, bench=bench, close_calls=calls, unprojected=unprojected)


def snapshot_rows(
    state: StartSit, projected_ids: set[str], taken_at: str,
) -> list[dict]:
    """One record per rostered player: what was claimed, and what we advised.

    Pure, and deliberately here rather than in `store.py`: deciding what a row
    SAYS is logic and needs testing without a database. `store.py` only knows
    how to write one.

    **`proj_pts` is None for a player with no projection -- never 0.0.**
    `with_weekly_points` assigns 0.0 as a SORT value (it correctly benches
    them), and `projected_ids` exists solely to keep that distinct from a real
    zero. Writing the sort value into the one table built for scoring would
    make an invented number indistinguishable from a measured one months later,
    which is the exact fabrication the 4a review spent a round removing.

    `matchup` is None until 4b ships the adjustment -- not 0.0, which would read
    as "computed, and it came to nothing".
    """
    started = {p.sleeper_id for _, p in state.lineup if p is not None}
    # An unprojected STARTER is in both `lineup` and `unprojected` (a known
    # overlap from the 4a review), so this walks the three lists and dedupes
    # rather than assuming they partition the roster. A duplicate would
    # over-report the count while the primary key quietly wrote one row.
    everyone = ([p for _, p in state.lineup if p is not None]
                + list(state.bench) + list(state.unprojected))

    rows: list[dict] = []
    seen: set[str] = set()
    for p in everyone:
        if p.sleeper_id in seen:
            continue
        seen.add(p.sleeper_id)
        # Absent means absent, not healthy -- the same rule the screen follows.
        # An empty string would later read as "we checked, and he was fine".
        bits = [b for b in (p.injury_status, p.practice_participation) if b]
        rows.append({
            "player_id": p.sleeper_id,
            "taken_at": taken_at,
            "proj_pts": p.proj_pts if p.sleeper_id in projected_ids else None,
            "matchup": None,
            "status": " / ".join(bits) if bits else None,
            "started": 1 if p.sleeper_id in started else 0,
        })
    return rows
