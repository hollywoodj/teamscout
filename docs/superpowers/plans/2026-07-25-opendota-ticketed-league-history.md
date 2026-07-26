# OpenDota Ticketed League History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dashboard's inferred league column with verified six-month ticketed-match win rate and add all-time ticketed league history to each player dossier.

**Architecture:** Fetch the signup pool's ticketed matches with one OpenDota Explorer query, cache the normalized rows for 24 hours, and aggregate them in a focused `scout/esports.py` module. Pass one history record into each player's existing analysis sections, embed only six-month fields in the dashboard, and render the complete history in `report_player_html.py`.

**Tech Stack:** Python 3 standard library, `requests`, OpenDota REST/Explorer API, `unittest`, generated HTML/CSS/JavaScript.

## Global Constraints

- Count a verified ticketed match only when OpenDota returns `leagueid > 0`.
- Define the six-month window as the 183 days before the UTC report run time.
- Fetch the entire signup pool with one Explorer request and cap the response at 10,000 rows.
- Cache ticketed rows for 24 hours; offline runs may use a cache of any age.
- Treat unavailable data separately from a verified zero-game history.
- Keep the existing organized/inhouse heuristic in analysis code.
- Add no esports filter, player badge, all-time dashboard count, or report-index column.
- Display the dashboard value as `56% (9g)` and an em dash when no six-month record exists.
- Preserve the existing generated dashboard and report behavior outside this feature.

## File Structure

- Create `scout/esports.py`: query construction, normalization, aggregation, recent selection, and cache policy.
- Create `tests/test_esports.py`: focused domain, cache, analysis, dashboard, and report tests.
- Modify `scout/opendota.py`: add one Explorer endpoint helper.
- Modify `scout/analysis.py`: copy ticketed-history fields into each player's metrics.
- Modify `scout/cli.py`: load one pool-wide history map and attach each record before analysis.
- Modify `scout/report_html.py`: replace the current inferred `League` column and compare-row value.
- Modify `scout/report_player_html.py`: render career, per-league, and match history.
- Modify `README.md`: document the verified ticketed metric and distinguish it from inferred organized games.
- Regenerate `LD2L_S22_Scouting.html`, `LD2L_S22_Scouting.xlsx`, and `scout_reports/*.html`.

---

### Task 1: OpenDota Explorer Client

**Files:**
- Modify: `scout/opendota.py:17-79`
- Create: `tests/test_esports.py`

**Interfaces:**
- Consumes: `OpenDota.get(path: str, params: dict | None) -> object | None`
- Produces: `OpenDota.explorer(sql: str) -> list[dict] | None`

- [ ] **Step 1: Write the failing client tests**

```python
# tests/test_esports.py
import sys
import types
import unittest
from unittest import mock

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = types.ModuleType("requests")

from scout.opendota import OpenDota


class ExplorerClientTests(unittest.TestCase):
    def test_explorer_returns_rows_from_valid_payload(self):
        client = object.__new__(OpenDota)
        with mock.patch.object(
            client,
            "get",
            return_value={"rows": [{"match_id": 10}]},
        ) as get:
            self.assertEqual(client.explorer("SELECT 1"), [{"match_id": 10}])
        get.assert_called_once_with("/explorer", params={"sql": "SELECT 1"})

    def test_explorer_rejects_invalid_payload(self):
        client = object.__new__(OpenDota)
        with mock.patch.object(client, "get", return_value={"rows": None}):
            self.assertIsNone(client.explorer("SELECT 1"))
        with mock.patch.object(client, "get", return_value=None):
            self.assertIsNone(client.explorer("SELECT 1"))
```

- [ ] **Step 2: Run the client tests and verify the expected failure**

Run:

```powershell
python -m unittest tests.test_esports.ExplorerClientTests -v
```

Expected: `AttributeError: 'OpenDota' object has no attribute 'explorer'`.

- [ ] **Step 3: Add the Explorer helper**

```python
# scout/opendota.py, beside the other endpoint helpers
def explorer(self, sql):
    payload = self.get("/explorer", params={"sql": sql})
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None
    return payload["rows"]
```

- [ ] **Step 4: Run the client tests**

Run:

```powershell
python -m unittest tests.test_esports.ExplorerClientTests -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit the client helper**

```powershell
git add scout/opendota.py tests/test_esports.py
git commit -m "Add OpenDota Explorer client"
```

---

### Task 2: Ticketed Match Normalization and Aggregation

**Files:**
- Create: `scout/esports.py`
- Modify: `tests/test_esports.py`

**Interfaces:**
- Consumes: integer Steam32 IDs, Explorer row dictionaries, `hero_map.name(hero_id) -> str`
- Produces:
  - `build_query(player_ids, limit=10000) -> str`
  - `aggregate_histories(rows, player_ids, hero_map, now=None, status="fresh", incomplete=False) -> dict[int, dict]`
  - `unavailable_history() -> dict`

The history record has this exact shape:

```python
{
    "status": "fresh",          # fresh | stale | unavailable
    "incomplete": False,
    "games": 3,
    "wins": 2,
    "losses": 1,
    "winrate": 66.7,
    "league_count": 2,
    "first": 1600000000,
    "latest": 1750000000,
    "six_month": {"games": 2, "wins": 1, "losses": 1, "winrate": 50.0},
    "leagues": [
        {
            "league_id": 100,
            "name": "League A",
            "games": 2,
            "wins": 1,
            "losses": 1,
            "winrate": 50.0,
            "first": 1740000000,
            "latest": 1750000000,
            "heroes": [{"name": "Axe", "games": 2}],
        }
    ],
    "recent_matches": [
        {
            "match_id": 11,
            "start_time": 1750000000,
            "league_id": 100,
            "league_name": "League A",
            "hero": "Axe",
            "result": "W",
            "kills": 4,
            "deaths": 2,
            "assists": 10,
            "gpm": 500,
            "xpm": 600,
        }
    ],
    "recent_mode": "six_months",  # six_months | latest_leagues | none
}
```

- [ ] **Step 1: Add failing query and aggregation tests**

```python
# tests/test_esports.py
from datetime import datetime, timezone

from scout.esports import aggregate_histories, build_query, unavailable_history


class HeroMapStub:
    NAMES = {1: "Axe", 2: "Bane"}

    def name(self, hero_id):
        return self.NAMES.get(int(hero_id), f"Hero {hero_id}")


class EsportsAggregationTests(unittest.TestCase):
    NOW = int(datetime(2026, 7, 25, tzinfo=timezone.utc).timestamp())

    @staticmethod
    def row(match_id, start_time, league_id=100, slot=0, radiant_win=True,
            hero_id=1, league_name="League A"):
        return {
            "account_id": 10,
            "match_id": match_id,
            "start_time": start_time,
            "leagueid": league_id,
            "league_name": league_name,
            "player_slot": slot,
            "radiant_win": radiant_win,
            "hero_id": hero_id,
            "kills": 4,
            "deaths": 2,
            "assists": 10,
            "gold_per_min": 500,
            "xp_per_min": 600,
        }

    def test_query_uses_sorted_integer_ids_and_ticketed_constraint(self):
        sql = build_query([20, "10", 20])
        self.assertIn("pm.account_id IN (10,20)", sql)
        self.assertIn("m.leagueid > 0", sql)
        self.assertIn("ORDER BY m.start_time DESC", sql)
        self.assertTrue(sql.rstrip().endswith("LIMIT 10000"))
        with self.assertRaises(ValueError):
            build_query(["10); DROP TABLE matches"])

    def test_aggregates_career_leagues_and_six_month_record(self):
        recent = self.NOW - 10 * 86400
        old = self.NOW - 400 * 86400
        rows = [
            self.row(1, recent, slot=0, radiant_win=True),
            self.row(2, old, league_id=200, slot=128, radiant_win=True,
                     hero_id=2, league_name="League B"),
            self.row(2, old, league_id=200, slot=128, radiant_win=True,
                     hero_id=2, league_name="League B"),
        ]
        history = aggregate_histories(rows, [10], HeroMapStub(), now=self.NOW)[10]
        self.assertEqual((history["games"], history["wins"], history["losses"]),
                         (2, 1, 1))
        self.assertEqual(history["league_count"], 2)
        self.assertEqual(history["six_month"],
                         {"games": 1, "wins": 1, "losses": 0, "winrate": 100.0})
        self.assertEqual(history["recent_mode"], "six_months")
        self.assertEqual(history["recent_matches"][0]["hero"], "Axe")
        self.assertEqual([x["name"] for x in history["leagues"]],
                         ["League A", "League B"])

    def test_dire_win_and_three_latest_leagues_fallback(self):
        rows = [
            self.row(1, self.NOW - 400 * 86400, league_id=1, slot=128,
                     radiant_win=False, league_name="Newest"),
            self.row(2, self.NOW - 500 * 86400, league_id=2,
                     league_name="Second"),
            self.row(3, self.NOW - 600 * 86400, league_id=3,
                     league_name="Third"),
            self.row(4, self.NOW - 700 * 86400, league_id=4,
                     league_name="Excluded"),
        ]
        history = aggregate_histories(rows, [10], HeroMapStub(), now=self.NOW)[10]
        self.assertEqual(history["six_month"]["games"], 0)
        self.assertEqual(history["recent_mode"], "latest_leagues")
        self.assertEqual(
            {m["league_name"] for m in history["recent_matches"]},
            {"Newest", "Second", "Third"},
        )
        self.assertEqual(history["recent_matches"][0]["result"], "W")

    def test_zero_history_is_distinct_from_unavailable(self):
        history = aggregate_histories([], [10], HeroMapStub(), now=self.NOW)[10]
        self.assertEqual(history["status"], "fresh")
        self.assertEqual(history["games"], 0)
        self.assertEqual(history["recent_mode"], "none")

    def test_unknown_league_and_hero_use_safe_fallback_labels(self):
        row = self.row(
            1,
            self.NOW - 86400,
            league_id=999,
            hero_id=999,
            league_name="",
        )
        history = aggregate_histories([row], [10], HeroMapStub(), now=self.NOW)[10]
        self.assertEqual(history["leagues"][0]["name"], "League 999")
        self.assertEqual(history["recent_matches"][0]["hero"], "Hero 999")

    def test_incomplete_state_survives_aggregation(self):
        history = aggregate_histories(
            [], [10], HeroMapStub(), now=self.NOW, incomplete=True,
        )[10]
        self.assertTrue(history["incomplete"])
```

- [ ] **Step 2: Run the aggregation tests and verify import failure**

Run:

```powershell
python -m unittest tests.test_esports.EsportsAggregationTests -v
```

Expected: `ModuleNotFoundError: No module named 'scout.esports'`.

- [ ] **Step 3: Implement query construction and normalization**

```python
# scout/esports.py
from collections import Counter, defaultdict
from datetime import datetime, timezone

RESULT_LIMIT = 10_000
RECENT_SECONDS = 183 * 86400

FIELDS = (
    "account_id", "match_id", "start_time", "leagueid", "league_name",
    "player_slot", "radiant_win", "hero_id", "kills", "deaths", "assists",
    "gold_per_min", "xp_per_min",
)


def build_query(player_ids, limit=RESULT_LIMIT):
    ids = sorted({int(value) for value in player_ids})
    if not ids:
        raise ValueError("ticketed history requires at least one player ID")
    joined = ",".join(str(value) for value in ids)
    return (
        "SELECT pm.account_id, pm.match_id, m.start_time, m.leagueid, "
        "l.name AS league_name, pm.player_slot, m.radiant_win, pm.hero_id, "
        "pm.kills, pm.deaths, pm.assists, pm.gold_per_min, pm.xp_per_min "
        "FROM player_matches pm "
        "JOIN matches m USING (match_id) "
        "LEFT JOIN leagues l ON l.leagueid = m.leagueid "
        f"WHERE pm.account_id IN ({joined}) AND m.leagueid > 0 "
        "ORDER BY m.start_time DESC "
        f"LIMIT {int(limit)}"
    )


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_row(row):
    if not isinstance(row, dict):
        return None
    out = {field: row.get(field) for field in FIELDS}
    for field in (
        "account_id", "match_id", "start_time", "leagueid", "player_slot",
        "hero_id", "kills", "deaths", "assists", "gold_per_min", "xp_per_min",
    ):
        out[field] = _int_or_none(out[field])
    if not all(out.get(field) is not None
               for field in ("account_id", "match_id", "start_time", "leagueid")):
        return None
    if out["leagueid"] <= 0:
        return None
    if out["radiant_win"] not in (True, False):
        out["radiant_win"] = None
    out["league_name"] = str(out.get("league_name") or "").strip()
    return out


def _won(row):
    slot, radiant_win = row.get("player_slot"), row.get("radiant_win")
    if slot is None or radiant_win is None:
        return None
    return (slot < 128) == radiant_win
```

- [ ] **Step 4: Implement aggregation and recent selection**

```python
# scout/esports.py, continued
def unavailable_history():
    return {
        "status": "unavailable",
        "incomplete": False,
        "games": 0,
        "wins": 0,
        "losses": 0,
        "winrate": None,
        "league_count": 0,
        "first": None,
        "latest": None,
        "six_month": {"games": 0, "wins": 0, "losses": 0, "winrate": None},
        "leagues": [],
        "recent_matches": [],
        "recent_mode": "none",
    }


def _summary(rows):
    decided = [(row, _won(row)) for row in rows]
    decided = [(row, won) for row, won in decided if won is not None]
    wins = sum(1 for _, won in decided if won)
    losses = len(decided) - wins
    return {
        "games": len(decided),
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / len(decided) * 100, 1) if decided else None,
    }


def _match_record(row, hero_map):
    won = _won(row)
    return {
        "match_id": row["match_id"],
        "start_time": row["start_time"],
        "league_id": row["leagueid"],
        "league_name": row["league_name"] or f"League {row['leagueid']}",
        "hero": hero_map.name(row["hero_id"]) if row.get("hero_id") else "Unknown",
        "result": "W" if won is True else "L" if won is False else "?",
        "kills": row.get("kills"),
        "deaths": row.get("deaths"),
        "assists": row.get("assists"),
        "gpm": row.get("gold_per_min"),
        "xpm": row.get("xp_per_min"),
    }


def aggregate_histories(rows, player_ids, hero_map, now=None,
                        status="fresh", incomplete=False):
    now = int(now if now is not None else
              datetime.now(tz=timezone.utc).timestamp())
    ids = sorted({int(value) for value in player_ids})
    grouped = defaultdict(list)
    seen = set()
    for raw in rows or []:
        row = _normalize_row(raw)
        if row is None or row["account_id"] not in ids:
            continue
        key = (row["account_id"], row["match_id"])
        if key in seen:
            continue
        seen.add(key)
        grouped[row["account_id"]].append(row)

    result = {}
    for account_id in ids:
        player_rows = sorted(grouped[account_id],
                             key=lambda row: row["start_time"], reverse=True)
        career = _summary(player_rows)
        recent_rows = [
            row for row in player_rows
            if row["start_time"] >= now - RECENT_SECONDS
        ]
        six_month = _summary(recent_rows)
        league_rows = defaultdict(list)
        for row in player_rows:
            league_rows[row["leagueid"]].append(row)

        leagues = []
        for league_id, entries in league_rows.items():
            summary = _summary(entries)
            heroes = Counter(
                hero_map.name(row["hero_id"])
                for row in entries if row.get("hero_id")
            )
            leagues.append({
                "league_id": league_id,
                "name": entries[0]["league_name"] or f"League {league_id}",
                **summary,
                "first": min(row["start_time"] for row in entries),
                "latest": max(row["start_time"] for row in entries),
                "heroes": [
                    {"name": name, "games": games}
                    for name, games in heroes.most_common(3)
                ],
            })
        leagues.sort(key=lambda league: league["latest"], reverse=True)

        if recent_rows:
            selected, mode = recent_rows, "six_months"
        elif leagues:
            league_ids = {league["league_id"] for league in leagues[:3]}
            selected = [row for row in player_rows
                        if row["leagueid"] in league_ids]
            mode = "latest_leagues"
        else:
            selected, mode = [], "none"

        result[account_id] = {
            "status": status,
            "incomplete": bool(incomplete),
            **career,
            "league_count": len(leagues),
            "first": min((row["start_time"] for row in player_rows), default=None),
            "latest": max((row["start_time"] for row in player_rows), default=None),
            "six_month": six_month,
            "leagues": leagues,
            "recent_matches": [
                _match_record(row, hero_map) for row in selected
            ],
            "recent_mode": mode,
        }
    return result
```

- [ ] **Step 5: Run aggregation tests**

Run:

```powershell
python -m unittest tests.test_esports.EsportsAggregationTests -v
```

Expected: 6 tests pass.

- [ ] **Step 6: Commit the domain layer**

```powershell
git add scout/esports.py tests/test_esports.py
git commit -m "Aggregate OpenDota ticketed history"
```

---

### Task 3: Pool Cache and Offline Fallback

**Files:**
- Modify: `scout/esports.py`
- Modify: `tests/test_esports.py`

**Interfaces:**
- Consumes:
  - `od.explorer(sql: str) -> list[dict] | None`
  - `cache.get_blob(name: str, max_age_hours: float | None) -> object | None`
  - `cache.set_blob(name: str, data: object) -> None`
- Produces:
  - `load_ticketed_histories(od, cache, season_id, player_ids, hero_map, offline=False, force=False, now=None) -> dict[int, dict]`

- [ ] **Step 1: Add failing cache-policy tests**

```python
# tests/test_esports.py
import tempfile

from scout.cache import Cache
from scout.esports import load_ticketed_histories


class ExplorerStub:
    def __init__(self, rows=None):
        self.rows = rows
        self.calls = []

    def explorer(self, sql):
        self.calls.append(sql)
        return self.rows


class EsportsCacheTests(unittest.TestCase):
    NOW = EsportsAggregationTests.NOW

    def payload(self):
        return {
            "player_ids": [10],
            "rows": [EsportsAggregationTests.row(
                1, self.NOW - 86400,
            )],
            "incomplete": False,
        }

    def test_fresh_complete_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob("ticketed_history_s53_v1", self.payload())
            od = ExplorerStub(rows=None)
            histories = load_ticketed_histories(
                od, cache, 53, [10], HeroMapStub(), now=self.NOW,
            )
            self.assertEqual(od.calls, [])
            self.assertEqual(histories[10]["status"], "fresh")
            self.assertEqual(histories[10]["games"], 1)

    def test_roster_growth_forces_one_pool_query(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob("ticketed_history_s53_v1", self.payload())
            od = ExplorerStub(rows=[])
            histories = load_ticketed_histories(
                od, cache, 53, [10, 20], HeroMapStub(), now=self.NOW,
            )
            self.assertEqual(len(od.calls), 1)
            self.assertEqual(histories[20]["status"], "fresh")

    def test_failed_online_query_uses_stale_cache(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob("ticketed_history_s53_v1", self.payload())
            od = ExplorerStub(rows=None)
            histories = load_ticketed_histories(
                od, cache, 53, [10], HeroMapStub(),
                force=True, now=self.NOW,
            )
            self.assertEqual(len(od.calls), 1)
            self.assertEqual(histories[10]["status"], "stale")

    def test_offline_without_cache_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            histories = load_ticketed_histories(
                ExplorerStub(rows=[]), Cache(root), 53, [10],
                HeroMapStub(), offline=True, now=self.NOW,
            )
            self.assertEqual(histories[10]["status"], "unavailable")
            self.assertIsNone(histories[10]["six_month"]["winrate"])
```

- [ ] **Step 2: Run cache tests and verify the expected import error**

Run:

```powershell
python -m unittest tests.test_esports.EsportsCacheTests -v
```

Expected: import fails because `load_ticketed_histories` is undefined.

- [ ] **Step 3: Implement cache coverage and fallback**

```python
# scout/esports.py
CACHE_HOURS = 24
CACHE_VERSION = 1


def _cache_name(season_id):
    return f"ticketed_history_s{int(season_id)}_v{CACHE_VERSION}"


def _covered(payload, ids):
    if not isinstance(payload, dict):
        return False
    cached_ids = payload.get("player_ids")
    return isinstance(cached_ids, list) and set(ids).issubset(
        {int(value) for value in cached_ids}
    ) and isinstance(payload.get("rows"), list)


def _from_payload(payload, ids, hero_map, now, status):
    if payload.get("incomplete"):
        print("  ⚠ OpenDota ticketed history reached the 10,000-row cap")
    covered = {int(value) for value in payload.get("player_ids", [])}
    histories = aggregate_histories(
        payload.get("rows", []),
        [account_id for account_id in ids if account_id in covered],
        hero_map,
        now=now,
        status=status,
        incomplete=bool(payload.get("incomplete")),
    )
    for account_id in ids:
        histories.setdefault(account_id, unavailable_history())
    return histories


def load_ticketed_histories(od, cache, season_id, player_ids, hero_map,
                            offline=False, force=False, now=None):
    ids = sorted({int(value) for value in player_ids})
    name = _cache_name(season_id)
    stale = cache.get_blob(name)
    if offline:
        return (_from_payload(stale, ids, hero_map, now, "stale")
                if stale else
                {account_id: unavailable_history() for account_id in ids})

    fresh = None if force else cache.get_blob(name, max_age_hours=CACHE_HOURS)
    if _covered(fresh, ids):
        return _from_payload(fresh, ids, hero_map, now, "fresh")

    rows = od.explorer(build_query(ids)) if ids else []
    if rows is not None:
        payload = {
            "player_ids": ids,
            "rows": rows,
            "incomplete": len(rows) >= RESULT_LIMIT,
        }
        cache.set_blob(name, payload)
        return _from_payload(payload, ids, hero_map, now, "fresh")

    if stale:
        print("  ⚠ OpenDota ticketed history unavailable; using stale cache")
        return _from_payload(stale, ids, hero_map, now, "stale")
    print("  ⚠ OpenDota ticketed history unavailable; no cache found")
    return {account_id: unavailable_history() for account_id in ids}
```

- [ ] **Step 4: Run cache and aggregation tests**

Run:

```powershell
python -m unittest tests.test_esports -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit cache behavior**

```powershell
git add scout/esports.py tests/test_esports.py
git commit -m "Cache ticketed league history"
```

---

### Task 4: Analysis and CLI Wiring

**Files:**
- Modify: `scout/analysis.py:221-282`
- Modify: `scout/cli.py:13-75`
- Modify: `tests/test_esports.py`

**Interfaces:**
- Consumes: `sections["esports"]` in the history shape from Task 2.
- Produces: the exact `esports_*` fields in the approved design.

- [ ] **Step 1: Add a failing analysis-copy test**

```python
# tests/test_esports.py
from scout.analysis import build_metrics


class AnalysisIntegrationTests(unittest.TestCase):
    def test_build_metrics_exposes_ticketed_history(self):
        history = aggregate_histories(
            [EsportsAggregationTests.row(
                1,
                EsportsAggregationTests.NOW - 86400,
            )],
            [10],
            HeroMapStub(),
            now=EsportsAggregationTests.NOW,
        )[10]
        player = {
            "name": "Player",
            "steam32": 10,
            "mmr": 2000,
            "signup_mmr": 2000,
        }
        metrics = build_metrics(player, {"esports": history}, HeroMapStub())
        self.assertEqual(metrics["esports_status"], "fresh")
        self.assertEqual(metrics["esports_games"], 1)
        self.assertEqual(metrics["esports_6mo_games"], 1)
        self.assertEqual(metrics["esports_6mo_winrate"], 100.0)
        self.assertEqual(metrics["esports_recent_mode"], "six_months")
        self.assertEqual(len(metrics["esports_leagues"]), 1)
```

- [ ] **Step 2: Run the analysis test and verify missing keys**

Run:

```powershell
python -m unittest tests.test_esports.AnalysisIntegrationTests -v
```

Expected: fail with `KeyError: 'esports_status'`.

- [ ] **Step 3: Add ticketed defaults and copy the history**

Add these defaults inside the `d` dictionary in `build_metrics`:

```python
"esports_status": "unavailable",
"esports_incomplete": False,
"esports_games": 0,
"esports_wins": 0,
"esports_losses": 0,
"esports_winrate": None,
"esports_league_count": 0,
"esports_first": None,
"esports_latest": None,
"esports_6mo_games": 0,
"esports_6mo_wins": 0,
"esports_6mo_losses": 0,
"esports_6mo_winrate": None,
"esports_leagues": [],
"esports_recent_matches": [],
"esports_recent_mode": "none",
```

Before `return d`, copy a valid history:

```python
esports = sections.get("esports")
if isinstance(esports, dict):
    recent = esports.get("six_month") or {}
    d.update({
        "esports_status": esports.get("status", "unavailable"),
        "esports_incomplete": bool(esports.get("incomplete")),
        "esports_games": esports.get("games", 0),
        "esports_wins": esports.get("wins", 0),
        "esports_losses": esports.get("losses", 0),
        "esports_winrate": esports.get("winrate"),
        "esports_league_count": esports.get("league_count", 0),
        "esports_first": esports.get("first"),
        "esports_latest": esports.get("latest"),
        "esports_6mo_games": recent.get("games", 0),
        "esports_6mo_wins": recent.get("wins", 0),
        "esports_6mo_losses": recent.get("losses", 0),
        "esports_6mo_winrate": recent.get("winrate"),
        "esports_leagues": list(esports.get("leagues") or []),
        "esports_recent_matches": list(esports.get("recent_matches") or []),
        "esports_recent_mode": esports.get("recent_mode", "none"),
    })
```

- [ ] **Step 4: Load one history map in the CLI**

Add the import:

```python
from .esports import load_ticketed_histories
```

After `hero_map = load_hero_map(...)`, load the pool:

```python
ticketed = load_ticketed_histories(
    od,
    cache,
    args.season,
    [player["steam32"] for player in players],
    hero_map,
    offline=args.offline,
    force=args.force_refresh,
)
```

Inside the player loop, attach the record before analysis:

```python
sections["esports"] = ticketed[player["steam32"]]
data = build_metrics(player, sections, hero_map)
```

Rename the console quick-stat label so it does not call the inferred heuristic
verified league data:

```python
print(f"  With organized/inhouse games (6mo): {league_exp}")
```

- [ ] **Step 5: Run focused and full regression tests**

Run:

```powershell
python -m unittest tests.test_esports.AnalysisIntegrationTests -v
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: the focused test and the existing regression suite pass.

- [ ] **Step 6: Commit analysis wiring**

```powershell
git add scout/analysis.py scout/cli.py tests/test_esports.py
git commit -m "Wire ticketed history into scouting metrics"
```

---

### Task 5: Dashboard Six-Month Win-Rate Column

**Files:**
- Modify: `scout/report_html.py:72-148`
- Modify: `scout/report_html.py:1131-1162`
- Modify: `scout/report_html.py:1190-1205`
- Modify: `scout/report_html.py:1305-1342`
- Modify: `scout/report_html.py:1690-1712`
- Modify: `tests/test_esports.py`

**Interfaces:**
- Consumes:
  - `d["esports_status"]`
  - `d["esports_6mo_games"]`
  - `d["esports_6mo_winrate"]`
- Produces dashboard record keys:
  - `esportsStatus: str`
  - `esports6moGames: int`
  - `esports6moWr: float | null`

- [ ] **Step 1: Add failing dashboard-record tests**

```python
# tests/test_esports.py
from scout import report_html


class DashboardEsportsTests(unittest.TestCase):
    def test_player_record_exposes_only_six_month_ticketed_fields(self):
        player = {
            "name": "Player",
            "steam32": 10,
            "steam64": 76561197960265738,
            "mmr": 2000,
            "captain": "N",
            "draftable": "Y",
            "vouched": "N",
            "statement": "",
        }
        data = build_metrics(
            player,
            {
                "esports": {
                    **unavailable_history(),
                    "status": "fresh",
                    "six_month": {
                        "games": 9,
                        "wins": 5,
                        "losses": 4,
                        "winrate": 55.6,
                    },
                }
            },
            HeroMapStub(),
        )
        record = report_html._player_record({"player": player, "data": data})
        self.assertEqual(record["esportsStatus"], "fresh")
        self.assertEqual(record["esports6moGames"], 9)
        self.assertEqual(record["esports6moWr"], 55.6)
        self.assertNotIn("leagueN", record)

    def test_template_has_no_esports_filter_or_badge(self):
        self.assertIn('t:"Esports 6mo WR"', report_html.TEMPLATE)
        self.assertNotIn('id="fesports"', report_html.TEMPLATE)
        self.assertNotIn("b-esports", report_html.TEMPLATE)
```

- [ ] **Step 2: Run the dashboard tests and verify failure**

Run:

```powershell
python -m unittest tests.test_esports.DashboardEsportsTests -v
```

Expected: fail because `esportsStatus` is missing and the template still says
`League`.

- [ ] **Step 3: Replace the dashboard record fields**

In `_player_record`, replace `leagueN`, `leagueWr`, and `leagueHeroes` with:

```python
"esportsStatus": d["esports_status"],
"esports6moGames": d["esports_6mo_games"],
"esports6moWr": d["esports_6mo_winrate"],
```

- [ ] **Step 4: Add sorting and cell rendering helpers**

Add beside the other JavaScript cell helpers:

```javascript
function esportsSort(p){
  if (p.esports6moWr == null || !p.esports6moGames) return -1;
  return p.esports6moWr * 100000 + Math.min(p.esports6moGames, 99999);
}

function esportsCell(p){
  if (p.esportsStatus === "unavailable")
    return '<span class="dim" title="Ticketed OpenDota history unavailable for this run">—</span>';
  if (p.esports6moWr == null || !p.esports6moGames)
    return '<span class="dim" title="No ticketed matches in the last six months">—</span>';
  return `${p.esports6moWr}% <span class="dim">(${p.esports6moGames}g)</span>`;
}
```

Replace the `COLS` entry:

```javascript
{k:"esports6moWr",t:"Esports 6mo WR",num:true,sort:esportsSort,
 d:"Win rate in verified OpenDota ticketed matches during the last six months. Games in parentheses; — = no ticketed matches or unavailable history"},
```

Replace the matching `rowHtml` cell:

```javascript
<td class="num">${esportsCell(p)}</td>
```

Replace the compare-tray row:

```javascript
["Esports 6mo WR", p=>p.esports6moWr==null||!p.esports6moGames
  ?"—":`${p.esports6moWr}% (${p.esports6moGames}g)`],
```

- [ ] **Step 5: Run dashboard and regression tests**

Run:

```powershell
python -m unittest tests.test_esports.DashboardEsportsTests -v
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the dashboard column**

```powershell
git add scout/report_html.py tests/test_esports.py
git commit -m "Show ticketed six-month win rate"
```

---

### Task 6: Detailed Player Esports History

**Files:**
- Modify: `scout/report_player_html.py:1-470`
- Modify: `scout/report_player_html.py:571-613`
- Modify: `tests/test_esports.py`

**Interfaces:**
- Consumes the `esports_*` metrics from Task 4.
- Produces `_esports_card(d: dict) -> str`.

- [ ] **Step 1: Add failing report-card tests**

```python
# tests/test_esports.py
from scout.report_player_html import _esports_card


class PlayerReportEsportsTests(unittest.TestCase):
    def data(self):
        return {
            "esports_status": "fresh",
            "esports_incomplete": False,
            "esports_games": 2,
            "esports_wins": 1,
            "esports_losses": 1,
            "esports_winrate": 50.0,
            "esports_league_count": 1,
            "esports_first": 1700000000,
            "esports_latest": 1750000000,
            "esports_6mo_games": 1,
            "esports_6mo_wins": 1,
            "esports_6mo_losses": 0,
            "esports_6mo_winrate": 100.0,
            "esports_leagues": [{
                "league_id": 100,
                "name": "<League A>",
                "games": 2,
                "wins": 1,
                "losses": 1,
                "winrate": 50.0,
                "first": 1700000000,
                "latest": 1750000000,
                "heroes": [{"name": "Axe", "games": 2}],
            }],
            "esports_recent_matches": [{
                "match_id": 123,
                "start_time": 1750000000,
                "league_id": 100,
                "league_name": "<League A>",
                "hero": "Axe",
                "result": "W",
                "kills": 4,
                "deaths": 2,
                "assists": 10,
                "gpm": 500,
                "xpm": 600,
            }],
            "esports_recent_mode": "six_months",
        }

    def test_card_renders_summary_leagues_matches_and_safe_text(self):
        html = _esports_card(self.data())
        self.assertIn("Esports history", html)
        self.assertIn("1–1", html)
        self.assertIn("&lt;League A&gt;", html)
        self.assertIn("4/2/10", html)
        self.assertIn("https://www.opendota.com/matches/123", html)

    def test_card_distinguishes_zero_from_unavailable(self):
        zero = self.data()
        zero.update({
            "esports_games": 0,
            "esports_leagues": [],
            "esports_recent_matches": [],
            "esports_recent_mode": "none",
        })
        self.assertIn("No ticketed OpenDota matches found", _esports_card(zero))
        zero["esports_status"] = "unavailable"
        self.assertIn("unavailable for this run", _esports_card(zero))

    def test_card_labels_latest_leagues_fallback(self):
        data = self.data()
        data["esports_recent_mode"] = "latest_leagues"
        data["esports_6mo_games"] = 0
        self.assertIn("three most recent leagues", _esports_card(data))
```

- [ ] **Step 2: Run the report tests and verify import failure**

Run:

```powershell
python -m unittest tests.test_esports.PlayerReportEsportsTests -v
```

Expected: import fails because `_esports_card` is undefined.

- [ ] **Step 3: Add date, number, and row helpers**

```python
# scout/report_player_html.py imports
from datetime import datetime, timezone


def _date(unix_ts):
    if not unix_ts:
        return "—"
    return datetime.fromtimestamp(
        int(unix_ts), tz=timezone.utc
    ).strftime("%Y-%m-%d")


def _stat(value):
    return "—" if value is None else str(value)


def _league_row(league):
    heroes = ", ".join(
        f"{E(str(hero['name']))} ({hero['games']}g)"
        for hero in league.get("heroes", [])
    ) or "—"
    wr = "—" if league.get("winrate") is None else f"{league['winrate']}%"
    return (
        "<tr>"
        f"<td>{E(str(league['name']))}</td>"
        f"<td class=\"num\">{league['wins']}–{league['losses']} "
        f"<span class=\"dim\">({wr}, {league['games']}g)</span></td>"
        f"<td>{_date(league.get('first'))} to {_date(league.get('latest'))}</td>"
        f"<td>{heroes}</td>"
        "</tr>"
    )


def _match_row(match):
    kda = "/".join(_stat(match.get(key))
                   for key in ("kills", "deaths", "assists"))
    match_id = int(match["match_id"])
    return (
        "<tr>"
        f"<td>{_date(match.get('start_time'))}</td>"
        f"<td>{E(str(match.get('league_name') or 'Unknown league'))}</td>"
        f"<td>{E(str(match.get('hero') or 'Unknown'))}</td>"
        f"<td class=\"num\">{E(str(match.get('result') or '?'))}</td>"
        f"<td class=\"num\">{kda}</td>"
        f"<td class=\"num\">{_stat(match.get('gpm'))}</td>"
        f"<td class=\"num\">{_stat(match.get('xpm'))}</td>"
        f"<td><a href=\"https://www.opendota.com/matches/{match_id}\">OD</a></td>"
        "</tr>"
    )
```

- [ ] **Step 4: Implement the complete card**

```python
def _esports_card(d):
    status = d.get("esports_status", "unavailable")
    if status == "unavailable":
        return (
            '<div class="card wide"><h2>Esports history</h2>'
            '<p class="dim">Esports history unavailable for this run.</p></div>'
        )
    if not d.get("esports_games"):
        return (
            '<div class="card wide"><h2>Esports history</h2>'
            '<p class="dim">No ticketed OpenDota matches found.</p></div>'
        )

    incomplete = (
        '<div class="verdict warn">History reached the 10,000-row pool cap; '
        'career totals may be incomplete.</div>'
        if d.get("esports_incomplete") else ""
    )
    six_wr = (f"{d['esports_6mo_winrate']}%"
              if d.get("esports_6mo_winrate") is not None else "—")
    summary = (
        '<div class="es-summary">'
        f'<span><b>{d["esports_games"]}</b><small>career games</small></span>'
        f'<span><b>{d["esports_wins"]}–{d["esports_losses"]}</b>'
        f'<small>{d["esports_winrate"]}% career</small></span>'
        f'<span><b>{d["esports_league_count"]}</b><small>leagues</small></span>'
        f'<span><b>{d["esports_6mo_wins"]}–{d["esports_6mo_losses"]}</b>'
        f'<small>{six_wr} in 6mo</small></span>'
        f'<span><b>{_date(d.get("esports_first"))}</b><small>first</small></span>'
        f'<span><b>{_date(d.get("esports_latest"))}</b><small>latest</small></span>'
        '</div>'
    )
    league_rows = "".join(_league_row(league)
                          for league in d.get("esports_leagues", []))
    mode = d.get("esports_recent_mode")
    match_title = (
        "Ticketed matches, last six months"
        if mode == "six_months"
        else "Ticketed matches from three most recent leagues"
    )
    match_rows = "".join(_match_row(match)
                         for match in d.get("esports_recent_matches", []))
    return (
        '<div class="card wide esports"><h2>Esports history</h2>'
        f"{incomplete}{summary}"
        '<h3>All-time leagues</h3><div class="table-scroll">'
        '<table class="kv esports-table"><thead><tr><th>League</th>'
        '<th>Record</th><th>Dates</th><th>Top heroes</th></tr></thead>'
        f"<tbody>{league_rows}</tbody></table></div>"
        f"<h3>{E(match_title)}</h3><div class=\"table-scroll\">"
        '<table class="kv esports-table"><thead><tr><th>Date</th><th>League</th>'
        '<th>Hero</th><th>Result</th><th>K/D/A</th><th>GPM</th><th>XPM</th>'
        f"<th>Match</th></tr></thead><tbody>{match_rows}</tbody></table></div>"
        "</div>"
    )
```

Add focused CSS inside `PAGE_CSS`:

```css
.card.wide{grid-column:1/-1}
.es-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:8px;margin:10px 0 16px}
.es-summary span{background:var(--surface);border:1px solid var(--border);
  border-radius:6px;padding:9px}
.es-summary b{display:block;font:700 17px/1.2 var(--mono)}
.es-summary small{display:block;color:var(--muted);margin-top:3px}
.table-scroll{overflow-x:auto}
.esports-table{min-width:720px}
.esports h3{margin:16px 0 7px;font-size:12px;color:var(--gold)}
.esports-table th{text-align:left;color:var(--muted);font-size:10px}
```

Add the card to `_player_page` without changing the report index:

```python
body = (
    _winrate_card(d) + _east_card(d) + _heroes_card(d)
    + _lanes_card(d) + _toxicity_card(d) + _esports_card(d)
)
```

Remove the inferred `Organized/league` row from `_winrate_card`; the new card
owns every esports claim in the dossier.

- [ ] **Step 5: Run report and full regression tests**

Run:

```powershell
python -m unittest tests.test_esports.PlayerReportEsportsTests -v
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the detailed reports**

```powershell
git add scout/report_player_html.py tests/test_esports.py
git commit -m "Add ticketed history to player reports"
```

---

### Task 7: Documentation, Online Regeneration, and Final Verification

**Files:**
- Modify: `README.md:105-110`
- Modify: `README.md:270-290`
- Regenerate: `LD2L_S22_Scouting.html`
- Regenerate: `LD2L_S22_Scouting.xlsx`
- Regenerate: `scout_reports/*.html`

**Interfaces:**
- Consumes the completed ticketed-history feature.
- Produces current Season 22 reports with verified website budgets and OpenDota ticketed history.

- [ ] **Step 1: Update user-facing documentation**

Replace wording that calls the inferred Captains Mode and 10-stack sample
`League` data with:

```markdown
**Esports 6mo WR** uses verified OpenDota ticketed matches (`leagueid > 0`).
The dashboard shows win rate and sample size for the last six months. Each
player's 🔍 scouting report includes their all-time per-league record and recent
ticketed matches. The scout fetches the signup pool with one cached OpenDota
Explorer query.

The separate organized/inhouse signal still recognizes Captains Mode and full
10-stack lobbies for internal scouting analysis. It does not claim those
matches were ticketed leagues.
```

- [ ] **Step 2: Run syntax and full test verification**

Run:

```powershell
python -m compileall -q scout ld2l_scout.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: compile command exits 0 and every test passes.

- [ ] **Step 3: Run the online scout once**

Run:

```powershell
python ld2l_scout.py
```

Expected:

- one ticketed-history Explorer request on a cold cache
- team budgets printed from `ld2l.org`
- dashboard, workbook, and player reports generated
- command exits 0

- [ ] **Step 4: Verify the generated artifacts**

Run:

```powershell
rg -n -m 1 "Esports 6mo WR" LD2L_S22_Scouting.html
rg -n -m 1 "Esports history" scout_reports
rg -n "fesports|b-esports" LD2L_S22_Scouting.html
Get-Item LD2L_S22_Scouting.html, LD2L_S22_Scouting.xlsx, scout_reports\index.html |
  Select-Object Name,Length,LastWriteTime
```

Expected:

- dashboard contains `Esports 6mo WR`
- player reports contain `Esports history`
- the filter and badge search returns no matches
- artifact timestamps match the final run

- [ ] **Step 5: Inspect one populated and one empty player report**

Open one report containing a ticketed league table and one report containing
`No ticketed OpenDota matches found`. Check desktop and narrow widths:

- tables scroll horizontally instead of overflowing the dossier
- league names and heroes remain readable
- match links open the matching OpenDota match ID
- the dashboard column shows `% (Ng)` for populated records and an em dash for
  empty records

- [ ] **Step 6: Commit documentation and regenerated artifacts**

Stage only the files owned by this feature:

```powershell
git add README.md LD2L_S22_Scouting.html LD2L_S22_Scouting.xlsx scout_reports
git commit -m "Document and regenerate ticketed scouting reports"
```

- [ ] **Step 7: Run final verification from the committed state**

Run:

```powershell
git status --short
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: the pre-existing unrelated working changes remain visible, no
ticketed-history implementation file remains unstaged, and every test passes.
