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
import re
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
         "if p.position in FLEX_ELIGIBLE and p.sleeper_id not in used), None)",
         "if p.sleeper_id not in used), None)"),
        ("one player fills two fixed slots",
         "if p.position == row[0] and p.sleeper_id not in used), None)",
         "if p.position == row[0]), None)"),
        ("leftovers spill into fixed slots, not just FLEX",
         '        if row[0] != "FLEX":\n            continue',
         '        if row[0] != "FLEX" and row[1] is None:\n            continue'),
        ("optimal lineup fills slots worst-first",
         "remaining = sorted(roster, key=lambda p: -p.proj_pts)",
         "remaining = sorted(roster, key=lambda p: p.proj_pts)"),
        ("FLEX filled BEFORE the fixed slots, so it steals the best RB",
         '        if row[0] == "FLEX":\n            continue\n'
         '        match = next((p for p in remaining\n'
         '                      if p.position == row[0] and p.sleeper_id not in used), None)',
         '        match = next((p for p in remaining\n'
         '                      if (p.position == row[0] or row[0] == "FLEX"\n'
         '                          and p.position in FLEX_ELIGIBLE)\n'
         '                      and p.sleeper_id not in used), None)'),
        ("static replacement baseline",
         "    repl = replacement_points(pool, ranks)",
         "    repl = replacement_points(available, ranks)"),
        ("tiers drawn from the draining pool -- late rounds all read tier 1",
         "tiers = assign_tiers(pool, vbd(pool, repl), tunables.tier_break_sigma)",
         "tiers = assign_tiers(available, vbd(available, repl), tunables.tier_break_sigma)"),
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
        ("restore banner reports typed marks, not the roster you will see",
         "    mine = _manual_mine(log_path, mark_state.mine, draft_slot, num_teams, has_feed)",
         "    mine = mark_state.mine"),
        ("handover loses your roster (feed-less CLI ignores the seat)",
         "    if has_feed:\n        return typed_mine",
         "    return typed_mine"),
        ("derivation applied to a league WITH a feed, contradicting it",
         "    if has_feed:\n        return typed_mine", "    if False:\n        return typed_mine"),
        ("a not-mine override is re-derived on the next render",
         "    return (derived - explicit_not_mine(log_path)) | typed_mine",
         "    return derived | typed_mine"),
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
        ("ambiguous roster line silently resolved to the first match",
         "        if len(matches) == 1:\n            players.append(matches[0])",
         "        if matches:\n            players.append(matches[0])"),
        ("unresolved roster lines dropped silently",
         'problems.append(f"no player matches {name!r}")', "pass"),
        ("empty lineup slots hidden, so a hole in the roster is invisible",
         '            out.append(f"  {slot:<5} -- EMPTY --   no eligible player on this roster")',
         "            pass"),
        ("degradation notes dropped from the screen",
         '        out += [""] + [f"!! {n}" for n in notes]', "        pass"),
        ("a dead draft feed crashes _lineup instead of degrading",
         '                except Exception as exc:                  # noqa: BLE001 - never fatal\n'
         '                    notes.append(f"could not reach the Sleeper draft feed to derive your "\n'
         '                                 f"roster_id ({exc}) -- showing an empty roster")\n'
         '                    feed_failed = True',
         "                except Exception:\n                    raise"),
        ("roster_id override silently used with no note",
         '            if used_override:\n'
         '                # Names WHOSE roster is being read, not just that an override\n'
         '                # happened -- `owner` was already resolved above for exactly\n'
         '                # this, so this is reuse, not a second network call.\n'
         '                notes.append(f"using roster_id {rid} from config.toml (override) -- "\n'
         '                             f"reading {owner or \'an unrecognised owner\'}\'s roster, "\n'
         '                             f"not derived from the draft")',
         "            pass"),
        ("an orphaned roster_id renders a blank screen with no explanation",
         '                notes.append(f"roster_id {rid} is not in this league\'s rosters -- "\n'
         '                             f"the roster data may be stale or the id may be wrong")',
         "                pass"),
        ("rostered players missing from the pool go unreported",
         '                notes.append(f"{len(missing)} rostered players are not in the player pool: "\n'
         '                             f"{\', \'.join(missing)}")',
         "                pass"),
        ("lineup's nfl-state guard removed -- a dead endpoint crashes 'lineup --week 4' too",
         '    try:\n'
         '        state = load_nfl_state()\n'
         '    except Exception as exc:                          # noqa: BLE001 - degrade, never fabricate\n'
         '        state = {}\n'
         '        notes.append(f"could not reach Sleeper\'s /state/nfl ({exc}) -- season defaults "\n'
         '                     f"to {SEASON}")',
         '    state = load_nfl_state()'),
        ("preflight's nfl-state guard removed -- a dead endpoint aborts the report early again",
         '    try:\n'
         '        state = load_nfl_state()\n'
         '        week = state.get("week")\n'
         '        season_str = str(state.get("season") or SEASON)\n'
         '        print(f"nfl week        : {week} ({state.get(\'season\')} {state.get(\'season_type\')})")\n'
         '    except Exception as exc:                          # noqa: BLE001 - degrade, never fabricate\n'
         '        print(f"nfl week        : NO -- {exc}")\n'
         '        ok = False',
         '    state = load_nfl_state()\n'
         '    week = state.get("week")\n'
         '    season_str = str(state.get("season") or SEASON)\n'
         '    print(f"nfl week        : {week} ({state.get(\'season\')} {state.get(\'season_type\')})")'),
        ("preflight's rosters guard removed -- a dead endpoint aborts before the feed check again",
         '        try:\n'
         '            rosters = load_league_rosters(league.league_id)\n'
         '            print(f"rosters         : {len(rosters)} teams")\n'
         '            rostered_ids = sorted({pid for r in rosters for pid in (r.get("players") or [])})\n'
         '            roster_scope = "rostered league-wide"\n'
         '        except Exception as exc:                      # noqa: BLE001 - degrade, never fabricate\n'
         '            print(f"rosters         : NO -- {exc}")\n'
         '            ok = False',
         '        rosters = load_league_rosters(league.league_id)\n'
         '        print(f"rosters         : {len(rosters)} teams")\n'
         '        rostered_ids = sorted({pid for r in rosters for pid in (r.get("players") or [])})\n'
         '        roster_scope = "rostered league-wide"'),
        ("preflight projections join reports everyone rostered as projected",
         "projected = sum(1 for pid in rostered_ids if pid in weekly)",
         "projected = len(rostered_ids)"),
        ("lineup total's floor caveat dropped when a starter is unprojected",
         '    caveat = (f"  (floor -- {unprojected_starters} starter"\n'
         '              f"{\'s\' if unprojected_starters != 1 else \'\'} unprojected)"\n'
         '              if unprojected_starters else "")',
         '    caveat = ""'),
        ("roster_id override note drops the owner's name",
         'notes.append(f"using roster_id {rid} from config.toml (override) -- "\n'
         '                             f"reading {owner or \'an unrecognised owner\'}\'s roster, "\n'
         '                             f"not derived from the draft")',
         'notes.append(f"using roster_id {rid} from config.toml (override) -- '
         'not derived from the draft")'),
        ("misleading injury codes rendered raw instead of through the display map",
         "injury = INJURY_STATUS_DISPLAY.get(p.injury_status, p.injury_status)",
         "injury = p.injury_status"),
        ("lineup's rosters-fetch guard drops its note, so a dead endpoint says nothing",
         'notes.append(f"could not reach Sleeper\'s league rosters endpoint "\n'
         '                         f"({exc}) -- showing an empty roster")',
         "pass"),
        ("lineup's users-fetch guard no longer catches, so a display name kills the lineup",
         "            except Exception as exc:                      "
         "# noqa: BLE001 - degrade, never fabricate\n"
         "                # The last unguarded fetch in this function",
         "            except ZeroDivisionError as exc:              "
         "# noqa: BLE001 - degrade, never fabricate\n"
         "                # The last unguarded fetch in this function"),
    ],
    "feeds.py": [
        ("picks poll drops the cache-buster, so Cloudflare serves a stale board",
         '            f"{SLEEPER_PICKS_URL.format(draft_id=self.draft_id)}"\n            f"?_={int(time.time() * 1000)}",',
         "            SLEEPER_PICKS_URL.format(draft_id=self.draft_id),"),
        ("picks cache key keyed on the busted URL -- a new file every poll",
         'f"picks_{self.draft_id}",',
         'f"picks_{self.draft_id}_{int(time.time() * 1000)}",'),
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
        ("a numeric draft id is filed as the seat (the id/slot swap)",
         "    return argv[0], int(argv[1]), argv[2] if len(argv) > 2 else \"sleeper-main\"",
         "    return argv[1], int(argv[0]), argv[2] if len(argv) > 2 else \"sleeper-main\""),
        ("a malformed invocation is accepted instead of printing usage",
         "    if len(argv) < 2 or not argv[1].isdecimal():\n        return None",
         "    if False:\n        return None"),
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
        ("weekly projection cache key drops the week -- every week serves week 1",
         'f"proj_{season}_wk{week}_{pos}"', 'f"proj_{season}_{pos}"'),
        ("missing depth chart reads as first string",
         'depth_chart_order=(int(p["depth_chart_order"])\n'
         '                               if p.get("depth_chart_order") is not None else None),',
         'depth_chart_order=int(p.get("depth_chart_order") or 0),'),
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
        ("click resolves rows by name instead of id (non-negotiable #1)",
         '                last_marked = rows[active_cell["row"]]["id"]',
         '                last_marked = rows[active_cell["row"]]["player"]'),
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
        ("tier badge styles the wrong column, so tier loses its colour",
         '"column_id": "tier"', '"column_id": "pos"'),
        ("bye clash read off the whole pool -- the opening board is all red",
         "rostered_byes = {(p.position, p.bye) for p in state.my_roster if p.bye}",
         "rostered_byes = {(p.position, p.bye) for p in state.available if p.bye}"),
        ("bye clash ignores position -- any shared bye week flags",
         "if (r.player.position, r.player.bye) in rostered_byes:",
         "if r.player.bye in {b for _p, b in rostered_byes}:"),
        ("clash never flagged -- every bye reads as ordinary",
         'flags.append(f"BYE{r.player.bye} CLASH")',
         'flags.append(f"bye{r.player.bye}")'),
        ("re-clicking the highlighted cell is silently dropped",
         "return status, (n or 0) + 1, None, last_marked",
         "return status, (n or 0) + 1, active_cell, last_marked"),
        ("override reads the cleared selection, so it never fires",
         'elif trigger == "override" and last_marked:',
         'elif trigger == "override" and active_cell and rows:'),
        ("FLEX filter falls through to an exact position match",
         '        out = [r for r in out if r["pos"] in FLEX_ELIGIBLE]',
         '        out = [r for r in out if r["pos"] == position]'),
        ("position filter is a no-op",
         'out = [r for r in out if r["pos"] == position]', "out = out"),
        ("search matches on prefix only, not substring",
         'out = [r for r in out if q in r["player"].lower()]',
         'out = [r for r in out if r["player"].lower().startswith(q)]'),
        ("panel counts a starter on the bench as well",
         "if p.sleeper_id not in started]", "]"),
        ("panel hides empty slots instead of showing them",
         # Anchored on the line above, because a bare "    return out" also
         # matches `board_rows`'s filter 30 lines earlier -- and replace(.., 1)
         # took THAT one, so this mutation was reporting "killed" for breaking
         # a completely different function.
         '    out += [("BN", None)] * max(0, bench_slots - len(remaining))\n'
         "    return out",
         '    out += [("BN", None)] * max(0, bench_slots - len(remaining))\n'
         "    return [r for r in out if r[1] is not None]"),
        ("override shown on a feed league, where it is a dead control",
         '            {"display": "none"} if has_feed else {},',
         "            {},"),
        ("undo hidden along with the override -- no misclick recovery",
         'Output("override", "style"),',
         'Output("undo", "style"),'),
        ("position colours never reach the table",
         "rows, POS_STYLES + TIER_STYLES + CLASH_STYLES,",
         "rows, TIER_STYLES + CLASH_STYLES,"),
        ("the page glows live on every pick, including other seats'",
         '            "page page--live" if is_on_the_clock(state, league, settings.num_teams)\n            else "page",',
         '            "page page--live",'),
        ("on-the-clock predicate inverted -- glows on everyone else's turn",
         "    return next_pick_number(\n        state.current_pick - 1, league.draft_slot, num_teams) == state.current_pick",
         "    return next_pick_number(\n        state.current_pick, league.draft_slot, num_teams) == state.current_pick"),
        ("build_app drops the configured interval on the floor",
         "        layout=_layout(league_names, default_league, poll_ms))",
         "        layout=_layout(league_names, default_league))"),
        ("refresh interval ignores config (back to a hardcoded 5s)",
         'return max(tunables.poll_seconds.get(platform, 5), 1) * 1000',
         "return 5000"),
        ("interval floor removed -- a 0 in config busy-loops the feed",
         "max(tunables.poll_seconds.get(platform, 5), 1)",
         "tunables.poll_seconds.get(platform, 5)"),
        ("a failed poll erases the draft (back to pick 1, full pool)",
         "picks = _LAST_PICKS.get(league.name, [])", "picks = []"),
        ("last-good picks never recorded, so the cache is always empty",
         "_LAST_PICKS[league.name] = picks", "pass"),
        ("silent window: a failing feed says nothing for its first 15s",
         '        lines.append(f"feed not answering -- last good poll {stale_seconds:.0f}s ago")',
         "        pass"),
        ("bench picks hidden -- you cannot see your own bench",
         '    out += [("BN", p.name) for p in remaining]', "    pass"),
    ],
    "season.py": [
        ("weekly projection guard stops rejecting a null stats row",
         "if not pid or not stats:", "if not pid:"),
        ("weekly scoring mutates the shared season pool",
         "return [replace(p, proj_pts=weekly.get(p.sleeper_id, 0.0)) for p in roster]",
         "for p in roster:\n        p.proj_pts = weekly.get(p.sleeper_id, 0.0)\n    return roster"),
        ("close-call challenger ignores slot eligibility (a kicker challenges a WR)",
         "challenger = next((b for b in bench if _eligible(b, slot) and b.sleeper_id not in unprojected_ids), None)",
         "challenger = next((b for b in bench if b.sleeper_id not in unprojected_ids), None)"),
        ("every gap reported, so the real decision is buried",
         "if gap <= close_call_points:", "if gap >= 0:"),
        ("bench ordered worst-first",
         "key=lambda p: -p.proj_pts)", "key=lambda p: p.proj_pts)"),
        ("projected_ids distinction lost -- unprojected treated as projected",
         "unprojected_ids = set() if projected_ids is None else {p.sleeper_id for p in roster if p.sleeper_id not in projected_ids}",
         "unprojected_ids = set()"),
        ("descriptive-only rows scored as zero instead of omitted",
         "if not any(k in scoring for k in stats):\n            continue",
         "pass"),
        ("close call built on an unprojected starter's fabricated 0.0",
         "        if starter.sleeper_id in unprojected_ids:\n            continue",
         "        pass"),
        ("roster_id assumed equal to draft_slot -- you manage someone else's team",
         "    found = {p.roster_id for p in picks\n"
         "             if p.draft_slot == draft_slot and p.roster_id is not None}\n"
         "    return found.pop() if len(found) == 1 else None",
         "    return draft_slot"),
        ("a contradictory draft picks the first roster_id instead of refusing",
         "return found.pop() if len(found) == 1 else None",
         "return found.pop() if found else None"),
    ],

}


# A duplicate key in the dict literal above keeps only the LAST block, silently.
# That happened on 2026-08-27 and cost 26 cli.py mutations with no warning at
# all -- the run simply reported a smaller total. Checked against the source
# text because by the time the dict exists the evidence is already gone.
_KEYS = re.findall(r'^    "([^"]+)": \[', Path(__file__).read_text(), re.M)
if len(_KEYS) != len(set(_KEYS)):
    _dupes = sorted({k for k in _KEYS if _KEYS.count(k) > 1})
    raise SystemExit(f"duplicate key(s) in MUTATIONS: {_dupes} -- earlier blocks "
                     "would be silently dropped. Merge them.")


def _target_path(fname: str) -> Path:
    """A key with a slash is a path from ROOT (scripts/); anything else is a
    module in the package."""
    return ROOT / fname if "/" in fname else ROOT / "ffhelper" / fname


def main() -> int:
    results = []
    for fname, muts in MUTATIONS.items():
        path = _target_path(fname)
        original = path.read_text()
        try:
            for label, old, new in muts:
                n = original.count(old)
                if n == 0:
                    results.append((fname, label, "STALE - pattern gone, update this script"))
                    continue
                if n > 1:
                    # `replace(old, new, 1)` silently takes the FIRST match, so
                    # an ambiguous pattern mutates somewhere other than the line
                    # the label names -- and then reports "killed" for breaking
                    # an unrelated function. Found 2026-09-02 in app.py, where a
                    # bare "    return out" hit `board_rows` instead of the
                    # roster panel. Same failure shape as the duplicate-key bug
                    # above: the check reports success while checking the wrong
                    # thing. Anchor the pattern on an adjacent line instead.
                    results.append((fname, label, f"AMBIGUOUS - matches {n} places, "
                                                  "anchor it on an adjacent line"))
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
