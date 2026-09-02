"""Does the matchup adjustment earn its place? Scored on a real season.

    .venv/bin/python scripts/backtest_weekly.py [--league sleeper-main] [--season 2025]

The season-mode sibling of `backtest.py`, and the gate the spec puts in front of
the matchup column: it may not reorder a lineup until it beats unadjusted
projections out of sample. It imports `season.points_allowed` and
`season.matchup_factor` rather than re-deriving them -- a backtest of a second
implementation proves nothing about the one that ships.

THE PROVENANCE PROBLEM, AND WHY THERE ARE TWO TESTS
---------------------------------------------------
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

**So no matchup number is shown anywhere and `start_sit` ranks on unadjusted
points.** `season.points_allowed` / `matchup_factor` / `matchup_deltas` stay --
they are what this script scores, and they are the one line it would take to
reopen. To reopen, bring a season where the adjustment WINS here.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffhelper import season as season_mod                          # noqa: E402
from ffhelper.cli import resolve_settings                          # noqa: E402
from ffhelper.config import get_league, load_config               # noqa: E402
from ffhelper.data import (load_players, load_weekly_actuals,      # noqa: E402
                           load_weekly_projections, score_stats)

ROOT = Path(__file__).resolve().parent.parent
WEEKS = range(1, 19)
POSITIONS = ("QB", "RB", "WR", "TE")
SHRINK_SWEEP = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
# Below this share of projected players actually playing, the projection set has
# been filtered after the fact. A real week loses 1-3% of projected starters.
CLEAN_DNP_RATE = 0.01


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


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--league", default="sleeper-main")
    ap.add_argument("--season", default="2025")
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    args = ap.parse_args(argv)

    leagues, _ = load_config(args.config)
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

    print("\nVERDICT")
    if best_pos < 0.2:
        print(f"  Test A's best position correlates at r = {best_pos:+.3f}. A defense's "
              f"early rate barely predicts its own late rate,")
        print("  so there is little matchup signal to extract at all.")
    improved = {k: sum(1 for pos, (b, a, _) in t.items() if a < b) for k, t in wins.items()}
    best_k = max(improved, key=lambda k: (improved[k], -k))
    print(f"  Test B: k={best_k:.0f} improves {improved[best_k]} of {len(POSITIONS)} positions.")
    if improved[best_k] < len(POSITIONS):
        print("  The adjustment does NOT beat unadjusted projections across the board.")
        print("  This is what it did on 2024 and 2025, so nothing is shown on the")
        print("  lineup screen and `start_sit` ranks on unadjusted points. Reopening")
        print("  it means bringing a season where this table comes out the other way.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
