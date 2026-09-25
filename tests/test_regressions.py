import json
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock


# The production dependency is intentionally optional for these stdlib-only
# regression tests. Modules under test only resolve requests at call time.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    sys.modules["requests"] = requests_stub


from scout import config
from scout.analysis import is_organized_match
from scout.broadcast import SNAPSHOT_KEYS, SSEHub
from scout.cache import Cache
from scout.heroes import load_hero_map
from scout.herodraft import load_meta
from scout.herodraft_html import render_page
from scout.live import LiveState
from scout.mockdraft import (
    MockState,
    _ai_bid_round,
    _next_nominator,
    _resolve_sale,
    _run_open_auction,
)
from scout.user_config import load_budget_overrides, load_target_sets


class OfflineTests(unittest.TestCase):
    def test_offline_hero_map_uses_stale_cache_without_api_call(self):
        class FakeCache:
            def get_blob(self, name, max_age_hours=None):
                return None if max_age_hours is not None else {"1": "Cached Hero"}

        class NoNetwork:
            def constants_heroes(self):
                raise AssertionError("offline mode attempted an API call")

        hero_map = load_hero_map(NoNetwork(), FakeCache(), offline=True)
        self.assertEqual(hero_map.name(1), "Cached Hero")

    def test_offline_rank_icons_do_not_request_missing_files(self):
        if importlib.util.find_spec("openpyxl") is None:
            openpyxl = types.ModuleType("openpyxl")
            styles = types.ModuleType("openpyxl.styles")
            utils = types.ModuleType("openpyxl.utils")

            def style_stub(*args, **kwargs):
                return object()

            openpyxl.Workbook = object
            for name in ("Alignment", "Border", "Font", "PatternFill", "Side"):
                setattr(styles, name, style_stub)
            utils.get_column_letter = lambda n: str(n)
            sys.modules["openpyxl"] = openpyxl
            sys.modules["openpyxl.styles"] = styles
            sys.modules["openpyxl.utils"] = utils

        try:
            from scout import report_html
        except ModuleNotFoundError as e:
            self.fail(f"report module could not be imported: {e}")

        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(config, "CACHE_DIR", root):
                with mock.patch.object(
                    sys.modules["requests"],
                    "get",
                    side_effect=AssertionError("offline mode attempted an icon request"),
                    create=True,
                ):
                    self.assertEqual(report_html._rank_icon_uris(offline=True), {})


class CacheTests(unittest.TestCase):
    def test_concurrent_section_updates_do_not_lose_data(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            threads = [
                threading.Thread(
                    target=cache.set_section,
                    args=(123, f"section_{i}", {"value": i}),
                )
                for i in range(12)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            for i in range(12):
                self.assertEqual(
                    cache.get_section(123, f"section_{i}", None),
                    {"value": i},
                )

    def test_replace_retries_transient_permission_errors(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            real_replace = os.replace
            attempts = []

            def flaky_replace(src, dst):
                attempts.append((src, dst))
                if len(attempts) < 3:
                    raise PermissionError("temporarily locked")
                return real_replace(src, dst)

            with mock.patch("scout.cache.os.replace", side_effect=flaky_replace):
                with mock.patch("scout.cache.time.sleep"):
                    cache.set_blob("retry", {"ok": True})

            self.assertEqual(cache.get_blob("retry"), {"ok": True})
            self.assertEqual(len(attempts), 3)


class UserConfigTests(unittest.TestCase):
    def _write(self, root, name, value):
        path = os.path.join(root, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)
        return path

    def test_budget_file_requires_an_object_and_nonnegative_integers(self):
        with tempfile.TemporaryDirectory() as root:
            bad_shape = self._write(root, "shape.json", [])
            bad_value = self._write(root, "value.json", {"Team": None})
            negative = self._write(root, "negative.json", {"Team": -1})
            valid = self._write(root, "valid.json", {"Team": "500"})

            for path in (bad_shape, bad_value, negative):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        load_budget_overrides(path)
            self.assertEqual(load_budget_overrides(valid), {"Team": 500})

    def test_target_file_requires_lists_of_integer_ids(self):
        with tempfile.TemporaryDirectory() as root:
            bad = self._write(root, "bad.json", {"Team": None})
            valid = self._write(root, "valid.json", {"Team": ["10", 20]})
            with self.assertRaises(ValueError):
                load_target_sets(bad)
            self.assertEqual(load_target_sets(valid), {"Team": {10, 20}})


class MockAuctionTests(unittest.TestCase):
    @staticmethod
    def player(steam32=10, worth=500):
        return {
            "steam32": steam32,
            "name": f"P{steam32}",
            "mmr": 2000,
            "adj_skill": 2000,
            "worth": worth,
            "est": 100,
            "value_tier": "C",
            "base_value": worth,
            "slots": {1: 2000},
            "primary": 1,
            "is_star": False,
        }

    def state(self):
        captains = [
            {"captain": "Me", "budget": 100, "team_id": "1", "pos": [1]},
            {"captain": "Bot", "budget": 100, "team_id": "2", "pos": [2]},
        ]
        return MockState(53, "S22", [self.player()], captains, {}, "Me")

    def competitive_state(self):
        captains = [
            {"captain": "A", "budget": 500, "team_id": "1", "pos": [2]},
            {"captain": "B", "budget": 500, "team_id": "2", "pos": [3]},
            {"captain": "Me", "budget": 500, "team_id": "3", "pos": [4]},
        ]
        return MockState(
            53, "S22", [self.player(worth=100)], captains, {}, "Me"
        )

    def test_full_human_roster_cannot_bid(self):
        state = self.state()
        me = state.teams["Me"]
        me.roster = [
            {
                "steam32": 100 + i,
                "name": str(i),
                "price": 1,
                "pos": i + 1,
                "prefs": [i + 1],
            }
            for i in range(config.MOCK_BUYS)
        ]
        state.phase = "bidding"
        state.nominee = self.player()
        state.high_bid = 1
        state.high_bidder = "Bot"

        self.assertEqual(state.human_bid(2), (False, "roster full"))

    def test_sale_floor_preserves_minimum_bids_for_future_slots(self):
        state = self.state()
        state.phase = "bidding"
        state.nominee = self.player()
        state.high_bid = 1
        state.high_bidder = "Bot"
        state.window = 1

        _resolve_sale(state)

        team = state.teams["Bot"]
        self.assertGreaterEqual(
            team.budget,
            team.slots_left * config.MOCK_RESERVE_PER_SLOT,
        )
        self.assertGreaterEqual(team.affordable(), config.MOCK_MIN_BID)

    def test_lowest_starting_budget_nominates_first_with_stable_ties(self):
        captains = [
            {"captain": "High", "budget": 500, "team_id": "1", "pos": [1]},
            {"captain": "Low A", "budget": 200, "team_id": "2", "pos": [2]},
            {"captain": "Low B", "budget": 200, "team_id": "3", "pos": [3]},
            {"captain": "Mid", "budget": 300, "team_id": "4", "pos": [4]},
        ]
        state = MockState(
            53, "S22", [self.player()], captains, {}, "Low A"
        )

        self.assertEqual(state.order, ["Low A", "Low B", "Mid", "High"])
        self.assertEqual(_next_nominator(state), "Low A")

    def test_speed_change_during_ai_wait_preserves_bid_opportunities(self):
        from scout import mockdraft

        class Clock:
            now = 100.0

            @classmethod
            def advance(cls, seconds):
                cls.now += seconds

        class Switch:
            changed = False

        class FakeStop:
            def __init__(self, state, switch):
                self.state = state
                self.switch = switch

            def is_set(self):
                return False

            def wait(self, seconds):
                if self.switch and not Switch.changed:
                    Switch.changed = True
                    self.state.set_speed(8)
                Clock.advance(seconds)
                return False

        class FakeTimingEvent:
            def __init__(self, state, switch):
                self.state = state
                self.switch = switch
                self.pending = False

            def clear(self):
                self.pending = False

            def set(self):
                self.pending = True

            def wait(self, timeout):
                if self.switch and not Switch.changed:
                    Clock.advance(min(0.05, timeout))
                    Switch.changed = True
                    self.state.set_speed(8)
                    return True
                Clock.advance(timeout)
                return self.pending

        def opportunities(switch):
            Clock.now = 100.0
            Switch.changed = False
            state = MockState(
                53,
                "S22",
                [self.player(worth=100)],
                [
                    {"captain": "A", "budget": 500,
                     "team_id": "1", "pos": [1]},
                    {"captain": "B", "budget": 500,
                     "team_id": "2", "pos": [2]},
                ],
                {},
                "A",
            )
            state._timing_changed = FakeTimingEvent(state, switch)
            stop = FakeStop(state, switch)
            rounds = []

            def record_round(current, force=False):
                if force:
                    return False
                rounds.append(Clock.now)
                return False

            with mock.patch.object(
                mockdraft.time, "time", side_effect=lambda: Clock.now
            ), mock.patch.object(
                mockdraft.time, "monotonic", side_effect=lambda: Clock.now
            ), mock.patch.object(
                mockdraft,
                "_ai_bid_round",
                side_effect=record_round,
            ):
                if not switch:
                    state.set_speed(8)
                state._open_auction(state.pool[10], 1, "A")
                _run_open_auction(state, stop)
            return len(rounds)

        self.assertEqual(opportunities(switch=False), 6)
        self.assertEqual(opportunities(switch=True), 6)

    def test_forced_ai_round_bypasses_silence_only_for_eligible_competitor(self):
        state = self.competitive_state()
        player = state.pool[10]
        state._open_auction(player, 1, "A")

        with mock.patch("scout.mockdraft.random.random", return_value=1.0):
            self.assertFalse(_ai_bid_round(state))
            self.assertTrue(_ai_bid_round(state, force=True))

        self.assertEqual(state.high_bidder, "B")
        self.assertGreater(state.high_bid, 1)

        state.teams["A"].budget = 1
        state.high_bidder = "B"
        state.high_bid = state.teams["B"].max_bid(
            player, list(state.pool.values())
        )
        self.assertFalse(_ai_bid_round(state, force=True))

    def test_expired_auction_runs_to_competitive_ceiling(self):
        from scout import mockdraft

        state = self.competitive_state()
        player = state.pool[10]
        clock = {"now": 100.0}
        stop = threading.Event()
        competitors = ("A", "B")

        with mock.patch.object(
            mockdraft.time, "time", side_effect=lambda: clock["now"]
        ):
            state._open_auction(player, 1, "A")
            ceilings = [
                state.teams[name].max_bid(player, list(state.pool.values()))
                for name in competitors
            ]
            state.deadline = clock["now"]

            def expire(current, _stop, _seconds):
                clock["now"] = current.deadline
                return True

            with mock.patch.object(
                mockdraft.random, "random", return_value=1.0
            ), mock.patch.object(
                mockdraft.random, "choice", side_effect=lambda eager: eager[0]
            ), mock.patch.object(
                mockdraft.random, "choices", return_value=[25]
            ), mock.patch.object(
                mockdraft, "_wait_scaled_interval", side_effect=expire
            ):
                _run_open_auction(state, stop)

        self.assertGreaterEqual(state.high_bid, min(ceilings))
        self.assertFalse(_ai_bid_round(state, force=True))


class MockRosterSourceTests(unittest.TestCase):
    def test_official_roster_overrides_stale_export_and_drops_champ_from_pool(self):
        from scout import mockdraft

        official = [{
            "captain": "champ0044",
            "steam64": config.STEAM64_OFFSET + 154288911,
            "team_id": "10",
            "team": "Champ's team",
            "budget": 260,
            "unspent": 260,
        }]
        curated = ([{
            "captain": "champ0044",
            "steam64": None,
            "team_id": None,
            "budget": 255,
            "pos": None,
        }], {154288911: [3, 4, 5]}, set())
        players = [{
            "name": "champ0044",
            "steam32": 154288911,
            "steam64": config.STEAM64_OFFSET + 154288911,
            "mmr": 4178,
            "captain": "N",
        }, {
            "name": "Player",
            "steam32": 7,
            "steam64": config.STEAM64_OFFSET + 7,
            "mmr": 3000,
            "captain": "N",
        }]
        fake_cache = mock.Mock()
        fake_cache.get_blob.return_value = None

        with mock.patch.object(mockdraft, "Cache", return_value=fake_cache), \
             mock.patch.object(mockdraft, "OpenDota",
                               return_value=mock.Mock()), \
             mock.patch.object(mockdraft, "players_from_snapshot",
                               return_value=("S22", players)), \
             mock.patch.object(mockdraft, "load_hero_map",
                               return_value=mock.Mock()), \
             mock.patch.object(mockdraft, "fetch_player_sections",
                               return_value=({}, 0)), \
             mock.patch.object(
                 mockdraft,
                 "build_metrics",
                 side_effect=lambda player, sections, heroes: {
                     "adj_skill": player["mmr"],
                     "worth_cost": 100,
                     "est_cost": 90,
                 },
             ), \
             mock.patch.object(mockdraft, "annotate_players",
                               return_value=None), \
             mock.patch.object(mockdraft, "pool_analysis"), \
             mock.patch.object(mockdraft, "_load_captains_file",
                               return_value=curated), \
             mock.patch.object(mockdraft, "load_official_teams",
                               return_value=(official, "website", None),
                               create=True), \
             mock.patch.object(mockdraft, "_player_slots",
                               return_value={1: 3000}), \
             mock.patch.object(mockdraft, "position_ratings",
                               return_value={"primary": 1, "ratings": {}}), \
             mock.patch.object(mockdraft, "value_tier", return_value="C"):
            label, pool, captains, _ = mockdraft._load_pool(
                53, True, roster_source="official")

        self.assertEqual(label, "S22")
        self.assertEqual(captains[0]["budget"], 260)
        self.assertNotIn("champ0044", [player["name"] for player in pool])

    def test_parser_accepts_official_roster_alias(self):
        from scout.cli import build_parser

        alias = build_parser().parse_args(["--mock", "--official-roster"])
        curated = build_parser().parse_args(
            ["--mock", "--roster", "curated"])

        self.assertEqual(alias.roster, "official")
        self.assertEqual(curated.roster, "curated")

    def test_mock_snapshot_names_roster_source(self):
        state = MockState(
            53,
            "S22",
            [MockAuctionTests.player()],
            [{"captain": "Me", "budget": 100,
              "team_id": "1", "pos": [1]}],
            {},
            "Me",
            roster_source="official",
        )

        self.assertEqual(
            state.live_snapshot()["mock"]["roster_source"],
            "official",
        )

    def test_mock_snapshot_exposes_captain_steam_id_to_dashboard(self):
        state = MockState(
            53,
            "S22",
            [MockAuctionTests.player()],
            [{
                "captain": "champ0044",
                "steam64": config.STEAM64_OFFSET + 154288911,
                "budget": 265,
                "team_id": "435",
                "pos": [3],
            }],
            {},
            "champ0044",
            roster_source="official",
        )

        team = state.live_snapshot()["mock"]["teams"][0]

        self.assertEqual(team["steam32"], 154288911)


class StatsTests(unittest.TestCase):
    """scout.stats primitives — the untested foundation the skill ensemble and
    the family-wise hot/cold bar are built on."""

    def test_binom_z_scales_with_evidence_and_guards_empty(self):
        from scout import stats
        self.assertIsNone(stats.binom_z(0, 0))
        self.assertEqual(stats.binom_z(5, 10), 0.0)         # 50% → no signal
        self.assertAlmostEqual(stats.binom_z(75, 100), 5.0)  # (75-50)/(10/2)

    def test_family_z_raises_the_bar_with_more_tests(self):
        from scout import stats
        self.assertIsNone(stats.family_z(0))
        one = stats.family_z(1, 0.10)
        many = stats.family_z(100, 0.10)
        self.assertGreater(many, one)   # Bonferroni tightens the cutoff

    def test_robust_z_needs_enough_peers_and_some_spread(self):
        from scout import stats
        self.assertIsNone(stats.robust_z(5, [1, 2, 3]))          # too few peers
        self.assertIsNone(stats.robust_z(5, [7] * 12))           # no spread (MAD 0)
        z = stats.robust_z(20, list(range(10, 22)))
        self.assertIsNotNone(z)
        self.assertGreater(z, 0)                                  # above the median

    def test_ivw_mean_weights_toward_the_tighter_estimate(self):
        from scout import stats
        self.assertEqual(stats.ivw_mean([]), (None, None))
        mean, sigma = stats.ivw_mean([(100, 10), (200, 100)])
        self.assertLess(mean, 150)          # pulled toward the tight (sigma 10) one
        self.assertLess(sigma, 10)          # combined sigma beats either input

    def test_wilson_lower_is_below_point_estimate_and_guards_empty(self):
        from scout import stats
        self.assertIsNone(stats.wilson_lower(0, 0))
        self.assertLess(stats.wilson_lower(7, 10), 0.7)

    def test_fisher_exact_matches_enumerable_tables_and_guards_empty(self):
        from scout import stats
        self.assertIsNone(stats.fisher_exact(0, 0, 0, 0))
        self.assertIsNone(stats.fisher_exact(-1, 0, 0, 0))
        self.assertIsNone(stats.fisher_exact(True, 1, 1, 1))
        self.assertAlmostEqual(stats.fisher_exact(1, 1, 1, 1), 1.0)
        self.assertAlmostEqual(stats.fisher_exact(2, 0, 0, 2), 1 / 3)
        # [[8, 2], [1, 5]] is a textbook two-sided example (~0.03497).
        self.assertAlmostEqual(stats.fisher_exact(8, 2, 1, 5), 0.034965, places=5)

    def test_clamp(self):
        from scout import stats
        self.assertEqual(stats.clamp(5, 0, 10), 5)
        self.assertEqual(stats.clamp(-1, 0, 10), 0)
        self.assertEqual(stats.clamp(99, 0, 10), 10)


class ToxicityTests(unittest.TestCase):
    """Chat toxicity now lives in scout.toxicity. Exact-token scan (no substring
    matches), severity weighting, and a private-chat guard."""

    def test_private_or_empty_chat_returns_only_the_flag(self):
        from scout import toxicity
        self.assertEqual(toxicity.score(None), {"private_chat": True})
        self.assertEqual(toxicity.score({"my_word_counts": {}}),
                         {"private_chat": True})

    def test_exact_token_scan_does_not_fire_on_substrings(self):
        from scout import toxicity
        out = toxicity.score({"my_word_counts": {"assist": 50, "class": 20,
                                                 "gg": 30}})
        self.assertEqual(out["toxicity_breakdown"],
                         {"flame": 0, "curse": 0, "slur": 0})
        self.assertEqual(out["toxicity_label"], "Clean")

    def test_severity_weighting_and_banding(self):
        from scout import toxicity
        clean = toxicity.score({"my_word_counts": {"hello": 500, "ez": 1}})
        heavy = toxicity.score({"my_word_counts": {"retard": 40, "fuck": 40,
                                                   "hello": 20}})
        self.assertEqual(clean["toxicity_label"], "Clean")
        self.assertGreater(heavy["toxicity_score"], clean["toxicity_score"])
        self.assertEqual(heavy["toxicity_breakdown"]["slur"], 40)
        self.assertEqual(heavy["toxicity_breakdown"]["curse"], 40)


class FlagHotColdTests(unittest.TestCase):
    """flag_hot_cold owns the family-wise streak flag that pool_analysis used to
    inline (build_metrics leaves it unset by design)."""

    @staticmethod
    def _pd(z30):
        return {"data": {"z30": z30}}

    def test_family_bar_rises_with_pool_size_and_flags_streaks(self):
        from scout.analysis import flag_hot_cold
        small = [self._pd(3.0), self._pd(-3.0)]
        bar_small = flag_hot_cold(small)
        self.assertGreaterEqual(bar_small, config.HOT_COLD_Z)
        self.assertTrue(small[0]["data"]["hot"])
        self.assertTrue(small[1]["data"]["cold"])

        big = [self._pd(2.0)] + [self._pd(0.0) for _ in range(200)]
        bar_big = flag_hot_cold(big)
        self.assertGreater(bar_big, bar_small)      # Bonferroni tightens
        self.assertFalse(big[0]["data"]["hot"])      # z=2 no longer clears the bar

    def test_players_without_a_30d_record_are_skipped(self):
        from scout.analysis import flag_hot_cold
        pool = [self._pd(None), self._pd(3.0)]
        flag_hot_cold(pool)
        self.assertNotIn("hot", pool[0]["data"])     # z30 None → untouched
        self.assertTrue(pool[1]["data"]["hot"])


class PositionRatingTests(unittest.TestCase):
    """position_ratings used to emit a 3-step function, so pos 4 and 5 were
    always identical and the two off-lanes usually collided. It now stacks four
    evidence channels, each shrunk by the sample behind it."""

    @staticmethod
    def _d(**over):
        d = {
            "adj_skill": 3000, "skill_unc": 200, "winrate": 50,
            "lane_pcts": {}, "lane_wr": {}, "lane_n": 0, "lane_gpm": {},
            "hero_games": {}, "hero_pos_baseline": None,
            "avg_gpm": 0, "avg_apd": None, "stats_n": 0,
        }
        d.update(over)
        return d

    def test_no_skill_estimate_yields_nothing(self):
        from scout.analysis import position_ratings
        self.assertEqual(position_ratings(self._d(adj_skill=None,
                                                 skill_mmr=None)), {})

    def test_hero_pool_separates_pos_4_from_pos_5(self):
        """The regression that motivated the rewrite: lane data alone cannot
        tell the two supports apart, so they came out equal for everyone."""
        from scout.analysis import position_ratings
        # Lion/CM/Dazzle/Warlock are pure pos 5; Tusk/Nyx/Bounty pure pos 4
        hard = position_ratings(self._d(
            hero_games={26: 120, 5: 90, 50: 80, 37: 60}, avg_gpm=260,
            avg_apd=3.0, stats_n=200))["ratings"]
        soft = position_ratings(self._d(
            hero_games={100: 120, 88: 90, 62: 80, 107: 60}, avg_gpm=340,
            avg_apd=1.9, stats_n=200))["ratings"]
        self.assertGreater(hard[5]["mmr"], hard[4]["mmr"])
        self.assertGreater(soft[4]["mmr"], soft[5]["mmr"])

    def test_lane_share_is_continuous_not_stepped(self):
        from scout.analysis import position_ratings
        def mid(share):
            r = position_ratings(self._d(lane_pcts={"Mid": share}, lane_n=150))
            return r["ratings"][2]["mmr"]
        # under the old 10/25 thresholds 12 and 24 were the same number
        self.assertNotEqual(mid(12), mid(24))
        self.assertLess(mid(12), mid(24))
        self.assertLess(mid(24), mid(40))

    def test_thin_samples_shrink_toward_base(self):
        """A lopsided hero pool with barely any games behind it must not earn
        the same spread as the same pool over hundreds of games."""
        from scout.analysis import position_ratings
        pool = {26: 6, 5: 4}
        thin = position_ratings(self._d(hero_games=pool))["ratings"]
        thick = position_ratings(self._d(
            hero_games={k: v * 40 for k, v in pool.items()}))["ratings"]
        self.assertLess(abs(thin[5]["delta"]), abs(thick[5]["delta"]))
        self.assertGreater(thin[5]["unc"], thick[5]["unc"])

    def test_spread_is_capped(self):
        from scout.analysis import POS_SPREAD_CAP, position_ratings
        r = position_ratings(self._d(
            lane_pcts={"Safe": 100}, lane_n=400, lane_wr={"Safe": {
                "n": 400, "w": 360, "wr": 90.0}},
            hero_games={1: 500, 44: 400}, avg_gpm=800, avg_apd=0.4,
            stats_n=400))["ratings"]
        for pos in range(1, 6):
            self.assertLessEqual(abs(r[pos]["delta"]), POS_SPREAD_CAP)

    def test_conf_vocabulary_stays_stable_for_mockdraft(self):
        """mockdraft._slots filters on these exact strings."""
        from scout.analysis import position_ratings
        r = position_ratings(self._d(lane_pcts={"Safe": 60, "Off": 30},
                                     lane_n=150, hero_games={1: 200}))
        for entry in r["ratings"].values():
            self.assertIn(entry["conf"], ("measured", "part-time", "est"))

    def test_pool_baseline_recentres_hero_affinity(self):
        """The hero table is honestly lopsided (only ~6 pure pos 4 heroes vs
        ~17 pure pos 5), so a flat 1-in-5 neutral made everyone a hard support.
        pool_analysis re-centres on the pool's own median."""
        from scout.analysis import _set_hero_pos_baseline
        pool = [{"data": self._d(hero_games={26: 50, 5: 50, 100: 40})}
                for _ in range(12)]
        _set_hero_pos_baseline(pool)
        base = pool[0]["data"]["hero_pos_baseline"]
        self.assertIsNotNone(base)
        self.assertEqual(set(base), {1, 2, 3, 4, 5})
        self.assertAlmostEqual(sum(base.values()), 1.0, places=6)

    def test_tiny_pool_keeps_the_flat_prior(self):
        from scout.analysis import _set_hero_pos_baseline
        pool = [{"data": self._d(hero_games={26: 100})} for _ in range(3)]
        _set_hero_pos_baseline(pool)
        self.assertIsNone(pool[0]["data"]["hero_pos_baseline"])


class HeroPositionTableTests(unittest.TestCase):
    """The hero->position table is hand-curated, so guard its shape."""

    def test_weights_normalise(self):
        from scout.hero_positions import POS_WEIGHTS
        for hid, w in POS_WEIGHTS.items():
            self.assertAlmostEqual(sum(w.values()), 1.0, places=6, msg=hid)
            for pos in w:
                self.assertIn(pos, (1, 2, 3, 4, 5))

    def test_affinity_shares_sum_to_one_and_skip_unknown_heroes(self):
        from scout.hero_positions import affinity
        shares, counted = affinity({1: 50, 999999: 500})
        self.assertEqual(counted, 50)            # unknown hero ignored entirely
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=6)
        self.assertGreater(shares[1], shares[5])

    def test_empty_pool_is_safe(self):
        from scout.hero_positions import affinity
        shares, counted = affinity({})
        self.assertEqual(counted, 0)
        self.assertEqual(set(shares.values()), {0.0})

    def test_every_id_is_a_real_hero_with_a_matching_name(self):
        """Guards against a mistyped id silently priming the wrong hero. Anchored
        to HERO_FALLBACK, not live OpenDota, which renames heroes periodically."""
        from scout.heroes import HERO_FALLBACK
        from scout.hero_positions import HERO_POS
        for hid, (name, _) in HERO_POS.items():
            self.assertIn(hid, HERO_FALLBACK, msg=f"unknown hero id {hid}")
            self.assertEqual(name, HERO_FALLBACK[hid], msg=f"id {hid}")


class PricingTests(unittest.TestCase):
    """The premium algorithm now has one Python home (scout.pricing) and a
    language-neutral fixture both it and the dashboard JS replay."""

    def test_committed_golden_vectors_match_the_python_spec(self):
        from scout import pricing
        path = os.path.join(os.path.dirname(pricing.__file__),
                            "pricing_vectors.json")
        with open(path, encoding="utf-8") as f:
            fixture = json.load(f)
        rank, pos = fixture["rank"], fixture["pos"]
        self.assertTrue(fixture["cases"])
        for c in fixture["cases"]:
            pos_ranked = {int(k): v for k, v in c["posRanked"].items()}
            got = pricing.combined_premium(c["mmr"], c["roles"], c["ranked"],
                                           pos_ranked, rank, pos)
            self.assertAlmostEqual(got, c["premium"], places=6,
                                   msg=f"vector drift at mmr={c['mmr']}")

    def test_rank_premium_interpolates_between_and_clamps_outside(self):
        from scout import pricing
        pts = [[1, 80], [3, 40], [8, 30]]
        self.assertEqual(pricing.rank_premium(1, pts), 80)   # at first point
        self.assertEqual(pricing.rank_premium(0, pts), 80)   # clamped below
        self.assertEqual(pricing.rank_premium(2, pts), 60)   # midway 80->40
        self.assertEqual(pricing.rank_premium(99, pts), 30)  # clamped above

    def test_round5_snaps_to_five_and_floors_at_five(self):
        from scout import pricing
        self.assertEqual(pricing.round5(0), 5)
        self.assertEqual(pricing.round5(12), 10)
        self.assertEqual(pricing.round5(13), 15)

    def test_dashboard_embeds_vectors_and_leaves_no_template_markers(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(config, "CACHE_DIR", root):
                from scout import report_html
                out = os.path.join(root, "dash.html")
                report_html.generate_dashboard([], out, "S22", 53,
                                                offline=True)
                with open(out, encoding="utf-8") as f:
                    page = f.read()
        self.assertIn("checkPricing", page)          # JS self-check present
        self.assertIn("PRICING_VECTORS", page)        # fixture embedded
        self.assertNotIn("{{", page)                  # every marker filled in

    def test_budget_bar_uses_remaining_money_only_in_mock_mode(self):
        if importlib.util.find_spec("openpyxl") is None:
            openpyxl = types.ModuleType("openpyxl")
            styles = types.ModuleType("openpyxl.styles")
            utils = types.ModuleType("openpyxl.utils")

            def style_stub(*args, **kwargs):
                return object()

            openpyxl.Workbook = object
            for name in ("Alignment", "Border", "Font", "PatternFill", "Side"):
                setattr(styles, name, style_stub)
            utils.get_column_letter = lambda n: str(n)
            sys.modules["openpyxl"] = openpyxl
            sys.modules["openpyxl.styles"] = styles
            sys.modules["openpyxl.utils"] = utils

        from scout import report_html

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required to exercise dashboard JavaScript")
        match = re.search(
            r"function budgetBarState\(.*?^\}",
            report_html.TEMPLATE,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        script = match.group(0) + """
const cases = [
  budgetBarState(100, 0, true),
  budgetBarState(100, 25, true),
  budgetBarState(100, 100, true),
  budgetBarState(100, 25, false),
];
process.stdout.write(JSON.stringify(cases));
"""
        got = json.loads(subprocess.check_output(
            [node, "-e", script], text=True
        ))

        self.assertEqual([case["fillPct"] for case in got], [100, 75, 0, 25])
        self.assertEqual(got[1]["percentText"], "75% remaining")
        self.assertEqual(got[3]["percentText"], "25% used")
        self.assertEqual(got[1]["title"], "remaining $75 of $100 (75%)")

    def test_budget_only_captain_maps_to_signup_steam_id(self):
        from scout.report_html import _captain_id_map
        all_data = [{
            "player": {"name": "champ0044", "steam32": 154288911},
            "data": {},
        }]

        result = _captain_id_map(all_data, {" CHAMP0044 ": 260})

        self.assertEqual(result, {" CHAMP0044 ": 154288911})


class CaptainsTests(unittest.TestCase):
    """Captain/budget derivations now live in one module (scout.captains),
    replacing four slightly-different inline copies."""

    TEAMS = [
        {"captain": "Alice", "team_id": "11", "budget": 500},
        {"captain": "Bob", "team_id": "22", "budget": 300},
        {"captain": "", "team_id": "33", "budget": 999},   # unnamed → skipped
        {"captain": "Cara", "team_id": None, "budget": 200},  # no id → no cap_map
    ]

    def test_captain_map_skips_teams_without_id_or_name(self):
        from scout.captains import captain_map
        self.assertEqual(captain_map(self.TEAMS), {"11": "Alice", "22": "Bob"})

    def test_budget_map_skips_unnamed_captains(self):
        from scout.captains import budget_map
        self.assertEqual(budget_map(self.TEAMS),
                         {"Alice": 500, "Bob": 300, "Cara": 200})

    def test_resolve_budgets_layers_overrides_over_scraped(self):
        from scout.captains import resolve_budgets
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "budgets.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"Bob": 750}, f)
            budgets, count, err = resolve_budgets(self.TEAMS, path=path)
        self.assertIsNone(err)
        self.assertEqual(count, 1)
        self.assertEqual(budgets["Bob"], 750)     # override wins
        self.assertEqual(budgets["Alice"], 500)   # scraped kept

    def test_resolve_budgets_reports_a_malformed_override_file(self):
        from scout.captains import resolve_budgets
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "budgets.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)   # wrong shape → ValueError inside
            budgets, count, err = resolve_budgets(self.TEAMS, path=path)
        self.assertIsNotNone(err)
        self.assertEqual(count, 0)
        self.assertEqual(budgets["Alice"], 500)   # scraped survives the bad file

    def test_override_team_budgets_mutates_rows_in_place(self):
        from scout.captains import override_team_budgets
        teams = [dict(t) for t in self.TEAMS]
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "budgets.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"Alice": 123}, f)
            count, err = override_team_budgets(teams, path=path)
        self.assertIsNone(err)
        self.assertEqual(count, 1)
        self.assertEqual(teams[0]["budget"], 123)

    def test_null_steam_id_resolves_by_normalized_player_name(self):
        from scout.captains import resolve_team_identities
        teams = [{"captain": "  CHAMP0044 ", "steam64": None,
                  "team_id": None, "budget": 260}]
        players = [{"name": "champ0044", "steam32": 154288911}]

        rows, unresolved = resolve_team_identities(teams, players)

        self.assertEqual(unresolved, [])
        self.assertEqual(rows[0]["steam64"],
                         154288911 + config.STEAM64_OFFSET)

    def test_ambiguous_name_is_not_resolved(self):
        from scout.captains import resolve_team_identities
        teams = [{"captain": "Champ", "steam64": None, "budget": 260}]
        players = [{"name": "champ", "steam32": 1},
                   {"name": " CHAMP ", "steam32": 2}]

        rows, unresolved = resolve_team_identities(teams, players)

        self.assertEqual(rows, [])
        self.assertEqual(unresolved, ["Champ"])

    def test_official_loader_caches_rows_and_applies_budget_override(self):
        from scout.captains import load_official_teams
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            override = os.path.join(root, "budgets.json")
            with open(override, "w", encoding="utf-8") as f:
                json.dump({"champ0044": 275}, f)
            live = [{
                "captain": "champ0044",
                "steam64": 76561198114554639,
                "team_id": "10",
                "team": "Champ's team",
                "budget": 260,
                "unspent": 260,
            }]

            rows, source, error = load_official_teams(
                53, cache, fetcher=lambda _: live, path=override)
            cached, cached_source, cached_error = load_official_teams(
                53, cache, offline=True, path=override)

        self.assertIsNone(error)
        self.assertEqual(source, "website")
        self.assertEqual(rows[0]["budget"], 275)
        self.assertIsNone(cached_error)
        self.assertEqual(cached_source, "cache")
        self.assertEqual(cached[0]["budget"], 275)

    def test_official_loader_fails_without_live_or_cached_rows(self):
        from scout.captains import load_official_teams
        with tempfile.TemporaryDirectory() as root:
            rows, source, error = load_official_teams(
                53,
                Cache(root),
                fetcher=lambda _: [],
                path=os.path.join(root, "budgets.json"),
            )

        self.assertEqual(rows, [])
        self.assertEqual(source, "missing")
        self.assertIn("official roster", error.lower())


class BroadcastContractTests(unittest.TestCase):
    """The /live/state wire shape now has one home (scout.broadcast). Both the
    --live follower and the --mock auction must keep emitting every key it
    defines, so the dashboard has one shape to trust."""

    def test_live_snapshot_carries_the_shared_wire_contract(self):
        snap = LiveState(53).snapshot()
        for key in SNAPSHOT_KEYS:
            self.assertIn(key, snap)
        self.assertIn("log", snap)          # live-only socket feed
        self.assertNotIn("mock", snap)

    def test_mock_snapshot_carries_the_shared_wire_contract(self):
        captains = [
            {"captain": "Me", "budget": 100, "team_id": "1", "pos": [1]},
            {"captain": "Bot", "budget": 100, "team_id": "2", "pos": [2]},
        ]
        snap = MockState(53, "S22", [MockAuctionTests.player()], captains,
                         {}, "Me").live_snapshot()
        for key in SNAPSHOT_KEYS:
            self.assertIn(key, snap)
        self.assertEqual(snap["mode"], "mock")     # mock-only envelope
        self.assertIn("mock", snap)

    def test_sse_hub_drops_dead_writers_and_delivers_to_live_ones(self):
        class Writer:
            def __init__(self, broken=False):
                self.broken, self.data = broken, b""

            def write(self, payload):
                if self.broken:
                    raise BrokenPipeError("closed tab")
                self.data += payload

            def flush(self):
                pass

        hub = SSEHub()
        good, dead = Writer(), Writer(broken=True)
        hub.add(good)
        hub.add(dead)
        hub.broadcast({"kind": "bid", "amount": 42})

        self.assertIn(b'"amount": 42', good.data)
        self.assertTrue(good.data.startswith(b"data: "))
        # a second broadcast must not raise — the dead writer was pruned
        hub.broadcast({"kind": "sold"})


class HeroDraftTests(unittest.TestCase):
    def test_organized_match_classifier_is_shared_and_strict(self):
        self.assertFalse(is_organized_match({"lobby_type": 1, "game_mode": 22}))
        self.assertTrue(is_organized_match({"lobby_type": 1, "game_mode": 2}))
        self.assertTrue(is_organized_match({"lobby_type": 2, "party_size": 10}))

    def test_generated_page_escapes_script_terminators_and_names(self):
        payload = "</script><script>globalThis.PWNED=1</script>"
        page = render_page(
            [{"steam32": 1, "name": payload, "mmr": 1, "role": "Any"}],
            {1: {"n": "Hero", "key": "", "attr": "str"}},
            payload,
        )
        self.assertNotIn(payload, page)
        self.assertIn("<\\/script>", page)
        self.assertIn("&lt;/script&gt;", page)

    def test_failed_matchup_rows_are_not_published_as_fresh_cache(self):
        stats = {
            "1": {"g": 100, "w": 50},
            "2": {"g": 100, "w": 50},
        }
        stale = {"1": {"2": [20, 10]}}

        class FakeCache:
            def __init__(self):
                self.writes = []

            def get_blob(self, name, max_age_hours=None):
                if name == "hero_meta_stats":
                    return stats
                if name == "hero_matchups":
                    return None if max_age_hours is not None else stale
                return None

            def set_blob(self, name, data):
                self.writes.append((name, data))

        class FakeOpenDota:
            def hero_matchups(self, hid):
                return None if hid == 1 else []

        cache = FakeCache()
        with mock.patch("scout.herodraft.Cache", return_value=cache):
            with mock.patch("scout.herodraft.OpenDota", return_value=FakeOpenDota()):
                meta = load_meta(offline=False)

        self.assertIn(1, meta["adv"])
        self.assertFalse(any(name == "hero_matchups" for name, _ in cache.writes))


if __name__ == "__main__":
    unittest.main()
