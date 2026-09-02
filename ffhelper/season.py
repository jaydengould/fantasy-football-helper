"""Season mode: what to start, and who to add. PURE -- no I/O, no network.

Same rule as `value.py`, for the same reason: this is where the logic worth
testing lives, and it must test without a network. If something here wants to
fetch, the design is wrong -- put the loader in `data.py`.
"""
from dataclasses import dataclass, replace

from ffhelper.data import Player, score_stats
from ffhelper.value import FLEX_ELIGIBLE, optimal_lineup


def weekly_points(projections: list[dict], scoring: dict[str, float]) -> dict[str, float]:
    """Score one week's projection rows under this league's rules.

    A row with no stats is OMITTED rather than scored 0.0. Absent means "no
    projection this week" and the caller can say so; 0.0 is a claim that the
    player will score nothing, which is a number the source never supplied.

    Real Sleeper rows for unprojected players carry only descriptive fields
    (adp_dd_ppr, etc). A row counts as projected only if stats contains at least
    one key that the league scores.
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
