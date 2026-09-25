"""RD2L HTML parsing and match cache. No network."""

from scout.bbc_source import index_official_matches
from scout.rd2l_source import (
    load_rd2l_matches,
    match_ids,
    parse_matchups,
    parse_rd2l,
    parse_roster_page,
    parse_standings,
    parse_team_list,
)


class Heroes:
    def name(self, hero_id):
        return {1: "Anti-Mage", 2: "Axe"}.get(hero_id, f"Hero {hero_id}")

TEAMS_HTML = """
<table><tbody>
<tr><td><a href="/seasons/S/divisions/D/teams/abc">Jiggy</a><span> (Jiggy)</span></td><td>1</td></tr>
<tr><td><a href="/seasons/S/divisions/D/teams/def">Ducks</a><span> (Duck)</span></td><td>2</td></tr>
</tbody></table>
"""

STANDINGS_HTML = """
<table><tbody>
<tr><td>1</td><td><a href="/seasons/S/divisions/D/teams/def">Ducks</a><span> (Duck)</span></td><td><img src=""></td><td>2</td><td>0</td><td>1</td></tr>
<tr><td>2</td><td><a href="/seasons/S/divisions/D/teams/abc">Jiggy</a><span> (Jiggy)</span></td><td><img src=""></td><td>1</td><td>1</td><td>0</td></tr>
</tbody></table>
"""

MATCHUPS_HTML = """
<table><thead><tr><th>Home Team</th><th>Away Team</th></tr></thead><tbody>
<tr><td><a href="/seasons/S/divisions/D/teams/abc">Jiggy</a><span> (Jiggy)</span></td><td><a href="/seasons/S/divisions/D/teams/def">Ducks</a><span> (Duck)</span></td></tr>
</tbody></table>
"""

JIGGY_HTML = """
<title>RD2L : Season 39 - Jiggy Roster</title>
<h5 class="title is-5"><span>Record: 1 - 1</span></h5>
<h5 class="title is-5"><span>Division: <a href="/divisions/D">EST-TUES</a></span></h5>
<h5 class="title is-5"><span>Captain</span></h5>
<a href="/profile/132324147"><strong>Jiggy</strong></a>
<h5 class="title is-5"><span>Players</span></h5>
<table><tbody>
<tr><td><a href="/profile/108954137">blurry</a></td><td></td><td><img class="image rank is-48x48" src="/assets/medals/62.png" alt="62"></td></tr>
<tr><td><a href="/profile/156404497">Hollywood</a></td><td></td><td><img class="image rank is-48x48" src="/assets/medals/14.png" alt="14"></td></tr>
</tbody></table>
<a href="https://www.dotabuff.com/matches/9001087727">game</a>
"""


def test_parse_division_pages():
    teams = parse_team_list(TEAMS_HTML)
    assert [row["name"] for row in teams] == ["Jiggy", "Ducks"]
    standings = parse_standings(STANDINGS_HTML)
    jiggy = next(row for row in standings if row["name"] == "Jiggy")
    assert (jiggy["place"], jiggy["wins"], jiggy["losses"]) == (2, 1, 1)
    matchups = parse_matchups(MATCHUPS_HTML)
    assert matchups == [{
        "homeId": "abc", "home": "Jiggy", "awayId": "def", "away": "Ducks",
    }]


def test_roster_page_puts_captain_first():
    page = parse_roster_page(JIGGY_HTML)
    assert [player["id"] for player in page["players"]] == [132324147, 108954137, 156404497]
    assert page["players"][0]["captain"] is True
    assert page["division"] == "EST-TUES"
    assert page["wins"] == 1 and page["losses"] == 1
    assert page["matchIds"] == [9001087727]


def test_parse_rd2l_labels_the_league():
    data = parse_rd2l(
        {"abc": JIGGY_HTML, "def": ""},
        STANDINGS_HTML,
        MATCHUPS_HTML,
        TEAMS_HTML,
        39,
    )
    assert data["league"] == "RD2L EST-TUES Season 39"
    jiggy = next(team for team in data["teams"] if team["key"] == "jiggy")
    assert jiggy["roster"] == [132324147, 108954137, 156404497]
    assert jiggy["league"] == data["league"]
    assert data["matchups"][0]["aKey"] == "jiggy"
    assert data["matchups"][0]["bKey"] == "ducks"
    assert data["matchups"][0]["league"] == data["league"]
    assert {row["key"] for row in data["standings"]} == {"jiggy", "ducks"}


def _player(account_id, slot, hero_id, win_side):
    return {
        "account_id": account_id,
        "player_slot": slot,
        "hero_id": hero_id,
        "kills": 1,
        "deaths": 2,
        "assists": 3,
        "gold_per_min": 400,
        "xp_per_min": 500,
        "isRadiant": slot < 128,
    }


def test_match_ids_are_unique():
    data = {"teams": [
        {"matchIds": [5, 5, "6"]},
        {"matchIds": [6, 7]},
    ]}
    assert match_ids(data) == [5, 6, 7]


def test_index_official_matches_uses_roster_when_lobby_name_differs():
    radiant = [1, 2, 3, 4, 5]
    dire = [6, 7, 8, 9, 10]
    players = [_player(sid, index, 1, True) for index, sid in enumerate(radiant)]
    players += [_player(sid, 128 + index, 2, False) for index, sid in enumerate(dire)]
    raw = {
        "match_id": 42,
        "start_time": 100,
        "duration": 1800,
        "radiant_win": True,
        "radiant_name": "Radiant",
        "dire_name": "Dire",
        "players": players,
    }
    teams = [
        {"key": "jiggy", "name": "Jiggy", "short": "Jiggy", "roster": radiant},
        {"key": "ducks", "name": "Ducks", "short": "Ducks", "roster": dire},
    ]
    official, team_matches, team_games = index_official_matches(
        {42: raw}, teams, Heroes(), "RD2L EST-TUES Season 39",
    )
    assert team_matches[0]["radiant"]["team_key"] == "jiggy"
    assert team_matches[0]["dire"]["team_key"] == "ducks"
    assert official[1][0]["result"] == "W"
    assert official[1][0]["opponent_key"] == "ducks"
    assert official[6][0]["result"] == "L"
    assert team_games["jiggy"][1] == 1


def test_load_rd2l_matches_skips_ids_already_cached(tmp_path):
    path = tmp_path / "rd2l_matches.json"
    path.write_text(
        '{"fetchedAt": 1, "matches": {"42": {"match_id": 42, "players": [{"account_id": 1}]}}}',
        encoding="utf-8",
    )
    rd2l = {"teams": [{"matchIds": [42, 43]}]}
    calls = []

    def fetcher(match_id):
        calls.append(match_id)
        return {"match_id": match_id, "players": [{"account_id": 9}]}

    loaded = load_rd2l_matches(rd2l, fetcher=fetcher, path=str(path))
    assert calls == [43]
    assert set(loaded) == {42, 43}
    again = load_rd2l_matches(rd2l, fetcher=fetcher, path=str(path))
    assert calls == [43]
    assert set(again) == {42, 43}
