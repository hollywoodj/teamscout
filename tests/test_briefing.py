import pytest

from scout.briefing import (
    KEY_READS_FIELD_NAME, LIMIT_FIELD_VALUE, LIMIT_TOTAL,
    _enforce_limits, briefing_text, build_briefing,
)

HEROES = {
    1: {"n": "Hero One", "key": "h1"},
    2: {"n": "Hero Two", "key": "h2"},
    3: {"n": "Hero Three", "key": "h3"},
    4: {"n": "Hero Four", "key": "h4"},
    5: {"n": "Hero Five", "key": "h5"},
    6: {"n": "Hero Six", "key": "h6"},
    7: {"n": "Hero Seven", "key": "h7"},
}


def _team_match(match_id, start_time, duration, radiant_key, dire_key,
                 radiant_win, picks_bans):
    def side_players(base_id):
        return [{
            "id": base_id + i, "name": f"P{base_id + i}", "hero_id": 1,
            "kills": 5, "deaths": 3, "assists": 6, "gpm": 500, "xpm": 550,
            "lane_eff": 60, "obs_placed": 1, "sen_placed": 1,
            "obs_kills": 0, "sen_kills": 0, "stuns": 2.0, "camps_stacked": 1,
            "towers_killed": 0, "roshans_killed": 0, "buybacks": 0,
            "firstblood": (i == 0), "teamfight": 0.5, "hero_damage": 8000,
        } for i in range(5)]

    return {
        "match_id": match_id, "start_time": start_time, "duration": duration,
        "series_id": None,
        "radiant": {"name": "Radiant", "team_key": radiant_key,
                    "players": side_players(1)},
        "dire": {"name": "Dire", "team_key": dire_key,
                 "players": side_players(11)},
        "radiant_win": radiant_win,
        "picks_bans": picks_bans,
        "patch": 60,
        "radiant_score": 20, "dire_score": 15, "first_blood_time": 90,
    }


def _official_row(team_key, opponent_key, result, hero_id, position, **extra):
    row = {
        "match_id": 1, "start_time": 100, "league_name": "LD2L", "patch": 60,
        "team": "Team Alpha", "opponent": "Team Beta", "opponent_key": opponent_key,
        "team_key": team_key, "player_name": "Player", "hero_id": hero_id,
        "hero": HEROES[hero_id]["n"], "result": result,
        "kills": 5, "deaths": 3, "assists": 4, "gpm": 500, "xpm": 550,
        "last_hits": 100, "denies": 5, "net_worth": 10000,
        "hero_damage": 8000, "tower_damage": 500, "healing": 0,
        "lane_eff": 60, "lane_role": 1, "is_roaming": False, "is_radiant": True,
        "observer_wards": 1, "sentry_wards": 1, "obs_map": [], "sen_map": [],
        "dewards": 0, "duration": 1800, "teamfight": 0.5, "obs_placed": 1,
        "sen_placed": 1, "obs_kills": 0, "sen_kills": 0, "stuns": 2.0,
        "camps_stacked": 1, "rune_pickups": 1, "towers_killed": 0,
        "roshans_killed": 0, "buybacks": 0, "firstblood": False,
        "position": position, "position_confidence": "high",
    }
    row.update(extra)
    return row


def build_fixture():
    picks_bans_g1 = [
        {"hero_id": 1, "is_pick": True, "team": 0, "order": 0},
        {"hero_id": 2, "is_pick": True, "team": 1, "order": 1},
        {"hero_id": 3, "is_pick": False, "team": 0, "order": 2},
        {"hero_id": 4, "is_pick": False, "team": 1, "order": 3},
    ]
    picks_bans_g2 = [
        {"hero_id": 1, "is_pick": True, "team": 0, "order": 0},
        {"hero_id": 3, "is_pick": False, "team": 0, "order": 1},
        {"hero_id": 4, "is_pick": False, "team": 1, "order": 2},
    ]
    picks_bans_g3 = [
        {"hero_id": 2, "is_pick": True, "team": 1, "order": 0},
        {"hero_id": 5, "is_pick": False, "team": 1, "order": 1},
        {"hero_id": 6, "is_pick": False, "team": 0, "order": 2},
    ]
    picks_bans_g4 = [
        {"hero_id": 2, "is_pick": True, "team": 1, "order": 0},
        {"hero_id": 5, "is_pick": False, "team": 1, "order": 1},
        {"hero_id": 6, "is_pick": False, "team": 0, "order": 2},
    ]

    team_matches = [
        _team_match(1, 100, 1700, "teamalpha", "teambeta", True, picks_bans_g1),
        _team_match(2, 200, 1900, "teamalpha", "teambeta", True, picks_bans_g2),
        _team_match(3, 300, 2500, "teambeta", "teamalpha", True, picks_bans_g3),
        _team_match(4, 400, 2600, "teambeta", "teamalpha", True, picks_bans_g4),
    ]

    # Player 1: 4 official rows, one with a missing "kills" value that
    # per-game averages must skip rather than treat as zero.
    player1_rows = [
        _official_row("teamalpha", "teambeta", "W", 1, 1, kills=10, deaths=2,
                       assists=5, gpm=650, teamfight=0.6, firstblood=True),
        _official_row("teamalpha", "teambeta", "W", 1, 1, kills=8, deaths=1,
                       assists=4, gpm=700, teamfight=0.5),
        _official_row("teamalpha", "teambeta", "L", 2, 1, kills=None, deaths=5,
                       assists=2, gpm=500, teamfight=0.4),
        _official_row("teamalpha", "teambeta", "L", 1, 1, kills=3, deaths=6,
                       assists=1, gpm=450, teamfight=0.3, buybacks=1),
    ]
    player2_rows = [
        _official_row("teamalpha", "teambeta", "W", 3, 2, kills=4, deaths=3,
                       assists=8, teamfight=0.65, obs_kills=2, sen_kills=1),
        _official_row("teamalpha", "teambeta", "L", 3, 2, kills=2, deaths=5,
                       assists=6, teamfight=0.55, obs_kills=1, sen_kills=0),
    ]
    player3_rows = [
        _official_row("teamalpha", "teambeta", "W", 4, 3, kills=3, deaths=2,
                       assists=10, teamfight=0.7),
        _official_row("teamalpha", "teambeta", "L", 4, 3, kills=1, deaths=4,
                       assists=7, teamfight=0.6),
    ]
    # Player 4: zero official rows for this team -> "no official games" path.
    player4_rows = []
    # Player 5: exactly one official row -> stat lines shown, hero line falls
    # back to heroPool (fewer than 2 official games).
    player5_rows = [
        _official_row("teamalpha", "teambeta", "W", 6, 5, kills=1, deaths=8,
                       assists=12, teamfight=0.2, obs_kills=3, sen_kills=2),
    ]

    def hero_pool(entries):
        return {"heroes": [
            {"id": hid, "lifetime": {"games": g, "wins": w, "last": 0},
             "recent": {"games": 0, "wins": 0, "kda": None, "gpm": None, "kdaDelta": None},
             "official": {"games": 0, "wins": 0}, "esports": {"games": 0, "wins": 0},
             "position": None, "score": 0.5, "tags": [], "metaWr": None}
            for hid, g, w in entries
        ], "gems": [], "baseline": {"games": 0, "wins": 0, "winrate": None, "kda": None},
            "pubWindowDays": 180}

    players = [
        {"id": 1, "name": "Alice", "rank": "Divine", "mmr": 5000,
         "official": {"status": "bbc", "games": len(player1_rows),
                       "wins": 2, "winrate": 50.0, "matches": player1_rows},
         "heroPool": hero_pool([(1, 8, 5)])},
        {"id": 2, "name": "Bob", "rank": "Ancient", "mmr": 4500,
         "official": {"status": "bbc", "games": len(player2_rows),
                       "wins": 1, "winrate": 50.0, "matches": player2_rows},
         "heroPool": hero_pool([(3, 6, 3)])},
        {"id": 3, "name": "Cara", "rank": "Legend", "mmr": 3800,
         "official": {"status": "bbc", "games": len(player3_rows),
                       "wins": 1, "winrate": 50.0, "matches": player3_rows},
         "heroPool": hero_pool([(4, 5, 2)])},
        {"id": 4, "name": "Dee", "rank": "Archon", "mmr": 3000,
         "official": {"status": "unavailable", "games": 0, "wins": 0,
                       "winrate": None, "matches": player4_rows},
         "heroPool": hero_pool([(7, 10, 6), (1, 5, 2)])},
        {"id": 5, "name": "Eli", "rank": "Crusader", "mmr": 2200,
         "official": {"status": "bbc", "games": len(player5_rows),
                       "wins": 1, "winrate": 100.0, "matches": player5_rows},
         "heroPool": hero_pool([(6, 4, 3)])},
    ]

    teams = [
        {"key": "teamalpha", "name": "Team Alpha", "short": "ALPHA",
         "record": "2-2", "captain": "Alice", "roster": [1, 2, 3, 4, 5],
         "replacements": [], "league": "LD2L"},
        {"key": "teambeta", "name": "Team Beta", "short": "BETA",
         "record": "2-2", "captain": "Zed", "roster": [11, 12, 13, 14, 15],
         "replacements": [], "league": "LD2L"},
    ]

    standings = [
        {"name": "Team Alpha", "short": "ALPHA", "wins": 2, "losses": 2,
         "record": "2-2", "key": "teamalpha", "rank": 1, "league": "LD2L"},
        {"name": "Team Beta", "short": "BETA", "wins": 2, "losses": 2,
         "record": "2-2", "key": "teambeta", "rank": 1, "league": "LD2L"},
    ]

    matchups = [
        {"a": "Team Alpha", "aShort": "ALPHA", "aKey": "teamalpha",
         "b": "Team Beta", "bShort": "BETA", "bKey": "teambeta",
         "week": 5, "league": "LD2L"},
    ]

    return {
        "season": "Season 53", "seasonId": 53, "generatedAt": 1_800_000_000,
        "patches": [], "teams": teams, "matchups": matchups,
        "standings": standings, "teamMatches": team_matches, "heroes": HEROES,
        "officialSource": {"available": True, "league": "LD2L Season 53",
                            "generated": "2026-09-20", "week": 5},
        "players": players,
    }


def test_team_resolution_exact_fuzzy_and_missing():
    payload = build_fixture()
    assert build_briefing(payload, "Team Alpha")["title"].startswith("ALPHA")
    assert build_briefing(payload, "alpha")["title"].startswith("ALPHA")
    assert build_briefing(payload, "teamalpha")["title"].startswith("ALPHA")
    with pytest.raises(ValueError):
        build_briefing(payload, "Team Nowhere")


def test_default_vs_uses_current_matchup():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    assert "BETA" in embed["description"].splitlines()[0]


def test_form_strip_and_streak():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    form_line = embed["description"].splitlines()[1]
    assert "\U0001F7E9\U0001F7E9\U0001F7E5\U0001F7E5" in form_line
    assert "L2" in form_line


def test_side_split_key_read():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    key_reads = next(f for f in embed["fields"] if f["name"] == KEY_READS_FIELD_NAME)
    assert "Radiant" in key_reads["value"] and "Dire" in key_reads["value"]


def test_per_game_averages_ignore_none():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    alice_field = next(f for f in embed["fields"] if "Alice" in f["name"])
    # kills across (10, 8, 3), skipping the row with kills=None -> avg 7.0
    assert "7.0/" in alice_field["value"]


def test_no_official_games_player_falls_back_to_hero_pool():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    dee_field = next(f for f in embed["fields"] if "Dee" in f["name"])
    assert "No official games for this team yet" in dee_field["value"]
    assert "pubs:" in dee_field["value"]
    assert "Hero Seven" in dee_field["value"]


def test_thin_sample_player_uses_hero_pool_for_hero_line():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    eli_field = next(f for f in embed["fields"] if "Eli" in f["name"])
    assert "No official games" not in eli_field["value"]
    assert "pubs:" in eli_field["value"]


def test_draft_side_mapping_uses_team_index():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    draft_field = next(f for f in embed["fields"] if "Draft" in f["name"])
    assert "Hero One" in draft_field["value"]
    assert "Hero Two" in draft_field["value"]
    assert "Picks:" in draft_field["value"]
    assert "Bans:" in draft_field["value"]
    assert "Banned vs:" in draft_field["value"]


def test_briefing_text_renders_plain_text():
    payload = build_fixture()
    embed = build_briefing(payload, "Team Alpha")
    text = briefing_text(embed)
    assert "SCOUT BRIEFING" in text
    assert "ALPHA" in text


def test_enforce_limits_caps_total_and_trims_key_reads_first():
    embed = {
        "author": {"name": "Scout"},
        "title": "T" * 300,
        "description": "D" * 5000,
        "color": 0,
        "fields": [
            {"name": "Big field", "value": "X" * 2000, "inline": True},
            {"name": KEY_READS_FIELD_NAME,
             "value": "\n".join(f"bullet {i} " + "y" * 200 for i in range(20)),
             "inline": False},
        ],
        "footer": {"text": "F" * 3000},
    }
    _enforce_limits(embed)
    total = (len(embed["title"]) + len(embed["description"])
             + len(embed["footer"]["text"]) + len(embed["author"]["name"])
             + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"]))
    assert total <= LIMIT_TOTAL
    for field in embed["fields"]:
        assert len(field["value"]) <= LIMIT_FIELD_VALUE
    assert len(embed["title"]) <= 256
    assert len(embed["footer"]["text"]) <= 2048
