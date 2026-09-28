"""Team ranks stay comparable across the full official league field."""

from unittest.mock import patch

from scout.team_rankings import team_rankings
from scout.team_scout_html import render_page


def _players(gpm, *, missing=False):
    return [{"gpm": None if missing and i == 0 else gpm,
             "kills": 5, "deaths": 3, "firstblood": i == 0}
            for i in range(5)]


def _payload():
    teams = [{"key": f"t{i}", "league": "LD2L", "name": f"Team {i}"}
             for i in range(1, 13)]
    matches = [{"radiant": {"team_key": f"t{i}", "players": _players(600 - i * 10)},
                "dire": {"team_key": f"t{i + 1}", "players": _players(600 - (i + 1) * 10,
                                                                      missing=i + 1 == 12)},
                "radiant_win": i % 4 == 1}
               for i in range(1, 13, 2)]
    teams.extend([{"key": "other", "league": "RD2L", "name": "Other"},
                  {"key": "other2", "league": "RD2L", "name": "Other 2"}])
    matches.append({"radiant": {"team_key": "other", "players": _players(999)},
                    "dire": {"team_key": "other2", "players": _players(400)},
                    "radiant_win": True})
    return {"teams": teams, "teamMatches": matches,
            "officialSource": {"league": "LD2L"}}


def test_gpm_ranks_across_twelve_teams_and_excludes_missing_totals():
    ranks = team_rankings(_payload())
    assert ranks["t1"]["metrics"]["gpm"]["rank"] == 1
    assert ranks["t1"]["metrics"]["gpm"]["total"] == 11
    assert ranks["t11"]["metrics"]["gpm"]["rank"] == 11
    assert ranks["t12"]["metrics"]["gpm"] == {"rank": None, "total": 11, "value": None}
    assert ranks["t12"]["games"] == 1
    assert ranks["other"]["metrics"]["gpm"]["rank"] == 1
    assert ranks["other"]["metrics"]["gpm"]["total"] == 2


def test_ties_share_place_and_next_place_skips():
    payload = _payload()
    payload["teamMatches"][0]["dire"]["players"] = _players(590)
    payload["teamMatches"][1]["radiant"]["players"] = _players(590)
    ranks = team_rankings(payload)
    assert ranks["t1"]["metrics"]["gpm"]["rank"] == 1
    assert ranks["t2"]["metrics"]["gpm"]["rank"] == 1
    assert ranks["t3"]["metrics"]["gpm"]["rank"] == 1
    assert ranks["t4"]["metrics"]["gpm"]["rank"] == 4


def test_page_embeds_ranks_for_team_ui():
    with patch("scout.team_scout_html._rank_icons_json", return_value="{}"):
        page = render_page(_payload())
    assert '"teamRankings":{' in page
    assert 'function teamRankingsPanel(side)' in page
    assert '"gpm":{"rank":1,"total":11' in page
