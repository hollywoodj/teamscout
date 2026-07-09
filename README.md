# LD2L Scout

Scouting tool for the [Learn Dota 2 League](https://ld2l.org). Scrapes the season
signup list, enriches every player with OpenDota data, and produces:

- **`LD2L_S22_Scouting.xlsx`** — multi-sheet workbook (scouting board, by-role,
  value picks, signature heroes, lobby/league intel, head-to-head template)
- **`LD2L_S22_Scouting.html`** — self-contained interactive dashboard
  (sort/filter/search, draft board with best-available-by-position, compare tray;
  drafted marks persist in localStorage — works offline, safe to refresh mid-draft)

## Usage

```
pip install -r requirements.txt
python ld2l_scout.py                 # single run (current season)
python ld2l_scout.py --loop          # re-run every 2 hours
python ld2l_scout.py --season 53     # explicit LD2L season id
python ld2l_scout.py --force-refresh # ignore cache TTLs
```

Optional: set `OPENDOTA_API_KEY` for faster/uncapped API access. Without it the
tool paces itself for the free tier and reuses cached data (`cache/`): volatile
stats refresh every 2h, heavy history every 24h, new signups fetch everything.

**Auction values**: past auction drafts (last 4 auction seasons, cached weekly)
feed two columns — *Last Cost* (what a returning player actually went for, or
"captain"/"undrafted") and *Est. Cost* (median winning bid of the 7 nearest-MMR
players across those seasons, normalized to the current auction base and rounded
to the bid resolution). Estimates are a starting anchor, not a prediction —
captains' own valuations, meta reads, and package deals move real prices.

**Draft-day budget tracking**: captains get weighted budgets (lower-MMR captains
get more). Budgets are scraped automatically from the season teams page
(`/teams/{season}`, "Total Money" column) as soon as teams are posted — no setup
needed. A `budgets.json` next to the script can override individual captains:

```json
{ "Hollywood": 515, "Crypt1c": 310 }
```

The dashboard's Draft board shows remaining budget per captain. During the
auction, mark a player drafted and enter the price paid + winning team in their
row — budgets, market-spent totals, and best-available update live, and it all
persists in localStorage across refreshes.

## Background job (Windows)

`install_scout.ps1` (run as admin) registers a Task Scheduler job that runs
`run_scout.bat` every 2 hours, logging to `scout_log.txt`. Remove with
`uninstall_scout.ps1`.

## Layout

```
ld2l_scout.py      entry point
scout/
  config.py        season id, URLs, TTLs, thresholds
  ld2l.py          signup scraping (ld2l.org data-* attributes)
  opendota.py      rate-limited API client w/ retries + call counter
  cache.py         per-player JSON cache with per-section freshness
  fetch.py         cache-aware fetching + signup delta detection
  heroes.py        dynamic hero map (OpenDota constants, bundled fallback)
  analysis.py      derived signals (lobby rank, lanes, solo/party, form, tiers)
  auction.py       past auction-draft harvesting + cost estimation
  report_xlsx.py   Excel workbook
  report_html.py   HTML dashboard
  cli.py           argparse CLI + loop mode
```

## New season checklist

1. Find the new season id: look at the signups link on https://ld2l.org
   (e.g. `/seasons/53/signups` = Season 22).
2. Update `DEFAULT_SEASON_ID` in `scout/config.py` (or pass `--season`).
3. Delete `cache/signups_s<old>.json` if you want a clean "new signup" baseline.
