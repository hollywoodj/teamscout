# OpenDota Esports History

Date: 2026-07-25
Status: Approved

## Goal

Add verified OpenDota ticketed-match history to LD2L Scout. Captains should be
able to filter the dashboard to players with esports records and inspect each
player's league career in the scouting report.

The existing organized-match signal remains useful, but it relies on a lobby
fingerprint. The new feature will label only matches with a nonzero OpenDota
`leagueid` as verified esports matches.

## User experience

### Dashboard

The player-board controls gain a `🏆 Esports` filter. Turning it on shows players
with at least one verified ticketed match.

Players with verified history receive a compact badge containing their
all-time ticketed game count. The dashboard adds an `Esports` column for the
verified count and renames the existing `League` column to `Organized (6mo)`.
The rename keeps inferred Captains Mode and 10-stack games distinct from
ticketed league games.

The filter joins the existing saved filter state. A report refresh will preserve
the user's selected filter in browser storage.

### Player scouting report

Each report gains an `Esports history` card with these sections:

- Career summary: total games, wins and losses, win rate, league count, first
  appearance, and latest appearance.
- Per-league table: league name, games, record, win rate, first and last dates,
  and the player's most-used heroes in that league.
- Recent matches: ticketed matches from the last six months, sorted newest
  first. Each row shows date, league, hero, result, K/D/A, GPM, XPM, and a link
  to the OpenDota match page.

If a player has no ticketed games in the last six months, the recent section
shows matches from the player's three most recent leagues. The heading states
that the report used this fallback.

A player with no verified matches sees `No ticketed OpenDota matches found`.
A run that could not fetch or load esports data shows `Esports history
unavailable for this run`. The report must not turn missing data into a zero.

### Report index

The scouting-report index adds a sortable `Esports` count. This gives the user
a second way to find league-experienced players before opening a dossier.

## Data source

OpenDota documents `/explorer` as an endpoint for read-only SQL queries. The
scout will make one query for the signup pool and join:

- `player_matches` for player result and performance fields
- `matches` for time, side, result, and `leagueid`
- `leagues` for the league name

The query restricts `account_id` to the integer Steam32 IDs from the current
signup list and requires `matches.leagueid > 0`. It returns:

- account ID and match ID
- start time, league ID, and league name
- player slot and Radiant result
- hero ID
- kills, deaths, assists, GPM, and XPM

The query orders rows by start time, newest first and caps the pool result at
10,000 rows. The implementation will construct the ID list from parsed integers
and will not interpolate text from the website or browser.

Source: <https://api.opendota.com/api/>

## Architecture

### OpenDota client

`scout/opendota.py` gains an Explorer helper that accepts a SQL string and
returns the `rows` array from a valid response. It uses the existing request
method, rate limit, retries, user agent, and API key handling.

### Esports subsystem

A focused `scout/esports.py` module owns:

- construction of the pool query
- response validation and match deduplication
- cache loading and stale-cache fallback
- aggregation by player and league
- selection of the six-month recent view or three-league fallback

The module returns a map keyed by Steam32 ID. Each value carries a data status,
career totals, per-league summaries, and match rows. Report generators consume
this structure without issuing network requests.

### Orchestration and cache

`scout/cli.py` loads esports history after scraping the signup pool and before
building player metrics. The online scout uses a 24-hour cache. A cache miss
costs one additional OpenDota request for the full pool.

An offline run reads the last cached result regardless of age. If an online
request fails, the scout uses stale cached data and prints a warning. If no
cache exists, it records an unavailable status for the run.

The cache key includes the season and a schema version. The cached payload
stores the fetched timestamp, queried player IDs, normalized match rows, and
whether the result reached the 10,000-row cap. The implementation will warn
rather than claim a complete career when the result reaches that cap.

### Analysis and output records

`scout/analysis.py` keeps its current inferred organized-match calculations.
It receives the normalized esports history and exposes separate fields such as:

- `esports_status`
- `esports_games`, `esports_wins`, `esports_losses`, `esports_winrate`
- `esports_league_count`
- `esports_first`, `esports_latest`
- `esports_leagues`
- `esports_recent_matches`
- `esports_recent_mode`

`scout/report_html.py` embeds the summary fields needed for the dashboard
filter, badge, and column. `scout/report_player_html.py` receives the full
league and match lists for the detailed card.

## Aggregation rules

The player wins when their side matches `radiant_win`:

- `player_slot < 128` means Radiant
- `player_slot >= 128` means Dire

The subsystem deduplicates rows by `(account_id, match_id)`. It groups league
rows by `leagueid`; missing names render as `League <id>`. Hero IDs use the
scout's existing hero-name map.

The six-month boundary uses each match's UTC start time and the run time. The
three-league fallback selects league groups by their latest match date and
includes the matches belonging to those groups.

League tables sort by latest appearance. Match tables sort newest first. The
report displays no win rate for a zero-game or unavailable record.

## Failure handling

- Invalid Explorer payload: print a warning and use stale cache.
- Explorer timeout or HTTP failure: follow the same stale-cache path.
- Missing league name: show the numeric league ID.
- Missing performance field: show an em dash in that cell.
- Unknown hero ID: use the existing hero-map fallback.
- No cache during an offline run: mark esports data unavailable.
- Safety limit reached: retain the returned rows, label the career history as
  incomplete, and print a console warning.

The dashboard disables the esports filter when the entire run lacks esports
data. Its tooltip explains why.

## Testing

Unit tests will cover:

- query construction from integer player IDs
- Explorer response validation and row deduplication
- Radiant and Dire win calculation
- career and per-league aggregation
- six-month selection and the three-recent-leagues fallback
- unknown league and hero labels
- fresh cache, stale fallback, and offline cache behavior
- unavailable and truncated states

Report tests will verify:

- the dashboard record contains verified esports fields
- the `🏆 Esports` filter includes only players with ticketed games
- the existing organized count remains separate
- the report renders career, league, and recent match sections
- missing data renders as unavailable rather than zero
- OpenDota match links use the expected match ID

The full regression suite must pass before regenerating the Season 22 dashboard
and player reports.

## Scope boundaries

This feature reads OpenDota and does not write to OpenDota, Steam, or LD2L. It
does not scrape Dotabuff or Liquipedia. It does not treat the `/pros` endpoint
as the player's league record because that endpoint lists pro players they
encountered rather than the player's ticketed matches.

The feature does not replace the current organized/inhouse heuristic. It gives
the heuristic an accurate label and presents verified esports history beside
it.
