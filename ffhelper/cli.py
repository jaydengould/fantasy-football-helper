"""Terminal draft board. Phase 3 replaces render() with Dash; the engine is
identical either way.
"""
import argparse
import logging
import queue
import sys
import threading
import time
from pathlib import Path

from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import (
    LeagueSettings, Player, adp_format_for, apply_ffc_adp, apply_projections,
    apply_sleeper_adp, fetch_json, load_ffc_adp, load_players, load_projections,
    load_sleeper_settings, norm_name,
)
from ffhelper.feeds import PickFeed, SleeperFeed
from ffhelper.value import Row, build_board, detect_run, next_pick_number

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SEASON = "2026"
SLEEPER_DRAFT_URL = "https://api.sleeper.app/v1/draft/{draft_id}"


def find_players(pool: dict[str, Player], query: str) -> list[Player]:
    """Partial, case-insensitive name search over `pool`.

    Uses `norm_name` -- the SAME normalisation the FFC join uses -- so accent
    folding and generational-suffix stripping come for free: "pineiro"
    matches "Eddy Pineiro" and "harrison" matches "Marvin Harrison Jr.".

    Returns ALL matches in a stable (name, id) order. Never returns just the
    first: "robinson" matches both Bijan and Brian Robinson, and picking one
    silently would remove the wrong player from the board.
    """
    q = norm_name(query)
    if not q:
        return []
    return sorted(
        (p for p in pool.values() if q in norm_name(p.name)),
        key=lambda p: (p.name, p.sleeper_id),
    )


class MarkDrafted:
    """Manual mark-drafted state: player_ids hand-marked gone, plus a
    one-level-deep undo of the most recent mark.

    Only ids are tracked -- the pool itself lives in `players` and is
    filtered by `drafted` exactly like feed-reported picks are, so the board
    never has to know which source removed a player.
    """

    def __init__(self) -> None:
        self._history: list[str] = []
        self._marked: set[str] = set()

    def mark(self, player_id: str) -> None:
        if player_id in self._marked:
            return                          # already marked: idempotent, no-op
        self._marked.add(player_id)
        self._history.append(player_id)

    def undo(self) -> None:
        if not self._history:
            return                          # nothing to undo: no-op, never raises
        self._marked.discard(self._history.pop())

    @property
    def drafted(self) -> set[str]:
        return set(self._marked)


def _handle_command(
    line: str, pool: dict[str, Player], mark_state: MarkDrafted, pending: list[Player],
) -> tuple[list[Player], str]:
    """Process one line of manual input; pure and stdin-free so it is directly
    testable. `pending` is the disambiguation list left open by the previous
    command (empty when none is open). Returns the new pending list plus a
    status line for the caller to print.

    Protocol: "u"/"undo" undoes the last mark; a bare number, while a
    disambiguation list is open, selects from it; anything else is a name
    search. A search with exactly one match marks it directly -- that is not
    "picking the first" because there is only one candidate. A search with
    several matches opens the disambiguation list instead of guessing.
    """
    line = line.strip()
    if not line:
        return pending, ""
    if line.lower() in ("u", "undo"):
        mark_state.undo()
        return [], "undid last mark"
    if pending and line.isdigit():
        idx = int(line)
        if 1 <= idx <= len(pending):
            chosen = pending[idx - 1]
            mark_state.mark(chosen.sleeper_id)
            return [], f"marked {chosen.name} ({chosen.position} {chosen.team})"
        return pending, f"choose 1-{len(pending)}, or type a new search"
    matches = find_players(pool, line)
    if not matches:
        return [], f"no match for {line!r}"
    if len(matches) == 1:
        p = matches[0]
        mark_state.mark(p.sleeper_id)
        return [], f"marked {p.name} ({p.position} {p.team})"
    listing = "; ".join(f"{i}:{p.name} {p.position}-{p.team}" for i, p in enumerate(matches, 1))
    return matches, f"multiple matches, type a number -- {listing}"


def _stdin_reader(q: "queue.Queue[str]") -> None:
    """Daemon-thread target: blocks reading stdin lines so the render loop
    never has to. Runs in its own thread; any failure (stdin unavailable,
    closed, or captured e.g. under a test runner) just ends the thread --
    the queue simply stays empty, same as no input at all.
    """
    try:
        for raw_line in sys.stdin:
            q.put(raw_line.strip())
    except Exception:                                   # noqa: BLE001
        pass


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


def _lookup_roster_id(league: League, settings: LeagueSettings) -> int | None:
    """Resolve the user's Sleeper roster_id from the configured draft_slot via
    the draft object's `slot_to_roster_id` map, fetched through the existing
    cached `fetch_json` (no new HTTP path, no reimplemented caching).

    Never guesses: returns None -- and callers must leave my_roster empty --
    when draft_slot isn't configured, the platform has no such mapping
    (anything but Sleeper today), or the lookup fails for any reason.
    """
    if league.draft_slot is None or league.platform != "sleeper" or not settings.draft_id:
        return None
    try:
        raw = fetch_json(
            SLEEPER_DRAFT_URL.format(draft_id=settings.draft_id),
            f"draft_{settings.draft_id}",
        )
    except Exception as exc:                      # noqa: BLE001 - degrade, don't fabricate
        log.warning("could not resolve my_roster (slot_to_roster_id unavailable): %s", exc)
        return None
    roster_id = (raw.get("slot_to_roster_id") or {}).get(str(league.draft_slot))
    return int(roster_id) if roster_id is not None else None


def _my_roster_from_picks(
    picks: list, players: dict[str, Player], roster_id: int | None,
) -> list[Player]:
    """Picks carrying the user's roster_id are the user's own players.

    Manually marked players carry no roster_id (there may be no feed at all
    in manual mode, and a hand-marked pick could belong to any team), so they
    are never folded in here -- doing so would be a guess, not a lookup.
    """
    if roster_id is None:
        return []
    return [
        players[p.sleeper_id] for p in picks
        if p.roster_id == roster_id and p.sleeper_id in players
    ]


def _render_tick(
    picks: list, last_ok: float, players: dict[str, Player], settings: LeagueSettings,
    league: League, tunables: Tunables, limit: int, manual_gone: set[str],
    roster_id: int | None, status: str = "",
) -> None:
    """Build and print one frame of the draft board from the current picks.

    Pulled out of `_run` so a single iteration's work can be wrapped in its
    own try/except and driven a bounded number of times from tests.
    """
    drafted = {p.sleeper_id for p in picks} | manual_gone
    available = [p for pid, p in players.items() if pid not in drafted]
    my_roster = _my_roster_from_picks(picks, players, roster_id)
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
    print("\ntype part of a name to mark drafted, a number to disambiguate, 'u' to undo")
    if status:
        print(status)
    print("\n(ctrl-c to stop; run `preflight` before the draft)")


def _run(
    league: League, tunables: Tunables, limit: int, max_iterations: int | None = None,
    input_queue: "queue.Queue[str] | None" = None,
) -> int:
    """Poll the feed and redraw the board forever (or `max_iterations` times).

    The loop must never die: a crash here during a live draft leaves the user
    with nothing while their pick clock keeps running. Every iteration is two
    independently-guarded steps -- poll, then render -- so a failure in
    either is logged and the loop moves on to the next tick. `max_iterations`
    exists only so tests can drive a bounded number of ticks without a real
    `while True` or a blocking `time.sleep`.

    Manual mark-drafted input is read on a daemon thread onto `input_queue`
    (a plain stdlib Queue) and drained here once per tick -- never blocking
    the redraw on `input()`. A daemon thread was chosen over a select() poll
    on stdin because it needs no platform-specific fd handling and is
    trivially testable: pass `input_queue` directly and skip the thread.
    """
    players, settings = load_board_inputs(league, tunables)
    if not settings.draft_id:
        print("league has no draft_id yet", file=sys.stderr)
        return 1

    feed: PickFeed = SleeperFeed(settings.draft_id)
    roster_id = _lookup_roster_id(league, settings)
    mark_state = MarkDrafted()
    pending: list[Player] = []
    status = ""

    if input_queue is None:
        input_queue = queue.Queue()
        threading.Thread(target=_stdin_reader, args=(input_queue,), daemon=True).start()

    picks: list = []
    last_ok = time.time()
    interval = tunables.poll_seconds.get(league.platform, 5)
    interval = max(interval, 1)  # ponytail: floor to 1s to prevent busy-loop / API rate limiting

    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        while not input_queue.empty():
            pending, status = _handle_command(input_queue.get_nowait(), players, mark_state, pending)

        try:
            picks = feed.get_picks()
            last_ok = time.time()
        except Exception as exc:                      # noqa: BLE001 - loop must never die
            log.warning("poll failed: %s", exc)

        try:
            _render_tick(picks, last_ok, players, settings, league, tunables, limit,
                         mark_state.drafted, roster_id, status)
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
