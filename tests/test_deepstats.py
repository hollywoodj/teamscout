import tempfile
import unittest
import sys
import types

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = types.ModuleType("requests")

from scout.cache import Cache


class MatchClientStub:
    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls = []

    def match(self, match_id):
        self.calls.append(int(match_id))
        return self.payloads.get(int(match_id))


def timeline(value):
    return [0] * 10 + [value]


def parsed_match(match_id=100):
    return {
        "match_id": match_id,
        "start_time": 1_780_000_000,
        "duration": 2400,
        "version": 22,
        "players": [
            {
                "account_id": 10,
                "player_slot": 0,
                "lane": 1,
                "lane_role": 1,
                "is_roaming": False,
                "gold_t": timeline(3000),
                "xp_t": timeline(2800),
                "observer_kills": 2,
                "sentry_kills": 3,
            },
            {
                "account_id": 11,
                "player_slot": 1,
                "lane": 1,
                "lane_role": 1,
                "is_roaming": False,
                "gold_t": timeline(2200),
                "xp_t": timeline(2100),
                "observer_kills": 0,
                "sentry_kills": 0,
            },
            {
                "account_id": 20,
                "player_slot": 128,
                "lane": 1,
                "lane_role": 3,
                "is_roaming": False,
                "gold_t": timeline(2500),
                "xp_t": timeline(2300),
                "observer_kills": 0,
                "sentry_kills": 1,
            },
            {
                "account_id": 21,
                "player_slot": 129,
                "lane": 1,
                "lane_role": 3,
                "is_roaming": False,
                "gold_t": timeline(2000),
                "xp_t": timeline(1800),
                "observer_kills": 0,
                "sentry_kills": 0,
            },
            {
                "account_id": 30,
                "player_slot": 2,
                "lane": 2,
                "lane_role": 2,
                "is_roaming": False,
                "gold_t": timeline(3100),
                "xp_t": timeline(3000),
            },
            {
                "account_id": 31,
                "player_slot": 130,
                "lane": 2,
                "lane_role": 2,
                "is_roaming": False,
                "gold_t": timeline(3050),
                "xp_t": timeline(2950),
            },
        ],
    }


class MatchCacheTests(unittest.TestCase):
    def test_match_cache_round_trip_is_separate_from_player_sections(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            self.assertIsNone(cache.get_match(100))
            cache.set_match(100, {"match_id": 100, "version": 22})
            self.assertEqual(
                cache.get_match(100),
                {"match_id": 100, "version": 22},
            )

    def test_completed_match_cache_is_immutable_but_unparsed_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_match(100, {"match_id": 100})
            cache.set_match(100, parsed_match(100))
            cache.set_match(100, {**parsed_match(100), "duration": 99})

            self.assertEqual(cache.get_match(100)["duration"], 2400)


class DeepSampleTests(unittest.TestCase):
    def test_extracts_target_dewards_and_both_physical_lane_totals(self):
        from scout.deepstats import player_sample

        sample = player_sample(parsed_match(), 10, target_slot=0)

        self.assertTrue(sample["parsed"])
        self.assertEqual(sample["lane"], 1)
        self.assertEqual(sample["lane_role"], 1)
        self.assertEqual(sample["observer_kills"], 2)
        self.assertEqual(sample["sentry_kills"], 3)
        self.assertEqual(sample["ally_lane_gold10"], 5200)
        self.assertEqual(sample["enemy_lane_gold10"], 4500)
        self.assertEqual(sample["ally_lane_xp10"], 4900)
        self.assertEqual(sample["enemy_lane_xp10"], 4100)

    def test_target_slot_fallback_handles_anonymous_account(self):
        from scout.deepstats import player_sample

        match = parsed_match()
        match["players"][0]["account_id"] = None
        sample = player_sample(match, 10, target_slot=0)
        self.assertEqual(sample["player_slot"], 0)
        self.assertEqual(sample["observer_kills"], 2)

    def test_unparsed_match_keeps_coverage_without_inventing_metrics(self):
        from scout.deepstats import player_sample

        match = {
            "match_id": 101,
            "start_time": 1_780_000_100,
            "duration": 1800,
            "players": [{"account_id": 10, "player_slot": 0}],
        }
        sample = player_sample(match, 10, target_slot=0)
        self.assertFalse(sample["parsed"])
        self.assertIsNone(sample["observer_kills"])
        self.assertIsNone(sample["ally_lane_gold10"])

    def test_missing_ward_kill_fields_stay_unavailable(self):
        from scout.deepstats import player_sample

        match = parsed_match()
        match["players"][0].pop("observer_kills")
        match["players"][0].pop("sentry_kills")
        sample = player_sample(match, 10, target_slot=0)

        self.assertTrue(sample["parsed"])
        self.assertIsNone(sample["observer_kills"])
        self.assertIsNone(sample["sentry_kills"])

    def test_loader_fetches_new_matches_once_and_reuses_immutable_cache(self):
        from scout.deepstats import load_player_deep_stats

        matches = [
            {"match_id": 100, "start_time": 200, "player_slot": 0},
            {"match_id": 101, "start_time": 100, "player_slot": 0},
        ]
        payloads = {
            100: parsed_match(100),
            101: {**parsed_match(101), "start_time": 1_779_000_000},
        }
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            first_client = MatchClientStub(payloads)
            first = load_player_deep_stats(
                first_client,
                cache,
                {"steam32": 10},
                matches,
                limit=10,
            )
            second_client = MatchClientStub()
            second = load_player_deep_stats(
                second_client,
                cache,
                {"steam32": 10},
                matches,
                limit=10,
            )

        self.assertEqual(first_client.calls, [100, 101])
        self.assertEqual(second_client.calls, [])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_loader_retries_legacy_unparsed_cache_online(self):
        from scout.deepstats import load_player_deep_stats

        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            cache.set_match(100, {"match_id": 100, "players": []})
            client = MatchClientStub({100: parsed_match(100)})

            samples = load_player_deep_stats(
                client,
                cache,
                {"steam32": 10},
                [{"match_id": 100, "start_time": 200, "player_slot": 0}],
            )

            self.assertEqual(client.calls, [100])
            self.assertTrue(samples[0]["parsed"])
            self.assertEqual(cache.get_match(100)["version"], 22)

    def test_loader_limits_to_ten_newest_and_offline_never_fetches(self):
        from scout.deepstats import load_player_deep_stats

        matches = [
            {"match_id": match_id, "start_time": match_id, "player_slot": 0}
            for match_id in range(1, 13)
        ]
        with tempfile.TemporaryDirectory() as root:
            cache = Cache(root)
            client = MatchClientStub()
            samples = load_player_deep_stats(
                client,
                cache,
                {"steam32": 10},
                matches,
                offline=True,
                limit=10,
            )

        self.assertEqual(client.calls, [])
        self.assertEqual(samples, [])


class OpenDotaMatchClientTests(unittest.TestCase):
    def test_match_helper_uses_expected_endpoint(self):
        from unittest import mock

        from scout.opendota import OpenDota

        client = object.__new__(OpenDota)
        with mock.patch.object(
            client,
            "get",
            return_value={"match_id": 100},
        ) as get:
            self.assertEqual(client.match(100), {"match_id": 100})
        get.assert_called_once_with("/matches/100")


if __name__ == "__main__":
    unittest.main()
