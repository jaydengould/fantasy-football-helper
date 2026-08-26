"""Measure how well the survival model predicted a COMPLETED Sleeper draft.

Survival is only as good as its ADP mean, and which ADP best matches a real
draft room is an empirical question this settles in one run:

    .venv/bin/python scripts/calibrate.py <draft_id> <your_draft_slot> [league]

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
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ffhelper.cli import load_board_inputs
from ffhelper.config import League, get_league, load_config
from ffhelper.value import next_pick_number, survival_prob

PICKS_URL = "https://api.sleeper.app/v1/draft/{draft_id}/picks"
BUCKETS = 5


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    draft_id, slot = argv[0], int(argv[1])
    league_name = argv[2] if len(argv) > 2 else "sleeper-main"

    picks = sorted(
        json.load(urllib.request.urlopen(PICKS_URL.format(draft_id=draft_id), timeout=10)),
        key=lambda r: r["pick_no"],
    )
    if not picks:
        print(f"draft {draft_id} has no picks yet -- run this after it completes")
        return 1

    leagues, tun = load_config(Path(__file__).resolve().parent.parent / "config.toml")
    base = get_league(leagues, league_name)

    drafted_at = {p["player_id"]: p["pick_no"] for p in picks}
    my_turns = [p["pick_no"] for p in picks if p.get("draft_slot") == slot]
    if not my_turns:
        print(f"no picks carry draft_slot {slot}; seats present: "
              f"{sorted({p.get('draft_slot') for p in picks})}")
        return 1
    # The state to judge from is the turn BEFORE each pick, plus the first one.
    turns = [my_turns[0]] + my_turns[:-1]
    num_teams = 12

    for source in ("ffc", "sleeper"):
        league = League(**{**base.__dict__, "adp_source": source})
        players, settings = load_board_inputs(league, tun)
        num_teams = settings.num_teams
        buckets: dict[float, list[int]] = {}
        for cur in turns:
            nxt = next_pick_number(cur, slot, num_teams)
            for pid, p in players.items():
                if drafted_at.get(pid, 10**9) < cur:
                    continue                                  # already gone
                pred = survival_prob(p, nxt)
                if pred < 0.02 or pred > 0.98:
                    continue                                  # uninformative band
                key = int(pred * BUCKETS) / BUCKETS
                slot_ = buckets.setdefault(key, [0, 0])
                slot_[0] += 1
                slot_[1] += drafted_at.get(pid, 10**9) >= nxt

        print(f"\nADP SOURCE: {source}   ({len(turns)} turns, {len(picks)} picks)")
        print(f"  {'model says':<16}{'n':>6}{'actually survived':>20}")
        for key in sorted(buckets):
            n, survived = buckets[key]
            print(f"  {key:.0%}-{key + 1 / BUCKETS:.0%}{'':<8}{n:>6}{survived / n:>19.0%}")
    print("\nIdeal reads 10/30/50/70/90 down the actual column. Flat = no signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
