# OpenDota Ticketed League History

Date: 2026-07-25
Status: Approved

## Goal

Show each player's verified ticketed-match win rate from the last six months on
the scouting dashboard. Add a detailed, all-time ticketed league history to
each player's HTML scouting report.

OpenDota identifies a ticketed league match with a nonzero `leagueid`. The
existing scout infers organized games from lobby type, game mode, and party
size. That inference remains available to analysis code but will no longer
appear in the dashboard's `League` column.

## Dashboard

Rename the current `League` column to `Esports 6mo WR`. Each cell shows the
player's win rate across verified ticketed matches during the six months before
the report run:

```text
56% (9g)
```

The cell shows an em dash when the player has no ticketed matches in that
window. Missing OpenDota data also shows an em dash, with a tooltip that states
the data was unavailable for the run.

The column sorts by win rate. Players with the same win rate sort by ticketed
game count. Players with no six-month ticketed record sort last.

This feature adds no esports filter, player badge, all-time dashboard count, or
report-index column.

## Player scouting report

Each player's existing HTML dossier gains an `Esports history` card.

### Career summary

The summary shows:

- all-time ticketed games
- wins, losses, and win rate
- number of leagues
- first ticketed appearance
- latest ticketed appearance
- six-month record and win rate

### Per-league history

A table groups the player's all-time ticketed matches by `leagueid`. Each row
shows:

- league name
- games, wins, losses, and win rate
- first and latest match dates
- most-played heroes in that league

The table sorts leagues by the player's latest match in each league.

### Match history

The match table shows ticketed matches from the last six months, newest first.
Each row contains:

- date and league name
- hero and result
- K/D/A
- GPM and XPM
- a link to the OpenDota match page

If the player has no ticketed match in the last six months, the table shows
matches from their three most recent leagues. The heading identifies this
fallback.

A player with no verified ticketed matches sees `No ticketed OpenDota matches
found`. A run that could not fetch or load ticketed data shows `Esports history
unavailable for this run`. Missing data must not render as a zero-game career.

## Data source

OpenDota documents `/explorer` as a read-only SQL endpoint. The scout will make
one pool-wide query joining:

- `player_matches` for player result and performance fields
- `matches` for start time, side, result, and `leagueid`
- `leagues` for the league name

The query restricts `account_id` to parsed integer Steam32 IDs from the current
signup list and requires `matches.leagueid > 0`. It returns:

- account ID and match ID
- start time, league ID, and league name
- player slot and Radiant result
- hero ID
- kills, deaths, assists, GPM, and XPM

The query orders rows by start time, newest first and caps the pool result at
10,000 rows. The implementation will build the ID list from integers and will
not interpolate text from the website or browser.

Source: <https://api.opendota.com/api/>

## Architecture

### OpenDota client

`scout/opendota.py` gains an Explorer helper that accepts a SQL string and
returns the `rows` array from a valid response. It uses the current request
method, retry policy, rate limit, user agent, and API key handling.

### Ticketed-history subsystem

A focused `scout/esports.py` module owns:

- construction of the pool query
- response validation and match deduplication
- cache loading and stale-cache fallback
- aggregation by player and league
- six-month calculations
- selection of the three-recent-leagues fallback

The module returns a map keyed by Steam32 ID. Each value carries a data status,
career totals, a six-month summary, per-league summaries, and match rows. Report
generators consume this structure without issuing network requests.

### Orchestration and cache

`scout/cli.py` loads ticketed history after scraping signups and before building
player metrics. The online scout uses a 24-hour cache. A cache miss costs one
OpenDota request for the signup pool.

An offline run reads the cached result regardless of age. If an online request
fails, the scout uses stale cached data and prints a warning. If no cache
exists, it records an unavailable status for the run.

The cache key includes the season and a schema version. The payload stores the
fetch timestamp, queried player IDs, normalized match rows, and whether the
result reached the 10,000-row cap. The scout will label the history incomplete
and print a warning when the result reaches that cap.

### Analysis and reports

`scout/analysis.py` keeps the current inferred organized-match calculation
separate from verified ticketed history. It receives the normalized ticketed
record and exposes:

- `esports_status`
- `esports_games`, `esports_wins`, `esports_losses`, `esports_winrate`
- `esports_league_count`, `esports_first`, `esports_latest`
- `esports_6mo_games`, `esports_6mo_wins`, `esports_6mo_winrate`
- `esports_leagues`
- `esports_recent_matches`, `esports_recent_mode`

`scout/report_html.py` embeds only the six-month fields required for the
dashboard column. `scout/report_player_html.py` receives the full career,
league, and match lists.

## Aggregation rules

The player wins when their side matches `radiant_win`:

- `player_slot < 128` means Radiant
- `player_slot >= 128` means Dire

The subsystem deduplicates rows by `(account_id, match_id)`. It groups league
rows by `leagueid`; a missing name renders as `League <id>`. Hero IDs use the
scout's existing hero-name map.

The six-month boundary uses the run time and each match's UTC start time. The
three-league fallback selects league groups by their latest match date and
includes matches from those groups.

League summaries sort by latest appearance. Match rows sort newest first.
Win-rate calculations use only matches with a valid side and result.

## Failure handling

- Invalid Explorer payload: print a warning and use stale cache.
- Explorer timeout or HTTP failure: follow the stale-cache path.
- Missing league name: show the numeric league ID.
- Missing performance field: show an em dash in that cell.
- Unknown hero ID: use the existing hero-map fallback.
- No cache during an offline run: mark ticketed history unavailable.
- Safety cap reached: retain the rows, label the career history incomplete,
  and print a warning.

## Testing

Unit tests will cover:

- query construction from integer player IDs
- Explorer response validation and row deduplication
- Radiant and Dire win calculation
- all-time and six-month aggregation
- per-league grouping
- three-recent-leagues fallback
- unknown league and hero labels
- fresh cache, stale fallback, and offline cache behavior
- unavailable and incomplete states

Report tests will verify:

- the dashboard record contains six-month ticketed fields
- the column renders win rate and sample size
- the column sorts by win rate, then sample size
- zero recent games and unavailable data render as an em dash
- the report renders career, league, and match sections
- the match table switches to the three-league fallback when required
- OpenDota match links use the expected match ID
- the removed filter, badge, and index changes do not appear

The full regression suite must pass before regenerating the Season 22 dashboard
and player reports.

## Scope boundaries

This feature reads OpenDota and does not write to OpenDota, Steam, or LD2L. It
does not scrape Dotabuff or Liquipedia. It does not treat `/players/{id}/pros`
as league history because that endpoint lists pro players encountered in
matches.

The feature leaves the existing organized/inhouse heuristic in analysis code.
The dashboard and detailed report use verified ticketed matches for esports
claims.
