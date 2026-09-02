"""Season mode: what to start, and who to add. PURE -- no I/O, no network.

Same rule as `value.py`, for the same reason: this is where the logic worth
testing lives, and it must test without a network. If something here wants to
fetch, the design is wrong -- put the loader in `data.py`.
"""
from dataclasses import dataclass, replace

from ffhelper.data import Player, score_stats
from ffhelper.value import FLEX_ELIGIBLE, optimal_lineup


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
