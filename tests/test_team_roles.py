"""Execute the shipped role analysis in Node, including its rendered evidence."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from scout.team_scout_html import TEMPLATE, render_page


ROLE_JS = Path(__file__).resolve().parents[1] / "scout" / "team_roles.js"


def game(mid, positions=(1, 2, 3, 4, 5), ids=(1, 2, 3, 4, 5), **kwargs):
    return {
        "match_id": mid, "win": True,
        "players": [{"id": pid, "name": f"Player {pid}", "hero_id": pid,
                     "position": pos, "confidence": "high", "evidence": ["farm pattern"]}
                    for pid, pos in zip(ids, positions)],
        **kwargs,
    }


def analyze(games, roster=(1, 2, 3, 4, 5), replaced=()):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise Team Scout's role analysis")
    script = r"""
const fs=require('fs'),vm=require('vm');
const data=JSON.parse(fs.readFileSync(0,'utf8'));
const byId=new Map(data.roster.map(id=>[Number(id),{name:`Player ${id}`}])) ;
const POS={1:'Carry',2:'Mid',3:'Offlane',4:'Soft support',5:'Hard support'};
const E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const officialRoleAt=(id,mid)=>data.games.find(g=>String(g.match_id)===String(mid))?.players.find(p=>String(p.id)===String(id))||{};
const context={byId,POS,E,officialRoleAt,heroName:id=>`Hero ${id}`,heroIcon:()=>'',dbMatchUrl:id=>`https://www.dotabuff.com/matches/${id}`};
vm.createContext(context);
vm.runInContext(fs.readFileSync(data.script,'utf8'),context);
const roster=new Set(data.roster),replaced=new Set(data.replaced);
const result=context.teamRoleBreakdown(data.games,roster,replaced);
const html=context.teamRolesPanel(data.games,roster,replaced);
process.stdout.write(JSON.stringify({result,html}));
"""
    proc = subprocess.run(
        [node, "-e", script], input=json.dumps({"script": str(ROLE_JS),
        "games": games, "roster": roster, "replaced": replaced}),
        text=True, encoding="utf-8", capture_output=True, check=True,
    )
    return json.loads(proc.stdout)


def test_one_swap_in_four_full_roster_games_is_isolated_not_flex():
    data = analyze([game(1), game(2), game(3), game(4, (2, 1, 3, 4, 5))])
    d = data["result"]
    assert d["fullGames"] == 4
    assert d["fullChangeGames"] == 1  # One game, not two player deviations.
    assert not any(p["flexFull"] for p in d["players"])
    assert "no repeated flex pattern" in d["verdict"]
    assert {e["name"] for e in d["changes"]} == {"Player 1", "Player 2"}
    assert all(e["matches"] == [4] for e in d["changes"])
    assert 'href="https://www.dotabuff.com/matches/4"' in data["html"]
    assert "Isolated with full roster" in data["html"]


def test_standin_shuffle_does_not_establish_regular_core_or_support_flex():
    games = [game(1), game(2), game(3),
             game(4, (2, 1, 3, 5, 4), (1, 6, 3, 4, 5)),
             game(5, (2, 1, 3, 5, 4), (1, 6, 3, 4, 5))]
    d = analyze(games)["result"]
    assert d["fullGames"] == 3 and d["standinGames"] == 2
    assert d["standinChangeGames"] == 2 and d["fullChangeGames"] == 0
    assert "only in 2 games with stand-ins" in d["verdict"]
    assert not any(p["flexFull"] or p["supportFlex"] for p in d["players"])
    assert all(e["standins"] == ["Player 6"] and e["missing"] == ["Player 2"]
               for e in d["changes"])


@pytest.mark.parametrize("positions,support", [((2, 1, 3, 4, 5), False),
                                              ((1, 2, 3, 5, 4), True),
                                              ((1, 4, 3, 2, 5), False)])
def test_repeated_changes_require_two_games_in_each_role(positions, support):
    d = analyze([game(1), game(2), game(3, positions), game(4, positions)])["result"]
    flexible = [p for p in d["players"] if p["flexFull"]]
    assert len(flexible) == 2
    assert all(p["supportFlex"] == support for p in flexible)
    assert d["verdict"].startswith("Repeated support-role changes" if support
                                   else "Repeated full-roster role changes")
    assert "2 games" in d["verdict"]
    assert len(d["changes"]) == 2


@pytest.mark.parametrize("confidence,evidence", [("low", ["safe lane"]),
                                                 (None, []),
                                                 ("high", ["hero profile"])])
def test_weak_inference_cannot_establish_flex(confidence, evidence):
    games = [game(1), game(2), game(3), game(4, (2, 1, 3, 4, 5)),
             game(5, (2, 1, 3, 4, 5))]
    for g in games[3:]:
        for p in g["players"][:2]:
            p.update(confidence=confidence, evidence=evidence)
    d = analyze(games)["result"]
    assert not d["changes"]
    assert len(d["uncertainChanges"]) == 2
    assert all(e["reasons"] == ["weak role evidence"] for e in d["uncertainChanges"])
    assert not any(p["flexFull"] for p in d["players"])


def test_conflicting_positions_cannot_be_reported_as_swaps():
    d = analyze([game(1), game(2), game(3), game(4, (1, 2, 4, 4, 5)),
                 game(5, (1, 2, 4, 4, 5))])["result"]
    assert not d["changes"]
    assert d["uncertainChanges"][0]["reasons"] == ["conflicting team positions"]
    assert not any(p["flexFull"] for p in d["players"])


@pytest.mark.parametrize("ids", [(1, 2, 3, 4), (1, 2, 3, 4, None), (1, 2, 3, 4, 0)])
def test_incomplete_or_anonymous_lineups_are_never_full_roster(ids):
    d = analyze([game(1, ids=ids), game(2, ids=ids), game(3, ids=ids)])["result"]
    assert d["fullGames"] == 0 and d["standinGames"] == 0
    assert d["unknownGames"] == 3
    assert "regular-team flex is unproven" in d["verdict"]
    assert len([p for p in d["players"] if p["posted"]]) == 5


def test_no_full_roster_baseline_cannot_imply_stability_or_standin_causality():
    d = analyze([game(1, ids=(1, 6, 3, 4, 5)),
                 game(2, ids=(1, 6, 3, 4, 5)),
                 game(3, (2, 1, 3, 4, 5), (1, 6, 3, 4, 5))])["result"]
    assert d["fullGames"] == 0 and d["standinGames"] == 3
    assert not d["changes"]
    assert "regular-team flex is unproven" in d["verdict"]


def test_substitution_heavy_history_does_not_overwrite_full_roster_main_role():
    games = [game(1), game(2), game(3)]
    games.extend(game(i, (2, 1, 3, 4, 5), (1, 6, 3, 4, 5)) for i in range(4, 10))
    d = analyze(games)["result"]
    p = next(p for p in d["players"] if p["id"] == "1")
    assert p["primary"]["position"] == 1 and p["baselineEstablished"]
    assert p["flexStandin"] and not p["flexFull"]
    assert d["standinChangeGames"] == 6


def test_duplicate_games_and_players_do_not_inflate_evidence():
    g = game(4, (2, 1, 3, 4, 5))
    g["players"].append(dict(g["players"][0]))
    d = analyze([game(1), game(2), game(3), g, g, {**g, "match_id": "4"}])["result"]
    assert d["games"] == 4 and d["fullGames"] == 4 and d["fullChangeGames"] == 1
    assert not any(p["flexFull"] for p in d["players"])


def test_string_roster_ids_match_numeric_match_ids():
    d = analyze([game(1), game(2), game(3), game(4)], roster=("1", "2", "3", "4", "5"))["result"]
    assert d["fullGames"] == 4 and d["standinGames"] == 0
    assert "Mostly settled roles" in d["verdict"]


def test_former_player_games_cannot_establish_current_flex():
    games = [game(1, ids=(1, 2, 3, 4, 6)), game(2, ids=(1, 2, 3, 4, 6)),
             game(3, (2, 1, 3, 4, 5), (1, 2, 3, 4, 6)),
             game(4, (2, 1, 3, 4, 5), (1, 2, 3, 4, 6)), game(5)]
    d = analyze(games, replaced=(6,))["result"]
    assert d["currentGames"] == 1 and d["fullGames"] == 1
    assert not any(p["flexFull"] for p in d["players"])
    assert next(p for p in d["players"] if p["id"] == "6")["games"] == 4


def test_historical_fallback_is_labelled_and_never_calls_current_team_flexible():
    games = [game(1, ids=(1, 2, 3, 4, 6)), game(2, ids=(1, 2, 3, 4, 6)),
             game(3, (2, 1, 3, 4, 5), (1, 2, 3, 4, 6))]
    d = analyze(games, replaced=(6,))["result"]
    assert d["eraFallback"] and d["fullGames"] == 0
    assert "historical roles" in d["verdict"]
    assert not d["changes"] and not d["uncertainChanges"]


def test_incomplete_known_roster_is_not_invented_from_appearance_frequency():
    d = analyze([game(1), game(2), game(3)], roster=(1, 2, 3, 4))["result"]
    assert d["fullGames"] == 0
    assert "known five-player roster" in d["verdict"]


@pytest.mark.parametrize("sides,expected", [([True] * 5, True),
                                           ([True, True, False, False, False], False),
                                           ([None] * 5, False)])
def test_custom_roster_requires_players_to_be_teammates(sides, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required")
    source = re.search(r"function playerOfficialLineups\(.*?^\}", TEMPLATE,
                       re.MULTILINE | re.DOTALL).group(0)
    ps = [{"id": i, "name": f"Player {i}", "official": {"matches": [
        {"match_id": 42, "is_radiant": side, "result": "W", "hero_id": i}]}}
          for i, side in enumerate(sides, 1)]
    proc = subprocess.run([node, "-e", source + "\nconsole.log(JSON.stringify(playerOfficialLineups(" + json.dumps(ps) + ")));"],
                          capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout)[0]["lineupKnown"] is expected
    d = analyze([game(1, lineupKnown=expected), game(2, lineupKnown=expected)])["result"]
    assert d["fullGames"] == (2 if expected else 0)


def test_missing_positions_are_visible_and_do_not_imply_stability():
    data = analyze([game(1, (None,) * 5), game(2, (None,) * 5), game(3, (None,) * 5)])
    d = data["result"]
    assert d["usable"] == 0 and d["observations"] == 15
    assert "limited" in d["verdict"]
    assert "3 unclassified" in data["html"]
    assert "Everyone stays" not in data["html"]


def test_shared_hero_at_same_position_is_not_role_flex():
    games = [game(1), game(2), game(3, ids=(6, 2, 3, 4, 5))]
    games[2]["players"][0]["hero_id"] = 1
    d = analyze(games)["result"]
    hero = next(h for h in d["flexHeroes"] if h["id"] == 1)
    assert hero["label"] == "Sharing involves stand-ins or unknown players"
    assert not any(p["flexFull"] for p in d["players"])


def test_player_and_standin_names_are_escaped_in_evidence():
    games = [game(1), game(2), game(3), game(4, (2, 1, 3, 4, 5), (1, 6, 3, 4, 5))]
    games[-1]["players"][0]["name"] = '<img src=x onerror="bad()">'
    games[-1]["players"][1]["name"] = '<script>bad()</script>'
    html = analyze(games)["html"]
    assert '<img src=x' not in html and '<script>bad()' not in html
    assert '&lt;img' in html and '&lt;script&gt;' in html


def test_role_script_is_embedded_in_self_contained_render():
    page = render_page({"seasonId": 53, "players": [], "patches": [], "teams": []})
    assert "__TEAM_ROLES__" not in page
    assert ROLE_JS.read_text(encoding="utf-8") in page
    assert "function officialRoleAt" in page
    assert "Role changes and evidence" in page
    assert "They flex." not in page
