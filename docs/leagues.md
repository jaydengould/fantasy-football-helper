# Leagues — settings, scoring, and what differs between them

Referenced from `CLAUDE.md`. Read this when computing a board, a lineup,
or anything that depends on scoring, roster shape, or replacement level.

| League | Platform | Draft | Format |
| --- | --- | --- | --- |
| Bros with no hoes (`1395959490938966016`) | Sleeper | **DRAFTED 2026-09-01** | snake, 12 team, 15 rd, seat 5 |
| Yahoo league (id in `.env`) | Yahoo | **DRAFTED 2026-09-01** | snake, **10 team**, seat 2 |

**Both drafts are done.** Sleeper completed 180 picks and the roster reads from
the API; the Yahoo roster has no API and must be hand-entered for season mode.
The 2026 season starts **Sept 9** (`state/nfl`), so week 1 lineups are the first
live use of the tool after the drafts.

Sleeper scoring: full PPR, 0.1/yd rush+rec, 0.04/yd pass, **6-pt passing TDs**
(not Sleeper's default 4). Roster `QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF` + 5 bench.

**Yahoo scoring (user-supplied 2026-08-24, complete). Must be hand-entered — no
API access.** Roster `QB/WR/WR/RB/TE/FLEX/FLEX/K/DEF` + 5 bench —
**ONE RB slot, not two; confirmed by the user 2026-09-01 against Yahoo's own UI**
after they noticed it while drafting. Two FLEX, everything else unchanged. So it
is NOT the same shape as the Sleeper league (which starts two RBs), and it is 10
teams rather than 12. `config.toml` was corrected by the user the same day.
Mapped to Sleeper stat keys for `score_stats`:

```
pass_cmp 0.25  pass_yd 0.04  pass_td 6   pass_int -2   pass_2pt 2
rush_yd  0.1   rush_td 6     rush_2pt 2
rec 0.5        rec_yd 0.1    rec_td 6    rec_2pt 2
fum_lost -2    fum_rec_td 6

K:   fgm_0_19 3  fgm_20_29 3  fgm_30_39 3  fgm_40_49 4  fgm_50_59 5
     fgm_60p 5   xpm 1        (no FG-miss penalty — differs from Sleeper's -1)

DEF: sack 1  int 2  fum_rec 2  def_td 6  def_st_td 6  st_td 6  safe 2  blk_kick 2
     pts_allow_0 10  _1_6 7  _7_13 4  _14_20 1  _21_27 0  _28_34 -1  _35p -4
```

Unmapped: "extra point returned 2" has no clean Sleeper key (negligible).

**Replacement levels:** Sleeper QB12/TE12/RB36/WR36; Yahoo **QB10/TE10/RB20/WR30**.
Generated 2026-09-01 by running `replacement_ranks` against the corrected
settings, not by hand.

**CORRECTED 2026-09-01 — Yahoo was recorded as RB30 and it is RB20.** The cause
was the roster shape above: this file said two RB slots, Yahoo starts one. Two
consequences, one harmless and one not:

- **The board was NEVER wrong.** `config.toml` is what the engine reads, and it
  carried `RB = 2` until the user corrected it — so the pre-draft Yahoo board WAS
  computed against two RB slots and was wrong in exactly the way this file
  described. The draft is over, so that cost is spent and unrecoverable.
- **RB20 makes RBs worth LESS in Yahoo, not more** — the opposite of what the
  strategy table below concluded. One RB starter plus a shallower 10-team pool
  means replacement-level RB is a much better player than at RB36.

**The two leagues differ in ways that change the board, not just the numbers:**
- **10 teams vs 12** — shallower replacement (QB10, ~RB25, ~WR30), so elite players
  gain value relative to the pool.
- **Half PPR (0.5) vs full PPR (1.0)** — shifts RB/WR balance.
- **0.25 per completion** — unique to Yahoo. Allen's ~313 projected completions are
  worth **+78 points**, comparable to 13 passing TDs. Systematically favours
  high-volume pocket passers over rushing QBs. The two leagues want different QBs.
- **INT −2 vs −1.**

Known blind spot: return yards/TDs are scored in the Yahoo league but Sleeper's
projections carry no return stats, so those categories contribute ~0.

**Validated 2026-08-24 against real projections. THE RB ROW IS NOW INVALID** —
it was computed with `RB = 2` in config, and Yahoo starts one RB. The QB rows are
unaffected: QB replacement is QB10 either way, and the completion bonus that
drives them has nothing to do with the RB count.

| | Sleeper | Yahoo |
| --- | --- | --- |
| QB1 off the board | pick 24 | **pick 18** |
| QB2–4 | 54, 56, 61 | **39, 40, 44** |
| QB2 identity | L. Jackson | **J. Burrow** |
| Top 13 | mixed | ~~9 of 13 are RBs~~ **INVALID** — computed against two RB slots (see above) |

Draft strategy consequences: **take QBs ~15 picks earlier in Yahoo**, and **prefer
volume passers over rushing QBs there** — the completion bonus rewards attempts,
not legs, so Burrow rises to QB2 while Jackson leaves the top four. Inverted from
Sleeper. The RB tilt comes from half PPR plus 10-team shallower replacement.

**Precision caveat added 2026-08-25 (`TODO.md` §15).** The arithmetic above is
correct and is not in question. But measured across 2021–2025, **no position
ranks its own top 12 better than ~+0.35 Spearman** — the gap between tiers is
real, the order *within* a tier is close to noise. So the POSITIONAL call (QB is
scarcer in Yahoo, move it up) is far better supported than the IDENTITY call
(Burrow specifically over Jackson specifically). Take the tier early if the board
says so; do not agonise over which name inside it.

