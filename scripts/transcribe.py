"""Turn a finished draft's results page into a journal `calibrate.py` can score.

    .venv/bin/python scripts/transcribe.py <league> <your_slot> [results.txt]

Reads a pasted draft board (a file, or stdin) and writes
`.draft/<league>-<date>-transcript.jsonl` -- the same op format the live board
journals by hand.

**This is why a mock that ran too fast to type into is not a wasted mock.** Live
entry and calibration were coupled only by accident: survival is measured from
the ORDER players left the board, and a finished results page carries that order
with no clock attached.

Your own picks are marked from `slot` and the snake, not from the text -- sound
even if you autopicked, because calibration never reads your roster. Your picks
enter only as the turn boundaries between which the ROOM's picks are scored, and
those come from your seat.

Written against Yahoo's results page, whose rows look like:

    Round 2
    (1) jeremy - Cook III, James (Buf - RB)
    (4) Paul - Seattle (Sea - DEF)

That is: pick-within-round, the MANAGER's name, then "Surname[ Suffix], Given",
then team and position. Simpler one-per-line forms ("1. Ja'Marr Chase (Cin-WR)")
also parse.

Three things it refuses to do, each because the failure is silent otherwise:

- **Guess a name.** A line resolving to no player, or two, stops the run.
- **Trust line order when the page numbers its picks.** Round and pick-in-round
  reconstruct the true overall number, which is checked to be exactly 1..N with
  no gaps. A snake's even rounds run right-to-left, so a copy of the BOARD view
  arrives in the wrong order and would otherwise be scored happily.
- **Write to the live board's journal path.** `ffhelper.cli run` replays that
  file on startup; a transcript there would pour a finished draft into the next
  live board.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffhelper.cli import DRAFT_LOG_DIR, find_players, load_board_inputs
from ffhelper.config import get_league, load_config
from ffhelper.data import Player

ROUND = re.compile(r"^\s*round\s+(\d+)\b", re.I)
# "(4) " or "4. " / "4) " / "4: " -- the pick's number within its round.
PICK_NO = re.compile(r"^\s*(?:\((\d+)\)|(\d+)\s*[.):])\s*")
# Trailing "(Buf - RB)" / "(Cin-WR)". Team code first, position second.
TAIL = re.compile(r"\(([^)]*)\)\s*$")
POSITIONS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "PK": "K",
             "DEF": "DEF", "DST": "DEF", "D/ST": "DEF"}
SKIP = re.compile(r"^\s*(pick|player|team|pos|result)\b", re.I)


def parse_line(line: str) -> tuple[str, str | None, str | None, str | None] | None:
    """-> (name, position, team, manager) for a pick line, else None.

    `name` is put back into normal order: Yahoo writes "Cook III, James", which
    becomes "James Cook III" so that `norm_name`'s suffix stripping lines it up
    with the pool's "James Cook". A row with no comma is a team defense
    ("Denver"), left as-is because `resolve` joins those on the team code.
    """
    if not line.strip() or ROUND.match(line) or SKIP.match(line):
        return None
    text = PICK_NO.sub("", line.strip())

    position = team = None
    tail = TAIL.search(text)
    if tail:
        parts = [t for t in re.split(r"[\s\-,]+", tail.group(1).upper()) if t]
        for token in parts:
            if token in POSITIONS:
                position = POSITIONS[token]
            else:
                team = token
        text = text[: tail.start()]

    # "manager - Surname, Given" -> drop the manager. rsplit, not split: a
    # manager name may itself contain " - ", a player name never does (hyphens
    # in "Smith-Njigba" and "Amon-Ra" carry no surrounding spaces).
    manager, _, field = text.rpartition(" - ")
    field = (field or text).strip(" \t-–—")
    if "," in field:
        surname, _, given = field.partition(",")
        field = f"{given.strip()} {surname.strip()}".strip()
    return (field, position, team, manager.strip() or None) if field else None


def parse_board(text: str, num_teams: int) -> tuple[list[tuple], list[str]]:
    """-> (picks in draft order, ordering problems)

    Each pick is `(overall_or_None, name, position, team, manager)`. When the page
    numbers its picks and labels its rounds, the overall number is reconstructed
    as `(round - 1) * num_teams + pick` and the caller checks the run is
    complete; otherwise ordering falls back to the order lines appear.
    """
    picks, rnd = [], 0
    for line in text.splitlines():
        header = ROUND.match(line)
        if header:
            rnd = int(header.group(1))
            continue
        parsed = parse_line(line)
        if parsed is None:
            continue
        match = PICK_NO.match(line.strip())
        within = next((int(g) for g in (match.groups() if match else ()) if g), None)
        overall = (rnd - 1) * num_teams + within if (rnd and within) else None
        picks.append((overall, *parsed))

    numbered = [p[0] for p in picks if p[0] is not None]
    problems: list[str] = []
    if not numbered:
        return picks, problems              # unnumbered page: trust line order
    if len(numbered) != len(picks):
        problems.append(f"{len(picks) - len(numbered)} of {len(picks)} rows carry no "
                        "pick number -- cannot verify the order")
    elif sorted(numbered) != list(range(1, len(numbered) + 1)):
        missing = sorted(set(range(1, max(numbered) + 1)) - set(numbered))
        dupes = sorted({n for n in numbered if numbered.count(n) > 1})
        problems.append(
            f"the {len(numbered)} rows found are not a complete 1..{len(numbered)} run"
            + (f"; missing {missing[:12]}" if missing else "")
            + (f"; repeated {dupes[:12]}" if dupes else "")
            + ".\n  Most likely only part of the page was copied -- select from the "
              "first pick\n  to the last, including every round.")
    else:
        # Complete and unique, so the numbers are better evidence of order than
        # the order rows happen to appear in. Sorting makes a copy of the BOARD
        # view work too: a snake's even rounds run right-to-left there, and
        # scoring that as written would invert every other round's horizons.
        picks.sort(key=lambda row: row[0])
    return picks, problems


def resolve(pool: dict[str, Player], name: str, position: str | None,
            team: str | None) -> list[Player]:
    """Candidates for one transcribed row, narrowed by position and team.

    A team defense is joined on its TEAM CODE, never its name: the page writes
    "Los Angeles (LAC - DEF)" and there are two Los Angeles defenses. The code is
    an identifier, which is what non-negotiable #1 asks for; the city is not.

    For everyone else the name is narrowed by position, then by team, then by an
    exact match -- and where that still leaves two (Bijan and Brian Robinson are
    both ATL RBs), the caller reports rather than picking one.
    """
    if position == "DEF" and team:
        return [p for p in pool.values() if p.position == "DEF" and p.team == team]

    matches = find_players(pool, name)
    for narrowing in (lambda p: p.position == position if position else True,
                      lambda p: p.team == team if team else True):
        narrowed = [p for p in matches if narrowing(p)]
        if narrowed:
            matches = narrowed
    # An exact name beats a substring one: "Josh Allen" must not be ambiguous
    # merely because some "Josh Allender" also plays quarterback.
    exact = [p for p in matches if p.name.lower() == name.lower()]
    return exact or matches


def snake_turns(slot: int, num_teams: int, total_picks: int) -> list[int]:
    turns, rnd = [], 1
    while True:
        pick = (rnd - 1) * num_teams + (slot if rnd % 2 else num_teams - slot + 1)
        if pick > total_picks:
            return turns
        turns.append(pick)
        rnd += 1


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    league_name = argv[0]
    rest = argv[1:]
    # An explicit slot is an OVERRIDE, not the input. The league already carries
    # `draft_slot`, and passing it again by hand is how a transcript gets scored
    # against somebody else's seat -- which happened the first time this ran.
    slot_arg = next((a for a in rest if a.isdecimal()), None)
    source = next((a for a in rest if not a.isdecimal()), None)
    raw = Path(source).read_text(encoding="utf-8") if source else sys.stdin.read()

    leagues, tun = load_config(Path(__file__).resolve().parent.parent / "config.toml")
    league = get_league(leagues, league_name)
    slot = int(slot_arg) if slot_arg else league.draft_slot
    if slot is None:
        print(f"league {league_name!r} has no draft_slot in config.toml, and none "
              f"was given.\nUsage: transcribe.py <league> [slot] [results.txt]")
        return 2
    print(f"seat: {slot}" + ("  (from config.toml)" if not slot_arg else "  (from the command line)"))
    players, settings = load_board_inputs(league, tun)

    parsed, problems = parse_board(raw, settings.num_teams)
    if not parsed:
        print("no picks found. Expected one pick per line, in pick order, e.g.\n"
              "  (1) manager - Gibbs, Jahmyr (Det - RB)")
        return 1

    # Where the page names the manager behind each pick, one seat's picks must
    # all carry the SAME name. Inconsistency means the rows are out of order --
    # it does NOT prove the slot is right, because any other valid seat is
    # equally self-consistent. What guards against a wrong slot is printing the
    # manager's name on success, so a seat that is not yours is visible.
    mine = set(snake_turns(slot, settings.num_teams, len(parsed)))
    managers = {i: row[4] for i, row in enumerate(parsed, 1) if row[4]}
    seat_managers = {managers[i] for i in mine if i in managers}
    if len(seat_managers) > 1:
        others = {m for m in managers.values()}
        problems.append(
            f"seat {slot} does not hold a consistent set of picks -- "
            f"{sorted(seat_managers)} all appear at {sorted(mine)}.\n"
            f"  Either the slot is wrong or the rows are out of order. "
            f"Seats in this draft: {sorted(others)}")

    picks: list[Player] = []
    for i, (overall, name, position, team, _manager) in enumerate(parsed, 1):
        matches = resolve(players, name, position, team)
        if len(matches) == 1:
            picks.append(matches[0])
        else:
            problems.append(
                f"pick {overall or i:>3}: {name!r}"
                + (f" [{position}{' ' + team if team else ''}]" if position else "")
                + ("  -- no player matches" if not matches
                   else "  -- ambiguous: " + ", ".join(
                       f"{p.name} ({p.position} {p.team})" for p in matches[:6])))

    seen, dupes = set(), []
    for p in picks:
        (dupes.append(p.name) if p.sleeper_id in seen else seen.add(p.sleeper_id))
    if dupes:
        problems.append("the same player is drafted twice: " + ", ".join(dupes[:10]))

    if problems:
        # Degrade, never fabricate. Guessing a name, or dropping a row, shifts
        # every pick number after it and silently moves every survival horizon.
        print(f"REFUSING TO WRITE -- {len(problems)} problem(s) in "
              f"{len(parsed)} parsed rows:\n")
        print("\n".join(f"  {p}" for p in problems[:25]))
        if len(problems) > 25:
            print(f"  ... and {len(problems) - 25} more")
        print("\nFix those rows and re-run. The position and team in parentheses "
              "are what\ndisambiguate a name, so keep them.")
        return 1

    # Named after the INPUT file, so several drafts transcribed on one day do
    # not collide -- `results2.txt` becomes `<league>-<date>-results2.jsonl`.
    # Reaching n=3 on one morning is the normal case, not an edge one.
    #
    # NEVER plain `<league>-<date>.jsonl`: that is the live board's own journal,
    # and `ffhelper.cli run` replays whatever it finds there on startup. The tag
    # is always non-empty, so the two can never collide.
    tag = re.sub(r"[^A-Za-z0-9_]+", "-", Path(source).stem) if source else "transcript"
    path = DRAFT_LOG_DIR / f"{league_name}-{date.today().isoformat()}-{tag}.jsonl"
    if path.exists():
        print(f"REFUSING TO OVERWRITE {path} -- move it aside first.")
        return 1
    DRAFT_LOG_DIR.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for i, p in enumerate(picks, 1):
            fh.write(json.dumps({"op": "mark", "id": p.sleeper_id, "mine": i in mine}) + "\n")

    print(f"wrote {len(picks)} picks to {path}")
    print(f"  seat {slot} of {settings.num_teams}"
          + (f" ({seat_managers.pop()})" if len(seat_managers) == 1 else "")
          + f": your picks are {sorted(mine)}")
    print(f"  yours: " + ", ".join(p.name for i, p in enumerate(picks, 1) if i in mine))
    print(f"\nNow: .venv/bin/python scripts/calibrate.py {path} {slot}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
