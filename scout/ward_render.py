"""Ward placement map rendering for Team Scout (Pillow, no Discord import).

Mirrors the ward-map placement logic in scout/team_scout_html.py (clustering,
patch selection, world->pct mapping, dot sizing). When Dota is installed,
Discord uses its current minimap texture as the background and projects
wards, towers and rune spots with the map's own dota_minimap_boundary,
tower and rune-spawner origins (scout/dota_map_entities.py), so every
overlay sits exactly where the game draws it. OpenDota's 7.40 image, with
OpenDota's 64..192 ward-cell projection, is the fallback background.
"""

from __future__ import annotations

import io
import math
import os
import struct
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .bbc_source import team_key as _team_key
from .minimap_icons import MINIMAP_ICON_UNIT, RUNE_ICON, draw_rune_icon

MAP_ASSET_PATH = Path(__file__).resolve().parent.parent / "cache" / "assets" / "detailed_740.jpg"
MAP_ASSET_URL = "https://www.opendota.com/assets/images/dota2/map/detailed_740.jpg"
CURRENT_MAP_ASSET_PATH = MAP_ASSET_PATH.parent.parent / "dota_current_minimap.png"
MAP_LANDMARKS_PATH = MAP_ASSET_PATH.parent.parent / "dota_map_landmarks.json"
# World extent of a map image in game units: (min_x, min_y, max_x, max_y).
#
# The installed minimap texture spans -8192..8192 on both axes: on an
# in-game minimap screenshot the six Tier 1 tower icons fit one linear
# projection per axis to within a pixel (identical scale on x and y), and
# that projection puts +-8192 exactly on the HUD frame. The map's own
# dota_minimap_boundary corners, read from maps/dota.vpk by
# scout/dota_map_entities.py, take precedence whenever they can be read.
#
# OpenDota's detailed_740.jpg is a slightly different crop of that terrain.
# Registering the screenshot's terrain onto the image (edge-map cross
# correlation, sub-pixel) and pushing the tower projection through it gives
# these bounds; with them every Tier 1 origin lands on the lane art and on
# the icon the game draws. OpenDota's own 64..192 ward-cell convention
# (-8192..8192) is 1-2% off on this image, which is what put the tower
# markers beside the lanes before.
CURRENT_MAP_WORLD_BOUNDS = (-8192, -8192, 8192, 8192)
OPENDOTA_MAP_WORLD_BOUNDS = (-8237, -8401, 8452, 8298)

WARD_PATCH_NAME = "7.41"
WARD_PATCH_FALLBACK_ID = 60

# Team Scout's web map is 240px; dot sizes there scale up here by 380/240.
WEB_MAP_SIZE = 240
SHEET_MAP_SIZE = 380
DOT_SCALE = SHEET_MAP_SIZE / WEB_MAP_SIZE

BG_COLOR = "#111820"
HEADER_COLOR = "#f2f3f5"
LABEL_NAME_COLOR = "#f2f3f5"
LABEL_META_COLOR = "#b5bac1"
LEGEND_COLOR = "#b5bac1"
OBS_FILL = "#dfb65d"
OBS_BORDER = "#1a1408"
SEN_FILL = "#45c7cf"
SEN_BORDER = "#041416"
EMPTY_OVERLAY = (0, 0, 0, 140)
DIM_OVERLAY_ALPHA = 82  # ~32% of 255

PAD = 20
HEADER_H = 34
LABEL_H = 26
GAP = 16
LEGEND_H = 40

SUPERSAMPLE = 2

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_REGULAR = FONT_DIR / "segoeui.ttf"
FONT_BOLD = FONT_DIR / "segoeuib.ttf"


def _font(path, size):
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size=size)


def ward_patch_id(payload):
    """Find the patch id whose name is "7.41"; fall back to id 60 (the same
    fallback Team Scout's web report uses) if the patch list doesn't have it."""
    for patch in payload.get("patches") or []:
        if str(patch.get("name")) == WARD_PATCH_NAME:
            return patch.get("id")
    return WARD_PATCH_FALLBACK_ID


def cluster_wards(points, bin=5):
    """Bin nearby ward points together: group by rounding to the nearest
    `bin` units, average x/y within each bucket, count occupants. Returns a
    list of {"x", "y", "n"} sorted ascending by n (so dense clusters draw
    last / on top, matching the web report)."""
    buckets = {}
    for pt in points or []:
        try:
            x = float(pt[0])
            y = float(pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        key = (round(x / bin) * bin, round(y / bin) * bin)
        entry = buckets.setdefault(key, {"sx": 0.0, "sy": 0.0, "n": 0})
        entry["sx"] += x
        entry["sy"] += y
        entry["n"] += 1
    out = [{"x": e["sx"] / e["n"], "y": e["sy"] / e["n"], "n": e["n"]} for e in buckets.values()]
    out.sort(key=lambda row: row["n"])
    return out


def bounds_rect(world_bounds):
    """Normalise (low, high) or (min_x, min_y, max_x, max_y) bounds."""
    if len(world_bounds) == 2:
        low, high = world_bounds
        return float(low), float(low), float(high), float(high)
    min_x, min_y, max_x, max_y = world_bounds
    return float(min_x), float(min_y), float(max_x), float(max_y)


def grid_to_world(x, y):
    """OpenDota ward grid (cell 128 = world origin, 128 units per cell) to
    game world units. OpenDota's parser reports cell + offset / 128, so the
    grid value is the ward's exact position, not a whole cell."""
    return (x - 128) * 128, (y - 128) * 128


def world_to_px(x, y, size, world_bounds=OPENDOTA_MAP_WORLD_BOUNDS):
    """Project OpenDota ward-grid coordinates onto the selected map image."""
    min_x, min_y, max_x, max_y = bounds_rect(world_bounds)
    world_x, world_y = grid_to_world(x, y)
    left = (world_x - min_x) / (max_x - min_x)
    top = (max_y - world_y) / (max_y - min_y)
    return left * size, top * size


_LANDMARKS = {"loaded": False, "value": None}
_WARNED = set()


def _warn_once(key, message):
    if key not in _WARNED:
        _WARNED.add(key)
        print(message, file=sys.stderr)


def map_landmarks():
    """Landmarks read from the installed Dota map (see dota_map_entities):
    {"bounds": [min_x, min_y, max_x, max_y], "towers": [...], "runes": [...]}
    or None when no install can be read. Cached for the process."""
    if not _LANDMARKS["loaded"]:
        _LANDMARKS["loaded"] = True
        try:
            from .dota_map_asset import _steam_game_dirs
            from .dota_map_entities import ensure_map_landmarks

            _LANDMARKS["value"] = ensure_map_landmarks(MAP_LANDMARKS_PATH, _steam_game_dirs())
        except (OSError, ValueError, struct.error) as exc:
            _warn_once("landmarks", f"Ward maps: could not read the Dota map's entities ({exc}); "
                                    "towers, rune spots and the minimap extent use built-in values.")
            _LANDMARKS["value"] = None
    return _LANDMARKS["value"]


def map_info():
    """Describe the background and landmarks the ward maps will use, for
    the snapshot's meta.json and for diagnostics."""
    path = _map_asset_path()
    current = Path(path) == CURRENT_MAP_ASSET_PATH
    landmarks = map_landmarks() if current else None
    return {
        "background": "dota" if current else "opendota",
        "path": str(path),
        "bounds": list(bounds_rect(_map_world_bounds(path))),
        "landmarks": "dota" if landmarks and landmarks.get("bounds") else "builtin",
        "towers": len((landmarks or {}).get("towers") or []),
        "runes": len((landmarks or {}).get("runes") or []),
        "trees": len((landmarks or {}).get("trees") or []),
    }


def _map_world_bounds(path):
    if Path(path) == CURRENT_MAP_ASSET_PATH:
        bounds = (map_landmarks() or {}).get("bounds")
        if bounds and len(bounds) == 4:
            return tuple(float(v) for v in bounds)
        return CURRENT_MAP_WORLD_BOUNDS
    return OPENDOTA_MAP_WORLD_BOUNDS


def _dot_px(kind, n):
    base = 11 if kind == "obs" else 8
    cap = 30 if kind == "obs" else 24
    px = max(base, min(cap, round(base * (n ** 0.5))))
    return px * DOT_SCALE


def _player_position_rows(player, key):
    matches = (player.get("official") or {}).get("matches") or []
    return [row for row in matches if row.get("team_key") == key]


def _position_mode_and_games(rows):
    counts = {}
    for row in rows:
        pos = row.get("position")
        if pos:
            counts[pos] = counts.get(pos, 0) + 1
    if not counts:
        return None, 0
    pos = max(counts.items(), key=lambda kv: kv[1])[0]
    return pos, counts[pos]


def select_map_players(payload, team, positions=(1, 4, 5), excluded_names=()):
    """Pick, for each requested position, the roster player whose inferred
    position mode matches it (ties -> whichever has played more games at
    that position). A position nobody plays is skipped. Returns a list of
    (position, player) tuples, in the order `positions` was given."""
    players_by_id = {p.get("id"): p for p in payload.get("players") or []}
    key = team.get("key")
    roster_ids = team.get("roster") or []

    excluded = {name.casefold() for name in excluded_names}
    candidates = {}  # position -> (games_at_pos, player)
    for pid in roster_ids:
        player = players_by_id.get(pid)
        if player is None or (player.get("name") or "").casefold() in excluded:
            continue
        rows = _player_position_rows(player, key)
        pos, games = _position_mode_and_games(rows)
        if pos is None or pos not in positions:
            continue
        best = candidates.get(pos)
        if best is None or games > best[0]:
            candidates[pos] = (games, player)

    out = []
    for pos in positions:
        found = candidates.get(pos)
        if found is not None:
            out.append((pos, found[1]))
    return out


def player_side_wards(player, team_key, patch_id):
    """Official rows for this team on the ward patch, split by side. Falls
    back to pubWards (marked pubs=True) when both official sides are empty."""

    def _empty():
        return {"obs": [], "sen": [], "games": 0}

    official = {"radiant": _empty(), "dire": _empty()}
    for row in (player.get("official") or {}).get("matches") or []:
        if row.get("team_key") != team_key:
            continue
        if row.get("patch") != patch_id:
            continue
        is_radiant = row.get("is_radiant")
        if is_radiant is True:
            side = official["radiant"]
        elif is_radiant is False:
            side = official["dire"]
        else:
            continue
        side["obs"].extend(row.get("obs_map") or [])
        side["sen"].extend(row.get("sen_map") or [])
        side["games"] += 1

    has_official = bool(official["radiant"]["obs"] or official["radiant"]["sen"]
                         or official["dire"]["obs"] or official["dire"]["sen"])
    if has_official:
        official["pubs"] = False
        return official

    pubs = {"radiant": _empty(), "dire": _empty()}
    for row in player.get("pubWards") or []:
        if row.get("patch") != patch_id:
            continue
        is_radiant = row.get("is_radiant")
        if is_radiant is True:
            side = pubs["radiant"]
        elif is_radiant is False:
            side = pubs["dire"]
        else:
            continue
        side["obs"].extend(row.get("obs_map") or [])
        side["sen"].extend(row.get("sen_map") or [])
        side["games"] += 1

    pubs["pubs"] = True
    return pubs


def _map_asset_path():
    from .dota_map_asset import ensure_current_minimap

    try:
        current = ensure_current_minimap(CURRENT_MAP_ASSET_PATH)
        if current is not None:
            return current
        _warn_once("minimap", "Ward maps: no Dota install found; using OpenDota's 7.40 map image.")
    except (OSError, ValueError, struct.error) as exc:
        _warn_once("minimap", f"Ward maps: Dota's minimap could not be read ({exc}); "
                              "using OpenDota's 7.40 map image.")
    if not MAP_ASSET_PATH.exists():
        os.makedirs(MAP_ASSET_PATH.parent, exist_ok=True)
        import urllib.request
        urllib.request.urlretrieve(MAP_ASSET_URL, MAP_ASSET_PATH)
    return MAP_ASSET_PATH


def _load_map_image(size, map_path=None):
    try:
        img = Image.open(map_path or _map_asset_path()).convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        return Image.new("RGB", (size, size), "#1f2b22")


def _draw_ward_map(obs_points, sen_points, size, dim=False, pubs=False):
    """Render one map tile (RGBA) at `size`x`size`, supersampled internally."""
    big = size * SUPERSAMPLE
    map_path = _map_asset_path()
    bounds = _map_world_bounds(map_path)
    base = _load_map_image(big, map_path).convert("RGBA")

    overlay = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    sen_clusters = cluster_wards(sen_points)
    obs_clusters = cluster_wards(obs_points)

    def draw_cluster(kind, cluster, fill, border):
        x, y = world_to_px(cluster["x"], cluster["y"], size, bounds)
        d = _dot_px(kind, cluster["n"]) * SUPERSAMPLE
        cx, cy = x * SUPERSAMPLE, y * SUPERSAMPLE
        bbox = (cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2)
        draw.ellipse(bbox, fill=fill, outline=border, width=max(1, SUPERSAMPLE))

    for c in sen_clusters:
        draw_cluster("sen", c, SEN_FILL, SEN_BORDER)
    for c in obs_clusters:
        draw_cluster("obs", c, OBS_FILL, OBS_BORDER)

    combined = Image.alpha_composite(base, overlay)
    combined = combined.resize((size, size), Image.LANCZOS)

    if not obs_clusters and not sen_clusters:
        dark = Image.new("RGBA", (size, size), EMPTY_OVERLAY)
        combined = Image.alpha_composite(combined, dark)
        d = ImageDraw.Draw(combined)
        font = _font(FONT_REGULAR, 16)
        text = "No ward maps"
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((size - tw) / 2, (size - th) / 2), text, fill="#e5e5e5", font=font)

    # A side with 0 games is dimmed regardless of whether it also shows the
    # "No ward maps" placeholder (which covers 0-wards-but-some-games too) -
    # these are two independent signals, matching the web report's separate
    # wardSlot "off" class and wardMap empty-state.
    if dim:
        dim_overlay = Image.new("RGBA", (size, size), (0, 0, 0, DIM_OVERLAY_ALPHA))
        combined = Image.alpha_composite(combined, dim_overlay)

    return combined


def _draw_ward_heatmap(obs_points, sen_points, size, dim=False):
    """Render additive placement density; brighter areas contain more wards."""
    map_path = _map_asset_path()
    bounds = _map_world_bounds(map_path)
    base = ImageEnhance.Brightness(_load_map_image(size, map_path)).enhance(0.58).convert("RGBA")

    def density(points):
        mask = Image.new("L", (size, size))
        diameter = 56
        stamp = Image.new("L", (diameter, diameter))
        ImageDraw.Draw(stamp).ellipse((23, 23, 33, 33), fill=255)
        stamp = stamp.filter(ImageFilter.GaussianBlur(10))
        for point in points or []:
            try:
                x, y = world_to_px(float(point[0]), float(point[1]), size, bounds)
            except (IndexError, TypeError, ValueError):
                continue
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < size and 0 <= y < size):
                continue
            left, top = round(x) - diameter // 2, round(y) - diameter // 2
            box = (max(0, left), max(0, top), min(size, left + diameter), min(size, top + diameter))
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            source = stamp.crop((box[0] - left, box[1] - top, box[2] - left, box[3] - top))
            mask.paste(ImageChops.add(mask.crop(box), source), box)
        return mask.point(lambda value: min(185, value * 3))

    for points, color in ((obs_points, (255, 190, 65)), (sen_points, (53, 212, 229))):
        overlay = Image.new("RGBA", (size, size), (*color, 0))
        overlay.putalpha(density(points))
        base = Image.alpha_composite(base, overlay)

    if not obs_points and not sen_points:
        base = Image.alpha_composite(base, Image.new("RGBA", (size, size), EMPTY_OVERLAY))
        draw = ImageDraw.Draw(base)
        label = "No ward maps"
        font = _font(FONT_REGULAR, 16)
        box = draw.textbbox((0, 0), label, font=font)
        draw.text(((size - (box[2] - box[0])) / 2, (size - (box[3] - box[1])) / 2),
                  label, fill="#e5e5e5", font=font)
    if dim:
        base = Image.alpha_composite(base, Image.new("RGBA", (size, size),
                                                     (0, 0, 0, DIM_OVERLAY_ALPHA)))
    return base


def render_ward_sheet(payload, team, positions=(1, 4, 5)):
    """Render the Radiant|Dire x Pos-1/4/5 ward sheet for `team` and return
    PNG bytes. `team` is a team row dict (payload["teams"][i])."""
    key = team.get("key")
    patch_id = ward_patch_id(payload)
    rows = select_map_players(payload, team, positions=positions)

    n_rows = max(1, len(rows))
    width = PAD * 2 + SHEET_MAP_SIZE * 2 + GAP
    top = PAD + HEADER_H + GAP
    row_h = LABEL_H + SHEET_MAP_SIZE + GAP
    height = top + n_rows * row_h + LEGEND_H + PAD

    canvas = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    font_header = _font(FONT_BOLD, 20)
    font_name = _font(FONT_BOLD, 15)
    font_meta = _font(FONT_REGULAR, 13)
    font_legend = _font(FONT_REGULAR, 13)

    col_x = [PAD, PAD + SHEET_MAP_SIZE + GAP]
    draw.text((col_x[0], PAD), "Radiant", fill=HEADER_COLOR, font=font_header)
    draw.text((col_x[1], PAD), "Dire", fill=HEADER_COLOR, font=font_header)

    if not rows:
        msg = "No Pos 1, 4 or 5 players found on this roster."
        draw.text((PAD, top), msg, fill=LABEL_META_COLOR, font=font_meta)

    y = top
    for pos, player in rows:
        wards = player_side_wards(player, key, patch_id)
        name = player.get("name") or "Unknown"
        pubs_suffix = " (pubs)" if wards.get("pubs") else ""

        for col, side in enumerate(("radiant", "dire")):
            side_data = wards[side]
            obs_n = len(side_data["obs"])
            sen_n = len(side_data["sen"])
            games = side_data["games"]
            x = col_x[col]

            left_label = f"{name} \u00b7 Pos {pos}"
            right_label = (f"none placed{pubs_suffix}" if not games else
                            f"{games}g \u00b7 {obs_n} obs \u00b7 {sen_n} sen{pubs_suffix}")
            draw.text((x, y), left_label, fill=LABEL_NAME_COLOR, font=font_name)
            rbbox = draw.textbbox((0, 0), right_label, font=font_meta)
            rw = rbbox[2] - rbbox[0]
            draw.text((x + SHEET_MAP_SIZE - rw, y + 2), right_label, fill=LABEL_META_COLOR, font=font_meta)

            dim = not games
            tile = _draw_ward_map(side_data["obs"], side_data["sen"], SHEET_MAP_SIZE,
                                    dim=dim, pubs=wards.get("pubs", False))
            canvas.paste(tile.convert("RGB"), (x, y + LABEL_H))

        y += row_h

    legend_y = y + (LEGEND_H - 16) // 2
    lx = PAD
    draw.ellipse((lx, legend_y, lx + 14, legend_y + 14), fill=OBS_FILL, outline=OBS_BORDER)
    draw.text((lx + 20, legend_y - 2), "Observer", fill=LEGEND_COLOR, font=font_legend)
    lx += 110
    draw.ellipse((lx, legend_y, lx + 14, legend_y + 14), fill=SEN_FILL, outline=SEN_BORDER)
    draw.text((lx + 20, legend_y - 2), "Sentry", fill=LEGEND_COLOR, font=font_legend)
    lx += 90
    draw.text((lx, legend_y - 2), "Larger = placed there more often", fill=LEGEND_COLOR, font=font_legend)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def render_player_ward_rows(payload, team, heatmap=False):
    """Return one two-map PNG per roster player, in roster order."""
    players = {player.get("id"): player for player in payload.get("players") or []}
    key = team.get("key")
    patch_id = ward_patch_id(payload)
    rows = []
    for index, player_id in enumerate(team.get("roster") or [], start=1):
        player = players.get(player_id)
        if player is None:
            continue
        name = player.get("name") or "Unknown"
        wards = player_side_wards(player, key, patch_id)
        width = SHEET_MAP_SIZE * 2 + GAP
        image = Image.new("RGB", (width, SHEET_MAP_SIZE), BG_COLOR)
        for side_index, side in enumerate(("radiant", "dire")):
            side_data = wards[side]
            renderer = _draw_ward_heatmap if heatmap else _draw_ward_map
            tile = renderer(side_data["obs"], side_data["sen"],
                            SHEET_MAP_SIZE, dim=not side_data["games"])
            short_name = name
            suffix = f" · {side.title()}" + (" · pubs" if wards.get("pubs") else "")
            label = short_name + suffix
            draw = ImageDraw.Draw(tile)
            font = _font(FONT_BOLD, 18)
            while short_name and draw.textlength(label, font=font) > SHEET_MAP_SIZE - 40:
                short_name = short_name[:-1]
                label = short_name + "…" + suffix
            label_width = draw.textlength(label, font=font)
            draw.rounded_rectangle((10, 10, min(SHEET_MAP_SIZE - 10, label_width + 30), 44),
                                   radius=6, fill="#111820")
            draw.text((20, 15), label, fill=HEADER_COLOR, font=font)
            image.paste(tile.convert("RGB"), (side_index * (SHEET_MAP_SIZE + GAP), 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        prefix = "ward-heatmap-player" if heatmap else "ward-player"
        rows.append((f"{prefix}-{index}.png", buffer.getvalue(),
                     f"{name}: Radiant and Dire ward {'heatmaps' if heatmap else 'maps'}"))
    return rows


# --------------------------------------------------------------------------
# Mid ward (rune to rune, before 1:00)
# --------------------------------------------------------------------------
#
# Ported from a scratchpad prototype that read placement times off BBC's raw
# OpenDota match cache directly; this version reads them off Team Scout's own
# payload instead, via the [x, y, t] points bbc_source._ward_points() now
# emits (t = the log entry's integer `time` in seconds on the game clock,
# negative = pre-horn; missing when the source entry had no time).

# The window is a grid-unit square centred between the two runes flanking mid
# lane. The rune markers come from the installed map's power-rune spawners
# (water runes spawn on those spots). MID_RUNE_SPOTS is the fallback used
# when the map cannot be read: the two river rune icons measured on an
# in-game minimap screenshot (the centroid of each icon's whole disc) and
# pushed through the same tower-calibrated projection as the map bounds
# above (about 25 world units of precision).
MID_RUNE_SPOTS = [(115.0, 136.4), (137.0, 118.3)]
# Bounty rune spawners, in game world units, measured the same way from the
# two jungle rune icons on that screenshot. The map's own
# dota_item_rune_spawner_bounty origins replace these when readable.
BOUNTY_RUNE_WORLD = ((-1029.0, 4401.0), (569.0, -4693.0))
MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF = 126.2, 127.5, 17
MID_WARD_CUTOFF = 60
MID_CLUSTER_RADIUS = 2.0
SIDE_LANE_CUTOFF = 210  # 3:30; mid keeps its 1:00 cutoff.
# World-grid crops around the two side-lane meeting areas. The same crop is
# shown for Radiant and Dire so their ward spots can be compared directly.
SIDE_LANE_WINDOWS = {
    "top": (95, 160, 27),
    "bottom": (160, 95, 27),
}
# Fallback Tier 1 origins (game world units) for when the installed map's
# entity lumps cannot be read; lane_towers() prefers the live npc_dota_tower
# origins. These are reference markers, not match-specific alive/destroyed
# state.
LANE_TOWER_WORLD = {
    "mid": ((-1543.998535, -1407.998413, "R T1"),
            (523.999756, 651.999817, "D T1")),
    "top": ((-6336.0, 1856.002197, "R T1"),
            (-5274.558105, 6036.044434, "D T1")),
    "bottom": ((4859.866211, -6379.263184, "R T1"),
               (6269.338867, -2240.000244, "D T1")),
}

MID_SRC_SIZE = 900  # default for calculations using OpenDota's 7.40 image
MID_PANEL_SIZE = 600
MID_SUPERSAMPLE = 2


def in_mid_window(x, y):
    """True when (x, y) falls inside the rune-to-rune mid window."""
    return abs(x - MID_WINDOW_CX) <= MID_WINDOW_HALF and abs(y - MID_WINDOW_CY) <= MID_WINDOW_HALF


def _mid_to_src(x, y, source_size=(MID_SRC_SIZE, MID_SRC_SIZE),
                world_bounds=OPENDOTA_MAP_WORLD_BOUNDS):
    width, height = source_size
    return (world_to_px(x, y, width, world_bounds)[0],
            world_to_px(x, y, height, world_bounds)[1])


def _game_world_to_grid(x, y):
    """Project Source 2 origins onto OpenDota's 64..192 ward grid.

    OpenDota's replay parser reports cell + local offset / 128; world origin
    is cell 128. Keep this conversion shared by every tower landmark.
    """
    return 128 + x / 128, 128 + y / 128


def lane_towers(lane):
    """(world_x, world_y, label) for every tower the installed map has on
    `lane` (all tiers; the crop decides which are visible), else the
    built-in Tier 1 fallback."""
    landmarks = map_landmarks() or {}
    towers = [t for t in landmarks.get("towers") or [] if t.get("lane") == lane]
    if towers:
        return tuple((float(t["x"]), float(t["y"]),
                      f"{'R' if t.get('side') == 'radiant' else 'D'} T{t.get('tier')}")
                     for t in towers)
    return LANE_TOWER_WORLD[lane]


def mid_rune_spots():
    """Grid-unit (x, y) of the two river rune spots flanking mid: the map's
    water/power rune spawners when readable, else MID_RUNE_SPOTS."""
    landmarks = map_landmarks() or {}
    runes = landmarks.get("runes") or []
    for kind in ("water", "powerup"):
        spots = [r for r in runes if r.get("kind") == kind]
        if len(spots) >= 2:
            spots.sort(key=lambda r: math.hypot(float(r["x"]), float(r["y"])))
            return [_game_world_to_grid(float(r["x"]), float(r["y"])) for r in spots[:2]]
    return list(MID_RUNE_SPOTS)


def bounty_rune_spots():
    """World (x, y) of every bounty rune spawner: the installed map's
    dota_item_rune_spawner_bounty origins when readable, else the two
    measured BOUNTY_RUNE_WORLD spots."""
    runes = (map_landmarks() or {}).get("runes") or []
    spots = []
    for rune in runes:
        if rune.get("kind") != "bounty":
            continue
        try:
            spots.append((float(rune["x"]), float(rune["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return spots or list(BOUNTY_RUNE_WORLD)


def _lane_crop_box(cx, cy, half, source_size=(MID_SRC_SIZE, MID_SRC_SIZE),
                   world_bounds=OPENDOTA_MAP_WORLD_BOUNDS):
    left, top = _mid_to_src(cx - half, cy + half, source_size, world_bounds)
    right, bottom = _mid_to_src(cx + half, cy - half, source_size, world_bounds)
    return round(left), round(top), round(right), round(bottom)


def _zoom_to_panel(x, y, cx, cy, half, source_size=(MID_SRC_SIZE, MID_SRC_SIZE),
                   world_bounds=OPENDOTA_MAP_WORLD_BOUNDS):
    """Place an overlay using the same rounded source crop as the image."""
    left, top, right, bottom = _lane_crop_box(cx, cy, half, source_size, world_bounds)
    source_x, source_y = _mid_to_src(x, y, source_size, world_bounds)
    scale = MID_PANEL_SIZE * MID_SUPERSAMPLE
    return ((source_x - left) / (right - left) * scale,
            (source_y - top) / (bottom - top) * scale)


def _draw_water_rune(draw, cx, cy, size):
    """Simple water rune: a cyan diamond with one light facet and a dark
    outline. Ported as-is from the prototype's water_rune.py."""
    navy = "#0a1f3a"
    hw, hh = size * 0.34, size * 0.5
    width = max(1, round(size * 0.05))
    top, right, bottom, left = (cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)
    draw.polygon([top, right, bottom, left], fill="#3cc6e6")
    draw.polygon([top, (cx, cy + hh), left], fill="#8ff3ff")
    draw.polygon([top, right, bottom, left], outline=navy, width=width)


# Tower markers copy the in-game minimap's tower cubes. Geometry is in
# "icon pixels" measured on an in-game minimap screenshot, relative to the
# tower origin's projection (+x right, +y down); one icon pixel is
# TOWER_ICON_UNIT world units there, so the cubes keep the game's size
# against the terrain at every crop scale.
TOWER_ICON_UNIT = MINIMAP_ICON_UNIT
# Furthest reach of the rune icon from its centre, in icon pixels.
RUNE_ICON_RADIUS = max(math.hypot(x, y) for _layer, _color, shapes in RUNE_ICON
                       for _hole, points in shapes for x, y in points)
# Side lanes: a square cube seen from the front (top face over a front face,
# a one-pixel shaded right edge, black outline heavier on the top/left).
TOWER_SQUARE_FACE = (-4.74, -4.16, 5.26, 5.84)  # left, top, right, bottom
TOWER_SQUARE_TOP_BOTTOM = 1.84                   # top face ends, front face starts
TOWER_SQUARE_SIDE_LEFT = 4.26                    # shaded right strip starts
TOWER_SQUARE_OUTLINE = (2.0, 2.0, 1.0, 1.0)      # left, top, right, bottom
# Mid: the same cube turned 45 degrees, a hexagon of top, left and right faces.
TOWER_DIAMOND = {
    "top": (-0.12, -7.17), "right": (6.38, -1.6), "right_low": (6.38, 3.15),
    "bottom": (-0.12, 7.83), "left_low": (-6.62, 3.15), "left": (-6.62, -1.5),
    "centre": (-0.12, 3.07),
}
TOWER_DIAMOND_OUTLINE = 1.2
TOWER_COLORS = {
    "R": {"top": (128, 242, 0), "front": (104, 198, 0), "side_top": (84, 163, 0),
          "side_front": (67, 132, 0), "left": (65, 129, 0), "right": (37, 79, 0)},
    "D": {"top": (255, 0, 0), "front": (209, 0, 0), "side_top": (229, 0, 0),
          "side_front": (189, 0, 0), "left": (136, 0, 0), "right": (82, 0, 0)},
}

# Trees from the map's ent_dota_tree entities, drawn over the installed
# minimap (OpenDota's fallback image already has its trees painted in).
TREE_DIAMETER = 150.0  # world units
TREE_COLORS = {
    "radiant": {"outline": (34, 52, 10), "body": (76, 112, 18), "light": (118, 156, 40)},
    "dire": {"outline": (18, 28, 38), "body": (56, 84, 106), "light": (92, 122, 144)},
}


def _draw_tower_cube(draw, cx, cy, side, diamond, kx, ky):
    """Draw the game's tower cube centred on projection (cx, cy).

    `kx`/`ky` are panel pixels per world unit; `diamond` selects the rotated
    mid-lane icon. `side` is "R" or "D"."""
    colors = TOWER_COLORS["R" if side == "R" else "D"]
    ux, uy = TOWER_ICON_UNIT * kx, TOWER_ICON_UNIT * ky

    def at(x, y):
        return cx + x * ux, cy + y * uy

    if diamond:
        g = TOWER_DIAMOND
        hexagon = [at(*g[k]) for k in ("top", "right", "right_low", "bottom", "left_low", "left")]
        # Outline: the hexagon grown outward from its centre by the outline width.
        mid_x = sum(p[0] for p in hexagon) / 6
        mid_y = sum(p[1] for p in hexagon) / 6
        grow = TOWER_DIAMOND_OUTLINE * ux
        outline = []
        for x, y in hexagon:
            dx, dy = x - mid_x, y - mid_y
            length = math.hypot(dx, dy) or 1.0
            outline.append((x + dx / length * grow, y + dy / length * grow))
        draw.polygon(outline, fill=(0, 0, 0))
        draw.polygon([at(*g["left"]), at(*g["centre"]), at(*g["bottom"]), at(*g["left_low"])],
                     fill=colors["left"])
        draw.polygon([at(*g["centre"]), at(*g["right"]), at(*g["right_low"]), at(*g["bottom"])],
                     fill=colors["right"])
        draw.polygon([at(*g["top"]), at(*g["right"]), at(*g["centre"]), at(*g["left"])],
                     fill=colors["top"])
        return

    left, top, right, bottom = TOWER_SQUARE_FACE
    ol, ot, orr, ob = TOWER_SQUARE_OUTLINE
    split, strip = TOWER_SQUARE_TOP_BOTTOM, TOWER_SQUARE_SIDE_LEFT
    draw.rectangle((*at(left - ol, top - ot), *at(right + orr, bottom + ob)), fill=(0, 0, 0))
    draw.rectangle((*at(left, top), *at(strip, split)), fill=colors["top"])
    draw.rectangle((*at(left, split), *at(strip, bottom)), fill=colors["front"])
    draw.rectangle((*at(strip, top), *at(right, split)), fill=colors["side_top"])
    draw.rectangle((*at(strip, split), *at(right, bottom)), fill=colors["side_front"])


def _draw_tree(draw, cx, cy, world_x, world_y, kx, ky):
    """A small pine in the minimap art's style, green on the Radiant half and
    blue-grey on the Dire half (split along the river diagonal)."""
    colors = TREE_COLORS["dire" if world_x + world_y > 0 else "radiant"]
    w = TREE_DIAMETER * kx / 2
    h = TREE_DIAMETER * ky / 2
    body = [(cx, cy - h * 1.15), (cx + w * 0.55, cy - h * 0.25), (cx + w * 0.35, cy - h * 0.25),
            (cx + w * 0.95, cy + h * 0.75), (cx - w * 0.95, cy + h * 0.75),
            (cx - w * 0.35, cy - h * 0.25), (cx - w * 0.55, cy - h * 0.25)]
    pad = max(1.0, w * 0.18)
    draw.polygon([(x + (pad if x > cx else -pad if x < cx else 0), y + (pad if y > cy else -pad))
                  for x, y in body], fill=colors["outline"])
    draw.polygon(body, fill=colors["body"])
    draw.polygon([(cx, cy - h * 1.15), (cx - w * 0.55, cy - h * 0.25), (cx - w * 0.35, cy - h * 0.25),
                  (cx - w * 0.95, cy + h * 0.75), (cx - w * 0.2, cy + h * 0.75)], fill=colors["light"])
    draw.rectangle((cx - w * 0.14, cy + h * 0.75, cx + w * 0.14, cy + h * 1.05), fill=colors["outline"])


def map_trees():
    """World (x, y) of every ent_dota_tree in the installed map, or []."""
    trees = (map_landmarks() or {}).get("trees") or []
    out = []
    for point in trees:
        try:
            out.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def cluster_mid_spots(wards, radius=MID_CLUSTER_RADIUS):
    """Greedy, time-ordered clustering: walk `wards` oldest-first and join a
    ward to the first existing spot of the same kind within `radius` grid
    units of that spot's running mean position; otherwise start a new spot.
    Observer spots are labelled A, B, C... by descending use count; sentry
    spots are labelled 1, 2, 3... the same way."""
    out = []
    for w in sorted(wards, key=lambda w: w["t"]):
        for spot in out:
            if spot["kind"] == w["kind"] and math.hypot(spot["x"] - w["x"], spot["y"] - w["y"]) <= radius:
                spot["items"].append(w)
                n = len(spot["items"])
                spot["x"] = sum(i["x"] for i in spot["items"]) / n
                spot["y"] = sum(i["y"] for i in spot["items"]) / n
                break
        else:
            out.append({"kind": w["kind"], "x": w["x"], "y": w["y"], "items": [w]})
    out.sort(key=lambda s: (s["kind"] != "obs", -len(s["items"])))
    obs_spots = [s for s in out if s["kind"] == "obs"]
    sen_spots = [s for s in out if s["kind"] == "sen"]
    for i, s in enumerate(obs_spots):
        s["label"] = chr(ord("A") + i)
    for i, s in enumerate(sen_spots):
        s["label"] = str(i + 1)
    return out


def mid_ward_events(payload, team, cutoff=MID_WARD_CUTOFF):
    """Group `team`'s ward-patch official rows by match and pick the mid-ward
    events per game: the team's FIRST observer inside the rune-to-rune window
    with time < `cutoff` (placed by anyone on the team), plus EVERY sentry
    inside the window with time < `cutoff` (placed by anyone). A row's
    obs_map/sen_map points without a recorded time are skipped (there's no
    way to judge the cutoff for them).

    Returns (games, wards, mid_names): `games` and `wards` are each
    {"radiant": ..., "dire": ...} (games holds match-id sets, wards holds
    event dicts); `mid_names` is the set of player names who played
    position 2 for this team in the matches considered.
    """
    key = team.get("key")
    patch_id = ward_patch_id(payload)
    rows = [row for player in payload.get("players") or []
            for row in (player.get("official") or {}).get("matches") or []
            if row.get("team_key") == key and row.get("patch") == patch_id]

    by_match = {}
    for row in rows:
        by_match.setdefault(row.get("match_id"), []).append(row)

    games = {"radiant": set(), "dire": set()}
    wards = {"radiant": [], "dire": []}
    mid_names = set()

    for match_id, mrows in by_match.items():
        side = "radiant" if mrows[0].get("is_radiant") else "dire"
        games[side].add(match_id)
        mid_row = next((r for r in mrows if r.get("position") == 2), None)
        if mid_row and mid_row.get("player_name"):
            mid_names.add(mid_row["player_name"])

        events = []
        for row in mrows:
            is_mid = row is mid_row
            for kind, log in (("obs", row.get("obs_map") or []), ("sen", row.get("sen_map") or [])):
                for pt in log:
                    if len(pt) < 3:
                        continue
                    x, y, t = pt[0], pt[1], pt[2]
                    if t < cutoff and in_mid_window(x, y):
                        events.append({
                            "kind": kind, "x": float(x), "y": float(y), "t": int(t),
                            "match": match_id, "is_mid": is_mid,
                            "mid_hero": (mid_row or {}).get("hero"),
                        })
        obs_events = sorted((e for e in events if e["kind"] == "obs"), key=lambda e: e["t"])
        wards[side] += obs_events[:1] + [e for e in events if e["kind"] == "sen"]

    return games, wards, mid_names


def side_lane_ward_events(payload, team, lane, cutoff=SIDE_LANE_CUTOFF):
    """First observer and every sentry per game in a side-lane crop before 3:30.

    The crop is shared by both sides. Points without placement times and
    points inside the mid window are excluded.
    """
    if lane not in SIDE_LANE_WINDOWS:
        raise ValueError(f"Unknown side lane: {lane}")
    cx, cy, half = SIDE_LANE_WINDOWS[lane]
    key = team.get("key")
    patch_id = ward_patch_id(payload)
    by_match = {}
    for player in payload.get("players") or []:
        for row in (player.get("official") or {}).get("matches") or []:
            if row.get("team_key") == key and row.get("patch") == patch_id:
                by_match.setdefault(row.get("match_id"), []).append(row)

    games = {"radiant": set(), "dire": set()}
    wards = {"radiant": [], "dire": []}
    for match_id, rows in by_match.items():
        side = "radiant" if rows[0].get("is_radiant") else "dire"
        games[side].add(match_id)
        events = []
        for row in rows:
            for kind, log in (("obs", row.get("obs_map") or []),
                              ("sen", row.get("sen_map") or [])):
                for point in log:
                    if len(point) < 3:
                        continue
                    try:
                        x, y, t = float(point[0]), float(point[1]), int(point[2])
                    except (TypeError, ValueError):
                        continue
                    if (t < cutoff and abs(x - cx) <= half and abs(y - cy) <= half
                            and not in_mid_window(x, y)):
                        events.append({"kind": kind, "x": x, "y": y, "t": t,
                                       "match": match_id})
        observers = sorted((event for event in events if event["kind"] == "obs"),
                           key=lambda event: event["t"])
        wards[side].extend(observers[:1])
        wards[side].extend(event for event in events if event["kind"] == "sen")
    return games, wards


def _load_mid_map_base():
    """Use the current Dota map when installed; keep its native crop scale."""
    map_path = _map_asset_path()
    base = Image.open(map_path).convert("RGB")
    return (ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.75)).enhance(0.85),
            _map_world_bounds(map_path))


def _render_zoomed_lane(games, wards, cx, cy, half, label, cutoff, markers=(), towers=(),
                        diamond_towers=False, trees=None, bounty_runes=None):
    """Draw matching Radiant/Dire crops with the mid map's spot styling.

    `trees` are world (x, y) tree origins to draw under everything else;
    None draws the installed map's trees when the background is the
    installed minimap (OpenDota's fallback image has its own trees).
    `bounty_runes` are world (x, y) bounty spawners drawn as the game's rune
    icon; None uses bounty_rune_spots()."""
    base, bounds = _load_mid_map_base()
    box = _lane_crop_box(cx, cy, half, base.size, bounds)
    scale = MID_PANEL_SIZE * MID_SUPERSAMPLE
    crop = base.crop(box).resize((scale, scale), Image.LANCZOS)
    # Panel pixels per world unit, from the same rounded crop as the image.
    min_x, min_y, max_x, max_y = bounds_rect(bounds)
    kx = scale / (box[2] - box[0]) * base.size[0] / (max_x - min_x)
    ky = scale / (box[3] - box[1]) * base.size[1] / (max_y - min_y)
    if trees is None:
        trees = map_trees() if Path(_map_asset_path()) == CURRENT_MAP_ASSET_PATH else ()
    margin = TREE_DIAMETER / 128
    visible_trees = []
    for world_x, world_y in trees:
        gx, gy = _game_world_to_grid(world_x, world_y)
        if abs(gx - cx) <= half + margin and abs(gy - cy) <= half + margin:
            visible_trees.append((world_x, world_y, *_zoom_to_panel(gx, gy, cx, cy, half,
                                                                    base.size, bounds)))
    # Draw far trees first so nearer (lower) ones overlap them, like the art.
    visible_trees.sort(key=lambda t: t[3])
    if visible_trees:
        draw = ImageDraw.Draw(crop)
        for world_x, world_y, px, py in visible_trees:
            _draw_tree(draw, px, py, world_x, world_y, kx, ky)
    # Bounty runes: the game's rune icon at the game's size, clipped by the
    # crop edge exactly as the in-game minimap would show that window.
    icon_reach = RUNE_ICON_RADIUS * MINIMAP_ICON_UNIT / 128
    for world_x, world_y in (bounty_rune_spots() if bounty_runes is None else bounty_runes):
        gx, gy = _game_world_to_grid(world_x, world_y)
        if abs(gx - cx) <= half + icon_reach and abs(gy - cy) <= half + icon_reach:
            px, py = _zoom_to_panel(gx, gy, cx, cy, half, base.size, bounds)
            draw_rune_icon(crop, px, py, MINIMAP_ICON_UNIT * kx, MINIMAP_ICON_UNIT * ky)

    def font(size, bold=False):
        return _font(FONT_BOLD if bold else FONT_REGULAR, size)

    def panel(side):
        im = crop.copy()
        draw = ImageDraw.Draw(im)
        for rx, ry in markers:
            px, py = _zoom_to_panel(rx, ry, cx, cy, half, base.size, bounds)
            _draw_water_rune(draw, px, py, 54 * MID_SUPERSAMPLE)

        for world_x, world_y, tower_label in towers:
            tx, ty = _game_world_to_grid(world_x, world_y)
            if not (abs(tx - cx) <= half and abs(ty - cy) <= half):
                continue
            px, py = _zoom_to_panel(tx, ty, cx, cy, half, base.size, bounds)
            _draw_tower_cube(draw, px, py, tower_label[0], diamond_towers, kx, ky)

        spots = cluster_mid_spots(wards[side])
        for spot in reversed(spots):
            px, py = _zoom_to_panel(spot["x"], spot["y"], cx, cy, half, base.size, bounds)
            n = len(spot["items"])
            is_obs = spot["kind"] == "obs"
            fill, edge = (OBS_FILL, OBS_BORDER) if is_obs else (SEN_FILL, SEN_BORDER)
            # Observers and sentries share one size so a spot's number stays
            # readable; colour alone tells the ward type apart.
            radius = (16 + 7 * (n - 1)) * MID_SUPERSAMPLE
            draw.ellipse((px - radius, py - radius, px + radius, py + radius),
                         fill=fill, outline=edge, width=3 * MID_SUPERSAMPLE)
            label_font = font(int(radius * 1.05), True)
            label_w = draw.textlength(spot["label"], font=label_font)
            draw.text((px - label_w / 2, py - radius * 0.72), spot["label"], fill=edge, font=label_font)

            if n > 1:
                tag = f"{n}x"
                tag_font = font(18 * MID_SUPERSAMPLE, True)
                tag_w = draw.textlength(tag, font=tag_font)
                box = (px + radius * .55, py - radius - 6 * MID_SUPERSAMPLE,
                       px + radius * .55 + tag_w + 12 * MID_SUPERSAMPLE, py - radius + 22 * MID_SUPERSAMPLE)
                draw.rounded_rectangle(box, 6 * MID_SUPERSAMPLE, fill="#111820")
                draw.text((px + radius * .55 + 6 * MID_SUPERSAMPLE, py - radius - 6 * MID_SUPERSAMPLE),
                          tag, fill="#f2f3f5", font=tag_font)
        return im.resize((MID_PANEL_SIZE, MID_PANEL_SIZE), Image.LANCZOS), spots

    gap = 24
    width = MID_PANEL_SIZE * 2 + gap
    height = MID_PANEL_SIZE

    sheet = Image.new("RGB", (width, height), BG_COLOR)
    summary = {}
    for i, side in enumerate(("radiant", "dire")):
        im, spots = panel(side)
        x = i * (MID_PANEL_SIZE + gap)

        g_with = len({w["match"] for w in wards[side] if w["kind"] == "obs"})
        g = len(games[side])
        by_mid = sum(1 for w in wards[side] if w["kind"] == "obs" and w.get("is_mid", True))
        by_teammate = g_with - by_mid

        obs_spots = [s for s in spots if s["kind"] == "obs"]
        top_spot_count = len(obs_spots[0]["items"]) if obs_spots else 0
        panel_draw = ImageDraw.Draw(im)
        panel_label = f"{label} <{cutoff // 60}:{cutoff % 60:02d} · {side.title()}"
        label_font = font(22, True)
        label_width = panel_draw.textlength(panel_label, font=label_font)
        panel_draw.rounded_rectangle((12, 12, label_width + 36, 49), 6, fill="#111820")
        panel_draw.text((24, 17), panel_label, fill=HEADER_COLOR, font=label_font)
        sheet.paste(im, (x, 0))

        summary[side] = {
            "games": g,
            "withObserver": g_with,
            "byTeammate": by_teammate,
            "topSpotCount": top_spot_count,
            "spots": len(obs_spots),
        }

    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), summary


def render_mid_ward(payload, team, cutoff=MID_WARD_CUTOFF):
    """Render the rune-to-rune Mid pair, retaining its 1:00 window."""
    games, wards, _mid_names = mid_ward_events(payload, team, cutoff=cutoff)
    return _render_zoomed_lane(games, wards, MID_WINDOW_CX, MID_WINDOW_CY,
                               MID_WINDOW_HALF, "Mid ward", cutoff,
                               mid_rune_spots(), lane_towers("mid"), diamond_towers=True)


def render_side_lane_ward(payload, team, lane, cutoff=SIDE_LANE_CUTOFF):
    """Render the Top or Bottom lane pair through 3:30."""
    games, wards = side_lane_ward_events(payload, team, lane, cutoff=cutoff)
    cx, cy, half = SIDE_LANE_WINDOWS[lane]
    return _render_zoomed_lane(games, wards, cx, cy, half,
                               f"{lane.title()} lane", cutoff,
                               towers=lane_towers(lane))


def render_player_lane_ward_rows(payload, team):
    """One horizontal Radiant/Dire lane pair for Mid, Pos 4, and Pos 5.

    Each player's own official placements are isolated before the per-match
    first-observer rule is applied. Supports use their offlane/safe-lane crop
    for each side, so every image has the same visible two-map layout as the
    full-map support ward images.
    """
    width = MID_PANEL_SIZE * 2 + 24
    header_h = 52
    height = header_h + MID_PANEL_SIZE
    rows = []
    selected = select_map_players(payload, team, positions=(2, 4, 5),
                                  excluded_names=("Mareth",))
    for position, player in selected:
        name = player.get("name") or "Unknown"
        player_payload = {"patches": payload.get("patches") or [], "players": [player]}
        if position == 2:
            lane_image = Image.open(io.BytesIO(render_mid_ward(player_payload, team)[0])).convert("RGB")
            lane_name = "Mid"
        else:
            radiant_lane = "top" if position == 4 else "bottom"
            dire_lane = "bottom" if position == 4 else "top"
            radiant_pair = Image.open(io.BytesIO(
                render_side_lane_ward(player_payload, team, radiant_lane)[0])).convert("RGB")
            dire_pair = Image.open(io.BytesIO(
                render_side_lane_ward(player_payload, team, dire_lane)[0])).convert("RGB")
            lane_image = Image.new("RGB", (width, MID_PANEL_SIZE), BG_COLOR)
            lane_image.paste(radiant_pair.crop((0, 0, MID_PANEL_SIZE, MID_PANEL_SIZE)), (0, 0))
            lane_image.paste(dire_pair.crop((MID_PANEL_SIZE + 24, 0, width, MID_PANEL_SIZE)),
                             (MID_PANEL_SIZE + 24, 0))
            lane_name = "Offlane" if position == 4 else "Safe lane"
        canvas = Image.new("RGB", (width, height), BG_COLOR)
        draw = ImageDraw.Draw(canvas)
        name_font = _font(FONT_BOLD, 25)
        heading = f"{name} · Pos {position} · {lane_name}"
        short_name = heading
        while short_name and draw.textlength(short_name + ("…" if short_name != heading else ""),
                                             font=name_font) > width - 40:
            short_name = short_name[:-1]
        if short_name != heading:
            short_name += "…"
        draw.text((20, 9), short_name, fill=HEADER_COLOR, font=name_font)
        canvas.paste(lane_image, (0, header_h))
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG", optimize=True)
        rows.append((f"lane-pos-{position}.png", buffer.getvalue(),
                     f"{name} (Pos {position}): {lane_name} wards by Radiant and Dire"))
    return rows
