import importlib.util
from importlib.machinery import ModuleSpec
import sys
import tempfile
import types
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock


try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = types.ModuleType("requests")


from scout.cache import Cache
from scout.analysis import build_metrics
from scout.opendota import OpenDota
from scout.esports import (
    aggregate_histories,
    build_query,
    load_ticketed_histories,
    unavailable_history,
)


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


class HeroMapStub:
    NAMES = {1: "Axe", 2: "Bane"}

    def name(self, hero_id):
        return self.NAMES.get(int(hero_id), f"Hero {hero_id}")


class ExplorerStub:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def explorer(self, sql):
        self.queries.append(sql)
        return self.rows


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
        self.assertEqual(
            (history["games"], history["wins"], history["losses"]),
            (2, 1, 1),
        )
        self.assertEqual(history["league_count"], 2)
        self.assertEqual(
            history["six_month"],
            {"games": 1, "wins": 1, "losses": 0, "winrate": 100.0},
        )
        self.assertEqual(history["recent_mode"], "six_months")
        self.assertEqual(history["recent_matches"][0]["hero"], "Axe")
        self.assertEqual(
            [item["name"] for item in history["leagues"]],
            ["League A", "League B"],
        )

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
            {match["league_name"] for match in history["recent_matches"]},
            {"Newest", "Second", "Third"},
        )
        self.assertEqual(history["recent_matches"][0]["result"], "W")

    def test_zero_history_is_distinct_from_unavailable(self):
        history = aggregate_histories([], [10], HeroMapStub(), now=self.NOW)[10]
        self.assertEqual(history["status"], "fresh")
        self.assertEqual(history["games"], 0)
        self.assertEqual(history["recent_mode"], "none")
        self.assertEqual(unavailable_history()["status"], "unavailable")

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


class EsportsCacheTests(unittest.TestCase):
    NOW = EsportsAggregationTests.NOW

    @staticmethod
    def row(account_id=10, match_id=1):
        row = EsportsAggregationTests.row(
            match_id,
            EsportsAggregationTests.NOW - 86400,
        )
        row["account_id"] = account_id
        return row

    def test_complete_fresh_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob(
                "ticketed_history_s53_v1",
                {"player_ids": [10], "rows": [self.row()], "incomplete": False},
            )
            od = ExplorerStub(None)
            result = load_ticketed_histories(
                od, cache, 53, [10], HeroMapStub(), now=self.NOW,
            )
        self.assertEqual(od.queries, [])
        self.assertEqual(result[10]["status"], "fresh")
        self.assertEqual(result[10]["games"], 1)

    def test_roster_growth_forces_one_pool_query(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob(
                "ticketed_history_s53_v1",
                {"player_ids": [10], "rows": [self.row()], "incomplete": False},
            )
            od = ExplorerStub([self.row(10), self.row(20, 2)])
            result = load_ticketed_histories(
                od, cache, 53, [10, 20], HeroMapStub(), now=self.NOW,
            )
        self.assertEqual(len(od.queries), 1)
        self.assertEqual(result[20]["status"], "fresh")
        self.assertEqual(result[20]["games"], 1)

    def test_failed_forced_query_uses_stale_cache(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob(
                "ticketed_history_s53_v1",
                {"player_ids": [10], "rows": [self.row()], "incomplete": False},
            )
            od = ExplorerStub(None)
            result = load_ticketed_histories(
                od,
                cache,
                53,
                [10],
                HeroMapStub(),
                force=True,
                now=self.NOW,
            )
        self.assertEqual(len(od.queries), 1)
        self.assertEqual(result[10]["status"], "stale")
        self.assertEqual(result[10]["games"], 1)

    def test_offline_without_cache_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            result = load_ticketed_histories(
                ExplorerStub([]),
                Cache(root),
                53,
                [10],
                HeroMapStub(),
                offline=True,
                now=self.NOW,
            )
        self.assertEqual(result[10], unavailable_history())

    def test_malformed_matching_cache_is_not_treated_as_zero_history(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob(
                "ticketed_history_s53_v1",
                {"player_ids": [10], "rows": None, "incomplete": False},
            )
            od = ExplorerStub([self.row()])
            result = load_ticketed_histories(
                od, cache, 53, [10], HeroMapStub(), now=self.NOW,
            )
        self.assertEqual(len(od.queries), 1)
        self.assertEqual(result[10]["status"], "fresh")
        self.assertEqual(result[10]["games"], 1)

    def test_offline_malformed_cache_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_blob("ticketed_history_s53_v1", "broken")
            result = load_ticketed_histories(
                ExplorerStub([]),
                cache,
                53,
                [10],
                HeroMapStub(),
                offline=True,
                now=self.NOW,
            )
        self.assertEqual(result[10], unavailable_history())


class EsportsMetricsTests(unittest.TestCase):
    def test_build_metrics_exposes_ticketed_history_fields(self):
        history = aggregate_histories(
            [EsportsCacheTests.row()],
            [10],
            HeroMapStub(),
            now=EsportsAggregationTests.NOW,
        )[10]
        metrics = build_metrics(
            {"steam32": 10, "mmr": 3000},
            {"esports": history},
            HeroMapStub(),
        )
        self.assertEqual(metrics["esports_status"], "fresh")
        self.assertEqual(metrics["esports_games"], 1)
        self.assertEqual(metrics["esports_6mo_games"], 1)
        self.assertEqual(metrics["esports_6mo_winrate"], 100.0)
        self.assertEqual(metrics["esports_leagues"][0]["name"], "League A")
        self.assertEqual(
            metrics["esports_recent_matches"][0]["match_id"],
            1,
        )

    def test_build_metrics_defaults_to_unavailable_ticketed_history(self):
        metrics = build_metrics(
            {"steam32": 10, "mmr": 3000},
            {},
            HeroMapStub(),
        )
        self.assertEqual(metrics["esports_status"], "unavailable")
        self.assertIsNone(metrics["esports_6mo_winrate"])
        self.assertEqual(metrics["esports_recent_matches"], [])


class EsportsDashboardTests(unittest.TestCase):
    @staticmethod
    def report_html():
        if (
            "openpyxl" not in sys.modules
            and importlib.util.find_spec("openpyxl") is None
        ):
            openpyxl = types.ModuleType("openpyxl")
            styles = types.ModuleType("openpyxl.styles")
            utils = types.ModuleType("openpyxl.utils")
            openpyxl.__spec__ = ModuleSpec("openpyxl", loader=None)
            styles.__spec__ = ModuleSpec("openpyxl.styles", loader=None)
            utils.__spec__ = ModuleSpec("openpyxl.utils", loader=None)

            class Placeholder:
                def __init__(self, *args, **kwargs):
                    pass

            openpyxl.Workbook = Placeholder
            for name in ("Alignment", "Border", "Font", "PatternFill", "Side"):
                setattr(styles, name, Placeholder)
            utils.get_column_letter = lambda value: str(value)
            sys.modules["openpyxl"] = openpyxl
            sys.modules["openpyxl.styles"] = styles
            sys.modules["openpyxl.utils"] = utils
        from scout import report_html
        return report_html

    @staticmethod
    def player():
        return {
            "name": "Ticket Tester",
            "steam32": 10,
            "steam64": 76561197960265738,
            "mmr": 3000,
            "captain": "N",
            "draftable": "Y",
            "vouched": "N",
            "statement": "",
        }

    def player_data(self):
        history = aggregate_histories(
            [EsportsCacheTests.row()],
            [10],
            HeroMapStub(),
            now=EsportsAggregationTests.NOW,
        )[10]
        return {
            "player": self.player(),
            "data": build_metrics(
                self.player(),
                {"esports": history},
                HeroMapStub(),
            ),
        }

    def test_player_record_contains_six_month_ticketed_winrate(self):
        record = self.report_html()._player_record(self.player_data())
        self.assertEqual(record["esportsStatus"], "fresh")
        self.assertEqual(record["esports6moGames"], 1)
        self.assertEqual(record["esports6moWr"], 100.0)
        self.assertNotIn("leagueN", record)

    def test_generated_dashboard_has_one_esports_column_and_no_filter(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "dashboard.html"
            self.report_html().generate_dashboard(
                [self.player_data()],
                str(output),
                "S22",
                53,
                offline=True,
            )
            html = output.read_text(encoding="utf-8")
        self.assertIn("Esports 6mo WR", html)
        self.assertIn('"esports6moGames": 1', html)
        self.assertIn("function esportsSort(p)", html)
        self.assertIn("sort:esportsSort", html)
        self.assertIn("No ticketed matches in the last six months", html)
        self.assertIn("Ticketed OpenDota history unavailable", html)
        self.assertNotIn('id="fesports"', html)
        self.assertNotIn("b-esports", html)


class EsportsPlayerReportTests(unittest.TestCase):
    @staticmethod
    def report_module():
        EsportsDashboardTests.report_html()
        from scout import report_player_html
        return report_player_html

    def metrics(self, rows):
        history = aggregate_histories(
            rows,
            [10],
            HeroMapStub(),
            now=EsportsAggregationTests.NOW,
        )[10]
        return build_metrics(
            {"steam32": 10, "mmr": 3000},
            {"esports": history},
            HeroMapStub(),
        )

    def test_card_shows_career_leagues_and_recent_match_details(self):
        html = self.report_module()._esports_card(
            self.metrics([EsportsCacheTests.row()])
        )
        self.assertIn("Ticketed esports history", html)
        self.assertIn("Career", html)
        self.assertIn("League A", html)
        self.assertIn("<th>Games</th>", html)
        self.assertIn("1–0", html)
        self.assertIn("100.0%", html)
        self.assertIn("Last 6 months", html)
        self.assertIn("Axe", html)
        self.assertIn("4/2/10", html)
        self.assertIn(
            'href="https://www.opendota.com/matches/1"',
            html,
        )

    def test_card_labels_three_latest_leagues_fallback(self):
        old = EsportsAggregationTests.row(
            7,
            EsportsAggregationTests.NOW - 400 * 86400,
        )
        html = self.report_module()._esports_card(self.metrics([old]))
        self.assertIn(
            "No ticketed matches in the last 6 months; showing matches "
            "from the 3 most recent leagues.",
            html,
        )

    def test_card_distinguishes_zero_history_from_unavailable(self):
        report = self.report_module()
        zero = report._esports_card(self.metrics([]))
        missing_metrics = self.metrics([])
        missing_metrics["esports_status"] = "unavailable"
        unavailable = report._esports_card(missing_metrics)
        self.assertIn("No ticketed matches found", zero)
        self.assertIn("Ticketed history unavailable", unavailable)

    def test_card_escapes_league_names_and_drops_inferred_league_row(self):
        row = EsportsAggregationTests.row(
            1,
            EsportsAggregationTests.NOW - 86400,
            league_name="<script>alert(1)</script>",
        )
        report = self.report_module()
        metrics = self.metrics([row])
        html = report._esports_card(metrics)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("Organized/league", report._winrate_card(metrics))


if __name__ == "__main__":
    unittest.main()
