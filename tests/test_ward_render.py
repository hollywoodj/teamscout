import io

from PIL import Image

import scout.ward_render as ward_render
from scout.ward_render import (
    CURRENT_MAP_ASSET_PATH, CURRENT_MAP_WORLD_BOUNDS, GAP, HEADER_H, LABEL_H, LEGEND_H,
    LANE_TOWER_WORLD, MID_PANEL_SIZE, MID_RUNE_SPOTS,
    MID_SUPERSAMPLE,
    MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF, OPENDOTA_MAP_WORLD_BOUNDS, PAD,
    SHEET_MAP_SIZE,
    SIDE_LANE_WINDOWS, _game_world_to_grid, _lane_crop_box, _map_asset_path,
    _map_world_bounds,
    _mid_to_src,
    _zoom_to_panel,
    bounds_rect, cluster_mid_spots, cluster_wards, grid_to_world, in_mid_window,
    lane_towers, mid_rune_spots, mid_ward_events,
    player_side_wards, render_mid_ward, render_player_lane_ward_rows,
    render_player_ward_rows,
    render_side_lane_ward, side_lane_ward_events,
    render_ward_sheet, select_map_players,
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


def test_heatmap_player_rows_keep_full_size_and_use_distinct_filenames():
    payload, team = build_payload()
    individual = render_player_ward_rows(payload, team)
    heatmaps = render_player_ward_rows(payload, team, heatmap=True)
    assert len(individual) == len(heatmaps)
    assert heatmaps[0][0] == "ward-heatmap-player-1.png"
    assert heatmaps[0][1] != individual[0][1]
    image = Image.open(io.BytesIO(heatmaps[0][1]))
    assert image.size == (SHEET_MAP_SIZE * 2 + GAP, SHEET_MAP_SIZE)


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


def test_player_ward_rows_include_every_roster_player_as_two_maps():
    payload, team = build_payload()
    rows = render_player_ward_rows(payload, team)
    assert len(rows) == len(team["roster"]) == 5
    assert [row[0] for row in rows] == [f"ward-player-{n}.png" for n in range(1, 6)]
    assert ["CarryA", "CarryB", "Support4", "OffLane", "MidPlayer"] == [
        row[2].split(":")[0] for row in rows]
    for _filename, data, _description in rows:
        image = Image.open(io.BytesIO(data))
        assert image.size == (SHEET_MAP_SIZE * 2 + GAP, SHEET_MAP_SIZE)


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
    assert img.size == (MID_PANEL_SIZE * 2 + 24, MID_PANEL_SIZE)
    assert set(summary.keys()) == {"radiant", "dire"}
    assert summary["radiant"]["games"] == 1
    assert summary["dire"]["games"] == 0


def test_side_lane_wards_use_first_observer_and_all_sentries_before_330():
    payload = _mid_payload({
        "Offlane": [_mid_row(1, 3, True, "Offlane", "Axe",
                             obs=[[95, 160, 209], [96, 160, 210]],
                             sen=[[95, 161, -20], [96, 161, 209], [96, 162, 210]])],
        "Support": [_mid_row(1, 4, True, "Support", "Hoodwink",
                             obs=[[95, 160, -10], [95, 160], [126, 127, -30]])],
    })
    games, wards = side_lane_ward_events(payload, payload["teams"][0], "top")
    assert games["radiant"] == {1}
    assert [w["t"] for w in wards["radiant"] if w["kind"] == "obs"] == [-10]
    assert [w["t"] for w in wards["radiant"] if w["kind"] == "sen"] == [-20, 209]
    assert wards["dire"] == []


def test_side_lane_crops_are_distinct_and_render_at_mid_zoom_size():
    payload = _mid_payload({
        "Carry": [_mid_row(1, 1, True, "Carry", "Drow Ranger",
                           obs=[[160, 95, 100], [95, 160, 100]])],
    })
    team = payload["teams"][0]
    _games, bottom = side_lane_ward_events(payload, team, "bottom")
    assert [(w["x"], w["y"]) for w in bottom["radiant"]] == [(160.0, 95.0)]
    png_bytes, summary = render_side_lane_ward(payload, team, "bottom")
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png_bytes)).size == (MID_PANEL_SIZE * 2 + 24, MID_PANEL_SIZE)
    assert summary["radiant"]["withObserver"] == 1
    assert summary["dire"]["withObserver"] == 0


def test_tower_landmarks_match_the_game_map_entity_origins():
    # Without a readable map the current minimap is projected like OpenDota's
    # image, -8192..8192 (where the Tier 1 origins sit on the lane art).
    # These are the pixel positions of the six fallback Tier 1 origins on a
    # 400px map.
    expected = {
        "mid": ((162, 234), (213, 184)),
        "top": ((45, 155), (71, 53)),
        "bottom": ((319, 356), (353, 255)),
    }
    assert CURRENT_MAP_WORLD_BOUNDS == OPENDOTA_MAP_WORLD_BOUNDS == (-8192, -8192, 8192, 8192)
    for lane, towers in LANE_TOWER_WORLD.items():
        for (world_x, world_y, _label), pixel in zip(towers, expected[lane]):
            grid_x, grid_y = _game_world_to_grid(world_x, world_y)
            assert tuple(round(value) for value in _mid_to_src(
                grid_x, grid_y, (400, 400), CURRENT_MAP_WORLD_BOUNDS)) == pixel


def test_world_to_px_accepts_symmetric_and_rectangular_bounds():
    assert bounds_rect((-8192, 8192)) == (-8192.0, -8192.0, 8192.0, 8192.0)
    assert bounds_rect([-5120, -4608, 5120, 5120]) == (-5120.0, -4608.0, 5120.0, 5120.0)
    assert grid_to_world(128, 128) == (0, 0)
    assert grid_to_world(64, 192) == (-8192, 8192)
    # A two-tuple keeps the old symmetric behaviour.
    assert world_to_px(64, 64, 240, (-8192, 8192)) == world_to_px(64, 64, 240)
    # An asymmetric boundary is honoured on each axis independently: the
    # world origin is not at the image centre.
    x, y = world_to_px(128, 128, 400, (-5120, -4608, 5120, 5120))
    assert abs(x - 200) < 1e-9
    assert abs(y - 400 * 5120 / 9728) < 1e-9
    # The boundary corners map to the image corners.
    left, bottom = world_to_px(*_game_world_to_grid(-5120, -4608), 400, (-5120, -4608, 5120, 5120))
    right, top = world_to_px(*_game_world_to_grid(5120, 5120), 400, (-5120, -4608, 5120, 5120))
    assert (round(left), round(bottom), round(right), round(top)) == (0, 400, 400, 0)


def _fake_landmarks():
    return {
        "bounds": [-9000.0, -8500.0, 8800.0, 9100.0],
        "towers": [
            {"side": "radiant", "tier": 1, "lane": "mid", "name": "npc_dota_goodguys_tower1_mid",
             "x": -1500.0, "y": -1400.0},
            {"side": "dire", "tier": 1, "lane": "mid", "name": "npc_dota_badguys_tower1_mid",
             "x": 500.0, "y": 650.0},
            {"side": "radiant", "tier": 2, "lane": "mid", "name": "npc_dota_goodguys_tower2_mid",
             "x": -3500.0, "y": -3000.0},
            {"side": "dire", "tier": 1, "lane": "top", "name": "npc_dota_badguys_tower1_top",
             "x": -5300.0, "y": 6000.0},
        ],
        "runes": [
            {"kind": "bounty", "name": "", "x": -4000.0, "y": 3000.0},
            {"kind": "powerup", "name": "", "x": -1700.0, "y": 1100.0},
            {"kind": "powerup", "name": "", "x": 1700.0, "y": -1100.0},
            {"kind": "xp", "name": "", "x": -7000.0, "y": 1000.0},
        ],
    }


def test_map_landmarks_drive_bounds_towers_and_rune_spots(monkeypatch):
    monkeypatch.setattr(ward_render, "map_landmarks", _fake_landmarks)
    # The installed minimap uses the map's own boundary; OpenDota's image
    # keeps OpenDota's projection.
    assert _map_world_bounds(CURRENT_MAP_ASSET_PATH) == (-9000.0, -8500.0, 8800.0, 9100.0)
    assert _map_world_bounds(ward_render.MAP_ASSET_PATH) == OPENDOTA_MAP_WORLD_BOUNDS
    # Every tower on the lane is offered (the crop decides visibility).
    assert lane_towers("mid") == ((-1500.0, -1400.0, "R T1"), (500.0, 650.0, "D T1"),
                                  (-3500.0, -3000.0, "R T2"))
    assert lane_towers("top") == ((-5300.0, 6000.0, "D T1"),)
    # Only power-rune spawners (where water runes spawn) mark the mid crop.
    assert mid_rune_spots() == [_game_world_to_grid(-1700.0, 1100.0), _game_world_to_grid(1700.0, -1100.0)]


def test_map_landmark_fallbacks_when_no_map_is_readable(monkeypatch):
    monkeypatch.setattr(ward_render, "map_landmarks", lambda: None)
    assert _map_world_bounds(CURRENT_MAP_ASSET_PATH) == CURRENT_MAP_WORLD_BOUNDS
    assert lane_towers("bottom") == LANE_TOWER_WORLD["bottom"]
    assert mid_rune_spots() == list(MID_RUNE_SPOTS)
    # A map whose lumps lack a lane still falls back for that lane only.
    monkeypatch.setattr(ward_render, "map_landmarks", lambda: {"towers": _fake_landmarks()["towers"], "runes": []})
    assert lane_towers("bottom") == LANE_TOWER_WORLD["bottom"]
    assert lane_towers("top") == ((-5300.0, 6000.0, "D T1"),)
    assert mid_rune_spots() == list(MID_RUNE_SPOTS)


def test_lane_render_uses_landmark_towers_and_bounds(monkeypatch):
    monkeypatch.setattr(ward_render, "map_landmarks", _fake_landmarks)
    monkeypatch.setattr(ward_render, "_map_asset_path", lambda: CURRENT_MAP_ASSET_PATH)
    monkeypatch.setattr(ward_render, "_load_mid_map_base",
                        lambda: (Image.new("RGB", (512, 512), "#334455"), _map_world_bounds(CURRENT_MAP_ASSET_PATH)))
    payload = _mid_payload({"Mid": [_mid_row(1, 2, True, "Mid", "Hero")]})
    team = payload["teams"][0]
    png, _summary = render_mid_ward(payload, team)
    image = Image.open(io.BytesIO(png)).convert("RGB")
    bounds = _map_world_bounds(CURRENT_MAP_ASSET_PATH)
    for world_x, world_y, label in lane_towers("mid"):
        x, y = _game_world_to_grid(world_x, world_y)
        if not (abs(x - MID_WINDOW_CX) <= MID_WINDOW_HALF and abs(y - MID_WINDOW_CY) <= MID_WINDOW_HALF):
            continue
        px, py = _zoom_to_panel(x, y, MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF, (512, 512), bounds)
        center = (round(px / 2), round(py / 2))
        red, green, _blue = image.getpixel((center[0] + 17, center[1]))
        assert (green > red * 1.3) if label.startswith("R") else (red > green * 1.3)
        assert min(image.getpixel(center)) > 220


def test_tower_projection_uses_the_exact_rounded_image_crop():
    # A tower and the background must use the same integer crop bounds.
    # The old continuous-window transform displaced the overlay after crop.
    for source_size, bounds in (((900, 900), (-8192, 8192)),
                                ((400, 400), CURRENT_MAP_WORLD_BOUNDS)):
        for lane, (cx, cy, half) in (("mid", (MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF)),
                                    *SIDE_LANE_WINDOWS.items()):
            left, top, right, bottom = _lane_crop_box(cx, cy, half, source_size, bounds)
            for world_x, world_y, _label in LANE_TOWER_WORLD[lane]:
                grid_x, grid_y = _game_world_to_grid(world_x, world_y)
                source_x, source_y = _mid_to_src(grid_x, grid_y, source_size, bounds)
                panel_x, panel_y = _zoom_to_panel(grid_x, grid_y, cx, cy, half,
                                                  source_size, bounds)
                scale = MID_PANEL_SIZE * MID_SUPERSAMPLE
                assert abs(left + panel_x / scale * (right - left) - source_x) < 1e-9
                assert abs(top + panel_y / scale * (bottom - top) - source_y) < 1e-9


def test_tower_landmarks_are_visible_in_both_panels_of_every_lane():
    payload = _mid_payload({"Mid": [_mid_row(1, 2, True, "Mid", "Hero")]})
    team = payload["teams"][0]
    map_path = _map_asset_path()
    source_size = Image.open(map_path).size
    bounds = _map_world_bounds(map_path)
    for lane in ("mid", "top", "bottom"):
        png, _summary = (render_mid_ward(payload, team) if lane == "mid"
                         else render_side_lane_ward(payload, team, lane))
        image = Image.open(io.BytesIO(png)).convert("RGB")
        cx, cy, half = ((MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF)
                        if lane == "mid" else SIDE_LANE_WINDOWS[lane])
        for world_x, world_y, label in LANE_TOWER_WORLD[lane]:
            x, y = _game_world_to_grid(world_x, world_y)
            px, py = _zoom_to_panel(x, y, cx, cy, half, source_size, bounds)
            for offset in (0, MID_PANEL_SIZE + 24):
                center = (round(px / 2) + offset, round(py / 2))
                red, green, _blue = image.getpixel((center[0] + 17, center[1]))
                assert (green > red * 1.3) if label.startswith("R") else (red > green * 1.3)
                assert min(image.getpixel(center)) > 220  # white tower silhouette


def _ward_gold_pixels(image, x, y):
    # Match the observer marker itself, not similarly colored map terrain.
    return sum(
        sum(abs(channel - expected) for channel, expected in
            zip(image.getpixel((xx, yy)), (223, 182, 93))) < 30
        for xx in range(x - 12, x + 13)
        for yy in range(y - 12, y + 13)
    )


def test_lane_sheets_are_per_player_with_radiant_and_dire_columns():
    payload = _mid_payload({
        "Radiant Player": [_mid_row(1, 4, True, "Radiant Player", "Hero",
                                   obs=[[95, 160, 100]])],
        "Dire Player": [_mid_row(2, 5, False, "Dire Player", "Hero",
                                obs=[[110, 150, 100]])],
    })
    rows = render_player_lane_ward_rows(payload, payload["teams"][0])
    assert [name for name, _png, _description in rows] == [
        "lane-pos-4.png", "lane-pos-5.png"]
    first = Image.open(io.BytesIO(rows[0][1])).convert("RGB")
    second = Image.open(io.BytesIO(rows[1][1])).convert("RGB")
    assert first.size == second.size == (MID_PANEL_SIZE * 2 + 24, 652)
    # Each role's lane pair appears at full width, with no three-lane stack.
    lane_y = 52
    assert _ward_gold_pixels(first, 300, lane_y + 300) > 50
    assert _ward_gold_pixels(second, 300, lane_y + 300) < 10
    dire_x = MID_PANEL_SIZE + 24 + 467
    assert _ward_gold_pixels(second, dire_x, lane_y + 411) > 50
    assert _ward_gold_pixels(first, dire_x, lane_y + 411) < 10


def test_support_lane_pairs_follow_each_sides_lane():
    payload = _mid_payload({
        "Pos 4": [
            _mid_row(1, 4, True, "Pos 4", "Hero", obs=[[95, 160, 100]]),
            _mid_row(2, 4, False, "Pos 4", "Hero", obs=[[160, 95, 100]]),
        ],
        "Pos 5": [
            _mid_row(1, 5, True, "Pos 5", "Hero", obs=[[160, 95, 100]]),
            _mid_row(2, 5, False, "Pos 5", "Hero", obs=[[95, 160, 100]]),
        ],
    })
    rows = render_player_lane_ward_rows(payload, payload["teams"][0])
    for _name, png, description in rows:
        image = Image.open(io.BytesIO(png)).convert("RGB")
        assert image.size == (MID_PANEL_SIZE * 2 + 24, 652)
        for x in (300, MID_PANEL_SIZE + 24 + 300):
            assert _ward_gold_pixels(image, x, 52 + 300) > 50
        assert ("Offlane" if "Pos 4" in description else "Safe lane") in description


def test_lane_sheets_select_mid_and_supports_without_mareth():
    payload = _mid_payload({
        "Carry": [_mid_row(1, 1, True, "Carry", "Hero")],
        "Mid": [_mid_row(1, 2, True, "Mid", "Hero")],
        "Offlane": [_mid_row(1, 3, True, "Offlane", "Hero")],
        "Mareth": [_mid_row(1, 4, True, "Mareth", "Hero")],
        "Support 4": [_mid_row(1, 4, True, "Support 4", "Hero")],
        "Support 5": [_mid_row(1, 5, True, "Support 5", "Hero")],
    })
    rows = render_player_lane_ward_rows(payload, payload["teams"][0])
    assert [name for name, _png, _description in rows] == [
        "lane-pos-2.png", "lane-pos-4.png", "lane-pos-5.png"]
    assert [description.split(":")[0] for _name, _png, description in rows] == [
        "Mid (Pos 2)", "Support 4 (Pos 4)", "Support 5 (Pos 5)"]
