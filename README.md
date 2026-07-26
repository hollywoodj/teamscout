# LD2L Scout

Scouting tool for the [Learn Dota 2 League](https://ld2l.org). Scrapes the season
signup list, enriches every player with OpenDota data, and produces:

- **`LD2L_S22_Scouting.xlsx`** — multi-sheet workbook (scouting board, by-role,
  value picks, signature heroes, lobby/league intel, head-to-head template)
- **`LD2L_S22_Scouting.html`** — self-contained interactive dashboard
  (sort/filter/search, draft board with best-available-by-position, compare tray;
  drafted marks persist in localStorage — works offline, safe to refresh mid-draft).
  The **Esports 6mo WR** column shows verified OpenDota ticketed-match win rate
  and sample size, such as `56% (9g)`.
- **`scout_reports/`** — one self-contained HTML **scout report per player**
  (+ an `index.html`): career narrative, winrate breakdowns, US-East
  vulnerability read, strongest/signature heroes, per-position ratings on the
  Plays-Like scale, verified all-time ticketed league history, and a chat
  toxicity report. Skip with `--no-reports`.

## Usage

```
pip install -r requirements.txt
python ld2l_scout.py                 # single run (current season)
python ld2l_scout.py --loop          # re-run every 2 hours
python ld2l_scout.py --season 53     # explicit LD2L season id
python ld2l_scout.py --force-refresh # ignore cache TTLs
python ld2l_scout.py --offline       # rebuild reports from cache, zero network
python ld2l_scout.py --live          # draft day: follow the live draft (read-only)
python ld2l_scout.py --mock          # practice: local mock auction vs AI captains
python ld2l_scout.py --mock --me "Hollywood"   # pick your seat (default: Hollywood)
python ld2l_scout.py --herodraft     # practice: Captains Mode hero draft vs a bot
```

Optional: set `OPENDOTA_API_KEY` for faster/uncapped API access. Without it the
tool paces itself for the free tier and reuses cached data (`cache/`): volatile
stats refresh every 2h, heavy history every 24h, and new signups fetch
everything. Ticketed history uses one pool-wide OpenDota Explorer query and is
cached for 24 hours; `--offline` reuses the last cached result.
The separate Captains Mode/full-stack organized-play heuristic remains an
internal scouting signal; it is not presented as proof that a match belonged
to a ticketed league.

## How the numbers are computed

**Plays Like (skill estimate)**: a behavioral estimate of true current skill,
built *without* looking at the listed MMR so the two can be compared honestly:

- *medal-implied MMR* (rank_tier, ~154 MMR per star) and the *median
  average_rank of the ranked lobbies they actually queue into* (up to 200
  matches / 6 months) are combined by inverse-variance weighting;
- if the two disagree by >500 MMR the lobby signal is trusted more when it's
  higher (medals decay; lobbies don't lie) and the medal more when it's lower
  (party queue drags average_rank down);
- a *momentum* nudge (±≤120) applies only when the 30-day record is
  statistically real (|z| ≥ 1.28), and a *rust* penalty (1.5/day past 30 days
  idle, ≤180) covers inactivity;
- OpenDota's `computed_mmr` is deliberately ignored — for this population it
  compresses everyone into ~3700-4300 regardless of actual skill (r≈0.5).

**Gap** = Plays Like − listed MMR. Big positive = likely underpriced; big
negative = risk. A listed MMR ≤1100 with a huge gap is flagged `★unrated`
(placeholder signup, expect an admin re-rate) rather than sold as a bargain.

**Value Tier** grades the gap: S ≥ +500 (steal), A ≥ +300, B ≥ +150,
C = fair (±150), D ≤ −150, E ≤ −300 (overpriced), F ≤ −500. A trailing `?`
means the gap is smaller than the skill estimate's uncertainty — treat it as
a lead, not a verdict.

**Est$ / Worth$ / Edge$**: expected price at listed MMR, price a player of
that *true* skill usually goes for, and the difference — the auction edge.
The price model is a 7-nearest-by-MMR median over the last 4 auction seasons,
normalized to the current base (LOOCV MAE ≈ 36; fancier models don't beat the
noise in real bids), plus a scarcity premium: every tracked draft bid its top
names well past what MMR alone implies (the #1 slot went 215–257 on a 500
base in all 4 seasons) and let the late rounds go for steals, so the estimate
is shifted by pool rank — about +80 at the very top, fading to zero by
mid-board, roughly −15 in the tail. Scarcity is also positional: the top 3
available at each position carry +40/+25/+12 (a player gets the larger of
the overall and positional premiums, never both). In the dashboard the
premium recomputes live from the hand-set roles, captains and corrected
MMRs — set the support (4/5) role circles to price that market properly.
*Last Cost* shows what a returning player actually went for.

**Server**: the region a player has played most over the last 3 months
(USE / USW / SEA / EU…), derived from each match's cluster. Hover the cell for
the full mix. Needs an online run to populate (cluster is a re-fetched field).

**Climb (listed-MMR change since signup)**: the player's listed MMR the first
time the tool sees them is captured as a baseline and held fixed; Climb is the
current listing minus that baseline. It flags ▲/▼ when an admin re-rate or a
self-update moves the number before the draft, and reads "—" while unchanged.
It's a freshness signal (is the number in front of you still the one they
signed up with?), read alongside *Gap* — a big Gap with no Climb is a player
whose listing hasn't been touched, the kind others may not have re-scouted.
Baseline persists in `cache/mmr_baseline_s{season}.json`, so it only accrues
signal across runs through the signup/re-rate period.

**Outlier signals** are z-score based, not fixed thresholds: hot/cold streaks
need |z| ≥ 1.65 on the 30-day record; farm (median GPM) and KDA are robust
(median/MAD) z-scores against stated-core / all players within ±700 listed
MMR; "holds up a bracket" uses the record in lobbies 2+ stars above their own
medal with a Wilson lower bound.

**My Team planner** (dashboard): enter your locked-in roster with each player's
role(s) — multi-select for flex. A bipartite matching of players to positions
computes which of Pos 1–5 you still *need* (two Pos-1-only players cover one
carry slot, not two), and lists the best-available player for each gap. The
"🎯 Fit my needs" filter narrows the board to players who can fill an open
position, and a behavioural "1-trick" flag (from actual lane concentration)
marks players who only play one role. Candidate roles come from the per-row
role circles (measured-lane seeded, hand-editable), never the signup sheet.

**Draft-day budget tracking**: captains get weighted budgets (lower-MMR captains
get more). Budgets are scraped automatically from the season teams page
(`/teams/{season}`, "Total Money" column) as soon as teams are posted — no setup
needed. A `budgets.json` next to the script can override individual captains:

```json
{ "Hollywood": 515, "Crypt1c": 310 }
```

**Roles** are set by you, not by the signup sheet. Each row has five circles
(P1–P5); toggle the positions a player can play this season. Declared signup
prefs are ignored entirely (they're unreliable) — the circles start from the
lanes the player *actually* plays over the last 6 months (Safe→1, Mid→2,
Off→3; supports can't be told from lane alone, so set P4/P5 by hand) and you
correct from there. These roles drive the position filter, best-available, and
My Team needs. Your edits persist in localStorage. (The Excel workbook, which
can't see your edits, groups by the same measured-lane roles.)

**Signup MMR vs Current MMR**: the board splits MMR into the signup-sheet value
(often a stale placeholder like the 1000 floor) and a hand-set **Current MMR**.
Dotabuff can't be auto-scraped (Cloudflare 403) and Valve hides exact MMR, so
you type the real number (e.g. Hollywood 1000 → 1700); it's saved in your
browser and used to rank the draft tooling. The **Medal** column is the live
OpenDota rank, which can be stale if the player hasn't recalibrated.

**Private profiles** are flagged (🔒) when a player hasn't exposed their match
history — OpenDota reports this via `fh_unavailable`, so their stats will be
missing/thin. Also summarised in the run's console output and an Excel column.

**Captains** are set by hand too (the **C** button on each row), since the
signup flag is unreliable — it seeds once from the site's captain:yes as a
starting point, then you curate. Anyone marked captain drops off the draft
board (best-available + My Team targets) and gets a card in the **Teams** tab.

Each row has a short **Note** field (max 30 chars, e.g. "wants to stick to one
role"), saved in your browser.

Each row has a **✕** to cross off a player you don't want to play with. They
stay visible, struck through in red, everywhere they appear (board,
best-available, My Team targets) — a crossing-out is a visual note, not a
removal. Only *drafting* a player takes them off the best-available draft
board. (A "hide excluded" toggle can hide them entirely if you prefer.) The
list is personal and persists in localStorage.

**Live draft mode (`--live`)**: on draft day, `python ld2l_scout.py --live`
serves the dashboard at `http://localhost:8322/` and follows the ld2l.org
draft **read-only** — nothing is ever posted to the site. The public draft
page is polled every 3s, so completed picks mark themselves (price + winning
team, budgets and best-available update on their own). With the optional
socket deps installed (see `requirements.txt`), it also joins the same
read-only socket.io broadcast every spectator's browser gets, which powers an
**ON THE BLOCK banner**: the nominated player's MMR, Plays-like, Worth$/Est$,
roles, your note and 🎯/✕ marks, plus an advisory **bid assistant** — pick
"I am \<captain\>" in the header and it shows your remaining budget, open
roster slots, whether the player fills a role you still need, and a suggested
max bid (`min(Worth$, budget − $5 × remaining slots)`). It advises only; you
place actual bids by hand in the draft room. A ● LIVE chip shows feed health,
and everything still persists in localStorage — manual edits (price/team you
type yourself) are never overwritten by the feed. Without the socket deps you
still get automatic pick marking, just no nomination banner.

**Mock draft mode (`--mock`)**: practice the auction before draft day, **inside
your real dashboard**. `python ld2l_scout.py --mock` serves the same
`LD2L_S22_Scouting.html` that `--live` does at `http://localhost:8322/`, builds
the draftable pool from the last scout run (same cache as `--offline`), removes
the captains from the pool, and runs a **full English auction locally** — nothing
is ever sent to the site. The auction drives the dashboard's existing header
ticker, live feed, budget tracking and auto pick-marking (the same machinery
`--live` uses), and adds a **🎲 Mock bar** at the top with the interactive
controls: pick your **Seat**, **Start** (a 10-second "draft is starting in…"
countdown), **Nominate** on your turn, and **+1 / +5 / +25** bid buttons. The old
standalone mock board is retired — one surface for both mock and live. (Regenerate
the dashboard once — any normal scout run — so the Mock bar is present.)

Mock roster authority is explicit:

```powershell
python ld2l_scout.py --mock --roster official
python ld2l_scout.py --mock --roster curated
```

Use **official** after the draft roster is finalized. Captains, Steam IDs, team
IDs and starting budgets come from the LD2L season teams page; a valid response
is cached by season for offline fallback. `budgets.json` remains the intentional
final override. `MockDraft.vbs` launches this mode.

Use **curated** during preseason. The captains and starting budgets come from
`captains.json`, with missing Steam IDs recovered from exact player-name
matches. In both modes the `⬇ Captains → mock` export supplies your role circles
and the players marked off the draft (⊘). That keeps the dashboard as the one
scouting surface without letting an old export replace finalized website
budgets.

Captains nominate from lowest to highest starting budget (source order breaks
ties), and each mock team card's blue budget bar shows the share of starting
money remaining.

**Hero draft practice (`--herodraft`)**: practice the *in-game* Captains Mode
pick/ban against the team you're about to face, at `http://localhost:8323/`,
on a board **laid out like the Dota client** — your picks stack down one side,
theirs down the other, ban strips and the phase timer across the top, and the
hero pool in the four attribute columns (Strength / Agility / Intelligence /
Universal, alphabetical, portraits only) in the exact in-game arrangement. Build
your roster and the enemy roster from the cached signup pool (persisted to
`herodraft_teams.json`), name the opposition, choose first pick and side — or
coin-flip both. The draft order is the current **patch 7.40** Captains Mode
sequence (first-pick bans 3-2-2 / second-pick 4-1-2, picks 1-3-1 both sides),
with the real clocks: 15s first ban phase, 30s everything else, 130s reserve
each, timed-out ban = no ban, timed-out pick = random hero.

The bot drafts the enemy side from their **real data**: each player's lifetime
hero stats, 180-day form, and specifically the heroes they play in organized-
league games (the same lobby fingerprint the scout uses); its bans target
*your* roster's comfort heroes the same way.

**Hero ratings + win probability**: every draftable hero shows a Dotabuff-style
rating (e.g. **+4.10**) on its tile and in the Scouting Report, combining four
signals — your roster's **comfort** on the hero, the hero's **patch winrate**
in the LD2L rank brackets (OpenDota `/heroStats`), its **matchup advantage vs**
the heroes the enemy has already picked, and its coverage **synergy with** your
own picks (both from the OpenDota hero-vs-hero matrix). A live **win-probability
meter** at the top reads "*your team is 55% favored*" from the heroes on the
board so far, and each pick lands in the feed with its rating ("picks Meepo
(+7.5)"). On your turns the Scouting Report ranks the best bans (their biggest
threats) and picks (your best-rated heroes) with the full breakdown, and each
pick is auto-assigned to the roster player who plays it best.

The patch meta is fetched once from OpenDota (hero winrates + a 127-call
matchup matrix) and cached for days, so subsequent drafts — and `--offline` —
run entirely from cache. Without any cached meta the board still works on
roster comfort alone (ratings just omit the patch/matchup terms). Fully local:
nothing is sent to ld2l.org or Steam (hero portraits load from the Steam CDN
when online, plain tiles otherwise).

**AI drafting model**: each team seats its captain plus its purchases into
*distinct* positions 1–5 by assignment — a P2/P3 flex slides to P3 when a
P2-only player is bought later, and a captain marked P4/P5 covers whichever
support seat the roster leaves open. A player who fills a seat the team can't
otherwise cover commands full market value. A player who *doesn't* can still
be bought **off-role**: captains will burn a seat and shuffle someone off-role
for a clearly better player, valued at 0.75× worth — but only when that
discounted value still beats the best on-role player left on the board, so a
Legend core outbids a Crusader support filler but loses to an Ancient one, and
top talent never slips through for $1. Bids are hard-capped at 1.25× a
player's Worth$ no matter how target premiums and aggression stack, so there
are no runaway overbids. The Mock bar shows which positions your own team
still needs (`need P4/P5`). The clock can pause naturally, but a player cannot
hammer while a non-leading AI captain remains willing and able to raise;
expired auctions perform one last legal AI bid check before closing.

You draft from the board (default seat **Hollywood**, changeable in the header)
against rational AI captains: each values players by role need (fill positions
1–5 around the captain's own role), remaining budget (keeps reserve for unfilled
slots), and the tool's `Worth$`/skill estimates. When you press **Start** there's
a **10-second countdown** ("the draft is starting in…"), then the auction runs at
a lifelike tempo — bidders mostly click **+1**, occasionally **+5**, rarely
**+25**, so contested players grind up in small increments instead of a couple of
big jumps (tune `MOCK_BID_STEPS` / `MOCK_AI_TICK` in `config.py`). Put a player
**on the block** by nominating on your turn; bid with the on-screen +1/+5/+25
buttons on any auction. You can assign each captain (yours or an opponent's) a set
of **🎯 target players** they should chase harder — targets persist to
`mock_targets.json` and reload next time. Run it as many times as you like;
**Reset** restarts the draft while keeping targets and your seat. Changing speed
during an auction preserves the same AI bidding opportunities; it changes elapsed
time, not expected sale prices.

During the auction, `--live` (or `--mock`) marks players drafted and fills in the
price paid + winning team from the draft feed — market totals, the Draft board
best-available, and the Teams tab all update live and persist in localStorage. A **hide captains**
toggle drops captains from the main board when you only want draftable players.

The **Teams** tab shows each captain with their drafted roster, a **Needs**
line (roles still to fill, via role matching), and a **money breakdown**:
a hand-set **Budget**, **Spent**, **Remaining**, and a mini bar graph showing
the share of the budget used (turns red when over). Budgets are set by hand in
the Teams tab for now and also feed the Draft board's budget chips. The
best-available player list stays on the Draft board only.

## Player scout reports (`scout_reports/`)

Every run also writes a per-player HTML report (open `scout_reports/index.html`).
Each page pulls together, for one player:

- **Career narrative** — a template (no LLM) summary: experience, main role,
  Plays-Like skill/value tier, activity, verified ticketed history, US-East record.
  Tenure is approximated from total game volume (OpenDota exposes no
  account-creation date).
- **Winrate breakdowns** — lifetime, 30/90-day form, solo vs party, record in
  lobbies above their own bracket.
- **Ticketed esports history** — OpenDota matches with `leagueid > 0`: all-time
  record, league-by-league dates/results/top heroes, and match detail for the
  last six months. If there are no matches in that window, the report shows the
  three most recent leagues instead.
- **US-East vulnerability** — win rate specifically on US East (the server LD2L
  plays on), with a verdict (`Vulnerable` / `Below even` / `Holds up`) and the
  gap vs their lifetime rate.
- **Strongest heroes** — most-played and signature heroes (100g+, 53%+ WR).
- **Position ratings** — an estimated skill at each of Pos 1–5 on the tool's
  Plays-Like (medal + MMR) scale. Cores are weighted by measured lane share;
  supports (4/5) can't be told from lane data and are flagged as estimates.
- **Toxicity report** — a 0–100 score from the OpenDota chat word cloud
  (exact-token flame/curse/slur scan, slurs weighted heaviest), the flagged
  words, and a mini word cloud. Needs an online run to populate; private/unparsed
  profiles show "no chat data".

## Background job (Windows)

`install_scout.ps1` (run as admin) registers a Task Scheduler job that runs
`run_scout.bat` every 2 hours, logging to `scout_log.txt`. Remove with
`uninstall_scout.ps1`.

## Layout

```
ld2l_scout.py      entry point
scout/
  config.py        season id, URLs, TTLs, thresholds, model constants
  ld2l.py          signup scraping (ld2l.org data-* attributes)
  opendota.py      rate-limited API client w/ retries + call counter
  cache.py         per-player JSON cache with per-section freshness
  fetch.py         cache-aware fetching + signup delta + offline snapshot
  heroes.py        dynamic hero map (OpenDota constants, bundled fallback)
  stats.py         statistical primitives (binomial z, MAD z, IVW, Wilson)
  analysis.py      per-player signals + pool-relative pass (skill, gap, z's)
  auction.py       past auction-draft harvesting + kNN price estimator
  live.py          --live draft-day mode: read-only draft follower + localhost server
  mockdraft.py     --mock mode: local practice auction vs AI captains (offline)
  herodraft.py     --herodraft mode: Captains Mode pick/ban practice vs a bot
  herodraft_html.py  Dota-themed draft board page (served by herodraft.py)
  report_xlsx.py   Excel workbook
  report_html.py   HTML dashboard
  report_mock_html.py  interactive mock-draft board (served by mockdraft.py)
  cli.py           argparse CLI + loop mode
```

## New season checklist

1. Find the new season id: look at the signups link on https://ld2l.org
   (e.g. `/seasons/53/signups` = Season 22).
2. Update `DEFAULT_SEASON_ID` in `scout/config.py` (or pass `--season`).
3. Delete `cache/signups_s<old>.json` if you want a clean "new signup" baseline.
