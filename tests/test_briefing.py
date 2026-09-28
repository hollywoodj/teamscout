import pytest

from scout.briefing import (
    LIMIT_COMPONENTS, LIMIT_TEXT_TOTAL, TYPE_CONTAINER, TYPE_MEDIA_GALLERY,
    TYPE_SECTION, TYPE_SEPARATOR, TYPE_TEXT_DISPLAY, TYPE_THUMBNAIL,
    _count_components, _text_chars, build_briefing_page, build_recon_page, build_wards_page,
    page_text,
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
                 radiant_win, picks_bans, patch=60):
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
        "patch": patch,
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
                       assists=5, gpm=650, teamfight=0.6, firstblood=True,
                       obs_map=[[100, 100]], sen_map=[], is_radiant=True, patch=60),
        _official_row("teamalpha", "teambeta", "W", 1, 1, kills=8, deaths=1,
                       assists=4, gpm=700, teamfight=0.5,
                       obs_map=[[101, 101]], sen_map=[], is_radiant=True, patch=60),
        _official_row("teamalpha", "teambeta", "L", 2, 1, kills=None, deaths=5,
                       assists=2, gpm=500, teamfight=0.4, is_radiant=False, patch=60),
        _official_row("teamalpha", "teambeta", "L", 1, 1, kills=3, deaths=6,
                       assists=1, gpm=450, teamfight=0.3, buybacks=1,
                       is_radiant=False, patch=60),
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
         "heroPool": hero_pool([(1, 8, 5)]), "pubWards": []},
        {"id": 2, "name": "Bob", "rank": "Ancient", "mmr": 4500,
         "official": {"status": "bbc", "games": len(player2_rows),
                       "wins": 1, "winrate": 50.0, "matches": player2_rows},
         "heroPool": hero_pool([(3, 6, 3)]), "pubWards": []},
        {"id": 3, "name": "Cara", "rank": "Legend", "mmr": 3800,
         "official": {"status": "bbc", "games": len(player3_rows),
                       "wins": 1, "winrate": 50.0, "matches": player3_rows},
         "heroPool": hero_pool([(4, 5, 2)]), "pubWards": []},
        {"id": 4, "name": "Dee", "rank": "Archon", "mmr": 3000,
         "official": {"status": "unavailable", "games": 0, "wins": 0,
                       "winrate": None, "matches": player4_rows},
         "heroPool": hero_pool([(7, 10, 6), (1, 5, 2)]), "pubWards": []},
        {"id": 5, "name": "Eli", "rank": "Crusader", "mmr": 2200,
         "official": {"status": "bbc", "games": len(player5_rows),
                       "wins": 1, "winrate": 100.0, "matches": player5_rows},
         "heroPool": hero_pool([(6, 4, 3)]), "pubWards": []},
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
        "patches": [{"id": 60, "name": "7.41"}], "teams": teams, "matchups": matchups,
        "standings": standings, "teamMatches": team_matches, "heroes": HEROES,
        "officialSource": {"available": True, "league": "LD2L Season 53",
                            "generated": "2026-09-20", "week": 5},
        "players": players,
    }


def test_team_resolution_exact_fuzzy_and_missing():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "ALPHA" in text
    page2 = build_briefing_page(payload, "alpha")
    assert "ALPHA" in page_text(page2["components"])
    page3 = build_briefing_page(payload, "teamalpha")
    assert "ALPHA" in page_text(page3["components"])
    with pytest.raises(ValueError):
        build_briefing_page(payload, "Team Nowhere")


def test_team_header_puts_record_beside_name_without_subheader():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert text.splitlines()[1] == "## ALPHA · 2-2"
    assert "Up next vs" not in text
    assert "No upcoming matchup posted" not in text


def test_team_profile_uses_league_ranks_instead_of_raw_team_gpm():
    text = page_text(build_briefing_page(build_fixture(), "Team Alpha")["components"])
    assert "__League ranks__" in text
    assert "GPM #1/2" in text
    assert "XPM #1/2" in text
    assert "#1 means most" in text


def test_briefing_omits_form_strip():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "**Form**" not in text
    assert "\U0001F7E9" not in text
    assert "\U0001F7E5" not in text


def test_single_container_with_accent_color():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    assert len(page["components"]) == 1
    container = page["components"][0]
    assert container["type"] == TYPE_CONTAINER
    assert container["accent_color"] == 0xE74C3C


def test_side_split_key_read():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "Key reads" in text
    assert "-sided" in text


def test_per_game_averages_ignore_none():
    payload = build_fixture()
    payload["players"][0]["official"]["matches"][2]["gpm"] = None
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    # GPM across (650, 700, 450), skipping the missing value -> avg 600.
    assert "600 GPM · 4 games" in text


def test_no_official_games_does_not_show_pub_heroes():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    dee_block = text[text.index("Dee"):].split("\n\n")[0]
    assert "No official games for this team yet" in dee_block
    assert "**Heroes**" in dee_block
    assert "Hero Seven" not in dee_block


def test_one_official_game_shows_its_hero_only():
    payload = build_fixture()
    pub = dict(payload["players"][4]["heroPool"]["heroes"][0])
    pub["id"] = 7
    payload["players"][4]["heroPool"]["heroes"].append(pub)
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    eli_block = text[text.index("Eli"):].split("\n\n")[0]
    assert "Hero Six 1-0" in eli_block
    assert "Hero Seven" not in eli_block


def test_player_section_lists_every_official_hero_for_this_team():
    payload = build_fixture()
    matches = payload["players"][0]["official"]["matches"]
    for hero_id in (3, 4, 5):
        matches.append(_official_row("teamalpha", "teambeta", "W", hero_id, 1))
    matches.append(_official_row("teambeta", "teamalpha", "W", 7, 1))
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    alice_block = text[text.index("Alice"):text.index("Bob")]
    heroes_line = next(line for line in alice_block.splitlines()
                       if line.startswith("**Heroes**"))
    for name in ("Hero One", "Hero Two", "Hero Three", "Hero Four", "Hero Five"):
        assert name in heroes_line
    assert "Hero Seven" not in heroes_line
    assert heroes_line.index("Hero One") < heroes_line.index("Hero Two")


def test_player_heroes_sort_by_win_rate_then_games():
    payload = build_fixture()
    payload["players"][0]["official"]["matches"] = [
        _official_row("teamalpha", "teambeta", result, hero_id, 1)
        for hero_id, results in ((1, "WWL"), (2, "W"), (3, "WW"), (4, "LL"))
        for result in results
    ]
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    alice_block = text[text.index("Alice"):text.index("Bob")]
    heroes_line = next(line for line in alice_block.splitlines()
                       if line.startswith("**Heroes**"))
    assert (heroes_line.index("Hero Three") < heroes_line.index("Hero Two")
            < heroes_line.index("Hero One") < heroes_line.index("Hero Four"))


def test_all_official_heroes_survive_discord_text_budget():
    payload = build_fixture()
    for player in payload["players"]:
        player["official"]["matches"].extend(
            _official_row("teamalpha", "teambeta", "W", hero_id, 1)
            for hero_id in range(1, 8)
        )
    emoji = {str(hero_id): f"<:a_very_long_hero_emoji_name_{hero_id}:123456789012345678>"
             for hero_id in range(1, 8)}
    page = build_briefing_page(payload, "Team Alpha", hero_emoji=emoji)
    text = page_text(page["components"])
    assert _text_chars(page["components"]) <= LIMIT_TEXT_TOTAL
    hero_lines = [line for line in text.splitlines() if line.startswith("**Heroes** ")]
    assert len(hero_lines) == 5
    for line in hero_lines:
        for hero_id, token in emoji.items():
            assert token in line
            assert HEROES[int(hero_id)]["n"] not in line


def test_draft_side_mapping_uses_team_index():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    draft_block = text[text.index("Draft"):text.index("Players")]
    assert "Hero One" in draft_block or "H1" not in draft_block  # no emoji -> full/short name fallback
    assert "**Most picked**" in draft_block
    assert "**Their bans**" in draft_block
    assert "**Banned against them**" in draft_block


def test_keycaps_use_variation_selector_16():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "1️⃣" in text
    assert "2️⃣" in text


def test_hero_emoji_substitution_with_map():
    payload = build_fixture()
    hero_emoji = {"1": "<:h_heroone:111>", "3": "<:h_herothree:333>"}
    page = build_briefing_page(payload, "Team Alpha", hero_emoji=hero_emoji)
    text = page_text(page["components"])
    assert "<:h_heroone:111>" in text
    alice_block = text[text.index("Alice"):text.index("Bob")]
    heroes_line = next(line for line in alice_block.splitlines()
                       if line.startswith("**Heroes**"))
    assert "<:h_heroone:111> 2-1" in heroes_line
    assert "Hero One" not in heroes_line
    assert "Hero Two" in heroes_line  # missing emoji still has a readable fallback


def test_medal_badge_replaces_rank_text_before_name_in_briefing():
    payload = build_fixture()
    payload["players"][0]["rankTier"] = 75
    page = build_briefing_page(payload, "Team Alpha",
                               medal_emoji={"75": "<:medal_75:123>"})
    text = page_text(page["components"])
    assert "<:medal_75:123> **__Alice__**" in text
    assert "**__Alice__** · Divine" not in text


def test_medal_badge_replaces_rank_text_before_name_in_recon():
    payload = build_fixture()
    payload["players"][0]["rankTier"] = 75
    page = build_recon_page(payload, "Team Alpha", now=1_780_000_000,
                            medal_emoji={"75": "<:medal_75:123>"})
    text = page_text(page["components"])
    assert "<:medal_75:123> **Alice**" in text
    assert "**Alice** · Divine" not in text


def test_hero_emoji_substitution_without_map_uses_short_names():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha", hero_emoji=None)
    text = page_text(page["components"])
    assert "<:h_" not in text


def test_player_thumbnails_use_steam_avatars_even_without_official_games():
    payload = build_fixture()
    payload["players"][0]["avatar"] = "https://avatars.steamstatic.com/alice_full.jpg"
    payload["players"][3]["avatar"] = "https://avatars.steamstatic.com/dee_full.jpg"
    page = build_briefing_page(payload, "Team Alpha")
    container = page["components"][0]
    sections = [c for c in container["components"] if c.get("type") == TYPE_SECTION]
    assert len(sections) == 2
    assert all(section["accessory"]["type"] == TYPE_THUMBNAIL for section in sections)
    assert [section["accessory"]["media"]["url"] for section in sections] == [
        "https://avatars.steamstatic.com/alice_full.jpg",
        "https://avatars.steamstatic.com/dee_full.jpg",
    ]


def test_thumbnail_absent_falls_back_to_plain_text_display():
    payload = build_fixture()
    payload["players"][0]["avatar"] = "not-a-url"
    page = build_briefing_page(payload, "Team Alpha")
    container = page["components"][0]
    sections = [c for c in container["components"] if c.get("type") == TYPE_SECTION]
    assert not sections


def test_page_text_renders_plain_text():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "SCOUT BRIEFING" in text
    assert "ALPHA" in text
    assert text.index("Key reads") < text.index("Draft") < text.index("Players")
    assert len([line for line in text.splitlines() if line.startswith("- **")]) <= 3
    assert "Team profile" not in text
    assert "**Combat**" not in text
    assert "**Teamfight**" not in text
    assert "**Vision**" not in text
    assert "**Stats**" in text


def test_no_flags_key_in_builder_output():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    assert "flags" not in page
    for component in page["components"]:
        assert "flags" not in component


def test_component_count_within_limit():
    payload = build_fixture()
    page = build_briefing_page(payload, "Team Alpha")
    assert _count_components(page["components"]) <= LIMIT_COMPONENTS


def test_text_budget_enforced_with_oversized_fixture():
    payload = build_fixture()
    # Blow up the roster to 20 players with long names and full hero pools,
    # and lots of official rows, to push well past the 4000-char budget.
    big_roster = []
    matches = []
    for i in range(20):
        pid = 100 + i
        rows = [
            _official_row("teamalpha", "teambeta", "W", (i % 7) + 1, (i % 5) + 1,
                           kills=10, deaths=2, assists=5)
            for _ in range(6)
        ]
        big_roster.append({
            "id": pid, "name": f"PlayerWithAVeryLongNameNumber{i}",
            "rank": "Divine 5",
            "official": {"status": "bbc", "games": len(rows), "wins": 3,
                         "winrate": 50.0, "matches": rows},
            "heroPool": {"heroes": [], "gems": [],
                         "baseline": {"games": 0, "wins": 0, "winrate": None, "kda": None},
                         "pubWindowDays": 180},
            "pubWards": [],
        })
        matches.append(_team_match(900 + i, 100 + i, 1800, "teamalpha", "teambeta", True, []))
    payload["players"].extend(big_roster)
    payload["teams"][0]["roster"] = payload["teams"][0]["roster"] + [p["id"] for p in big_roster]
    payload["teamMatches"].extend(matches)

    page = build_briefing_page(payload, "Team Alpha")
    assert _text_chars(page["components"]) <= LIMIT_TEXT_TOTAL
    assert _count_components(page["components"]) <= LIMIT_COMPONENTS


# --------------------------------------------------------------------------
# Recon page
# --------------------------------------------------------------------------

def test_recon_uses_scouted_team_weekly_pubs_even_with_vs_selected():
    from datetime import datetime

    payload = build_fixture()
    # A fixed Wednesday; Monday is Sep 21, 2026 in the bot's local zone.
    now = datetime(2026, 9, 23, 12).timestamp()
    monday = datetime(2026, 9, 21).timestamp()
    payload["players"][0].update(private=False, matches=[
            {"id": 900, "at": monday + 100, "hero": 1, "win": True, "lobby": 0, "mode": 2},
            {"id": 901, "at": monday + 200, "hero": 1, "win": False, "lobby": 7, "mode": 2},
            {"id": 902, "at": monday + 300, "hero": 2, "win": True, "lobby": 1, "mode": 2},
            {"id": 903, "at": monday + 400, "hero": 2, "win": True, "lobby": 0, "mode": 23},
            {"id": 904, "at": monday - 100, "hero": 2, "win": True, "lobby": 0, "mode": 2},
        ])
    payload["players"][1].update(private=True, matches=[
            {"id": 900, "at": monday + 100, "hero": 1, "win": True, "lobby": 0, "mode": 2},
        ])
    payload["players"].extend([
        {"id": 11, "name": "Zed", "matches": [
            {"id": 990, "at": monday + 100, "hero": 2, "win": True, "lobby": 0, "mode": 2}]},
        {"id": 12, "name": "Yen", "matches": []},
    ])
    page = build_recon_page(payload, "Team Alpha", vs="Team Beta", now=now)
    text = page_text(page["components"])
    assert "Team Alpha · Recon" in text
    assert "3 player-games" in text
    assert "2/5" in text
    assert "Unique heroes** 1" in text
    assert "Private profiles** Bob" in text
    assert "Most played this week" in text
    assert "Match 900" in text
    assert "902" not in text and "903" not in text and "904" not in text
    assert "Zed" not in text and "Yen" not in text and "990" not in text
    assert "By player" in text
    assert _text_chars(page["components"]) <= LIMIT_TEXT_TOTAL
    assert _count_components(page["components"]) <= LIMIT_COMPONENTS


def test_recon_does_not_need_an_upcoming_opponent():
    payload = build_fixture()
    payload["matchups"] = []
    page = build_recon_page(payload, "Team Alpha")
    text = page_text(page["components"])
    assert "Team Alpha · Recon" in text
    assert "No upcoming opponent" not in text


# --------------------------------------------------------------------------
# Wards page
# --------------------------------------------------------------------------

def _wards_fixture():
    payload = build_fixture()
    for row in payload["players"][0]["official"]["matches"]:
        row["patch"] = 60
        row["position"] = 4
    payload["players"][0]["official"]["matches"][0].update(
        is_radiant=True, obs_map=[[100, 100]], sen_map=[[110, 110]])
    payload["players"][0]["official"]["matches"][1].update(
        is_radiant=True, obs_map=[[101, 101]], sen_map=[])
    for row in payload["players"][0]["official"]["matches"][2:]:
        row.update(is_radiant=False)
    payload["teams"][0]["roster"] = [1]
    return payload


def test_wards_page_single_container_with_media_gallery():
    payload = _wards_fixture()
    page = build_wards_page(payload, "Team Alpha")
    assert len(page["components"]) == 1
    container = page["components"][0]
    assert container["type"] == TYPE_CONTAINER
    galleries = [c for c in container["components"] if c.get("type") == TYPE_MEDIA_GALLERY]
    assert len(galleries) == 1
    assert galleries[0]["items"][0]["media"]["url"] == "attachment://ward-player-1.png"
    assert not any(c["type"] == TYPE_TEXT_DISPLAY for c in container["components"])


def test_wards_page_returns_png_file():
    payload = _wards_fixture()
    page = build_wards_page(payload, "Team Alpha")
    assert page["files"]
    filename, data = page["files"][0]
    assert filename == "ward-player-1.png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_wards_page_heatmap_mode_changes_game_maps_and_explains_colors():
    page = build_wards_page(_wards_fixture(), "Team Alpha", game_mode="heatmap")
    assert page["files"][0][0] == "ward-heatmap-player-1.png"
    text = [node["content"] for node in page["components"][0]["components"]
            if node["type"] == TYPE_TEXT_DISPLAY]
    assert any("Gold: observers" in line and "Brighter: more placements" in line
               for line in text)


def test_wards_page_full_maps_only_include_supports_and_exclude_mareth():
    payload = _wards_fixture()
    payload["teams"][0]["roster"] = [1, 3, 5]
    payload["players"][4]["official"]["matches"][0]["obs_map"] = [[120, 120]]
    payload["players"][2]["name"] = "Mareth"
    for row in payload["players"][2]["official"]["matches"]:
        row["position"] = 5
    page = build_wards_page(payload, "Team Alpha")
    galleries = [c for c in page["components"][0]["components"]
                 if c["type"] == TYPE_MEDIA_GALLERY]
    assert len(galleries) == 2
    assert all(len(gallery["items"]) == 1 for gallery in galleries)
    assert [name for name, _data in page["files"]] == [
        "ward-player-1.png", "ward-player-2.png"]


def test_wards_page_extra_images_appended():
    payload = _wards_fixture()
    extra = [("zoom.png", b"fakepngdata", "A zoomed detail")]
    page = build_wards_page(payload, "Team Alpha", extra_images=extra)
    container = page["components"][0]
    galleries = [c for c in container["components"] if c.get("type") == TYPE_MEDIA_GALLERY]
    assert len(galleries) == 2
    assert all(len(gallery["items"]) == 1 for gallery in galleries)
    assert galleries[0]["items"][0]["media"]["url"] == "attachment://zoom.png"
    filenames = [f for f, _b in page["files"]]
    assert "zoom.png" in filenames


def test_wards_page_puts_player_lane_sheet_before_full_map():
    payload = _wards_fixture()
    extra = [("lane-player-1.png", b"fakelanes", "Player lanes by side")]
    page = build_wards_page(payload, "Team Alpha", extra_images=extra)
    container = page["components"][0]
    galleries = [c for c in container["components"] if c.get("type") == TYPE_MEDIA_GALLERY]
    assert len(galleries) == 2
    assert galleries[0]["items"][0]["media"]["url"] == "attachment://lane-player-1.png"
    assert galleries[1]["items"][0]["media"]["url"] == "attachment://ward-player-1.png"

    filenames = [f for f, _b in page["files"]]
    assert filenames == ["lane-player-1.png", "ward-player-1.png"]

    headings = [c["content"] for c in container["components"]
                if c["type"] == TYPE_TEXT_DISPLAY]
    assert headings == ["### Lane Wards", "### Game Wards"]


def test_wards_page_groups_per_player_lane_sheets_before_full_maps():
    payload = _wards_fixture()
    images = [("lane-player-1.png", b"lane1", "Player 1 lanes"),
              ("lane-player-2.png", b"lane2", "Player 2 lanes")]
    page = build_wards_page(payload, "Team Alpha", extra_images=images)
    container = page["components"][0]["components"]
    assert [node["content"] for node in container if node["type"] == TYPE_TEXT_DISPLAY] == [
        "### Lane Wards", "### Game Wards"]
    assert [name for name, _data in page["files"]] == [
        "lane-player-1.png", "lane-player-2.png", "ward-player-1.png"]


def test_wards_page_uses_special_note_only_when_no_ward_data():
    payload = _wards_fixture()
    for row in payload["players"][0]["official"]["matches"]:
        row["obs_map"] = []
        row["sen_map"] = []
    page = build_wards_page(payload, "Team Alpha")
    container = page["components"][0]
    assert container["components"][0]["type"] == TYPE_TEXT_DISPLAY
    assert container["components"][0]["content"] == "Not enough ward data yet."
    assert container["components"][1]["type"] == TYPE_MEDIA_GALLERY
