import time
import unittest
import tempfile
from pathlib import Path

from scout.analysis import build_metrics
from scout.heroes import HERO_FALLBACK, HeroMap


HERO_MAP = HeroMap(HERO_FALLBACK)


def player(name="Test Player", steam32=10, mmr=3000):
    return {
        "name": name,
        "steam32": steam32,
        "steam64": 76561197960265728 + steam32,
        "mmr": mmr,
        "captain": "N",
        "draftable": "Y",
        "vouched": "N",
        "statement": "",
    }


def raw_match(**overrides):
    match = {
        "match_id": 100,
        "start_time": int(time.time()) - 86400,
        "duration": 1800,
        "player_slot": 0,
        "radiant_win": True,
        "hero_id": 80,
        "lane": 1,
        "lane_role": 1,
        "is_roaming": False,
        "version": 22,
        "lane_efficiency_pct": 60,
        "purchase_ward_observer": 2,
        "purchase_ward_sentry": 4,
        "average_rank": 45,
        "party_size": 1,
        "lobby_type": 7,
        "game_mode": 22,
        "kills": 5,
        "deaths": 3,
        "assists": 8,
        "gold_per_min": 500,
        "xp_per_min": 600,
        "cluster": 122,
    }
    match.update(overrides)
    return match


def deep_sample(**overrides):
    sample = {
        "match_id": 100,
        "start_time": int(time.time()) - 86400,
        "duration": 1800,
        "parsed": True,
        "player_slot": 0,
        "lane": 1,
        "lane_role": 1,
        "is_roaming": False,
        "gold10": 3000,
        "xp10": 2800,
        "ally_lane_gold10": 5200,
        "enemy_lane_gold10": 4500,
        "ally_lane_xp10": 4900,
        "enemy_lane_xp10": 4100,
        "observer_kills": 2,
        "sentry_kills": 3,
    }
    sample.update(overrides)
    return sample


class ProjectionAndRawMetricTests(unittest.TestCase):
    def test_projection_contains_deep_proxy_fields_and_version_is_bumped(self):
        from scout.fetch import MATCHES_SECTION, MATCH_PROJECTION

        for field in (
            "version",
            "lane",
            "lane_efficiency_pct",
            "is_roaming",
            "purchase_ward_observer",
            "purchase_ward_sentry",
        ):
            self.assertIn(field, MATCH_PROJECTION)
        self.assertEqual(MATCHES_SECTION, "matches_v4")

    def test_build_metrics_normalizes_lane_efficiency_and_vision_per_30(self):
        metrics = build_metrics(
            player(),
            {"matches": [raw_match()], "deep": [deep_sample()]},
            HERO_MAP,
        )
        self.assertEqual(metrics["lane_eff_n"], 1)
        self.assertEqual(metrics["lane_eff_median"], 60)
        self.assertEqual(metrics["vision_n"], 1)
        self.assertEqual(metrics["observer_per30"], 2.0)
        self.assertEqual(metrics["sentry_per30"], 4.0)
        self.assertEqual(metrics["deep_samples"][0]["observer_kills"], 2)

    def test_roaming_and_unparsed_rows_do_not_enter_lane_efficiency(self):
        metrics = build_metrics(
            player(),
            {
                "matches": [
                    raw_match(is_roaming=True, lane_efficiency_pct=80),
                    raw_match(match_id=101, version=None, lane_efficiency_pct=None),
                ],
            },
            HERO_MAP,
        )
        self.assertEqual(metrics["lane_eff_n"], 0)
        self.assertIsNone(metrics["lane_eff_median"])

    def test_requested_hero_matrix_has_lifetime_recent_and_ticketed_evidence(self):
        esports = {
            "status": "fresh",
            "games": 3,
            "wins": 2,
            "losses": 1,
            "winrate": 66.7,
            "league_count": 1,
            "six_month": {"games": 3, "wins": 2, "losses": 1, "winrate": 66.7},
            "leagues": [],
            "recent_matches": [],
            "recent_mode": "none",
            "hero_stats": {
                "Lone Druid": {"games": 2, "wins": 2},
            },
        }
        metrics = build_metrics(
            player(),
            {
                "heroes": [{"hero_id": "80", "games": 30, "win": 18}],
                "matches": [
                    raw_match(match_id=100, hero_id=80),
                    raw_match(match_id=101, hero_id=80),
                    raw_match(match_id=102, hero_id=80),
                ],
                "esports": esports,
            },
            HERO_MAP,
        )
        lone_druid = next(
            row for row in metrics["requested_heroes"]
            if row["hero"] == "Lone Druid"
        )
        self.assertEqual(lone_druid["lifetime_games"], 30)
        self.assertEqual(lone_druid["recent_games"], 3)
        self.assertEqual(lone_druid["ticketed_games"], 2)
        self.assertEqual(lone_druid["label"], "Proven")
        self.assertEqual(len(metrics["requested_heroes"]), 10)


class StatisticalEvidenceTests(unittest.TestCase):
    def test_beta_posterior_shrinks_small_samples_to_even(self):
        from scout.analysis import beta_posterior_rate

        self.assertAlmostEqual(beta_posterior_rate(1, 1), 54.5, places=1)
        self.assertAlmostEqual(beta_posterior_rate(60, 100), 59.1, places=1)

    def test_league_proof_requires_sample_and_multiple_leagues(self):
        from scout.analysis import league_proof

        proven = league_proof({
            "esports_status": "fresh",
            "esports_games": 40,
            "esports_wins": 27,
            "esports_league_count": 3,
        })
        limited = league_proof({
            "esports_status": "fresh",
            "esports_games": 4,
            "esports_wins": 4,
            "esports_league_count": 1,
        })
        self.assertEqual(proven["label"], "Proven winner")
        self.assertEqual(limited["label"], "Limited sample")
        self.assertLess(limited["posterior_wr"], 65)

    def test_exact_lane_result_uses_combined_gold_and_xp_with_draw_band(self):
        from scout.analysis import exact_lane_result

        self.assertEqual(exact_lane_result(deep_sample(), 0.6), "win")
        self.assertEqual(
            exact_lane_result(
                deep_sample(
                    ally_lane_gold10=5000,
                    enemy_lane_gold10=4900,
                    ally_lane_xp10=5000,
                    enemy_lane_xp10=5000,
                ),
                0.6,
            ),
            "draw",
        )
        self.assertIsNone(
            exact_lane_result(deep_sample(ally_lane_gold10=None), 0.6)
        )

    def test_role_fit_only_calls_close_credible_positions_versatile(self):
        from scout.analysis import role_fit

        ratings = {
            "primary": 4,
            "ratings": {
                1: {"mmr": 2800, "conf": "est"},
                2: {"mmr": 2750, "conf": "est"},
                3: {"mmr": 2825, "conf": "est"},
                4: {"mmr": 3200, "conf": "measured"},
                5: {"mmr": 3110, "conf": "part-time"},
            },
        }
        fit = role_fit({}, ratings=ratings)
        self.assertEqual(fit["best"], 4)
        self.assertEqual(fit["secondary"], [5])
        self.assertEqual(fit["label"], "Versatile")

    def test_role_fit_does_not_turn_broad_part_time_guesses_into_versatility(self):
        from scout.analysis import role_fit

        ratings = {
            "primary": 4,
            "ratings": {
                1: {"mmr": 3060, "conf": "part-time"},
                2: {"mmr": 3050, "conf": "part-time"},
                3: {"mmr": 3040, "conf": "part-time"},
                4: {"mmr": 3200, "conf": "measured"},
                5: {"mmr": 3110, "conf": "part-time"},
            },
        }
        fit = role_fit({}, ratings=ratings)
        self.assertEqual(fit["secondary"], [5])
        self.assertEqual(fit["credible"], [4, 5])

    def test_role_fit_without_credible_position_is_unclear(self):
        from scout.analysis import role_fit

        ratings = {
            "primary": None,
            "ratings": {
                pos: {"mmr": 3000 + pos, "conf": "est"}
                for pos in range(1, 6)
            },
        }
        fit = role_fit({}, ratings=ratings)
        self.assertEqual(
            fit,
            {"best": None, "secondary": [], "credible": [], "label": "Unclear"},
        )

    def test_tied_percentiles_share_the_same_average_rank(self):
        from scout.analysis import _percentile_scores

        scores = _percentile_scores([10, 10, 20, None])
        self.assertEqual(scores[0], 25.0)
        self.assertEqual(scores[1], 25.0)
        self.assertEqual(scores[2], 100.0)

    def test_pool_pass_finalizes_exact_lane_and_deward_rates(self):
        from scout.analysis import _finalize_deep_and_role_metrics

        metrics = build_metrics(
            player(),
            {"matches": [raw_match()], "deep": [deep_sample()]},
            HERO_MAP,
        )
        _finalize_deep_and_role_metrics([
            {"player": player(), "data": metrics},
        ])
        self.assertEqual(metrics["lane_win_n"], 1)
        self.assertEqual(metrics["lane_win_pct"], 100.0)
        self.assertEqual(metrics["deward_n"], 1)
        self.assertEqual(metrics["observer_kills_per30"], 2.0)
        self.assertEqual(metrics["sentry_kills_per30"], 3.0)

    def test_lane_win_percentage_includes_draws_in_its_sample(self):
        from scout.analysis import _finalize_deep_and_role_metrics

        metrics = build_metrics(
            player(),
            {
                "matches": [raw_match()],
                "deep": [
                    deep_sample(match_id=1),
                    deep_sample(
                        match_id=2,
                        ally_lane_gold10=5000,
                        enemy_lane_gold10=4900,
                        ally_lane_xp10=5000,
                        enemy_lane_xp10=5000,
                    ),
                ],
            },
            HERO_MAP,
        )
        _finalize_deep_and_role_metrics([
            {"player": player(), "data": metrics},
        ])

        self.assertEqual(metrics["lane_win_n"], 2)
        self.assertEqual(metrics["lane_win_pct"], 50.0)
        self.assertEqual(metrics["lane_draw_pct"], 50.0)
        self.assertEqual(metrics["lane_score_pct"], 75.0)
        self.assertEqual(metrics["dewards_per30"], 5.0)

    def test_pool_pass_counts_lane_losses_without_pluralization_drift(self):
        from scout.analysis import _finalize_deep_and_role_metrics

        losing = deep_sample(
            ally_lane_gold10=4000,
            enemy_lane_gold10=5200,
            ally_lane_xp10=3900,
            enemy_lane_xp10=5000,
        )
        metrics = build_metrics(
            player(),
            {"matches": [raw_match()], "deep": [losing]},
            HERO_MAP,
        )
        _finalize_deep_and_role_metrics([
            {"player": player(), "data": metrics},
        ])
        self.assertEqual(metrics["lane_losses"], 1)
        self.assertEqual(metrics["lane_results_by_lane"]["Safe"]["losses"], 1)


class DraftValueScoreTests(unittest.TestCase):
    @staticmethod
    def pd(name, edge, league=None, lane=None):
        data = {
            "edge_cost": edge,
            "value_gap": edge * 10 if edge is not None else None,
            "listed_suspect": False,
            "esports_status": "fresh",
            "esports_games": 0,
            "esports_wins": 0,
            "esports_league_count": 0,
            "lane_win_pct": lane,
            "lane_decided_n": 10 if lane is not None else 0,
            "role_fit": {"best": 1, "secondary": [], "label": "Specialist"},
            "vision_score": None,
            "requested_heroes": [],
        }
        if league:
            data.update(league)
        return {"player": player(name=name), "data": data}

    def test_auction_edge_dominates_and_missing_channels_are_neutral(self):
        from scout.analysis import score_draft_values

        pool = [
            self.pd("Big Edge", 80),
            self.pd("Small Edge", 10, lane=80),
            self.pd("No Price", None),
        ]
        score_draft_values(pool)
        self.assertGreater(
            pool[0]["data"]["draft_value_score"],
            pool[1]["data"]["draft_value_score"],
        )
        self.assertEqual(pool[2]["data"]["draft_value_channels"]["league"], 50)
        self.assertEqual(pool[2]["data"]["draft_value_channels"]["lane"], 50)
        self.assertEqual(pool[2]["data"]["draft_value_channels"]["auction"], 50)

    def test_skill_gap_does_not_substitute_for_missing_auction_edge(self):
        from scout.analysis import score_draft_values

        missing_price = self.pd("Missing Price", None)
        missing_price["data"]["value_gap"] = 5000
        known_price = self.pd("Known Price", 10)
        score_draft_values([missing_price, known_price])

        self.assertEqual(
            missing_price["data"]["draft_value_channels"]["auction"],
            50,
        )
        self.assertEqual(missing_price["data"]["draft_value_confidence"], "low")

    def test_thin_vision_sample_is_shrunk_and_lowers_coverage(self):
        from scout.analysis import score_draft_values

        thin = self.pd("Thin Vision", None)
        thin["data"].update({
            "vision_score": 100,
            "vision_reliability": 0.1,
            "vision_n": 1,
            "deward_n": 0,
        })
        score_draft_values([thin])

        self.assertEqual(thin["data"]["draft_value_channels"]["vision"], 100)
        self.assertEqual(thin["data"]["draft_value_confidence"], "low")

    def test_scores_assign_stable_pool_ranks_and_confidence(self):
        from scout.analysis import score_draft_values

        pool = [
            self.pd("A", 60),
            self.pd("B", 30),
            self.pd("C", 0),
        ]
        score_draft_values(pool)
        self.assertEqual(
            [pd["data"]["draft_value_rank"] for pd in pool],
            [1, 2, 3],
        )
        self.assertIn(
            pool[0]["data"]["draft_value_confidence"],
            ("high", "medium", "low"),
        )

    def test_scores_rank_only_draftable_non_captains(self):
        from scout.analysis import score_draft_values

        available = self.pd("Available", 20)
        captain = self.pd("Captain", 100)
        captain["player"]["captain"] = "Y"
        unavailable = self.pd("Unavailable", 90)
        unavailable["player"]["draftable"] = "N"
        pool = [available, captain, unavailable]

        score_draft_values(pool)

        self.assertEqual(available["data"]["draft_value_rank"], 1)
        self.assertIsNone(captain["data"]["draft_value_rank"])
        self.assertIsNone(unavailable["data"]["draft_value_rank"])


class DraftValueReportTests(unittest.TestCase):
    def player_data(self):
        from scout.analysis import (
            _finalize_deep_and_role_metrics,
            score_draft_values,
        )

        p = player()
        metrics = build_metrics(
            p,
            {
                "profile": {"rank_tier": 45},
                "heroes": [
                    {"hero_id": "80", "games": 30, "win": 18},
                    {"hero_id": "47", "games": 10, "win": 6},
                ],
                "matches": [raw_match()],
                "deep": [deep_sample()],
            },
            HERO_MAP,
        )
        metrics["edge_cost"] = 40
        metrics["worth_cost"] = 120
        metrics["est_cost"] = 80
        pd = {"player": p, "data": metrics}
        _finalize_deep_and_role_metrics([pd])
        score_draft_values([pd])
        return pd

    @staticmethod
    def dashboard_module():
        from tests.test_esports import EsportsDashboardTests

        return EsportsDashboardTests.report_html()

    def test_dashboard_record_contains_compact_deep_scouting_fields(self):
        record = self.dashboard_module()._player_record(self.player_data())
        self.assertIn("draftValue", record)
        self.assertIn("draftRank", record)
        self.assertIn("laneWinPct", record)
        self.assertIn("dewards30", record)
        self.assertIn("bestRole", record)
        self.assertIn("requestedHeroFit", record)

    def test_generated_dashboard_has_sortable_draft_value_column(self):
        module = self.dashboard_module()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "dashboard.html"
            module.generate_dashboard(
                [self.player_data()],
                str(output),
                "S22",
                53,
                offline=True,
            )
            html = output.read_text(encoding="utf-8")
        self.assertIn("Draft Value", html)
        self.assertIn("function draftValueCell(p)", html)
        self.assertIn('"draftValue":', html)

    def test_player_report_cards_answer_every_scouting_question(self):
        from scout import report_player_html

        data = self.player_data()["data"]
        draft = report_player_html._draft_recommendation_card(data)
        lanes = report_player_html._lanes_card(data)
        vision = report_player_html._vision_card(data)
        heroes = report_player_html._requested_heroes_card(data)
        self.assertIn("Draft recommendation", draft)
        self.assertIn("Strongest evidence", draft)
        self.assertIn("Principal risks", draft)
        self.assertIn("Lane win", lanes)
        self.assertIn("match WR", lanes)
        self.assertIn("Dewards", vision)
        self.assertIn("Sentries purchased", vision)
        for name in (
            "Lone Druid",
            "Meepo",
            "Huskar",
            "Phantom Lancer",
            "Medusa",
            "Sniper",
            "Viper",
            "Witch Doctor",
            "Zeus",
            "Necrophos",
        ):
            self.assertIn(name, heroes)


if __name__ == "__main__":
    unittest.main()
