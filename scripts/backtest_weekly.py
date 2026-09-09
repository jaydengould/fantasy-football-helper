"""Does the matchup adjustment earn its place? Scored on a real season.

    .venv/bin/python scripts/backtest_weekly.py [--league bros-fantasy] [--season 2025]

The season-mode sibling of `backtest.py`, and the gate the spec puts in front of
the matchup column: it may not reorder a lineup until it beats unadjusted
projections out of sample. It imports `season.points_allowed` and
`season.matchup_factor` rather than re-deriving them -- a backtest of a second
implementation proves nothing about the one that ships.

THE PROVENANCE PROBLEM, AND WHY THERE ARE THREE TESTS
-----------------------------------------------------
`backtest.py` makes a source prove it was frozen before scoring it. The weekly
projections FAIL that check, in a way worth naming precisely (measured 2025,
QB/RB/WR/TE, all 18 weeks):

  6165 projected player-weeks, of which 6 did not play -- 0.1%.

Nobody projects that well. Every real week has starters who are surprise
inactives, and a genuine preseason-of-the-week projection set contains them. A
set this clean has been filtered after the fact to the players who played. The
VALUES look untouched (r = 0.67-0.80 against actuals, MAE 3.5-4.7 -- a copied
number would read r = 1.0), so what is contaminated is the POPULATION, not the
numbers: survivorship, and it flatters absolute accuracy.

So this script does not report a single number:

  TEST A -- actuals only, uncontaminated. Split the season in half and ask
    whether what a defense allowed early predicts what it allows late. This
    touches no projection at all, so the survivorship above cannot reach it. It
    is the honest answer to "is there a matchup signal in the first place".

  TEST B -- adjusted vs unadjusted MAE, relative only. Both arms are scored on
    the identical contaminated population, so the bias is shared and the
    COMPARISON survives even though neither absolute MAE may be quoted. The
    script says so on screen rather than trusting the reader to remember.

  TEST C -- the same data under the scoring rule a LINEUP actually uses. Test B
    is a distance over every projected player-week; a lineup decision is a
    RANKING between two players eligible for one slot, and the overwhelming
    majority of player-weeks are not decisions -- a 30-point gap cannot be
    flipped, and averaging its error in swamps the pairs that can. A signal can
    be net-negative across the pool and still positive where two players sit
    within a few points. Test C restricts to those pairs and asks "did it pick
    the higher scorer". Its `share` column measures that premise rather than
    asserting it: what fraction of startable pairs are decisions at all.

    Two choices in it are worth naming. The population is `season.startable_pool`
    -- depth derived from `replacement_ranks`, so a pair below what the league
    starts is never scored (nobody chooses between WR80 and WR81) and no
    hand-picked "top 40" enters. And N is SWEPT, not picked: `close_call_points`
    is 3.0, a number sourced to this same survivorship-filtered set, and a gate
    built to fix that reading may not be calibrated by it.

Rates for week w are built from weeks 1..w-1 only. Using the whole season would
hand the adjustment the result it is being asked to predict.

THE RESULT, AND WHY THERE IS NO MATCHUP COLUMN
-----------------------------------------------
Run on 2024 and 2025 (~8000 scored player-weeks), the adjustment LOST:

  Test B, weekly MAE, unadjusted -> adjusted, at every shrinkage k tried:
    2025   QB 7.68->7.70   RB 4.09->4.10   WR 4.07->4.07   TE 3.23->3.24   (k=16)
    2024   QB 7.41->7.48   RB 3.91->3.90   WR 4.23->4.25   TE 3.20->3.21   (k=16)
  It is worse at every position in both seasons except RB 2024, where k>=8 is a
  wash. Error rises MONOTONICALLY as the adjustment gets louder, so the best
  value of k is the one that turns it off.

  Test A flips sign between seasons at the same position (WR +0.351 in 2025,
  -0.268 in 2024; RB +0.011 and +0.319). A quantity that unstable is noise.

  Out of sample, the factor correlates +0.02 to +0.06 with a player's actual
  weekly deviation from his own mean, while the PROJECTION's own week-to-week
  movement correlates +0.05 to +0.22 -- four times better. Rotowire is already
  carrying whatever weekly signal there is.

Also checked, because ruling out one suspect is not a verdict: the naive
points-allowed rate is confounded by the offenses a defense happened to face, so
a schedule-adjusted version (each game expressed against that offense's own
season mean) was measured too. Split-half r: 2024 QB +.170 RB +.377 WR -.062
TE +.165, 2025 QB +.273 RB -.084 WR +.357 TE +.339 -- same instability, same
sign flips. The estimator is not the problem.

WHAT TEST C ADDED, AND THE PREMISE IT CORRECTED
-----------------------------------------------
Run on 2024 and 2025 at k=0 (the loudest arm), the close-call reading agrees with
Test B rather than rescuing the adjustment. Hit rate, baseline -> +matchup, at
N=3 (RELATIVE only -- the population is the same survivorship-filtered set):

  2025   QB 53.9->56.2   RB 56.2->52.5   WR 55.4->51.9   TE 56.8->48.1
  2024   QB 50.3->52.5   RB 56.8->54.6   WR 54.4->50.7   TE 57.9->59.4

Four independent readings per season (one per position; the N rows are nested
subsets of each other, so the 16 printed cells are not 16 samples). RB and WR
lose in both seasons. TE swings -8.7 then +1.5 points -- the same sign flip
Test A shows, in a second instrument. QB is the one position that gains in both,
by +2.3 and +2.2 points at N=3, on flips that are right 52% and 56% of the time.
**Two seasons, one league's scoring, and a QB-only effect that appears where the
population is smallest is a hypothesis, not a finding** -- and the honest way to
settle it is the snapshot, on frozen weekly projections, not a third pass over
this same filtered set.

One thing the run sharpens. Test C was built on the reading that "the
overwhelming majority of player-weeks are not decisions", with the N-point gap
named as what separates them. That is right about the population and wrong
about which filter does the work. TWO filters are stacked here, and their sizes
are very different:

  DEPTH   342 projected player-weeks a week -> 96 startable (QB12 RB36 WR36
          TE12, from `replacement_ranks`). 72% of Test B's rows are removed by
          being nobody's start/sit call in the first place.
  GAP     of the startable PAIRS that survive, N=3 keeps 40-72% and N=1 keeps
          15-33% (the `share` column, both seasons).

So among startable players a close call is the common case, not the rare one,
and the N sweep's wide end (N=5 keeps 62-93%) is close to "all startable pairs"
-- N=1 and N=2 are where the gap filter is actually a distinct instrument. Read
the narrow rows first. Test C earns its place by scoring a decision rather than
a distance, not by decisions being rare.

**So no matchup number is shown anywhere and `start_sit` ranks on unadjusted
points.** `season.points_allowed` / `matchup_factor` / `matchup_deltas` stay --
they are what this script scores, and they are the one line it would take to
reopen. To reopen, bring a season where the adjustment WINS here.
"""
import argparse
import itertools
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffhelper import season as season_mod                          # noqa: E402
from ffhelper.cli import resolve_settings                          # noqa: E402
from ffhelper.config import get_league, load_config               # noqa: E402
from ffhelper.data import (LeagueSettings, Player, load_players,   # noqa: E402
                           load_weekly_actuals, load_weekly_projections,
                           score_stats)

ROOT = Path(__file__).resolve().parent.parent
WEEKS = range(1, 19)
POSITIONS = ("QB", "RB", "WR", "TE")
SHRINK_SWEEP = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
# Below this share of projected players actually playing, the projection set has
# been filtered after the fact. A real week loses 1-3% of projected starters.
CLEAN_DNP_RATE = 0.01
# Test C's "how close is close". SWEPT, never a single value: the project's own
# close_call_points (3.0) is sourced to the survivorship-filtered weekly set
# this script exists to work around, so picking it here would launder the
# number Test C was built to replace. A signal has to hold across the sweep.
GAP_SWEEP = (1.0, 2.0, 3.0, 5.0)


def load_season(season: str, scoring: dict[str, float], players: dict) -> tuple[dict, dict]:
    """{week: {player_id: projected points}}, {week: [actual rows]}."""
    proj, acts = {}, {}
    for wk in WEEKS:
        proj[wk] = season_mod.weekly_points(
            load_weekly_projections(season, wk), scoring)
        acts[wk] = load_weekly_actuals(season, wk)
        print(f"  week {wk:>2}: {len(proj[wk]):>4} projected, {len(acts[wk]):>4} actual rows",
              file=sys.stderr)
    return proj, acts


def actual_points(rows: list[dict], scoring: dict[str, float]) -> dict[str, float]:
    return {r["player_id"]: score_stats(r["stats"], scoring)
            for r in rows if r.get("player_id") and r.get("stats")}


def provenance(proj: dict, acts: dict) -> float:
    """Share of projected player-weeks that did not produce a stat line."""
    projected = missing = 0
    for wk in WEEKS:
        played = {r["player_id"] for r in acts[wk] if r.get("player_id")}
        projected += len(proj[wk])
        missing += len(set(proj[wk]) - played)
    return missing / projected if projected else 0.0


def test_a_split_half(acts: dict, players: dict, scoring: dict) -> dict[str, tuple[float, int]]:
    """Do early-season points-allowed rates predict late-season ones?

    Uncontaminated: actuals only, no projection anywhere in it.
    """
    first = season_mod.points_allowed(
        [r for wk in range(1, 10) for r in acts[wk]], players, scoring)
    second = season_mod.points_allowed(
        [r for wk in range(10, 19) for r in acts[wk]], players, scoring)
    out = {}
    for pos in POSITIONS:
        keys = [k for k in first.allowed if k[1] == pos and k in second.allowed]
        if len(keys) < 3:
            continue
        xs = [first.allowed[k] for k in keys]
        ys = [second.allowed[k] for k in keys]
        out[pos] = (statistics.correlation(xs, ys), len(keys))
    return out


def test_b_mae(proj: dict, acts: dict, players: dict, scoring: dict,
               shrink_k: float) -> dict[str, tuple[float, float, int]]:
    """{position: (unadjusted MAE, adjusted MAE, n)}, walking the season forward."""
    errs: dict[str, list[tuple[float, float]]] = {pos: [] for pos in POSITIONS}
    for wk in range(2, 19):
        rates = season_mod.points_allowed(
            [r for w in range(1, wk) for r in acts[w]], players, scoring)
        actual = actual_points(acts[wk], scoring)
        opp = season_mod.opponents(acts[wk])       # the actual row carries it too
        for pid, projected in proj[wk].items():
            player = players.get(pid)
            if player is None or player.position not in errs or pid not in actual:
                continue
            if pid not in opp:
                continue
            factor = season_mod.matchup_factor(rates, opp[pid], player.position, shrink_k)
            errs[player.position].append(
                (abs(projected - actual[pid]), abs(projected * factor - actual[pid])))
    return {pos: (statistics.fmean(a for a, _ in v), statistics.fmean(b for _, b in v), len(v))
            for pos, v in errs.items() if v}


@dataclass(frozen=True)
class PairScore:
    """One scored start/sit decision. `gap` is the projection gap, in points."""
    gap: float
    base_hit: bool      # the higher projection outscored the other
    arm_hit: bool       # the adjusted pick outscored the other
    flipped: bool       # the arm picked the OTHER player -- the only rows it can earn on


@dataclass(frozen=True)
class PairSummary:
    n: int
    base: float         # share of close calls the baseline got right
    arm: float
    flips: int
    flip_hits: int
    share: float        # close calls as a share of every scored pair


def _pick(x: Player, y: Player, xv: float, yv: float) -> Player:
    """Whichever the ranker prefers. Equal values break on id, so a tie is at
    least the SAME coin every run -- an unstable tie-break would show up as a
    difference between arms that neither arm caused."""
    if xv != yv:
        return x if xv > yv else y
    return min((x, y), key=lambda p: p.sleeper_id)


def close_call_pairs(
    proj: dict, acts: dict, players: dict, settings: LeagueSettings,
    flex_share: dict[str, float], shrink_k: float,
) -> dict[str, list[PairScore]]:
    """Every startable same-position pair of the season, scored by both arms.

    Not filtered by gap here: the gap is recorded per pair and the sweep buckets
    them afterwards, so the season is walked once rather than once per N.

    ponytail: same-position pairs only. A real FLEX call ranks an RB against a
    WR, which is a harder comparison and a different population; add it when a
    signal turns out to be position-specific and this cannot see it.
    """
    scoring = settings.scoring
    out: dict[str, list[PairScore]] = {pos: [] for pos in POSITIONS}
    for wk in range(2, 19):
        rates = season_mod.points_allowed(
            [r for w in range(1, wk) for r in acts[w]], players, scoring)
        actual = actual_points(acts[wk], scoring)
        opp = season_mod.opponents(acts[wk])
        pool = season_mod.startable_pool(players, proj[wk], settings.roster_slots,
                                         settings.num_teams, flex_share)
        by_pos: dict[str, list[Player]] = {}
        for p in pool:
            if p.position in out and p.sleeper_id in actual and p.sleeper_id in opp:
                by_pos.setdefault(p.position, []).append(p)

        for pos, group in by_pos.items():
            factor = {p.sleeper_id: season_mod.matchup_factor(
                rates, opp[p.sleeper_id], pos, shrink_k) for p in group}
            for a, b in itertools.combinations(group, 2):
                sa, sb = actual[a.sleeper_id], actual[b.sleeper_id]
                if sa == sb:
                    continue     # no correct pick exists -- scoring it moves the rate for free
                truth = a if sa > sb else b
                base = _pick(a, b, a.proj_pts, b.proj_pts)
                arm = _pick(a, b, a.proj_pts * factor[a.sleeper_id],
                            b.proj_pts * factor[b.sleeper_id])
                out[pos].append(PairScore(
                    gap=abs(a.proj_pts - b.proj_pts), base_hit=base is truth,
                    arm_hit=arm is truth, flipped=arm is not base))
    return out


def summarize(scored: list[PairScore], gap: float) -> PairSummary | None:
    """Both arms over the pairs within `gap`. None when there are none."""
    close = [s for s in scored if s.gap <= gap]
    if not close:
        return None
    flips = [s for s in close if s.flipped]
    return PairSummary(
        n=len(close),
        base=statistics.fmean(float(s.base_hit) for s in close),
        arm=statistics.fmean(float(s.arm_hit) for s in close),
        flips=len(flips), flip_hits=sum(1 for s in flips if s.arm_hit),
        share=len(close) / len(scored),
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", default="bros-fantasy")
    ap.add_argument("--season", default="2025")
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    args = ap.parse_args(argv)

    leagues, tunables = load_config(args.config)
    settings = resolve_settings(get_league(leagues, args.league))
    scoring = settings.scoring
    players = load_players()

    print(f"loading {args.season} weeks 1-18 under {args.league}'s scoring", file=sys.stderr)
    proj, acts = load_season(args.season, scoring, players)

    dnp = provenance(proj, acts)
    print(f"\nPROVENANCE  {dnp:.1%} of projected player-weeks did not play "
          f"(a clean set loses >{CLEAN_DNP_RATE:.0%})")
    contaminated = dnp < CLEAN_DNP_RATE
    if contaminated:
        print("  the projection set has been filtered to who played -- survivorship.")
        print("  ABSOLUTE accuracy below is therefore FLATTERING and may not be quoted.")
        print("  Test B's comparison still holds: both arms score the same rows.")

    print(f"\nTEST A -- does a defense's early rate predict its late rate? "
          f"(actuals only, no projection)")
    signal = test_a_split_half(acts, players, scoring)
    for pos, (r, n) in signal.items():
        print(f"  {pos:<3} weeks 1-9 vs 10-18   r = {r:+.3f}  over {n} defenses")
    best_pos = max(signal.values(), key=lambda v: v[0])[0] if signal else 0.0

    print(f"\nTEST B -- weekly MAE, unadjusted vs matchup-adjusted "
          f"({'RELATIVE ONLY' if contaminated else 'absolute'})")
    print(f"  {'k':>5}  " + "  ".join(f"{p:>16}" for p in POSITIONS))
    wins = {}
    for k in SHRINK_SWEEP:
        table = test_b_mae(proj, acts, players, scoring, k)
        cells = []
        for pos in POSITIONS:
            if pos not in table:
                cells.append(f"{'--':>16}")
                continue
            base, adj, n = table[pos]
            cells.append(f"{base:6.2f}->{adj:6.2f}")
        wins[k] = table
        print(f"  {k:>5.0f}  " + "  ".join(cells))

    improved = {k: sum(1 for pos, (b, a, _) in t.items() if a < b) for k, t in wins.items()}
    best_k = max(improved, key=lambda k: (improved[k], -k))

    # The LOUDEST arm in the sweep (k=0 is no shrinkage at all), deliberately and
    # not via Test B's best_k -- which tie-breaks to k=0 only when nothing wins,
    # so the two would agree today for unrelated reasons and diverge silently on
    # a season where the adjustment did win. Loudest is the right choice on its
    # own terms: it flips the most picks, which is the most chances Test C can
    # give a signal. One that cannot win at full volume will not win shrunk.
    loud_k = min(SHRINK_SWEEP)
    print(f"\nTEST C -- close calls only: two STARTABLE players at one position, "
          f"projections within N.")
    print(f"  Did the higher one outscore the other? Baseline ranks on the projection, "
          f"the arm on")
    print(f"  projection x matchup factor at k={loud_k:.0f} (loudest -- the most picks it "
          f"can change).")
    if contaminated:
        print("  Hit RATES are as flattered as Test B's MAE; the COMPARISON holds.")
    scored = close_call_pairs(proj, acts, players, settings, tunables.flex_share, loud_k)
    print(f"  {'N':>5}  {'POS':<4} {'pairs':>7} {'share':>7} {'baseline':>9} "
          f"{'+matchup':>9} {'flips':>7} {'right':>7}")
    beats = flips_total = 0
    for gap in GAP_SWEEP:
        for pos in POSITIONS:
            s = summarize(scored[pos], gap) if scored[pos] else None
            if s is None:
                continue
            right = f"{s.flip_hits}/{s.flips}" if s.flips else "--"
            print(f"  {gap:>5.0f}  {pos:<4} {s.n:>7} {s.share:>6.1%} {s.base:>9.1%} "
                  f"{s.arm:>9.1%} {s.flips:>7} {right:>7}")
            beats += s.arm > s.base
            if gap == GAP_SWEEP[-1]:
                flips_total += s.flips     # widest N only; the narrower ones are subsets
    print("  The N rows are NESTED (every N=1 pair is also an N=5 pair), so 16 cells "
          "are not")
    print("  16 samples. One position in one season is one reading; there are four.")

    print("\nVERDICT")
    if best_pos < 0.2:
        print(f"  Test A's best position correlates at r = {best_pos:+.3f}. A defense's "
              f"early rate barely predicts its own late rate,")
        print("  so there is little matchup signal to extract at all.")
    print(f"  Test B: k={best_k:.0f} improves {improved[best_k]} of {len(POSITIONS)} positions.")
    if improved[best_k] < len(POSITIONS):
        print("  The adjustment does NOT beat unadjusted projections across the board.")
        print("  This is what it did on 2024 and 2025, so nothing is shown on the")
        print("  lineup screen and `start_sit` ranks on unadjusted points. Reopening")
        print("  it means bringing a season where this table comes out the other way.")
    cells = len(GAP_SWEEP) * len(POSITIONS)
    print(f"  Test C: the arm beats the baseline in {beats} of {cells} close-call cells, "
          f"changing {flips_total} picks at N={GAP_SWEEP[-1]:.0f}.")
    if not flips_total:
        print("  It never changes a pick, so Test C cannot separate the two arms here --")
        print("  Test B's loss is not an artefact of scoring the wrong population.")
    elif beats <= cells // 2:
        print("  A signal that only pays off on close calls would show up HERE and does")
        print("  not, which is the one alternative Test B's MAE could not rule out.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
