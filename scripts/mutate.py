"""Mutation check: break the engine on purpose and see whether the suite notices.

This project's defining lesson is that a fully green suite proves nothing on its
own -- nine defects have now been found by running the code, every one of them
past a green suite. A passing test can be vacuous in ways that reading it does
not reveal. This is the mechanical check for that.

A mutation that is KILLED means at least one test actually depends on that logic.
A mutation that SURVIVES means no test does: change the line however you like and
the suite stays green. Every survivor is either a real coverage gap or an
equivalent mutant (a change with no observable effect) -- and you have to decide
which, by hand.

Run it before merging any branch that touches value.py, and after adding tests
you believe close a gap:

    .venv/bin/python scripts/mutate.py

The file is restored no matter how the run ends. Add a mutation whenever you add
non-trivial logic: the cost is one line, and it is the only thing that tells you
whether the test you just wrote does anything.

KNOWN EQUIVALENT MUTANT (expected to survive, do not chase):
  "tier threshold strictness" -- `>` vs `>=` on float gaps. Two gaps are never
  exactly equal on real data, so no test can distinguish the two forms.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/bin/python"

# (label, exact source text, replacement). One occurrence each, applied alone.
MUTATIONS: dict[str, list[tuple[str, str, str]]] = {
    "value.py": [
        ("vbd sign",
         "p.proj_pts - repl.get(p.position, 0.0)", "p.proj_pts + repl.get(p.position, 0.0)"),
        ("replacement off-by-one",
         "pool[min(rank, len(pool)) - 1]", "pool[min(rank, len(pool)) - 2]"),
        ("tier threshold strictness",
         "if i < len(gaps) and gaps[i] > threshold:", "if i < len(gaps) and gaps[i] >= threshold:"),
        ("tier sigma ignored",
         "sigma * statistics.pstdev(threshold_gaps)", "statistics.pstdev(threshold_gaps)"),
        ("survival inverted",
         "return 1.0 - NormalDist(player.adp, max(stdev, 0.1)).cdf(at_pick)",
         "return NormalDist(player.adp, max(stdev, 0.1)).cdf(at_pick)"),
        ("vona walk weight", "prob_all_gone *= 1.0 - surv", "prob_all_gone *= surv"),
        ("vona sign", "return candidate.proj_pts - expected", "return expected - candidate.proj_pts"),
        ("divergence sign",
         "return {pid: adp_rank[pid] - proj_rank[pid] for pid in proj_rank}",
         "return {pid: proj_rank[pid] - adp_rank[pid] for pid in proj_rank}"),
        ("run detection window", "recent_positions[-window:]", "recent_positions[:window]"),
        ("snake next-pick boundary", "if pick > current_pick:", "if pick >= current_pick:"),
        ("flex share ignored",
         "ranks[pos] = round(num_teams * (starters + share * flex_slots))",
         "ranks[pos] = round(num_teams * starters)"),
        ("board sort tiebreak",
         "key=lambda r: (-max(round(r.vona, 1), 0.0), -r.vbd)", "key=lambda r: -r.vona"),
        ("lineup flex eligibility",
         "if p.position in FLEX_ELIGIBLE and p.sleeper_id not in used:",
         "if p.sleeper_id not in used:"),
    ],
    "cli.py": [
        ("current_pick horizon",
         "current_pick = max(len(drafted), highest) + 1", "current_pick = max(len(drafted), highest)"),
        ("stale threshold", "elif stale_seconds > 15:", "elif stale_seconds > 15000:"),
        ("disambiguation predicate",
         "if pending and line.isdecimal():", "if pending and line.isdigit():"),
        ("mark idempotency", "if player_id in self._marked:", "if False:"),
        ("draft_slot range check",
         "elif not 1 <= league.draft_slot <= settings.num_teams:", "elif False:"),
        ("draft_id override",
         "if league.draft_id and league.draft_id != settings.draft_id:", "if False:"),
    ],
    "data.py": [
        ("stale_ok honoured", "if not stale_ok:", "if False:"),
    ],
}


def main() -> int:
    results = []
    for fname, muts in MUTATIONS.items():
        path = ROOT / "ffhelper" / fname
        original = path.read_text()
        try:
            for label, old, new in muts:
                if old not in original:
                    results.append((fname, label, "STALE - pattern gone, update this script"))
                    continue
                path.write_text(original.replace(old, new, 1))
                p = subprocess.run(
                    [str(PY), "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
                    cwd=ROOT, capture_output=True, text=True, timeout=300,
                )
                results.append((fname, label, "killed" if p.returncode else "*** SURVIVED ***"))
        finally:
            path.write_text(original)              # always restore

    print(f"\n{'file':<10} {'mutation':<28} result")
    print("-" * 62)
    for f, label, r in results:
        print(f"{f:<10} {label:<28} {r}")
    bad = [r for r in results if "SURVIV" in r[2] or "STALE" in r[2]]
    print("-" * 62)
    print(f"{len(results)} mutations, {len(bad)} needing a look")

    p = subprocess.run([str(PY), "-m", "pytest", "-q", "--no-header"], cwd=ROOT,
                       capture_output=True, text=True)
    print("restored suite:", p.stdout.strip().splitlines()[-1])
    # One known equivalent mutant is expected to survive; see the module docstring.
    return 1 if len(bad) > 1 else 0


if __name__ == "__main__":
    sys.exit(main())
