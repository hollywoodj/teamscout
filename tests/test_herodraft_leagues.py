"""League selection contracts for the Team Scout mock draft."""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from scout.herodraft import load_league_context


class HeroDraftLeagueTests(unittest.TestCase):
    def test_rd2l_cached_teams_join_the_draft_pool(self):
        rd2l = {
            "league": "RD2L EST-TUES",
            "teams": [
                {"id": "a", "key": "pond", "name": "Pond", "captain": "Ada",
                 "roster": [2]},
                {"id": "b", "key": "wolves", "name": "Wolves", "captain": "Bea",
                 "roster": [3]},
            ],
            "players": [{"id": 2, "name": "Ada", "rankTier": None},
                        {"id": 3, "name": "Bea", "rankTier": 0}],
        }
        bbc = {"teams": [], "players": {}, "official": {}, "teamMatches": []}
        with ExitStack() as stack:
            for target, value in (
                ("scout.heroes.load_hero_map", {}),
                ("scout.bbc_source.load_bbc_data", bbc),
                ("scout.overrides.load_overrides",
                 {"accounts": {}, "rosters": {}, "replaced": {}}),
                ("scout.team_scout._all_pulled_players", {}),
                ("scout.rd2l_source.load_rd2l", rd2l),
                ("scout.rd2l_source.load_rd2l_matches", {}),
            ):
                stack.enter_context(patch(target, return_value=value))
            stack.enter_context(patch("scout.herodraft.fetch_player_sections",
                                      return_value=({"profile": {"rank_tier": 80,
                                                                  "profile": {"avatarfull": "https://example.test/avatar.jpg"}}}, None)))
            rows, profiles = [], {}
            league = load_league_context(None, None, profiles, rows)

        self.assertEqual({t["key"] for t in league["teams"]}, {"pond", "wolves"})
        self.assertTrue(all(t["league"] == "rd2l" for t in league["teams"]))
        self.assertEqual({p["steam32"] for p in rows}, {2, 3})
        self.assertEqual({p["steam32"]: p["rankTier"] for p in rows},
                         {2: 80, 3: 80})
        self.assertTrue(all(p["avatar"] == "https://example.test/avatar.jpg"
                            for p in rows))
        self.assertEqual(set(league["books"]), {"pond", "wolves"})


if __name__ == "__main__":
    unittest.main()
