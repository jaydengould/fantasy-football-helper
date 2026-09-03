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

    # Deterministic: a board that renames a package when nothing changed is one
    # nobody can trust. Ties on gain_me are real, not rounding -- a throw-in
    # that contributes 0 to either lineup (rb2 in the fixture) reproduces a
    # 1-for-1's exact gain as a 2-for-1, found by running Task 5's own test
    # after Task 6 landed. Fewest players moved breaks the tie: the simpler ask
    # for an identical outcome is the one to lead with.
    out.sort(key=lambda p: (-p.gain_me, len(p.give) + len(p.get),
                            _ids(p.give), _ids(p.get)))
    return out


def _pin_matches(pin: Player, give, get, mine: list[Player]) -> bool:
    """Task 7 fills this in. Until then every proposal passes."""
    return True
