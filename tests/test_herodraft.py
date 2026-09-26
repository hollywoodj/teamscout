from scout import config
from scout.herodraft import (
    CM_SEQUENCE, DraftState, build_draft_book, first_pick_side,
    scout_pick_value,
)


def _match(team_key, hid, win, first=True):
    team = 0 if first else 1
    return {
        "radiant": {"team_key": team_key if first else "other"},
        "dire": {"team_key": "other" if first else team_key},
        "radiant_win": win if first else (not win),
        "picks_bans": [
            {"hero_id": hid, "is_pick": True, "team": team, "order": 7},
        ],
    }


def _prof(sid, name="P"):
    return {"steam32": sid, "name": name, "mmr": 1000, "pref_role": "Any",
            "heroes": {}, "recent": {}, "league": {}}


def _state(tmp_path, monkeypatch, book, enemy_key="wolves"):
    monkeypatch.setattr(config, "HERODRAFT_TEAMS_FILE",
                        str(tmp_path / "herodraft_teams.json"))
    pool = [{"steam32": i, "name": f"P{i}", "mmr": 1, "role": "Any"}
            for i in range(1, 11)]
    profiles = {i: _prof(i, f"P{i}") for i in range(1, 11)}
    # A high-comfort decoy so the bot has something else to want.
    profiles[6]["heroes"][9] = {"g": 80, "w": 48, "last": 2e9}
    heroes = {i: {"n": f"H{i}", "key": "", "attr": "str"} for i in range(1, 20)}
    league = {
        "teams": [{"key": enemy_key, "name": "Wolves", "short": "WLV",
                   "roster": [6, 7, 8, 9, 10]}],
        "books": {enemy_key: book},
    }
    state = DraftState(53, "S", pool, profiles, heroes, league=league)
    ok, msg = state.set_teams(
        [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], "Wolves",
        enemy_key=enemy_key)
    assert ok, msg
    ok, msg = state.start("enemy", "radiant")
    assert ok, msg
    return state


def test_first_pick_side_uses_earliest_pick_not_first_row():
    assert first_pick_side([
        {"is_pick": False, "team": 1, "order": 0, "hero_id": 1},
        {"is_pick": True, "team": 0, "order": 7, "hero_id": 2},
        {"is_pick": True, "team": 1, "order": 8, "hero_id": 3},
    ]) == 0
    assert first_pick_side([]) is None


def test_draft_book_counts_winning_first_picks():
    matches = [_match("wolves", 1, True) for _ in range(3)]
    book = build_draft_book(matches, "wolves")
    assert book["games"] == 3
    assert book["openers"][True][1] == {"g": 3, "w": 3}
    assert book["picks"][1]["g"] == 3
    assert book["picks"][1]["w"] == 3
    assert scout_pick_value(book, 1, 0, True) > scout_pick_value(
        book, 9, 0, True)


def test_bot_first_picks_the_3_0_opener_unless_banned(tmp_path, monkeypatch):
    book = build_draft_book([_match("wolves", 1, True) for _ in range(3)],
                            "wolves")
    state = _state(tmp_path, monkeypatch, book)
    pick_idx = next(i for i, step in enumerate(CM_SEQUENCE)
                    if step["type"] == "pick" and step["team"] == 0)
    state.idx = pick_idx
    top = state.bot_candidates(0, "pick", 4)
    assert top, "expected scouted candidates"
    assert top[0][0] == 1

    state.taken.add(1)
    blocked = state.bot_candidates(0, "pick", 4)
    assert all(hid != 1 for hid, _ in blocked)


# ---------------------------------------------------------------------------
# Official records: success-ranked, undefeated, per-player
# ---------------------------------------------------------------------------

from scout.herodraft import (  # noqa: E402
    HeroDraftHub, book_cards, hero_score, is_undefeated, load_meta_heroes,
    meta_value, record_edge, role_term, undefeated_bonus,
)


def _match_with_players(team_key, hid, win, sid):
    m = _match(team_key, hid, win)
    m["radiant"]["players"] = [{"id": sid, "hero_id": hid}]
    m["dire"]["players"] = []
    return m


def test_success_ranked_not_volume_ranked():
    # the old games×winrate product ranked a 5-5 habit above a 3-0 hero
    assert record_edge({"g": 3, "w": 3}) > record_edge({"g": 10, "w": 5}) == 0
    assert record_edge({"g": 3, "w": 0}) < 0
    assert record_edge({"g": 6, "w": 4}) < record_edge({"g": 3, "w": 3})
    three_oh = build_draft_book([_match("w", 1, True)] * 3, "w")
    five_five = build_draft_book(
        [_match("w", 1, True)] * 5 + [_match("w", 1, False)] * 5, "w")
    assert scout_pick_value(three_oh, 1, 2, False) > scout_pick_value(
        five_five, 1, 2, False)


def test_undefeated_bonus_grows_with_the_streak_and_needs_two_games():
    assert not is_undefeated({"g": 1, "w": 1})
    assert is_undefeated({"g": 2, "w": 2})
    assert not is_undefeated({"g": 4, "w": 3})
    assert 0 < undefeated_bonus({"g": 2, "w": 2}) < undefeated_bonus({"g": 4, "w": 4})
    assert undefeated_bonus({"g": 9, "w": 9}) == config.HERODRAFT_UNDEFEATED_TEAM_CAP
    two_oh = build_draft_book([_match("w", 1, True)] * 2, "w")
    three_one = build_draft_book(
        [_match("w", 1, True)] * 3 + [_match("w", 1, False)], "w")
    assert scout_pick_value(two_oh, 1, 2, False) > scout_pick_value(
        three_one, 1, 2, False)


def test_draft_book_records_who_played_what_and_cards_lead_with_undefeated():
    matches = ([_match_with_players("w", 1, True, 6)] * 2
               + [_match_with_players("w", 9, True, 7)] * 4
               + [_match_with_players("w", 9, False, 7)] * 2)
    book = build_draft_book(matches, "w")
    assert book["players"][6][1] == {"g": 2, "w": 2}
    assert book["players"][7][9] == {"g": 6, "w": 4}
    cards = book_cards(book, {6: "Ana", 7: "Bob"})
    assert [c["hid"] for c in cards] == [1, 9]        # 2-0 undefeated first
    assert cards[0]["undefeated"] and cards[0]["who"] == "Ana 2–0"
    assert not cards[1]["undefeated"] and cards[1]["who"] == "Bob 4–2"


def test_player_official_record_is_the_strongest_comfort_signal():
    plain = _prof(1)
    plain["heroes"][9] = {"g": 30, "w": 18, "last": 2e9}       # 60% over 30 pubs
    proven = _prof(2)
    proven["official"] = {9: {"g": 3, "w": 3}}                 # 3-0 in officials
    s_plain, why_plain = hero_score(plain, 9)
    s_proven, why_proven = hero_score(proven, 9)
    assert s_proven > s_plain
    assert "3–0 in officials (undefeated)" in why_proven
    assert "officials" not in why_plain
    losing = _prof(3)
    losing["official"] = {9: {"g": 3, "w": 0}}
    assert hero_score(losing, 9)[0] < s_proven / 3


def test_bot_reads_a_players_official_record(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, book={})
    # enemy player 7 is 3-0 on hero 12 in officials; nobody has pub comfort on it
    state.profiles[7]["official"] = {12: {"g": 3, "w": 3}}
    state.reset()
    ok, _ = state.start("enemy", "radiant")
    assert ok
    pick_idx = next(i for i, step in enumerate(CM_SEQUENCE)
                    if step["type"] == "pick" and step["team"] == 0)
    state.idx = pick_idx
    top = state.bot_candidates(0, "pick", 3)
    assert top[0][0] == 12
    assert "undefeated" in top[0][1]["who"]


# ---------------------------------------------------------------------------
# Curated meta + role coverage + smarter bans
# ---------------------------------------------------------------------------

def test_curated_meta_file_resolves_every_hero_name():
    from scout.heroes import HERO_FALLBACK
    heroes = {hid: {"n": n, "key": "", "attr": "all"} for hid, n in HERO_FALLBACK.items()}
    meta = load_meta_heroes(heroes)
    assert meta["patch"].startswith("7.4")
    assert meta["heroes"], "curated meta is empty"
    import json as _json
    with open(config.__file__.replace("config.py", "meta_heroes.json"), encoding="utf-8") as f:
        raw = _json.load(f)
    assert len(meta["heroes"]) == len(raw["heroes"]), "a hero name failed to resolve"
    assert meta_value(meta["heroes"], 70) == 1.0                  # Ursa is S
    assert meta_value(meta["heroes"], 999) == 0.0
    assert all(t["tier"] in ("S", "A", "B") for t in meta["heroes"].values())


def test_meta_heroes_join_the_bot_candidate_pool(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, book={})
    state.meta["tags"] = {14: {"tier": "S", "pos": [4], "note": ""}}
    pick_idx = next(i for i, step in enumerate(CM_SEQUENCE)
                    if step["type"] == "pick" and step["team"] == 0)
    state.idx = pick_idx
    hids = [h for h, _ in state.bot_candidates(0, "pick", 12)]
    assert 14 in hids
    assert state.rating(0, 14)["m"] == 1.0
    assert state.snapshot()["meta_tags"]["14"] == "S"


def test_role_coverage_penalises_a_fourth_carry_and_rewards_the_open_seat():
    carries = [1, 8, 44]                       # Anti-Mage, Juggernaut, PA
    assert role_term(carries, 48) < 0          # Luna: another pos 1
    assert role_term(carries, 5) > 0           # Crystal Maiden: pos 5 open
    assert role_term([], 1) == role_term([], 5) > 0   # nothing covered yet
    assert role_term(carries, 999999) == 0.0   # unknown hero: no opinion
    # urgency grows with the pick index
    assert abs(role_term([1, 8, 44, 2], 48)) > abs(role_term([1], 48))


def test_bot_fills_the_open_seat_late_in_the_draft(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, book={})
    # enemy has equal comfort on Luna (48, carry) and Crystal Maiden (5, pos 5)
    for hid in (48, 5):
        state.profiles[8]["heroes"][hid] = {"g": 40, "w": 24, "last": 2e9}
    state.reset()
    ok, _ = state.start("enemy", "radiant")
    assert ok
    state.picks[0] = [1, 8, 44, 2]             # three carries + Axe already
    state.taken.update(state.picks[0])
    pick_idx = next(i for i, step in enumerate(CM_SEQUENCE)
                    if step["type"] == "pick" and step["team"] == 0)
    state.idx = pick_idx
    top = state.bot_candidates(0, "pick", 2)
    assert top[0][0] == 5, "the support should beat a fourth carry"


def test_ban_is_discounted_when_the_banner_wants_the_hero_more(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, book={})
    # I (team 1) am 80g on hero 9; the enemy barely knows it. Banning it is a
    # waste of a ban: the threat rating stays, the ban total drops.
    state.profiles[1]["heroes"][9] = {"g": 80, "w": 56, "last": 2e9}
    state.profiles[6]["heroes"][9] = {"g": 3, "w": 2, "last": 2e9}
    state.reset()
    ok, _ = state.start("enemy", "radiant")
    assert ok
    ban_idx = next(i for i, step in enumerate(CM_SEQUENCE)
                   if step["type"] == "ban" and step["team"] == 1)
    state.idx = ban_idx
    cands = dict(state.bot_candidates(1, "ban", 20))
    assert 9 in cands
    assert cands[9]["self_discount"] > 0
    assert cands[9]["total"] < cands[9]["threat"]


def test_picks_are_seated_by_comfort_then_measured_position(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, book={})
    # player 6 is a career support (hero pool: CM, Lion), player 7 a career carry
    state.profiles[6]["heroes"] = {5: {"g": 90, "w": 50, "last": 2e9},
                                   26: {"g": 60, "w": 30, "last": 2e9}}
    state.profiles[7]["heroes"] = {1: {"g": 90, "w": 50, "last": 2e9},
                                   8: {"g": 60, "w": 30, "last": 2e9}}
    for prof in state.profiles.values():
        prof.pop("_aff", None)
    state.reset()
    ok, _ = state.start("enemy", "radiant")
    assert ok
    # Spectre (67): nobody has played it, so the carry player should get it
    who = state._assign_pick(0, 67)
    assert who == "P7"


# ---------------------------------------------------------------------------
# HeroDraftHub: routing shared by --herodraft and Team Scout's /draft
# ---------------------------------------------------------------------------

def test_hub_routes_before_and_after_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HERODRAFT_TEAMS_FILE",
                        str(tmp_path / "herodraft_teams.json"))
    hub = HeroDraftHub(53, offline=True)
    code, ctype, body = hub.route_get("/draft")
    assert code == 503 and b"loading" in body
    assert hub.route_post("/draft/start", {})[0] == 503
    assert hub.route_get("/api/other") is None
    # hand-load: what load() would fill in from cache
    hub.pool = [{"steam32": i, "name": f"P{i}", "mmr": 1, "role": "Any"}
                for i in range(1, 11)]
    hub.profiles = {i: _prof(i, f"P{i}") for i in range(1, 11)}
    hub.heroes = {i: {"n": f"H{i}", "key": "", "attr": "str"} for i in range(1, 30)}
    hub.page = b"<html>board</html>"
    hub.ready = True
    monkeypatch.setattr("scout.herodraft._league_stamp", lambda: hub._stamp)
    assert hub.route_get("/draft")[0] == 200
    code, ctype, body = hub.route_get("/draft/state", key="ld2l")
    assert code == 200 and json.loads(body)["phase"] == "setup"
    # one draft per sign-in
    code, obj = hub.route_post("/draft/teams", {"mine": [1, 2], "enemy": [6, 7],
                                                "enemy_name": "Wolves"}, key="ld2l")
    assert code == 200 and obj["ok"]
    assert hub.route_post("/draft/start", {"first": "me", "side": "radiant"},
                          key="ld2l")[0] == 200
    assert json.loads(hub.route_get("/draft/state", key="ld2l")[2])["phase"] == "drafting"
    assert json.loads(hub.route_get("/draft/state", key="rd2l")[2])["phase"] == "setup"
    assert hub.route_get("/sounds/../secret.mp3")[0] == 404
    hub.stop()


import json  # noqa: E402
