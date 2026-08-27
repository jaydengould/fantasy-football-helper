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
        ("survival conditions on the current pick",
         "return min(still_there(at_pick) / still_there(from_pick), 1.0)",
         "return still_there(at_pick)"),
        ("survival inverted",
         "return 1.0 / (1.0 + math.exp(min((pick - player.adp) / scale, _EXP_CAP)))",
         "return 1.0 - 1.0 / (1.0 + math.exp(min((pick - player.adp) / scale, _EXP_CAP)))"),
        ("variance matching on the logistic scale",
         "scale = max(stdev, 0.1) * math.sqrt(3) / math.pi", "scale = max(stdev, 0.1)"),
        ("board conditions vona on current_pick",
         "vona=vona(available, p, at_pick, current_pick),", "vona=vona(available, p, at_pick),"),
        ("board conditions survival on current_pick",
         "survival=survival_prob(p, at_pick, current_pick),",
         "survival=survival_prob(p, at_pick),"),
        ("vona walk weight", "prob_all_gone *= 1.0 - surv", "prob_all_gone *= surv"),
        ("vona sign", "return candidate.proj_pts - expected", "return expected - candidate.proj_pts"),
        ("divergence sign",
         "out.update({pid: adp_rank[pid] - proj_rank[pid] for pid in proj_rank})",
         "out.update({pid: proj_rank[pid] - adp_rank[pid] for pid in proj_rank})"),
        ("run detection window", "recent_positions[-window:]", "recent_positions[:window]"),
        ("snake next-pick boundary", "if pick > current_pick:", "if pick >= current_pick:"),
        ("flex share ignored",
         "ranks[pos] = round(num_teams * (starters + share * flex_slots))",
         "ranks[pos] = round(num_teams * starters)"),
        ("board sort vbd tiebreak",
         "            -r.vbd,\n", ""),
        ("lineup flex eligibility",
         "if p.position in FLEX_ELIGIBLE and p.sleeper_id not in used:",
         "if p.sleeper_id not in used:"),
        ("static replacement baseline",
         "repl = replacement_points(replacement_pool if replacement_pool is not None else available, ranks)",
         "repl = replacement_points(available, ranks)"),
        ("roster-need gate on the sort",
         "            -max(round(r.vona, 1), 0.0) if r.marginal > MARGINAL_EPS else 0.0,",
         "            -max(round(r.vona, 1), 0.0),"),
        ("vona floor+round in the sort",
         "            -max(round(r.vona, 1), 0.0) if r.marginal > MARGINAL_EPS else 0.0,",
         "            -r.vona,"),
        ("redundant K/DEF demotion",
         "            is_redundant(r.player, my_roster, settings_slots),\n", ""),
        ("redundancy needs a filled slot",
         "return held >= roster_slots.get(player.position, 1)", "return True"),
        ("divergence excludes unpriced players",
         "        if p.adp < ADP_UNKNOWN:\n            by_pos.setdefault(p.position, []).append(p)",
         "        if True:\n            by_pos.setdefault(p.position, []).append(p)"),
        ("divergence ranked within position",
         "            by_pos.setdefault(p.position, []).append(p)",
         "            by_pos.setdefault(\"ALL\", []).append(p)"),
        ("tiers grouped per position",
         "    for p in players:\n        by_pos.setdefault(p.position, []).append(p)",
         "    for p in players:\n        by_pos.setdefault(\"ALL\", []).append(p)"),
        ("divergence reports None not a number",
         "out: dict[str, int | None] = {p.sleeper_id: None for p in players}",
         "out: dict[str, int | None] = {p.sleeper_id: 0 for p in players}"),
        ("bench-only detection",
         "return bool(board) and all(r.marginal <= MARGINAL_EPS for r in board)",
         "return False"),
    ],
    "cli.py": [
        ("commas split one line into commands", 'line.split(",")', "[line]"),
        ("every command in a batch is reported",
         'status = "  |  ".join(statuses)', 'status = statuses[-1] if statuses else ""'),
        ("input wait bounded by the poll interval",
         "first = _wait_for_input(input_queue, max(0.0, next_poll - time.monotonic()))",
         "first = _wait_for_input(input_queue, 0.0)"),
        ("wait returns the typed line", "return input_queue.get(timeout=timeout)",
         "input_queue.get(timeout=timeout)\n        return None"),
        ("poll only when due", "if time.monotonic() >= next_poll:", "if True:"),
        ("current_pick horizon",
         "current_pick = max(len(drafted), highest) + 1", "current_pick = max(len(drafted), highest)"),
        ("stale threshold", "elif stale_seconds > 15:", "elif stale_seconds > 15000:"),
        ("disambiguation predicate",
         "if pending and line.isdecimal():", "if pending and line.isdigit():"),
        ("mark idempotency",
         "if player_id in self._marked and (not mine or player_id in self._mine):",
         "if False:"),
        ("mark claim upgrade",
         "if player_id in self._marked and (not mine or player_id in self._mine):",
         "if player_id in self._marked:"),
        ("undo restores prior mine membership",
         "(self._mine.add if was_mine else self._mine.discard)(player_id)",
         "self._mine.discard(player_id)"),
        ("unmark guard on unmarked player",
         "if player_id not in self._marked:\n            return", "if False:\n            return"),
        ("unmark clears the claim too",
         "self._marked.discard(player_id)\n        self._mine.discard(player_id)",
         "self._marked.discard(player_id)"),
        ("unmark scoped to hand-marked players",
         "scope = {pid: p for pid, p in pool.items() if pid in marked}", "scope = pool"),
        ("unmark action reaches _apply", 'if action == "unmark":\n        mark_state.unmark',
         'if False:\n        mark_state.unmark'),
        ("undo is journalled", 'self._log(op="undo")', "pass"),
        ("mark carries the mine flag into the log",
         'self._log(op="mark", id=player_id, mine=mine)',
         'self._log(op="mark", id=player_id, mine=False)'),
        ("logging armed after replay", "state.attach_log(path)", "pass"),
        ("corrupt log lines are counted", "skipped += 1", "pass"),
        ("draft log is dated",
         'DRAFT_LOG_DIR / f"{league.name}-{date.today().isoformat()}.jsonl"',
         'DRAFT_LOG_DIR / f"{league.name}.jsonl"'),
        ("overrule inert without a configured slot",
         "if my_slot is None:\n        return set()", "if False:\n        return set()"),
        ("overrule ignores slotless picks",
         "p.draft_slot is not None and p.draft_slot != my_slot", "p.draft_slot != my_slot"),
        ("overruled claims leave my_roster",
         "manual_mine - overruled", "manual_mine"),
        ("draft_slot range check",
         "elif not 1 <= league.draft_slot <= settings.num_teams:", "elif False:"),
        ("draft_id override",
         "if league.draft_id and league.draft_id != settings.draft_id:", "if False:"),
        ("my_roster slot match",
         "if p.draft_slot == my_slot and p.sleeper_id in players", "if p.sleeper_id in players"),
        ("on-the-clock banner",
         "if next_pick_number(current_pick - 1, league.draft_slot, settings.num_teams) == current_pick:",
         "if False:"),
        ("redraw dedup",
         "if frame != last_frame or stale or iterations == 0:", "if True:"),
        ("adp_source validated",
         "if league.adp_source not in ADP_SOURCES:", "if False:"),
    ],
    "feeds.py": [
        ("pick draft_slot parsed",
         "draft_slot=int(slot) if slot is not None else None,", "draft_slot=None,"),
    ],
    "scripts/transcribe.py": [
        ("position and team narrow candidates",
         "narrowed = [p for p in matches if narrowing(p)]", "narrowed = []"),
        ("exact name beats a substring", "return exact or matches", "return matches"),
        ("a defense joins on its team code",
         'if position == "DEF" and team:', "if False:"),
        ("D/ST survives tokenising", 'r"[\\s\\-,]+"', 'r"[\\s\\-,/]+"'),
        ("column headers are skipped",
         "if not line.strip() or ROUND.match(line) or SKIP.match(line):",
         "if not line.strip() or ROUND.match(line):"),
        ("surname-first names are put back in order",
         'field = f"{given.strip()} {surname.strip()}".strip()',
         'field = f"{surname.strip()} {given.strip()}".strip()'),
        ("rows are ordered by pick number",
         "picks.sort(key=lambda row: row[0])", "pass"),
        ("an incomplete run is refused",
         "elif sorted(numbered) != list(range(1, len(numbered) + 1)):", "elif False:"),
    ],
    "scripts/calibrate.py": [
        ("room discipline counts only what is still available",
         "if other not in gone:\n                rank += 1", "rank += 1"),
        ("seat inferred from the first claimed pick",
         "slot = slot_override or my_turns[0]", "slot = slot_override or 1"),
        ("the first turn is scored once",
         "return drafted_at, my_turns[:-1], slot",
         "return drafted_at, [my_turns[0]] + my_turns[:-1], slot"),
        ("a log is proven against the snake",
         "if my_turns != expected:", "if False:"),
        ("league name stops at the date",
         r'r"^(?P<league>.+?)-\d{4}-\d{2}-\d{2}(?:-.*)?$"', r'r"^(?P<league>.+?)-.*$"'),
        ("journal excludes taken-back marks",
         'if op.get("op") == "mark" and pid in state.drafted and pid not in seen:',
         'if op.get("op") == "mark" and pid not in seen:'),
        ("journal my_turns are claimed picks",
         "my_turns = [i for i, pid in enumerate(seq, 1) if pid in state.mine]",
         "my_turns = [i for i, pid in enumerate(seq, 1)]"),
        ("snake reverses on even rounds",
         "(slot if rnd % 2 else num_teams - slot + 1)", "slot"),
    ],
    "data.py": [
        ("stale_ok honoured", "if not stale_ok:", "if False:"),
        ("adp_source gates the ffc overwrite",
         "if set_adp and row.get(\"adp\") is not None:", "if row.get(\"adp\") is not None:"),
        ("ffc bye is taken regardless of adp_source",
         "if row.get(\"bye\"):", "if set_adp and row.get(\"bye\"):"),
    ],
    "ffhelper/board.py": [
        ("pick count ignores manual marks",
         "current_pick = max(len(drafted), highest) + 1",
         "current_pick = max(len(picks), highest) + 1"),
        ("pick count off by one",
         "current_pick = max(len(drafted), highest) + 1",
         "current_pick = max(len(drafted), highest)"),
        ("overruled claims left in my_roster",
         "_combine_my_roster(feed_roster, manual_mine - overruled, players)",
         "_combine_my_roster(feed_roster, manual_mine, players)"),
        ("replacement drawn from the draining pool",
         "replacement_pool=list(players.values()),",
         "replacement_pool=available,"),
        ("attribution claims every pick",
         "return {pid for i, pid in enumerate(order, 1) if i in turns}",
         "return set(order)"),
        ("attribution off by one",
         "return {pid for i, pid in enumerate(order, 1) if i in turns}",
         "return {pid for i, pid in enumerate(order, 0) if i in turns}"),
        ("attribution guesses with no seat",
         "    if seat is None:\n        return set()",
         "    if seat is None:\n        seat = 1"),
    ],
    "ffhelper/app.py": [
        ("click resolves rows by position instead of id",
         'status = apply_click(path, rows[active_cell["row"]]["id"])',
         'status = apply_click(path, rows[active_cell["row"]]["player"])'),
        ("undo not journalled",
         "    state.undo()\n    return \"undone\"",
         "    return \"undone\""),
        ("write does not force a redraw",
         "return status, (n or 0) + 1", "return status, n"),
        ("not-mine override forgotten on the next tick (plain union)",
         "manual_mine = (derived - explicit_not_mine(log_path)) | mark_state.mine",
         "manual_mine = derived | mark_state.mine"),
        ("board trimmed to the screen BEFORE filtering (K shows three rows)",
         "board_rows(state, limit=200,", "board_rows(state, limit=40,"),
        ("tier bands never alternate",
         "band = _BAND_B if band == _BAND_A else _BAND_A", "band = band"),
        ("tier bands group across positions (tier is per-position)",
         'key = (r["pos"], r["tier"])', 'key = r["tier"]'),
        ("position filter is a no-op",
         'out = [r for r in out if r["pos"] == position]', "out = out"),
        ("search matches on prefix only, not substring",
         'out = [r for r in out if q in r["player"].lower()]',
         'out = [r for r in out if r["player"].lower().startswith(q)]'),
        ("panel starts a QB at FLEX (disagrees with MARG)",
         'match = next((p for p in remaining if p.position in FLEX_ELIGIBLE), None)',
         'match = next((p for p in remaining), None)'),
        ("panel fills slots worst-first",
         "remaining = sorted(my_roster, key=lambda p: -p.proj_pts)",
         "remaining = sorted(my_roster, key=lambda p: p.proj_pts)"),
        ("panel hides empty slots instead of showing them",
         "    return out", "    return [r for r in out if r[1] is not None]"),
        ("a failed poll erases the draft (back to pick 1, full pool)",
         "picks = _LAST_PICKS.get(league.name, [])", "picks = []"),
        ("last-good picks never recorded, so the cache is always empty",
         "_LAST_PICKS[league.name] = picks", "pass"),
        ("silent window: a failing feed says nothing for its first 15s",
         '        lines.append(f"feed not answering -- last good poll {stale_seconds:.0f}s ago")',
         "        pass"),
        ("bench picks hidden -- you cannot see your own bench",
         '    out += [("BN", p.name) for p in remaining]', "    pass"),
        ("leftovers spill into fixed slots, not just FLEX",
         '        if row[0] != "FLEX":\n            continue',
         '        if row[0] != "FLEX" and row[1] is None:\n            continue'),
    ],
}


def main() -> int:
    results = []
    for fname, muts in MUTATIONS.items():
        # A key with a slash is a path from ROOT (scripts/); anything else is a
        # module in the package.
        path = ROOT / fname if "/" in fname else ROOT / "ffhelper" / fname
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

    print(f"\n{'file':<22} {'mutation':<32} result")
    print("-" * 62)
    for f, label, r in results:
        print(f"{f:<22} {label:<32} {r}")
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
