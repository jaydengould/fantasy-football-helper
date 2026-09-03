# Season mode on the web — one site, two modes

Written 2026-09-03, after Phase 5 merged. This is the first spec whose subject is
a *surface* rather than a model: nothing here changes what the tool believes, only
where it can be read from.

**Authority:** `CLAUDE.md` holds the standing decisions and non-negotiables. Where
this spec and that file disagree, that file wins and this one is wrong. The Phase 3
spec's "Hosting, later" section (`2026-08-26-phase-3-dash-ui-design.md`) is the
direct predecessor; this spec resolves it.

**Scope note.** An earlier draft of this document grew to cover scheduled jobs,
push notifications, cache-TTL fixes and always-on hosting, because a question
about notifications was answered by expanding the spec rather than by opening a
phase. That work is not lost — it is in "Deferred, with the research intact" at
the end, which is the more valuable half of this document. **This phase builds a
website and nothing else. Nothing in it runs unattended.**

## What this builds

One Dash application with a homepage that routes to draft mode and to the three
season commands, reachable from a phone.

| Route | What it shows |
| --- | --- |
| `/` | League picker, nav, status strip, headlines, trending |
| `/draft` | The existing Phase 3 board, unchanged, marked local-only |
| `/lineup` | `ffhelper lineup` as a web page |
| `/waivers` | `ffhelper waivers` as a web page |
| `/trades` | `ffhelper trades` as a web page |

**It is launched from the terminal**, `python -m ffhelper.app`, exactly as the
draft board is today, and it binds to localhost. **No hosting, no Tailscale, no
`0.0.0.0` in this phase** — those are a later decision, and the evaluation
recorded under "Hosting" is reference material for making it, not work to be
done here.

## What this is for — recorded, because it bounds everything

Asked and answered 2026-09-03. The user wants:

1. **Phone access in-season.** Check lineup/waivers/trades without a terminal.
2. **One surface instead of five commands.**

And explicitly does **not** want:

3. **Sharing with leaguemates.** No public URL, no other readers.
4. **Anything running unattended on a project he may forget about.**

**Item 3's absence is the single most load-bearing fact in this document.** No
authentication is required, and with it goes login, session handling, a hardened
config surface, and any question about leaking the tool's edge. The Phase 3 spec
listed authentication first among "what hosting would newly require"; that
requirement is void, and it was the expensive one.

**Item 4 is why there are no scheduled jobs here**, and the reasoning is worth
keeping: a `launchd` plist writes its output nowhere unless configured to, so a
moved venv, a renamed repo or a changed endpoint makes it fail every week in
silence. That converts a known gap into a false belief that weeks are being
recorded — the same species as the recurring mistake `CLAUDE.md` records, *a
verification tool reporting success while checking something else*. The site
nudges instead; see Homepage.

## Architecture

### `ffhelper/pipeline.py` — new

The impure orchestration layer between the loaders and the renderers. Today
`_lineup`, `_waivers` and `_trades` in `cli.py` each fuse four jobs: fetch,
compute, format as text, and print. Only the first two are shared with the web.

```
build_lineup(league, tunables, week, fetcher=None)                -> LineupView
build_waivers(league, tunables, week, limit, fetcher=None)         -> WaiverView
build_trades(league, tunables, week, player, limit, fetcher=None)  -> TradeView
```

Each view is a frozen dataclass carrying everything **both** renderers need —
the computed state (`StartSit`, `list[WaiverTarget]`, trade proposals), plus
resolved week and season, owner, notes, matchup context and practice line. No
printing. No database write. No dash import.

`fetcher` stays an explicit argument, matching the existing loader convention,
so every builder is testable without the network.

**Why a new module rather than leaving these in `cli.py`:** `cli.py` is 1844
lines (measured 2026-09-03) and the extraction removes several hundred of them.
`season.py` and `value.py` are pure by rule and cannot hold fetching, while
`data.py` holds loaders and knows nothing about leagues. The orchestration has
no existing home.

**Why one shared builder rather than a web-side copy:** the rule `CLAUDE.md`
already states for `lineup_value()` / `optimal_lineup()`, applied one level up.
Two code paths that can disagree about what this week's advice is would be the
same defect that produced that rule.

### `ffhelper/news.py` — new

RSS only, parsed with stdlib `xml.etree.ElementTree`. One entry point returning
`Headline(title, url, source, published)`. Caching reuses `data.py`'s existing
TTL file cache, which needs a text-returning sibling to `fetch_json`.

Candidate feeds — ESPN NFL, ProFootballTalk, the Bears' official site. **The
exact URLs are unverified and must be checked at build time**, not trusted from
memory.

X/Twitter was evaluated and rejected: read access to the API begins at roughly
$100/mo, the free tier cannot read timelines at all, Nitter is dead, and
scraping needs an authenticated session and violates the terms. Bluesky's public
API is free and was offered as the only real substitute; the user declined it.

### `ffhelper/app.py` — restructured

Multi-page via `dcc.Location` and a single callback switching layout on
pathname. League rides in the query string (`?league=sleeper-main`) so every
page is linkable and the picker rewrites the URL rather than holding state.

**Hand-rolled, roughly twenty lines — not `dash.use_pages`.** `use_pages`
imposes a `pages/` directory convention and app-level configuration to solve a
problem five routes do not have.

The app is constructed at import time, with league selection coming from the URL
rather than `argv`.

**This is not hosting work done early.** League-in-the-URL is what multi-page
routing requires anyway, and once league selection is out of `argv` the `app =
Dash(...)` line has no reason to sit inside `main()` — it is the same number of
lines either way. That it also happens to be the retrofit the Phase 3 spec
identified for hosting is a consequence, not a motivation. The comment at the
foot of `app.py` refusing to fake that retrofit with a dead `server` global
should be replaced, not deleted — it records a real correction.

### Changed, minimally

`data.py` gains a text-returning sibling to `fetch_json` for RSS. That is all.

### Unchanged

`season.py`, `value.py`, `store.py`, `board.py`, `trade.py`, `feeds.py`,
`config.py`. If any of them needs to change, the design is wrong and this spec
should be revisited before the change is made.

## Two decisions taken in the design

### The web surface never writes the snapshot

`_lineup` writes to `season.db` on every run, and `store.write_snapshot` uses
`INSERT OR REPLACE` on `(league, season, week, player_id)`. The documented
semantics are "the LAST look taken before kickoff", which is correct for a human
running a command deliberately.

On the web it is a defect. Every page refresh rewrites the week's rows with a new
`taken_at`, and **a page opened after kickoff overwrites the pre-kickoff record
with a post-kickoff one** — destroying the only thing the table exists to hold.
No warning, no error, and the row still looks healthy.

So `build_lineup` does not touch the database. `cli.py`'s `_lineup` keeps its
`_record_snapshot` call unchanged, and the snapshot remains something a human
causes by running the command.

### Season pages use `html.Table`, not `DataTable`

They are read-only ranked lists with no cell interaction, `DataTable` fights
responsive layout on a phone, and hand-rolling here proves the pattern before
the board depends on it — de-risking the Phase 3.7 swap (TODO item 6) rather
than pre-empting it. The board keeps `DataTable` until 3.7 decides.

## Homepage

- **League picker and nav.** Four links.
- **Status strip.** Current NFL week; whether this week's snapshot is recorded;
  age of `.roster/yahoo-main.txt`. These are the two operational risks in TODO
  items 2 and 3, surfaced on the screen the user always lands on, at the cost of
  one small fetch, one SQLite read and one `stat`.
- **Headlines panel.** RSS, newest first, each item a link out.
- **Trending panel.** `load_trending()`, already in `data.py`. Its docstring is
  emphatic that these are national counts and must never predict whether the
  user's own claim wins; **the panel must repeat that on screen.**

### The snapshot line is a nudge, and it replaces the scheduled job

This is the design's answer to item 4. The user opens the site each week to set
a lineup; that is exactly the moment a snapshot is due. The strip says so, the
user runs one command, and **nothing runs unattended.** It is pull, not push: it
cannot fail silently, and if the project is abandoned it stops along with it.

**The line is absent, never wrong, when the database cannot be read.** If
`season.db` is missing or unreadable the line is omitted entirely rather than
reporting "not recorded" — that would be a fabricated value where a measured one
is expected, which non-negotiable #7 bars. Two lines of code. It never fires
while the app and the database sit on the same machine, which is the whole of
this phase; it matters the moment either moves.

### Panels are separated from anything advisory

A news box beside lineup advice implies the advice **considered** the news. It
did not: `start_sit` sees projections, practice status and injury designation,
and nothing else. The panels are visually separate and labelled as headlines,
and an unreachable feed renders "feed unavailable" rather than a silently empty
box — non-negotiables #3 and #7.

## Hosting — reference only, decided in a later phase

Nothing in this section is built here. It is recorded so the decision, whenever
it is taken, does not have to be researched again.

### The finding

**The application work is identical on every host.** Extracting the pipeline,
routing the pages, and rendering HTML are the same diff whether the process runs
on `localhost:8050`, on a Tailscale address, or on Fly.io. Hosting is a final
step measured in minutes, not a foundation. It is therefore **decided last**.

**Dropping the scheduled jobs changed this section's conclusion.** An earlier
draft ruled out Render's free tier on three grounds — no persistent disk,
spin-down killing an in-process scheduler, and cron being a paid product. **Two
of the three are now void:** there is no scheduler and nothing on the host
writes, so there is no data for an ephemeral disk to destroy. A free host that
cannot see `season.db` reports a missing snapshot line, not a lost database.

### The candidates

**Prices are from memory and MUST be verified before any money is spent.**

**The Mac + Tailscale — $0, and the recommendation.** Tailscale on the Mac and
the phone; bind Dash to `0.0.0.0`; reach it at the tailnet address from
anywhere. Tailscale *is* the authentication, which is only acceptable because of
fact 3. `season.db`, `.cache/` (164 MB, measured) and `.roster/yahoo-main.txt`
all stay where they are — no secret migration, no volume, no redeploy story.

**With scheduling dropped, the Mac sleeping no longer matters.** A website
tolerates being intermittent: if the Mac is asleep, the page loads later. That
was never true of a scheduled job, which is what made sleep a problem — see
Deferred.

**Render free / Fly free-tier — now genuinely viable** for this scope, with one
real cost: spin-down means roughly 50 seconds of cold start on the first phone
visit after idle, on top of the fetches. An annoyance, not a risk.

**Paid, ~$3–7/mo (Fly, or Render Starter) — buys away the cold start** and
nothing else this phase needs. Not recommended yet.

**GitHub Pages remains impossible**: Pages serves static files, Dash is a Flask
app needing a live Python process.

### The one thing that argues against ever moving off the Mac

`.roster/yahoo-main.txt` is 447 bytes, gitignored, and hand-maintained after
every Yahoo add/drop (TODO item 3). Locally that is a text editor. Hosted it is
a redeploy or a web textarea, and a textarea is a config-editing surface with
all the hazards the Phase 3 spec deferred.

## Measured cost of a page load

Timed 2026-09-03 against the live APIs, read-only:

| | Cold (TTL expired) | Warm |
| --- | --- | --- |
| Wall time | 4.57s | 0.49s |
| CPU (user+sys) | — | 0.24s |
| Peak RSS | 128 MB | 123 MB |

Nearly all the cold time is network wait, not CPU. `sleeper_players.json` is
14.6 MB and cached for 24 hours; weekly projections for one hour; rosters for
five minutes. **A page load is cheap and the existing cache is sufficient — no
caching layer is needed.**

## Degradation

- **`yahoo-main` has no API.** `/waivers` and `/trades` render the same explicit
  message `cli.py` prints today — that the pool needs every team's roster and
  Yahoo serves none — never an empty table. `/lineup` works, from the roster file.
- **`/draft` states on the page** that it is local-only and single-process, and
  that the CLI must not run against the same league concurrently. Hosting the
  draft board is out of scope; see below.
- **A failed fetch degrades to a named absence**, never a fabricated number.
  Non-negotiable #7 applies to every panel on every page.
- **`load_nfl_injuries` currently returns 404** — `injuries_2026.csv` does not
  yet exist, expected for 2026-09-03 with the season starting Sept 9. The loader
  degrades correctly rather than fabricating. Re-verify after the season starts.

## Staging

Each step is independently shippable.

1. **Extract `pipeline.py`;** `cli.py` renders from it. **The existing text
   renderer tests must pass unchanged** — that is the evidence the extraction
   altered no behaviour, and it is the only evidence that counts.
2. **Multi-page shell,** homepage with status strip, season pages as
   `html.Pre(<existing text renderer>)`. Usable from a phone at the end of this
   step, with horizontal scrolling.
3. **Upgrade `/lineup`, `/waivers`, `/trades` to real HTML,** one page per
   commit. The text renderers remain as the CLI's output and as a fallback.
4. **Headlines and trending panels.**

**Hosting is not a step.** The app runs from the terminal on localhost when
step 4 lands, which is the whole deliverable. Deciding where else it might run
happens later, with the app in hand and a season's use behind it.

## Testing

- **Builders take an explicit `fetcher`** and are tested offline against
  fixtures, like every loader. No network, no mocking — the existing rule.
- **The extraction's proof is the unchanged renderer tests**, not new ones. A
  new test that passes against both the old and new code proves nothing about
  the refactor.
- **`conftest.py`'s network and database guards apply unchanged.** No test may
  reach either; the web tests are no exception.
- **The status strip's snapshot logic must be tested against `:memory:`**,
  covering three cases: a recorded week, a week with no rows, and **an
  unreadable or missing database, which must omit the line rather than report
  "not recorded"**. The third is the one a suite naturally skips and the one the
  non-negotiable is about.
- **Mutations in `scripts/mutate.py`** for the RSS parser and the status strip's
  snapshot predicate — both are branch logic whose failure is silent and
  plausible-looking.

## Out of scope

- **Hosting the draft board.** Both drafts finished 2026-09-01; the next is
  roughly eleven months out. The Phase 3 spec concluded draft night stays local
  deliberately: the journal file is the database and the CLI-takeover fallback
  works only because both processes read the same local disk. Hosted, that
  fallback is gone. The homepage links to `/draft`; it runs where it always ran.
- **In-browser config editing.** Deferred by the Phase 3 spec for reasons that
  have not changed: `config.toml` is load-bearing for correctness, `tomllib` is
  read-only, and a silently-failed edit produces a healthy-looking wrong board.
- **Authentication.** Not required, per fact 3.
- **Bluesky or any social feed.** Offered, declined.
- **The Phase 3.7 `DataTable` swap.** This spec produces evidence for it and
  does not perform it.

## Deferred, with the research intact

Everything below was designed and partly verified on 2026-09-03 and then cut, on
the user's decision, to keep this phase a website. **None of it should be
re-derived.** It is a phase of its own, best opened once the season has run long
enough to say how much the snapshots and alerts are actually missed.

### Alerting — the design that was cut

**Want:** be told on the phone when a starter is ruled out or a lineup is left
unset, without having to remember to look.

**Verified 2026-09-03 against the live Sleeper payload**, not assumed: the
roster object returned by `load_league_rosters()` carries `starters` (10 ids)
alongside `players` (15). Nothing in the codebase reads it —
`roster_player_ids()` takes `players`. **The tool has never known what was
actually submitted, and the data to know it has been arriving all along.**

**Design principle: silent unless actionable.** An alert that arrives on every
run regardless of content stops being read, and then the week it matters it is
dismissed with the rest.

**Triggers.** (1) A submitted starter is OUT, DOUBTFUL, or not practising. (2)
The submitted lineup differs from `optimal_lineup()` by more than
`close_call_points` — an existing tunable already deciding whether a gap is
worth mentioning, so no invented number (non-negotiable #8). A raw diff would
fire every week, since optimal-per-projection never equals a human's choices.

**Deduplication is mandatory, not a refinement.** Repeated runs against one
unresolved problem produce identical notifications, which is the same fatigue by
another route. Hash the rendered alert text, store the digest under `.cache/`,
skip when unchanged. Roughly five lines. It also removes the need for any
mid-week-noise knob: a lineup wrong on Wednesday alerts once and then stays
quiet.

**Transport: Discord webhook.** `requests.post(url, json={"content": text})`,
URL in `.env`, never committed. Chosen over ntfy.sh because ntfy topics are
public in both directions and keep no history; over email because a Discord push
lands on a phone through an app the user already runs. The target channel must
be set to *All Messages* or Discord batches it and a late-breaking scratch
arrives too late to act on. Keep the transport as one `notify(text)` function so
swapping it is a function body.

**Sleeper only.** Yahoo has no API and therefore no `starters`.

### The TTL defect — measured, unfixed, and blocking any alerting

**Neither `load_players` nor `load_nfl_injuries` passes `ttl_seconds`, so both
take `fetch_json`'s 86,400s default.** Verified live: `sleeper_players.json` on
disk was from the previous evening and was served from cache on two consecutive
runs.

**Any frequent sweep would therefore re-read yesterday's injury picture and
alert on none of it, while every test passed and every run looked healthy.** The
alert path must pass a short `ttl_seconds`; the default stays for every other
caller, since the draft board has no reason to refetch a 14.6 MB file hourly.

**Unresolved and blocking:** which source actually carries a Sunday-morning
ruling. nflverse's file is the official *weekly* injury report — practice
participation and Out/Doubtful/Questionable, published Wednesday to Friday.
Gameday inactives at 90 minutes are a different feed. If that reading is right,
Sleeper's `injury_status` via `load_players` is the one that moves, making that
loader's TTL the most load-bearing number in the alerting design. **Not
verified. Settle before building trigger 1.**

### Timing — what the schedule has to respect

Inactives are released **90 minutes before each kickoff**, and Sleeper locks
players individually at their own game time. So the 1pm and 4pm slates have
separate windows, and one run cannot serve both.

**Do not enumerate slates.** A five-entry list (TNF / 1pm / 4pm / SNF / MNF)
silently omits the 09:30 London games, the Saturday slates in weeks 16–18, and
the holiday games — and kickoff times appear in no payload this project fetches,
so the list could never be validated. An hourly sweep across a wide daily window
covers every kickoff the league can invent, is one config entry instead of five,
and is affordable **only** because of deduplication.

**Cost is not the constraint.** Measured: ~0.24s CPU per run, ~5–7 CPU-seconds
per day for thirteen runs, ~123 MB peak RSS that exits with the process, and
20–30 MB/day of network. Negligible.

### The snapshot write must be separated from any sweep

An earlier draft had every scheduled run write the snapshot. **That is the same
defect this spec rejects for the web surface**: with `INSERT OR REPLACE`, a
later run overwrites an earlier row with post-kickoff state for players whose
games have started — silently, and the row still reads as healthy. Any future
design must have exactly one writing run per week, before the first kickoff.

**Residual, stated and not quantified:** a Thursday-night or Monday-night
starter recorded at a Sunday-morning write is recorded after his game or before
it. `proj_pts` most likely survives, since weekly projections are static;
`status` most likely does not. Unobserved, and **must not be written up as a
finding until a week has been watched.** The clean fix is `taken_at` in the
primary key so nothing overwrites — a change to what a row means, in the one
stateful module in the package.

### Where a scheduled job could run — four candidates, none chosen

**`launchd` on the Mac.** Ten lines of XML. **Rejected for this phase on the
user's explicit objection to unattended jobs on a project he may forget**, and
the objection is technically sound: launchd writes output nowhere unless
configured to, so a moved venv or changed endpoint fails weekly in silence.

**And it would not work reliably anyway.** The machine is a MacBook Pro 14-inch
(`Mac14,9`, 2023) with `sleep 1`, `standby 1`, `powernap 1` on AC. **A sleeping
Mac does not run launchd calendar jobs on schedule** — they are deferred and
*coalesced*, firing once on wake rather than once per missed slot. Power Nap
covers Apple's own services, not user LaunchAgents; being on AC does not prevent
sleep; a closed lid sleeps regardless outside clamshell mode. `caffeinate -s`
during game windows or `pmset repeat wakeorpoweron` (one repeating event only,
so one guaranteed wake per day) are the mitigations. *Documented behaviour, not
measured here.*

**GitHub Actions, committing `season.db` to the repo.** Free for public repos,
needs no secrets since Sleeper is unauthenticated, and runs whether or not the
Mac is awake. Three problems, all real:

1. **The repo is public.** Snapshot rows carry `proj_pts` — Rotowire's weekly
   projection with league scoring applied. Derived rather than raw, so arguably
   outside the letter of non-negotiable #5, but squarely inside its spirit. The
   rows are also the user's own roster and start/sit decisions, published where
   leaguemates can read them, in a repo that has already had one redaction
   incident. **A private repo or private gist holding only `season.db` removes
   this problem entirely**, at the cost of a second repo.
2. **Scheduled Actions run late.** Delays of 10–30 minutes are normal under
   load and runs are sometimes skipped. Fatal for a pre-kickoff snapshot;
   tolerable for a weekly record.
3. **Actions auto-disables scheduled workflows after 60 days of repo
   inactivity** — which relocates the forgotten-project failure rather than
   solving it. In its favour, GitHub emails on workflow failure, so it is less
   silent than launchd.

**An always-on host (~$3–5/mo).** Removes the sleep question entirely. This —
not the website — is what the money would actually buy, and it is the strongest
argument for paying that exists in this project.

**Doing nothing scheduled at all.** What this phase chooses. The status strip
nudges; the user runs the command.

## Open questions

1. **Should `taken_at` join the snapshot primary key?** Not needed by anything
   in this phase. Becomes load-bearing the moment more than one run per week
   writes.
2. **Which RSS feeds, exactly.** URLs to be verified at build time.
3. **Whether the status strip should surface `preflight`'s other checks.** The
   strip carries two; `preflight` carries more. Left until the strip has been
   lived with.
4. **Which injury source carries a Sunday-morning ruling.** See the TTL section.
   Blocks alerting, blocks nothing here.
