from scout.keys import (gpm_key, keys_to_victory, lane_key, lane_outcome,
                        merge_keys, player_keys)


def _n(n, win, gpm=500, lane=50, pos=3, result=None):
    row = {"win": win, "gpm": gpm, "laneEff": lane, "position": pos}
    if result is not None:
        row["laneResult"] = result
    return [row] * n


def _player(name, rows, official=None, pid=1):
    return {"id": pid, "name": name, "rows": rows, "official_rows": official or []}


def _cliff(pos=3):
    """8-2 when ahead in lane/farm, 2-8 when behind."""
    return (
        _n(8, True, gpm=650, lane=60, pos=pos)
        + _n(2, False, gpm=650, lane=60, pos=pos)
        + _n(2, True, gpm=500, lane=40, pos=pos)
        + _n(8, False, gpm=500, lane=40, pos=pos)
    )


def test_lane_outcome_prefers_parsed_result_over_efficiency():
    assert lane_outcome({"laneResult": "loss", "laneEff": 70}) == "loss"
    assert lane_outcome({"laneEff": 55}) == "win"
    assert lane_outcome({"laneEff": 45}) == "loss"
    assert lane_outcome({"laneEff": 50}) == "draw"
    assert lane_outcome({}) is None


def test_lane_key_emits_offlane_action_for_a_sharp_split():
    key = lane_key({"id": 7, "name": "Winkx"}, _cliff(), "LD2L officials")
    assert key is not None
    assert key["action"] == "Win the offlane"
    assert key["kind"] == "lane"
    assert key["p"] < 0.05
    assert "Winkx is 2–8 (20%) when losing the lane" in key["reason"]
    assert "8–2 (80%) when winning it" in key["reason"]
    assert "LD2L officials" in key["reason"]


def test_lane_key_stays_silent_on_a_thin_or_weak_split():
    thin = _n(1, True, lane=40) + _n(3, False, lane=40) + _n(8, True, lane=60) + _n(2, False, lane=60)
    assert lane_key({"id": 1, "name": "Winkx"}, thin, "LD2L officials") is None
    even = _n(6, True, lane=60) + _n(5, False, lane=60) + _n(5, True, lane=40) + _n(6, False, lane=40)
    assert lane_key({"id": 1, "name": "Winkx"}, even, "LD2L officials") is None


def test_gpm_key_finds_the_rounded_midpoint_cut():
    enemy = gpm_key({"id": 7, "name": "Winkx"}, _cliff(), "enemy", "LD2L officials")
    assert enemy is not None
    assert enemy["action"] == "Keep Winkx under 600 GPM"
    assert "below 600 GPM" in enemy["reason"]
    assert "2–8 (20%)" in enemy["reason"]
    assert "8–2 (80%)" in enemy["reason"]
    ours = gpm_key({"id": 3, "name": "Alice"}, _cliff(), "mine", "LD2L officials")
    assert ours["action"] == "Get Alice over 600 GPM"


def test_gpm_key_skips_supports_and_small_farm_gaps():
    support = _cliff(pos=5)
    assert gpm_key({"id": 1, "name": "Pos5"}, support, "enemy", "LD2L officials") is None
    close = (
        _n(8, True, gpm=530, lane=60)
        + _n(2, False, gpm=530, lane=60)
        + _n(2, True, gpm=500, lane=40)
        + _n(8, False, gpm=500, lane=40)
    )
    assert gpm_key({"id": 1, "name": "Carry"}, close, "enemy", "LD2L officials") is None


def test_keys_to_victory_uses_officials_only():
    winkx = _player("Winkx", _cliff(), official=_cliff(), pid=7)
    alice = _player("Alice", _cliff(), official=_cliff(), pid=3)
    keys = keys_to_victory([alice], [winkx])
    actions = [k["action"] for k in keys]
    assert "Win the offlane" in actions
    offlane = next(k for k in keys if k["action"] == "Win the offlane")
    assert any("Alice" in reason for reason in offlane["reasons"])
    assert any("Winkx" in reason for reason in offlane["reasons"])
    assert all("LD2L officials" in reason for k in keys for reason in k["reasons"])
    assert not any("public games" in reason for k in keys for reason in k["reasons"])
    assert "Keep Winkx under 600 GPM" in actions
    assert "Get Alice over 600 GPM" in actions


def test_keys_to_victory_ignores_public_rows():
    keys = keys_to_victory(
        [_player("Alice", _cliff(), pid=3)],
        [_player("Winkx", _cliff(), pid=7)],
    )
    assert keys == []


def test_keys_to_victory_is_empty_without_a_real_split():
    mush = _n(10, True, gpm=520, lane=52) + _n(10, False, gpm=500, lane=48)
    keys = keys_to_victory(
        [_player("A", [], official=mush)],
        [_player("B", [], official=mush, pid=2)],
    )
    assert keys == []


def test_player_keys_can_return_both_lane_and_gpm():
    found = player_keys({"id": 7, "name": "Winkx"}, _cliff(), "enemy", "LD2L officials")
    kinds = {k["kind"] for k in found}
    assert kinds == {"lane", "gpm"}
    ours = player_keys({"id": 3, "name": "Alice"}, _cliff(), "mine", "LD2L officials")
    assert {k["kind"] for k in ours} == {"lane", "gpm"}


def test_merge_keys_stacks_the_same_action():
    alice = player_keys({"id": 3, "name": "Alice"}, _cliff(), "mine", "LD2L officials")
    winkx = player_keys({"id": 7, "name": "Winkx"}, _cliff(), "enemy", "LD2L officials")
    merged = merge_keys(alice + winkx)
    offlane = next(k for k in merged if k["action"] == "Win the offlane")
    assert len(offlane["reasons"]) == 2
    assert any("Alice" in reason for reason in offlane["reasons"])
    assert any("Winkx" in reason for reason in offlane["reasons"])


def test_caps_gpm_keys_to_the_two_sharpest():
    enemies = [
        _player("A", [], official=_cliff(), pid=1),
        _player("B", [], official=_cliff(), pid=2),
        _player("C", [], official=_cliff(), pid=3),
    ]
    keys = keys_to_victory([_player("Us", [], official=_cliff(), pid=9)], enemies)
    gpm = [k["action"] for k in keys if "GPM" in k["action"]]
    assert len(gpm) == 2
