"""PURE ranking engine. No I/O, no network, no module-level mutable state.

Everything here is a function of its arguments, which is what makes the whole
board testable without touching a network.
"""
import statistics
from statistics import NormalDist

from ffhelper.data import Player


def replacement_ranks(
    roster_slots: dict[str, int], num_teams: int, flex_share: dict[str, float]
) -> dict[str, int]:
    """How deep the league drafts each position before value hits baseline."""
    flex_slots = roster_slots.get("FLEX", 0)
    ranks: dict[str, int] = {}
    for pos, starters in roster_slots.items():
        if pos == "FLEX":
            continue
        share = flex_share.get(pos, 0.0)
        ranks[pos] = round(num_teams * (starters + share * flex_slots))
    return ranks


def replacement_points(players: list[Player], ranks: dict[str, int]) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos, rank in ranks.items():
        pool = sorted(
            (p.proj_pts for p in players if p.position == pos), reverse=True
        )
        if not pool:
            out[pos] = 0.0
        else:
            out[pos] = pool[min(rank, len(pool)) - 1]
    return out


def vbd(players: list[Player], repl: dict[str, float]) -> dict[str, float]:
    return {p.sleeper_id: p.proj_pts - repl.get(p.position, 0.0) for p in players}


def assign_tiers(
    players: list[Player], scores: dict[str, float], sigma: float
) -> dict[str, int]:
    """Break a tier when the gap to the next player exceeds sigma * stdev(gaps).

    The stdev is computed only over draftable players (score > 0, i.e. above
    replacement) -- the below-replacement tail is full of near-zero gaps that
    would drag the stdev down and swallow every real gap at the top of the
    board. Tier ASSIGNMENT still walks every player in the position, draftable
    or not; only the threshold's input set is narrowed.

    ponytail: gap-based clustering, not k-means. If tiers look wrong in a real
    draft, turn the sigma knob before reaching for a clustering library.
    """
    tiers: dict[str, int] = {}
    by_pos: dict[str, list[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)

    for pos, group in by_pos.items():
        group = sorted(group, key=lambda p: -scores.get(p.sleeper_id, 0.0))
        gaps = [
            scores.get(group[i].sleeper_id, 0.0) - scores.get(group[i + 1].sleeper_id, 0.0)
            for i in range(len(group) - 1)
        ]
        # group is sorted descending by score, so draftable players (score > 0)
        # are always a prefix of it -- count them and take that many leading gaps.
        draftable_n = sum(1 for p in group if scores.get(p.sleeper_id, 0.0) > 0)
        # ponytail: fewer than 2 draftable players means no meaningful stdev to
        # compute over the draftable set -- fall back to the full gap set
        # (identical to pre-fix behaviour) rather than a special case.
        threshold_gaps = gaps[: draftable_n - 1] if draftable_n >= 2 else gaps
        threshold = (
            sigma * statistics.pstdev(threshold_gaps)
            if len(threshold_gaps) > 1
            else float("inf")
        )
        tier = 1
        for i, p in enumerate(group):
            tiers[p.sleeper_id] = tier
            if i < len(gaps) and gaps[i] > threshold:
                tier += 1
    return tiers
