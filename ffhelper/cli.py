"""Terminal draft board. Phase 3 replaces render() with Dash; the engine is
identical either way.
"""
import argparse
import json
import logging
import queue
import sys
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import (
    LeagueSettings, Player, SLEEPER_ADP_FIELD, adp_format_for, apply_ffc_adp,
    apply_projections, apply_sleeper_adp, fetch_json, load_ffc_adp, load_players,
    load_projections, load_sleeper_settings, norm_name,
)
from ffhelper.feeds import Pick, PickFeed, SleeperFeed
from ffhelper.value import Row, build_board, detect_run, is_bench_only, next_pick_number

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SEASON = "2026"

# Hand-typed marks are journalled here so a mis-hit ctrl-C does not cost ~100
# re-typed names in a league with no feed. Gitignored -- it is draft state.
# Anchored to ROOT, not cwd: a relative path means the log you recover depends
# on which directory you happened to launch from, and the one time that matters
# is the restart mid-draft when you are not thinking about your shell.
DRAFT_LOG_DIR = ROOT / ".draft"
SLEEPER_DRAFT_URL = "https://api.sleeper.app/v1/draft/{draft_id}"
# Validated at load, not at first use: an unknown value must fail at preflight,
# not silently fall through to FFC halfway through a draft. "yahoo" is
# deliberately absent -- see League.adp_source.
ADP_SOURCES = {"ffc", "sleeper"}


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
    """Manual mark-drafted state: player_ids hand-marked gone, which of those
    are the user's own roster, and a full LIFO undo stack -- `_history` is
    unbounded, so repeated `undo()` walks back through every mark made this
    session, one at a time, not just the most recent one.

    Only ids are tracked -- the pool itself lives in `players` and is
    filtered by `drafted` exactly like feed-reported picks are, so the board
    never has to know which source removed a player. `mine` is the subset of
    `drafted` the user explicitly marked as their own pick (see
    `_handle_command`'s "me " prefix) -- never inferred -- and is what lets a
    feed-less draft fold self-marked picks into `my_roster`.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path
        # (player_id, was in `drafted`, was in `mine`) BEFORE the call that
        # pushed it. undo() restores that membership verbatim, which is why the
        # same history serves mark, claim and unmark without a direction flag.
        # An entry is pushed only when something actually changed, so `u` never
        # burns a turn on a no-op.
        self._history: list[tuple[str, bool, bool]] = []
        self._marked: set[str] = set()
        self._mine: set[str] = set()

    def _record(self, player_id: str) -> None:
        self._history.append((player_id, player_id in self._marked, player_id in self._mine))

    def attach_log(self, path: Path) -> None:
        """Start journalling from here on. Called after a replay, never before:
        arming it first would append the restored log back onto itself."""
        self._log_path = path

    def _log(self, **op: object) -> None:
        """Append one op to the draft log. NEVER raises.

        Persistence is insurance, not a dependency: if the log cannot be
        written the draft carries on without a safety net, because losing the
        net is survivable and losing the board mid-pick is not. Opened and
        closed per op so the bytes reach the OS immediately -- a killed process
        cannot take a buffer down with it. No fsync: the failure being defended
        against is ctrl-C or a closed terminal, not loss of power.
        """
        if self._log_path is None:
            return
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(op) + "\n")
        except Exception as exc:                      # noqa: BLE001 - never fatal
            log.warning("could not write draft log %s: %s", self._log_path, exc)
            self._log_path = None                     # warn once, not per pick

    def mark(self, player_id: str, mine: bool = False) -> None:
        """Idempotent per FIELD, not per call. Marking an already-marked player
        again is a no-op, but CLAIMING an already-marked player still works --
        recording a pick and then realising it was your own is a normal thing to
        do against a pick clock, and dropping the claim silently would compute
        MARG against a roster missing your own player.
        """
        if player_id in self._marked and (not mine or player_id in self._mine):
            return                          # nothing would change
        self._record(player_id)
        self._marked.add(player_id)
        if mine:
            self._mine.add(player_id)
        self._log(op="mark", id=player_id, mine=mine)

    def unmark(self, player_id: str) -> None:
        """Take one mark back without unwinding everything made after it.

        `undo` is a single LIFO, so correcting a mistake from ten picks ago used
        to mean ten undos and nine retypes -- unusable against a pick clock in a
        draft where every pick is hand-entered. This reaches the one player.
        """
        if player_id not in self._marked:
            return                          # not marked: no-op, and no history
        self._record(player_id)
        self._marked.discard(player_id)
        self._mine.discard(player_id)
        self._log(op="unmark", id=player_id)

    def undo(self) -> None:
        if not self._history:
            return                          # nothing to undo: no-op, never raises
        player_id, was_marked, was_mine = self._history.pop()
        (self._marked.add if was_marked else self._marked.discard)(player_id)
        (self._mine.add if was_mine else self._mine.discard)(player_id)
        # Logged like any other op. An unlogged undo would be replayed away --
        # a restart would resurrect a mark the user had already taken back.
        self._log(op="undo")

    @property
    def drafted(self) -> set[str]:
        return set(self._marked)

    @property
    def mine(self) -> set[str]:
        return set(self._mine)


def _apply(mark_state: MarkDrafted, player: Player, action: str) -> str:
    """Carry out one resolved command against one unambiguous player."""
    where = f"({player.position} {player.team})"
    if action == "unmark":
        mark_state.unmark(player.sleeper_id)
        return f"unmarked {player.name} {where} -- back on the board"
    mark_state.mark(player.sleeper_id, mine=action == "mine")
    return f"marked {player.name} {where}" + (" as yours" if action == "mine" else "")


def _handle_command(
    line: str, pool: dict[str, Player], mark_state: MarkDrafted,
    pending: list[Player], pending_action: str = "",
) -> tuple[list[Player], str, str]:
    """Process one line of manual input; pure and stdin-free so it is directly
    testable. `pending` is the disambiguation list left open by the previous
    command (empty when none is open); `pending_action` says which command that
    open disambiguation belongs to, so picking a number from it does what the
    user originally asked for. Returns the new pending list, the new
    pending_action, and a status line for the caller to print.

    Actions are "" (mark drafted), "mine" and "unmark".

    Protocol: "u"/"undo" reverses the last change, whatever it was -- there is
    one shared LIFO history. A bare number, while a disambiguation list is open,
    selects from it. Anything else is a name search, optionally prefixed:

      "me " marks the match as the user's own pick rather than just drafted --
      "me gibbs" is fast enough to type against a 120-second pick clock.

      "-" takes a mark back -- "-gibbs". It searches ONLY players marked by
      hand, because those are the only ones it can take back: a feed-reported
      pick is not in `mark_state`, and pretending to un-draft one would put a
      genuinely gone player back on the board. Scoping this way also resolves
      "-robinson" outright when only one Robinson was marked.

    A search with exactly one match applies directly -- that is not "picking the
    first" because there is only one candidate. A search with several matches
    opens the disambiguation list instead of guessing, for every action alike --
    disambiguation is never bypassed, because taking the wrong player back onto
    the board is the same class of error as marking the wrong one gone.
    """
    line = line.strip()
    if not line:
        return pending, pending_action, ""
    if line.lower() in ("u", "undo"):
        mark_state.undo()
        return [], "", "undid last change"
    # isdecimal(), not isdigit(): isdigit() is True for superscripts ('²') and
    # other numeric forms that int() then refuses. isdecimal() is exactly the
    # set int() accepts.
    if pending and line.isdecimal():
        idx = int(line)
        if 1 <= idx <= len(pending):
            return [], "", _apply(mark_state, pending[idx - 1], pending_action)
        return pending, pending_action, f"choose 1-{len(pending)}, or type a new search"

    if line.startswith("-"):
        action, query = "unmark", line[1:].strip()
    elif line[:3].lower() == "me ":
        action, query = "mine", line[3:]
    else:
        action, query = "", line

    scope = pool
    if action == "unmark":
        marked = mark_state.drafted
        scope = {pid: p for pid, p in pool.items() if pid in marked}

    matches = find_players(scope, query)
    if not matches:
        if action == "unmark":
            return [], "", f"no marked player matches {query!r}"
        return [], "", f"no match for {line!r}"
    if len(matches) == 1:
        return [], "", _apply(mark_state, matches[0], action)
    listing = "; ".join(f"{i}:{p.name} {p.position}-{p.team}" for i, p in enumerate(matches, 1))
    verb = "unmark" if action == "unmark" else "mark"
    return matches, action, f"multiple matches, type a number to {verb} -- {listing}"


def _split_commands(line: str) -> list[str]:
    """Split one typed line into commands on commas.

    Catching up is where a hand-entered draft is won or lost: falling five picks
    behind means five names, and one line of `a, b, c, d, e` is one round trip
    instead of five. Measured need -- a 12-team Yahoo mock on a 30s clock hands
    you roughly one pick every eight seconds and cannot be kept up with one name
    at a time.

    Safe to split unconditionally: no player, team or defense name in the pool
    contains a comma, and a disambiguation number never does either. Empty
    fragments (a trailing comma, a double comma) are dropped rather than sent on
    as blank commands.
    """
    return [part for part in (p.strip() for p in line.split(",")) if part]


def _stdin_reader(q: "queue.Queue[str]") -> None:
    """Daemon-thread target: blocks reading stdin lines so the render loop
    never has to. Runs in its own thread; any failure (stdin unavailable,
    closed, or captured e.g. under a test runner) ends the thread and the
    queue simply stays empty, same as no input at all -- but that failure is
    logged, not swallowed, because a silently-dead reader looks identical to
    "no one has typed anything yet" for the rest of the session.
    """
    try:
        for raw_line in sys.stdin:
            q.put(raw_line.strip())
    except Exception as exc:                            # noqa: BLE001
        log.warning("stdin reader stopped unexpectedly (%s) -- "
                     "manual input is disabled for the rest of this session", exc)
    else:
        log.warning("stdin closed -- manual input is disabled for the rest of this session")


def _wait_for_input(input_queue: "queue.Queue[str]", timeout: float) -> str | None:
    """Block until a command is typed or `timeout` elapses. -> the line, or None.

    This is what makes typing feel instant, and it is not a micro-optimisation:
    the loop used to `time.sleep(interval)` and drain the queue only at tick
    boundaries, so a name typed just after a tick sat unprocessed for up to a
    full poll interval. On Yahoo that is 12 seconds -- spent waiting on a feed
    that does not exist, in the one mode where the board can ONLY change because
    you typed something. It cost a full round of a live mock draft before the
    cause was found, because the delay looks exactly like a slow terminal.

    Blocking on the queue instead means the poll clock still paces the network
    and nothing else. A `queue.Queue` is already the hand-off between the stdin
    thread and this loop; this just uses the part of it that waits.
    """
    try:
        return input_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def render(
    board: list[Row], limit: int, stale_seconds: float | None,
    my_roster: list[Player], runs: dict[str, int], divergence_flag_slots: int = 10,
) -> str:
    lines: list[str] = []
    if stale_seconds is None:
        # No feed at all (manual-only league) -- there is nothing to be
        # stale, so say THAT plainly instead of showing a staleness clock
        # that has nothing to measure, or letting silence read as "nothing
        # drafted yet".
        lines.append("--  MANUAL MODE: no pick feed -- picks are entered by hand only  --")
    elif stale_seconds > 15:
        lines.append(f"!!  FEED STALE {stale_seconds:.0f}s  -- board may be out of date")
    if is_bench_only(board):
        # Degrade, never fabricate. Every starting slot is full, so no available
        # player improves the lineup and there is nothing left to rank on. Say
        # that instead of presenting the residual ordering as a recommendation:
        # at pick 164 of the Task 13 mock this state produced a confident case
        # for a third quarterback, and then for a second kicker.
        lines.append("--  STARTING LINEUP FULL: no player improves your starters.  --")
        lines.append("--  These are BENCH picks, ordered by value over league replacement.  --")
        lines.append("--  The tool has no model of upside or handcuffs -- trust yourself here.  --")
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
        # divergence is None for a player the market has never priced -- a third
        # of the pool. No opinion is not agreement, so he gets no flag and the
        # column shows a dash rather than a fabricated 0.
        if r.divergence is not None and abs(r.divergence) >= divergence_flag_slots:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        if r.player.bye:
            flags.append(f"bye{r.player.bye}")
        div = "-" if r.divergence is None else f"{r.divergence:+d}"
        lines.append(
            f"{i:<3} {r.player.name[:24]:<24} {r.player.position:<4} {r.vona:>7.1f} "
            f"{r.vbd:>7.1f} {r.marginal:>7.1f} {r.tier:>4} {r.survival:>6.0%} "
            f"{div:>5}  {' '.join(flags)}"
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

    `league.draft_id`, when set, overrides whichever draft the settings name --
    see `League.draft_id`. Announced on stderr, never silent: pointing the feed
    at a different draft than the league's own is exactly the kind of thing that
    must not be discovered halfway through a real draft.
    """
    settings = _resolve_settings_source(league)
    if league.draft_id and league.draft_id != settings.draft_id:
        print(f"draft override  : feed points at draft {league.draft_id} "
              f"(league {league.name!r} reports {settings.draft_id}); "
              f"scoring and roster still come from {league.name!r}", file=sys.stderr)
        settings = replace(settings, draft_id=league.draft_id)
    return settings


def _resolve_settings_source(league: League) -> LeagueSettings:
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
    """Cold start: fetch everything, join by ID, then enrich with FFC.

    Sleeper ADP is applied first as the ID-keyed baseline, then FFC's fuzzy
    join runs. Whether FFC OVERWRITES that baseline is `league.adp_source`; the
    join itself always runs, because bye weeks come from nowhere else.
    """
    settings = resolve_settings(league, season)
    players = load_players()
    projections = load_projections(season)

    apply_projections(players, projections, settings.scoring)
    fmt = league.adp_format or adp_format_for(settings)
    apply_sleeper_adp(players, projections, SLEEPER_ADP_FIELD.get(fmt, f"adp_{fmt.replace('-', '_')}"))

    if league.adp_source not in ADP_SOURCES:
        raise ValueError(
            f"league {league.name!r} has adp_source={league.adp_source!r}; "
            f"expected one of {sorted(ADP_SOURCES)}. "
            f"(\"yahoo\" is not implemented -- the API is not available yet.)"
        )
    teams = league.adp_teams or settings.num_teams
    unmatched = apply_ffc_adp(players, load_ffc_adp(fmt, teams, int(season)),
                              set_adp=league.adp_source == "ffc")
    if unmatched:
        # Printed, never silently dropped.
        print(f"FFC: {len(unmatched)} unmatched -> {', '.join(unmatched[:15])}"
              + (" ..." if len(unmatched) > 15 else ""), file=sys.stderr)

    # Drop players with no projection: they cannot be ranked.
    return {pid: p for pid, p in players.items() if p.proj_pts > 0}, settings


def _my_roster_from_picks(
    picks: list, players: dict[str, Player], my_slot: int | None,
) -> list[Player]:
    """Picks made from the user's own seat are the user's own players.

    Matched on `draft_slot`, NOT `roster_id`. A Sleeper mock draft returns
    `roster_id: None` on every pick, so the previous roster_id match silently
    produced an empty roster for a whole 180-pick draft -- and an empty roster
    makes MARG meaningless, which is what let the board keep recommending a
    quarterback after one was already drafted. `draft_slot` is present in both
    mocks and league drafts and needs no `slot_to_roster_id` lookup, since it
    is exactly the value already configured as `league.draft_slot`.

    Manually marked players carry no seat (there may be no feed at all in
    manual mode, and a hand-marked pick could belong to any team), so they are
    never folded in here -- that would be a guess, not a lookup. See
    `_combine_my_roster` for where self-marked players ("me ") are added back.
    """
    if my_slot is None:
        return []
    mine = [
        players[p.sleeper_id] for p in picks
        if p.draft_slot == my_slot and p.sleeper_id in players
    ]
    if picks and not mine and not any(p.draft_slot is not None for p in picks):
        # Degrade, never fabricate: an empty roster here is indistinguishable
        # from "you have not picked yet", and that silence is exactly how the
        # roster_id version hid for an entire draft.
        log.warning("no pick carries a draft_slot -- my_roster cannot be resolved, "
                    "so MARG is computed against an empty roster. Use 'me <player>' "
                    "to mark your own picks by hand.")
    return mine


def _draft_log_path(league: League) -> Path:
    """Where this league's hand-typed marks are journalled.

    Dated, so a mock on one day and the real draft on another never share a
    file -- replaying a mock's marks into a live draft would be far worse than
    having no log at all.

    ponytail: a draft crossing local midnight starts a fresh file. The restore
    banner reports 0 marks, which is visible; the fix would be to key on
    draft_id, which Yahoo (the platform that needs this) does not have.
    """
    return DRAFT_LOG_DIR / f"{league.name}-{date.today().isoformat()}.jsonl"


def _restore_marks(path: Path) -> tuple[MarkDrafted, int, int]:
    """Rebuild mark state from a draft log. -> (state, ops applied, lines skipped)

    Replays OPS rather than restoring a snapshot, so `_history` is rebuilt too
    and `u` still works for everything typed before the crash.

    Never raises: a corrupt line -- most likely a final op truncated by the
    hard kill this exists to survive -- costs that one op and is counted, not
    the rest of the draft. Logging is armed only AFTER the replay, so reading
    the log back does not append it to itself.
    """
    state = MarkDrafted()
    applied = skipped = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except Exception as exc:                          # noqa: BLE001 - never fatal
        log.warning("could not read draft log %s: %s", path, exc)
        lines = []

    for line in lines:
        if not line.strip():
            continue
        try:
            op = json.loads(line)
            if op["op"] == "mark":
                state.mark(op["id"], mine=bool(op.get("mine")))
            elif op["op"] == "unmark":
                state.unmark(op["id"])
            elif op["op"] == "undo":
                state.undo()
            else:
                raise ValueError(f"unknown op {op['op']!r}")
        except Exception:                             # noqa: BLE001 - never fatal
            skipped += 1
            continue
        applied += 1

    state.attach_log(path)
    return state, applied, skipped


def _claims_overruled_by_feed(
    picks: list, mine_ids: set[str], my_slot: int | None,
) -> set[str]:
    """Self-marked ids the feed attributes to a DIFFERENT seat.

    `me <player>` is a claim, and the feed is the authority on who actually
    drafted whom. A claim the feed contradicts is provably wrong, and leaving it
    standing computes MARG against a roster the user does not have -- the same
    class of wrongness as Task 13's empty `my_roster`, just inverted.

    Two guards, both of which turn a helpful correction into a roster-wiping
    disaster if dropped:

    - `my_slot is None` returns nothing. With no slot configured, every pick's
      slot differs from `None`, so a naive `!=` would overrule EVERY claim.
    - A pick with no `draft_slot` attributes to nobody and is ignored. Guessing
      from it would be fabrication, and it is the exact shape a Sleeper mock
      once returned for every pick in a 180-pick draft.
    """
    if my_slot is None:
        return set()
    return {
        p.sleeper_id for p in picks
        if p.sleeper_id in mine_ids and p.draft_slot is not None and p.draft_slot != my_slot
    }


def _combine_my_roster(
    feed_roster: list[Player], mine_ids: set[str], players: dict[str, Player],
) -> list[Player]:
    """Merge feed-detected roster players with explicitly self-marked ones.

    A player can reach `mine_ids` after the feed already reported the same
    pick under the user's roster_id (self-marked on a hunch, feed catches up
    a tick later) -- `seen` guards against listing that player twice.
    """
    seen = {p.sleeper_id for p in feed_roster}
    extra = [players[pid] for pid in sorted(mine_ids) if pid in players and pid not in seen]
    return feed_roster + extra


class NullFeed:
    """A `PickFeed` that reports no picks, ever.

    Selected -- see `_select_feed` -- when a league has no draft_id yet, or
    is on a platform with no real feed implementation (Yahoo, ESPN, CBS, a
    friend's league...). The board still renders in full, driven entirely by
    manual marks; nothing downstream needs to know or care that this feed is
    empty by construction rather than by network result.
    """

    def get_picks(self) -> list[Pick]:
        return []


def _select_feed(league: League, settings: LeagueSettings) -> tuple[PickFeed, bool]:
    """Choose this league's pick feed -- one explicit check, not a chain of
    silent fallbacks.

    Sleeper is the only platform with a real feed today. A Sleeper league
    with a resolved draft_id gets `SleeperFeed`; every other case (no
    draft_id yet, or a platform with no feed implementation at all) gets
    `NullFeed`, so `run` still starts and renders a full board from manual
    marks. The bool says whether a real feed is live, purely so the caller
    can give the board an honest staleness story instead of measuring time
    against a feed that was never there.
    """
    if league.platform == "sleeper" and settings.draft_id:
        return SleeperFeed(settings.draft_id), True
    return NullFeed(), False


def _manual_mine(log_path, typed_mine: set[str], draft_slot: int | None,
                 num_teams: int, has_feed: bool) -> set[str]:
    """Which drafted players are YOURS, for a board with no pick feed.

    The web board derives this from your seat and the journal's pick order; the
    terminal used to read only explicit `me` marks. Clicking never writes those,
    so a ctrl-C handover from the web board arrived here with an EMPTY roster --
    MARG meaningless, the sort's roster-need gate disabled, which is Task 13
    defect #1 landing exactly when the fallback is being reached for.

    A league WITH a feed is untouched: there, `draft_slot` on the feed's own
    picks is authoritative, and deriving from journal order could contradict it.
    So a league with a feed does not change.

    Explicit statements win over the derived guess in BOTH directions, which is
    why `explicit_not_mine` is subtracted every call rather than once: `auto_mine`
    recomputes from pick POSITION alone and has no memory of an override.

    An unset seat is NOT guarded here: `auto_mine` already returns nothing when
    it has no seat, and that guard is tested and mutation-covered. A second copy
    would be a second rule to keep in step.
    """
    if has_feed:
        return typed_mine
    # ponytail: imported here, not at module scope, because board.py imports
    # THIS module -- a top-level import would be a cycle. The plan already
    # schedules the real fix for after 2026-09-06, when cli.py adopts board.py
    # and the journal helpers move across for good.
    from ffhelper.board import auto_mine, explicit_not_mine, marks_in_entry_order
    derived = auto_mine(marks_in_entry_order(log_path), draft_slot, num_teams)
    return (derived - explicit_not_mine(log_path)) | typed_mine


def _render_tick(
    picks: list, last_ok: float | None, players: dict[str, Player], settings: LeagueSettings,
    league: League, tunables: Tunables, limit: int, manual_gone: set[str],
    manual_mine: set[str], my_slot: int | None, status: str = "",
) -> None:
    """Build and print one frame of the draft board from the current picks.

    Pulled out of `_run` so a single iteration's work can be wrapped in its
    own try/except and driven a bounded number of times from tests.
    """
    # The current pick must reflect every player known to be drafted, not just
    # what the feed reported -- in manual (or feed-less) mode `picks` is
    # permanently empty, and `len(picks) + 1` would freeze the board at pick 1
    # forever regardless of how many players were hand-marked. `drafted` is
    # already the union used to filter the available pool; the pick count
    # must be derived from that SAME set so the board can't disagree with
    # itself about who's off the board. Set union means a player reported by
    # both the feed and a manual mark is counted once, not twice.
    #
    # The count alone is not enough either: `parse_sleeper_picks` skips
    # malformed rows, so one bad row would shift the horizon down by one for
    # the rest of the draft. The feed's own highest pick_no is authoritative
    # where it exists, so take whichever is further along.
    drafted = {p.sleeper_id for p in picks} | manual_gone
    highest = max((p.pick_no for p in picks), default=0)
    current_pick = max(len(drafted), highest) + 1
    available = [p for pid, p in players.items() if pid not in drafted]
    feed_roster = _my_roster_from_picks(picks, players, my_slot)
    # A claim the feed contradicts is dropped from the roster but NOT from
    # `manual_gone` -- the player really is drafted, just not by this user.
    overruled = _claims_overruled_by_feed(picks, manual_mine, my_slot)
    my_roster = _combine_my_roster(feed_roster, manual_mine - overruled, players)
    recent = [players[p.sleeper_id].position for p in picks[-8:] if p.sleeper_id in players]

    board = build_board(
        available, my_roster, settings.roster_slots, settings.num_teams,
        current_pick=current_pick, my_slot=league.draft_slot, tunables=tunables,
        # The FULL pool, not `available`: replacement level is a property of the
        # league, and drawing it from the draining pool inflated every late-round
        # number. See build_board's docstring.
        replacement_pool=list(players.values()),
    )
    print("\033[2J\033[H", end="")                # clear screen
    stale_seconds = None if last_ok is None else time.time() - last_ok
    print(render(board, limit, stale_seconds, my_roster, detect_run(recent),
                 tunables.divergence_flag_slots))
    for pid in sorted(overruled):
        seat = next(p.draft_slot for p in picks if p.sleeper_id == pid)
        name = players[pid].name if pid in players else pid
        # Stays up until the stale claim is cleared, which is the point: the
        # roster on screen no longer matches what the user typed.
        # ponytail: the message names the player and the help line below carries
        # the notation, so no computed "-<handle>" hint. Both ways of building
        # one are wrong: the raw last token of "Marvin Harrison Jr." is "Jr.",
        # and norm_name collapses whitespace ("-brandonaubrey"). A hint that
        # does not match is worse than no hint at the table.
        print(f"CLAIM OVERRULED: the feed says {name} was taken from seat {seat}, "
              f"not yours -- dropped from your roster. Clear the stale claim with '-<name>'.")
    if league.draft_slot:
        nxt = next_pick_number(current_pick, league.draft_slot, settings.num_teams)
        # Is the pick on the clock RIGHT NOW yours? `next_pick_number` is
        # strictly-after, so ask it from one pick earlier and see if it lands here.
        if next_pick_number(current_pick - 1, league.draft_slot, settings.num_teams) == current_pick:
            print(f"\n>>> PICK {current_pick} IS YOURS -- YOU ARE ON THE CLOCK <<<"
                  f"   (next after this: {nxt})")
        else:
            print(f"\npick {current_pick}   your next pick: {nxt} "
                  f"({nxt - current_pick} away)")
    print("\nname = mark drafted | \"me \" = your own pick | \"-\" = take a mark "
          "back | number = disambiguate | 'u' = undo"
          "\ncommas enter several at once:  nacua, me chase, gibbs")
    if status:
        print(status)
    print("\n(ctrl-c to stop; run `preflight` before the draft)")


def _print_restore_banner(log_path, mark_state, applied: int, skipped: int,
                          draft_slot: int | None, num_teams: int,
                          has_feed: bool) -> None:
    """Report what a restart recovered, counting the roster you will SEE.

    Not `mark_state.mine`, which counts only typed `me` claims: a draft entered
    by clicking on the web board has none, so this banner said "0 yours" on top
    of a board listing nine players. During a ctrl-C handover that reads as "the
    roster is gone", which is the failure the seat derivation exists to prevent.
    """
    if not (applied or skipped):
        return
    mine = _manual_mine(log_path, mark_state.mine, draft_slot, num_teams, has_feed)
    print(f"restored {applied} mark(s) from {log_path}"
          + (f" ({skipped} unreadable line(s) skipped)" if skipped else "")
          + f"\n  -> {len(mark_state.drafted)} drafted, {len(mine)} yours."
          " Delete that file to start fresh.")


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

    A league with no usable pick feed (no draft_id yet, or a platform with no
    feed implementation -- Yahoo, ESPN, CBS, a friend's league) is a
    first-class case, not an error: `_select_feed` hands back `NullFeed` and
    the board runs entirely from manual marks. This is the only way most
    users of this tool reach a live board at all.
    """
    players, settings = load_board_inputs(league, tunables)
    feed, has_feed = _select_feed(league, settings)

    # Journalled marks, restored first so a restart mid-draft picks up where the
    # last process died. Guarded like every other startup step: losing the
    # safety net must never be what stops the board from coming up.
    log_path = _draft_log_path(league)
    try:
        DRAFT_LOG_DIR.mkdir(exist_ok=True)
        mark_state, applied, skipped = _restore_marks(log_path)
        _print_restore_banner(log_path, mark_state, applied, skipped,
                              league.draft_slot, settings.num_teams, has_feed)
    except Exception as exc:                          # noqa: BLE001 - never fatal
        log.warning("draft log unavailable (%s); marks will not survive a restart", exc)
        mark_state = MarkDrafted()

    pending: list[Player] = []
    pending_action = ""
    status = ""

    if input_queue is None:
        input_queue = queue.Queue()
        threading.Thread(target=_stdin_reader, args=(input_queue,), daemon=True).start()

    picks: list = []
    last_frame: tuple | None = None
    last_ok: float | None = time.time() if has_feed else None
    interval = tunables.poll_seconds.get(league.platform, 5)
    interval = max(interval, 1)  # ponytail: floor to 1s to prevent busy-loop / API rate limiting

    iterations = 0
    next_poll = 0.0        # monotonic deadline; 0 forces a poll on the first tick
    while max_iterations is None or iterations < max_iterations:
        # Cleared every tick: a status set by a command belongs to the tick
        # it happened on. Without this reset, a message from an earlier tick
        # (when the queue was last non-empty) keeps re-printing on every
        # subsequent tick forever, since nothing else ever overwrites it.
        status = ""
        # Wait for a typed command OR for the next poll to fall due, whichever
        # comes first -- never a flat sleep. The poll interval paces the network
        # and nothing else; a keystroke wakes the loop immediately. See
        # `_wait_for_input`.
        first = _wait_for_input(input_queue, max(0.0, next_poll - time.monotonic()))
        lines = [] if first is None else [first]
        while not input_queue.empty():
            lines.append(input_queue.get_nowait())
        # Every command's message is KEPT, not overwritten. A batch of five
        # names produces five outcomes and any of them can be a miss or an open
        # disambiguation; showing only the last one would silently drop the
        # rest, which is invariant #3 broken in the exact mode that needs it
        # most. This also fixes the same overwrite for several lines typed
        # between two ticks.
        statuses: list[str] = []
        for line in lines:
            for command in _split_commands(line):
                # Guarded per COMMAND, not per drain: one bad line must not
                # discard the rest of the queue. This is the third per-tick
                # statement and obeys the same rule as the other two -- nothing
                # here propagates.
                try:
                    pending, pending_action, message = _handle_command(
                        command, players, mark_state, pending, pending_action
                    )
                except Exception as exc:              # noqa: BLE001 - loop must never die
                    log.warning("command %r failed: %s", command, exc)
                    message = f"could not handle {command!r} -- try again"
                if message:
                    statuses.append(message)
        status = "  |  ".join(statuses)

        # Only when it actually falls due. Waking on a keystroke must not turn
        # every character typed into a network request -- Sleeper IP-blocks
        # above ~1000 req/min and Yahoo's limits are undocumented.
        if time.monotonic() >= next_poll:
            try:
                picks = feed.get_picks()
                if has_feed:
                    last_ok = time.time()
            except Exception as exc:                  # noqa: BLE001 - loop must never die
                log.warning("poll failed: %s", exc)
            next_poll = time.monotonic() + interval

        # Redraw only when something actually changed. Polling stays at
        # `interval` so the feed is never behind, but a full screen-clear every
        # 5 seconds with identical content is unreadable churn -- you cannot
        # tell a real update from a repaint, and a status line can flash past
        # before it is read. While the feed is STALE the frame is always
        # redrawn, so the staleness counter keeps ticking up visibly.
        stale = last_ok is not None and (time.time() - last_ok) > 15
        frame = (len(picks), max((p.pick_no for p in picks), default=0),
                 frozenset(mark_state.drafted), frozenset(mark_state.mine), status)
        if frame != last_frame or stale or iterations == 0:
            try:
                _render_tick(picks, last_ok, players, settings, league, tunables, limit,
                             mark_state.drafted,
                             _manual_mine(log_path, mark_state.mine,
                                          league.draft_slot, settings.num_teams,
                                          has_feed),
                             league.draft_slot, status)
                # Only AFTER a successful draw. Marking the frame done before
                # rendering would make a failed render freeze the screen: the
                # next identical tick would dedup away the retry.
                last_frame = frame
            except Exception as exc:                  # noqa: BLE001 - loop must never die
                log.error("draft tick failed: %s", exc, exc_info=True)

        iterations += 1
    return 0


def _preflight(league: League, tunables: Tunables) -> int:
    """Validate everything before draft day. Run this the morning of."""
    ok = True
    players, settings = load_board_inputs(league, tunables)
    print(f"league          : {league.name} ({league.platform})")
    print(f"teams           : {settings.num_teams}")
    print(f"roster slots    : {settings.roster_slots}")
    print(f"scoring keys    : {len(settings.scoring)}  (pass_td={settings.scoring.get('pass_td')})")
    print(f"adp source      : {league.adp_source}")
    print(f"draft_id        : {settings.draft_id}")
    print(f"players w/ proj : {len(players)}")

    no_stdev = [p.name for p in players.values() if p.adp_stdev is None]
    print(f"missing stdev   : {len(no_stdev)}")
    if league.draft_slot is None:
        print("draft_slot      : NOT SET -- board will degrade to next-pick survival")
        ok = False
    elif not 1 <= league.draft_slot <= settings.num_teams:
        # Hand-entered and never guessed, so a typo is entirely possible -- and
        # an out-of-range slot silently produces wrong next-pick numbers for the
        # whole draft rather than failing.
        print(f"draft_slot      : {league.draft_slot} is OUT OF RANGE for "
              f"{settings.num_teams} teams -- every next-pick number will be wrong")
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
