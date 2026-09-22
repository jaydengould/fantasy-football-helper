# fantasy-football-helper

A fantasy football assistant for the draft and the season. It scores every player
against your league's own rules and answers the questions a ranking list can't:

- **On draft night:** who won't last until your next pick?
- **In season:** which lineup, waiver claim, or trade actually improves your
  starting lineup by more than projection noise?

When nothing clears that bar it says so. An empty waiver board is an answer, not
a failure.

## Status

| Capability | State |
| --- | --- |
| Draft board, terminal and web, with live Sleeper feed or manual entry | working |
| Weekly start/sit (`lineup`) | working |
| Waivers (`waivers`) | working, Sleeper only |
| Trade finder and offer grader (`trades`, web `/trades`) | working, Sleeper only |
| Yahoo API | blocked on Yahoo developer approval; hand-entered settings work |

Waivers and trades need every team's roster, which only Sleeper's API serves.

## Install

Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[web,dev]"
```

`web` adds `dash` for the browser app. It is optional: the terminal board runs
without it.

## Configure

Settings live in `config.toml`. For a Sleeper league, scoring, roster slots, and
team count sync from the platform:

```toml
[[league]]
name = "my-sleeper-league"
platform = "sleeper"
league_id = "1234567890"      # the number in your league URL
draft_slot = 3                 # your draft position, 1-indexed
adp_source = "sleeper"
```

`draft_slot` is manual on purpose: a wrong slot silently corrupts every survival
number, so the tool never guesses it. For Yahoo, ESPN, or any league without an
API, enter the settings by hand. See [docs/usage.md](docs/usage.md#configuration)
for that, plus tunables and secrets.

## Use

```bash
.venv/bin/python -m ffhelper.cli preflight --league NAME   # check sources, joins, config
.venv/bin/python -m ffhelper.cli lineup    --league NAME   # optimal lineup this week
.venv/bin/python -m ffhelper.cli waivers   --league NAME   # add/drops worth making
.venv/bin/python -m ffhelper.cli trades    --league NAME   # trades that help both sides
.venv/bin/python -m ffhelper.cli run       --league NAME   # live draft board (terminal)
.venv/bin/python -m ffhelper.app           --league NAME   # web app at 127.0.0.1:8050
```

The web app has a home page plus `/lineup`, `/waivers`, `/trades`, and `/draft`.
The `lineup`, `waivers`, and `trades` commands take `--week N`; `trades` also
takes `--player "name"` to search around one player.

Real output, week 1:

```
bros-fantasy  (jaydenpg)   week 1

STARTERS
  QB    Josh Allen               QB  BUF   24.4
  RB    D'Andre Swift            RB  CHI   13.5
  RB    TreVeyon Henderson       RB  NE    10.0  [Questionable]
  ...
        projected total                   134.4

BENCH
        Kyler Murray             QB  MIN   20.1
        ...
matchup context : none -- no completed weeks yet (a rank off no games is not a rank)
practice report : unavailable (HTTPError) -- nflverse publishes injuries_2026.csv once week 1 has been played
snapshot        : 120 players recorded for week 1 (15 on your roster, 105 startable pool)
```

Each run also records a snapshot of the week's projections to a local
`season.db`, since the APIs never serve them again.
[docs/usage.md](docs/usage.md) covers draft-night mechanics (manual entry, crash
recovery), what each season command prints, and why.

## Reading the draft board

Most draft tools rank by value. This one ranks by the **cost of waiting**. A real
board, 12-team full PPR, on the clock at pick 45:

```
#   PLAYER                   POS     VONA     VBD    MARG TIER   SURV   DIV  FLAGS
1   Drake Maye               QB       7.3    31.3   378.8    2    27%    +0  bye11
2   Tyler Warren             TE       5.2    38.6   201.1    4    27%    +0  Questionable bye13
3   D'Andre Swift            RB       4.8    60.1   208.0    7    67%    +3  bye10
4   David Montgomery         RB       2.9    58.2   206.1    7    34%    -1  BYE8 CLASH
5   Garrett Wilson           WR       2.8    47.6   224.9    7    21%    +0  bye13
6   Joe Burrow               QB       0.7    24.6   372.1    2    45%    +0  bye6
```

| Column | Meaning |
| --- | --- |
| **VONA** | What you lose by waiting. **The board sorts by this.** |
| **VBD** | Points above a replacement-level player at that position |
| **MARG** | How much he improves your *starting lineup* |
| **TIER** | Roughly interchangeable players, fixed from the full preseason pool |
| **SURV** | Likelihood of lasting to your next pick. An ordering, not a calibrated probability: it reads about 25–35 points low |
| **DIV** | Projection rank minus market rank, within position. A flag, never blended into the score |

Swift has the highest VBD on screen and sits third: he is the likeliest to last,
so waiting on him costs little. Maye and Burrow are both tier-2 quarterbacks, but
Maye is far less likely to last, so he is the one to take now. Take the tier the
board points at; the name within it is your call. Across 2021–2025, no
position's preseason top 12 ranked better than about +0.35 correlation with the
final order, so the gaps between tiers are real and the order within one is
close to noise.

## Principles

- **Players join on integer IDs, never names.** Bijan and Brian Robinson are both
  Atlanta running backs.
- **Projection and market are never averaged.** A board that tracks consensus
  produces consensus results; disagreement is shown as a flag.
- **Degrade visibly, never fabricate.** A missing source, stale feed, or
  ambiguous name produces a labelled gap, not a plausible guess.
- **It advises; it never drafts.** No auto-pick.

Settled design decisions and the measurements behind them are in
[docs/decisions.md](docs/decisions.md). Tests, scripts, and contributor rules
are in [docs/development.md](docs/development.md).

## Data sources

- **Sleeper API**: players, projections (Rotowire, via Sleeper), ADP, rosters,
  live draft picks. Fetched at runtime and never redistributed with this repo.
- **Fantasy Football Calculator**: bye weeks, and an alternative ADP source.
- **DynastyProcess**: cross-platform player ID crosswalk.
- **nflverse**: the official weekly practice report.

## License

[MIT](LICENSE). Covers this code only, not the data it fetches. ADP data
courtesy of [Fantasy Football Calculator](https://fantasyfootballcalculator.com).
Player ID crosswalk from [DynastyProcess](https://github.com/dynastyprocess/data).
