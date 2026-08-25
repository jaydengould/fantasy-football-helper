"""Terminal draft board. Phase 3 replaces render() with Dash; the engine is
identical either way.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import (
    LeagueSettings, Player, adp_format_for, apply_ffc_adp, apply_projections,
    apply_sleeper_adp, load_ffc_adp, load_players, load_projections,
    load_sleeper_settings,
)
from ffhelper.feeds import PickFeed, SleeperFeed
from ffhelper.value import Row, build_board, detect_run, next_pick_number

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SEASON = "2026"


def render(
    board: list[Row], limit: int, stale_seconds: float,
    my_roster: list[Player], runs: dict[str, int],
) -> str:
    lines: list[str] = []
    if stale_seconds > 15:
        lines.append(f"!!  FEED STALE {stale_seconds:.0f}s  -- board may be out of date")
    if runs:
        summary = "  ".join(f"{pos} {n}" for pos, n in sorted(runs.items(), key=lambda kv: -kv[1]))
        lines.append(f"last 8 picks:  {summary}")
    if my_roster:
        lines.append("my roster:  " + ", ".join(f"{p.name} ({p.position})" for p in my_roster))
    lines.append("")
    lines.append(f"{'#':<3} {'PLAYER':<24} {'POS':<4} {'VONA':>7} {'VBD':>7} "
                 f"{'MARG':>7} {'TIER':>4} {'SURV':>6} {'DIV':>5}  FLAGS")
    for i, r in enumerate(board[:limit], 1):
        flags = []
        if r.player.injury_status:
            flags.append(r.player.injury_status)
        if abs(r.divergence) >= 25:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        if r.player.bye:
            flags.append(f"bye{r.player.bye}")
        lines.append(
            f"{i:<3} {r.player.name[:24]:<24} {r.player.position:<4} {r.vona:>7.1f} "
            f"{r.vbd:>7.1f} {r.marginal:>7.1f} {r.tier:>4} {r.survival:>6.0%} "
            f"{r.divergence:>+5}  {' '.join(flags)}"
        )
    return "\n".join(lines)


def resolve_settings(league: League, season: str = SEASON) -> LeagueSettings:
    """Return the league's settings, preferring the platform API where one exists.

    Manual settings are a FIRST-CLASS path, not a fallback. Yahoo's API requires
    per-developer approval, ESPN has no official API, and CBS/NFL.com have none
    worth using — so for most leagues and most users of this repo, hand-entered
    settings are the ONLY way the tool works. API sync is an optimisation for the
    platforms that permit it, not the baseline.

    Precedence: platform API when reachable, else the config block. A league that
    later gains API access starts syncing with no config change.
    """
    if league.platform == "sleeper":
        return load_sleeper_settings(league.league_id)
    if league.settings is not None:
        return league_settings_from_config(league.settings)
    raise ValueError(
        f"league {league.name!r} on platform {league.platform!r} has no API support "
        f"and no [league.settings] block in config.toml. Add one — see README."
    )


def league_settings_from_config(raw: dict) -> LeagueSettings:
    """Build LeagueSettings from a hand-entered config block."""
    slots = {k: int(v) for k, v in (raw.get("roster_slots") or {}).items()}
    scoring = {k: float(v) for k, v in (raw.get("scoring") or {}).items()}
    if not slots:
        raise ValueError("[league.settings] needs roster_slots")
    if not scoring:
        raise ValueError("[league.settings] needs a scoring table")
    return LeagueSettings(
        num_teams=int(raw["num_teams"]),
        scoring=scoring,
        roster_slots=slots,
        rounds=int(raw.get("rounds", sum(slots.values()) + int(raw.get("bench", 0)))),
        draft_id=raw.get("draft_id"),
    )


def load_board_inputs(
    league: League, tunables: Tunables, season: str = SEASON
) -> tuple[dict[str, Player], LeagueSettings]:
    """Cold start: fetch everything, join by ID, then enrich with FFC."""
    settings = resolve_settings(league, season)
    players = load_players()
    projections = load_projections(season)

    apply_projections(players, projections, settings.scoring)
    fmt = league.adp_format or adp_format_for(settings)
    apply_sleeper_adp(players, projections, f"adp_{fmt.replace('-', '_')}")

    teams = league.adp_teams or settings.num_teams
    unmatched = apply_ffc_adp(players, load_ffc_adp(fmt, teams, int(season)))
    if unmatched:
        # Printed, never silently dropped.
        print(f"FFC: {len(unmatched)} unmatched -> {', '.join(unmatched[:15])}"
              + (" ..." if len(unmatched) > 15 else ""), file=sys.stderr)

    # Drop players with no projection: they cannot be ranked.
    return {pid: p for pid, p in players.items() if p.proj_pts > 0}, settings


def _render_tick(
    picks: list, last_ok: float, players: dict[str, Player], settings: LeagueSettings,
    league: League, tunables: Tunables, limit: int, manual_gone: set[str],
) -> None:
    """Build and print one frame of the draft board from the current picks.

    Pulled out of `_run` so a single iteration's work can be wrapped in its
    own try/except and driven a bounded number of times from tests.
    """
    drafted = {p.sleeper_id for p in picks} | manual_gone
    available = [p for pid, p in players.items() if pid not in drafted]
    my_roster: list[Player] = []                  # wired via slot_to_roster_id in a later task
    recent = [players[p.sleeper_id].position for p in picks[-8:] if p.sleeper_id in players]

    board = build_board(
        available, my_roster, settings.roster_slots, settings.num_teams,
        current_pick=len(picks) + 1, my_slot=league.draft_slot, tunables=tunables,
    )
    print("\033[2J\033[H", end="")                # clear screen
    print(render(board, limit, time.time() - last_ok, my_roster, detect_run(recent)))
    if league.draft_slot:
        nxt = next_pick_number(len(picks) + 1, league.draft_slot, settings.num_teams)
        print(f"\npick {len(picks) + 1}   your next pick: {nxt} "
              f"({nxt - len(picks) - 1} away)")
    print("\n(ctrl-c to stop; run `preflight` before the draft)")


def _run(
    league: League, tunables: Tunables, limit: int, max_iterations: int | None = None,
) -> int:
    """Poll the feed and redraw the board forever (or `max_iterations` times).

    The loop must never die: a crash here during a live draft leaves the user
    with nothing while their pick clock keeps running. Every iteration is two
    independently-guarded steps -- poll, then render -- so a failure in
    either is logged and the loop moves on to the next tick. `max_iterations`
    exists only so tests can drive a bounded number of ticks without a real
    `while True` or a blocking `time.sleep`.
    """
    players, settings = load_board_inputs(league, tunables)
    if not settings.draft_id:
        print("league has no draft_id yet", file=sys.stderr)
        return 1

    feed: PickFeed = SleeperFeed(settings.draft_id)
    manual_gone: set[str] = set()
    picks: list = []
    last_ok = time.time()
    interval = tunables.poll_seconds.get(league.platform, 5)

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        try:
            picks = feed.get_picks()
            last_ok = time.time()
        except Exception as exc:                      # noqa: BLE001 - loop must never die
            log.warning("poll failed: %s", exc)

        try:
            _render_tick(picks, last_ok, players, settings, league, tunables, limit, manual_gone)
        except Exception as exc:                      # noqa: BLE001 - loop must never die
            log.error("draft tick failed: %s", exc, exc_info=True)

        iterations += 1
        if max_iterations is None or iterations < max_iterations:
            time.sleep(interval)
    return 0


def _preflight(league: League, tunables: Tunables) -> int:
    """Validate everything before draft day. Run this the morning of."""
    ok = True
    players, settings = load_board_inputs(league, tunables)
    print(f"league          : {league.name} ({league.platform})")
    print(f"teams           : {settings.num_teams}")
    print(f"roster slots    : {settings.roster_slots}")
    print(f"scoring keys    : {len(settings.scoring)}  (pass_td={settings.scoring.get('pass_td')})")
    print(f"draft_id        : {settings.draft_id}")
    print(f"players w/ proj : {len(players)}")

    no_stdev = [p.name for p in players.values() if p.adp_stdev is None]
    print(f"missing stdev   : {len(no_stdev)}")
    if league.draft_slot is None:
        print("draft_slot      : NOT SET -- board will degrade to next-pick survival")
        ok = False
    else:
        print(f"draft_slot      : {league.draft_slot}")

    if settings.draft_id:
        try:
            n = len(SleeperFeed(settings.draft_id).get_picks())
            print(f"feed reachable  : yes ({n} picks so far)")
        except Exception as exc:                      # noqa: BLE001
            print(f"feed reachable  : NO -- {exc}")
            ok = False
    print("\nPREFLIGHT OK" if ok else "\nPREFLIGHT INCOMPLETE -- see above")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="ffhelper")
    ap.add_argument("command", choices=["run", "preflight"])
    ap.add_argument("--league", required=True)
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)

    leagues, tunables = load_config(args.config)
    try:
        league = get_league(leagues, args.league)
    except KeyError as exc:
        print(exc.args[0] if exc.args else str(exc), file=sys.stderr)
        return 1
    if args.command == "preflight":
        return _preflight(league, tunables)
    try:
        return _run(league, tunables, args.limit)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
