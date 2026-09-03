# Phase 5 Trade Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `trades` command that finds two-sided swaps improving both my starting lineup and my counterparty's, over the weeks that still count.

**Architecture:** A trade is `roster_upgrade` run twice — `horizon_total` on both rosters, before and after. A new pure module `ffhelper/trade.py` holds the two-roster search (1-for-1, 2-for-1, 2-for-2, plus a pinned-player mode); `season.py` gains the calendar and a per-week weight vector that `horizon_total` applies; `cli.py` gains `_trades` and `render_trades` mirroring `_waivers`.

**Tech Stack:** Python 3.12 stdlib only. No new dependencies. `itertools.combinations`, `math.ceil/log2/sqrt`.

**Spec:** `docs/superpowers/specs/2026-09-02-phase-5-trade-finder-design.md` — read it before Task 1. The plan argues from the spec and the spec travels with it.

## Global Constraints

Copied verbatim from `CLAUDE.md` and the spec. Every task's requirements implicitly include this section.

- **Python 3.12, stdlib first.** No new dependency. Runtime deps stay `requests`, `yfpy`, `dash`.
- **`value.py` and `season.py` are PURE** — no I/O, no network, no module-level state. `trade.py` obeys the same rule.
- **`store.py` is the only stateful module.** Nothing in this phase writes to it.
- **No module-level league state.** Every function takes league context.
- **Never join load-bearing data on player name.** IDs only. The pinned-player lookup is a UI affordance over `find_players`, and it refuses ambiguity rather than guessing.
- **Degrade, never fabricate.** Every missing source produces a labelled absent column or a stated refusal, never a zero or a guess.
- **No auto-anything.** The tool advises; a human sends the offer.
- **Every new test verified RED before the fix**, via `git stash push -u -- ffhelper && .venv/bin/python -m pytest -k <name>`. **The `-u` is not optional** — `trade.py` is a NEW file and plain `git stash push` leaves it on disk, so the test passes and proves nothing.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** A surviving mutation is evidence about the TEST — fix the test, never weaken the mutation.
- **`scripts/mutate.py` runs in the FOREGROUND, ALONE.** No subagent may run its own concurrently. The suite must be GREEN before a mutation run is believed.
- **No test may reach the network or the real database** — guarded autouse in `tests/conftest.py`. Do not add a fixture that bypasses it.
- Run everything with `.venv/bin/python`.

---

### Task 1: The playoff calendar, read from the payload

The league's fantasy season ends at week 17, not 18. `season.LAST_REGULAR_WEEK = 18` is already shipped and is wrong for this league. Read `playoff_week_start` and `playoff_teams` rather than assuming.

**Files:**
- Modify: `ffhelper/data.py` — `LeagueSettings` (line ~263), `load_sleeper_settings` (line ~296)
- Modify: `ffhelper/season.py` — add `last_scoring_week` beside `LAST_REGULAR_WEEK` (line ~44)
- Test: `tests/test_data.py`, `tests/test_season.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `LeagueSettings.playoff_week_start: int | None`, `.playoff_teams: int | None`, `.playoff_round_type: int | None`; `season.last_scoring_week(settings: LeagueSettings) -> tuple[int, str | None]` returning `(week, note)` where `note` is `None` when the calendar was read cleanly.

- [ ] **Step 1: Write the failing tests**

In `tests/test_season.py`:

```python
def _settings(**kw):
    """A LeagueSettings with the real sleeper-main shape, overridable per test."""
    from ffhelper.data import LeagueSettings
    base = dict(
        num_teams=12,
        scoring={"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
        playoff_week_start=15,
        playoff_teams=6,
        playoff_round_type=0,
    )
    base.update(kw)
    return LeagueSettings(**base)


def test_last_scoring_week_is_the_final_playoff_week_not_week_18():
    """6 teams is a 3-round bracket, so 15 -> 17. Week 18 is played by nobody
    and contributes to no fantasy outcome; summing it silently pads every
    rest-of-season total with a week that cannot be won."""
    week, note = season.last_scoring_week(_settings())
    assert week == 17
    assert note is None


def test_last_scoring_week_handles_a_four_team_bracket():
    """ceil(log2(4)) = 2 rounds, so 15 -> 16. The arithmetic must follow the
    bracket, not a constant offset."""
    week, note = season.last_scoring_week(_settings(playoff_teams=4))
    assert week == 16
    assert note is None


def test_last_scoring_week_refuses_multi_week_rounds_and_says_so():
    """playoff_round_type != 0 means a round spans two weeks, which this tool
    does not model. Fall back to the constant and NAME the reason -- computing
    a confident wrong last week is the fabrication this project forbids."""
    week, note = season.last_scoring_week(_settings(playoff_round_type=1))
    assert week == season.LAST_REGULAR_WEEK
    assert note is not None and "round" in note


def test_last_scoring_week_falls_back_when_the_league_serves_no_playoff_fields():
    """Yahoo's hand-entered settings carry no playoff block at all. Degrade to
    the constant with a note, never to a guessed bracket."""
    week, note = season.last_scoring_week(
        _settings(playoff_week_start=None, playoff_teams=None, playoff_round_type=None))
    assert week == season.LAST_REGULAR_WEEK
    assert note is not None
```

In `tests/test_data.py`:

```python
def test_sleeper_settings_carry_the_playoff_calendar():
    """The horizon end is a league RULE and must be read, not assumed. Same
    class as the one-RB-slot and FAAB errors, both of which came from taking an
    API default as fact."""
    payload = {
        "total_rosters": 12,
        "scoring_settings": {"rec": 1.0},
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                             "K", "DEF", "BN", "BN", "BN", "BN", "BN"],
        "draft_id": "123",
        "settings": {"playoff_week_start": 15, "playoff_teams": 6,
                     "playoff_round_type": 0},
    }
    st = data.load_sleeper_settings(
        "L1", cache_dir=tmp_cache(), fetcher=lambda url: json.dumps(payload))
    assert st.playoff_week_start == 15
    assert st.playoff_teams == 6
    assert st.playoff_round_type == 0


def test_sleeper_settings_playoff_fields_are_none_when_absent():
    """A payload without a settings block must yield None, not 0 -- 0 would
    read as 'playoffs start week 0' and produce a nonsense horizon."""
    payload = {"total_rosters": 12, "scoring_settings": {}, "roster_positions": ["QB"]}
    st = data.load_sleeper_settings(
        "L1", cache_dir=tmp_cache(), fetcher=lambda url: json.dumps(payload))
    assert st.playoff_week_start is None
    assert st.playoff_teams is None
```

Match the existing `tests/test_data.py` conventions for `tmp_cache()` and the `fetcher=` seam — read a neighbouring test in that file and copy its shape exactly rather than inventing one.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_season.py -k last_scoring_week -v
.venv/bin/python -m pytest tests/test_data.py -k playoff -v
```

Expected: FAIL — `AttributeError: module 'ffhelper.season' has no attribute 'last_scoring_week'`, and `TypeError: LeagueSettings.__init__() got an unexpected keyword argument 'playoff_week_start'`.

- [ ] **Step 3: Add the fields**

In `ffhelper/data.py`, extend `LeagueSettings` (keep every existing field and its order; the new ones default to `None` so hand-entered Yahoo settings keep constructing):

```python
@dataclass(frozen=True)
class LeagueSettings:
    num_teams: int
    scoring: dict[str, float]
    roster_slots: dict[str, int]   # e.g. {"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":2,"K":1,"DEF":1}
    rounds: int
    draft_id: str | None = None
    # The fantasy calendar, read from the league payload rather than assumed.
    # `LAST_REGULAR_WEEK = 18` is the NFL's last week, not the league's: with
    # playoffs starting week 15 and a three-round bracket the season ends at
    # 17, and week 18 is played by nobody. None means the platform served no
    # playoff block (Yahoo's hand-entered settings), and the caller degrades.
    playoff_week_start: int | None = None
    playoff_teams: int | None = None
    playoff_round_type: int | None = None
    # The last week a trade may be made. 11 in the real league. Task 8 refuses
    # to print proposals past it -- offering a trade you are not allowed to
    # make is worse than offering none.
    trade_deadline: int | None = None
```

In `load_sleeper_settings`, read them out of the nested `settings` object:

```python
    raw_settings = raw.get("settings") or {}
    return LeagueSettings(
        num_teams=raw.get("total_rosters", 12),
        scoring={k: float(v) for k, v in (raw.get("scoring_settings") or {}).items()},
        roster_slots=slots,
        rounds=len(positions),
        draft_id=raw.get("draft_id"),
        playoff_week_start=raw_settings.get("playoff_week_start"),
        playoff_teams=raw_settings.get("playoff_teams"),
        playoff_round_type=raw_settings.get("playoff_round_type"),
        trade_deadline=raw_settings.get("trade_deadline"),
    )
```

Add `trade_deadline` to the Step 1 test's payload and assert it reads `11`, so the field is covered by the same red-first check as the others.

- [ ] **Step 4: Add `last_scoring_week`**

In `ffhelper/season.py`, directly below `LAST_REGULAR_WEEK`. Add `from math import ceil, log2` to the existing `math` import line:

```python
def last_scoring_week(settings: LeagueSettings) -> tuple[int, str | None]:
    """The last week this league actually scores, and a note if it was guessed.

    LAST_REGULAR_WEEK is the NFL's last week, not the league's. With playoffs
    starting week 15 and six teams (a three-round bracket) the fantasy season
    ends at week 17 -- week 18 is played by nobody and contributes to no
    outcome, so summing it pads every rest-of-season total by a week that
    cannot be won. Measured on the real league 2026-09-02.

    Returns the constant plus a NOTE rather than a confident wrong week when
    the payload cannot answer: absent playoff fields (Yahoo hand-entered
    settings), or multi-week rounds, which this tool does not model.

    playoff_round_type None is read as 0 (one week per round), which is the
    only shape hand-entered settings can mean.
    """
    start, teams = settings.playoff_week_start, settings.playoff_teams
    if not start or not teams or teams < 2:
        return LAST_REGULAR_WEEK, (
            f"league playoff settings are absent, so the horizon runs to week "
            f"{LAST_REGULAR_WEEK} and may include weeks nobody plays")
    if settings.playoff_round_type not in (None, 0):
        return LAST_REGULAR_WEEK, (
            f"playoff_round_type {settings.playoff_round_type} means multi-week "
            f"rounds, which this tool does not model -- the horizon runs to week "
            f"{LAST_REGULAR_WEEK}")
    return start + ceil(log2(teams)) - 1, None
```

`LeagueSettings` is already imported in `season.py` if it is used elsewhere; if not, add it to the existing `from .data import ...` line.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_season.py tests/test_data.py -v
```

Expected: PASS, with no other test broken. The new `LeagueSettings` fields default to `None`, so every existing construction still works.

- [ ] **Step 6: Add the mutation**

In `scripts/mutate.py`, under the `ffhelper/season.py` key. Anchor the target on enough surrounding text to be unique — the tool refuses a string matching more than one place:

```python
    ("the bracket length is ignored, so the horizon ends on the first playoff week",
     "return start + ceil(log2(teams)) - 1, None",
     "return start, None"),
```

- [ ] **Step 7: Commit**

```bash
git add ffhelper/data.py ffhelper/season.py tests/test_data.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): read the playoff calendar instead of assuming week 18

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 2: `week_weights` — a derived default, and one knob

A point scored in a week you do not play is worth nothing. The default weight for a week is the probability you play it under this league's own bracket. **This weights playoff weeks DOWN, which is deliberate and contested** — see the spec's "Week weights" section, which records both readings and why the tunable exists.

**Files:**
- Modify: `ffhelper/season.py`
- Modify: `ffhelper/config.py` — `Tunables`, `load_config`
- Test: `tests/test_season.py`, `tests/test_config.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `LeagueSettings.playoff_week_start` / `.playoff_teams` (Task 1).
- Produces: `season.week_weights(settings: LeagueSettings, weeks: Iterable[int], playoff_weight: float | None = None) -> dict[int, float]`; `Tunables.playoff_weight: float | None = None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_season.py` (`_settings` from Task 1 is reused):

```python
def test_week_weights_are_one_for_every_regular_season_week():
    w = season.week_weights(_settings(), range(1, 15))
    assert set(w.values()) == {1.0}


def test_week_weights_derive_playoff_weeks_from_the_bracket():
    """6 of 12 teams make it, top two seeded on a bye. So week 15 is played by
    the four unseeded qualifiers, week 16 by four, week 17 by two -- and the
    weight is the share of the league that plays it. Derived from the payload,
    NOT a picked multiplier: a hand-chosen number is what CLAUDE.md forbids."""
    w = season.week_weights(_settings(), range(15, 18))
    assert w[15] == pytest.approx(4 / 12)
    assert w[16] == pytest.approx(4 / 12)
    assert w[17] == pytest.approx(2 / 12)


def test_week_weights_shrink_the_bracket_for_a_four_team_playoff():
    """Two rounds, not three. The round sizes must follow playoff_teams."""
    w = season.week_weights(_settings(playoff_teams=4), range(15, 17))
    assert w[15] == pytest.approx(4 / 12)
    assert w[16] == pytest.approx(2 / 12)


def test_playoff_weight_overrides_the_derivation_for_playoff_weeks_only():
    """The knob exists because the direction is contested -- the literature
    weights playoff weeks UP. Setting it must not touch weeks 1-14."""
    w = season.week_weights(_settings(), range(13, 18), playoff_weight=2.0)
    assert w[13] == 1.0 and w[14] == 1.0
    assert w[15] == 2.0 and w[16] == 2.0 and w[17] == 2.0


def test_week_weights_are_flat_when_the_league_serves_no_playoff_block():
    """Degrade to flat, never to a guessed bracket."""
    w = season.week_weights(_settings(playoff_week_start=None, playoff_teams=None),
                            range(1, 19))
    assert set(w.values()) == {1.0}
```

In `tests/test_config.py`:

```python
def test_playoff_weight_defaults_to_none_and_loads_when_set(tmp_path):
    """None means 'use the derived weights'. A float means the user has taken
    the other reading of playoff value deliberately."""
    p = tmp_path / "c.toml"
    p.write_text('[[league]]\nname="x"\nplatform="sleeper"\nleague_id="1"\n')
    _, tun = config.load_config(p)
    assert tun.playoff_weight is None

    p.write_text('[[league]]\nname="x"\nplatform="sleeper"\nleague_id="1"\n'
                 '[tunables]\nplayoff_weight=1.5\n')
    _, tun = config.load_config(p)
    assert tun.playoff_weight == 1.5
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_season.py -k week_weights -v
.venv/bin/python -m pytest tests/test_config.py -k playoff_weight -v
```

Expected: FAIL — `has no attribute 'week_weights'`, and `AttributeError: 'Tunables' object has no attribute 'playoff_weight'`.

- [ ] **Step 3: Implement `week_weights`**

In `ffhelper/season.py`, below `last_scoring_week`:

```python
def week_weights(
    settings: LeagueSettings, weeks, playoff_weight: float | None = None,
) -> dict[int, float]:
    """How much each week counts, as the probability you play it.

    A point scored in a week you do not play is worth nothing. Under a uniform
    prior over seeds, a regular-season week is played by everyone (1.0) and a
    playoff week by whoever survives to it -- so a 6-of-12 bracket gives
    4/12, 4/12, 2/12 across weeks 15-17.

    THIS WEIGHTS PLAYOFF WEEKS DOWN, which is the opposite of the published
    playoff-biasing work. That work argues conditional value -- points in the
    final matter more BECAUSE the title is decided there -- which is only
    reachable through a matchup win-probability model nobody here has
    validated, and is exactly the hand-picked factor CLAUDE.md forbids. This
    answers the question the tool can answer: expected points that count.

    `playoff_weight` takes the other reading, replacing the derived weights on
    playoff weeks only. It exists because the direction is contested; the
    default refuses to smuggle a preference in as a fact.

    The uniform-seed prior is itself an assumption, and it is the one the
    deferred leverage slice replaces with real standings (TODO.md).
    """
    out = {int(w): 1.0 for w in weeks}
    start, teams, num = (settings.playoff_week_start, settings.playoff_teams,
                         settings.num_teams)
    if not start or not teams or teams < 2 or not num:
        return out
    rounds = ceil(log2(teams))
    bracket = 2 ** rounds
    for i in range(1, rounds + 1):
        wk = start + i - 1
        if wk not in out:
            continue
        if playoff_weight is not None:
            out[wk] = playoff_weight
            continue
        # Round 1 is played only by the teams without a bye; every later round
        # halves the bracket.
        playing = 2 * (teams - bracket // 2) if i == 1 else bracket // (2 ** (i - 1))
        out[wk] = playing / num
    return out
```

- [ ] **Step 4: Add the tunable**

In `ffhelper/config.py`, add to `Tunables` after `close_call_points`:

```python
    # How much a playoff week counts, overriding the derived weight.
    #
    # None (default) uses season.week_weights, which weights a week by the
    # probability you play it -- so playoff weeks come out BELOW 1.0, because
    # you may not be there. The published playoff-biasing work argues the
    # opposite: weight weeks 15-17 UP, because the title is decided there.
    # Both readings are coherent and they answer different questions; the
    # derivation is defaulted because it is the one with a source behind it.
    #
    # Set a float (e.g. 1.5) to take the other reading. To justify it as a
    # default, bring a backtest showing it picks better trades -- the same bar
    # the matchup adjustment failed.
    playoff_weight: float | None = None
```

And in `load_config`, inside the `Tunables(...)` construction:

```python
        playoff_weight=tun_raw.get("playoff_weight", defaults.playoff_weight),
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_season.py tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Add the mutations**

In `scripts/mutate.py`, under `ffhelper/season.py`:

```python
    ("every week weighs the same, so the playoff bracket is ignored",
     "playing = 2 * (teams - bracket // 2) if i == 1 else bracket // (2 ** (i - 1))",
     "playing = num"),
    ("the playoff_weight override leaks onto regular-season weeks",
     "        if wk not in out:\n            continue",
     "        if wk not in out:\n            pass"),
```

- [ ] **Step 7: Commit**

```bash
git add ffhelper/season.py ffhelper/config.py tests/test_season.py tests/test_config.py scripts/mutate.py
git commit -m "feat(season): week_weights -- derived from the bracket, with one knob

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 3: `horizon_total` applies weights; the floor uses their sum

**Files:**
- Modify: `ffhelper/season.py` — `horizon_total` (line ~125), `roster_upgrade` (line ~134), `waiver_targets` (line ~188)
- Test: `tests/test_season.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `week_weights` (Task 2).
- Produces: `horizon_total(roster, roster_slots, weekly_by_week, weights=None) -> float`; `effective_weeks(weekly_by_week, weights=None) -> float`; `roster_upgrade(..., weights=None)`; `waiver_targets(..., weights=None)`. **All new parameters are keyword-with-default, so every existing call site keeps working unchanged.**

- [ ] **Step 1: Write the failing tests**

In `tests/test_season.py`:

```python
def test_horizon_total_scales_each_week_by_its_weight():
    """A half-weighted week contributes half its lineup value. Without this the
    weight vector is inert and every downstream number ignores the calendar."""
    roster = [mk("a", "QB", 0.0)]
    slots = {"QB": 1}
    wbw = {1: {"a": 10.0}, 2: {"a": 10.0}}
    assert season.horizon_total(roster, slots, wbw) == pytest.approx(20.0)
    assert season.horizon_total(roster, slots, wbw, {1: 1.0, 2: 0.5}) == pytest.approx(15.0)


def test_horizon_total_treats_a_week_missing_from_the_weights_as_full():
    """A weight vector built for a different horizon must not silently zero a
    week -- absent means 'not specified', which is 1.0, never 0.0."""
    roster = [mk("a", "QB", 0.0)]
    wbw = {1: {"a": 10.0}, 2: {"a": 10.0}}
    assert season.horizon_total(roster, {"QB": 1}, wbw, {1: 1.0}) == pytest.approx(20.0)


def test_effective_weeks_is_the_sum_of_the_weights():
    """The floor grows as sqrt(n) because independent weekly errors partially
    cancel. A week counted at 0.33 contributes a third of a week's worth of
    error, so the effective sample size is the SUM of the weights, not the
    count. With flat weights this reduces to 4c's rule exactly."""
    wbw = {1: {}, 2: {}, 3: {}}
    assert season.effective_weeks(wbw) == pytest.approx(3.0)
    assert season.effective_weeks(wbw, {1: 1.0, 2: 1.0, 3: 0.5}) == pytest.approx(2.5)


def test_the_waiver_floor_scales_with_the_weights_not_the_week_count():
    """A down-weighted horizon is a smaller sample, so the bar must fall with
    it. Using the raw count keeps a season-length bar over a horizon that is
    effectively one week long, which silences real upgrades.

    Arithmetic, worked before implementing:
      base   = 4 weeks x 0.25 x 10.0 (qb_good starts) = 10.0
      after  = 4 weeks x 0.25 x 14.0 (qb_better starts, qb_bad cut) = 14.0
      gain   = 4.0
      effective weeks = 4 x 0.25 = 1.0 -> floor 3.0 * sqrt(1.0) = 3.0 -> PRINTS
      raw week count  = 4          -> floor 3.0 * sqrt(4.0) = 6.0 -> would NOT
    """
    roster = [mk("qb_good", "QB"), mk("qb_bad", "QB")]
    pool = [mk("qb_better", "QB")]
    slots = {"QB": 1}
    wbw = {w: {"qb_good": 10.0, "qb_bad": 0.0, "qb_better": 14.0}
           for w in range(1, 5)}
    weights = {w: 0.25 for w in range(1, 5)}

    out = season.waiver_targets(roster, pool, slots, wbw, 3.0, weights=weights)
    assert [t.player.sleeper_id for t in out] == ["qb_better"]
    assert out[0].gain == pytest.approx(4.0)
    assert out[0].drop.sleeper_id == "qb_bad"
```

**Confirm that arithmetic by hand before implementing.** The 4c plan's tie fixture was wrong and its own "run the numbers first" instruction is what caught it. If the hand arithmetic disagrees with the assertion, fix the fixture — never loosen the assertion.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_season.py -k "horizon_total or effective_weeks" -v
```

Expected: FAIL — `horizon_total() takes 3 positional arguments but 4 were given`, and `has no attribute 'effective_weeks'`.

- [ ] **Step 3: Implement**

Replace `horizon_total` in `ffhelper/season.py`:

```python
def horizon_total(
    roster: list[Player], roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]],
    weights: dict[int, float] | None = None,
) -> float:
    """Points the optimal lineup scores across every week in the horizon.

    `weights` scales each week by how much it counts -- see `week_weights`. A
    week absent from the vector counts FULLY (1.0), never zero: absent means
    unspecified, and a vector built for a different horizon must not silently
    delete a week.
    """
    return sum(
        lineup_value(with_weekly_points(roster, wk), roster_slots)
        * (1.0 if weights is None else weights.get(w, 1.0))
        for w, wk in weekly_by_week.items()
    )


def effective_weeks(
    weekly_by_week: dict[int, dict[str, float]],
    weights: dict[int, float] | None = None,
) -> float:
    """The sample size a significance floor should be scaled against.

    The floor grows as sqrt(n) because independent weekly errors partially
    cancel. A week counted at 0.33 supplies a third of a week's independent
    error, so the effective n is the SUM of the weights rather than the count.
    Flat weights give back the plain count, which is why one expression serves
    both and no second threshold exists.
    """
    if weights is None:
        return float(len(weekly_by_week))
    return sum(weights.get(w, 1.0) for w in weekly_by_week)
```

In `roster_upgrade`, add `weights: dict[int, float] | None = None` as the last parameter, pass it to both `horizon_total` calls (`base` and the `trial` loop), and **weight `own` too** — it is the drop tie-break's currency, and a tie-break ranking on unweighted points while the gain is weighted would break ties on a different quantity than it claims:

```python
    base = horizon_total(roster, roster_slots, weekly_by_week, weights)
    own = {p.sleeper_id: sum(wk.get(p.sleeper_id, 0.0)
                             * (1.0 if weights is None else weights.get(w, 1.0))
                             for w, wk in weekly_by_week.items())
           for p in roster}
    ...
        scored.append((horizon_total(trial, roster_slots, weekly_by_week, weights) - base, dropped))
```

In `waiver_targets`, add `weights: dict[int, float] | None = None` as the last parameter, change the floor, and pass it through:

```python
    floor = close_call_points * sqrt(effective_weeks(weekly_by_week, weights))
    ...
        gain, drop, weeks_started = roster_upgrade(
            roster, candidate, roster_slots, weekly_by_week, weights=weights)
```

Leave `weeks_started` counting raw weeks — it is a count of starts, not a value, and weighting it would make "starts 9 of 14" unreadable.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS, all 454+ tests. Every new parameter defaults to `None`, so untouched call sites behave identically. **If any existing test changes value, stop** — that means a default is not neutral and the fix is the default, not the test.

- [ ] **Step 5: Add the mutations**

```python
    ("horizon_total ignores the weight vector",
     "* (1.0 if weights is None else weights.get(w, 1.0))",
     "* 1.0"),
    ("a week absent from the weights is dropped instead of counted fully",
     "    return sum(weights.get(w, 1.0) for w in weekly_by_week)",
     "    return sum(weights.get(w, 0.0) for w in weekly_by_week)"),
    ("the waiver floor uses the raw week count instead of the effective one",
     "floor = close_call_points * sqrt(effective_weeks(weekly_by_week, weights))",
     "floor = close_call_points * sqrt(len(weekly_by_week))"),
```

- [ ] **Step 6: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "feat(season): horizon_total takes week weights; the floor scales with them

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 4: Extract `best_drop` from `roster_upgrade`

A 2-for-1 leaves the counterparty at 16 players, which is illegal, so they must cut one. That cut is the same computation `roster_upgrade` already performs. **Extract it rather than write a second one** — two rules for "which player does a team cut" is the `FLEX_ELIGIBLE` mistake, and here the two would disagree about what a trade costs.

**Files:**
- Modify: `ffhelper/season.py`
- Test: `tests/test_season.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `horizon_total(..., weights)` (Task 3).
- Produces: `season.best_drop(roster, roster_slots, weekly_by_week, weights=None, drop_tie_points=0.5) -> tuple[float, Player]` returning `(horizon total after the cut, the player cut)`.

- [ ] **Step 1: Write the failing test**

```python
def test_best_drop_takes_the_lowest_scorer_among_tied_cuts():
    """Ties are real -- in the real week-1 run five drops tied EXACTLY -- and
    naming an arbitrary member of a tie is fabrication: a name presented as
    computed when it was positional. Among cuts within drop_tie_points of the
    best, take the one with the fewest points of his own, then the id."""
    # Two bench players who never start: cutting either costs the lineup
    # nothing, so the totals tie exactly and only their own points separate them.
    roster = [mk("qb", "QB"), mk("rb1", "RB"), mk("rb2", "RB"),
              mk("bench_hi", "RB"), mk("bench_lo", "RB")]
    slots = {"QB": 1, "RB": 2}
    wbw = {1: {"qb": 20.0, "rb1": 15.0, "rb2": 14.0,
               "bench_hi": 9.0, "bench_lo": 1.0}}
    total, dropped = season.best_drop(roster, slots, wbw)
    assert dropped.sleeper_id == "bench_lo"
    assert total == pytest.approx(20.0 + 15.0 + 14.0)


def test_best_drop_will_cut_a_starter_when_that_is_genuinely_best():
    """The rule is not 'cut a bench player' -- it is 'maximise what remains'.
    A roster whose only cut is a starter must still return one."""
    roster = [mk("qb", "QB"), mk("qb2", "QB")]
    slots = {"QB": 1}
    wbw = {1: {"qb": 20.0, "qb2": 3.0}}
    total, dropped = season.best_drop(roster, slots, wbw)
    assert dropped.sleeper_id == "qb2"
    assert total == pytest.approx(20.0)
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_season.py -k best_drop -v
```

Expected: FAIL — `has no attribute 'best_drop'`.

- [ ] **Step 3: Implement, and rewrite `roster_upgrade` to use it**

Add above `roster_upgrade`:

```python
def best_drop(
    roster: list[Player], roster_slots: dict[str, int],
    weekly_by_week: dict[int, dict[str, float]],
    weights: dict[int, float] | None = None, drop_tie_points: float = 0.5,
) -> tuple[float, Player]:
    """(horizon total after the best single cut, the player cut).

    Used two ways: by `roster_upgrade`, where the roster is already full and an
    add IS an add-and-drop; and by the trade search, where a 2-for-1 leaves the
    counterparty at 16 players and the league forces a cut. ONE rule, because
    two would eventually disagree about what a trade costs.

    Ties are real and must not be broken by list order -- in the real week-1
    run five drops tied EXACTLY. Among cuts within `drop_tie_points` of the
    best, take the one with the fewest points of his own; the id is the final
    tie-break so the answer is deterministic across runs.
    """
    scored = [(horizon_total([*roster[:i], *roster[i + 1:]], roster_slots,
                             weekly_by_week, weights), p)
              for i, p in enumerate(roster)]
    own = {p.sleeper_id: sum(wk.get(p.sleeper_id, 0.0)
                             * (1.0 if weights is None else weights.get(w, 1.0))
                             for w, wk in weekly_by_week.items())
           for p in roster}
    best = max(t for t, _ in scored)
    tied = [(own[p.sleeper_id], t, p) for t, p in scored if t >= best - drop_tie_points]
    _, total, dropped = min(tied, key=lambda t: (t[0], t[2].sleeper_id))
    return total, dropped
```

Then replace `roster_upgrade`'s body down to the `drop` assignment with a call to it, keeping its docstring and the `weeks_started` block exactly as they are:

```python
    base = horizon_total(roster, roster_slots, weekly_by_week, weights)
    total, drop = best_drop([*roster, candidate], roster_slots, weekly_by_week,
                            weights, drop_tie_points)
    gain = total - base
```

**Task 3's weighted `own` dict moves into `best_drop` and is deleted from `roster_upgrade`** — that is this refactor, not a regression. `roster_upgrade` keeps only `base`, the `best_drop` call, and its existing `weeks_started` block.

**This is equivalent, and check that claim rather than trusting it:** `roster_upgrade` scored `roster - dropped + candidate` for each `dropped`; `best_drop([*roster, candidate])` scores the same set, because cutting `dropped` from `roster + candidate` leaves exactly that. The tie rule is unchanged — gain and total differ by the constant `base`, so ordering and the tie window are identical.

- [ ] **Step 4: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. **`roster_upgrade`'s existing tests are the proof of equivalence — every one of them must pass untouched. If any needs editing, the refactor is wrong.**

- [ ] **Step 5: Add the mutation**

```python
    ("the drop tie-break ignores the player's own points",
     "_, total, dropped = min(tied, key=lambda t: (t[0], t[2].sleeper_id))",
     "_, total, dropped = min(tied, key=lambda t: t[2].sleeper_id)"),
```

- [ ] **Step 6: Commit**

```bash
git add ffhelper/season.py tests/test_season.py scripts/mutate.py
git commit -m "refactor(season): extract best_drop -- one rule for which player a team cuts

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 5: `trade.py` — `Proposal` and the 1-for-1 search

**Files:**
- Create: `ffhelper/trade.py`
- Test: `tests/test_trade.py` (create)
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `season.horizon_total`, `season.best_drop` (Tasks 3-4); `data.Player`.
- Produces: `trade.Proposal(opponent, give, get, gain_me, gain_them, their_drop)`; `trade.trade_options(mine, theirs, opponent, roster_slots, weekly_by_week, floor, weights=None, pin=None) -> list[Proposal]`, sorted by `(-gain_me, give ids, get ids)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trade.py`:

```python
"""ffhelper.trade is PURE -- these tests never touch the network."""
import pytest

from ffhelper.data import Player
from ffhelper import trade


def mk(pid: str, pos: str) -> Player:
    return Player(pid, f"P{pid}", pos, "SEA", proj_pts=0.0)


SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}


def _swap_case():
    """A roster pair with a REAL surplus, not a contrived one.

    I start two RBs and two WRs. I hold three good WRs (one always benched) and
    only two RBs. They hold three good RBs and two WRs. Each of us is wasting a
    starter on the bench, which is the lineup-constraint surplus that makes a
    trade mutually beneficial -- the mechanism, reproduced small.
    """
    mine = [mk("qb", "QB"), mk("rb1", "RB"), mk("rb2", "RB"),
            mk("wr1", "WR"), mk("wr2", "WR"), mk("wr3", "WR"), mk("te", "TE")]
    theirs = [mk("tqb", "QB"), mk("trb1", "RB"), mk("trb2", "RB"), mk("trb3", "RB"),
              mk("twr1", "WR"), mk("twr2", "WR"), mk("tte", "TE")]
    week = {"qb": 20.0, "rb1": 12.0, "rb2": 6.0,
            "wr1": 18.0, "wr2": 17.0, "wr3": 16.0, "te": 8.0,
            "tqb": 19.0, "trb1": 15.0, "trb2": 14.0, "trb3": 13.0,
            "twr1": 11.0, "twr2": 5.0, "tte": 7.0}
    return mine, theirs, {1: week, 2: dict(week)}


def test_a_mutually_beneficial_one_for_one_is_found():
    """My benched WR3 (16.0) is worth more to them than their benched RB3
    (13.0) is to me -- but each of us upgrades a STARTING slot, which is why
    both gain. Numbers computed by hand before implementing."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, opponent=7, roster_slots=SLOTS,
                              weekly_by_week=wbw, floor=1.0)
    assert out, "the surplus case must produce at least one proposal"
    best = out[0]
    assert {p.sleeper_id for p in best.give} == {"wr3"}
    assert {p.sleeper_id for p in best.get} == {"trb3"}
    assert best.gain_me > 1.0 and best.gain_them > 1.0
    assert best.their_drop is None      # roster-neutral, nobody is cut
    assert best.opponent == 7


def test_a_proposal_that_helps_only_me_is_refused():
    """The board is an argument you send to another human. A swap the
    counterparty loses on is not a proposal, it is a fantasy."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, opponent=7, roster_slots=SLOTS,
                              weekly_by_week=wbw, floor=1.0)
    assert all(p.gain_them > 1.0 for p in out)


def test_the_floor_applies_to_BOTH_sides():
    """Measured on the real league: requiring only 'positive for them' is the
    difference between 11 rows of noise and 1 real row. A gain smaller than the
    error on the number that produced it cannot be defended."""
    mine, theirs, wbw = _swap_case()
    loose = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.0)
    strict = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=100.0)
    assert loose and not strict


def test_results_are_deterministic_across_runs():
    """A board that renames a package when nothing changed is one nobody can
    trust -- the same rule roster_upgrade's tie-break already follows."""
    mine, theirs, wbw = _swap_case()
    a = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    b = trade.trade_options(list(reversed(mine)), list(reversed(theirs)), 7,
                            SLOTS, wbw, floor=0.5)
    assert [( [p.sleeper_id for p in x.give], [p.sleeper_id for p in x.get]) for x in a] \
        == [( [p.sleeper_id for p in x.give], [p.sleeper_id for p in x.get]) for x in b]
```

**Before implementing, compute `_swap_case`'s numbers by hand and confirm the expected give/get.** The 4c plan's tie fixture was wrong and its own "run the numbers first" instruction is what caught it. If the hand arithmetic disagrees with the assertion, fix the fixture — never loosen the assertion.

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_trade.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ffhelper.trade'`.

- [ ] **Step 3: Create the module**

```python
"""Two-sided trade search. PURE -- no I/O, no network, no module-level state.

A trade is `roster_upgrade` run twice: what it does to my starting lineup, and
what it does to theirs, over the same weighted horizon. There is no new ranking
engine here and if this module ever seems to need one, the design is wrong.

Mutually beneficial trades exist because lineup constraints create surplus on
both rosters -- a fourth running back you cannot start is worth more to someone
starting two -- not because anybody is being fleeced.
"""
from dataclasses import dataclass
from itertools import combinations

from .data import Player
from .season import best_drop, horizon_total


@dataclass(frozen=True)
class Proposal:
    """One offer, and what each side would have to do to accept it."""
    opponent: int                     # roster_id
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    gain_me: float
    gain_them: float
    # Set only when the shape leaves the counterparty over the roster limit and
    # the league forces a cut. None means roster-neutral. It is part of the
    # OFFER -- they will notice it before you do -- so it is never hidden.
    their_drop: Player | None = None


def _without(roster: list[Player], players) -> list[Player]:
    gone = {p.sleeper_id for p in players}
    return [p for p in roster if p.sleeper_id not in gone]


def _ids(players) -> tuple[str, ...]:
    return tuple(sorted(p.sleeper_id for p in players))


def trade_options(
    mine: list[Player], theirs: list[Player], opponent: int,
    roster_slots: dict[str, int], weekly_by_week: dict[int, dict[str, float]],
    floor: float, weights: dict[int, float] | None = None,
    pin: Player | None = None,
) -> list[Proposal]:
    """Every swap with THIS opponent where both lineups gain more than `floor`.

    One opponent per call: it keeps this module single-subject and testable
    without a network, and leaves the league-wide loop in the caller where the
    league context already lives.

    BOTH sides must clear the floor, not merely be positive. The output is an
    argument you send to another human, and a gain smaller than the error on
    the number that produced it cannot be defended. Measured on the real league
    2026-09-02: that single choice is the difference between 11 rows of noise
    and 1 real row.
    """
    def ros(roster: list[Player]) -> float:
        return horizon_total(roster, roster_slots, weekly_by_week, weights)

    base_me, base_them = ros(mine), ros(theirs)
    out: list[Proposal] = []

    def consider(give: list[Player], get: list[Player]) -> None:
        if pin is not None and not _pin_matches(pin, give, get, mine):
            return
        gain_me = ros([*_without(mine, give), *get]) - base_me
        if gain_me <= floor:
            return
        after = [*_without(theirs, get), *give]
        drop = None
        if len(after) > len(theirs):
            # 16 players is not a legal roster, so the league forces a cut and
            # the cut is part of what the trade costs them. Same rule
            # `roster_upgrade` uses, imported rather than restated.
            total_them, drop = best_drop(after, roster_slots, weekly_by_week, weights)
        else:
            total_them = ros(after)
        gain_them = total_them - base_them
        if gain_them <= floor:
            return
        out.append(Proposal(opponent, tuple(give), tuple(get),
                            gain_me, gain_them, drop))

    for a in mine:
        for b in theirs:
            consider([a], [b])

    # Deterministic: a board that renames a package when nothing changed is one
    # nobody can trust.
    out.sort(key=lambda p: (-p.gain_me, _ids(p.give), _ids(p.get)))
    return out


def _pin_matches(pin: Player, give, get, mine: list[Player]) -> bool:
    """Task 7 fills this in. Until then every proposal passes."""
    return True
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_trade.py -v
```

Expected: PASS.

- [ ] **Step 5: Add the mutations**

Add an `"ffhelper/trade.py"` key to `MUTATIONS` in `scripts/mutate.py`. **Check first that no such key already exists** — a duplicate dict key silently discards a whole block, which this tool has already shipped once:

```python
    "ffhelper/trade.py": [
        ("the floor is checked on my side only, so their side can lose",
         "        if gain_them <= floor:\n            return",
         "        if gain_them <= -1e9:\n            return"),
        ("results are ordered by list position instead of deterministically",
         "    out.sort(key=lambda p: (-p.gain_me, _ids(p.give), _ids(p.get)))",
         "    pass"),
    ],
```

- [ ] **Step 6: Commit**

```bash
git add ffhelper/trade.py tests/test_trade.py scripts/mutate.py
git commit -m "feat(trade): Proposal and the 1-for-1 search, both sides over the floor

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 6: 2-for-1, with the forced cut

**Files:**
- Modify: `ffhelper/trade.py`
- Test: `tests/test_trade.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `trade_options`, `Proposal.their_drop` (Task 5).
- Produces: no new names. `trade_options` now also emits 2-for-1 proposals.

- [ ] **Step 1: Write the failing tests**

```python
def test_two_for_one_names_the_cut_the_counterparty_must_make():
    """They receive two and send one, so they land at 16 players -- illegal.
    The league forces a cut, that cut is part of what the trade costs them, and
    a proposal that hides it is quoting them a price they have not been told."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    two_for_one = [p for p in out if len(p.give) == 2 and len(p.get) == 1]
    assert two_for_one, "the 2-for-1 shape must be searched"
    assert all(p.their_drop is not None for p in two_for_one)
    assert all(p.their_drop.sleeper_id not in {g.sleeper_id for g in p.get}
               for p in two_for_one), "they cannot cut the player they just sent"


def test_my_fourteen_man_roster_is_not_refilled_from_the_wire():
    """A 2-for-1 leaves me at 14, which is LEGAL, so nothing is invented. The
    first probe added a free agent here and inflated every gain by whatever the
    wire happened to be worth -- conflating a trade with a waiver add, which
    `waivers` already answers separately."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    for p in out:
        if len(p.give) == 2 and len(p.get) == 1:
            kept = [x for x in mine if x.sleeper_id not in {g.sleeper_id for g in p.give}]
            expected = season.horizon_total([*kept, *p.get], SLOTS, wbw) \
                - season.horizon_total(mine, SLOTS, wbw)
            assert p.gain_me == pytest.approx(expected)
```

Add `from ffhelper import season` to the test module's imports.

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_trade.py -k two_for_one -v
```

Expected: FAIL — `AssertionError: the 2-for-1 shape must be searched`.

- [ ] **Step 3: Implement**

In `trade_options`, after the 1-for-1 loop:

```python
    for pair in combinations(mine, 2):
        for b in theirs:
            consider(list(pair), [b])
```

`consider` already handles the forced cut — that branch was written in Task 5 and this is the first shape that reaches it.

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_trade.py -v
```

Expected: PASS.

- [ ] **Step 5: Add the mutation**

```python
        ("the counterparty keeps 16 players, so their forced cut is free",
         "            total_them, drop = best_drop(after, roster_slots, weekly_by_week, weights)",
         "            total_them, drop = ros(after), None"),
```

- [ ] **Step 6: Commit**

```bash
git add ffhelper/trade.py tests/test_trade.py scripts/mutate.py
git commit -m "feat(trade): 2-for-1, with the cut the league forces on them

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 7: 2-for-2, and the pinned player

2-for-2 is where the surplus actually lives — measured, 49 proposals clear both floors across three opponents where 1-for-1 clears none. It is also roster-neutral, so it needs no cut.

**Files:**
- Modify: `ffhelper/trade.py`
- Test: `tests/test_trade.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: `trade_options`, `_pin_matches` (Task 5).
- Produces: `_pin_matches` implemented; `trade_options(..., pin=<Player>)` restricts to proposals containing `pin` on the correct side.

- [ ] **Step 1: Write the failing tests**

```python
def test_two_for_two_is_searched_and_is_roster_neutral():
    """The shape that carries the surplus. Measured on the real league: 1-for-1
    clears the floor zero times, 2-for-2 clears it 49 times across three
    opponents, because only a multi-player swap can change how many bodies each
    side carries at a position."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    two_two = [p for p in out if len(p.give) == 2 and len(p.get) == 2]
    assert two_two
    assert all(p.their_drop is None for p in two_two), "nobody is cut, both stay at 7"


def test_pinning_a_player_of_mine_keeps_only_offers_that_send_him():
    """'What is the best return for X?' -- so every row must send X."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in mine if p.sleeper_id == "wr3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5, pin=pin)
    assert out
    assert all("wr3" in {g.sleeper_id for g in p.give} for p in out)


def test_pinning_a_player_of_theirs_keeps_only_offers_that_acquire_him():
    """'What would it take to get Y?' -- so every row must receive Y. The side
    is chosen by roster MEMBERSHIP, not by an argument the caller passes: two
    sources of truth for one fact disagree eventually."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in theirs if p.sleeper_id == "trb3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5, pin=pin)
    assert out
    assert all("trb3" in {g.sleeper_id for g in p.get} for p in out)


def test_pinning_still_requires_both_sides_to_clear_the_floor():
    """Pinning narrows the search; it does not lower the bar."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in mine if p.sleeper_id == "wr3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=100.0, pin=pin)
    assert out == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_trade.py -k "two_two or pinning" -v
```

Expected: FAIL — no 2-for-2 rows, and the pin tests fail because `_pin_matches` returns `True` for everything.

- [ ] **Step 3: Implement**

Add the third shape after the 2-for-1 loop in `trade_options`:

```python
    for pair in combinations(mine, 2):
        for other in combinations(theirs, 2):
            consider(list(pair), list(other))
```

Replace `_pin_matches`:

```python
def _pin_matches(pin: Player, give, get, mine: list[Player]) -> bool:
    """Keep only proposals involving `pin`, on the side his roster implies.

    The side is decided by MEMBERSHIP, never by a flag the caller passes: a
    player of mine can only be given, one of theirs can only be got, and two
    sources of truth for one fact disagree eventually.
    """
    if any(p.sleeper_id == pin.sleeper_id for p in mine):
        return any(p.sleeper_id == pin.sleeper_id for p in give)
    return any(p.sleeper_id == pin.sleeper_id for p in get)
```

**No prefilter is added anywhere.** Pruning incoming players who cannot crack my lineup is sound for 1-for-1 and unsound here — giving away two players opens a slot the pruned player then fills. Measured: it silently dropped 22 of 49 real trades. If a future task proposes one, that measurement is the answer.

- [ ] **Step 4: Run to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_trade.py -v
```

Expected: PASS.

- [ ] **Step 5: Add the mutations**

```python
        ("the pin is matched against the wrong side of the offer",
         "        return any(p.sleeper_id == pin.sleeper_id for p in give)",
         "        return any(p.sleeper_id == pin.sleeper_id for p in get)"),
        ("2-for-2 is not searched, so the shape carrying the surplus is missed",
         "        for other in combinations(theirs, 2):\n            consider(list(pair), list(other))",
         "        for other in combinations(theirs, 2):\n            pass"),
```

- [ ] **Step 6: Commit**

```bash
git add ffhelper/trade.py tests/test_trade.py scripts/mutate.py
git commit -m "feat(trade): 2-for-2 and the pinned-player search

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 8: The `trades` command

**Files:**
- Modify: `ffhelper/cli.py` — add `render_trades` beside `render_waivers` (line ~1236), `_trades` beside `_waivers` (line ~1521), and the `main` argparse block (line ~1596)
- Test: `tests/test_cli.py`
- Modify: `scripts/mutate.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `cli.render_trades(best, week, last_week, league_name, owner, names, notes, weeks_scored, pinned) -> str`; `cli._trades(league, tunables, week=None, player=None) -> int`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, in a new `# --- Phase 5: the trade screen ---` section at the end of the file.

**Reuse the existing 4c helpers rather than inventing a stubbing style:** `_stub_waiver_inputs(monkeypatch)` (stubs `load_players`, `load_league_rosters`, `load_weekly_projections`, `load_nfl_state`, `resolve_settings`), `_sleeper_league()`, and the `Player` construction shown in `_target` near line 3118. Read `test_waivers_refuses_on_yahoo_because_there_is_no_pool` (line 3233) and `test_waivers_never_offers_a_player_another_team_owns` (line 3244) and follow them exactly.

`_stub_waiver_inputs` currently stubs settings **without** the playoff fields Task 1 added. Extend it so its `LeagueSettings` carries `playoff_week_start=15, playoff_teams=6, playoff_round_type=0, trade_deadline=11` — the existing 4c tests must still pass afterwards, and if any changes value, say so in the report rather than editing the assertion.

Write `mk_player(pid, pos)` as a local helper in the new section returning `Player(sleeper_id=pid, name=f"P{pid}", position=pos, team="X")`.

```python
def test_trades_refuses_yahoo_and_says_why(capsys, monkeypatch):
    """Not a fallback and not a bug: the search needs EVERY roster to know what
    the other eleven teams hold, and Yahoo serves none."""
    lg = League(name="yahoo-main", platform="yahoo", league_id="1")
    assert cli._trades(lg, Tunables()) == 1
    out = capsys.readouterr().out
    assert "sleeper" in out.lower() and "yahoo" in out.lower()


def test_trades_refuses_after_the_trade_deadline(capsys, monkeypatch):
    """trade_deadline is 11 in the real league. Printing proposals you are not
    allowed to make is worse than printing none -- and it exits 0, because a
    passed deadline is a legal state, not an error."""
    import ffhelper.cli as cli

    _stub_waiver_inputs(monkeypatch)
    rc = cli._trades(_sleeper_league(), Tunables(), week=13)
    out = capsys.readouterr().out
    assert rc == 0
    assert "deadline" in out.lower() and "11" in out


def test_trades_prints_an_empty_board_as_a_stated_result(capsys, monkeypatch):
    """Measured on the real league in week 1: one opponent qualifies, and on a
    tighter floor none do. A blank screen reads as a failed fetch, so silence
    must be a sentence."""
    import ffhelper.cli as cli

    _stub_waiver_inputs(monkeypatch)
    # close_call_points high enough that nothing in the fixture can clear it.
    rc = cli._trades(_sleeper_league(), replace(Tunables(), close_call_points=1e6),
                     week=1)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no trade" in out.lower()


def test_render_trades_names_both_packages_and_both_gains():
    """Pure render, no network. Every row is an argument you send to a human,
    so it must carry what each side gets and what each side gains."""
    p = trade.Proposal(opponent=7, give=(mk_player("a", "WR"),),
                       get=(mk_player("b", "RB"),),
                       gain_me=34.3, gain_them=13.7, their_drop=None)
    out = cli.render_trades([p], week=1, last_week=17, league_name="L",
                            owner="me", names={7: "leaguemate"}, notes=[],
                            weeks_scored=17, pinned=None)
    assert "leaguemate" in out and "34.3" in out and "13.7" in out
    assert "Pa" in out and "Pb" in out


def test_render_trades_names_the_forced_cut():
    """It is part of the offer and they will notice it before you do."""
    p = trade.Proposal(opponent=7, give=(mk_player("a", "WR"), mk_player("c", "WR")),
                       get=(mk_player("b", "RB"),),
                       gain_me=20.0, gain_them=5.0, their_drop=mk_player("d", "TE"))
    out = cli.render_trades([p], 1, 17, "L", "me", {7: "leaguemate"}, [], 17, None)
    assert "Pd" in out
```

Fill the `...` stubs from the neighbouring `_waivers` tests. **Do not add a fixture that reaches the network** — `tests/conftest.py` blocks it autouse and suite-wide, and a test that starts fetching keeps PASSING while only the clock changes.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cli.py -k trades -v
```

Expected: FAIL — `module 'ffhelper.cli' has no attribute '_trades'`.

- [ ] **Step 3: Implement `render_trades`**

Pure, beside `render_waivers`. Target output:

```
TRADES -- sleeper-main (jaydenpg) -- week 1, 17 weeks scored
  best offer per opponent; both sides must gain more than 12.4 pts

  leaguemate       you + 34.3   them + 13.7   [2-for-2]
                   give Khalil Shakir (WR) + Christian Watson (WR)
                   get  George Pickens (WR) + Los Angeles Chargers (DEF)

  it cannot tell you whether they will accept -- this league has never
  made a trade, so there is no history to rank managers by.
  preseason projections barely move week to week, so a September board is
  close to a restatement of season-long consensus.
```

The shape label is derived, not stored: `f"{len(give)}-for-{len(get)}"`. When `pinned` is set, the header names the player and the question instead ("best return for X" / "cost to acquire Y").

- [ ] **Step 4: Implement `_trades`**

Mirror `_waivers` exactly, in this order — every step but the search is already written and must be reused, not re-derived:

1. `if league.platform != "sleeper": print(...); return 1`
2. `settings = resolve_settings(league)`
3. `week, season_str, notes, _ = _resolve_week(week)`; `if week is None: ... return 1`
4. **Trade deadline:** `deadline = settings.trade_deadline` (added in Task 1). If `deadline is not None and week > deadline`, print that the deadline passed in week `deadline` and `return 0` — a passed deadline is a legal state, not an error. When it is `None`, say the deadline is unknown and carry on.
5. `last_week, cal_note = season_mod.last_scoring_week(settings)`; append `cal_note` to `notes` when it is not None.
6. `players = load_players()`; `roster, owner, notes_r, rosters, rid = _resolve_my_roster(...)`
7. Fetch `weekly_by_week` for `range(week, last_week + 1)` — **`last_week`, not `LAST_REGULAR_WEEK`** — with the identical per-week try/except and `failed` note that `_waivers` uses.
8. `weights = season_mod.week_weights(settings, weekly_by_week, tunables.playoff_weight)`
9. `floor = tunables.close_call_points * sqrt(season_mod.effective_weeks(weekly_by_week, weights))`
10. Resolve `pin` when `--player` was given, via `find_players(players, player)`: zero matches → say so and `return 1`; more than one → print all of them and `return 1` (**never guess — Bijan and Brian Robinson are both ATL RBs**); one → use it.
11. Loop the opponents, calling `trade.trade_options` per opponent, keeping `max(..., key=lambda p: p.gain_me)` per opponent for the board, or every row for the pinned mode (sorted by `gain_me`, or by `gain_them` when the pinned player is theirs).
12. Print a progress line to stderr per opponent — the sweep takes minutes and must not look hung.
13. `print(render_trades(...))`; `return 0`

Guard **every** fetch, including `load_league_users`, which is the exact sibling a previous fix wave missed on the happy path.

Mark the runtime with a `ponytail:` comment naming the ceiling:

```python
    # ponytail: the full sweep is ~330s (11 opponents x three shapes) because
    # 2-for-1 searches the counterparty's forced cut. Accepted: a weekly
    # one-shot command may be slow, and the alternative is pruning, which was
    # measured dropping 22 of 49 real trades. If this ever needs to be fast,
    # memoise horizon_total on a frozenset of player ids -- do NOT prefilter.
```

- [ ] **Step 5: Wire up `main`**

```python
    ap.add_argument("command", choices=["run", "preflight", "lineup", "waivers", "trades"])
    ap.add_argument("--player", default=None,
                    help="pin the search to one player: the best return for him "
                         "if he is yours, or what it would cost to acquire him")
    ...
    if args.command == "trades":
        return _trades(league, tunables, args.week, args.player)
```

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Add the mutations**

```python
    ("the trade deadline is ignored, so it offers trades you cannot make",
     "if deadline is not None and week > deadline:",
     "if deadline is not None and week > 999:"),
    ("the horizon runs to the NFL's last week instead of the league's",
     "for w in range(week, last_week + 1):",
     "for w in range(week, season_mod.LAST_REGULAR_WEEK + 1):"),
    ("an ambiguous --player silently takes the first match",
     "        if len(matches) > 1:",
     "        if len(matches) > 99:"),
```

Anchor each on enough surrounding text to match exactly once — `mutate.py` refuses an ambiguous target.

- [ ] **Step 8: Commit**

```bash
git add ffhelper/cli.py ffhelper/data.py tests/test_cli.py scripts/mutate.py
git commit -m "feat(cli): the trades subcommand, deadline-aware and Sleeper-only

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

### Task 9: Acceptance against the real league, and the docs

**No new code unless this task finds a defect.** Everything here is the project's standing rule that a green suite is not evidence — nine defects were found by running the tool and none by the suite.

**Files:**
- Modify: `CLAUDE.md`, `TODO.md`, `README.md` (only if it became wrong)

- [ ] **Step 1: Run the command for real**

```bash
.venv/bin/python -m ffhelper.cli trades --league sleeper-main
.venv/bin/python -m ffhelper.cli trades --league sleeper-main --player "smith-njigba"
.venv/bin/python -m ffhelper.cli trades --league yahoo-main          # must refuse, exit 1
```

Record the wall clock. Expect ~5 minutes for the board. **The output will not match the spec's sample**, which was measured with flat weights over 18 weeks — the shipped defaults end the horizon at 17 and down-weight the playoff weeks. Record what it actually prints, and confirm the difference is explained by those two changes and nothing else.

- [ ] **Step 2: Re-run the commands this phase changed**

```bash
.venv/bin/python -m ffhelper.cli waivers --league sleeper-main
.venv/bin/python -m ffhelper.cli lineup --league sleeper-main
.venv/bin/python -m ffhelper.cli lineup --league yahoo-main
.venv/bin/python -m ffhelper.cli preflight --league sleeper-main
```

`waivers` now runs to week 17 with weighted weeks, so **its numbers move and that is expected**. Confirm the empty board is still empty and the horizon it names is 17, not 18. `lineup` is a single week and must be unchanged.

- [ ] **Step 3: Mutation run — foreground, alone, on a green suite**

```bash
.venv/bin/python -m pytest -q                    # MUST be green first
git status --porcelain > /tmp/before.txt
.venv/bin/python scripts/mutate.py
git status --porcelain > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt              # MUST be empty
```

No subagent may run `mutate.py` concurrently. A survivor is evidence about the TEST — fix the test, never weaken the mutation. If a survivor exists because no test can reach the code, that is the finding: give the code a seam.

- [ ] **Step 4: Update the docs**

`CLAUDE.md`: add a session-log entry and add to Decisions — the acceptance prior is dead on a measurement (zero trades ever, no prior season); the horizon is read from the payload and `LAST_REGULAR_WEEK` was wrong for this league; the default week weights point opposite to the literature and why; the prefilter that dropped 22 of 49 real trades; and that the industry's single-number trade-value approach is barred by non-negotiable #2.

`TODO.md`: mark Phase 5 built; record the two deferred slices with what each needs — **leverage weighting** (playoff-odds simulation over the remaining schedule; data confirmed available: 11 distinct pairings across weeks 1-14, rosters carry `wins`/`losses`/`fpts`; live window weeks 8-11) and **win-probability lineups** (needs the same per-team score variance; gate is `backtest_weekly.py` on 2024 and 2025).

`README.md`: **change it only if it became wrong.** The command list gained `trades`, which a stranger cloning the repo would hit — that qualifies. Generate any sample by running the code, never by hand.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md TODO.md README.md
git commit -m "docs: phase 5 complete -- trades ships, and the calendar was wrong

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01BpiX5tkxWxNuEvxf2uXM4t"
```

---

## Self-review notes

Checked against the spec section by section.

**Covered:** the dead acceptance prior (Task 9 docs, and nothing is built in its place); the measurements (Task 5's fixture reproduces the surplus mechanism in miniature); both-sides floor (Task 5); roster legality and the forced cut (Tasks 4, 6); no wire re-fill (Task 6); no prefilter (Task 7, with the measurement recorded in the source); the calendar and trade deadline (Tasks 1, 8); week weights and the knob (Tasks 2, 3); both output modes (Tasks 7, 8); degradation (Task 8 step 4); the industry comparison and the GA rejection (Task 9 docs).

**Deliberately not tasks:** the leverage model and win-probability lineups are out of scope in the spec and are recorded in `TODO.md` by Task 9 instead.

**One risk flagged for the executor:** Task 4 is a refactor of shipped code whose proof is that `roster_upgrade`'s existing tests pass untouched. If any of them needs editing, stop and report — the equivalence argument is wrong, and the failure would otherwise be silent in the one function that decides what a trade costs.
