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
