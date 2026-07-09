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
  report_xlsx.py   Excel workbook
  report_html.py   HTML dashboard
  cli.py           argparse CLI + loop mode
```

## New season checklist

1. Find the new season id: look at the signups link on https://ld2l.org
   (e.g. `/seasons/53/signups` = Season 22).
2. Update `DEFAULT_SEASON_ID` in `scout/config.py` (or pass `--season`).
3. Delete `cache/signups_s<old>.json` if you want a clean "new signup" baseline.
