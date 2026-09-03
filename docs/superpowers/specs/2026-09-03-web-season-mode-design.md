# Season mode on the web — one site, two modes

Written 2026-09-03, after Phase 5 merged. This is the first spec whose subject is
a *surface* rather than a model: nothing here changes what the tool believes, only
where it can be read from.

**Authority:** `CLAUDE.md` holds the standing decisions and non-negotiables. Where
this spec and that file disagree, that file wins and this one is wrong. The Phase 3
spec's "Hosting, later" section (`2026-08-26-phase-3-dash-ui-design.md`) is the
direct predecessor; this spec resolves it.

## What this builds

One Dash application with a homepage that routes to draft mode and to the three
season commands, reachable from a phone. Concretely:

| Route | What it shows |
| --- | --- |
| `/` | League picker, nav, status strip, headlines, trending |
| `/draft` | The existing Phase 3 board, unchanged, marked local-only |
| `/lineup` | `ffhelper lineup` as a web page |
| `/waivers` | `ffhelper waivers` as a web page |
| `/trades` | `ffhelper trades` as a web page |

## What hosting is for — recorded, because it bounds everything

Asked and answered 2026-09-03. The user wants:

1. **Phone access in-season.** Check lineup/waivers/trades without a terminal.
2. **A guaranteed weekly snapshot.** TODO item 2: nothing schedules it today.
3. **One surface instead of five commands.**
4. **To be told, on the phone, when the lineup needs attention** — a starter
   ruled out, or a lineup left unset — without having to remember to look.
   Added later the same day; see "Alerting".

And explicitly does **not** want:

5. **Sharing with leaguemates.** No public URL, no other readers.

Item 5's absence is the single most load-bearing fact in this document. **No
authentication is required**, and with it goes login, session handling, a hardened
config surface, and any question about leaking the tool's edge. The Phase 3 spec
listed authentication first among "what hosting would newly require"; that
requirement is now void, and it was the expensive one.

Item 4 is the one want that is **not** served by the website at all. A push
notification is delivered by the scheduled job, which is why alerting is
specified here alongside the snapshot rather than as a page.

## Item 2 does not need a website

The weekly snapshot is fixed by one `launchd` plist running `ffhelper lineup`.
It is macOS-native, needs no dependency, no server and no browser, and it closes
the only genuinely irrecoverable risk in the queue. **It ships first and
independently of everything else here.** See "Scheduling the snapshot" below.

With item 2 handled separately, the web build is buying items 1 and 3 — an
ergonomics want. That is a real want and worth building; it is not worth
restructuring the data layer for.

## Hosting — the evaluation, and why the decision is deferred

### The finding

**The application work is identical on every host.** Extracting the pipeline,
routing the pages, and rendering HTML are the same diff whether the process runs
on `localhost:8050`, on a Tailscale address, or on Fly.io. Hosting is a final
step measured in minutes, not a foundation.

Therefore the hosting choice is **made last, after the app exists**, when the
Mac's real availability is known. The user's own answer to "what machine is
this?" was *not sure, depends on the week* — a genuine uncertainty, and this
sequencing means it does not have to be resolved to start.

### The candidates

**Prices below are from memory and MUST be verified before any money is spent.**

**Render, free tier — not viable.** Three independent blockers, any one of which
is fatal: no persistent disk on free, so `season.db` is wiped on every redeploy
(silently — and the table exists precisely because its contents cannot be
recovered); free services spin down after ~15 minutes idle, so an in-process
scheduler dies and every phone visit pays a cold start on top of the API fetches;
and cron is a paid product.

**Render, paid — viable, ~$7/mo** for a Starter instance plus a small disk.

**Fly.io — viable and the better paid option, ~$3–5/mo.** Volumes are
first-class, and machines suspend and wake in about a second rather than
spinning down for the better part of a minute. Better suited to a
SQLite-backed app that is idle most of the week.

**The Mac + Tailscale — $0, and the recommended starting point.** Tailscale on
the Mac and the phone; bind Dash to `0.0.0.0`; reach it at the tailnet address
from anywhere. Tailscale *is* the authentication, which is only acceptable
because of fact 4 above. `season.db`, `.cache/` (164 MB, measured 2026-09-03)
and `.roster/yahoo-main.txt` all stay exactly where they are — no secret
migration, no volume, no redeploy story. `launchd` keeps the process up and
restarts it at boot.

Its one failure mode is the Mac being asleep or away, which is the same
condition that threatens the snapshot job, and which `pmset repeat wake`
partially answers.

**GitHub Pages remains impossible**, as the Phase 3 spec said: Pages serves
static files and Dash is a Flask app needing a live Python process.

### What a move to Fly would newly require

Recorded now so the cost is known, not discovered:

- Secrets from `.env` into Fly secrets. Small — Yahoo OAuth, still blocked.
- A volume for `season.db` (12 KB, measured) and the snapshot job running there.
- The `app.py` retrofit the Phase 3 spec describes: build the app at import
  time, league selection out of `argv`. **This spec does that anyway** (see
  Routing), so it is no longer a hosting cost.
- An edit path for `.roster/yahoo-main.txt` (447 bytes, hand-maintained after
  every Yahoo add/drop, per TODO item 3). Locally this is a text editor. Hosted
  it is a redeploy or a web textarea, and the textarea is a config-editing
  surface with all the hazards the Phase 3 spec deferred. **This is the
  strongest single argument for staying on the Mac.**
- `.cache/` may stay ephemeral. It is a cache; a cold host refetches.

## Architecture

### `ffhelper/pipeline.py` — new

The impure orchestration layer between the loaders and the renderers. Today
`_lineup`, `_waivers` and `_trades` in `cli.py` each fuse four jobs: fetch,
compute, format as text, and print. Only the first two are shared with the web.

```
build_lineup(league, tunables, week, fetcher=None)          -> LineupView
build_waivers(league, tunables, week, limit, fetcher=None)   -> WaiverView
build_trades(league, tunables, week, player, limit, fetcher=None) -> TradeView
```

Each view is a frozen dataclass carrying everything **both** renderers need —
the computed state (`StartSit`, `list[WaiverTarget]`, trade proposals), plus
resolved week and season, owner, notes, matchup context and practice line. No
printing. No database write. No dash import.

`LineupView` additionally carries the **submitted** lineup (see Alerting), so
all three consumers — text, HTML and the alert — read one computation.

`fetcher` stays an explicit argument, matching the existing loader convention,
so every builder is testable without the network.

**Why a new module rather than leaving these in `cli.py`:** `cli.py` is 1844
lines (measured 2026-09-03) and the extraction removes several hundred of them.
More importantly, `season.py` and `value.py` are pure by rule and cannot hold
fetching, while `data.py` holds loaders and knows nothing about leagues. The
orchestration has no existing home.

**Why one shared builder rather than a web-side copy:** this is the rule
`CLAUDE.md` already states for `lineup_value()` / `optimal_lineup()`, applied
one level up. Two code paths that can disagree about what this week's advice is
would be the same defect that produced that rule.

### `ffhelper/news.py` — new

RSS only, parsed with stdlib `xml.etree.ElementTree`. One entry point returning
a list of `Headline(title, url, source, published)`. Caching reuses `data.py`'s
existing TTL file cache, which needs a text-returning sibling to `fetch_json`.

Candidate feeds — ESPN NFL, ProFootballTalk, the Bears' official site. **The
exact URLs are unverified and must be checked at build time**, not trusted from
memory.

X/Twitter was evaluated and rejected: read access to the API begins at roughly
$100/mo, the free tier cannot read timelines at all, Nitter is dead, and
scraping needs an authenticated session and violates the terms. That price is
15–30× the hosting cost under discussion, for a decorative panel. Bluesky's
public API is free and was offered as the only real substitute; the user
declined it.

### `ffhelper/app.py` — restructured

Multi-page via `dcc.Location` and a single callback switching layout on
pathname. League rides in the query string (`?league=sleeper-main`) so every
page is linkable and the picker rewrites the URL rather than holding state.

**Hand-rolled, roughly twenty lines — not `dash.use_pages`.** `use_pages`
imposes a `pages/` directory convention and app-level configuration to solve a
problem five routes do not have.

The app is constructed at import time, with league selection coming from the URL
rather than `argv`. This is exactly the retrofit the Phase 3 spec identified and
correctly refused to fake with a dead `server` global. The comment at the foot
of `app.py` describing that refusal should be replaced, not deleted — it records
a real correction.

### `ffhelper/notify.py` — new

One function, `notify(text) -> bool`, POSTing to a Discord webhook URL read from
`.env`. `requests` is already a dependency; no bot, no token, no gateway, no
library. Kept as its own module and its own function precisely because the user
is choosing between transports without having lived with either — swapping
Discord for `smtplib` later is then one function body, not a hunt through the
scheduler.

A failed POST is logged and returns `False`. It never raises into the caller:
an unreachable webhook must not cost the snapshot write, which is the one part
of the run that cannot be redone.

### Changed, minimally

- **`season.py`** gains `roster_starter_ids()` beside the existing
  `roster_player_ids()`, and the pure predicate that decides whether a lineup
  difference is worth alerting about. Both are logic, both stay pure, both
  test without a database or a network.
- **`data.py`** gains a text-returning sibling to `fetch_json` for RSS.

### Unchanged

`value.py`, `store.py`, `board.py`, `trade.py`, `feeds.py`, `config.py`. If any
of them needs to change, the design is wrong and this spec should be revisited
before the change is made.

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

So: **the scheduled job owns the write; the web surface is read and compute
only.** `build_lineup` does not touch the database; `cli.py`'s `_lineup` keeps
its `_record_snapshot` call.

A pleasant consequence: apart from the status strip read below, the web app is
stateless.

### Season pages use `html.Table`, not `DataTable`

They are read-only ranked lists with no cell interaction, `DataTable` fights
responsive layout on a phone, and hand-rolling here proves the pattern before
the board depends on it — de-risking the Phase 3.7 swap (TODO item 6) rather
than pre-empting it. The board keeps `DataTable` until 3.7 decides.

## The `season.db` coupling, stated plainly

The homepage status strip answers "is this week's snapshot recorded?", which is a
**read** of `season.db` — the table's first reader ever (verified 2026-09-03:
`cli.py:1221` is the only caller of `store.connect`, and nothing reads).

That read ties the web app to wherever the database lives, which is wherever the
scheduled job runs. Practically: **the app and the snapshot job stay together.**
On the Mac today; both move together if the app ever moves to Fly.

The alternative is dropping that line from the strip, which is also the line that
makes the strip worth having. The coupling is accepted deliberately.

## Homepage

- **League picker and nav.** Four links.
- **Status strip.** Current NFL week; whether this week's snapshot is recorded;
  age of `.roster/yahoo-main.txt`. These are the two operational risks in TODO
  items 2 and 3, surfaced on the screen you always land on, at the cost of one
  small fetch, one DB read and one `stat`.
- **Headlines panel.** RSS, newest first, each item a link out.
- **Trending panel.** `load_trending()`, already in `data.py`. Its docstring is
  emphatic that these are national counts and must never predict whether your
  own claim wins; **the panel must repeat that on screen.**

**The panels are visually separate from anything advisory and are labelled as
headlines.** A news box beside lineup advice implies the advice considered the
news. It did not: `start_sit` sees projections, practice status and injury
designation, and nothing else. An unreachable feed renders "feed unavailable",
never a silently empty box — the same rule as non-negotiable #3 and #7.

## Scheduling the snapshot

`launchd` plists with `StartCalendarInterval`:

| Run | Time (ET) | Purpose |
| --- | --- | --- |
| Thursday | 19:00 | Redundancy |
| Sunday | 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, 12:45 | Alerting; last write is the record |

**Why the Sunday window rather than one run.** The original design set a single
run at 11:30. That is wrong for two reasons found during the alerting
discussion. First, **official inactives are released 90 minutes before
kickoff — 11:30 ET for the 1pm slate** — so a run at 11:30 races the release it
exists to catch. Second, a scratch announced at 12:15 is exactly the event the
user asked to be told about, and a single earlier run cannot see it.

Repeated runs are affordable **only because alerts are silent when clean** (see
Alerting). Without that property this window would be six notifications a
Sunday and the feature would be dead inside a month.

Repeated runs also make the snapshot *better*, not worse: `INSERT OR REPLACE`
means the last write before kickoff wins, and the documented semantics are
already "the LAST look taken before kickoff". The 12:45 run is a closer record
than 11:30 would have been.

**The Thursday run is redundancy, not Thursday fidelity.** This correction was
made during design, after the schedule was chosen. Because the primary key is
`(league, season, week, player_id)` and the write is `INSERT OR REPLACE`,
Sunday's run overwrites Thursday's rows entirely, including the TNF starter's
pre-game state. What Thursday actually buys is a record surviving a failed
Sunday run — Mac asleep, network down, API flaking — instead of nothing. That is
worth the second plist on its own terms.

Capturing genuine Thursday-evening state requires adding `taken_at` to the
primary key, which changes what a row means. It is an open question below, not a
silent change to the one stateful module in the package.

**Machine availability.** `launchd` runs a missed calendar job when the machine
wakes, but a wake after kickoff produces a post-hoc record with no value.
`pmset repeat wake` scheduled shortly before each run is the native mitigation.
It cannot help a machine that is off or elsewhere; that residual risk is the
same one that argues for a paid always-on host, and it is accepted for now.

## Alerting

**Verified 2026-09-03 against the live Sleeper payload**, not assumed: the
roster object returned by `load_league_rosters()` carries `starters` (10 ids)
alongside `players` (15). Nothing in the codebase reads it —
`roster_player_ids()` takes `players`. **The tool has never known what the user
actually submitted, and the data to know it has been arriving all along.**

### The design principle

**Silent unless actionable.** An alert that arrives on every run regardless of
content is one that stops being read, and then the week it matters it is
dismissed with the rest. That failure is the reason this feature is usually not
worth building, and avoiding it is the whole design.

### Triggers

An alert is sent when either holds for the user's own roster:

1. **A submitted starter is OUT, DOUBTFUL, or not practising.** Already carried
   on `Player` — `injury_status` plus the nflverse practice status wired in
   during 4a. No new source.
2. **The submitted lineup differs from `optimal_lineup()` by more than
   `close_call_points`.** This is "you forgot to set your lineup", stated in
   points.

**The threshold is not a new number.** `close_call_points` is an existing
tunable already doing exactly this job — deciding whether a gap is worth
mentioning — in `lineup`, `waivers` and `trades`. Non-negotiable #8 bars
inventing a discount or weight; reusing the knob that already answers this
question is the compliant move, and a raw diff would not be: optimal-per-
projection almost never equals a human's choices, so an ungated comparison
fires every week and rebuilds the fatigue problem through the back door.

### Deduplication — required, not a refinement

Seven Sunday runs against one unresolved problem is seven identical
notifications. That is the same alert fatigue arriving by a different route, and
it would have shipped unnoticed.

**Send only when the alert's content changes.** Hash the rendered alert text
(`hashlib`, stdlib), store the digest at `.cache/alert-<league>-<season>-<week>`,
and skip the POST when it matches. Roughly five lines. A resolved problem
followed by a new one produces a new digest and a new alert, which is correct.

`.cache/` is the right home: losing the digest costs one duplicate
notification, which is precisely the severity that belongs in a cache and not in
`season.db`.

### Transport

Discord webhook. `requests.post(url, json={"content": text})` — the URL lives in
`.env` beside the other secrets and is **never committed**; the repo is public.
Chosen over `ntfy.sh` on three grounds: ntfy topics are public, so anyone
guessing the name could both read the alerts and post to them; ntfy keeps no
history; and Discord renders markdown, so a lineup difference can be a code
block rather than mangled plaintext. Chosen over email because a Discord push
lands on a phone through an app the user already runs.

**Setup note that decides whether this works at all:** the target channel must
be set to *All Messages*. Discord's default batching would deliver a 12:15
scratch late, which for this purpose is identical to not delivering it.

### Freshness

The alert is only as good as the data behind it. `load_league_rosters` already
caches for 300s, which is right for a 30-minute cadence. **The injury and
practice loaders' TTLs have not been checked against this cadence** — if either
is cached for an hour, a Sunday-morning ruling is invisible until after
kickoff and the feature silently does nothing. `load_weekly_actuals`'s docstring
already establishes the pattern of passing a shorter `ttl_seconds` on live-game
paths. Resolving this is an implementation task, and it is listed in Testing
because a wrong answer here fails silently and looks healthy.

### Scope

**Sleeper only.** Yahoo has no API, so there is no `starters` array and no way
to know what was submitted. The roster file records who is owned, never who is
started. `yahoo-main` gets no alerts, and the spec does not pretend otherwise.

## Degradation

- **`yahoo-main` has no API.** `/waivers` and `/trades` render the same explicit
  message `cli.py` prints today — that the pool needs every team's roster and
  Yahoo serves none — never an empty table. `/lineup` works, from the roster file.
- **`/draft` states on the page** that it is local-only and single-process, and
  that the CLI must not run against the same league concurrently. Hosting the
  draft board is explicitly out of scope; see below.
- **A failed fetch degrades to a named absence**, never a fabricated number.
  Non-negotiable #7 applies to every panel on every page.

## Staging

Each step is independently shippable and independently useful.

1. **`launchd` snapshot job.** Closes TODO item 2. No app changes. Thursday
   plus the Sunday window; no alerting yet, so it is silent by construction.
2. **Alerting.** `roster_starter_ids()`, the threshold predicate, `notify.py`,
   the dedupe digest. Rides on step 1's job and needs none of the web work —
   which is why it comes second rather than last, despite being specified late.
3. **Extract `pipeline.py`;** `cli.py` renders from it. **The existing text
   renderer tests must pass unchanged** — that is the evidence the extraction
   altered no behaviour, and it is the only evidence that counts.
4. **Multi-page shell,** homepage with status strip, season pages as
   `html.Pre(<existing text renderer>)`. Usable from a phone at the end of this
   step, with horizontal scrolling.
5. **Upgrade `/lineup`, `/waivers`, `/trades` to real HTML,** one page per
   commit. The text renderers remain as the CLI's output and as a fallback.
6. **Headlines and trending panels.**
7. **Hosting**, decided with the app in hand.

Steps 1 and 2 deliver want 4 — arguably the highest-value want on the list —
before any of the web work begins.

## Testing

- **Builders take an explicit `fetcher`** and are tested offline against
  fixtures, like every loader. No network, no mocking — the existing rule.
- **The extraction's proof is the unchanged renderer tests**, not new ones. A
  new test that passes against both the old and new code proves nothing about
  the refactor.
- **`conftest.py`'s network and database guards apply unchanged.** No test may
  reach either; the web tests are no exception, and a Dash test that starts a
  server is not worth the guard it would need waiving.
- **Mutations in `scripts/mutate.py`** for the RSS parser and for the status
  strip's snapshot-recorded predicate — both are branch logic whose failure is
  silent and plausible-looking.
- **The status strip's "recorded?" logic must be tested against `:memory:`**,
  including the week-with-no-rows case, which is the case that matters.

### Alerting specifically

Every one of these fails silently and looks healthy, which is why they are
enumerated rather than left to judgement.

- **The clean case must be tested: no alert is sent.** This is the property the
  entire design rests on, and it is the one a suite naturally omits because
  nothing happens. A test that only proves alerts fire would pass against code
  that alerts every run.
- **The dedupe must be tested across two runs with unchanged input** — one
  POST, not two. Also across two runs where the problem *changes*, which must
  produce two.
- **The threshold must be tested on both sides of `close_call_points`**, since
  a comparison written with the wrong sign or a `>=` for a `>` produces a
  feature that either never fires or always does.
- **`notify()` must be tested for the failure path**: a rejected POST returns
  `False`, logs, and does not raise. The snapshot write must still happen. No
  test may reach Discord — the transport takes an injectable poster, the same
  convention as `fetcher`.
- **The injury and practice TTLs must be confirmed against the 30-minute
  cadence** and the finding written down. If a loader caches for an hour, the
  alert cannot see a Sunday-morning ruling, and every test above still passes.
- **Mutations** for the threshold comparison and the dedupe predicate.

## Out of scope

- **Hosting the draft board.** Both drafts finished 2026-09-01; the next is
  roughly eleven months out. The Phase 3 spec concluded draft night stays local
  deliberately: the journal file is the database and the CLI-takeover fallback
  works only because both processes read the same local disk. Hosted, that
  fallback is gone. The homepage links to `/draft`; it runs where it always ran.
- **In-browser config editing.** Deferred by the Phase 3 spec for reasons that
  have not changed: `config.toml` is load-bearing for correctness, `tomllib` is
  read-only, and a silently-failed edit produces a healthy-looking wrong board.
- **Authentication.** Not required, per fact 4. Revisit only if sharing is ever
  wanted, and treat it as a new spec rather than an addition.
- **Bluesky or any social feed.** Offered, declined.
- **Alerts on waivers or trades.** Neither is time-critical in the way a
  kickoff is, and both would be advisory pushes with no deadline — the exact
  shape of notification that trains you to ignore the channel.
- **X/Twitter alerts or any second transport.** `notify()` is one function so a
  swap stays cheap; a fallback chain is not built until one transport has
  actually failed.
- **The Phase 3.7 `DataTable` swap.** This spec produces evidence for it and
  does not perform it.

## Open questions

1. **Should `taken_at` join the snapshot primary key,** so multiple looks per
   week are kept rather than overwritten? It would make the Thursday run
   meaningful on its own terms and would let a Sunday-morning look be compared
   against a Thursday one. It also changes what a row means and touches
   `store.py`. **Not decided; not needed for anything in this spec.**
2. **Which RSS feeds, exactly.** URLs to be verified at build time.
3. **Whether the status strip should also surface `preflight`'s other checks.**
   The strip carries two of them; `preflight` carries more. Deliberately left
   until the strip has been lived with.
4. **What the injury and practice loader TTLs actually are**, and whether the
   alert path needs shorter ones. Listed as an open question rather than
   answered from memory. See Testing.
5. **Whether the Sunday window should extend to the late slate** (4:05/4:25 ET
   kickoffs). The current window covers the 1pm games only. Left until one
   Sunday has been observed, because the answer depends on how many of the
   user's starters play late — a fact about this roster, not about the design.
