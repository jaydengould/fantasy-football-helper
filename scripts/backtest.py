"""Settle "is projection source X better than what we use?" against real outcomes.

    .venv/bin/python scripts/backtest.py [season ...]      # default: 2025

Scores each source's preseason projection against what actually happened, on its
OWN top-N (20 QB/TE, 40 RB/WR) so a source is not punished for covering players
another does not rank. Joins ESPN to Sleeper on `espn_id` through the
DynastyProcess crosswalk -- integer IDs, never names (non-negotiable #1).

WHY THE PROVENANCE CHECK IS THE POINT OF THIS SCRIPT
----------------------------------------------------
Both APIs happily serve a "season projection" for a season that has already been
played. Sometimes that number was frozen before week 1; sometimes it was revised
as the season went. A revised projection scores brilliantly and is worthless --
it is hindsight wearing a projection's clothes, and it would silently invert the
answer this script exists to give.

So a source must PROVE it is frozen before its accuracy is reported: a preseason
projection gives essentially everyone a full slate of games, because it cannot
know who gets hurt. A contaminated source is refused and named, never scored.

That check is not hypothetical. Measured 2026-08-25:
  - ESPN 2025: 91% full-slate, median 17.0 games -> clean.
  - ESPN 2024: 12% full-slate, median 15.12, MINIMUM 0.05 games -> revised.
    Nothing written before week 1 projects a player for 0.05 games.

RESULT ON THE CLEAN 2025 SEASON (MAE in season points, lower is better):
  QB  rotowire 75.3  espn 93.2   |  RB  rotowire 63.8  espn 62.5
  WR  rotowire 75.0  espn 80.3   |  TE  rotowire 46.3  espn 44.5
  ALL rotowire 66.5  espn 70.5   -> Rotowire 6% better; ESPN much worse at QB.
Averaging the two never beat Rotowire alone (68.1). See TODO.md section 13.
"""
import csv
import io
import json
import statistics
import sys
import urllib.request

CROSSWALK_URL = ("https://raw.githubusercontent.com/dynastyprocess/data/"
                 "master/files/db_playerids.csv")
ESPN_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
            "/segments/0/leaguedefaults/3?view=kona_player_info")
SLEEPER_URL = ("https://api.sleeper.app/{kind}/nfl/{season}"
               "?season_type=regular&position[]={pos}&order_by=pts_ppr")

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TOP_N = {"QB": 20, "RB": 40, "WR": 40, "TE": 20}
ESPN_GAMES_KEY = "210"          # ESPN keys stats numerically; 210 is games.
FULL_SLATE = 16.9               # 17 games, less float slop.
FROZEN_SHARE = 0.75             # below this, treat the source as revised.
ACTUALS_AGREE = 0.99            # two platforms' actual points must agree this well.


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    return urllib.request.urlopen(req, timeout=90).read()


def load_crosswalk() -> dict[str, str]:
    """espn_id -> sleeper_id. The one ID join that makes this comparison legal."""
    rows = csv.DictReader(io.StringIO(_get(CROSSWALK_URL).decode()))
    return {r["espn_id"].strip(): r["sleeper_id"].strip() for r in rows
            if r.get("espn_id", "").strip() not in ("", "NA")
            and r.get("sleeper_id", "").strip() not in ("", "NA")}


def frozen_share(games: list[float]) -> float:
    """Share of players projected a full slate -- the preseason fingerprint."""
    return sum(1 for g in games if g >= FULL_SLATE) / len(games) if games else 0.0


def load_sleeper(season: int) -> tuple[dict, dict, dict, dict, list[float]]:
    """Rotowire projections, as served by Sleeper. -> proj, actual, position, name, games"""
    proj, actual, position, name, games = {}, {}, {}, {}, []
    for pos in TOP_N:
        for r in json.loads(_get(SLEEPER_URL.format(kind="projections", season=season, pos=pos))):
            if r["stats"].get("pts_ppr") is None:
                continue
            proj[r["player_id"]] = r["stats"]["pts_ppr"]
            position[r["player_id"]] = pos
            player = r.get("player") or {}
            name[r["player_id"]] = f"{player.get('first_name')} {player.get('last_name')}"
            if r["stats"].get("gp") is not None:
                games.append(r["stats"]["gp"])
        for r in json.loads(_get(SLEEPER_URL.format(kind="stats", season=season, pos=pos))):
            if r["stats"].get("pts_ppr") is not None:
                actual[r["player_id"]] = r["stats"]["pts_ppr"]
    return proj, actual, position, name, games


def load_espn(season: int, crosswalk: dict[str, str]) -> tuple[dict, dict, list[float]]:
    """ESPN's own model, keyed back to sleeper_id. -> proj, actual, games

    Season totals are statSplitTypeId 0 / scoringPeriodId 0; statSourceId 1 is
    the projection and 0 is what the player actually did.
    """
    filt = {"players": {"limit": 1500,
                        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"}}}
    payload = json.loads(_get(ESPN_URL.format(season=season),
                              {"X-Fantasy-Filter": json.dumps(filt, separators=(",", ":"))}))
    proj, actual, games = {}, {}, []
    for row in payload.get("players", []):
        player = row["player"]
        sleeper_id = crosswalk.get(str(player.get("id")))
        if not sleeper_id:
            continue                        # unmatched, and reported in the summary
        for s in player.get("stats", []):
            if not (s.get("seasonId") == season and s.get("statSplitTypeId") == 0
                    and s.get("scoringPeriodId") == 0 and s.get("appliedTotal") is not None):
                continue
            if s.get("statSourceId") == 1:
                proj[sleeper_id] = s["appliedTotal"]
                played = (s.get("stats") or {}).get(ESPN_GAMES_KEY)
                if played is not None:
                    games.append(played)
            elif s.get("statSourceId") == 0:
                actual[sleeper_id] = s["appliedTotal"]
    return proj, actual, games


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values: list[float]) -> list[float]:
        out = [0.0] * len(values)
        for place, i in enumerate(sorted(range(len(values)), key=lambda i: -values[i])):
            out[i] = place + 1
        return out
    return statistics.correlation(ranks(xs), ranks(ys))


def run_season(season: int, crosswalk: dict[str, str]) -> None:
    print("=" * 66)
    print(f"SEASON {season}")
    sl_proj, sl_actual, position, name, sl_games = load_sleeper(season)
    es_proj, es_actual, es_games = load_espn(season, crosswalk)

    sources = {"rotowire": (sl_proj, sl_games), "espn": (es_proj, es_games)}
    print("\nprovenance -- a source is only scored if its projection was frozen "
          "before week 1:")
    clean = {}
    for source, (proj, games) in sources.items():
        share = frozen_share(games)
        ok = share >= FROZEN_SHARE
        detail = (f"{len(proj)} players, {share:.0%} full-slate"
                  + (f", median {statistics.median(games):.2f} games, min {min(games):.2f}"
                     if games else ", no games column"))
        print(f"  {source:<9} {'FROZEN ' if ok else 'REVISED'}  {detail}")
        if ok:
            clean[source] = proj
        else:
            print(f"  {'':<9} REFUSED -- these numbers saw the season they predict, "
                  f"so scoring them would flatter {source}.")

    both = [(sl_actual[k], es_actual[k]) for k in sl_actual if k in es_actual]
    if both:
        agree = statistics.correlation([a for a, _ in both], [b for _, b in both])
        print(f"\nsanity     the two platforms' ACTUAL points agree r={agree:.4f} "
              f"(mean diff {statistics.mean(abs(a - b) for a, b in both):.1f} pts, "
              f"n={len(both)})")
        if agree < ACTUALS_AGREE:
            print("           ABORT -- the scorings differ, so the errors below would "
                  "not be comparable.")
            return

    if len(clean) < 2:
        print("\nOnly one uncontaminated source. Nothing to compare this season.")
        return

    universe = set(sl_actual).intersection(*(set(p) for p in clean.values()))
    clean["average"] = {k: statistics.mean(p[k] for p in clean.values()) for k in universe}
    print(f"universe   {len(universe)} players projected by every source with a known actual\n")

    print(f"{'pos':<5}{'source':<10}{'MAE':>8}{'bias':>9}{'spearman':>10}{'top-N hit':>11}")
    print("-" * 53)
    overall: dict[str, list[float]] = {source: [] for source in clean}
    weak_ordering = []
    for pos, n in TOP_N.items():
        pool = [k for k in universe if position.get(k) == pos]
        if len(pool) < n:
            print(f"{pos:<5}(only {len(pool)} players, need {n} -- skipped)")
            continue
        actually_best = set(sorted(pool, key=lambda k: -sl_actual[k])[:n])
        for source, proj in clean.items():
            top = sorted(pool, key=lambda k: -proj[k])[:n]
            errors = [proj[k] - sl_actual[k] for k in top]
            overall[source] += [abs(e) for e in errors]
            rho = spearman([proj[k] for k in top], [sl_actual[k] for k in top])
            if rho < 0:
                weak_ordering.append((pos, source))
            print(f"{pos:<5}{source:<10}{statistics.mean(abs(e) for e in errors):>8.1f}"
                  f"{statistics.mean(errors):>+9.1f}{rho:>10.3f}"
                  f"{f'{len(set(top) & actually_best)}/{n}':>11}")
        print("-" * 53)
    for source, errors in overall.items():
        print(f"{'ALL':<5}{source:<10}{statistics.mean(errors):>8.1f}")

    # A negative rank correlation means the ordering was worse than a coin flip
    # at that position. That is a bigger finding than any MAE, so show the names.
    for pos, source in weak_ordering:
        if source == "average":
            continue
        pool = [k for k in universe if position.get(k) == pos]
        finish = {k: i + 1 for i, k in enumerate(sorted(pool, key=lambda k: -sl_actual[k]))}
        print(f"\n{source} could not order {pos} in {season} -- its preseason top 12:")
        for i, k in enumerate(sorted(pool, key=lambda k: -clean[source][k])[:12], 1):
            print(f"  projected {pos}{i:<3} {name.get(k, k):<24} finished {pos}{finish[k]:<4}"
                  f"({clean[source][k]:.0f} projected, {sl_actual[k]:.0f} actual)")


def main(argv: list[str]) -> int:
    seasons = [int(a) for a in argv] or [2025]
    crosswalk = load_crosswalk()
    print(f"crosswalk  {len(crosswalk)} espn_id -> sleeper_id")
    for season in seasons:
        run_season(season, crosswalk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
