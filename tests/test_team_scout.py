import base64
import contextlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from scout.bbc_source import (
    _ward_points, _ward_purchases, bbc_source_stamp, load_bbc_data, team_key,
)
from scout.overrides import load_overrides, save_overrides
from scout import team_scout
from scout.team_scout import (apply_lane_results, assemble_team, build_player_record,
                              compact_match, deep_summary, infer_position,
                              normalize_patches, parse_steam_id_query)
from scout.team_scout_html import render_page


class Heroes:
    def name(self, hero_id):
        return {1: "Anti-Mage"}.get(hero_id, f"Hero {hero_id}")


def test_compact_match_infers_patch_and_result():
    patches = normalize_patches([
        {"id": 59, "name": "7.40", "date": "2025-12-16T00:00:00Z"},
        {"id": 60, "name": "7.41", "date": "2026-03-24T00:00:00Z"},
    ])
    row = compact_match({
        "match_id": 99,
        "start_time": 1775000000,
        "player_slot": 130,
        "radiant_win": False,
        "hero_id": 1,
        "hero_damage": 12345,
        "lobby_type": 7,
    }, patches)
    assert row["patch"] == 60
    assert row["win"] is True
    assert row["heroDamage"] == 12345
    assert row["position"] == 1
    assert row["positionConfidence"] == "high"
    assert row["obs"] is None
    assert row["sen"] is None
    assert row["laneResult"] is None
    assert row["lobby"] == 7


def test_is_pub_accepts_ranked_and_unranked_excludes_lobbies_and_turbo():
    from scout.team_scout import is_pub
    assert is_pub({"lobby": 0, "mode": 1}) is True
    assert is_pub({"lobby": 7, "mode": 22}) is True
    assert is_pub({"lobby": 1, "mode": 1}) is False  # practice lobby (league/inhouse)
    assert is_pub({"lobby": 0, "mode": 23}) is False  # turbo
    assert is_pub({"lobby": None, "mode": 1}) is False  # unknown lobby type, not assumed a pub


def test_ward_purchases_use_nested_purchase_and_treat_omitted_zeros_as_zero():
    assert _ward_purchases({
        "purchase_ward_observer": 17, "purchase_ward_sentry": 37,
    }) == (17, 37)
    assert _ward_purchases({"purchase": {"ward_observer": 4, "tango": 1}}) == (4, 0)
    assert _ward_purchases({
        "purchase": {"tango": 1}, "obs_placed": 0, "sen_placed": 0,
    }) == (0, 0)
    assert _ward_purchases({"obs_placed": 3, "sen_placed": 9}) == (3, 9)
    assert _ward_purchases({"kills": 5}) == (None, None)


def test_ward_points_read_xy_and_key_fallback():
    assert _ward_points([
        {"x": 133.1, "y": 101.6},
        {"key": "[163, 99]"},
        {"x": "nope"},
    ]) == [[133.1, 101.6], [163.0, 99.0]]
    assert _ward_points(None) == []


def test_ward_points_carries_time_when_present():
    assert _ward_points([
        {"x": 133.1, "y": 101.6, "time": -58},
        {"x": 140.0, "y": 120.0, "time": 300},
        {"key": "[163, 99]"},  # no time key -> stays [x, y]
    ]) == [[133.1, 101.6, -58], [140.0, 120.0, 300], [163.0, 99.0]]


def test_compact_match_reads_nested_ward_purchases():
    patches = normalize_patches([
        {"id": 60, "name": "7.41", "date": "2026-03-24T00:00:00Z"},
    ])
    row = compact_match({
        "match_id": 99, "start_time": 1775000000, "hero_id": 1,
        "purchase": {"ward_observer": 6, "ward_sentry": 11},
    }, patches)
    assert row["obs"] == 6
    assert row["sen"] == 11


def test_position_inference_separates_side_lane_core_and_support():
    carry = infer_position({
        "lane_role": 1, "hero_id": 1, "duration": 2400,
        "last_hits": 310, "gold_per_min": 650,
    })
    support = infer_position({
        "lane_role": 1, "hero_id": 5, "duration": 2400,
        "last_hits": 35, "gold_per_min": 285,
        "purchase_ward_observer": 5, "purchase_ward_sentry": 8,
    })
    assert carry["position"] == 1
    assert carry["confidence"] in ("medium", "high")
    assert support["position"] == 5
    assert "ward purchases" in support["evidence"]


def test_position_inference_calls_mid_from_observed_lane():
    result = infer_position({"lane_role": 2, "hero_id": 13})
    assert result["position"] == 2
    assert result["confidence"] == "high"


def test_position_inference_marks_ambiguous_side_lane_as_low_confidence():
    result = infer_position({"lane_role": 1, "hero_id": 999})
    assert result["position"] == 1
    assert result["confidence"] == "low"
    assert result["evidence"] == ["safe lane"]


def test_apply_lane_results_uses_parsed_gold_and_xp():
    matches = [{"id": 1, "win": True}, {"id": 2, "win": False}, {"id": 3, "win": True}]
    deep = [
        {"match_id": 1, "ally_lane_gold10": 3000, "enemy_lane_gold10": 2000,
         "ally_lane_xp10": 3000, "enemy_lane_xp10": 2000},
        {"match_id": 2, "ally_lane_gold10": 2100, "enemy_lane_gold10": 2000,
         "ally_lane_xp10": 2100, "enemy_lane_xp10": 2000},
        {"match_id": 99, "ally_lane_gold10": 1000, "enemy_lane_gold10": 4000,
         "ally_lane_xp10": 1000, "enemy_lane_xp10": 4000},
    ]
    apply_lane_results(matches, deep)
    assert matches[0]["laneResult"] == "win"
    assert matches[1]["laneResult"] == "draw"
    assert matches[2]["laneResult"] is None


def test_deep_summary_uses_only_parsed_evidence():
    summary = deep_summary([
        {"parsed": True, "duration": 1800, "ally_lane_gold10": 2500,
         "enemy_lane_gold10": 2000, "ally_lane_xp10": 3000,
         "enemy_lane_xp10": 2500, "observer_kills": 1, "sentry_kills": 2},
        {"parsed": False, "duration": 1800, "observer_kills": 20,
         "sentry_kills": 20},
    ])
    assert summary == {
        "parsed": 1, "lanes": 1, "laneW": 1, "laneD": 0, "laneL": 0,
        "dewards30": 3.0,
    }


def test_build_player_record_includes_esports_hero_pool_and_links(tmp_path):
    from scout.cache import Cache
    from scout.team_scout import build_player_record

    cache = Cache(root=str(tmp_path))
    patches = normalize_patches([
        {"id": 60, "name": "7.41", "date": "2026-03-24T00:00:00Z"},
    ])
    player = {"steam32": 105248644, "name": "Someone", "mmr": 6000}
    sections = {
        "profile": {"profile": {"personaname": "Someone"}, "rank_tier": 65},
        "wl": {"win": 10, "lose": 5},
        "heroes": [],
        "matches": [],
    }
    record = build_player_record(player, sections, Heroes(), patches, [], cache=cache)
    assert record["esports"]["status"] == "unavailable"
    assert record["heroPool"]["heroes"] == []
    assert record["heroPool"]["gems"] == []
    assert record["heroPool"]["pubWindowDays"] == 180
    assert record["links"] == {
        "dotabuff": "https://www.dotabuff.com/players/105248644",
        "dotabuffEsports": "https://www.dotabuff.com/esports/players/105248644",
        "opendota": "https://www.opendota.com/players/105248644",
    }


def test_build_player_record_without_cache_reports_esports_unavailable():
    patches = normalize_patches([
        {"id": 60, "name": "7.41", "date": "2026-03-24T00:00:00Z"},
    ])
    player = {"steam32": 1, "name": "NoCache", "mmr": 0}
    record = build_player_record(
        player, {"heroes": [], "matches": []}, Heroes(), patches, [],
    )
    assert record["esports"]["status"] == "unavailable"
    assert record["links"]["opendota"] == "https://www.opendota.com/players/1"


def test_bbc_adapter_builds_current_team_and_official_rows(tmp_path):
    graphics = tmp_path / "Show Graphics"
    scrapers = tmp_path / "scrapers"
    graphics.mkdir()
    scrapers.mkdir()
    feed = {
        "league": "LD2L Season XXII", "week": 5, "generated": "now",
        "standings": [{"name": "Team Alpha", "value": "6-2"}],
        "upcoming": [{
            "a": "Team Alpha", "aShort": "ALPHA", "ac": "Captain",
            "b": "Team Beta", "bShort": "BETA", "bc": "Other",
            "rosters": {
                "a": [{"id": 76561197960265729, "name": "One"}],
                "b": [{"id": 76561197960265730, "name": "Two"}],
            },
        }],
    }
    (graphics / "feed.json").write_text(json.dumps(feed), encoding="utf-8")
    match = {
        "match_id": 123, "start_time": 1775000000, "duration": 1800,
        "radiant_win": True, "radiant_name": "Team Alpha",
        "dire_name": "Team Beta", "patch": 60,
        "players": [{
            "account_id": 1, "isRadiant": True, "hero_id": 1,
            "kills": 8, "deaths": 2, "assists": 12, "gold_per_min": 600,
            "xp_per_min": 700, "observer_kills": 1, "sentry_kills": 2,
            "purchase": {"tango": 1}, "obs_placed": 0, "sen_placed": 0,
            "teamfight_participation": 0.42, "stuns": 12.5,
            "camps_stacked": 2, "rune_pickups": 3, "towers_killed": 1,
            "roshans_killed": 0, "buyback_count": 1, "firstblood_claimed": True,
        }],
    }
    (scrapers / ".od_match_cache.json").write_text(
        json.dumps({"123": match}), encoding="utf-8"
    )

    result = load_bbc_data(Heroes(), root=str(tmp_path))
    assert result["week"] == 5
    assert result["teams"][0]["record"] == "6-2"
    assert result["teams"][0]["roster"] == [1]
    assert result["players"][1]["name"] == "One"
    assert result["official"][1][0]["opponent"] == "Team Beta"
    assert result["official"][1][0]["opponent_key"] == "teambeta"
    assert result["official"][1][0]["result"] == "W"
    assert result["official"][1][0]["dewards"] == 3
    assert result["official"][1][0]["observer_wards"] == 0
    assert result["official"][1][0]["sentry_wards"] == 0
    assert result["official"][1][0]["is_radiant"] is True
    assert result["official"][1][0]["teamfight"] == 0.42
    assert result["official"][1][0]["obs_placed"] == 0
    assert result["official"][1][0]["sen_placed"] == 0
    assert result["official"][1][0]["obs_kills"] == 1
    assert result["official"][1][0]["sen_kills"] == 2
    assert result["official"][1][0]["stuns"] == 12.5
    assert result["official"][1][0]["camps_stacked"] == 2
    assert result["official"][1][0]["rune_pickups"] == 3
    assert result["official"][1][0]["towers_killed"] == 1
    assert result["official"][1][0]["roshans_killed"] == 0
    assert result["official"][1][0]["buybacks"] == 1
    assert result["official"][1][0]["firstblood"] is True
    assert result["matchups"] == [{
        "a": "Team Alpha", "aShort": "ALPHA", "aCaptain": "Captain",
        "aKey": "teamalpha",
        "b": "Team Beta", "bShort": "BETA", "bCaptain": "Other",
        "bKey": "teambeta",
        "week": None, "label": "", "matchId": None,
    }]


def test_bbc_source_stamp_changes_when_feed_is_rewritten(tmp_path):
    graphics = tmp_path / "Show Graphics"
    scrapers = tmp_path / "scrapers"
    graphics.mkdir()
    scrapers.mkdir()
    feed = graphics / "feed.json"
    cache = scrapers / ".od_match_cache.json"
    feed.write_text("{}", encoding="utf-8")
    cache.write_text("{}", encoding="utf-8")
    first = bbc_source_stamp(root=str(tmp_path))
    feed.write_text('{"week": 7}', encoding="utf-8")
    second = bbc_source_stamp(root=str(tmp_path))
    assert first != second
    missing = bbc_source_stamp(root=str(tmp_path / "absent"))
    assert all(mtime == 0 and size == 0 for _, mtime, size in missing)


def test_render_page_escapes_script_endings():
    page = render_page({"seasonId": 53, "players": [], "patches": [],
                        "teams": [], "bad": "</script>"})
    assert "<\\/script>" in page
    assert "Add team" in page
    assert 'class="teamIdentity"' in page
    assert "flatMap(p=>windowMatches(p))" in page
    assert "Wins / losses" in page
    assert "Best heroes" in page
    assert "Public record" not in page
    assert "Highest impact" in page
    assert "function impactPlayers" in page
    assert "function impactPanel" in page
    assert "function officialTeamHeroStats" in page
    assert "Ranked by KDA in LD2L officials." in page
    assert "Ranked by KDA in the selected public window." not in page
    assert "No official player data." in page
    assert "matchSummary(windowMatches(p))" not in page.split("function impactPlayers")[1].split("function impactPanel")[0]
    assert "officialRows(p)" in page.split("function impactPlayers")[1].split("function impactPanel")[0]
    assert "windowSelect()" not in page.split("function matchupPage")[1].split("function")[0]
    assert "player-games in window" not in page.split("function overview")[1].split("function playerRow")[0]
    assert "winLossPanel(mine.flatMap(p=>officialRows(p))" in page
    assert "winLossPanel(mine.flatMap(p=>windowMatches(p))" not in page
    assert "<th>XPM</th>" in page.split("function impactPanel")[1].split("function overview")[0]
    assert "HD/min" not in page.split("function impactPanel")[1].split("function overview")[0]
    assert "${impactPanel(ps)}" in page
    assert 'metric("Public record"' not in page
    assert "Most seen role" not in page
    assert "function wilson" in page
    assert "positionConfidence" in page
    assert 'data-view="league"' in page
    assert "Teams</button>" in page
    assert ">Standings</button>" not in page
    assert "<th>Win %</th>" not in page
    assert "standingsWho" in page
    assert "data-open-matchup" in page
    assert "Week ${week} matchups" in page
    assert "No upcoming matchups yet." in page
    assert 'class="nav navMine"' in page
    assert 'class="nav navEnemy"' in page
    assert 'class="nav navSide"' in page
    assert 'aria-label="Your team"' in page
    assert 'aria-label="Opponent"' in page
    assert 'aria-label="League"' in page
    assert page.index('data-view="matchup"') < page.index('data-view="standings"')
    assert page.index('data-view="standings"') < page.index('data-view="league"')
    assert 'data-view="results"' not in page
    assert ".sideBlock{display:flex;gap:0;" in page
    assert ".sideBlock.mine{border:1.5px solid rgba(255,255,255,.35);border-radius:28px}" in page
    assert "g.isRadiant?`${scouted}<div class=\"vsTiny\">vs</div>${other}`:`${other}<div class=\"vsTiny\">vs</div>${scouted}`" in page
    assert ".heroCell .heroIcon,.heroCell .heroFallback{display:block;border-radius:0}" in page
    assert ".draftLine{display:flex;align-items:flex-end;gap:0;" in page
    assert ".draftAct.ours:after{background:#fff}" in page
    assert ".draftAct.ours.ban:after{background:transparent;border:1px solid #fff}" in page
    assert '${ban?" ban":""}' in page
    assert ".draftAct.ours:before{background:var(--mine)}" in page
    assert ".draftAct:after{content:\"\";width:5px;height:5px;border-radius:50%;background:transparent;margin-top:3px;flex:none;order:2;box-sizing:border-box}" in page
    assert ".teamName{font-weight:650;font-size:24px;line-height:1.15}" in page
    assert ".singlePage>.teamsetup{margin:14px 0 8px;border:0;background:transparent;box-shadow:none;padding:0;border-radius:0}" in page
    assert ".draftAct .heroIcon,.draftAct .heroFallback{display:block;border-radius:0}" in page
    assert "width:28px;height:28px" not in page
    assert ".gameList .draftLine{flex-wrap:nowrap" in page
    assert "heroIcon(x.hero_id,28,ban)" in page
    assert ".sideBlock{flex-wrap:nowrap;gap:0}" in page
    assert 'data-view="player"' not in page
    assert "${matchTable(p,true)}" in page
    assert "${matchTable(p,true)</div>" not in page
    assert "<th>Obs</th>" in page
    assert "<th>Sen</th>" in page
    assert "Observers / 30" in page
    assert "function visionLine" in page
    assert "w&&w.total>0" not in page
    assert "function standingsStrip" not in page
    assert "data-edit-roster" in page
    assert "function swapStandin" in page
    assert "function completeSwap" in page
    assert "Ward maps · 7.41" in page
    assert "function wardMap" in page
    assert "function clusterWards" in page
    assert "function wardDotPx" in page
    assert "Larger = more often" in page
    assert "function wardStyleToggle" in page
    assert "function paintWardHeats" in page
    assert 'data-ward-style="heat"' in page
    assert 'saved.wardStyle==="heat"?"heat":"dots"' in page
    assert "rare → often" in page
    assert "s.map(pt=>wardDot(\"sen\",pt))" not in page
    assert "s.map(c=>wardDot(\"sen\",c))" in page
    assert "function wardSplit" in page
    assert "function gameWardSplit" in page
    assert "${wardMap(g.obs,g.sen" not in page
    assert 'wardSlot("Radiant"' in page
    assert 'wardSlot("Dire"' in page
    assert 'wardSideLabel">Us' not in page
    assert 'wardSideLabel">Them' not in page
    assert "${wardMap(all.obs,all.sen" not in page
    assert "${wardMap(w.obs,w.sen" not in page
    assert "detailed_740.jpg" in page
    assert "Most successful for" in page
    assert "Most successful against" in page
    assert "Struggle against" in page
    assert "Good with" in page
    assert "In your losses" in page
    assert "Unbeaten on this" in page
    assert "No repeating comfort heroes yet." in page
    assert "Official hero matchups" in page
    assert "function teamHeroMatchups" in page
    assert "heroMatchupPanel(games,replacedIdsFor(side))" in page
    assert "heroMatchupPanel(officials)" not in page
    assert 'class="teamIdentity"' in page
    assert "${editing?'Done':'Settings'}" in page
    assert "${ps.length}/5" not in page
    assert 'class="rosterLine"' in page
    assert 'class="rosterRight"' in page
    assert "gearBtn" in page
    assert "function teamPage(side){" in page
    assert "function setupHead" in page
    assert "function setupRoster" in page
    assert "function setup(side,showRoster=true)" in page
    assert "${setupHead(side)}" in page
    assert 'class="teamRoster"' in page
    assert "pane===\"players\"?`<div class=\"teamRoster\">${setupRoster(side)}</div>`" in page
    assert "const showRoster=pane!==\"draft\"&&pane!==\"roles\";" not in page
    assert "${setup(side,showRoster)}" not in page
    assert '<div class="pageHeading"><h2>${label}</h2></div>' not in page
    assert "function teamPlayers" in page
    assert 'positionPanel(rows,"Roles")' not in page
    assert "${ps.map(x=>playerRow(x,side)).join(\"\")}" not in page
    assert "function teamDraft" in page
    assert "function teamResults" in page
    assert 'data-team-sub="${side}:players"' in page
    assert 'data-team-sub="${side}:roles"' in page
    assert 'data-team-sub="${side}:draft"' in page
    assert 'data-team-sub="${side}:results"' in page
    assert "Roles</button>" in page
    assert "function teamRoles" in page
    assert "function teamRoleBreakdown" in page
    assert "function officialRoleGames" in page
    assert "Flex heroes" in page
    assert "How they flex" in page
    assert "<h3>Standins</h3>" in page
    assert "Also played" not in page
    assert "They stick to set roles." in page
    assert "They flex." in page
    assert "Cores stay on the same roles. They only flex support." in page
    assert "They move around to fit standins." in page
    assert "function postedIdsFor" in page
    assert "function currentIdsFor" in page
    assert "function replacedIdsFor" in page
    assert "function persistReplaced" in page
    assert "data-mark-replaced" in page
    assert "data-unmark-replaced" in page
    assert "<b>Replaced</b>" in page
    assert "<h3>Replaced</h3>" in page
    assert "goneHeroName" in page
    assert "since replacement" in page
    assert "struck through" in page
    assert "${teamRoles('mine')}" in page
    assert 'positionPanel(mine.flatMap(p=>windowMatches(p)),state.mineName)' not in page
    assert "<h3>Positions</h3>" not in page
    assert "Select a player to open their profile." not in page
    assert "if(!p){p=ps[0];state[side===\"mine\"?\"focusMine\":\"focusEnemy\"]=p.id}" in page
    assert 'data-player-sub="${side}:overview"' in page
    assert 'data-player-sub="${side}:officials"' in page
    assert 'data-player-sub="${side}:pubs"' in page
    assert 'data-player-sub="${side}:wards"' in page
    assert 'data-player-sub="${side}:standins"' in page
    assert page.index('data-player-sub="${side}:wards"') < page.index('data-player-sub="${side}:standins"')
    assert "Standins</button>" in page
    assert "function standinsTab" in page
    assert 'pane==="standins"?standinsTab(side)' in page
    assert "signup role" not in page
    assert "Officials</button>" in page
    assert "Overview</button>" in page
    assert "function playerOfficialsTab" in page
    assert 'pane==="officials"?playerOfficialsTab(p)' in page
    assert "function playerPubsTab" in page
    assert "function playerWardsTab" in page
    assert "function playerWardGames" in page
    assert "function collectPubWards" in page
    assert "p.pubWards" in page
    assert "Recent 7.41 games are still waiting on an OpenDota parse." in page
    assert "function mapsFold" in page
    assert "function officialMatchRows" in page
    assert "function officialMapsFold" not in page
    assert "wardRow" not in page.split("function officialMatchRows")[1].split("function pickNums")[0]
    assert 'mapsFold("",wardSplit(all,220))' not in page
    assert "${wardSplit(all,460)}" in page
    assert 'mapsFold("",gameWardSplit(split,140))' not in page
    assert "${gameWardSplit(g,240)}" in page
    assert "flex-direction:column" in page.split(".wardSplit,.gameWards{")[1].split("}")[0]
    assert "function steam64" in page
    assert "function steamUrl" in page
    assert "function steamLink" in page
    assert "function steamIcon" in page
    assert "steamcommunity.com/profiles/${steam64(id)}" in page
    assert 'href="${steamUrl(p.id)}">Steam</a>' not in page
    assert "${steamLink(p.id)}" in page
    assert "${officialSeriesList(p)}" in page
    assert "function officialSeriesList" in page
    assert "function officialSeriesGroups" in page
    assert "function officialSeriesCard" in page
    assert "function officialMatchNumber" in page
    assert "rows.map(m=>officialMatchRows(p,m))" not in page
    assert "officialMatchRows(p,m,officialMatchNumber(p,m,i+1))" in page
    assert "function captainLabel" in page
    assert "function opponentLink" in page
    assert "https://www.dotabuff.com/matches/${id}" in page
    assert "opendota.com/matches/${m.match_id}" not in page
    assert "<th>Official match</th>" not in page
    assert 'colspan="17"' not in page
    assert 'colspan="15"' not in page
    assert "opponentLink(m.opponent,m.opponent_key,m.match_id)" not in page
    assert 'href="${dbMatchUrl(m.match_id)}">Match ${n}</a>' in page
    assert "captainLabel(opp.name,opp.team_key)" in page
    assert "captainLabel(g.opponent,g.opponent_key)" in page
    assert "Ward maps</button>" in page
    assert "Wards</button>" not in page
    assert "Pubs</button>" in page
    assert "By game" in page
    assert "Most banned" in page
    assert "Players</button>" in page
    assert "Draft</button>" in page
    assert "Results</button>" in page
    assert ">Team</button>" not in page
    assert 'data-view="results"' not in page
    assert 'data-view="player"' not in page
    assert "matchupTbl" in page
    assert "winKda" in page
    assert "heroPickSummary" not in page
    assert "heroSummaryChip" not in page
    assert "matchupLabel" not in page
    assert '<h2>Matchup</h2>' not in page
    assert '<h2>League</h2>' not in page
    assert '<h2>Standings</h2>' not in page
    assert "League Stats</button>" in page
    assert ">League</button>" not in page
    assert 'class="mark"' not in page
    assert 'id="season"' not in page
    assert 'id="window"' not in page
    assert "Analysis window" not in page
    assert 'data-window' in page
    assert "function seriesWeekLabel" in page
    assert "function leagueWeekMap" in page
    assert "`Week ${week}`" in page
    assert "Match ${n}" in page
    assert "Game ${n}" not in page
    assert "Match ${g.m.match_id}" not in page
    assert 'href="${dbMatchUrl(g.m.match_id)}">Match ${n}</a>' in page
    assert "function gameDraftLine" in page
    assert "class=\"draftN\"" in page
    assert "${gameDraftLine(g)}${visionLine(focusPlayers(g.mine.players,focusId))}" in page
    assert "function focusPlayers" in page
    assert "function seriesWardGrid" in page
    block = page.split("function seriesWardGrid")[1].split("function seriesWardFold")[0]
    assert "g.mine.players" in block
    assert 'class="resultSide ${side}"' in block
    assert 'row("obs","Observer")' in block
    assert 'row("sen","Sentry")' in block
    assert "<span>Radiant</span><span>Dire</span>" in block
    assert "g.m.radiant" not in block
    assert "g.m.dire" not in block
    assert "function wardSingle" in page
    per_game = page.split("function gameWardSplit")[1].split("function collectPlayerWards")[0]
    assert "scoutedWardMap" in per_game
    assert "wardSplit(" not in per_game
    assert "function seriesWardFold" in page
    assert "${seriesWardFold(games,focusId)}" in page
    assert "function mapsFold" in page
    assert '<details class="wardFold">' in page
    assert "function bindSeriesWardFolds" in page
    assert "o.open=d.open" in page
    assert 'closest(".seriesCard")' in page
    assert "${visionLine(g.mine.players)}${isWardPatch" not in page
    assert "${visionLine(g.mine.players)}${gameDraftLine(g)}" not in page
    assert "${laneStr}<b class=\"${cls}\">${wl}</b>" not in page
    assert "heroIcon(p.hero_id,48)" in page
    assert "heroIcon(p.hero_id,40)" not in page
    assert '<small><b class="${cls}">${wl}</b></small>' not in page
    assert "function playerHeroCell(p,focusId,pickN)" in page
    assert "function pickNums" in page
    assert "function playersByDraft" in page
    assert 'class="heroPickN"' in page
    assert "playersByDraft(g.mine.players,nums)" in page
    assert "playersByDraft(g.opp.players,nums)" in page
    assert "g.mine.players.map(p=>playerHeroCell(p,focusId))" not in page
    assert "myBans" not in page
    assert "max-width:48px;overflow:hidden;text-overflow:ellipsis" not in page
    assert 'font:650 22px/1.15 Georgia,serif' in page
    assert ".seriesScore{font:700 16px/1 Georgia,serif" in page
    assert ".seriesOpp{flex:1}" not in page
    assert ".gameList{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in page
    assert ".gameList .gameRow:only-child{grid-column:1/-1}" in page
    assert "function cellName" in page
    assert "t===t.toUpperCase()" in page
    assert 'replace(/([\\p{Ll}\\p{N}])(\\p{Lu})/gu,"$1 $2")' in page
    assert "-webkit-line-clamp:2" in page
    assert "overflow-wrap:normal" in page
    assert "title=\"Observers / sentries\"" not in page
    assert "class=\"vision\"" not in page
    assert "E(cellName(p.name)||p.name)" in page
    assert "function resultsPlayerList" in page
    assert "function resultsPlayerList(side){return members(side).map(p=>({id:p.id,name:p.name}))}" in page
    assert "for(const p of seen.values())out.push(p)" not in page
    assert "members(side).some(p=>p.id===id)?id:null" in page
    assert "function resultsPlayerId" in page
    assert 'aria-label="Filter by player"' in page
    assert ".resultsFilter .chip.on{border-color:var(--mine)" in page
    assert "data-results-player" in page
    assert 'data-results-player="${side}:">All' not in page
    assert ">All</button>" not in page
    assert "heroCell${on?' on':''}" in page
    assert "gameRow${sit?' sitout':''}" in page
    assert "toLocaleDateString(undefined,{month:\"short\",day:\"numeric\"})" not in page


def test_render_page_has_heroes_and_esports_subtabs():
    page = render_page({"seasonId": 53, "players": [], "patches": [],
                        "teams": [], "bad": "</script>"})
    assert 'data-player-sub="${side}:heroes"' in page
    assert 'data-player-sub="${side}:esports"' in page
    assert "Heroes</button>" in page
    assert "Esports</button>" in page
    assert page.index('data-player-sub="${side}:officials"') < page.index('data-player-sub="${side}:esports"')
    assert page.index('data-player-sub="${side}:pubs"') < page.index('data-player-sub="${side}:heroes"')
    assert "function playerHeroesTab" in page
    assert "function playerEsportsTab" in page
    assert "function heroGemsCard" in page
    assert "Hidden gems" in page
    assert "No hidden gems: nothing outside their comfort picks clears the bar yet." in page
    assert "Esports profile" in page
    assert "Open Dotabuff esports profile" in page
    assert "background refresh fills it in" in page
    assert "function isPub" in page
    assert "function heroPoolTable" in page
    assert "function esportsPoolCompare" in page
    assert "League pool vs pub pool" in page
    assert "data-hero-sort" in page


def test_render_page_has_league_tab_and_functions():
    page = render_page({"seasonId": 53, "players": [], "patches": [],
                        "teams": [], "bad": "</script>"})
    assert "function seasonHeroRecords" in page
    assert "function leaguePage" in page
    assert "leagueTbl" in page
    assert "Fear by team" not in page
    assert "function firstPickSide" in page
    assert "function teamSplitStats" in page
    assert "function teamSplitPanel" in page
    assert "All teams" in page
    assert "First pick" in page
    assert "Second pick" in page
    assert "<th>Radiant</th>" in page
    assert "<th>Dire</th>" in page
    assert "teamSplitPanel(games)" in page
    assert "<b>Standins</b>" not in page
    assert "<b>Replaced</b>" in page
    assert "<b>Replacements</b>" not in page
    # Teams and League Stats sit in the right-side league nav
    assert 'class="nav navMine"' in page
    assert 'class="nav navEnemy"' in page
    assert 'class="nav navSide"' in page
    assert 'aria-label="Your team"' in page
    assert 'aria-label="Opponent"' in page
    assert 'aria-label="League"' in page
    assert page.index('data-view="matchup"') < page.index('data-view="standings"')
    assert page.index('data-view="standings"') < page.index('data-view="league"')


def test_render_page_has_recon_tab():
    page = render_page({"seasonId": 53, "players": [], "patches": [], "teams": []})
    assert 'data-view="recon"' in page
    assert "Recon</button>" in page
    assert page.index('data-view="opponent"') < page.index('data-view="recon"')
    assert page.index('data-view="recon"') < page.index('data-view="matchup"')
    assert "function reconMonday" in page
    assert "function reconMatches" in page
    assert "function reconHeroStats" in page
    assert "function reconTeamHeroes" in page
    assert "function reconTogether" in page
    assert "function reconTogetherSection" in page
    assert "function reconPrivateSection" in page
    assert "function reconPage" in page
    assert "recon:reconPage" in page
    assert "Together this week" in page
    assert "Same public match, two or more of them." in page
    assert "g.players.length>=2" in page
    assert "reconTogetherSection(ps)" in page
    assert "reconPrivateSection(ps)" in page
    assert "Private profiles" in page
    assert "ps.filter(p=>p.private)" in page
    assert "privateBlock on" in page
    assert "metric privateBlock" in page
    assert "card reconTop" in page
    assert "${priv}</div></div>" in page
    assert "${priv}<div class=\"metrics\"" not in page
    recon_page = page.split("function reconPage")[1].split("const pages=")[0]
    assert "${metrics}${teamHeroes}${together}${players}" in recon_page
    assert "${metrics}${priv}${teamHeroes}" not in recon_page
    assert recon_page.index("Most played this week") < recon_page.index("By player")
    assert 'allowedViews=["team","opponent","recon","matchup","standings","league"]' in page
    assert "Most played this week" in page
    assert "Add an opponent to see what they've been playing this week." in page
    assert "Public games since" in page
    assert "Ranked by volume so hero spam shows first." in page
    assert "No cached public games since Monday." in page
    assert "quiet this week" in page
    assert "<h2>Recon</h2>" not in page
    assert 'members("enemy")' in page.split("function reconPage")[1].split("const pages=")[0]
    assert "windowSelect()" not in page.split("function reconPage")[1].split("const pages=")[0]
    assert "day===0?6:day-1" in page


def test_render_page_has_keys_to_victory():
    page = render_page({"seasonId": 53, "players": [], "patches": [], "teams": []})
    assert "<h3>Keys to victory</h3>" in page
    assert "function keysPanel" in page
    assert "keysPanel(mine,enemy)" in page
    assert "function fisherExact" in page
    assert "function laneKey" in page
    assert "function gpmKey" in page
    assert "No statistically significant keys in this official sample." in page
    assert "No statistically significant keys in this sample." not in page
    assert "Drawn from cached LD2L official matches." in page
    assert "playerKeys(p,windowMatches(p)" not in page
    assert 'playerKeys(p,off,side,"LD2L officials")' in page
    assert "KEY_MIN_GROUP=5" in page
    assert "KEY_MIN_GAP=.3" in page
    assert "KEY_MAX_BAD_WR=.4" in page
    assert "KEY_MIN_GOOD_WR=.55" in page
    assert "KEY_MIN_GPM_GAP=60" in page
    assert "KEY_LANE_WIN=55" in page
    assert "KEY_LANE_LOSS=45" in page
    assert "KEY_ALPHA=.05" in page
    assert "Keep ${p.name} under ${cut} GPM" in page
    assert "Get ${p.name} over ${cut} GPM" in page
    assert "Win the offlane" in page
    assert "two-sided Fisher exact test" in page
    assert "gold also rises after winning" in page
    assert "cut<500||cut>800" in page
    assert page.index("keysPanel(mine,enemy)") < page.index("<h3>Wins / losses</h3>")


# ---------------------------------------------------------------------------
# team_key normalization
# ---------------------------------------------------------------------------

def test_team_key_normalizes_apostrophes_and_article():
    straight = "The Mad King's Gambit"
    curly = "The Mad King’s Gambit"
    assert team_key(straight) == team_key(curly)
    assert team_key(straight) == "madkingsgambit"


def test_team_key_casefolds_and_ignores_article():
    assert team_key("roaring Arya") == team_key("Roaring Arya")
    assert team_key("The Simple Plan") == team_key("Simple Plan")


def test_team_key_handles_missing_name():
    assert team_key(None) == ""
    assert team_key("") == ""


# ---------------------------------------------------------------------------
# standings parsing + competition ranking
# ---------------------------------------------------------------------------

class Heroes2:
    def name(self, hero_id):
        return f"Hero {hero_id}"


def test_standings_parsing_and_competition_ranking(tmp_path):
    graphics = tmp_path / "Show Graphics"
    scrapers = tmp_path / "scrapers"
    graphics.mkdir()
    scrapers.mkdir()
    feed = {
        "league": "LD2L Season XXII", "week": 6,
        "standings": [
            {"name": "Team Alpha", "nameShort": "ALPHA", "value": "7 - 3", "captain": "A"},
            {"name": "Team Beta", "nameShort": "BETA", "value": "7-3", "captain": "B"},
            {"name": "Team Gamma", "nameShort": "GAMMA", "value": "5 - 5", "captain": "C"},
            {"name": "Team Delta", "nameShort": "DELTA", "value": "not-a-record", "captain": "D"},
            {"name": "Team Epsilon", "value": None},
        ],
        "upcoming": [],
    }
    (graphics / "feed.json").write_text(json.dumps(feed), encoding="utf-8")
    (scrapers / ".od_match_cache.json").write_text("{}", encoding="utf-8")

    result = load_bbc_data(Heroes2(), root=str(tmp_path))
    rows = {row["short"]: row for row in result["standings"]}
    assert rows["ALPHA"]["wins"] == 7 and rows["ALPHA"]["losses"] == 3
    assert rows["BETA"]["wins"] == 7 and rows["BETA"]["losses"] == 3
    # Ties on wins share the same (lower) rank; the next distinct value skips.
    assert rows["ALPHA"]["rank"] == 1
    assert rows["BETA"]["rank"] == 1
    assert rows["GAMMA"]["rank"] == 3
    # Malformed / missing records don't crash and fall back to 0-0.
    assert rows["DELTA"]["wins"] == 0 and rows["DELTA"]["losses"] == 0
    epsilon = next(row for row in result["standings"] if row["name"] == "Team Epsilon")
    assert epsilon["wins"] == 0 and epsilon["losses"] == 0
    # Feed order is preserved regardless of rank.
    assert [row["name"] for row in result["standings"]] == [
        "Team Alpha", "Team Beta", "Team Gamma", "Team Delta", "Team Epsilon",
    ]


# ---------------------------------------------------------------------------
# team_matches side resolution: by name, and by roster-overlap fallback
# ---------------------------------------------------------------------------

def _write_feed_and_cache(tmp_path, feed, matches):
    graphics = tmp_path / "Show Graphics"
    scrapers = tmp_path / "scrapers"
    graphics.mkdir()
    scrapers.mkdir()
    (graphics / "feed.json").write_text(json.dumps(feed), encoding="utf-8")
    (scrapers / ".od_match_cache.json").write_text(json.dumps(matches), encoding="utf-8")


def test_team_matches_resolves_side_by_name(tmp_path):
    feed = {
        "league": "LD2L", "week": 1, "standings": [],
        "upcoming": [{
            "a": "Team Alpha", "aShort": "ALPHA", "ac": "Cap A",
            "b": "Team Beta", "bShort": "BETA", "bc": "Cap B",
            "rosters": {
                "a": [{"id": 76561197960265728 + i, "name": f"A{i}"} for i in range(1, 6)],
                "b": [{"id": 76561197960265728 + i, "name": f"B{i}"} for i in range(101, 106)],
            },
        }],
    }
    players_radiant = [
        {"account_id": 1, "isRadiant": True, "player_slot": 0, "hero_id": 1,
         "lane_efficiency_pct": 54.2, "purchase_ward_observer": 2,
         "purchase_ward_sentry": 7,
         "obs_log": [{"x": 133.1, "y": 101.6}],
         "sen_log": [{"key": "[163,99]"}],
         "teamfight_participation": 0.55, "obs_placed": 2, "sen_placed": 7,
         "observer_kills": 1, "sentry_kills": 0, "stuns": 8.0,
         "camps_stacked": 1, "rune_pickups": 4, "towers_killed": 2,
         "roshans_killed": 1, "buyback_count": 0, "firstblood_claimed": False,
         "hero_damage": 15000},
        {"account_id": 2, "isRadiant": True, "player_slot": 1, "hero_id": 1,
         "purchase": {"tango": 3}, "obs_placed": 0, "sen_placed": 0},
        {"account_id": 3, "isRadiant": True, "player_slot": 2, "hero_id": 1,
         "purchase": {"ward_observer": 6, "ward_sentry": 11}},
    ] + [
        {"account_id": i, "isRadiant": True, "player_slot": i - 1, "hero_id": 1}
        for i in range(4, 6)
    ]
    match = {
        "match_id": 1, "start_time": 100, "duration": 1800, "patch": 60,
        "radiant_win": True, "radiant_name": "Team Alpha", "dire_name": "Team Beta",
        "radiant_score": 30, "dire_score": 18, "first_blood_time": 95,
        "picks_bans": [
            {"hero_id": 1, "is_pick": False, "team": 1, "order": 0},
            {"hero_id": 2, "is_pick": True, "team": 0, "order": 1},
        ],
        "players": players_radiant + [
            {"account_id": i, "isRadiant": False, "player_slot": 128 + (i - 101), "hero_id": 2}
            for i in range(101, 106)
        ],
    }
    _write_feed_and_cache(tmp_path, feed, {"1": match})

    result = load_bbc_data(Heroes2(), root=str(tmp_path))
    entry = result["teamMatches"][0]
    assert entry["radiant"]["team_key"] == team_key("Team Alpha")
    assert entry["dire"]["team_key"] == team_key("Team Beta")
    assert [p["id"] for p in entry["radiant"]["players"]] == [1, 2, 3, 4, 5]
    assert entry["radiant"]["players"][0]["lane_eff"] == 54.2
    assert entry["radiant"]["players"][0]["obs"] == 2
    assert entry["radiant"]["players"][0]["sen"] == 7
    assert entry["radiant"]["players"][0]["obs_map"] == [[133.1, 101.6]]
    assert entry["radiant"]["players"][0]["sen_map"] == [[163.0, 99.0]]
    assert entry["radiant"]["players"][0]["teamfight"] == 0.55
    assert entry["radiant"]["players"][0]["obs_placed"] == 2
    assert entry["radiant"]["players"][0]["sen_placed"] == 7
    assert entry["radiant"]["players"][0]["obs_kills"] == 1
    assert entry["radiant"]["players"][0]["sen_kills"] == 0
    assert entry["radiant"]["players"][0]["stuns"] == 8.0
    assert entry["radiant"]["players"][0]["camps_stacked"] == 1
    assert entry["radiant"]["players"][0]["rune_pickups"] == 4
    assert entry["radiant"]["players"][0]["towers_killed"] == 2
    assert entry["radiant"]["players"][0]["roshans_killed"] == 1
    assert entry["radiant"]["players"][0]["buybacks"] == 0
    assert entry["radiant"]["players"][0]["firstblood"] is False
    assert entry["radiant"]["players"][0]["hero_damage"] == 15000
    assert entry["radiant_score"] == 30
    assert entry["dire_score"] == 18
    assert entry["first_blood_time"] == 95
    assert entry["patch"] == 60
    assert entry["radiant"]["players"][1]["obs"] == 0
    assert entry["radiant"]["players"][1]["sen"] == 0
    assert entry["radiant"]["players"][2]["obs"] == 6
    assert entry["radiant"]["players"][2]["sen"] == 11
    assert entry["picks_bans"][1] == {
        "hero_id": 2, "is_pick": True, "team": 0, "order": 1,
    }


def test_team_matches_resolves_side_by_roster_overlap_when_name_unmatched(tmp_path):
    feed = {
        "league": "LD2L", "week": 1, "standings": [],
        "upcoming": [{
            "a": "Team Alpha", "aShort": "ALPHA", "ac": "Cap A",
            "b": "Team Beta", "bShort": "BETA", "bc": "Cap B",
            "rosters": {
                "a": [{"id": 76561197960265728 + i, "name": f"A{i}"} for i in range(1, 6)],
                "b": [{"id": 76561197960265728 + i, "name": f"B{i}"} for i in range(101, 106)],
            },
        }],
    }
    # radiant_name is something OpenDota made up that matches no posted team,
    # but 3+ of the radiant players are Team Alpha's posted roster.
    match = {
        "match_id": 2, "start_time": 200, "duration": 1800,
        "radiant_win": False, "radiant_name": "Radiant", "dire_name": "Team Beta",
        "players": [
            {"account_id": i, "isRadiant": True, "player_slot": i - 1, "hero_id": 1}
            for i in (1, 2, 3)
        ] + [
            {"account_id": 999, "isRadiant": True, "player_slot": 3, "hero_id": 1},
            {"account_id": 998, "isRadiant": True, "player_slot": 4, "hero_id": 1},
        ] + [
            {"account_id": i, "isRadiant": False, "player_slot": 128 + (i - 101), "hero_id": 2}
            for i in range(101, 106)
        ],
    }
    _write_feed_and_cache(tmp_path, feed, {"2": match})

    result = load_bbc_data(Heroes2(), root=str(tmp_path))
    entry = result["teamMatches"][0]
    assert entry["radiant"]["team_key"] == team_key("Team Alpha")
    assert entry["dire"]["team_key"] == team_key("Team Beta")


def test_team_matches_leaves_side_unresolved_below_overlap_threshold(tmp_path):
    feed = {
        "league": "LD2L", "week": 1, "standings": [],
        "upcoming": [{
            "a": "Team Alpha", "aShort": "ALPHA", "ac": "Cap A",
            "b": "Team Beta", "bShort": "BETA", "bc": "Cap B",
            "rosters": {
                "a": [{"id": 76561197960265728 + i, "name": f"A{i}"} for i in range(1, 6)],
                "b": [{"id": 76561197960265728 + i, "name": f"B{i}"} for i in range(101, 106)],
            },
        }],
    }
    match = {
        "match_id": 3, "start_time": 300, "duration": 1800,
        "radiant_win": True, "radiant_name": "Some Pug", "dire_name": "Team Beta",
        "players": [
            {"account_id": i, "isRadiant": True, "player_slot": i - 1, "hero_id": 1}
            for i in (1, 900, 901, 902, 903)
        ] + [
            {"account_id": i, "isRadiant": False, "player_slot": 128 + (i - 101), "hero_id": 2}
            for i in range(101, 106)
        ],
    }
    _write_feed_and_cache(tmp_path, feed, {"3": match})

    result = load_bbc_data(Heroes2(), root=str(tmp_path))
    entry = result["teamMatches"][0]
    assert entry["radiant"]["team_key"] is None
    assert entry["dire"]["team_key"] == team_key("Team Beta")


# ---------------------------------------------------------------------------
# replacements: an official player for a team who isn't on its roster
# ---------------------------------------------------------------------------

def test_assemble_team_computes_replacements_not_in_roster():
    team = {"name": "Team Alpha", "short": "ALPHA", "roster": [1, 2, 3, 4, 5]}
    id_to_name = {1: "One", 2: "Two", 999: "Standin"}
    team_games = {team_key("Team Alpha"): {1: 3, 2: 3, 999: 2}}
    result = assemble_team(team, {"rosters": {}, "players": {}}, id_to_name, team_games)
    assert result["postedRoster"] == [1, 2, 3, 4, 5]
    assert result["roster"] == [1, 2, 3, 4, 5]
    assert result["edited"] is False
    assert result["replacements"] == [{"id": 999, "name": "Standin", "games": 2}]
    assert result["replaced"] == []
    assert result["replacedPlayers"] == []


def test_assemble_team_replacement_disappears_once_added_to_roster():
    team = {"name": "Team Alpha", "short": "ALPHA", "roster": [1, 2, 3, 4, 5]}
    id_to_name = {1: "One", 999: "Standin"}
    team_games = {team_key("Team Alpha"): {1: 3, 999: 2}}
    overrides = {"rosters": {team_key("Team Alpha"): [1, 999, 3, 4, 5]}, "players": {}}
    result = assemble_team(team, overrides, id_to_name, team_games)
    assert result["roster"] == [1, 999, 3, 4, 5]
    assert result["edited"] is True
    assert result["replacements"] == []


def test_assemble_team_replaced_player_leaves_standins_and_stays_named():
    team = {"name": "Team Alpha", "short": "ALPHA", "roster": [1, 2, 3, 4, 5]}
    key = team_key("Team Alpha")
    id_to_name = {1: "One", 5: "Gone", 999: "Standin"}
    team_games = {key: {1: 4, 5: 3, 999: 2}}
    overrides = {"rosters": {}, "players": {}, "replaced": {key: [5]}}
    result = assemble_team(team, overrides, id_to_name, team_games)
    assert result["roster"] == [1, 2, 3, 4, 5]
    assert result["replaced"] == [5]
    assert result["replacedPlayers"] == [{"id": 5, "name": "Gone", "games": 3}]
    assert result["replacements"] == [{"id": 999, "name": "Standin", "games": 2}]


def test_assemble_team_replaced_standin_is_not_a_standin():
    team = {"name": "Team Alpha", "short": "ALPHA", "roster": [1, 2, 3, 4, 5]}
    key = team_key("Team Alpha")
    id_to_name = {999: "Former"}
    team_games = {key: {1: 4, 999: 6}}
    overrides = {"replaced": {key: [999]}}
    result = assemble_team(team, overrides, id_to_name, team_games)
    assert result["replacements"] == []
    assert result["replacedPlayers"] == [{"id": 999, "name": "Former", "games": 6}]


# ---------------------------------------------------------------------------
# overrides load/save roundtrip
# ---------------------------------------------------------------------------

def test_overrides_roundtrip_and_roster_override_marks_edited(tmp_path):
    path = str(tmp_path / "teamscout_overrides.json")
    assert load_overrides(path) == {
        "players": {}, "rosters": {}, "replaced": {}, "accounts": {},
    }

    data = load_overrides(path)
    data["players"]["123"] = {"name": "Standin", "added": 1700000000}
    data["rosters"]["madkingsgambit"] = [1, 2, 3]
    data["replaced"]["madkingsgambit"] = [9]
    save_overrides(data, path)

    reloaded = load_overrides(path)
    assert reloaded["players"]["123"]["name"] == "Standin"
    assert reloaded["rosters"]["madkingsgambit"] == [1, 2, 3]
    assert reloaded["replaced"]["madkingsgambit"] == [9]

    team = {"name": "Mad King's Gambit", "short": "MKG", "roster": [4, 5, 6, 7, 8]}
    result = assemble_team(team, reloaded, {9: "Old"}, {})
    assert result["roster"] == [1, 2, 3]
    assert result["postedRoster"] == [4, 5, 6, 7, 8]
    assert result["edited"] is True
    assert result["replaced"] == [9]
    assert result["replacedPlayers"][0]["name"] == "Old"


def test_overrides_load_tolerates_missing_or_corrupt_file(tmp_path):
    missing = str(tmp_path / "nope.json")
    assert load_overrides(missing) == {
        "players": {}, "rosters": {}, "replaced": {}, "accounts": {},
    }

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json", encoding="utf-8")
    assert load_overrides(str(corrupt)) == {
        "players": {}, "rosters": {}, "replaced": {}, "accounts": {},
    }


# ---------------------------------------------------------------------------
# search query parsing
# ---------------------------------------------------------------------------

def test_parse_steam_id_query_variants():
    assert parse_steam_id_query("105248644") == 105248644
    assert parse_steam_id_query("76561198071193362") == 76561198071193362 - 76561197960265728
    assert parse_steam_id_query("https://www.dotabuff.com/players/105248644") == 105248644
    assert parse_steam_id_query("https://www.opendota.com/players/105248644/matches") == 105248644
    assert parse_steam_id_query("https://stratz.com/players/105248644") == 105248644
    assert parse_steam_id_query(
        "https://steamcommunity.com/profiles/76561198071193362"
    ) == 76561198071193362 - 76561197960265728
    assert parse_steam_id_query("avgpeen") is None
    assert parse_steam_id_query("") is None
    assert parse_steam_id_query(None) is None


# --- basic auth -------------------------------------------------------------
# Team Scout sits behind a public Tailscale Funnel, so the password gate is the
# only thing between the roster-writing endpoints and the internet.

class _FakeState:
    """Enough of TeamScoutState for the handler to answer a request."""

    def __init__(self):
        self.payload = {"season": "S22", "players": [], "teams": []}
        self.page = b"<html>team scout</html>"

    def snapshot(self):
        return self.payload, self.page

    def rebuild_async(self):
        pass


@contextlib.contextmanager
def _auth_server(monkeypatch, password="whykennywhy", state=None):
    monkeypatch.setattr(team_scout, "AUTH_FAIL_DELAY", 0)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), team_scout._make_handler(state or _FakeState(), password)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(base, path="/", method="GET", auth=None, body=None):
    """Returns (status, headers). Never raises on a 4xx."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if auth is not None:
        req.add_header("Authorization", auth)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, dict(res.headers)
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers)


def _basic(user, password):
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {raw}"


def test_auth_missing_header_is_401_and_offers_basic_challenge(monkeypatch):
    with _auth_server(monkeypatch) as base:
        status, headers = _request(base)
    assert status == 401
    assert 'Basic realm="Team Scout"' in headers["WWW-Authenticate"]


def test_auth_correct_password_passes_with_any_username(monkeypatch):
    with _auth_server(monkeypatch) as base:
        assert _request(base, auth=_basic("james", "whykennywhy"))[0] == 200
        # one shared password: the username is not part of the check
        assert _request(base, auth=_basic("anyone", "whykennywhy"))[0] == 200
        assert _request(base, auth=_basic("", "whykennywhy"))[0] == 200


def test_auth_wrong_password_is_401(monkeypatch):
    with _auth_server(monkeypatch) as base:
        assert _request(base, auth=_basic("james", "whykennywh"))[0] == 401
        assert _request(base, auth=_basic("james", "WHYKENNYWHY"))[0] == 401
        assert _request(base, auth=_basic("james", ""))[0] == 401


def test_auth_malformed_header_is_401_not_a_crash(monkeypatch):
    with _auth_server(monkeypatch) as base:
        for header in (
            "Basic !!!not-base64!!!",
            "Basic",
            "Basic ",
            "Bearer whykennywhy",
            base64.b64encode(b"james:whykennywhy").decode(),  # no scheme
            # valid base64, but no colon to split a password out of
            "Basic " + base64.b64encode(b"whykennywhy").decode(),
        ):
            assert _request(base, auth=header)[0] == 401, header


def test_auth_gates_post_endpoints_not_just_the_page(monkeypatch):
    with _auth_server(monkeypatch) as base:
        # the roster endpoint writes teamscout_overrides.json - it must not be
        # reachable without the password
        for path in ("/api/roster", "/api/player"):
            status, _ = _request(base, path, method="POST", body={"team": "x"})
            assert status == 401, path
        assert _request(base, "/api/search?q=abc")[0] == 401
        # and with the password the gate is out of the way (404/400 are fine -
        # they mean we got past auth into the app's own routing)
        status, _ = _request(
            base, "/api/search?q=abc", auth=_basic("james", "whykennywhy")
        )
        assert status != 401


def test_password_loads_from_env_then_file(tmp_path, monkeypatch):
    path = tmp_path / "teamscout_auth.txt"
    path.write_text("\n\n  fromfile  \nignored second line\n", encoding="utf-8")
    monkeypatch.delenv("TEAMSCOUT_PASSWORD", raising=False)
    assert team_scout.load_teamscout_password(str(path)) == "fromfile"
    monkeypatch.setenv("TEAMSCOUT_PASSWORD", "fromenv")
    assert team_scout.load_teamscout_password(str(path)) == "fromenv"
    # missing file is empty, which makes run_team_scout fail closed
    monkeypatch.delenv("TEAMSCOUT_PASSWORD", raising=False)
    assert team_scout.load_teamscout_password(str(tmp_path / "nope.txt")) == ""


def _empty_overrides():
    return {"players": {}, "rosters": {}, "replaced": {}, "accounts": {}}


def _split_payload():
    def player(pid, name, team_key=None, opponent=None):
        matches = []
        if team_key:
            matches.append({
                "team_key": team_key, "result": "W", "opponent": opponent or "",
            })
        return {"id": pid, "name": name, "official": {"matches": matches}}

    return {
        "season": "S22",
        "seasonId": 22,
        "patches": [],
        "officialSource": {"league": "LD2L SEASON XXII"},
        "teams": [
            {
                "key": "alpha", "name": "Alpha", "short": "Alpha",
                "league": "LD2L SEASON XXII",
                "postedRoster": [1, 2], "roster": [1, 9], "edited": True,
                "replaced": [2],
                "replacedPlayers": [{"id": 2, "name": "Gone Alpha", "games": 1}],
                "replacements": [],
            },
            {
                "key": "bravo", "name": "Bravo", "short": "Bravo",
                "league": "LD2L SEASON XXII",
                "postedRoster": [3], "roster": [3, 7], "edited": True,
                "replaced": [], "replacedPlayers": [], "replacements": [],
            },
        ],
        "players": [
            {
                "id": 1, "name": "AlphaOne",
                "official": {"matches": [
                    {"team_key": "alpha", "result": "W", "opponent": "Bravo"},
                    {"team_key": "secret", "result": "L", "opponent": "Rd2lOnly"},
                ]},
            },
            player(2, "Gone Alpha"),
            player(3, "BravoThree"),
            player(7, "HiddenSub"),
            player(8, "PulledSecret"),
        ],
        "matchups": [{"aKey": "alpha", "bKey": "bravo", "a": "Alpha", "b": "Bravo"}],
        "standings": [
            {"key": "alpha", "name": "Alpha"},
            {"key": "bravo", "name": "Bravo"},
        ],
        "teamMatches": [{
            "radiant": {"team_key": "alpha", "name": "Alpha"},
            "dire": {"team_key": "bravo", "name": "Bravo"},
        }],
    }


def _ld2l_account():
    return {
        "user": "ld2l", "password": "alpha-secret", "team": "Alpha",
        "league": "ld2l", "locked": True,
    }


def _rd2l_account():
    return {
        "user": "rd2l", "password": "pond-secret", "team": "Pond",
        "league": "rd2l", "locked": True,
    }


def test_parse_accounts_keeps_a_single_shared_password():
    accounts = team_scout.parse_teamscout_accounts(
        "\n# comment\n  onlyone  \n"
    )
    assert len(accounts) == 1
    assert accounts[0]["user"] is None
    assert accounts[0]["password"] == "onlyone"
    assert accounts[0]["locked"] is False


def test_parse_accounts_keeps_shared_password_beside_a_team_line():
    accounts = team_scout.parse_teamscout_accounts(
        "sharedsecret\nrd2l:pond-secret:rd2l:Jiggy\n"
    )
    assert accounts[0]["user"] is None
    assert accounts[0]["password"] == "sharedsecret"
    assert accounts[0]["locked"] is False
    assert accounts[1]["user"] == "rd2l"
    assert accounts[1]["team"] == "Jiggy"
    assert accounts[1]["locked"] is True


def test_parse_admin_signin():
    accounts = team_scout.parse_teamscout_accounts("admin:top-secret:*\n")
    assert accounts[0]["user"] == "admin"
    assert accounts[0]["admin"] is True
    assert accounts[0]["locked"] is False
    assert accounts[0]["team"] is None


def test_admin_view_includes_every_team_signin():
    overrides = _empty_overrides()
    overrides["accounts"]["rd2l"] = {
        "players": {"8": {"name": "PulledSecret"}},
        "rosters": {"pond": [8]},
        "replaced": {},
    }
    admin = {
        "user": "admin", "password": "top-secret", "team": None,
        "league": None, "locked": False, "admin": True,
    }
    accounts = [_ld2l_account(), _rd2l_account(), admin]
    view = team_scout.view_for_account(_split_payload(), admin, overrides, accounts)
    assert {team["key"] for team in view["teams"]} >= {"alpha", "bravo", "pond"}
    assert {player["name"] for player in view["players"]} >= {"AlphaOne", "PulledSecret"}
    assert view["account"]["admin"] is True
    assert {row["user"] for row in view["account"]["signins"]} == {"ld2l", "rd2l"}
    assert "alpha-secret" not in json.dumps(view)
    assert "pond-secret" not in json.dumps(view)
    shared = team_scout.view_for_account(
        _split_payload(),
        {"user": None, "password": "shared", "locked": False},
        overrides,
        accounts,
    )
    assert "pond" not in {team["key"] for team in shared["teams"]}
    assert "PulledSecret" not in {player["name"] for player in shared["players"]}
    assert shared["account"]["admin"] is False


def test_parse_accounts_locks_each_team():
    text = (
        "# teams\n"
        "ld2l:alpha-secret:ld2l:The Alpha\n"
        "rd2l:pond-secret:rd2l:Pond Rats\n"
        "ld2l:ignored:ld2l:Duplicate\n"
    )
    accounts = team_scout.parse_teamscout_accounts(text)
    assert [row["user"] for row in accounts] == ["ld2l", "rd2l"]
    assert accounts[0]["team"] == "The Alpha"
    assert accounts[0]["league"] == "ld2l"
    assert accounts[0]["locked"] is True
    assert accounts[1]["password"] == "pond-secret"
    assert accounts[1]["team"] == "Pond Rats"


def test_locked_view_hides_the_other_league_and_private_edits():
    overrides = _empty_overrides()
    overrides["accounts"] = {
        "rd2l": {"players": {"8": {"name": "PulledSecret"}}, "rosters": {}, "replaced": {}},
    }
    ld2l = team_scout.view_for_account(_split_payload(), _ld2l_account(), overrides)
    names = {row["name"] for row in ld2l["players"]}
    assert "AlphaOne" in names
    assert "BravoThree" in names
    assert "HiddenSub" not in names
    assert "PulledSecret" not in names
    assert "Rd2lOnly" not in json.dumps(ld2l)
    alpha = next(team for team in ld2l["teams"] if team["key"] == "alpha")
    bravo = next(team for team in ld2l["teams"] if team["key"] == "bravo")
    assert alpha["roster"] == [1, 9]
    assert alpha["replaced"] == [2]
    assert bravo["roster"] == [3]
    assert bravo["edited"] is False
    assert ld2l["account"]["locked"] is True
    assert ld2l["account"]["teamKey"] == "alpha"

    rd2l = team_scout.view_for_account(_split_payload(), _rd2l_account(), overrides)
    rd2l_names = {row["name"] for row in rd2l["players"]}
    assert rd2l_names == {"PulledSecret"}
    assert [team["key"] for team in rd2l["teams"]] == ["pond"]
    assert rd2l["matchups"] == []
    assert rd2l["standings"] == []
    assert rd2l["teamMatches"] == []
    assert "Alpha" not in json.dumps(rd2l["teams"])
    assert "Bravo" not in json.dumps(rd2l)


def test_shared_password_keeps_rd2l_out_of_ld2l():
    payload = _split_payload()
    payload["teams"].append({
        "key": "jiggy", "name": "Jiggy", "short": "Jiggy",
        "league": "RD2L EST-TUES Season 39",
        "postedRoster": [11], "roster": [11],
        "replaced": [], "replacedPlayers": [], "replacements": [],
    })
    payload["players"].append({"id": 11, "name": "OnlyRd2l", "official": {"matches": []}})
    payload["standings"].append({
        "key": "jiggy", "name": "Jiggy", "league": "RD2L EST-TUES Season 39",
        "wins": 1, "losses": 1, "rank": 12,
    })
    payload["matchups"].append({
        "aKey": "jiggy", "bKey": "ducks", "a": "Jiggy", "b": "Ducks",
        "league": "RD2L EST-TUES Season 39",
    })
    shared = team_scout.view_for_account(
        payload, {"user": None, "password": "shared", "locked": False},
    )
    assert {team["key"] for team in shared["teams"]} == {"alpha", "bravo"}
    assert "OnlyRd2l" not in {player["name"] for player in shared["players"]}
    assert all("RD2L" not in str(row.get("league") or "") for row in shared["standings"])
    assert all(row.get("aKey") != "jiggy" for row in shared["matchups"])

    rd2l = team_scout.view_for_account(payload, _rd2l_account(), {})
    keys = {team["key"] for team in rd2l["teams"]}
    assert "jiggy" in keys
    assert "alpha" not in keys
    assert "bravo" not in keys


def _read(base, path="/", auth=None, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if auth is not None:
        req.add_header("Authorization", auth)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_named_signins_reject_the_other_password(monkeypatch):
    monkeypatch.setattr(team_scout, "load_overrides", lambda path=None: _empty_overrides())
    state = _FakeState()
    state.payload = _split_payload()
    accounts = [_ld2l_account(), _rd2l_account()]
    with _auth_server(monkeypatch, accounts, state) as base:
        status, page = _read(base, auth=_basic("ld2l", "alpha-secret"))
        assert status == 200
        assert "AlphaOne" in page
        assert "PulledSecret" not in page
        status, page = _read(base, auth=_basic("rd2l", "pond-secret"))
        assert status == 200
        assert "AlphaOne" not in page
        assert "BravoThree" not in page
        assert "Pond" in page
        assert _read(base, auth=_basic("rd2l", "alpha-secret"))[0] == 401
        assert _read(base, auth=_basic("ld2l", "pond-secret"))[0] == 401
        assert _read(base, auth=_basic("anyone", "alpha-secret"))[0] == 401


def test_locked_signin_cannot_edit_another_team(monkeypatch):
    monkeypatch.setattr(team_scout, "load_overrides", lambda path=None: _empty_overrides())
    saved = {}

    def _save(data, path=None):
        saved["data"] = data

    monkeypatch.setattr(team_scout, "save_overrides", _save)
    state = _FakeState()
    state.payload = _split_payload()
    with _auth_server(monkeypatch, [_ld2l_account()], state) as base:
        auth = _basic("ld2l", "alpha-secret")
        status, body = _read(
            base, "/api/roster", auth=auth, method="POST", body={"team": "bravo", "roster": [3]},
        )
        assert status == 403
        assert "data" not in saved
        status, body = _read(
            base, "/api/roster", auth=auth, method="POST", body={"team": "alpha", "roster": [1, 2]},
        )
        assert status == 200, body
        assert saved["data"]["accounts"]["ld2l"]["rosters"]["alpha"] == [1, 2]
        assert saved["data"]["rosters"] == {}


def test_pub_wards_keep_parsed_maps_and_queue_the_rest(tmp_path):
    from scout.cache import Cache

    cache = Cache(root=str(tmp_path))
    patches = [{"id": 60, "name": "7.41", "released": 100}]
    cache.set_match(9, {
        "match_id": 9, "start_time": 500, "patch": 60, "version": 22,
        "radiant_win": True,
        "players": [{
            "account_id": 7, "player_slot": 0, "hero_id": 3,
            "obs_log": [{"x": 80, "y": 90}], "sen_log": [],
        }],
    })

    class Online:
        def __init__(self):
            self.requested = []

        def recent_matches(self, sid):
            assert sid == 7
            return [
                {"match_id": 9, "start_time": 500},
                {"match_id": 8, "start_time": 400},
                {"match_id": 1, "start_time": 50},
            ]

        def match(self, match_id):
            assert match_id == 8
            return {"match_id": 8, "start_time": 400, "patch": 60, "version": None, "players": []}

        def request_parse(self, match_id):
            self.requested.append(match_id)
            return {}

    od = Online()
    rows, pending = team_scout.load_pub_wards(od, cache, 7, patches, {1}, offline=False)
    assert rows == [{
        "match_id": 9, "start_time": 500, "patch": 60, "hero_id": 3,
        "win": True, "is_radiant": True, "obs_map": [[80.0, 90.0]], "sen_map": [],
        "pub": True,
    }]
    assert pending is True
    assert od.requested == [8]

    class Offline:
        def recent_matches(self, sid):
            raise AssertionError(sid)

        def match(self, match_id):
            raise AssertionError(match_id)

        def request_parse(self, match_id):
            raise AssertionError(match_id)

    rows, pending = team_scout.load_pub_wards(Offline(), cache, 7, patches, {1}, offline=True)
    assert [row["match_id"] for row in rows] == [9]
    assert pending is True


class _SectionOD:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def _hit(self, value):
        self.calls += 1
        return None if self.fail else value

    def player(self, sid):
        return self._hit({"profile": {"account_id": sid}})

    def player_heroes(self, sid):
        return self._hit([])

    def matches(self, sid, **params):
        return self._hit([{"match_id": 1, "start_time": 2}])


def test_refresh_pub_sections_fetches_once_then_respects_ttl(tmp_path):
    from scout.cache import Cache
    from scout.fetch import MATCHES_SECTION
    from scout.team_scout import refresh_pub_sections

    cache = Cache(root=str(tmp_path))
    od = _SectionOD()
    assert refresh_pub_sections(od, cache, 7) == 3
    assert cache.get_section(7, MATCHES_SECTION, None) == [{"match_id": 1, "start_time": 2}]
    assert refresh_pub_sections(od, cache, 7) == 0


def test_refresh_pub_sections_failure_keeps_last_good_copy(tmp_path):
    from scout.cache import Cache
    from scout.fetch import MATCHES_SECTION
    from scout.team_scout import refresh_pub_sections

    cache = Cache(root=str(tmp_path))
    cache.set_section(7, MATCHES_SECTION, [{"match_id": 9, "start_time": 1}])
    doc_path = tmp_path / "players" / "7.json"
    import json
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["sections"][MATCHES_SECTION]["fetched_at"] = 0  # force it stale
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    refresh_pub_sections(_SectionOD(fail=True), cache, 7)
    assert cache.get_section(7, MATCHES_SECTION, None) == [{"match_id": 9, "start_time": 1}]


def test_render_page_auto_sets_this_weeks_opponent():
    page = render_page({"seasonId": 53, "players": [], "patches": [], "teams": []})
    assert "function weekFixture(key)" in page
    assert "function autoOpponent(force)" in page
    # boot, league switch, and loading My Team all re-point the opponent
    assert page.count("autoOpponent(") >= 4
    assert "if(side==='mine')autoOpponent(true)" in page


# ---------------------------------------------------------------------------
# Mock draft: the hero draft board behind the Team Scout sign-in
# ---------------------------------------------------------------------------

class _FakeHub:
    """Enough of HeroDraftHub to prove the handler delegates /draft to it."""

    def __init__(self):
        self.gets, self.posts = [], []

    def route_get(self, path, key="local", head=False):
        self.gets.append((path, key, head))
        if path == "/draft":
            return 200, "text/html; charset=utf-8", b"<html>board</html>"
        if path == "/draft/state":
            return 200, "application/json", b'{"phase":"setup"}'
        return None

    def route_post(self, path, body, key="local"):
        self.posts.append((path, body, key))
        return 200, {"ok": True}


@contextlib.contextmanager
def _draft_server(monkeypatch, accounts, hub):
    monkeypatch.setattr(team_scout, "AUTH_FAIL_DELAY", 0)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), team_scout._make_handler(_FakeState(), accounts, hub)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mock_draft_routes_need_the_password_and_are_keyed_per_signin(monkeypatch):
    hub = _FakeHub()
    accounts = team_scout.parse_teamscout_accounts(
        "ld2l:pw1:ld2l:Wolves\nrd2l:pw2:rd2l:Bears\n")
    with _draft_server(monkeypatch, accounts, hub) as base:
        assert _request(base, "/draft")[0] == 401
        assert _request(base, "/draft/state")[0] == 401
        assert _request(base, "/draft/start", method="POST", body={})[0] == 401
        assert not hub.gets and not hub.posts
        assert _request(base, "/draft?mine=wolves", auth=_basic("ld2l", "pw1"))[0] == 200
        assert _request(base, "/draft/state", auth=_basic("rd2l", "pw2"))[0] == 200
        status, _ = _request(base, "/draft/act", method="POST", body={"hid": 1},
                             auth=_basic("ld2l", "pw1"))
        assert status == 200
    assert [(p, k) for p, k, _ in hub.gets] == [("/draft", "ld2l"), ("/draft/state", "rd2l")]
    assert hub.posts == [("/draft/act", {"hid": 1}, "ld2l")]


def test_mock_draft_is_absent_when_no_hub_is_wired(monkeypatch):
    with _auth_server(monkeypatch) as base:
        assert _request(base, "/draft", auth=_basic("x", "whykennywhy"))[0] == 404


def test_page_has_a_mock_draft_button_that_launches_the_board():
    page = render_page({"season": "S22", "players": [], "teams": [], "account": {}})
    assert "data-mockdraft" in page
    assert 'window.open(mockDraftUrl(),' in page
    assert '"/draft"+(qs?"?"+qs:"")' in page
    # the nav's view switching must not swallow the launch button
    assert '.nav button[data-view]' in page
