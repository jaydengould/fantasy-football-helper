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


FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def lineup_value(roster: list[Player], roster_slots: dict[str, int]) -> float:
    """Points scored by the optimal starting lineup drawn from `roster`.

    Phase 1 uses this for starter-slot awareness; Phase 5's trade finder uses
    the identical function. Never inline it into the board.
    """
    remaining = sorted(roster, key=lambda p: -p.proj_pts)
    used: set[str] = set()
    total = 0.0

    for pos, count in roster_slots.items():
        if pos == "FLEX":
            continue
        picked = 0
        for p in remaining:
            if picked >= count:
                break
            if p.position == pos and p.sleeper_id not in used:
                used.add(p.sleeper_id)
                total += p.proj_pts
                picked += 1

    for _ in range(roster_slots.get("FLEX", 0)):
        for p in remaining:
            if p.position in FLEX_ELIGIBLE and p.sleeper_id not in used:
                used.add(p.sleeper_id)
                total += p.proj_pts
                break

    return total


def marginal_value(
    roster: list[Player], candidate: Player, roster_slots: dict[str, int]
) -> float:
    """How much adding `candidate` improves the optimal starting lineup."""
    return lineup_value([*roster, candidate], roster_slots) - lineup_value(roster, roster_slots)


from collections import Counter

from ffhelper.data import curve_stdev


def next_pick_number(current_pick: int, slot: int, num_teams: int) -> int:
    """The next pick belonging to `slot` strictly after `current_pick`.

    Snake order: round r (1-indexed) gives slot s the pick
    (r-1)*n + s on odd rounds, and (r-1)*n + (n-s+1) on even rounds.
    """
    r = 1
    while True:
        offset = slot if r % 2 == 1 else (num_teams - slot + 1)
        pick = (r - 1) * num_teams + offset
        if pick > current_pick:
            return pick
        r += 1


def survival_prob(player: Player, at_pick: int) -> float:
    """P(player is still available at `at_pick`), from ADP mean and spread.

    FFC's per-player stdev cannot be synthesized -- fitting it from ADP alone
    leaves 42.6% of the variance unexplained -- so the curve is only a fallback.
    """
    stdev = player.adp_stdev if player.adp_stdev is not None else curve_stdev(player.adp)
    return 1.0 - NormalDist(player.adp, max(stdev, 0.1)).cdf(at_pick)


def vona(players: list[Player], candidate: Player, at_pick: int) -> float:
    """Value Over Next Available: what it costs to wait rather than take him now.

    Expected best-at-position at `at_pick`, computed as a survival-weighted
    walk down the position board: the best player is the first who survives.

    The candidate himself is part of that walk -- if you wait, the best
    player still there at `at_pick` might well be him. Excluding him would
    overstate urgency for exactly the players most likely to survive.
    """
    same_pos = sorted(
        (p for p in players if p.position == candidate.position),
        key=lambda p: -p.proj_pts,
    )
    expected = 0.0
    prob_all_gone = 1.0
    for p in same_pos:
        surv = survival_prob(p, at_pick)
        expected += prob_all_gone * surv * p.proj_pts
        prob_all_gone *= 1.0 - surv
        if prob_all_gone < 1e-6:
            break
    return candidate.proj_pts - expected


def divergence(players: list[Player], scores: dict[str, float]) -> dict[str, int]:
    """projection_rank - adp_rank. Positive means the model likes him more
    than the market does.

    NEVER average these two ranks. Blending pulls the board toward consensus,
    and a board that tracks consensus produces consensus results.
    """
    by_proj = sorted(players, key=lambda p: -scores.get(p.sleeper_id, 0.0))
    by_adp = sorted(players, key=lambda p: p.adp)
    proj_rank = {p.sleeper_id: i for i, p in enumerate(by_proj, 1)}
    adp_rank = {p.sleeper_id: i for i, p in enumerate(by_adp, 1)}
    return {pid: adp_rank[pid] - proj_rank[pid] for pid in proj_rank}


def detect_run(recent_positions: list[str], window: int = 8) -> dict[str, int]:
    """Position counts over the last `window` picks."""
    if window <= 0:
        return {}
    return dict(Counter(recent_positions[-window:]))


from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    player: Player
    vbd: float
    vona: float
    marginal: float
    tier: int
    survival: float
    divergence: int


def build_board(
    available: list[Player],
    my_roster: list[Player],
    settings_slots: dict[str, int],
    num_teams: int,
    current_pick: int,
    my_slot: int | None,
    tunables,
) -> list[Row]:
    """Assemble the ranked board. Pure: same inputs, same output, always."""
    if not available:
        return []

    at_pick = (
        next_pick_number(current_pick, my_slot, num_teams)
        if my_slot is not None
        else current_pick + 1
    )
    ranks = replacement_ranks(settings_slots, num_teams, tunables.flex_share)
    repl = replacement_points(available, ranks)
    vbd_scores = vbd(available, repl)
    tiers = assign_tiers(available, vbd_scores, tunables.tier_break_sigma)
    divs = divergence(available, vbd_scores)

    rows = [
        Row(
            player=p,
            vbd=vbd_scores[p.sleeper_id],
            vona=vona(available, p, at_pick),
            marginal=marginal_value(my_roster, p, settings_slots),
            tier=tiers[p.sleeper_id],
            survival=survival_prob(p, at_pick),
            divergence=divs[p.sleeper_id],
        )
        for p in available
    ]
    return sorted(rows, key=lambda r: -r.vona)
