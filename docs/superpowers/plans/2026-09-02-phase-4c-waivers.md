# Phase 4c — Waivers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ffhelper.cli waivers`, which ranks free agents by the true
marginal value of adding them at the cost of one drop, over two horizons, and
prints nothing when nothing clears the measured noise.

**Architecture:** Loaders in `data.py`, all logic pure in `season.py`, one
subcommand in `cli.py`. The ranking primitive is `value.optimal_lineup`,
imported and never re-implemented. Two horizons share ONE code path: the floor
is `close_call_points × √weeks` and √1 = 1, so "this week" is the
rest-of-season function called with a one-week horizon.

**Tech Stack:** Python 3.12 stdlib (`math.sqrt`, `dataclasses`), `requests` via
the existing `data.fetch_json`. **No new dependency.**

**Spec:** `docs/superpowers/specs/2026-09-02-phase-4c-waivers-design.md` — read
it before Task 1. The plan argues from it and does not restate its measurements.

**Branch:** `phase-4c-waivers` (already created, spec committed at `e5c3cbc`).

## Global Constraints

Copied from `CLAUDE.md`; every task's requirements implicitly include these.

- **Python 3.12, stdlib first.** Dependencies are exactly `requests`, `yfpy`,
  `dash`. **Adding one is out of scope for this plan.**
- **`season.py` is PURE.** No I/O, no network, no globals, no module-level
  league state. If something here wants to fetch, put the loader in `data.py`.
- **`value.py` and `data.py` logic is imported, never copied.** A second copy
  of `FLEX_ELIGIBLE` or of the greedy lineup assignment is the defect this
  project has already paid for twice.
- **No module-level league state.** Every function takes league context.
- **Never join load-bearing data on player name.** Everything here joins on
  `sleeper_id` (a `str`).
- **Degrade, never fabricate.** A missing source removes its column, visibly
  labelled. Never a 0.0 standing in for "we did not know".
- **No test may reach the network or the real `season.db`.** Both are refused
  autouse in `tests/conftest.py`. Loaders under test are called with an
  explicit `fetcher`.
- **A new test must be shown to FAIL before the fix**, via
  `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k <name>`,
  then `git stash pop`. The `-u` is mandatory when the test covers a new file.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** A
  surviving mutation is evidence about the TEST — fix the test, never weaken
  the mutation. The mutation's target string must match **exactly one** place
  in the file (the tool refuses ambiguous ones as `AMBIGUOUS`).
- **`scripts/mutate.py` runs in the FOREGROUND, ALONE.** Never backgrounded,
  never concurrently with anything else, and **a subagent counts as something
  else**. Capture `git status` before and after and diff them.
- Test command is `.venv/bin/python -m pytest`. Suite is currently **419
  passing in ~0.9s**; keep it offline and sub-second.
- Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and
  the upgrade path.

## File Structure

| file | responsibility | change |
| --- | --- | --- |
| `ffhelper/data.py` | loaders only | **add** `load_trending` |
| `ffhelper/season.py` | pure season logic | **add** `LAST_REGULAR_WEEK`, `WaiverTarget`, `free_agent_pool`, `horizon_total`, `roster_upgrade`, `waiver_targets`, `waiver_position` |
| `ffhelper/cli.py` | commands and rendering | **extract** `_resolve_week`, `_resolve_my_roster` from `_lineup`; **add** `render_waivers`, `_waivers`, the `waivers` subcommand |
| `tests/test_data.py` | loader tests | add trending tests |
| `tests/test_season.py` | pure-logic tests | add the waiver block |
| `tests/test_cli.py` | command tests | add `_waivers` and render tests |
| `scripts/mutate.py` | mutation check | add 6 mutations |

**`load_league_transactions` is deliberately NOT built.** It has no consumer —
see the spec's 2026-09-02 amendment.

---

### Task 1: Extract `_resolve_week` and `_resolve_my_roster` from `_lineup`

Pure refactor, no behaviour change. It comes first because Tasks 6 and 7 need
both, and a second copy of "whose roster is this" would let `lineup` and
`waivers` advise different teams from one config.

**Files:**
- Modify: `ffhelper/cli.py` (`_lineup`, currently lines 1232-1421)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `_resolve_week(week: int | None) -> tuple[int | None, str, list[str]]`
    returning `(week, season_str, notes)`. `week` is `None` when neither
    `/state/nfl` nor the argument supplied one — the caller prints and returns 1.
  - `_resolve_my_roster(league: League, settings: LeagueSettings, players: dict[str, Player]) -> tuple[list[Player], str | None, list[str], list[dict]]`
    returning `(roster, owner, notes, rosters)`. `rosters` is the raw Sleeper
    payload (empty list for Yahoo or a failed fetch) — Task 6 reads
    `waiver_position` out of it, so it must not be discarded.

- [ ] **Step 1: Write the characterisation test for the seam**

This is a refactor, so the test pins CURRENT behaviour before moving anything.

```python
def test_resolve_week_prefers_the_explicit_week_over_state(monkeypatch):
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    week, season_str, notes = cli._resolve_week(7)
    assert (week, season_str) == (7, "2026")
    assert notes == []


def test_resolve_week_returns_none_when_state_is_dead_and_no_week_given(monkeypatch):
    def dead():
        raise RuntimeError("connection refused")
    monkeypatch.setattr(cli, "load_nfl_state", dead)
    week, season_str, notes = cli._resolve_week(None)
    # None, not a guessed 1 -- guessing a week is the fabrication the design forbids.
    assert week is None
    assert season_str == cli.SEASON
    assert any("state/nfl" in n for n in notes)


def test_resolve_week_treats_sleepers_offseason_zero_as_no_week(monkeypatch):
    # Sleeper serves "week": 0 in the offseason. `_lineup` guards on `not week`
    # and `_preflight` used to guard on `week is None`; the two disagreed and one
    # of them fetched projections for week 0.
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 0, "season": "2026"})
    week, _, _ = cli._resolve_week(None)
    assert week is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k resolve_week -v`
Expected: FAIL with `AttributeError: module 'ffhelper.cli' has no attribute '_resolve_week'`

- [ ] **Step 3: Extract `_resolve_week`**

Cut the block from `_lineup` (the `try: state = load_nfl_state()` through
`season_str = ...`) into:

```python
def _resolve_week(week: int | None) -> tuple[int | None, str, list[str]]:
    """The NFL week and season to work in, plus any degradation notes.

    Returns week=None when neither /state/nfl nor --week supplied one. The
    caller prints and stops: guessing a week (the old `or 1`) is exactly the
    fabrication this design forbids.

    `not week` rather than `week is None` is deliberate -- Sleeper serves
    "week": 0 in the offseason, and the two guards disagreeing is a defect this
    project already shipped once.
    """
    notes: list[str] = []
    try:
        state = load_nfl_state()
    except Exception as exc:                          # noqa: BLE001 - degrade, never fabricate
        state = {}
        notes.append(f"could not reach Sleeper's /state/nfl ({exc}) -- season "
                     f"defaults to {SEASON}")
    if week is None:
        week = state.get("week")
        if not week:
            return None, str(state.get("season") or SEASON), notes
    return int(week), str(state.get("season") or SEASON), notes
```

In `_lineup`, replace the cut block with:

```python
    week, season_str, notes = _resolve_week(week)
    if week is None:
        print("no NFL week available: /state/nfl is unreachable and --week "
              "was not given -- pass e.g. '--week 1' to run without it")
        return 1
```

**`_lineup` still needs the raw `state.get("week")` for `_record_snapshot`'s
current-week check.** Re-read it there via a second `load_nfl_state()` call is
WRONG (two fetches, and they can disagree). Instead have `_resolve_week` return
the raw value too — change the signature to return a 4-tuple
`(week, season_str, notes, state_week)` where `state_week = state.get("week")`,
and update the tests above to unpack four values. Do this now rather than
discovering it in Step 5.

- [ ] **Step 4: Run the week tests and the whole suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k resolve_week -v`
Expected: PASS

Run: `.venv/bin/python -m pytest`
Expected: 422 passed (419 + 3). **If any pre-existing `_lineup` test fails, the
refactor changed behaviour — fix the extraction, never the old test.**

- [ ] **Step 5: Write the characterisation test for `_resolve_my_roster`**

```python
def _fake_players():
    # Real ids and real names: a fixture of round numbers and "Player 1" is the
    # documented cause of seven defects in this project.
    return {
        "4034": data.Player(sleeper_id="4034", name="Josh Allen", position="QB", team="BUF"),
        "8151": data.Player(sleeper_id="8151", name="Jahmyr Gibbs", position="RB", team="DET"),
    }


def test_resolve_my_roster_prefers_the_config_override_and_names_the_owner(monkeypatch):
    rosters = [
        {"roster_id": 3, "owner_id": "u1", "players": ["4034", "8151"], "settings": {"waiver_position": 8}},
        {"roster_id": 5, "owner_id": "u2", "players": [], "settings": {"waiver_position": 1}},
    ]
    monkeypatch.setattr(cli, "load_league_rosters", lambda lid: rosters)
    monkeypatch.setattr(cli, "load_league_users", lambda lid: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: 0)
    league = config.League(name="t", platform="sleeper", league_id="1", roster_id=3)
    settings = _settings_for_test()          # reuse the helper already in tests/test_cli.py
    roster, owner, notes, raw = cli._resolve_my_roster(league, settings, _fake_players())
    assert sorted(p.sleeper_id for p in roster) == ["4034", "8151"]
    assert owner == "jaydenpg"
    assert any("override" in n for n in notes)
    # The raw payload must survive: `waivers` reads waiver_position out of it.
    assert raw is rosters


def test_resolve_my_roster_degrades_to_empty_when_rosters_are_unreachable(monkeypatch):
    def dead(lid):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(cli, "load_league_rosters", dead)
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)
    league = config.League(name="t", platform="sleeper", league_id="1", roster_id=3)
    roster, owner, notes, raw = cli._resolve_my_roster(league, _settings_for_test(), _fake_players())
    assert roster == [] and raw == []
    assert any("rosters endpoint" in n for n in notes)
```

`_settings_for_test()` — if `tests/test_cli.py` has no such helper, build a
`LeagueSettings` inline the same way the existing `_lineup` tests do; **read
them first and match, do not invent a second construction.**

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k resolve_my_roster -v`
Expected: FAIL with `AttributeError: ... has no attribute '_resolve_my_roster'`

- [ ] **Step 7: Extract `_resolve_my_roster`**

Move the whole `if league.platform == "sleeper": ... else: <roster file>` block
out of `_lineup` verbatim into:

```python
def _resolve_my_roster(
    league: League, settings: LeagueSettings, players: dict[str, Player],
) -> tuple[list[Player], str | None, list[str], list[dict]]:
    """Whose roster this is, on either platform, with every degradation note.

    Extracted from `_lineup` so `waivers` cannot grow a second answer to the
    question. Two commands disagreeing about which team they advise is the
    `FLEX_ELIGIBLE` mistake with higher stakes.

    Returns the raw Sleeper `rosters` payload as well: `waivers` reads
    `settings.waiver_position` out of it, and re-fetching would be a second
    call that can disagree with the first.
    """
```

**Move the code; do not retype it.** The block carries six degradation notes
that were each added by a review round finding a real defect. Keep every one,
and keep the `used_override` note in BOTH the success and failure branches.

`_lineup` becomes:

```python
    roster, owner, notes_r, _rosters = _resolve_my_roster(league, settings, players)
    notes += notes_r
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest`
Expected: 424 passed. **Any pre-existing `_lineup` failure means a note or a
branch was dropped in the move — restore it.**

- [ ] **Step 9: Run `lineup` against the real league to prove the refactor is invisible**

Run, and compare against the output in the session log before the change:
```bash
.venv/bin/python -m ffhelper.cli lineup --league sleeper-main
.venv/bin/python -m ffhelper.cli lineup --league yahoo-main
```
Expected: identical lineups, identical notes, identical owner line. This
project's record is that green suites pass over real defects; the refactor is
not done until both leagues print what they printed before.

- [ ] **Step 10: Commit**

```bash
git add ffhelper/cli.py tests/test_cli.py
git commit -m "refactor(cli): extract _resolve_week and _resolve_my_roster from _lineup

waivers needs both, and a second copy of 'whose roster is this' would let two
commands advise different teams from one config -- the FLEX_ELIGIBLE mistake
with higher stakes. Pure move: both leagues print byte-identical lineups.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 2: `data.load_trending`

**Files:**
- Modify: `ffhelper/data.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: `fetch_json(url, cache_key, ttl_seconds, cache_dir, fetcher, stale_ok)`.
- Produces: `load_trending(kind: str, lookback_hours: int = 24, limit: int = 100, cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None) -> dict[str, int]`
  mapping `sleeper_id -> count`.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_trending_maps_player_id_to_count(tmp_path):
    body = '[{"player_id": "11237", "count": 279845}, {"player_id": "8800", "count": 188559}]'
    got = data.load_trending("add", cache_dir=tmp_path, fetcher=lambda url: body)
    assert got == {"11237": 279845, "8800": 188559}


def test_load_trending_cache_key_separates_add_from_drop(tmp_path):
    # Without the kind in the key, the second caller is served the first one's
    # answer and every "dropped" count is silently an "added" count. Same defect
    # as the weekly-projection cache key that had to carry the week.
    data.load_trending("add", cache_dir=tmp_path, fetcher=lambda url: '[{"player_id": "1", "count": 5}]')
    got = data.load_trending("drop", cache_dir=tmp_path, fetcher=lambda url: '[{"player_id": "2", "count": 9}]')
    assert got == {"2": 9}


def test_load_trending_rejects_an_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        data.load_trending("sideways", cache_dir=tmp_path, fetcher=lambda url: "[]")


def test_load_trending_skips_rows_with_no_player_id(tmp_path):
    body = '[{"count": 5}, {"player_id": "8800", "count": 12}]'
    got = data.load_trending("add", cache_dir=tmp_path, fetcher=lambda url: body)
    assert got == {"8800": 12}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_data.py -k trending -v`
Expected: FAIL with `AttributeError: module 'ffhelper.data' has no attribute 'load_trending'`

- [ ] **Step 3: Implement**

```python
SLEEPER_TRENDING_URL = (
    "https://api.sleeper.app/v1/players/nfl/trending/{kind}"
    "?lookback_hours={hours}&limit={limit}"
)


def load_trending(
    kind: str, lookback_hours: int = 24, limit: int = 100,
    cache_dir: Path = CACHE_DIR, fetcher: Callable[[str], str] | None = None,
) -> dict[str, int]:
    """Adds or drops across all of Sleeper in the last `lookback_hours`.

    NATIONAL counts, across millions of leagues -- they say nothing about
    whether your own leaguemates want a player, and must never be used to
    predict whether a claim wins. Price description only; see the spec.

    The cache key carries the kind. Without it the second caller is served the
    first one's answer and every drop count is silently an add count -- the same
    defect the weekly-projection key was fixed for.
    """
    if kind not in ("add", "drop"):
        raise ValueError(f"trending kind must be 'add' or 'drop', got {kind!r}")
    rows = fetch_json(
        SLEEPER_TRENDING_URL.format(kind=kind, hours=lookback_hours, limit=limit),
        f"trending_{kind}_{lookback_hours}h",
        ttl_seconds=3600,
        cache_dir=cache_dir,
        fetcher=fetcher,
    )
    return {r["player_id"]: r.get("count", 0) for r in rows if r.get("player_id")}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_data.py -k trending -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the mutation**

In `scripts/mutate.py`, in the `"data.py"` block:

```python
        ("trending cache key ignores add/drop",
         'f"trending_{kind}_{lookback_hours}h"', 'f"trending_{lookback_hours}h"'),
```

- [ ] **Step 6: Verify the mutation is killed, run ALONE**

```bash
git status --short > /tmp/before.txt
.venv/bin/python scripts/mutate.py
git status --short > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "tree restored clean"
```
Expected: the new mutation reports **killed**; `diff` is empty. Nothing else may
run while this does.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/data.py tests/test_data.py scripts/mutate.py
git commit -m "feat(data): load_trending, keyed on kind

National add/drop counts as a PRICE signal only. The cache key carries the kind
or the second caller is served the first one's answer.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 3: `season.free_agent_pool` and `season.waiver_position`

Two small pure functions, together because they read the same `rosters` payload
and a reviewer would accept or reject them as one.

**Files:**
- Modify: `ffhelper/season.py`
- Test: `tests/test_season.py`

**Interfaces:**
- Consumes: `data.Player`.
- Produces:
  - `LAST_REGULAR_WEEK: int = 18`
  - `free_agent_pool(players: dict[str, Player], rosters: list[dict], projected_ids: set[str]) -> list[Player]`
  - `waiver_position(rosters: list[dict], roster_id: int) -> tuple[int | None, int]`

- [ ] **Step 1: Write the failing tests**

```python
def _pool():
    return {
        "4034": Player(sleeper_id="4034", name="Josh Allen", position="QB", team="BUF"),
        "8151": Player(sleeper_id="8151", name="Jahmyr Gibbs", position="RB", team="DET"),
        "6790": Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU"),
        "1234": Player(sleeper_id="1234", name="Marcedes Lewis", position="TE", team=None),
    }


def test_free_agent_pool_removes_every_rostered_player_not_just_mine():
    rosters = [{"roster_id": 3, "players": ["4034"]}, {"roster_id": 5, "players": ["8151"]}]
    got = season.free_agent_pool(_pool(), rosters, {"4034", "8151", "6790", "1234"})
    assert [p.sleeper_id for p in got] == ["6790", "1234"]


def test_free_agent_pool_keeps_only_players_with_a_projection():
    # 3051 of the 3231-player pool are unrostered, and most are retired or on a
    # practice squad. Without this filter the board is a list of retirees.
    rosters = [{"roster_id": 3, "players": ["4034"]}]
    got = season.free_agent_pool(_pool(), rosters, {"8151", "6790"})
    assert [p.sleeper_id for p in got] == ["8151", "6790"]


def test_free_agent_pool_survives_a_roster_with_players_none():
    # Sleeper serves "players": null for an empty roster; `or []` is required.
    rosters = [{"roster_id": 3, "players": None}, {"roster_id": 5, "players": ["4034"]}]
    got = season.free_agent_pool(_pool(), rosters, {"4034", "8151"})
    assert [p.sleeper_id for p in got] == ["8151"]


def test_waiver_position_reads_my_row_and_counts_the_league():
    rosters = [
        {"roster_id": 3, "settings": {"waiver_position": 8}},
        {"roster_id": 5, "settings": {"waiver_position": 1}},
    ]
    assert season.waiver_position(rosters, 3) == (8, 2)


def test_waiver_position_is_none_when_the_payload_carries_none():
    # Degrade, never fabricate: a missing position must not become 1.
    rosters = [{"roster_id": 3, "settings": {}}]
    assert season.waiver_position(rosters, 3) == (None, 1)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_season.py -k "free_agent_pool or waiver_position" -v`
Expected: FAIL with `AttributeError: module 'ffhelper.season' has no attribute 'free_agent_pool'`

- [ ] **Step 3: Implement**

```python
# The 2026 regular season. Week 18 is the last one a fantasy roster can score
# in; playoffs are league-configured and this tool does not model them.
LAST_REGULAR_WEEK = 18


def free_agent_pool(
    players: dict[str, Player], rosters: list[dict], projected_ids: set[str],
) -> list[Player]:
    """Everyone not on ANY roster who carries a projection in the horizon.

    Both halves are load-bearing. Subtracting only YOUR roster offers you
    players another team owns. Skipping the projection filter leaves 3051 of
    the 3231-player pool, nearly all retired or on a practice squad.
    """
    rostered: set[str] = set()
    for r in rosters:
        rostered |= set(r.get("players") or [])
    return [p for pid, p in players.items()
            if pid not in rostered and pid in projected_ids]


def waiver_position(rosters: list[dict], roster_id: int) -> tuple[int | None, int]:
    """(your rolling-waiver position, number of teams).

    The league is NOT FAAB -- see the spec. Position is None when the payload
    does not carry one; the caller drops the line rather than printing a 1.
    """
    mine = next((r for r in rosters if r.get("roster_id") == roster_id), None)
    pos = (mine or {}).get("settings", {}).get("waiver_position")
    return pos, len(rosters)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_season.py -k "free_agent_pool or waiver_position" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the mutations**

In `scripts/mutate.py`, in the `"season.py"` block:

```python
        ("free agent pool subtracts only my roster",
         "rostered |= set(r.get(\"players\") or [])", "rostered = set(r.get(\"players\") or [])"),
        ("free agent pool skips the projection filter",
         "if pid not in rostered and pid in projected_ids", "if pid not in rostered"),
```

- [ ] **Step 6: Verify killed, ALONE**

```bash
git status --short > /tmp/before.txt
.venv/bin/python scripts/mutate.py
git status --short > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "tree restored clean"
```
Expected: both new mutations **killed**, diff empty.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): free_agent_pool and waiver_position

The pool subtracts EVERY roster, not just mine, and keeps only projected
players -- without the filter it is 3051 mostly-retired names.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 4: `season.roster_upgrade` — the add-and-drop primitive

The core arithmetic. One candidate, one horizon, the best drop to pay for him.

**Files:**
- Modify: `ffhelper/season.py`
- Test: `tests/test_season.py`

**Interfaces:**
- Consumes: `value.optimal_lineup`, `season.with_weekly_points`, `LAST_REGULAR_WEEK`.
- Produces:
  - `horizon_total(roster: list[Player], roster_slots: dict[str, int], weekly_by_week: dict[int, dict[str, float]]) -> float`
  - `roster_upgrade(roster, candidate, roster_slots, weekly_by_week, drop_tie_points: float = 0.5) -> tuple[float, Player, int]`
    returning `(gain, drop, weeks_started)`.

`weekly_by_week` is `{week_number: {sleeper_id: points}}` — the output of
`weekly_points` per week, keyed by week.

- [ ] **Step 1: Write the failing tests**

```python
def _slots():
    return {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}


def _roster_for_upgrade():
    # Shaped like the real sleeper-main roster: one TE, a backup QB, RB depth.
    return [
        Player(sleeper_id="4034", name="Josh Allen", position="QB", team="BUF"),
        Player(sleeper_id="4892", name="Kyler Murray", position="QB", team="ARI"),
        Player(sleeper_id="4988", name="D'Andre Swift", position="RB", team="CHI"),
        Player(sleeper_id="9509", name="TreVeyon Henderson", position="RB", team="NE"),
        Player(sleeper_id="7591", name="Kenny Gainwell", position="RB", team="PIT"),
        Player(sleeper_id="9226", name="Jaxon Smith-Njigba", position="WR", team="SEA"),
        Player(sleeper_id="6794", name="Chris Olave", position="WR", team="NO"),
        Player(sleeper_id="8130", name="Christian Watson", position="WR", team="GB"),
        Player(sleeper_id="8144", name="Jake Ferguson", position="TE", team="DAL"),
        Player(sleeper_id="7839", name="Jason Myers", position="K", team="SEA"),
        Player(sleeper_id="DEN", name="Denver Broncos", position="DEF", team="DEN"),
    ]


_WK = {
    "4034": 24.4, "4892": 20.1, "4988": 13.5, "9509": 10.0, "7591": 9.5,
    "9226": 19.7, "6794": 16.2, "8130": 13.7, "8144": 9.7, "7839": 7.8, "DEN": 7.4,
}


def test_roster_upgrade_pays_for_the_add_with_a_drop():
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")
    weekly = {1: {**_WK, "6790": 12.0}}
    gain, drop, weeks_started = season.roster_upgrade(roster, cand, _slots(), weekly)
    # Schultz (12.0) starts at TE over Ferguson (9.7): +2.3. The drop must be a
    # player who was not starting, or the gain would be smaller.
    assert gain == pytest.approx(2.3)
    assert drop.sleeper_id == "7591"          # Gainwell: RB3, lowest own points
    assert weeks_started == 1


def test_roster_upgrade_is_negative_when_nobody_can_be_spared():
    # A candidate worse than everyone still forces a drop, so the honest answer
    # is <= 0. Reporting 0.0 would say "free", which it is not.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="0001", name="Practice Squad Guy", position="WR", team="LV")
    weekly = {1: {**_WK, "0001": 0.5}}
    gain, _, weeks_started = season.roster_upgrade(roster, cand, _slots(), weekly)
    assert gain <= 0.0
    assert weeks_started == 0


def test_roster_upgrade_sums_the_whole_horizon_not_just_the_first_week():
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")
    one = {1: {**_WK, "6790": 12.0}}
    three = {1: {**_WK, "6790": 12.0}, 2: {**_WK, "6790": 12.0}, 3: {**_WK, "6790": 12.0}}
    g1, _, s1 = season.roster_upgrade(roster, cand, _slots(), one)
    g3, _, s3 = season.roster_upgrade(roster, cand, _slots(), three)
    assert g3 == pytest.approx(g1 * 3)
    assert (s1, s3) == (1, 3)


def test_roster_upgrade_counts_only_the_weeks_the_candidate_actually_starts():
    # A bye is an ABSENT ROW, not a zero -- verified against the live endpoint
    # (Gibbs has no week-6 row). A candidate missing from a week must not be
    # counted as having started it.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")
    weekly = {1: {**_WK, "6790": 12.0}, 2: dict(_WK)}     # week 2: no Schultz row
    _, _, weeks_started = season.roster_upgrade(roster, cand, _slots(), weekly)
    assert weeks_started == 1


def test_roster_upgrade_breaks_a_drop_tie_on_the_droppeds_own_points():
    # Five players tied EXACTLY in the real week-1 run and the first one won by
    # position. Naming an arbitrary member of a tie as "the drop" is fabrication.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="NE", name="New England Patriots", position="DEF", team="NE")
    weekly = {1: {**_WK, "NE": 9.0}}
    # Upgrading DEF gains 1.6 regardless of who is cut, as long as they were not
    # starting -- Gainwell (9.5) and Murray (20.1) both qualify. The rule takes
    # the lowest own points, which is Gainwell.
    gain, drop, _ = season.roster_upgrade(roster, cand, _slots(), weekly)
    assert gain == pytest.approx(1.6)
    assert drop.sleeper_id == "7591"
```

**Before implementing, run each of these by hand against `_slots()` and `_WK`
and confirm the expected number.** If an assertion is wrong, the fixture is
wrong — fix the fixture, never loosen the assertion to whatever the code
returns. A test written to match the implementation proves nothing.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_season.py -k roster_upgrade -v`
Expected: FAIL with `AttributeError: module 'ffhelper.season' has no attribute 'roster_upgrade'`

- [ ] **Step 3: Implement**

```python
def horizon_total(
    roster: list[Player], roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]],
) -> float:
    """Points the optimal lineup scores across every week in the horizon."""
    return sum(lineup_value(with_weekly_points(roster, wk), roster_slots)
               for wk in weekly_by_week.values())


def roster_upgrade(
    roster: list[Player], candidate: Player, roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]], drop_tie_points: float = 0.5,
) -> tuple[float, Player, int]:
    """(gain, drop, weeks_started) for adding `candidate` at the cost of one cut.

    The roster is full, so an add IS an add-and-drop. An add-only number
    overstates every candidate by the value of whoever you would have cut, and
    then no two candidates are comparable.

    THE DROP IS CHOSEN ON THE WHOLE HORIZON, never one week. A one-week horizon
    happily offers to cut your backup quarterback for 1.2 points of streaming
    defense -- right arithmetic, ruinous advice.

    Ties are real and must not be broken by list order: in the real week-1 run
    five drops tied EXACTLY, and naming an arbitrary one of them is fabrication.
    Among drops within `drop_tie_points` of the best, the one with the fewest
    projected points of his own is taken, and the caller prints that rule.
    """
    base = horizon_total(roster, roster_slots, weekly_by_week)
    own = {p.sleeper_id: sum(wk.get(p.sleeper_id, 0.0) for wk in weekly_by_week.values())
           for p in roster}

    scored: list[tuple[float, Player]] = []
    for i, dropped in enumerate(roster):
        trial = [*roster[:i], *roster[i + 1:], candidate]
        scored.append((horizon_total(trial, roster_slots, weekly_by_week) - base, dropped))

    best_gain = max(g for g, _ in scored)
    tied = [(own[p.sleeper_id], g, p) for g, p in scored
            if g >= best_gain - drop_tie_points]
    _, gain, drop = min(tied, key=lambda t: (t[0], t[2].sleeper_id))

    kept = [p for p in roster if p.sleeper_id != drop.sleeper_id] + [candidate]
    weeks_started = sum(
        1 for wk in weekly_by_week.values()
        if candidate.sleeper_id in wk
        and any(p is not None and p.sleeper_id == candidate.sleeper_id
                for _, p in optimal_lineup(with_weekly_points(kept, wk), roster_slots))
    )
    return gain, drop, weeks_started
```

Note `min(..., key=(own_points, sleeper_id))`: the id is the final tie-break so
the answer is deterministic across runs. A non-deterministic drop name is a
board that changes when nothing changed.

Add to the imports at the top of `season.py`:
```python
from ffhelper.value import FLEX_ELIGIBLE, lineup_value, optimal_lineup
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_season.py -k roster_upgrade -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the mutations**

```python
        ("drop chosen on one week instead of the horizon",
         "scored.append((horizon_total(trial, roster_slots, weekly_by_week) - base, dropped))",
         "scored.append((lineup_value(with_weekly_points(trial, next(iter(weekly_by_week.values()))), roster_slots) - base, dropped))"),
        ("drop tie broken by list order",
         "_, gain, drop = min(tied, key=lambda t: (t[0], t[2].sleeper_id))",
         "_, gain, drop = tied[0]"),
        ("weeks_started counts weeks with no row for the candidate",
         "if candidate.sleeper_id in wk", "if True"),
```

- [ ] **Step 6: Verify killed, ALONE**

```bash
git status --short > /tmp/before.txt
.venv/bin/python scripts/mutate.py
git status --short > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "tree restored clean"
```
Expected: all three **killed**, diff empty. If "drop tie broken by list order"
survives, the tie test is not producing a real tie — fix the FIXTURE so the tie
exists, do not weaken the mutation.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): roster_upgrade -- add-and-drop over a horizon

The roster is full, so an add is an add-and-drop; an add-only number overstates
every candidate. The drop is chosen on the whole horizon (one week offers to cut
your backup QB for a streaming defense) and ties break on the dropped player's
own points, because five tied exactly in the real week-1 run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 5: `season.waiver_targets` — the ranking and the significance floor

**Files:**
- Modify: `ffhelper/season.py`
- Test: `tests/test_season.py`

**Interfaces:**
- Consumes: `roster_upgrade`.
- Produces:
  - `@dataclass(frozen=True) class WaiverTarget: player: Player; gain: float; drop: Player; weeks_started: int`
  - `waiver_targets(roster, pool, roster_slots, weekly_by_week, close_call_points: float, limit: int = 10) -> list[WaiverTarget]`

- [ ] **Step 1: Write the failing tests**

```python
def test_waiver_targets_ranks_by_gain_and_respects_the_limit():
    roster = _roster_for_upgrade()
    pool = [
        Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU"),
        Player(sleeper_id="8110", name="Chig Okonkwo", position="TE", team="TEN"),
    ]
    weekly = {1: {**_WK, "6790": 22.0, "8110": 18.0}}
    got = season.waiver_targets(roster, pool, _slots(), weekly, close_call_points=3.0, limit=1)
    assert [t.player.sleeper_id for t in got] == ["6790"]
    assert got[0].gain > got[0].gain - 1        # sanity: a real number, not None


def test_waiver_targets_floor_is_close_call_points_on_a_one_week_horizon():
    roster = _roster_for_upgrade()
    # Ferguson starts TE at 9.7; an 11.7 TE gains exactly 2.0, under the 3.0 bar.
    pool = [Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")]
    weekly = {1: {**_WK, "6790": 11.7}}
    assert season.waiver_targets(roster, pool, _slots(), weekly, close_call_points=3.0) == []
    # 13.7 gains 4.0 and clears it.
    weekly = {1: {**_WK, "6790": 13.7}}
    assert len(season.waiver_targets(roster, pool, _slots(), weekly, close_call_points=3.0)) == 1


def test_waiver_targets_floor_scales_as_sqrt_of_the_horizon():
    # THE POINT OF THE SQRT. close_call_points is calibrated to ONE week's
    # error; independent weekly errors partially cancel, so the bar on a
    # 9-week total is 3.0*3 = 9.0, not 3.0*9 = 27.0. A flat per-week bar is
    # ~4x too strict and silences real upgrades.
    roster = _roster_for_upgrade()
    pool = [Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")]
    # +1.3 a week over 9 weeks = 11.7 total. Bar is 9.0, so it clears.
    weekly = {w: {**_WK, "6790": 11.0} for w in range(1, 10)}
    got = season.waiver_targets(roster, pool, _slots(), weekly, close_call_points=3.0)
    assert len(got) == 1 and got[0].weeks_started == 9
    # A flat 3.0/week bar would have demanded 27.0 and printed nothing.
    assert got[0].gain < 27.0


def test_waiver_targets_returns_empty_when_nothing_clears_and_that_is_a_result():
    # The measured healthy-roster case: the best thing available is 0.46 pts a
    # week. An empty board is the honest answer and the caller prints it as one.
    roster = _roster_for_upgrade()
    pool = [Player(sleeper_id="0001", name="Deep Bench Guy", position="WR", team="LV")]
    weekly = {w: {**_WK, "0001": 1.0} for w in range(1, 19)}
    assert season.waiver_targets(roster, pool, _slots(), weekly, close_call_points=3.0) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_season.py -k waiver_targets -v`
Expected: FAIL with `AttributeError: ... has no attribute 'waiver_targets'`

- [ ] **Step 3: Implement**

Add `from math import sqrt` to `season.py`'s imports.

```python
@dataclass(frozen=True)
class WaiverTarget:
    """One free agent worth taking, and what he costs."""
    player: Player
    gain: float
    drop: Player
    weeks_started: int


def waiver_targets(
    roster: list[Player], pool: list[Player], roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]], close_call_points: float,
    limit: int = 10,
) -> list[WaiverTarget]:
    """Free agents whose upgrade clears the noise on this horizon, best first.

    THE FLOOR IS `close_call_points * sqrt(weeks)`, and the sqrt is the whole
    point. `close_call_points` is calibrated to a SINGLE week's projection error
    (TE weekly MAE 3.23, measured on 2025). The error on a fourteen-week total
    is not fourteen times that -- independent weekly errors partially cancel, so
    the standard error of a sum grows as sqrt(n). A flat per-week bar is roughly
    four times too strict and silences real upgrades.

    On a one-week horizon sqrt(1) = 1, so this same function serves the "this
    week" section with no branch and no second threshold.

    AN EMPTY LIST IS A RESULT, NOT A FAILURE. On a healthy 15-man roster the
    best thing on the wire is 0.46 points a week; ranking that would be the
    over-reaction the matchup adjustment already died on. The caller says so in
    a sentence.
    """
    floor = close_call_points * sqrt(len(weekly_by_week))
    out: list[WaiverTarget] = []
    for candidate in pool:
        gain, drop, weeks_started = roster_upgrade(
            roster, candidate, roster_slots, weekly_by_week)
        if gain > floor:
            out.append(WaiverTarget(candidate, gain, drop, weeks_started))
    out.sort(key=lambda t: (-t.gain, t.player.sleeper_id))
    return out[:limit]
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_season.py -k waiver_targets -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the mutation**

```python
        ("waiver floor does not scale with the horizon",
         "floor = close_call_points * sqrt(len(weekly_by_week))",
         "floor = close_call_points"),
```

- [ ] **Step 6: Verify killed, ALONE**

Same three-command block as Task 4 Step 6. Expected: **killed**, diff empty.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): waiver_targets and the sqrt(weeks) significance floor

close_call_points is calibrated to ONE week's error; weekly errors partially
cancel, so the bar on a season total grows as sqrt(n). A flat per-week bar is
~4x too strict. sqrt(1)=1, so one function serves both horizons.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 6: `render_waivers` — the screen, as a pure function

Rendering is separated from fetching for the same reason `render_lineup` is:
it is the part worth testing, and it must test without a network.

**Files:**
- Modify: `ffhelper/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `season.WaiverTarget`, `season.waiver_position`.
- Produces:
  `render_waivers(this_week: list[WaiverTarget], ros: list[WaiverTarget], week: int, last_week: int, league_name: str, owner: str | None, position: int | None, teams: int, trending: dict[str, int], notes: list[str], weeks_scored: int) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def _target(pid, name, pos, gain, drop_name, weeks):
    return season.WaiverTarget(
        player=data.Player(sleeper_id=pid, name=name, position=pos, team="X"),
        gain=gain,
        drop=data.Player(sleeper_id="7591", name=drop_name, position="RB", team="PIT"),
        weeks_started=weeks,
    )


def test_render_waivers_says_so_plainly_when_both_boards_are_empty():
    out = cli.render_waivers([], [], week=1, last_week=18, league_name="sleeper-main",
                             owner="jaydenpg", position=8, teams=12, trending={},
                             notes=[], weeks_scored=18)
    assert "nothing on the wire" in out.lower()
    # An empty board is a RESULT. It must never render as a blank section that
    # reads like a failed fetch.
    assert out.strip() != ""
    assert "THIS WEEK" not in out


def test_render_waivers_names_the_drop_and_the_caveat():
    ros = [_target("6790", "Dalton Schultz", "TE", 31.7, "Kenny Gainwell", 14)]
    out = cli.render_waivers([], ros, week=5, last_week=18, league_name="sleeper-main",
                             owner=None, position=8, teams=12, trending={}, notes=[],
                             weeks_scored=14)
    assert "Dalton Schultz" in out
    assert "drop Kenny Gainwell" in out
    assert "PROJECTION ONLY" in out
    # The week count is what makes the total readable -- a bye is an absent row.
    assert "14 of 14" in out


def test_render_waivers_states_what_a_claim_costs_you():
    out = cli.render_waivers([], [], week=5, last_week=18, league_name="sleeper-main",
                             owner=None, position=8, teams=12, trending={}, notes=[],
                             weeks_scored=14)
    assert "priority 8 of 12" in out
    assert "12th" in out


def test_render_waivers_omits_the_priority_line_when_the_position_is_unknown():
    out = cli.render_waivers([], [], week=5, last_week=18, league_name="y",
                             owner=None, position=None, teams=0, trending={},
                             notes=[], weeks_scored=14)
    assert "priority" not in out.lower()


def test_render_waivers_labels_trending_as_national():
    ros = [_target("6790", "Dalton Schultz", "TE", 31.7, "Kenny Gainwell", 14)]
    out = cli.render_waivers([], ros, week=5, last_week=18, league_name="s", owner=None,
                             position=8, teams=12, trending={"6790": 279845}, notes=[],
                             weeks_scored=14)
    # National counts say nothing about your eleven opponents. Printing one
    # without that label invites exactly the inference it cannot support.
    assert "NOT your league" in out or "not a signal about your league" in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k render_waivers -v`
Expected: FAIL with `AttributeError: module 'ffhelper.cli' has no attribute 'render_waivers'`

- [ ] **Step 3: Implement**

Follow `render_lineup`'s existing style (read it at `ffhelper/cli.py:1070`
first and match its header and `!!` note conventions).

```python
DROP_CAVEAT = ("  the drop is by PROJECTION ONLY -- it does not know about handcuffs,\n"
               "  upside, or your bye weeks. read it, do not follow it.")


def render_waivers(
    this_week: list[season_mod.WaiverTarget], ros: list[season_mod.WaiverTarget],
    week: int, last_week: int, league_name: str, owner: str | None,
    position: int | None, teams: int, trending: dict[str, int],
    notes: list[str], weeks_scored: int,
) -> str:
    """The waiver board. Pure: takes data, returns the screen."""
    lines = [f"WAIVERS -- {league_name}"
             + (f" ({owner})" if owner else "") + f" -- week {week}"]
    for n in notes:
        lines.append(f"  !! {n}")
    if position is not None and teams:
        lines.append(f"  waiver priority {position} of {teams} -- a successful claim "
                     f"sends you to {teams}th")

    def section(title: str, targets: list[season_mod.WaiverTarget], of: int) -> None:
        lines.append("")
        lines.append(title)
        for t in targets:
            lines.append(f"  {t.player.position:<3} {t.player.name:<26} "
                         f"+{t.gain:6.1f}   add, drop {t.drop.name} "
                         f"({t.weeks_started} of {of} starts)")
            count = trending.get(t.player.sleeper_id)
            if count:
                lines.append(f"        trending +{count:,} adds NATIONALLY "
                             f"-- NOT your league")

    if this_week:
        section(f"THIS WEEK -- upgrade to your week {week} lineup", this_week, 1)
    if ros:
        section(f"REST OF SEASON -- upgrade over weeks {week}-{last_week}",
                ros, weeks_scored)

    if not this_week and not ros:
        # A RESULT, not a blank. On a healthy roster the best thing available is
        # inside the measured weekly error, and saying nothing at all would read
        # as a failed fetch.
        lines.append("")
        lines.append("  nothing on the wire beats what you already have.")
        lines.append(f"  (a target must gain more than the weekly projection error "
                     f"to be listed -- see the spec.)")
    else:
        lines.append("")
        lines.append(DROP_CAVEAT)
    return "\n".join(lines)
```

`teams}th` renders "12th" correctly for this league and "1th"/"2th"/"3th"
elsewhere. **ponytail: ordinal suffix is wrong for teams ending 1, 2 or 3 —
no fantasy league has fewer than 4 teams, so it cannot fire here; fix it with a
suffix helper if this ever renders a non-league number.** Put that comment in
the source.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k render_waivers -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the mutation**

```python
        ("empty waiver board renders as a blank",
         'lines.append("  nothing on the wire beats what you already have.")',
         "pass"),
```

- [ ] **Step 6: Verify killed, ALONE**

Same block as before. Expected: **killed**, diff empty.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/cli.py tests/test_cli.py scripts/mutate.py
git commit -m "feat(cli): render_waivers, with the empty board as a stated result

An empty board is the honest answer on a healthy roster and must not render as
a blank section that reads like a failed fetch.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 7: `_waivers` and the `waivers` subcommand

**Files:**
- Modify: `ffhelper/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `_waivers(league: League, tunables: Tunables, week: int | None = None, limit: int = 10) -> int`, wired into `main`.

- [ ] **Step 1: Write the failing tests**

```python
def test_waivers_refuses_on_yahoo_because_there_is_no_pool(capsys):
    league = config.League(name="yahoo-main", platform="yahoo", league_id="723573")
    rc = cli._waivers(league, config.Tunables(), week=5)
    out = capsys.readouterr().out
    assert rc == 1
    # Labelled, not silent, and it says WHY -- the pool needs every roster.
    assert "yahoo" in out.lower() and "every roster" in out.lower()


def test_waivers_survives_a_dead_trending_endpoint(monkeypatch, capsys):
    _stub_waiver_inputs(monkeypatch)               # see below
    def dead(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(cli, "load_trending", dead)
    rc = cli._waivers(_sleeper_league(), config.Tunables(), week=1)
    out = capsys.readouterr().out
    assert rc == 0                                  # the board is the product
    assert "trending" in out.lower()                # says the column is gone
    assert "NATIONALLY" not in out                  # and prints no count


def test_waivers_drops_a_week_whose_projections_fail_and_says_how_many_scored(
        monkeypatch, capsys):
    # A failed week must not silently shrink the horizon -- the total would look
    # smaller for a reason nothing on screen explains.
    _stub_waiver_inputs(monkeypatch, fail_weeks={3})
    rc = cli._waivers(_sleeper_league(), config.Tunables(), week=1)
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 week of projections" in out or "could not be scored" in out
```

Write `_stub_waiver_inputs` and `_sleeper_league` as module-level helpers in
`tests/test_cli.py`, stubbing `load_players`, `load_weekly_projections`,
`load_league_rosters`, `load_league_users`, `load_nfl_state`, `load_trending`
and `cache_age_minutes`. **Model them on the existing `_lineup` test stubs in
that file — read those first and reuse their fixtures rather than writing a
second set.** The `_no_network` conftest fixture will catch any loader you miss,
by raising rather than by silently fetching.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k waivers -v`
Expected: FAIL with `AttributeError: module 'ffhelper.cli' has no attribute '_waivers'`

- [ ] **Step 3: Implement**

```python
def _waivers(league: League, tunables: Tunables, week: int | None = None,
             limit: int = 10) -> int:
    """Rank the free-agent pool. One shot -- no loop, no polling."""
    if league.platform != "sleeper":
        # Not a fallback and not a bug: the pool is the full player list minus
        # the union of EVERY roster, and Yahoo serves no rosters without API
        # access. A pool built from one hand-entered roster would be silently
        # wrong, which is worse than absent.
        print(f"waivers needs every team's roster to know who is free, and "
              f"{league.platform} has no API access -- so this command is "
              f"Sleeper-only. `lineup` still works for {league.name}.")
        return 1

    settings = resolve_settings(league)
    week, season_str, notes, _state_week = _resolve_week(week)
    if week is None:
        print("no NFL week available: /state/nfl is unreachable and --week "
              "was not given -- pass e.g. '--week 1' to run without it")
        return 1

    players = load_players()
    roster, owner, notes_r, rosters = _resolve_my_roster(league, settings, players)
    notes += notes_r
    if not roster:
        print("no roster resolved, so there is nothing to upgrade -- "
              + "; ".join(notes))
        return 1

    weekly_by_week: dict[int, dict[str, float]] = {}
    failed: list[int] = []
    for w in range(week, season_mod.LAST_REGULAR_WEEK + 1):
        try:
            rows = load_weekly_projections(season_str, w)
        except Exception as exc:                      # noqa: BLE001 - degrade, never fabricate
            failed.append(w)
            continue
        weekly_by_week[w] = season_mod.weekly_points(rows, settings.scoring)
    if not weekly_by_week:
        print("no weekly projections could be fetched -- nothing can be ranked")
        return 1
    if failed:
        # A shorter horizon is a smaller total, and a total that shrank for an
        # unexplained reason is the kind of silent wrongness this project keeps
        # finding. Say which weeks are missing.
        notes.append(f"{len(failed)} week(s) of projections could not be scored "
                     f"({', '.join(str(w) for w in failed)}) -- the rest-of-season "
                     f"total covers {len(weekly_by_week)} weeks, not "
                     f"{season_mod.LAST_REGULAR_WEEK - week + 1}")

    projected = set().union(*(set(wk) for wk in weekly_by_week.values()))
    pool = season_mod.free_agent_pool(players, rosters, projected)

    this_week_horizon = {week: weekly_by_week[week]} if week in weekly_by_week else {}
    this_week = season_mod.waiver_targets(
        roster, pool, settings.roster_slots, this_week_horizon,
        tunables.close_call_points, limit) if this_week_horizon else []
    ros = season_mod.waiver_targets(
        roster, pool, settings.roster_slots, weekly_by_week,
        tunables.close_call_points, limit)

    try:
        trending = load_trending("add")
    except Exception as exc:                          # noqa: BLE001 - degrade, never fabricate
        trending = {}
        notes.append(f"could not reach Sleeper's trending endpoint ({exc}) -- "
                     f"the trending column is absent")

    rid = next((r.get("roster_id") for r in rosters
                if set(r.get("players") or []) & {p.sleeper_id for p in roster}), None)
    position, teams = season_mod.waiver_position(rosters, rid) if rid else (None, 0)

    print(render_waivers(this_week, ros, week, season_mod.LAST_REGULAR_WEEK,
                         league.name, owner, position, teams, trending, notes,
                         len(weekly_by_week)))
    return 0
```

**The `rid` re-derivation above is a smell.** `_resolve_my_roster` already knew
the roster_id and threw it away. If Task 1's extraction can return it as a fifth
element without disturbing `_lineup`, do that instead and delete these two
lines — a second derivation of one fact is how this project's own conventions
say two sources of truth start disagreeing. Prefer the fix; only keep the
re-derivation if `_lineup` would have to change to accommodate it.

Wire into `main`:

```python
    ap.add_argument("command", choices=["run", "preflight", "lineup", "waivers"])
    ...
    if args.command == "waivers":
        return _waivers(league, tunables, args.week, args.limit)
```

Note `--limit` already exists on the parser (default 20) and is used by `run`.
Pass it through; do not add a second flag.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k waivers -v`
Expected: PASS (3 tests)

Run: `.venv/bin/python -m pytest`
Expected: all green, still under ~1.5s and still offline.

- [ ] **Step 5: Add the mutation**

```python
        ("waivers builds the pool from my roster only",
         "pool = season_mod.free_agent_pool(players, rosters, projected)",
         "pool = season_mod.free_agent_pool(players, rosters[:1], projected)"),
```

- [ ] **Step 6: Verify killed, ALONE**

Same block. Expected: **killed**, diff empty.

- [ ] **Step 7: Commit**

```bash
git add ffhelper/cli.py tests/test_cli.py scripts/mutate.py
git commit -m "feat(cli): the waivers subcommand

Sleeper-only and says why: the pool needs every roster and Yahoo has no API.
A week whose projections fail drops out of the horizon and the screen says how
many weeks the total actually covers.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

---

### Task 8: Run it against the real league, then close the branch

**Nothing in this project is done because the suite is green.** Nine defects
have been found by running the code past a fully green suite; this task is the
one that has historically found them.

**Files:**
- Modify: `CLAUDE.md`, `TODO.md`, `README.md` (only if wrong)

- [ ] **Step 1: Run it for real, both leagues**

```bash
time .venv/bin/python -m ffhelper.cli waivers --league sleeper-main
.venv/bin/python -m ffhelper.cli waivers --league yahoo-main
.venv/bin/python -m ffhelper.cli lineup --league sleeper-main
.venv/bin/python -m ffhelper.cli preflight --league sleeper-main
```

**Expected, and this is the acceptance criterion that matters:**
- `sleeper-main` in week 1 prints **an empty board** with the "nothing on the
  wire" line. A board with rows on a healthy 15-man roster in week 1 is **the
  defect, not the success** — it means the floor is wrong or the pool is
  polluted. Investigate before shipping.
- `yahoo-main` refuses, labelled, exit 1.
- `lineup` and `preflight` print exactly what they printed before Task 1.
- Wall clock on a warm cache is a few seconds. A cold cache fetches ~108 files
  (6 positions × 18 weeks) and will be slower; run it twice.

- [ ] **Step 2: Verify the empty board is empty for the RIGHT reason**

An empty board and a broken pool look identical on screen. Prove the pipeline
works by lowering the bar temporarily in a scratch script (never in the source):

```bash
.venv/bin/python - <<'EOF'
from ffhelper import cli, config, season
# close_call_points=0.0 turns the floor off. If this still prints nothing, the
# pool or the horizon is broken -- not the floor.
leagues, _ = config.load_config(cli.ROOT / "config.toml")
lg = [l for l in leagues if l.name == "sleeper-main"][0]
cli._waivers(lg, config.Tunables(close_call_points=0.0), week=1)
EOF
```
Expected: with the floor off, rows appear (tight ends, per the spec's §14 note).
That is the pipeline proving itself. **Do not commit this script.**

- [ ] **Step 3: Full mutation run, FOREGROUND and ALONE**

```bash
git status --short > /tmp/before.txt
.venv/bin/python -m pytest        # a mutation run against a RED suite "kills" everything
.venv/bin/python scripts/mutate.py
git status --short > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt && echo "tree restored clean"
```
Expected: 1 needing a look — the documented `value.py` tier-threshold equivalent
mutant — and nothing else. Any other survivor is evidence about a TEST; fix the
test, never the mutation.

- [ ] **Step 4: Update the three docs**

- `CLAUDE.md`: mark 4c COMPLETE in the phases table; add a session-log entry
  recording what the real run printed, the FAAB correction, and the √weeks
  floor error found in self-review.
- `TODO.md`: close the 4c item; record anything the real run turned up.
- `README.md`: **only if it is now wrong.** It gains the `waivers` command line
  and the test count. Generate any sample by RUNNING the code, never by hand.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md TODO.md README.md
git commit -m "docs: phase 4c complete

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011gnmovTPypaCw5DbZuYGJY"
```

- [ ] **Step 6: Report, do not merge**

`main` and the remote are the user's alone. Report the branch, the test count,
the mutation result, and what the real run printed on both leagues.

---

## Self-Review

**Spec coverage:**

| spec section | task |
| --- | --- |
| rolling priority, no FAAB bid | 3 (`waiver_position`), 6 (render) |
| the significance floor, `close_call_points × √weeks` | 5 |
| two sections, one code path | 5, 7 |
| add-and-drop marginal value | 4 |
| drop on the ROS horizon, tie-break stated | 4 |
| free-agent pool = all players − every roster, projected only | 3 |
| `load_trending`, national and labelled | 2, 6 |
| `_resolve_my_roster` extraction | 1 |
| bye = absent row, print the week count | 4 (`weeks_started`), 7 (failed weeks), 6 (render) |
| Yahoo refuses, labelled | 7 |
| degradations: trending, rosters, a failed week | 7 |
| empty board is a printed result | 5, 6, 8 |
| testing discipline, 6 mutations | every task |
| out of scope: snapshot, Dash | not planned — correct |

No gaps.

**Placeholder scan:** none — every step carries runnable code or an exact command.

**Type consistency:** `weekly_by_week: dict[int, dict[str, float]]` is used
identically in Tasks 4, 5 and 7. `WaiverTarget` fields (`player`, `gain`,
`drop`, `weeks_started`) match between Task 5's definition, Task 6's render and
Task 7's caller. `_resolve_my_roster` returns a 4-tuple in Task 1 and is
unpacked as 4 in Task 7 — with a flagged option to make it 5, handled explicitly
rather than left to drift. `_resolve_week` returns a 4-tuple in both Task 1 and
Task 7.

**Two known risks carried deliberately:**
1. **Task 1 is a 90-line move in a working command.** Mitigated by running
   `lineup` on both leagues before and after, which is the only check that
   catches a dropped degradation note.
2. **The Task 4 fixture numbers are hand-computed.** Step 1 says to verify each
   by hand before implementing, because a test written to match the code proves
   nothing — the failure mode this project traced seven defects to.
