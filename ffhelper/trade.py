"""Two-sided trade search. PURE -- no I/O, no network, no module-level state.

A trade is `roster_upgrade` run twice: what it does to my starting lineup, and
what it does to theirs, over the same weighted horizon. There is no new ranking
engine here and if this module ever seems to need one, the design is wrong.

Mutually beneficial trades exist because lineup constraints create surplus on
both rosters -- a fourth running back you cannot start is worth more to someone
starting two -- not because anybody is being fleeced.
"""
from dataclasses import dataclass
from itertools import combinations

from .data import Player
from .season import best_drop, horizon_total


@dataclass(frozen=True)
class Proposal:
    """One offer, and what each side would have to do to accept it."""
    opponent: int                     # roster_id
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    gain_me: float
    gain_them: float
    # Set only when the shape leaves the counterparty over the roster limit and
    # the league forces a cut. None means roster-neutral. It is part of the
    # OFFER -- they will notice it before you do -- so it is never hidden.
    their_drop: Player | None = None


def _without(roster: list[Player], players) -> list[Player]:
    gone = {p.sleeper_id for p in players}
    return [p for p in roster if p.sleeper_id not in gone]


def _ids(players) -> tuple[str, ...]:
    return tuple(sorted(p.sleeper_id for p in players))


def trade_options(
    mine: list[Player], theirs: list[Player], opponent: int,
    roster_slots: dict[str, int], weekly_by_week: dict[int, dict[str, float]],
    floor: float, weights: dict[int, float] | None = None,
    pin: Player | None = None,
) -> list[Proposal]:
    """Every swap with THIS opponent where both lineups gain more than `floor`.

    One opponent per call: it keeps this module single-subject and testable
    without a network, and leaves the league-wide loop in the caller where the
    league context already lives.

    BOTH sides must clear the floor, not merely be positive. The output is an
    argument you send to another human, and a gain smaller than the error on
    the number that produced it cannot be defended. Measured on the real league
    2026-09-02: that single choice is the difference between 11 rows of noise
    and 1 real row.
    """
    def ros(roster: list[Player]) -> float:
        return horizon_total(roster, roster_slots, weekly_by_week, weights)

    base_me, base_them = ros(mine), ros(theirs)
    out: list[Proposal] = []

    def consider(give: list[Player], get: list[Player]) -> None:
        if pin is not None and not _pin_matches(pin, give, get, mine):
            return
        gain_me = ros([*_without(mine, give), *get]) - base_me
        if gain_me <= floor:
            return
        after = [*_without(theirs, get), *give]
        drop = None
        if len(after) > len(theirs):
            # 16 players is not a legal roster, so the league forces a cut and
            # the cut is part of what the trade costs them. Same rule
            # `roster_upgrade` uses, imported rather than restated.
            total_them, drop = best_drop(after, roster_slots, weekly_by_week, weights)
        else:
            total_them = ros(after)
        gain_them = total_them - base_them
        if gain_them <= floor:
            return
        # Sorted, not just tuple(give): with 2+ players the tuple's ORDER
        # depends on iteration order over `mine`/`theirs`, invisible while
        # every shape was 1-for-1 and every give/get had one element. Found by
        # test_results_are_deterministic_across_runs failing on 2-for-1.
        out.append(Proposal(opponent, tuple(sorted(give, key=lambda p: p.sleeper_id)),
                            tuple(sorted(get, key=lambda p: p.sleeper_id)),
                            gain_me, gain_them, drop))

    for a in mine:
        for b in theirs:
            consider([a], [b])

    for pair in combinations(mine, 2):
        for b in theirs:
            consider(list(pair), [b])

    for pair in combinations(mine, 2):
        for other in combinations(theirs, 2):
            consider(list(pair), list(other))

    # Deterministic: a board that renames a package when nothing changed is one
    # nobody can trust. Ties on gain_me are real, not rounding -- a throw-in
    # that contributes 0 to either lineup (rb2 in the fixture) reproduces a
    # 1-for-1's exact gain as a 2-for-1, found by running Task 5's own test
    # after Task 6 landed. Fewest players moved breaks the tie: the simpler ask
    # for an identical outcome is the one to lead with.
    out.sort(key=lambda p: (-p.gain_me, len(p.give) + len(p.get),
                            _ids(p.give), _ids(p.get)))
    return out


@dataclass(frozen=True)
class Grade:
    """One offer someone SENT me, scored. Not a search: the shape is theirs."""
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    gain_me: float
    gain_them: float
    floor: float
    my_drops: tuple[Player, ...] = ()
    their_drops: tuple[Player, ...] = ()
    # Points MY forced cuts cost, already inside gain_me -- surfaced so the
    # drop is visible rather than weighted. Often 0.0: the cut never starts.
    # What it cannot price is the cut as injury cover; no multiplier stands
    # in for that (non-negotiable #8).
    drop_cost: float = 0.0

    @property
    def verdict(self) -> str:
        """Three bands, never a letter grade.

        The only cutoff is the finder's own floor -- the error on the number
        itself. A to F would need cutoffs nobody measured (CLAUDE.md
        non-negotiable #8). Only MY gain decides: their gain is context for
        why they sent it, not a reason to accept.
        """
        if self.gain_me > self.floor:
            return "accept"
        if self.gain_me < -self.floor:
            return "decline"
        return "too close to call"


def _settle(roster: list[Player], limit: int, roster_slots, weekly_by_week,
            weights) -> tuple[float, tuple[Player, ...], float]:
    """Horizon total once `roster` is cut back to `limit`, who was cut, and
    what the cuts cost against keeping everyone.

    ponytail: one best_drop at a time, greedy. Exact whenever the cuts are
    bench players (the normal case); a 3-for-1 that must cut two starters
    could in theory beat greedy by choosing the pair jointly.
    """
    uncut = horizon_total(roster, roster_slots, weekly_by_week, weights)
    drops: list[Player] = []
    while len(roster) > limit:
        _, cut = best_drop(roster, roster_slots, weekly_by_week, weights)
        drops.append(cut)
        roster = _without(roster, [cut])
    total = horizon_total(roster, roster_slots, weekly_by_week, weights)
    return total, tuple(drops), uncut - total


def grade_offer(
    mine: list[Player], theirs: list[Player], give: list[Player], get: list[Player],
    roster_slots: dict[str, int], weekly_by_week: dict[int, dict[str, float]],
    floor: float, my_limit: int, their_limit: int,
    weights: dict[int, float] | None = None,
) -> Grade:
    """Score one received offer on both sides, over the finder's horizon.

    Unlike `trade_options`, MY roster can grow here -- they choose the shape,
    and a 1-for-2 in my favour forces me to cut someone. `*_limit` is the
    roster size each side may hold; the caller knows it, this module does not.
    """
    def ros(roster: list[Player]) -> float:
        return horizon_total(roster, roster_slots, weekly_by_week, weights)

    me_after, my_drops, drop_cost = _settle([*_without(mine, give), *get], my_limit,
                                            roster_slots, weekly_by_week, weights)
    them_after, their_drops, _ = _settle([*_without(theirs, get), *give], their_limit,
                                         roster_slots, weekly_by_week, weights)
    return Grade(tuple(give), tuple(get), me_after - ros(mine),
                 them_after - ros(theirs), floor, my_drops, their_drops, drop_cost)


def keep_mine(
    mine: list[Player], theirs: list[Player], give: list[Player], get: list[Player],
    roster_slots: dict[str, int], weekly_by_week: dict[int, dict[str, float]],
    floor: float, my_limit: int, their_limit: int,
    weights: dict[int, float] | None = None,
) -> Grade | None:
    """When accepting forces me to cut one of MY players: the same offer with
    them keeping enough of theirs that I cut none of mine. The best such
    offer for me, then the fewest players; None if the cut is only players
    I would receive, or no smaller offer would itself be accepted.

    By projections this never beats accepting as offered -- the grade already
    cut whoever is worth least, theirs included (measured: 381 real subsets,
    none better beyond best_drop's tie tolerance). It is shown for what
    projections cannot see: a bench player's value as injury cover. The page
    states what keeping him costs; the reader decides if he is worth it.
    """
    args = (roster_slots, weekly_by_week, floor, my_limit, their_limit, weights)
    got = {p.sleeper_id for p in get}

    def cuts_only_received(g: Grade) -> bool:
        return all(p.sleeper_id in got for p in g.my_drops)

    if cuts_only_received(grade_offer(mine, theirs, give, get, *args)):
        return None
    out = [g for n in range(1, len(get))
           for sub in combinations(get, n)
           for g in [grade_offer(mine, theirs, give, list(sub), *args)]
           if cuts_only_received(g) and g.verdict == "accept"]
    return min(out, key=lambda g: (-g.gain_me, len(g.get), _ids(g.get)), default=None)


def _pin_matches(pin: Player, give, get, mine: list[Player]) -> bool:
    """Keep only proposals involving `pin`, on the side his roster implies.

    The side is decided by MEMBERSHIP, never by a flag the caller passes: a
    player of mine can only be given, one of theirs can only be got, and two
    sources of truth for one fact disagree eventually.
    """
    if any(p.sleeper_id == pin.sleeper_id for p in mine):
        return any(p.sleeper_id == pin.sleeper_id for p in give)
    return any(p.sleeper_id == pin.sleeper_id for p in get)
