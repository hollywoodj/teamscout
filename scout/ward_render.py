"""Ward placement map rendering for Team Scout (Pillow, no Discord import).

Mirrors the ward-map logic in scout/team_scout_html.py (clustering, patch
selection, world->pct mapping, dot sizing) so the Discord "Wards" page shows
the same picture as the web report - just rendered to a PNG instead of CSS
dots on top of an <img>.
"""

from __future__ import annotations

import io
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .bbc_source import team_key as _team_key

MAP_ASSET_PATH = Path(__file__).resolve().parent.parent / "cache" / "assets" / "detailed_740.jpg"
MAP_ASSET_URL = "https://www.opendota.com/assets/images/dota2/map/detailed_740.jpg"

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


def world_to_px(x, y, size):
    """OpenDota grid coords (~64-192) -> pixel coords on a `size`x`size`
    square: left=(x-64)/128, top=1-(y-64)/128 (matches wardPct in
    team_scout_html.py)."""
    left = (x - 64) / 128
    top = 1 - (y - 64) / 128
    return left * size, top * size


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


def select_map_players(payload, team, positions=(1, 4, 5)):
    """Pick, for each requested position, the roster player whose inferred
    position mode matches it (ties -> whichever has played more games at
    that position). A position nobody plays is skipped. Returns a list of
    (position, player) tuples, in the order `positions` was given."""
    players_by_id = {p.get("id"): p for p in payload.get("players") or []}
    key = team.get("key")
    roster_ids = team.get("roster") or []

    candidates = {}  # position -> (games_at_pos, player)
    for pid in roster_ids:
        player = players_by_id.get(pid)
        if player is None:
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


def _load_map_image(size):
    try:
        if not MAP_ASSET_PATH.exists():
            os.makedirs(MAP_ASSET_PATH.parent, exist_ok=True)
            import urllib.request
            urllib.request.urlretrieve(MAP_ASSET_URL, MAP_ASSET_PATH)
        img = Image.open(MAP_ASSET_PATH).convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception:
        return Image.new("RGB", (size, size), "#1f2b22")


def _draw_ward_map(obs_points, sen_points, size, dim=False, pubs=False):
    """Render one map tile (RGBA) at `size`x`size`, supersampled internally."""
    big = size * SUPERSAMPLE
    base = _load_map_image(big).convert("RGBA")

    overlay = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    sen_clusters = cluster_wards(sen_points)
    obs_clusters = cluster_wards(obs_points)

    def draw_cluster(kind, cluster, fill, border):
        x, y = world_to_px(cluster["x"], cluster["y"], size)
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
# lane. RUNE spots below are approximate - eyeballed off the map image, not
# read from OpenDota data - and only used to draw the rune markers.
MID_RUNE_SPOTS = [(115.2, 136.3), (137.2, 118.7)]  # approximate rune spots
MID_WINDOW_CX, MID_WINDOW_CY, MID_WINDOW_HALF = 126.2, 127.5, 17
MID_WARD_CUTOFF = 60
MID_CLUSTER_RADIUS = 2.0

MID_SRC_SIZE = 900  # native pixel size of detailed_740.jpg
MID_PANEL_SIZE = 600
MID_SUPERSAMPLE = 2


def in_mid_window(x, y):
    """True when (x, y) falls inside the rune-to-rune mid window."""
    return abs(x - MID_WINDOW_CX) <= MID_WINDOW_HALF and abs(y - MID_WINDOW_CY) <= MID_WINDOW_HALF


def _mid_to_src(x, y):
    return ((x - 64) / 128 * MID_SRC_SIZE, (1 - (y - 64) / 128) * MID_SRC_SIZE)


def _mid_to_panel(x, y):
    span = 2 * MID_WINDOW_HALF
    px = (x - (MID_WINDOW_CX - MID_WINDOW_HALF)) / span * MID_PANEL_SIZE * MID_SUPERSAMPLE
    py = ((MID_WINDOW_CY + MID_WINDOW_HALF) - y) / span * MID_PANEL_SIZE * MID_SUPERSAMPLE
    return px, py


def _mid_clock(t):
    return ("-" if t < 0 else "") + f"{abs(t) // 60}:{abs(t) % 60:02d}"


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


def _load_mid_map_base():
    """The map crop base image, dimmed the same way the prototype did:
    colour to 75%, then brightness to 85%. Not resized - detailed_740.jpg is
    already 900x900 (MID_SRC_SIZE), matching the grid->pixel math below."""
    base = Image.open(MAP_ASSET_PATH).convert("RGB")
    return ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.75)).enhance(0.85)


def render_mid_ward(payload, team, cutoff=MID_WARD_CUTOFF):
    """Render the "Mid ward before 1:00, rune to rune" sheet for `team`.

    Returns (png_bytes, summary) where summary is {"radiant": {...},
    "dire": {...}}, each {"games", "withObserver", "byTeammate",
    "topSpotCount", "spots"}.
    """
    games, wards, mid_names = mid_ward_events(payload, team, cutoff=cutoff)

    base = _load_mid_map_base()
    x0, y0 = _mid_to_src(MID_WINDOW_CX - MID_WINDOW_HALF, MID_WINDOW_CY + MID_WINDOW_HALF)
    x1, y1 = _mid_to_src(MID_WINDOW_CX + MID_WINDOW_HALF, MID_WINDOW_CY - MID_WINDOW_HALF)
    crop = base.crop((round(x0), round(y0), round(x1), round(y1))).resize(
        (MID_PANEL_SIZE * MID_SUPERSAMPLE, MID_PANEL_SIZE * MID_SUPERSAMPLE), Image.LANCZOS)

    def font(size, bold=False):
        return _font(FONT_BOLD if bold else FONT_REGULAR, size)

    def panel(side):
        im = crop.copy()
        draw = ImageDraw.Draw(im)
        for rx, ry in MID_RUNE_SPOTS:
            px, py = _mid_to_panel(rx, ry)
            _draw_water_rune(draw, px, py, 54 * MID_SUPERSAMPLE)

        spots = cluster_mid_spots(wards[side])
        for spot in reversed(spots):
            px, py = _mid_to_panel(spot["x"], spot["y"])
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

            starred = any(not item["is_mid"] for item in spot["items"])
            if n > 1 or starred:
                tag = f"{n}x{'*' if starred else ''}"
                tag_font = font(18 * MID_SUPERSAMPLE, True)
                tag_w = draw.textlength(tag, font=tag_font)
                box = (px + radius * .55, py - radius - 6 * MID_SUPERSAMPLE,
                       px + radius * .55 + tag_w + 12 * MID_SUPERSAMPLE, py - radius + 22 * MID_SUPERSAMPLE)
                draw.rounded_rectangle(box, 6 * MID_SUPERSAMPLE, fill="#111820")
                draw.text((px + radius * .55 + 6 * MID_SUPERSAMPLE, py - radius - 6 * MID_SUPERSAMPLE),
                          tag, fill="#f2f3f5", font=tag_font)
        return im.resize((MID_PANEL_SIZE, MID_PANEL_SIZE), Image.LANCZOS), spots

    pad, gap, head_h, sub_h, list_h = 24, 24, 58, 50, 200
    width = pad * 2 + MID_PANEL_SIZE * 2 + gap
    height = pad + head_h + sub_h + MID_PANEL_SIZE + list_h + 40

    sheet = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    mid_name_text = " / ".join(sorted(n for n in mid_names if n)) or "-"
    team_label = team.get("short") or team.get("name") or team.get("key") or "Team"
    title = f"{team_label} · Mid ward before 1:00 · Rune to rune · mid: {mid_name_text}"
    draw.text((pad, pad - 4), title, fill=HEADER_COLOR, font=font(24, True))

    summary = {}
    for i, side in enumerate(("radiant", "dire")):
        im, spots = panel(side)
        x = pad + i * (MID_PANEL_SIZE + gap)
        y = pad + head_h

        g_with = len({w["match"] for w in wards[side] if w["kind"] == "obs"})
        g = len(games[side])
        by_mid = sum(1 for w in wards[side] if w["kind"] == "obs" and w["is_mid"])
        by_teammate = g_with - by_mid

        draw.text((x, y), side.title(), fill=HEADER_COLOR, font=font(22, True))

        obs_spots = [s for s in spots if s["kind"] == "obs"]
        top_spot_count = len(obs_spots[0]["items"]) if obs_spots else 0
        if not obs_spots:
            verdict = "No early observer"
        elif top_spot_count / max(g_with, 1) >= 0.5:
            verdict = f"One main spot ({top_spot_count} of {g_with})"
        else:
            verdict = f"Spread over {len(obs_spots)} spots"
        header_line = f"Mid observer in {g_with} of {g} games · {verdict}"
        if by_teammate:
            header_line += f" · {by_teammate}* by a teammate"
        draw.text((x, y + 28), header_line, fill=LABEL_META_COLOR, font=font(17))

        panel_y = y + sub_h + 6
        sheet.paste(im, (x, panel_y))
        draw.rectangle((x, panel_y, x + MID_PANEL_SIZE - 1, panel_y + MID_PANEL_SIZE - 1), outline="#2a3a48")

        legend_y = panel_y + MID_PANEL_SIZE + 12
        legend_font = font(15)
        label_font = font(17, True)
        for spot in spots:
            def one(item):
                hero = item.get("mid_hero") or "Unknown"
                return f"{hero}{'' if item['is_mid'] else '*'} {_mid_clock(item['t'])}"

            who = ", ".join(one(item) for item in spot["items"])
            kind_label = "obs" if spot["kind"] == "obs" else "sen"
            spot_fill = OBS_FILL if spot["kind"] == "obs" else SEN_FILL
            draw.text((x, legend_y), spot["label"], fill=spot_fill, font=label_font)
            words = f"{len(spot['items'])}x {kind_label} · {who}".split(" ")
            line = ""
            for word in words:
                trial = (line + " " + word).strip()
                if draw.textlength(trial, font=legend_font) > MID_PANEL_SIZE - 24 and line:
                    draw.text((x + 22, legend_y), line, fill="#dbdee1", font=legend_font)
                    legend_y += 21
                    line = word
                else:
                    line = trial
            draw.text((x + 22, legend_y), line, fill="#dbdee1", font=legend_font)
            legend_y += 25

        summary[side] = {
            "games": g,
            "withObserver": g_with,
            "byTeammate": by_teammate,
            "topSpotCount": top_spot_count,
            "spots": len(obs_spots),
        }

    footer_y = height - pad - 16
    footer = ("First observer per game plus every sentry, rune to rune, before 1:00 (pre-horn included) "
              "· * = placed by a teammate, not the mid · heroes are the mid's hero that game "
              "· 7.41 officials")
    draw.text((pad, footer_y), footer, fill="#8b949e", font=font(15))

    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), summary
