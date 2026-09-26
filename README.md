# LD2L Scout

Scouting tool for the [Learn Dota 2 League](https://ld2l.org). Scrapes the season
signup list, enriches every player with OpenDota data, and produces:

- **`LD2L_S22_Scouting.xlsx`** — multi-sheet workbook (scouting board, by-role,
  value picks, signature heroes, lobby/league intel, head-to-head template)
- **`LD2L_S22_Scouting.html`** — self-contained interactive dashboard
  (sort/filter/search, draft board with best-available-by-position, compare tray;
  drafted marks persist in localStorage — works offline, safe to refresh mid-draft).
  The **Esports 6mo WR** column shows verified OpenDota ticketed-match win rate
  and sample size, such as `56% (9g)`. This figure comes from OpenDota's
  Explorer, which only covers pro/premium leagues - it does not see amateur
  leagues like LD2L itself (Team Scout's per-player Esports tab uses a
  different, slower method that does). The **Draft Value** column ranks the
  pool with a confidence-weighted combination of auction edge, verified league
  proof, recent lane results, role fit, vision/dewarding, and targeted hero fit.
- **`scout_reports/`** — one self-contained HTML **scout report per player**
  (+ an `index.html`): career narrative, winrate breakdowns, US-East
  vulnerability read, strongest/signature heroes, per-position ratings on the
  Plays-Like scale, verified all-time ticketed league history, exact recent
  lane/deward evidence, requested-hero fit, and a chat toxicity report. Skip
  with `--no-reports`.

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
python ld2l_scout.py --herodraft     # practice: Captains Mode hero draft vs a bot (also the Mock Draft button in Team Scout)
python ld2l_scout.py --teamscout     # mirror: scout your team against an opponent
python ld2l_scout.py --refresh-creators  # pull BSJ / Speeed meta videos into the draft bot
```

Optional: set `OPENDOTA_API_KEY` for faster/uncapped API access. Without it the
tool paces itself for the free tier and reuses cached data (`cache/`): volatile
stats refresh every 2h, heavy history every 24h, and new signups fetch
everything. Ticketed history uses one pool-wide OpenDota Explorer query and is
cached for 24 hours; `--offline` reuses the last cached result.
The ten newest full match parses per player are cached permanently by match ID
because completed matches are immutable. The first deep run is heavier; later
runs fetch only newly selected matches and offline runs reuse the cache.
The separate Captains Mode/full-stack organized-play heuristic remains an
internal scouting signal; it is not presented as proof that a match belonged
to a ticketed league.

**Team Scout (`--teamscout`)** is a mirrored team-versus-opponent web app at
**http://127.0.0.1:8324/**. Pick either side from the current LD2L Season 22
teams, or assemble a custom five-player roster. Four focused pages keep team
work separate: Your Team, Player Breakdown, Opponent, and a mirrored Matchup.
Team pages include hero pools, deep stats, and patch history. Player detail
includes lifetime hero records, this week,
current patch, recent-patch history, and a full row for every cached match.

Team Scout's analysis treats wins and losses as separate populations. For the
selected window it compares KDA, deaths, farm, XP, damage, tower pressure, lane
efficiency, ward purchases, and teamfight participation, then calls out the
largest observed differences. These are descriptive associations, not causal
claims; the UI shows sample sizes and a Wilson 95% win-rate range, warns on tiny
win/loss groups, and notes that player-games from the same match can be
correlated.

**Observed position** is inferred match by match from physical lane, the
hero's normal positional profile, farm pattern, and ward purchases. Every call
is labelled high/medium/low confidence because OpenDota's lane role cannot by
itself distinguish Pos 1 from Pos 5 or Pos 3 from Pos 4. Team and player pages
show the complete Pos 1-5 distribution and win rate at each inferred position;
the match logs show the position, confidence, and underlying evidence for each
game. Signup preference remains visible as a separate claim.

**Best Heroes** is success-ranked rather than volume-ranked. A beta-binomial
style evidence score shrinks small-sample win rates toward 50%, preventing a
single 1-0 hero from outranking a sustained record. Record, raw win rate,
inferred position, sample quality, and every roster player contributing to the
result are shown. The separate **Most exposed heroes** list remains ordered by
games because comfort/bannability and proven success answer different scouting
questions.

Current teams, rosters, week, and standings come read-only from the sibling BBC
show feed. Official win rate and official-match breakdowns come from BBC's
cached current-season OpenDota match payloads, including opponent, hero,
K/D/A, economy, lane efficiency, damage, and dewarding. Public-match history
continues to use the scout cache, so `--teamscout --offline` is draft-night safe.

### Player heroes and esports

A player's **Pubs** tab now means real ranked/unranked matches only - practice
lobbies (league and inhouse games) and Turbo are excluded, so a player's public
form is not padded by scrims or their own league games. The new **Heroes** tab
turns that same 180-day pub sample, lifetime hero history, official record, and
esports record into one hero pool table, plus a **Hidden gems** list: heroes
the player does well on but rarely shows in officials. A hero counts as a gem
when it clears a shrunk win-rate bar (small samples count less), isn't already
one of their five most-played "comfort" heroes, isn't stale (unplayed in over
a year), and has at most one official appearance so far - roughly, "heroes
they're quietly good at but nobody's drafted for them yet."

The new **Esports** tab is Team Scout's answer to a Dotabuff esports profile,
covering every ticketed league a player has queued into, amateur leagues
included. Dotabuff itself blocks automated access, and OpenDota's own Explorer
(used for the dashboard's Esports 6mo WR column) only indexes pro/premium
leagues - it returns zero rows for LD2L. Instead, Team Scout walks every
practice lobby a player has played via OpenDota's player-matches endpoint,
resolves each one's league one call at a time, and once a league is found,
pulls its complete match list for free (that list covers amateur tiers too).
Results are cached forever. The always-on service keeps this history
updated on its own (see Always on below); `python ld2l_scout.py
--refresh-esports` is an optional manual catch-up pass. Each run spends at
most 250 single-match lookups, so a first pass over a lobby-heavy pool can
take a few runs; the Esports tab shows how many lobby games are still
unclassified, and the online main scout run chips away at it too.

## Always on

Team Scout runs as a Windows Scheduled Task (`Team Scout`) that starts at logon and self-heals every 5 minutes. Bookmark **http://127.0.0.1:8324**. The service serves from cache (`--offline`) so the bookmark stays up without hitting the network.

The service also runs with `--auto-refresh`: two minutes after startup, and every 12 hours after that, a background thread pulls fresh OpenDota data for every Team Scout player (their recent match sample, which Recon and the Pubs/Heroes tabs read; rank and lifetime heroes every 3 days), classifies up to 150 more esports lobby games, then rebuilds the page. The page is still built from cache only, so if OpenDota is down the refresh logs a warning and the bookmark keeps serving the last good data. It is sized for OpenDota's free tier (about 1,000 calls a day); the knobs are the `TEAMSCOUT_*` refresh constants in `scout/config.py`. Progress lines start with `↻ Auto-refresh` in `logs	eamscout.log`. You never need to run `--refresh-esports` by hand; it stays available for a big catch-up pass.

```powershell
powershell -ExecutionPolicy Bypass -File services\install_teamscout_task.ps1
```

To pick up a fresh scout run: `Stop-ScheduledTask -TaskName 'Team Scout'; Start-ScheduledTask -TaskName 'Team Scout'`. Logs: `logs\teamscout.log`.

The always-on process also watches BBC's `feed.json` and match cache. When a new week is posted, Team Scout rebuilds itself within about 20 seconds. This week's series is on the **Teams** page; click a row to open that matchup.

**Mock Draft button.** The header (next to Matchup) and the Matchup page both carry
a **⚔ Mock Draft** button. It opens the Captains Mode practice board at
`/draft` behind the same sign-in, with **Your Team and the Opponent already
seated** (the rosters as loaded in Team Scout, standins included, plus the
posted team keys so the bot reads the right official draft book). Each
sign-in gets its own draft, so two teams can practise at once through the
funnel. The board's pool loads in the background after Team Scout starts;
`/draft` says "still loading" for the first few seconds. See *Hero draft
practice* below for how the bot drafts.

**Opponents set themselves.** This week's series come straight from the league sites: LD2L from the newest week on `ld2l.org/schedule/<season>`, RD2L from the division's matchups page on rd2l.gg. BBC's posted matchups are only the fallback when ld2l.org is unreachable and nothing is cached. The always-on process rechecks both sites every 30 minutes (`TEAMSCOUT_SCHEDULE_POLL_MINUTES`) and rebuilds when a new week appears. When My Team is set (a team sign-in, or loading a team into My Team), the Opponent side becomes that week's opponent. It does this once per week: pick a different opponent by hand and it stays until the next week is posted.

Manual `python ld2l_scout.py --teamscout` still opens a browser; the always-on task uses `--no-browser`.

## Scout Bot

Scout Bot is a Discord bot that posts the Briefing and Wards pages (the same
Components V2 pages Team Scout renders) into the team's `#test` channel. It
reads BBC's feed and official-match cache read-only, and only shells out to
`python -m scout.briefing_cli` (never an in-process import) to build a
briefing snapshot.

```powershell
python scout_bot.py                                    # gateway: slash commands (/week, /standings, /matchups, /roster, /recent, /briefing)
python scout_bot.py --post-briefing "Team Name" --vs "Other Team"   # one-shot post
python scout_bot.py --post-briefing "Team Name" --dry-run           # print both pages instead of posting
python scout_bot.py --sync-hero-emojis                              # (re)sync OpenDota hero art as Discord application emojis
```

It runs always-on via the `Scout Bot` Windows Scheduled Task, installed with:

```powershell
powershell -ExecutionPolicy Bypass -File services\install_scout_bot_task.ps1
```

Secrets (`SCOUT_BOT_TOKEN`, `SCOUT_BOT_APPLICATION_ID`, `SCOUT_BOT_GUILD_ID`,
`SCOUT_BOT_CHANNEL_ID`) live in the git-ignored `.env` at the repo root.

## Sharing it with the team

Team Scout is published to the internet through a Tailscale Funnel on the
`bbc-show` node:

**https://bbc-show.tail9d49f5.ts.net:8443/** -> `127.0.0.1:8324`

That node already funnels BBC ControlRoom on 443. The two coexist; Funnel only
permits 443, 8443 and 10000, so Team Scout takes 8443. Both are registered in
`Dev/PORTS.md`.

> `tailscale funnel reset` wipes **every** funnel on the node, BBC's included.
> To retire only this one: `tailscale funnel --https=8443 off`.

### The password

Every request needs HTTP basic auth - there is **no loopback exemption**, and
that is deliberate: Funnel proxies inbound public traffic to `127.0.0.1:8324`,
so a funnelled request and a local browser arrive from the same address. A
loopback bypass would be a bypass for the whole internet.

`teamscout_auth.txt` at the repo root is gitignored and never committed. With
nothing in that file and no `$TEAMSCOUT_PASSWORD`, the server refuses to start
rather than serving unauthenticated.

**One shared password.** A file with a single line and no colon is one secret
for the whole app. Any username works. `$TEAMSCOUT_PASSWORD` does the same
thing and overrides the file.

**One sign-in per team.** Give each team its own username, password, and
league. A line looks like:

```
ld2l:choose-a-password:ld2l:Your LD2L Team Name
rd2l:a-different-password:rd2l:Your RD2L Team Name
```

The team name is the posted name (capitalization and a leading "The" do not
matter). The password cannot contain a colon. That sign-in is locked to its
team: My Team cannot be switched, roster edits and pulled players stay in
that sign-in, and the other league is not in the page at all. Within the same
league, opponents are still there so you can scout the week, but only the
posted roster — not the other sign-in's private edits.

A line with no colon can stay in the file next to those. It remains the
shared password: any username, and it sees the LD2L league only.

An admin sign-in sees every team sign-in in one session. The line is
`admin:password:*` (the `*` is the whole third field). Team passwords still
cannot open that view.

The browser remembers one login for the site. Use **Sign out** (or a separate
browser profile) to switch teams. Two teams open at once means two profiles.

To rotate or add a team: edit `teamscout_auth.txt`, then
`Stop-ScheduledTask -TaskName 'Team Scout'; Start-ScheduledTask -TaskName 'Team Scout'`.

Failed attempts are logged to `logs	eamscout.log` with the client's public IP
from `X-Forwarded-For`, and each failure costs the caller a one-second delay.
Worth a glance now and then - the hostname is discoverable in public
Certificate Transparency logs, so it will get probed.

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

**Draft Value (0â€“100)** is pool-relative and deliberately price-led: 55% comes
from auction value, followed by verified league proof (15%), exact recent lane
results (12%), role fit (8%), vision/dewarding (5%), and requested-hero fit
(5%). Every secondary channel shrinks toward neutral when its sample is small.
Missing data lowers the confidence label instead of counting against a player.

**Lane win %** comes only from each player's ten-match parsed sample. It
compares both sides' combined minute-10 gold and XP in the same physical lane;
a resource gap under 5% is a draw, and draws remain in the displayed sample
denominator. The older per-lane number is explicitly called *match WR while
assigned to that lane*. EFF@10 is shown only as a fallback when exact
opposing-lane data is unavailable.

**Vision/dewarding** separates effort from outcome. Observer and sentry
purchases per 30 minutes come from the 200-match parsed projection. Observer
and sentry wards actually destroyed per 30 come from the ten full match
parses. Support comparisons are role-normalized; no ward purchases are
invented for unparsed matches.

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

**Hero draft practice (`--herodraft`, or the Mock Draft button in Team Scout)**:
practice the *in-game* Captains Mode pick/ban against the team you're about to
face, at `http://localhost:8323/` standalone or at Team Scout's `/draft`, on a
board **laid out like the Dota client** — your picks stack down one side,
theirs down the other, ban strips and the phase timer across the top, and the
hero pool in the four attribute columns (Strength / Agility / Intelligence /
Universal, alphabetical, portraits only) in the exact in-game arrangement. Build
your roster and the enemy roster from the cached signup pool **or pick the
same teams Team Scout is using** (persisted to `herodraft_teams.json`), name
the opposition, choose first pick and side — or coin-flip both. The draft
order is the current Captains Mode sequence (introduced in 7.34, unchanged
through **7.41f**): first-pick bans 3-2-2 / second-pick 4-1-2, picks 1-3-1,
with the real clocks: 15s first ban phase, 30s everything else, 130s reserve
each, timed-out ban = no ban, timed-out pick = random hero.

**What the bot drafts from** (all of it also feeds the hints on your turn):

- **Team Scout's official draft book** for each team — the heroes they have
  actually picked in league matches, ranked by *success, not volume*: a shrunk
  win rate above 50% scaled by √games, so a 3–0 hero outranks a 6–4 which
  outranks a 5–5 habit (the old games×winrate product got that backwards).
  **Undefeated heroes** (2+ games, no losses) get an extra bonus that grows
  with the streak; the first-pick record with a hero dominates the opening
  pick; slot habits count a little.
- **Each player's own official hero record** — who played what, and won, in
  their officials. A player who is 3–0 on a hero in league play gets the
  strongest comfort credit in the tool (more than 30 pubs at 60%), tagged
  `3–0 in officials (undefeated)` in the feed. Team Scout's per-player official
  rows are joined to the draft pool automatically.
- **Lifetime / 180-day / league-lobby comfort** from OpenDota, as before.
- **Role coverage** — every candidate is checked against the seats (pos 1–5,
  from `hero_positions.py`) the team's earlier picks already cover. A hero
  whose positions are still open scores up, a fourth carry scores down, and
  the weight grows with the pick index so the last pick fills the hole. Each
  pick is then seated with the roster player whose comfort *and* measured
  position profile fit it best (the carry player gets the carry).
- **Patch meta**, two ways. Online, OpenDota's bracket win rates and the
  hero-vs-hero matchup matrix (cached for days). Always, a curated
  current-patch tier list in **`scout/meta_heroes.json`** — S/A/B by position
  with a one-line why and the sources — so key meta heroes are recognised even
  offline and are always in the bot's candidate pool. It is hand-maintained:
  when a new patch lands, edit the file (names as OpenDota spells them) and
  the board picks it up on next start. The hints drawer marks meta heroes
  with an S/A badge and the sub-line shows the patch it was written for.
- **Creator watch** — what BSJ, Speeed and the like put out this week is
  treated as a key meta signal. `scout/meta_creators.json` is the watchlist
  (name, YouTube handle, weight). `python ld2l_scout.py --refresh-creators`
  pulls each creator's public YouTube RSS feed (no API key), keeps the
  meta-flavoured uploads ("Top 3 heroes in every role 7.41f", "broken hero",
  "tier list"...), and reads hero names and positions out of the title and
  description ("1:10 Carry: Ursa, PL and WK" → Ursa/PL/WK at pos 1). The Team
  Scout auto-refresh pass and an online `--herodraft` start do this on their
  own. Every creator that has named a hero recently adds a credit to its
  rating that decays over 60 days and lapses after 120, on top of the tier;
  a hero only creators mention still gets on the bot's radar. Hints show a
  creator badge ("BSJ · Speeed") and the drawer's **Creator watch** panel
  lists the videos with the heroes read from each. A video whose description
  names nothing can be filled in by hand in the same file (`videos` entries
  with `heroes`), and hand entries override what was read.
- **Bans** rate the hero from the *opponent's* perspective (their comfort,
  their official record, their open seats, how it counters what you already
  hold), plus the bans they themselves repeat. A ban is discounted when *you*
  want the hero more than they do — that's a pick, not a ban — and the hint
  says so.

The hints drawer's **Official records** panel lists each side's proven league
heroes (undefeated first, with the player and record) so you can see the ban
targets and your own safe picks at a glance; heroes already taken grey out.

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
- **Draft recommendation** — pool rank, 0–100 score, confidence, auction edge,
  recommended role, strongest evidence, principal risks, and the six component
  scores.
- **Lanes and dewarding** — exact recent lane W/D/L, EFF@10 fallback, ward
  purchases per 30, and successful observer/sentry dewards per 30, each with
  its parsed-match sample.
- **Requested hero fit** — lifetime, recent-six-month, and verified ticketed
  records for Lone Druid, Meepo, Huskar, Phantom Lancer, Medusa, Sniper, Viper,
  Witch Doctor, Zeus, and Necrophos. Labels distinguish proven/current evidence
  from historical one-offs.
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
  deepstats.py     immutable full-match cache + exact lane/deward extraction
  fetch.py         cache-aware fetching + signup delta + offline snapshot
  heroes.py        dynamic hero map (OpenDota constants, bundled fallback)
  stats.py         statistical primitives (binomial z, MAD z, IVW, Wilson)
  analysis.py      per-player signals + pool-relative pass (skill, gap, z's)
  auction.py       past auction-draft harvesting + kNN price estimator
  live.py          --live draft-day mode: read-only draft follower + localhost server
  mockdraft.py     --mock mode: local practice auction vs AI captains (offline)
  herodraft.py     Captains Mode pick/ban practice vs a bot (--herodraft, and Team Scout's /draft)
  herodraft_html.py  Dota-themed draft board page
  meta_heroes.json curated current-patch meta tiers by position (hand-edited per patch)
  creators.py      creator meta signal: YouTube RSS -> recent meta videos -> heroes named
  meta_creators.json  creator watchlist (BSJ, Speeed) + hand-entered videos
  bbc_source.py    read-only current-season team/official adapter for BBC artifacts
  team_scout.py    --teamscout payload builder and localhost server
  team_scout_html.py mirrored team/opponent scouting interface
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
