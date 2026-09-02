"""Season mode: what to start, and who to add. PURE -- no I/O, no network.

Same rule as `value.py`, for the same reason: this is where the logic worth
testing lives, and it must test without a network. If something here wants to
fetch, the design is wrong -- put the loader in `data.py`.
"""
from dataclasses import dataclass, replace

from ffhelper.data import Player, score_stats


def weekly_points(projections: list[dict], scoring: dict[str, float]) -> dict[str, float]:
    """Score one week's projection rows under this league's rules.

    A row with no stats is OMITTED rather than scored 0.0. Absent means "no
    projection this week" and the caller can say so; 0.0 is a claim that the
    player will score nothing, which is a number the source never supplied.
    """
    out: dict[str, float] = {}
    for row in projections:
        pid, stats = row.get("player_id"), row.get("stats")
        if not pid or not stats:
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
    """
    return [replace(p, proj_pts=weekly.get(p.sleeper_id, 0.0)) for p in roster]
