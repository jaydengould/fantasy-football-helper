# fantasy-football-helper

A live draft assistant that answers the question a printed cheat sheet cannot:
**what will not survive until my next pick?**

Most draft tools rank players by value. This one ranks by *cost of waiting*. If
three running backs of equal tier will still be available 19 picks from now and
only one tight end will be, the board says take the tight end — even though the
running backs score higher.

## Status

Draft mode is complete and has been exercised end to end against a full 180-pick
live draft, which is where most of its bugs came from. Season mode and a web UI
are planned but not built.

| Capability | State |
| --- | --- |
| Projections scored against your league's real rules | working |
| VBD, tiers, survival probability, VONA | working |
| Optimal-lineup marginal value | working |
| Live Sleeper draft feed | working |
| Manual pick entry (any platform, no feed needed) | working |
| Terminal board with auto-refresh | working |
| Hand-typed picks survive a crash or restart | working |
| Yahoo API feed | blocked on Yahoo developer approval |
| Web dashboard, season mode, trade finder | planned |

## Requirements

Python 3.12+. One runtime dependency does the work: `requests`. (`yfpy` is
declared for the Yahoo feed, which is blocked on developer approval and imports
nowhere yet.) Everything else is standard library — `tomllib` for config,
`statistics.NormalDist` for the survival math, `sqlite3` for season mode later.
Adding a dependency needs a reason a few lines of stdlib cannot cover.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Configuration

Everything lives in `config.toml`. Copy the example league blocks and edit.

### A league with a platform API (Sleeper)

Settings sync automatically — scoring, roster slots, team count, and draft id are
read from the platform.

```toml
[[league]]
name = "my-sleeper-league"
platform = "sleeper"
league_id = "1234567890"      # the number in your league URL
draft_slot = 3                 # your draft position, 1-indexed
```

`draft_slot` is deliberately manual. Draft order is often not final until the
draft starts, and a wrong slot silently corrupts every survival number — so the
tool never guesses it. Set it, then run `preflight` to confirm it took; a value
left commented out fails silently in exactly the way this warning describes.

Optionally, choose which ADP the survival model believes:

```toml
adp_source = "ffc"      # default. "sleeper" is the other option.
```

Survival calibration depends almost entirely on the accuracy of the ADP *mean*,
so this matters more than it looks. Use `"sleeper"` when your league drafts
inside the Sleeper app — the room is anchored on the number Sleeper shows them,
which most drafters have never compared against anything else. Use `"ffc"`
everywhere else. `scripts/calibrate.py` settles it with a measurement rather than
an argument (see [Scripts](#scripts)).

### A league without a platform API (Yahoo, ESPN, CBS, anywhere)

Enter the settings by hand. **This is a first-class path, not a workaround** —
Yahoo requires per-developer API approval that can be denied, ESPN has no official
API, and most people will use the tool this way.

```toml
[[league]]
name = "my-yahoo-league"
platform = "yahoo"
league_id = "123456"
draft_slot = 4

  [league.settings]
  num_teams = 10
  bench = 5
  roster_slots = { QB = 1, RB = 2, WR = 2, TE = 1, FLEX = 2, K = 1, DEF = 1 }

  [league.settings.scoring]
  pass_cmp = 0.25
  pass_yd  = 0.04
  pass_td  = 6
  pass_int = -2
  rush_yd  = 0.1
  rush_td  = 6
  rec      = 0.5
  rec_yd   = 0.1
  rec_td   = 6
  fum_lost = -2
```

Scoring keys follow Sleeper's stat naming. A platform API, where one exists, takes
precedence over this block — so a league that later gains API access starts
syncing with no config change.

### Tunables

```toml
[tunables]
tier_break_sigma = 1.0        # higher = fewer, coarser tiers
divergence_flag_slots = 10    # WITHIN-POSITION rank gap that earns a flag

[tunables.flex_share]         # how flex slots split across positions
RB = 0.5
WR = 0.5
TE = 0.0

[tunables.poll_seconds]       # floored at 1s to avoid API rate limiting
sleeper = 5
yahoo = 12
```

### Secrets

Only credentials belong in `.env` — league ids are not secret and live in
`config.toml`.

```
YAHOO_CONSUMER_KEY=...
YAHOO_CONSUMER_SECRET=...
```

`.env` is gitignored. Do not commit it.

## Usage

### Before the draft

```bash
.venv/bin/python -m ffhelper.cli preflight --league my-sleeper-league
```

Fetches every source, validates all joins, reports unmatched players, confirms the
feed is reachable, and warns if `draft_slot` is unset. **Run this the morning of
your draft**, not five minutes before.

### During the draft

```bash
.venv/bin/python -m ffhelper.cli run --league my-sleeper-league
```

The board refreshes automatically. If the feed drops, it keeps rendering the last
known state behind a `FEED STALE` banner rather than dying.

### Manual entry

For a league with no feed — or if a feed dies mid-draft — type into the running
board:

| Input | Effect |
| --- | --- |
| `gibbs` | mark Jahmyr Gibbs drafted by someone |
| `me nacua` | mark Puka Nacua drafted **by you** (counts toward your roster) |
| `-nacua` | take that mark back — he returns to the board |
| `2` | choose the 2nd option when a name is ambiguous |
| `u` | undo the last change, whatever it was |
| `nacua, me chase, gibbs` | several at once — one line instead of one round trip each |

Partial names work, accents and suffixes are handled (`pineiro` finds Eddy
Piñeiro, `harrison` finds Marvin Harrison Jr.). **Ambiguous names always prompt** —
typing `robinson` will not silently pick between Bijan and Brian.

`me ` matters more than it looks: a plain mark only clears a player off the
board, while `me ` also feeds your roster, which is what MARG is measured
against. In a league with no feed, skipping it means every marginal-value number
is computed against an empty roster.

`-` searches only what *you* marked by hand, so `-robinson` resolves outright if
only one Robinson was marked, and a feed-reported pick can never be un-drafted.
Recording a pick and then realising it was yours needs no undo — just claim it:
`nacua` followed by `me nacua`.

`u` restores the exact prior state, including whether a mark was claimed as
yours, and a no-op never consumes an undo.

### If it crashes, you lose nothing

Hand-typed marks are journalled to `.draft/<league>-<date>.jsonl` as they happen.
Restart and the board picks up where it left off:

```
restored 87 mark(s) from /…/.draft/my-yahoo-league-2026-09-01.jsonl
  -> 87 drafted, 9 yours. Delete that file to start fresh.
```

Undo history is rebuilt too, so `u` still works for picks typed before the crash.
The filename is dated so a mock never replays into a real draft. If the log can't
be written the draft carries on without it — persistence is insurance, never a
dependency.

### When the feed disagrees with you

If you claim a player the feed then reports from another seat, the claim is
dropped from your roster and says so:

```
CLAIM OVERRULED: the feed says Puka Nacua was taken from seat 4, not yours --
dropped from your roster. Clear the stale claim with '-<name>'.
```

He stays off the board — he really was drafted, just not by you.

## Reading the board

A real board, 12-team full PPR, on the clock at pick 45:

```
#   PLAYER                   POS     VONA     VBD    MARG TIER   SURV   DIV  FLAGS
1   Drake Maye               QB       8.0    31.3   378.8    1    23%    +0  bye11
2   D'Andre Swift            RB       6.5    60.1   208.0    1    61%    +3  bye10
3   Tyler Warren             TE       6.2    38.6   201.1    1    21%    +0  Questionable bye13
4   David Montgomery         RB       4.6    58.2   206.1    1    23%    -1  bye8
5   Garrett Wilson           WR       3.5    47.6   224.9    1    12%    +0  bye13
6   Sam LaPorta              TE       1.6    34.0   196.5    1    80%    +0  Questionable bye6
```

| Column | Meaning |
| --- | --- |
| **VONA** | What you lose by waiting. **The board sorts by this.** Negative means waiting is strictly better. |
| **VBD** | Points above a replacement-level player at that position |
| **MARG** | How much this player improves your *starting lineup* — a third RB is worth less than a first |
| **TIER** | Players in a tier are roughly interchangeable |
| **SURV** | Probability of still being available at your next pick |
| **DIV** | Projection rank minus market rank, **within position**. A flag, never blended into the score. `-` means the market never priced him — no opinion is not agreement. |

That board is the whole argument. **Swift has the highest VBD on screen (60.1)
and is not the pick.** He has a 61% chance of lasting to your next turn, so
waiting costs you 6.5 points. Maye is worth half as much by VBD but only 23%
likely to survive, so waiting costs 8.0 — and LaPorta, at 80% survival, costs
1.6, which is the board telling you that tight end can wait a round.

A value-ranked cheat sheet puts Swift first and is wrong. The question is never
"who is best available", it is "who will not be here next time".

`FLAGS` carries injury status, bye week, and — where the model and the market
disagree by more than `divergence_flag_slots` places within a position —
`MODEL+n` or `MARKET+n`. `MODEL+` means the projection likes him more than the
room does. It is a prompt to look, never an instruction, and it is deliberately
rare: about 6% of top-20 rows.

VONA is rounded to the displayed tenth before sorting and floored at zero, so the
board agrees with the numbers on screen and ties break on value. Without the
floor, every negative VONA is comparable only within its own position, and at
pick 1 — and on both sides of every snake turn — kickers sort above McCaffrey.

Two banners replace the ranking when ranking would mislead:

- **`STARTING LINEUP FULL`** — every starting slot is filled, so no available
  player improves your lineup and there is nothing honest left to rank on. The
  remaining order is bench value over league replacement, and the tool says
  plainly that it has no model of upside or handcuffs.
- **`MANUAL MODE`** / **`FEED STALE 23s`** — the board is running without a feed,
  or the feed stopped answering. It keeps rendering the last known state rather
  than dying, but it never pretends to be current.

`TIER` deserves more weight than its width suggests. Measured across 2021–2025,
no position's preseason top 12 was ordered better than about +0.35 rank
correlation with what actually happened. The gaps *between* tiers are real; the
order *within* one is close to noise.

## Data sources

- **Sleeper API** — player database, projections, ADP, live draft picks. Free, no
  auth. Projection data is provided by Rotowire via Sleeper; it is fetched at
  runtime and never redistributed with this repository.
- **FantasyFootballCalculator ADP** — per-player ADP standard deviation, which no
  other free source publishes and which the survival math depends on.
  *ADP data courtesy of [Fantasy Football Calculator](https://fantasyfootballcalculator.com).*
- **DynastyProcess player IDs** — cross-platform ID crosswalk. Required because
  Sleeper's own `yahoo_id` is unpopulated for every rookie and most second-year
  players.

**Deliberately single-source on projections.** ESPN was the obvious second
opinion and was tested rather than assumed: on 2025, Rotowire beat it 66.5 to
70.5 MAE overall and 75.3 to 93.2 at quarterback, and averaging the two never
beat Rotowire alone. Run `scripts/backtest.py` to reproduce that. The remaining
risk is real — every projection is poor in absolute terms — but the honest
upgrade is a confidence interval on the board, not another opinion.

## Design notes

**Player identity joins on integer IDs, never names.** Bijan Robinson and Brian
Robinson are both running backs on Atlanta; a name join silently merges them and
every downstream number becomes quietly wrong. FFC is the one source with no
cross-platform id, so it is confined to a final, non-load-bearing enrichment step
that reports unmatched and ambiguous names instead of guessing.

**Projection rank and market rank are never averaged.** A board that tracks
consensus produces consensus results. The disagreement is surfaced as a flag for
you to judge.

**Degrade, never fabricate.** Unknown draft slot, unreachable feed, ambiguous
name, missing settings, a claim the feed contradicts — each produces a visible,
labelled degradation rather than a plausible guess. This extends to analysis:
`scripts/backtest.py` refuses to score a projection source that cannot prove it
was frozen before the season it predicts.

**Replacement level is a property of the league, not of who is left.** Drawing it
from the draining pool makes the baseline collapse as the draft runs down — at
pick 164 of a test draft that gave a backup quarterback a VBD of +149 against a
true −32.5, and produced a confident case for drafting a third one.

**The tool advises; it never drafts.** There is no auto-pick and there will not
be one.

## Scripts

Four tools that answer questions the board cannot.

```bash
.venv/bin/python scripts/backtest.py [season ...]     # is source X actually better?
.venv/bin/python scripts/calibrate.py <draft_id> <slot>       # Sleeper draft
.venv/bin/python scripts/calibrate.py <log.jsonl> [more.jsonl ...]   # pooled
.venv/bin/python scripts/transcribe.py <league> [slot] [results.txt]
.venv/bin/python scripts/mutate.py
```

**`backtest.py`** scores a projection source against what actually happened.
Its real work is refusing to be fooled: both Sleeper and ESPN will serve a
"season projection" for a season already played, and some of those numbers were
revised *during* that season. A revised projection scores brilliantly and means
nothing. So a source must prove it was frozen before week 1 — a preseason
projection gives nearly everyone a full slate, because it cannot know who gets
hurt — and a source that fails is named and skipped, never scored.

**`calibrate.py`** replays a completed draft and asks, at each of your turns,
"will this player last to my next pick?", then buckets the answers by what the
model predicted. A well-calibrated model reads 10/30/50/70/90 down the actual
column. Flat means it has no discriminating power. This is how `adp_source` gets
settled by measurement. Given `.draft/*.jsonl` journals instead of a Sleeper
draft id it scores drafts entered by hand or transcribed, reconstructing pick
order from the order marks were made. **Pass several and they are pooled into
one table** — one draft is a hypothesis, not a finding. Your seat is read out of
each journal and then proven against the snake; a log whose claimed picks don't
land on a seat's snake positions is refused rather than scored, since a missing
pick shifts every number after it.

It also reports **room discipline** — the median rank, in ADP order, of the
player each pick took. A room drafting straight down the list reads 1–2, which
means the calibration below it is measuring that list against itself. Autodraft
and CPU drafters do exactly this, so the number decides whether to believe the
table.

**`transcribe.py`** turns a finished draft's results page into a journal
`calibrate.py` can score. Copy the results list, `pbpaste > .draft/results.txt`,
and run it — the seat comes from the league's `draft_slot`. This is how a draft
too fast to type into still yields a measurement.

It reads rows like `(4) manager - Cook III, James (Buf - RB)`: surname-first
names are put back in order (so suffix stripping lines them up with the pool),
defenses join on their **team code** because "Los Angeles" names two of them,
and rows are sorted by their reconstructed pick number rather than by where they
appear — a snake's even rounds run right-to-left in the board view. It refuses
to write if any row resolves to no player or two, or if the rows are not a
complete `1..N` run, since a missing row shifts every pick after it.

**`mutate.py`** breaks the engine on purpose, one line at a time, and checks the
suite notices. It is the only mechanical check that a test does anything, and it
has caught several tests that passed against deliberately broken code.

## Development

```bash
.venv/bin/pytest          # 232 tests, no network, runs in ~0.3s
```

`ffhelper/value.py` is pure — no I/O, no network, no module state — so the entire
ranking engine tests without a network.

Two conventions worth knowing before contributing:

- **A new test must be shown to fail before the fix.** `git stash push -- ffhelper
  && pytest -k <name>`. A test written after a fix and never seen red is not
  evidence that it works.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** It is one
  line, and it is the only thing that distinguishes a test from a decoration.

Neither is bureaucracy. Every serious defect this project has had was found by
running the code against real data while a full green suite looked on.

## License and attribution

Personal project. ADP data courtesy of
[Fantasy Football Calculator](https://fantasyfootballcalculator.com). Projections
via Sleeper (Rotowire). Player ID crosswalk from
[DynastyProcess](https://github.com/dynastyprocess/data).
