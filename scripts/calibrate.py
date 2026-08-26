"""Measure how well the survival model predicted a COMPLETED draft.

Survival is only as good as its ADP mean, and which ADP best matches a real
draft room is an empirical question this settles in one run:

    .venv/bin/python scripts/calibrate.py <draft_id> <your_slot> [league]
    .venv/bin/python scripts/calibrate.py <log.jsonl> [more.jsonl ...] [league]

The first form reads a Sleeper draft's picks endpoint. The second reads journals
from `.draft/` -- either the manual-entry log `ffhelper.cli` writes, or a
transcript from `scripts/transcribe.py`. That is the ONLY record a hand-entered
draft leaves: Yahoo has no pick feed.

**Pass several journals and they are POOLED into one table per source.** One
draft is a hypothesis; the question here is which ADP mean predicts a real room,
and that needs more than one room. The seat is read out of each journal (your
own picks are recorded in it) and proven against the snake, so pooling drafts
you sat in different seats for is fine.

For every one of your turns it asks, for each still-available player, "will he
last to my next pick?", buckets the answers by what the model predicted, and
prints what actually happened. A well-calibrated model reads 10/30/50/70/90 down
the ACTUAL column. Flat means the model has no discriminating power.

Measured on the Task 13 mock (1398139615038185472, slot 5), FFC ADP gave
74/82/89/90/94 -- nearly flat -- while Sleeper ADP gave 4/17/52/91/100. But that
mock's CPU drafters pick off Sleeper's own list, so the comparison is circular.
**Run this against a mock with real humans before trusting either.**
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffhelper.cli import _restore_marks, load_board_inputs, resolve_settings
from ffhelper.config import League, get_league, load_config
from ffhelper.value import next_pick_number, survival_prob

PICKS_URL = "https://api.sleeper.app/v1/draft/{draft_id}/picks"
BUCKETS = 5


def room_discipline(players: dict, drafted_at: dict[str, int]) -> tuple[float, float, int]:
    """How closely did the room draft straight down this ADP list?

    -> (median rank taken, share taken at rank 1, picks scored)

    The reason this is printed rather than left to judgement: **a room that picks
    off the same list the model believes cannot test the model.** That is what
    made the Task 13 Sleeper mock's beautiful 4/17/52/91/100 worthless -- CPU
    drafters picking off Sleeper's own ADP, 36% of them taking the literal top
    available, median rank taken 2. Yahoo's autodraft does the same thing off
    Yahoo's list, so a mock lobby where most seats autopicked reintroduces
    exactly that circularity by a different route.

    A median around 1-2 means the room IS the list. Humans reaching, panicking
    and taking their guys run far looser than that.

    ponytail: O(pool) per pick, ~100k comparisons on a full draft, which is
    instant and needs no index to maintain.
    """
    by_adp = [p.sleeper_id for p in sorted(players.values(), key=lambda p: p.adp)]
    order = [pid for pid, _ in sorted(drafted_at.items(), key=lambda kv: kv[1])]
    gone: set[str] = set()
    ranks: list[int] = []
    for pid in order:
        if pid not in players:
            continue                      # drafted someone with no projection
        rank = 1
        for other in by_adp:
            if other == pid:
                break
            if other not in gone:
                rank += 1
        ranks.append(rank)
        gone.add(pid)
    if not ranks:
        return 0.0, 0.0, 0
    ranks_sorted = sorted(ranks)
    median = ranks_sorted[len(ranks_sorted) // 2]
    return median, sum(r == 1 for r in ranks) / len(ranks), len(ranks)


def picks_from_journal(path: Path) -> tuple[dict[str, int], list[int]]:
    """Reconstruct (drafted_at, my_turns) from a manual-entry draft log.

    The order marks were TYPED is the order players came off the board -- which
    is true only if every pick was typed, and typed in order. That assumption is
    load-bearing for every number this script prints, so `main` proves it against
    the snake pattern before scoring anything.

    Undone and taken-back marks are excluded: `_restore_marks` replays the same
    ops the live board did, and only ids that survive that replay get a slot.
    """
    state, _applied, _skipped = _restore_marks(path)
    seq: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            op = json.loads(line)
        except Exception:                                 # noqa: BLE001 - torn final line
            continue
        pid = op.get("id")
        # ponytail: first mark wins. A player marked, taken back and re-marked
        # keeps his original slot. The common correction -- unmark the wrong
        # name, mark the right one -- touches two different players and so is
        # unaffected; upgrade path is to track order inside MarkDrafted itself.
        if op.get("op") == "mark" and pid in state.drafted and pid not in seen:
            seen.add(pid)
            seq.append(pid)
    drafted_at = {pid: i for i, pid in enumerate(seq, 1)}
    my_turns = [i for i, pid in enumerate(seq, 1) if pid in state.mine]
    return drafted_at, my_turns


def snake_turns(slot: int, num_teams: int, total_picks: int) -> list[int]:
    """The pick numbers seat `slot` owns in a snake draft, up to `total_picks`."""
    turns = []
    rnd = 1
    while True:
        pick = (rnd - 1) * num_teams + (slot if rnd % 2 else num_teams - slot + 1)
        if pick > total_picks:
            return turns
        turns.append(pick)
        rnd += 1


LEAGUE_FROM_LOG = re.compile(r"^(?P<league>.+?)-\d{4}-\d{2}-\d{2}(?:-.*)?$")


def load_draft(path: Path, num_teams: int, slot_override: int | None) -> tuple:
    """One hand-entered or transcribed draft. -> (drafted_at, turns, slot).

    The seat is INFERRED, not asked for: a journal already records which picks
    were yours (`mine`), and in a snake the first of those IS the seat. Asking
    for it again is how the first real transcript got scored against another
    manager -- the argument and `config.toml` simply disagreed.

    The inference is then PROVEN against the snake before anything is scored.
    Journal pick numbers are only as good as the entry: miss one pick and every
    number after it shifts, which quietly moves every survival horizon.
    """
    drafted_at, my_turns = picks_from_journal(path)
    if not my_turns:
        raise ValueError(
            f"{path.name}: no picks are marked as yours. In a hand-entered draft "
            "those are\n  the ones typed with 'me <player>'; a transcript marks "
            "them from your seat.")
    slot = slot_override or my_turns[0]
    expected = snake_turns(slot, num_teams, len(drafted_at))
    if my_turns != expected:
        raise ValueError(
            f"{path.name}: does not line up with seat {slot} of a {num_teams}-team "
            f"snake.\n  your picks   : {my_turns}\n  seat {slot} owns : {expected}"
            f"\n  {len(drafted_at)} marks total."
            "\n  Usual causes: a pick was never entered, picks were entered out of "
            "order, or\n  num_teams in config.toml does not match the lobby.")
    # One evaluation per CONSECUTIVE PAIR of your turns: stand at each turn and
    # ask what survives to the next one. The last turn is dropped because it has
    # no next pick to survive to.
    #
    # This was `[my_turns[0]] + my_turns[:-1]`, which scored the FIRST turn
    # twice -- and the first turn is the earliest board state, where survival
    # probabilities are most extreme, so the duplicate pulled the whole table.
    return drafted_at, my_turns[:-1], slot


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    logs = [Path(a) for a in argv if a.endswith(".jsonl")]
    numeric = [int(a) for a in argv if a.isdecimal()]
    names = [a for a in argv if not a.endswith(".jsonl") and not a.isdecimal()]
    slot_override = numeric[0] if numeric and logs else None

    config_path = Path(__file__).resolve().parent.parent / "config.toml"
    leagues, tun = load_config(config_path)

    drafts: list[tuple] = []          # (label, drafted_at, turns, slot)
    if logs:
        derived = {LEAGUE_FROM_LOG.match(p.stem).group("league")
                   if LEAGUE_FROM_LOG.match(p.stem) else p.stem for p in logs}
        if names:
            league_name = names[0]
        elif len(derived) == 1:
            league_name = derived.pop()
        else:
            # Pooling assumes ONE league: team count and scoring must match or
            # the buckets are being added across different draft shapes.
            print(f"these logs name different leagues ({sorted(derived)}). Pass the "
                  "league\nexplicitly, or score them separately.")
            return 1
        base = get_league(leagues, league_name)
        settings = resolve_settings(base)
        for path in logs:
            if not path.exists():
                print(f"no such draft log: {path}")
                return 1
            try:
                drafted_at, turns, slot = load_draft(path, settings.num_teams, slot_override)
            except ValueError as exc:
                print(f"REFUSING TO SCORE -- {exc}")
                return 1
            drafts.append((path.name, drafted_at, turns, slot))
    else:
        if len(argv) < 2 or not numeric:
            print(__doc__)
            return 2
        draft_id, slot = names[0], numeric[0]
        picks = sorted(
            json.load(urllib.request.urlopen(PICKS_URL.format(draft_id=draft_id), timeout=10)),
            key=lambda r: r["pick_no"],
        )
        if not picks:
            print(f"draft {draft_id} has no picks yet -- run this after it completes")
            return 1
        my_turns = [p["pick_no"] for p in picks if p.get("draft_slot") == slot]
        if not my_turns:
            print(f"no picks carry draft_slot {slot}; seats present: "
                  f"{sorted({p.get('draft_slot') for p in picks})}")
            return 1
        league_name = names[1] if len(names) > 1 else "sleeper-main"
        base = get_league(leagues, league_name)
        settings = resolve_settings(base)
        drafts.append((draft_id,
                       {p["player_id"]: p["pick_no"] for p in picks},
                       my_turns[:-1], slot))

    num_teams = settings.num_teams
    for label, drafted_at, _turns, slot in drafts:
        print(f"draft {label}: {len(drafted_at)} picks, seat {slot} of {num_teams}"
              + ("  (seat inferred from the log)" if not slot_override and logs else ""))
    if slot != base.draft_slot:
        # Not fatal -- replaying someone else's seat is legitimate -- but it is
        # the slip that scored the first real transcript against another manager.
        print(f"NOTE: seat {slot} is NOT {league_name!r}'s configured draft_slot "
              f"({base.draft_slot}).")

    for adp_source in ("ffc", "sleeper"):
        league = League(**{**base.__dict__, "adp_source": adp_source})
        players, _ = load_board_inputs(league, tun)

        buckets: dict[float, list[int]] = {}
        discipline = []
        for _label, drafted_at, turns, slot in drafts:
            discipline.append(room_discipline(players, drafted_at))
            for cur in turns:
                nxt = next_pick_number(cur, slot, num_teams)
                for pid, p in players.items():
                    if drafted_at.get(pid, 10**9) < cur:
                        continue                              # already gone
                    pred = survival_prob(p, nxt, cur)
                    if pred < 0.02 or pred > 0.98:
                        continue                              # uninformative band
                    key = int(pred * BUCKETS) / BUCKETS
                    cell = buckets.setdefault(key, [0, 0])
                    cell[0] += 1
                    cell[1] += drafted_at.get(pid, 10**9) >= nxt

        medians = [d[0] for d in discipline]
        at_top = sum(d[1] * d[2] for d in discipline) / max(sum(d[2] for d in discipline), 1)
        turn_count = sum(len(d[2]) for d in drafts)
        print(f"\nADP SOURCE: {adp_source}   "
              f"({len(drafts)} draft(s), {turn_count} turns)")
        print(f"  room discipline: median rank taken {medians if len(medians) > 1 else medians[0]}, "
              f"{at_top:.0%} took the top available")
        if max(medians) <= 2:
            print("  ^^ THIS ROOM IS THE LIST. Autodraft or bots pick straight down "
                  "an ADP\n     ranking, so the table below is largely circular -- "
                  "it measures the\n     list against itself. See TODO.md section 12.")
        print(f"  {'model says':<16}{'n':>6}{'actually survived':>20}")
        for key in sorted(buckets):
            n, survived = buckets[key]
            print(f"  {key:.0%}-{key + 1 / BUCKETS:.0%}{'':<8}{n:>6}{survived / n:>19.0%}")
    print("\nIdeal reads 10/30/50/70/90 down the actual column. Flat = no signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
