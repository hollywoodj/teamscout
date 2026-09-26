import io

from PIL import Image

from scout.ward_render import (
    GAP, HEADER_H, LABEL_H, LEGEND_H, PAD, SHEET_MAP_SIZE,
    cluster_mid_spots, cluster_wards, in_mid_window, mid_ward_events,
    player_side_wards, render_mid_ward, render_ward_sheet, select_map_players,
    ward_patch_id, world_to_px,
)


def test_cluster_wards_bins_nearby_points():
    pts = [[100, 100], [101, 102], [150, 150]]
    clusters = cluster_wards(pts, bin=5)
    assert len(clusters) == 2
    # sorted ascending by n -> the lone point comes first
    assert clusters[0]["n"] == 1
    assert clusters[-1]["n"] == 2
    big = clusters[-1]
    assert abs(big["x"] - 100.5) < 0.01
    assert abs(big["y"] - 101) < 0.01


def test_cluster_wards_ignores_bad_points():
    pts = [[1, 2], ["x", "y"], [None, None], [3]]
    clusters = cluster_wards(pts)
    assert len(clusters) == 1


def test_world_to_px_matches_web_formula():
    # x=64,y=64 -> left 0%, top 100% (bottom-left of a top-origin canvas)
    x, y = world_to_px(64, 64, 240)
    assert abs(x - 0) < 0.01
    assert abs(y - 240) < 0.01
    # x=192,y=192 -> left 100%, top 0%
    x, y = world_to_px(192, 192, 240)
    assert abs(x - 240) < 0.01
    assert abs(y - 0) < 0.01
    # midpoint -> 50/50
    x, y = world_to_px(128, 128, 240)
    assert abs(x - 120) < 0.01
    assert abs(y - 120) < 0.01


def _official_row(team_key, position, patch, is_radiant, obs=None, sen=None):
    return {
        "team_key": team_key, "position": position, "patch": patch,
        "is_radiant": is_radiant, "obs_map": obs or [], "sen_map": sen or [],
    }


def build_payload():
    players = [
        # Two candidates for Pos 1: player 2 has played it more.
        {"id": 1, "name": "CarryA", "official": {"matches": [
            _official_row("teamalpha", 1, 60, True, obs=[[100, 100]]),
        ]}},
        {"id": 2, "name": "CarryB", "official": {"matches": [
            _official_row("teamalpha", 1, 60, True, obs=[[110, 110]]),
            _official_row("teamalpha", 1, 60, False, sen=[[120, 120]]),
        ]}},
        {"id": 3, "name": "Support4", "official": {"matches": [
            _official_row("teamalpha", 4, 60, True, obs=[[90, 90], [95, 95]]),
        ]}},
        # No pos 5 player on this roster -> position should be skipped.
        {"id": 4, "name": "OffLane", "official": {"matches": [
            _official_row("teamalpha", 3, 60, True),
        ]}},
        # Pos 2 player with pubWards fallback (no official ward-patch rows).
        {"id": 5, "name": "MidPlayer", "official": {"matches": [
            _official_row("teamalpha", 2, 60, True),
        ]}, "pubWards": [
            {"patch": 60, "is_radiant": True, "obs_map": [[70, 70]], "sen_map": []},
        ]},
    ]
    team = {"key": "teamalpha", "roster": [1, 2, 3, 4, 5]}
    payload = {
        "patches": [{"id": 60, "name": "7.41"}],
        "players": players,
        "teams": [team],
    }
    return payload, team


def test_ward_patch_id_finds_named_patch():
    payload, _team = build_payload()
    assert ward_patch_id(payload) == 60


def test_ward_patch_id_falls_back_when_missing():
    assert ward_patch_id({"patches": []}) == 60


def test_select_map_players_breaks_ties_by_games_and_skips_missing():
    payload, team = build_payload()
    rows = select_map_players(payload, team, positions=(1, 4, 5))
    positions_selected = [p for p, _player in rows]
    assert positions_selected == [1, 4]  # pos 5 skipped, nobody plays it
    pos1_player = next(player for p, player in rows if p == 1)
    assert pos1_player["name"] == "CarryB"  # 2 rows at pos 1 beats 1 row


def test_player_side_wards_splits_by_side():
    payload, team = build_payload()
    player = next(p for p in payload["players"] if p["id"] == 2)
    wards = player_side_wards(player, "teamalpha", 60)
    assert wards["pubs"] is False
    assert wards["radiant"]["games"] == 1
    assert wards["dire"]["games"] == 1
    assert len(wards["radiant"]["obs"]) == 1
    assert len(wards["dire"]["sen"]) == 1


def test_player_side_wards_falls_back_to_pubs():
    payload, team = build_payload()
    player = next(p for p in payload["players"] if p["id"] == 5)
    wards = player_side_wards(player, "teamalpha", 60)
    assert wards["pubs"] is True
    assert wards["radiant"]["games"] == 1
    assert len(wards["radiant"]["obs"]) == 1


def test_render_ward_sheet_png_dimensions_and_row_scaling():
    payload, team = build_payload()
    png_bytes = render_ward_sheet(payload, team, positions=(1, 4, 5))
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.width == 816

    top = PAD + HEADER_H + GAP
    row_h = LABEL_H + SHEET_MAP_SIZE + GAP
    n_rows = 2  # pos 1 and pos 4 selected, pos 5 skipped
    expected_height = top + n_rows * row_h + LEGEND_H + PAD
    assert img.height == expected_height


def test_render_ward_sheet_handles_no_selected_players():
    payload = {"patches": [{"id": 60, "name": "7.41"}], "players": [],
               "teams": [{"key": "teamalpha", "roster": []}]}
    png_bytes = render_ward_sheet(payload, payload["teams"][0], positions=(1, 4, 5))
    img = Image.open(io.BytesIO(png_bytes))
    top = PAD + HEADER_H + GAP
    row_h = LABEL_H + SHEET_MAP_SIZE + GAP
    expected_height = top + 1 * row_h + LEGEND_H + PAD  # n_rows floors at 1
    assert img.height == expected_height


# --------------------------------------------------------------------------
# Mid ward (rune to rune, before 1:00)
# --------------------------------------------------------------------------

def _mid_row(match_id, position, is_radiant, player_name, hero,
             obs=None, sen=None, patch=60, team_key="teamalpha"):
    return {
        "match_id": match_id, "team_key": team_key, "patch": patch,
        "is_radiant": is_radiant, "position": position,
        "player_name": player_name, "hero": hero,
        "obs_map": obs or [], "sen_map": sen or [],
    }


def _mid_payload(rows_by_player):
    players = [{"id": i, "name": name, "official": {"matches": rows}}
               for i, (name, rows) in enumerate(rows_by_player.items(), start=1)]
    return {
        "patches": [{"id": 60, "name": "7.41"}],
        "players": players,
        "teams": [{"key": "teamalpha", "name": "Team Alpha", "short": "ALPHA",
                   "roster": list(range(1, len(rows_by_player) + 1))}],
    }


def test_mid_ward_first_observer_per_game_ignores_later():
    payload = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit", obs=[[126.2, 127.5, -58]])],
        "Support": [_mid_row(1, 4, True, "Support", "Storm Spirit", obs=[[126.5, 127.5, -10]])],
    })
    team = payload["teams"][0]
    games, wards, mid_names = mid_ward_events(payload, team)
    obs = [w for w in wards["radiant"] if w["kind"] == "obs"]
    assert len(obs) == 1
    assert obs[0]["t"] == -58  # the earlier placement wins, the later one is dropped
    assert games["radiant"] == {1}
    assert mid_names == {"Mid"}


def test_mid_ward_teammate_placement_marked_and_counted():
    payload = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit")],
        "Support": [_mid_row(1, 4, True, "Support", "Storm Spirit", obs=[[126.2, 127.5, -51]])],
    })
    team = payload["teams"][0]
    _, wards, _ = mid_ward_events(payload, team)
    obs = [w for w in wards["radiant"] if w["kind"] == "obs"]
    assert len(obs) == 1
    assert obs[0]["is_mid"] is False

    _png_bytes, summary = render_mid_ward(payload, team)
    assert summary["radiant"]["withObserver"] == 1
    assert summary["radiant"]["byTeammate"] == 1


def test_mid_ward_cutoff_excludes_60_includes_negative():
    payload_at_cutoff = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit", obs=[[126.2, 127.5, 60]])],
    })
    team = payload_at_cutoff["teams"][0]
    games, wards, _ = mid_ward_events(payload_at_cutoff, team, cutoff=60)
    assert games["radiant"] == {1}
    assert [w for w in wards["radiant"] if w["kind"] == "obs"] == []

    payload_pre_horn = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit", obs=[[126.2, 127.5, -119]])],
    })
    _, wards2, _ = mid_ward_events(payload_pre_horn, team, cutoff=60)
    obs2 = [w for w in wards2["radiant"] if w["kind"] == "obs"]
    assert len(obs2) == 1
    assert obs2[0]["t"] == -119


def test_mid_ward_window_excludes_outside_points():
    assert in_mid_window(126.2, 127.5) is True
    assert in_mid_window(50, 50) is False

    payload = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit", obs=[[50, 50, -30]])],
    })
    team = payload["teams"][0]
    _, wards, _ = mid_ward_events(payload, team)
    assert wards["radiant"] == []


def test_cluster_mid_spots_joins_within_radius_and_splits_beyond():
    close = [
        {"kind": "obs", "x": 120.0, "y": 120.0, "t": -50, "is_mid": True},
        {"kind": "obs", "x": 121.0, "y": 120.5, "t": -40, "is_mid": True},
    ]
    spots = cluster_mid_spots(close, radius=2.0)
    assert len(spots) == 1
    assert spots[0]["label"] == "A"
    assert len(spots[0]["items"]) == 2

    far = [
        {"kind": "obs", "x": 120.0, "y": 120.0, "t": -50, "is_mid": True},
        {"kind": "obs", "x": 130.0, "y": 130.0, "t": -40, "is_mid": True},
    ]
    spots_far = cluster_mid_spots(far, radius=2.0)
    assert len(spots_far) == 2
    assert {s["label"] for s in spots_far} == {"A", "B"}


def test_render_mid_ward_returns_valid_png_and_summary():
    payload = _mid_payload({
        "Mid": [_mid_row(1, 2, True, "Mid", "Storm Spirit", obs=[[126.2, 127.5, -58]])],
        "Support": [_mid_row(1, 4, True, "Support", "Storm Spirit", sen=[[136.0, 119.0, -30]])],
    })
    team = payload["teams"][0]
    png_bytes, summary = render_mid_ward(payload, team)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert set(summary.keys()) == {"radiant", "dire"}
    assert summary["radiant"]["games"] == 1
    assert summary["dire"]["games"] == 0
