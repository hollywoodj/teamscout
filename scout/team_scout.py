"""Mirrored team scouting workspace built from the existing scout cache."""

import base64
import binascii
import copy
import hmac
import json
import os
import re
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config
from .analysis import exact_lane_result, rank_tier_to_str
from .bbc_source import (
    _ward_points, _ward_purchases, bbc_source_stamp, index_official_matches,
    load_bbc_data, team_key, to_steam32,
)
from .cache import Cache
from .deepstats import load_player_deep_stats
from .fetch import (
    MATCH_PROJECTION, MATCHES_SECTION, fetch_player_sections,
    players_from_snapshot,
)
from .hero_positions import POS_WEIGHTS
from .hero_pool import build_hero_pool
from .herodraft import load_full_heroes
from .heroes import load_hero_map
from .league_history import (
    league_history_for, refresh_league_history, unavailable_history,
)
from .opendota import OpenDota
from .overrides import load_overrides, save_overrides
from .rd2l_source import load_rd2l, load_rd2l_matches
from .team_scout_html import render_page

MAX_REQUEST_BODY = 16 * 1024  # bytes

# Team Scout is reachable from the public internet through a Tailscale Funnel, so
# every request carries a shared password. The funnel proxies inbound traffic to
# 127.0.0.1, which means a funnelled request and James's own browser arrive from
# the same address: loopback is NOT a trust signal here, and there is deliberately
# no 127.0.0.1 exemption. Adding one would hand the whole internet a free pass to
# the roster-writing endpoints.
AUTH_REALM = "Team Scout"
AUTH_FILE = "teamscout_auth.txt"   # repo root, gitignored; one line = the password
AUTH_FAIL_DELAY = 1.0              # seconds; blunts automated guessing

_PROFILE_URL_RE = re.compile(
    r"(?:dotabuff\.com|opendota\.com|stratz\.com)/players/(\d+)", re.I
)
_STEAMCOMMUNITY_RE = re.compile(r"steamcommunity\.com/profiles/(\d+)", re.I)


class PlayerNotFound(Exception):
    """Raised when OpenDota has no profile for a pulled player id."""


def parse_steam_id_query(text):
    """Return a steam32 id if `text` is a bare id or a dotabuff/opendota/
    stratz "/players/<id>" or steamcommunity "/profiles/<id>" URL. Anything
    else (a name) returns None."""
    text = str(text or "").strip()
    if not text:
        return None
    match = _STEAMCOMMUNITY_RE.search(text)
    if match:
        return to_steam32(match.group(1))
    match = _PROFILE_URL_RE.search(text)
    if match:
        return to_steam32(match.group(1))
    if re.fullmatch(r"\d+", text):
        return to_steam32(text)
    return None


# Keeps offline mode useful before the first patch-constant fetch. Online runs
# replace this with OpenDota's maintained patch timeline.
PATCH_FALLBACK = [
    {"id": 57, "name": "7.38", "date": "2025-02-19T13:48:29.412Z"},
    {"id": 58, "name": "7.39", "date": "2025-05-22T23:36:01.602Z"},
    {"id": 59, "name": "7.40", "date": "2025-12-16T00:50:40.281Z"},
    {"id": 60, "name": "7.41", "date": "2026-03-24T00:50:59.580Z"},
]


def _timestamp(value):
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).timestamp())
    except (TypeError, ValueError):
        return 0


def normalize_patches(rows):
    """Return validated, timestamped patches in chronological order."""
    result = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            patch_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        released = _timestamp(row.get("date"))
        name = str(row.get("name") or patch_id)
        if released:
            result.append({"id": patch_id, "name": name, "released": released})
    result.sort(key=lambda row: (row["released"], row["id"]))
    return result


def patch_for_match(match, patches):
    """Use OpenDota's patch id when present, otherwise infer from start time."""
    try:
        if match.get("patch") is not None:
            return int(match["patch"])
    except (TypeError, ValueError):
        pass
    started = _timestamp(match.get("start_time"))
    eligible = [row["id"] for row in patches if row["released"] <= started]
    return eligible[-1] if eligible else None


def load_patch_timeline(od, cache, offline=False):
    rows = cache.get_blob(
        "patch_timeline", max_age_hours=config.TEAMSCOUT_PATCH_TTL_HOURS
    )
    if rows is None and not offline:
        rows = od.constants_patch()
        if normalize_patches(rows):
            cache.set_blob("patch_timeline", rows)
    rows = rows or cache.get_blob("patch_timeline") or PATCH_FALLBACK
    return normalize_patches(rows)


def _won(match):
    return ((int(match.get("player_slot") or 0) < 128)
            == bool(match.get("radiant_win")))


def infer_position(match):
    """Infer Dota position 1-5 from lane, hero, and economic behaviour.

    OpenDota's lane_role identifies Safe/Mid/Off, not the two players sharing
    a side lane.  This deliberately returns a confidence and the evidence used
    so Team Scout never presents a side-lane guess as an observed fact.
    """
    try:
        lane = int(match.get("lane_role"))
    except (TypeError, ValueError):
        lane = None
    try:
        hero_id = int(match.get("hero_id"))
    except (TypeError, ValueError):
        hero_id = None

    # Small non-zero baselines let behavioural evidence help on new heroes
    # without overpowering a known physical lane.
    scores = {pos: 0.08 for pos in range(1, 6)}
    evidence = []
    lane_positions = {
        1: {1: 1.00, 5: 0.82, 4: 0.18},
        2: {2: 1.18, 4: 0.08},
        3: {3: 1.00, 4: 0.82, 5: 0.12},
        4: {1: 0.28, 3: 0.35, 4: 0.45},
    }
    if lane in lane_positions:
        for pos, value in lane_positions[lane].items():
            scores[pos] += value
        evidence.append({1: "safe lane", 2: "mid lane", 3: "off lane",
                         4: "jungle"}[lane])

    hero_weights = POS_WEIGHTS.get(hero_id, {})
    if hero_weights:
        for pos, weight in hero_weights.items():
            scores[pos] += 0.9 * weight
        evidence.append("hero profile")

    duration = match.get("duration")
    last_hits = match.get("last_hits")
    gpm = match.get("gold_per_min")
    try:
        minutes = max(float(duration) / 60, 1)
        lhpm = float(last_hits) / minutes if last_hits is not None else None
    except (TypeError, ValueError):
        lhpm = None
    try:
        gpm = float(gpm) if gpm is not None else None
    except (TypeError, ValueError):
        gpm = None
    farm = max((gpm or 0) / 650, (lhpm or 0) / 8)
    if gpm is not None or lhpm is not None:
        farm = min(max(farm, 0), 1.25)
        scores[1] += 0.62 * farm
        scores[2] += 0.48 * farm
        scores[3] += 0.27 * farm
        scores[4] += 0.32 * (1 - min(farm, 1))
        scores[5] += 0.48 * (1 - min(farm, 1))
        evidence.append("farm pattern")

    wards = sum(float(match.get(key) or 0)
                for key in ("purchase_ward_observer", "purchase_ward_sentry"))
    if wards:
        ward_rate = min(wards / 8, 1)
        scores[4] += 0.38 * ward_rate
        scores[5] += 0.62 * ward_rate
        evidence.append("ward purchases")

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_pos, best_score = ranked[0]
    margin = best_score - ranked[1][1]
    confidence = "high" if margin >= 0.55 else "medium" if margin >= 0.25 else "low"
    if not evidence:
        return {"position": None, "confidence": "none", "evidence": []}
    return {
        "position": best_pos,
        "confidence": confidence,
        "evidence": evidence,
        "margin": round(margin, 3),
    }


def compact_match(match, patches):
    """Small browser-safe match row used for arbitrary time-window analysis."""
    def number(key):
        value = match.get(key)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    row = {
        "id": number("match_id"),
        "at": number("start_time"),
        "patch": patch_for_match(match, patches),
        "hero": number("hero_id"),
        "win": _won(match),
        "duration": number("duration"),
        "kills": number("kills"),
        "deaths": number("deaths"),
        "assists": number("assists"),
        "gpm": number("gold_per_min"),
        "xpm": number("xp_per_min"),
        "lh": number("last_hits"),
        "heroDamage": number("hero_damage"),
        "towerDamage": number("tower_damage"),
        "healing": number("hero_healing"),
        "laneEff": number("lane_efficiency_pct"),
        "obs": _ward_purchases(match)[0],
        "sen": _ward_purchases(match)[1],
        "teamfight": number("teamfight_participation"),
        "lane": number("lane_role"),
        "party": number("party_size"),
        "mode": number("game_mode"),
        "lobby": number("lobby_type"),
    }
    inferred = infer_position(match)
    row["position"] = inferred["position"]
    row["positionConfidence"] = inferred["confidence"]
    row["positionEvidence"] = inferred["evidence"]
    row["laneResult"] = None
    return row


TURBO_MODE = 23


def is_pub(row):
    """Real ranked/unranked pub game: excludes practice lobbies (leagues and
    inhouses), Turbo, and rows from older cache sections that never recorded
    a lobby type at all (treated as unknown, not assumed to be a pub)."""
    return row.get("lobby") in (0, 7) and row.get("mode") != TURBO_MODE


def apply_lane_results(matches, deep_samples):
    """Attach parsed 10-minute lane W/L onto compact match rows by match id."""
    by_id = {}
    for sample in deep_samples or []:
        if not isinstance(sample, dict):
            continue
        match_id = sample.get("match_id")
        result = exact_lane_result(sample, 0.6)
        if match_id and result:
            by_id[match_id] = result
    for row in matches:
        row["laneResult"] = by_id.get(row["id"])
    return matches


def deep_summary(samples):
    parsed = [row for row in samples if isinstance(row, dict) and row.get("parsed")]
    lane_rows = [row for row in parsed if all(
        row.get(key) is not None for key in (
            "ally_lane_gold10", "enemy_lane_gold10",
            "ally_lane_xp10", "enemy_lane_xp10",
        )
    )]
    wins = draws = losses = 0
    for row in lane_rows:
        ally = row["ally_lane_gold10"] + 0.6 * row["ally_lane_xp10"]
        enemy = row["enemy_lane_gold10"] + 0.6 * row["enemy_lane_xp10"]
        gap = (ally - enemy) / max(ally + enemy, 1)
        if gap > 0.025:
            wins += 1
        elif gap < -0.025:
            losses += 1
        else:
            draws += 1
    ward_rows = [row for row in parsed if (row.get("duration") or 0) > 0
                 and row.get("observer_kills") is not None
                 and row.get("sentry_kills") is not None]
    minutes30 = sum(row["duration"] for row in ward_rows) / 1800
    return {
        "parsed": len(parsed),
        "lanes": len(lane_rows),
        "laneW": wins,
        "laneD": draws,
        "laneL": losses,
        "dewards30": (round(sum(
            row["observer_kills"] + row["sentry_kills"] for row in ward_rows
        ) / minutes30, 2) if minutes30 else None),
    }


def build_player_record(player, sections, hero_map, patches, deep, official=None,
                         cache=None, meta=None):
    steam32 = int(player["steam32"])
    profile = sections.get("profile") or {}
    inner = profile.get("profile") or {}
    wl = sections.get("wl") or {}
    wins = int(wl.get("win") or 0)
    losses = int(wl.get("lose") or 0)
    heroes = []
    for row in sections.get("heroes") or []:
        try:
            hero_id = int(row["hero_id"])
            games = int(row.get("games") or 0)
            hero_wins = int(row.get("win") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if games:
            heroes.append({
                "id": hero_id,
                "name": hero_map.name(hero_id),
                "games": games,
                "wins": hero_wins,
                "last": int(row.get("last_played") or 0),
                "primaryPosition": max(
                    POS_WEIGHTS.get(hero_id, {}),
                    key=POS_WEIGHTS.get(hero_id, {}).get,
                    default=None,
                ),
            })
    heroes.sort(key=lambda row: (-row["games"], row["name"]))
    matches = [compact_match(row, patches) for row in sections.get("matches") or []]
    matches = [row for row in matches if row["id"] and row["at"]]
    apply_lane_results(matches, deep)
    for row in matches:
        row["heroName"] = hero_map.name(row["hero"]) if row["hero"] else "Unknown"
    matches.sort(key=lambda row: row["at"], reverse=True)
    official = _stamp_official(official)
    official_wins = sum(row.get("result") == "W" for row in official)
    esports = (
        league_history_for(cache, steam32, hero_map)
        if cache is not None else unavailable_history()
    )
    pub_rows = [row for row in matches if is_pub(row)]
    hero_pool = build_hero_pool(
        heroes, pub_rows, official, esports.get("heroes"),
        meta=meta, player_lifetime={"games": wins + losses, "wins": wins},
    )
    return {
        "id": steam32,
        "name": str(player.get("name") or inner.get("personaname") or "Unknown"),
        "mmr": int(player.get("mmr") or 0),
        "role": str(player.get("pref_role") or "Any"),
        "rank": rank_tier_to_str(profile.get("rank_tier")),
        "rankTier": profile.get("rank_tier"),
        "private": bool(inner.get("fh_unavailable")) or not (wins + losses or matches),
        "lifetime": {"games": wins + losses, "wins": wins},
        "heroes": heroes,
        "matches": matches,
        "deep": deep_summary(deep),
        "official": {
            "status": "bbc" if official else "unavailable",
            "games": len(official),
            "wins": official_wins,
            "winrate": (round(official_wins / len(official) * 100, 1)
                        if official else None),
            "matches": official,
        },
        "esports": esports,
        "heroPool": hero_pool,
        "links": {
            "dotabuff": f"https://www.dotabuff.com/players/{steam32}",
            "dotabuffEsports": f"https://www.dotabuff.com/esports/players/{steam32}",
            "opendota": f"https://www.opendota.com/players/{steam32}",
        },
        "lastMatch": matches[0]["at"] if matches else 0,
    }


def _int_ids(values):
    """Unique ints from a JSON list, skipping junk, preserving first-seen order."""
    out = []
    for value in values or []:
        try:
            sid = int(value)
        except (TypeError, ValueError):
            continue
        if sid not in out:
            out.append(sid)
    return out


def assemble_team(team, overrides, id_to_name, team_games):
    """Attach postedRoster/roster/edited/replacements/replaced to one BBC team.

    `team` is a bbc_source team row (has `roster` = the posted roster) or,
    on re-assembly, a previously-assembled team (has `postedRoster`).
    `overrides["rosters"]` maps team_key -> a saved roster override.
    `overrides["replaced"]` maps team_key -> former player ids to drop from
    current-team analysis (distinct from `replacements`, which are standins).
    `team_games` maps team_key -> {steam32: games played for that team}.
    """
    key = team.get("key") or team_key(team["name"])
    posted_roster = [int(x) for x in (
        team["postedRoster"] if team.get("postedRoster") is not None
        else team.get("roster") or []
    )]
    overrides = overrides if isinstance(overrides, dict) else {}
    override_roster = (overrides.get("rosters") or {}).get(key)
    if override_roster is not None:
        roster = _int_ids(override_roster)
        edited = True
    else:
        roster = list(posted_roster)
        edited = False
    roster_set = set(roster)
    replaced_ids = _int_ids((overrides.get("replaced") or {}).get(key))
    replaced_set = set(replaced_ids)
    games_for_team = (team_games or {}).get(key, {})
    replacement_ids = sorted(
        (sid for sid in games_for_team
         if sid not in roster_set and sid not in replaced_set),
        key=lambda sid: -games_for_team[sid],
    )
    replacements = [
        {"id": sid, "name": id_to_name.get(sid, f"Player {sid}"), "games": games_for_team[sid]}
        for sid in replacement_ids
    ]
    replaced_players = [
        {
            "id": sid,
            "name": id_to_name.get(sid, f"Player {sid}"),
            "games": games_for_team.get(sid, 0),
        }
        for sid in sorted(replaced_ids, key=lambda sid: (-games_for_team.get(sid, 0), sid))
    ]
    result = dict(team)
    result.update({
        "key": key,
        "postedRoster": posted_roster,
        "roster": roster,
        "edited": edited,
        "replacements": replacements,
        "replaced": replaced_ids,
        "replacedPlayers": replaced_players,
    })
    return result


def _all_pulled_players(overrides):
    """Every pulled player, shared file plus per-sign-in buckets."""
    pulled = {}
    overrides = overrides if isinstance(overrides, dict) else {}
    for sid, info in (overrides.get("players") or {}).items():
        pulled[str(sid)] = info
    for bucket in (overrides.get("accounts") or {}).values():
        if not isinstance(bucket, dict):
            continue
        for sid, info in (bucket.get("players") or {}).items():
            pulled.setdefault(str(sid), info)
    return pulled


def _stamp_official(rows):
    stamped = []
    for row in rows or []:
        row = dict(row)
        inferred = infer_position({
            "lane_role": row.get("lane_role"),
            "hero_id": row.get("hero_id"),
            "duration": row.get("duration"),
            "last_hits": row.get("last_hits"),
            "gold_per_min": row.get("gpm"),
            "purchase_ward_observer": row.get("observer_wards"),
            "purchase_ward_sentry": row.get("sentry_wards"),
        })
        row["position"] = inferred["position"]
        row["position_confidence"] = inferred["confidence"]
        row["position_evidence"] = inferred["evidence"]
        stamped.append(row)
    return stamped


def _official_block(rows):
    wins = sum(row.get("result") == "W" for row in rows)
    return {
        "status": "bbc" if rows else "unavailable",
        "games": len(rows),
        "wins": wins,
        "winrate": round(wins / len(rows) * 100, 1) if rows else None,
        "matches": rows,
    }


def _extend_official(record, rows):
    current = list((record.get("official") or {}).get("matches") or [])
    seen = {row.get("match_id") for row in current}
    added = _stamp_official(row for row in (rows or []) if row.get("match_id") not in seen)
    if not added:
        return
    current.extend(added)
    current.sort(key=lambda row: row.get("start_time") or 0, reverse=True)
    record["official"] = _official_block(current)


PUB_WARD_LIMIT = 8
PUB_WARD_SECTION = "ward_matches"
_WARD_PATCH_NAME = "7.41"


def _ward_patch(patches):
    """OpenDota patch id and release time for the ward-map patch."""
    for row in patches or []:
        if str(row.get("name")) == _WARD_PATCH_NAME:
            try:
                return int(row["id"]), int(row.get("released") or 0)
            except (TypeError, ValueError):
                break
    return 60, 0


def _parsed_match(payload):
    return (
        isinstance(payload, dict)
        and bool(payload.get("version"))
        and isinstance(payload.get("players"), list)
    )


def pub_ward_row(match, steam32, patch_id):
    """One player's observer/sentry placements from a parsed match, or None."""
    if not _parsed_match(match):
        return None
    try:
        if int(match.get("patch")) != int(patch_id):
            return None
        steam32 = int(steam32)
    except (TypeError, ValueError):
        return None
    target = None
    for player in match.get("players") or []:
        if not isinstance(player, dict):
            continue
        try:
            if int(player.get("account_id")) == steam32:
                target = player
                break
        except (TypeError, ValueError):
            continue
    if target is None:
        return None
    try:
        radiant = int(target.get("player_slot") or 0) < 128
    except (TypeError, ValueError):
        radiant = True
    won = radiant == bool(match.get("radiant_win"))
    return {
        "match_id": int(match.get("match_id") or 0),
        "start_time": int(match.get("start_time") or 0),
        "patch": int(patch_id),
        "hero_id": target.get("hero_id"),
        "win": won,
        "is_radiant": radiant,
        "obs_map": _ward_points(target.get("obs_log")),
        "sen_map": _ward_points(target.get("sen_log")),
        "pub": True,
    }


def _ward_match_index(rows, released, skip_ids):
    """Newest current-patch match ids from an OpenDota recent-match list."""
    found = []
    seen = set(skip_ids)
    ordered = sorted(
        (row for row in rows or [] if isinstance(row, dict)),
        key=lambda row: int(row.get("start_time") or 0),
        reverse=True,
    )
    for row in ordered:
        try:
            match_id = int(row.get("match_id"))
            start = int(row.get("start_time") or 0)
        except (TypeError, ValueError):
            continue
        if match_id in seen or start < released:
            continue
        seen.add(match_id)
        found.append({"match_id": match_id, "start_time": start})
        if len(found) >= PUB_WARD_LIMIT:
            break
    return found


def load_pub_wards(od, cache, steam32, patches, skip_ids, offline=False):
    """Parsed 7.41 pub ward maps for one player.

    League games already in `skip_ids` are left out. Unparsed matches are
    sent to OpenDota's parse queue when this is allowed to use the network.
    Returns (rows, pending) where pending means a current-patch game still
    has no parse.
    """
    patch_id, released = _ward_patch(patches)
    max_age = None if offline else config.TTL_HOURS["recent"]
    index = cache.get_section(steam32, PUB_WARD_SECTION, max_age)
    if index is None and not offline:
        recent = od.recent_matches(steam32) or []
        index = _ward_match_index(recent, released, skip_ids)
        cache.set_section(steam32, PUB_WARD_SECTION, index)
    elif isinstance(index, list):
        index = _ward_match_index(index, released, skip_ids)
    else:
        index = []
    rows = []
    pending = False
    for item in index:
        match_id = item["match_id"]
        payload = cache.get_match(match_id)
        if not _parsed_match(payload) and not offline:
            fetched = od.match(match_id)
            if isinstance(fetched, dict):
                payload = fetched
                cache.set_match(match_id, fetched)
        if not _parsed_match(payload):
            pending = True
            if not offline:
                od.request_parse(match_id)
            continue
        row = pub_ward_row(payload, steam32, patch_id)
        if row and (row["obs_map"] or row["sen_map"]):
            rows.append(row)
        elif row is None and int(payload.get("patch") or 0) == patch_id:
            pending = True
    return rows, pending


def _attach_pub_wards(records, teams, od, cache, patches, offline=False):
    """Fill pub ward maps for stand-ins whose league games have no placements."""
    by_id = {}
    for record in records:
        try:
            by_id[int(record["id"])] = record
        except (KeyError, TypeError, ValueError):
            continue
    standins = []
    seen = set()
    for team in teams:
        if not team.get("rd2lId") and not str(team.get("league") or "").upper().startswith("RD2L"):
            continue
        for row in team.get("replacements") or []:
            try:
                sid = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            if sid in seen or sid not in by_id:
                continue
            seen.add(sid)
            standins.append(sid)
    for sid in standins:
        record = by_id[sid]
        official = (record.get("official") or {}).get("matches") or []
        skip = set()
        placed = 0
        for row in official:
            try:
                skip.add(int(row.get("match_id")))
            except (TypeError, ValueError):
                pass
            placed += len(row.get("obs_map") or []) + len(row.get("sen_map") or [])
        if placed:
            record["pubWards"] = []
            record["pubWardsPending"] = False
            continue
        rows, pending = load_pub_wards(
            od, cache, sid, patches, skip, offline=offline,
        )
        record["pubWards"] = rows
        record["pubWardsPending"] = pending
        if rows or pending:
            print(
                f"  pub wards {record.get('name')}: {len(rows)} parsed"
                f"{' · parse queued' if pending else ''}",
                flush=True,
            )


def _rd2l_record(player, hero_map, patches, official=None, cache=None, meta=None):
    """Name and medal only. OpenDota fills the rest when that player is pulled."""
    rank = player.get("rankTier")
    return build_player_record(
        {
            "steam32": int(player["id"]),
            "name": player.get("name") or str(player["id"]),
            "mmr": 0,
        },
        {"profile": {"rank_tier": rank, "profile": {"personaname": player.get("name") or ""}}},
        hero_map,
        patches,
        [],
        official,
        cache=cache,
        meta=meta,
    )


def _merge_rd2l(teams, records, indexed, rd2l, hero_map, patches, raw_matches=None,
                 cache=None, meta=None):
    """Add one RD2L division beside the BBC league. Existing player records stay."""
    used = {team.get("key") for team in teams}
    by_player = {}
    for player in rd2l.get("players") or []:
        try:
            by_player[int(player["id"])] = player
        except (KeyError, TypeError, ValueError):
            continue
    name_to_id = {team_key(player.get("name")): sid for sid, player in by_player.items()}
    prepared = []
    for raw in rd2l.get("teams") or []:
        name = raw.get("name") or ""
        key = raw.get("key") or team_key(name)
        if not name or not key:
            continue
        if key in used:
            key = f"{key}-{str(raw.get('id') or 'x')[:6].lower()}"
        used.add(key)
        prepared.append((key, raw))
    league = rd2l.get("league") or "RD2L"
    official, team_matches, team_games = index_official_matches(
        raw_matches or {},
        [{
            "key": key,
            "name": raw.get("name") or "",
            "short": raw.get("short") or raw.get("name") or "",
            "roster": raw.get("roster") or [],
        } for key, raw in prepared],
        hero_map,
        league,
        name_to_id,
    )
    by_record = {}
    for row in records:
        try:
            by_record[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue

    def ensure_player(sid, info):
        if sid in by_record:
            _extend_official(by_record[sid], official.get(sid))
            indexed.add(sid)
            return
        record = _rd2l_record(info, hero_map, patches, official.get(sid), cache=cache, meta=meta)
        records.append(record)
        by_record[sid] = record
        indexed.add(sid)

    empty = {"players": {}, "rosters": {}, "replaced": {}}
    added = {}
    for key, raw in prepared:
        for sid in raw.get("roster") or []:
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                continue
            info = by_player.get(sid) or {"id": sid, "name": str(sid)}
            ensure_player(sid, info)
        for sid, rows in official.items():
            played_here = any(row.get("team_key") == key for row in rows)
            if played_here and sid not in indexed:
                name = next((row.get("player_name") for row in rows if row.get("player_name")), None)
                ensure_player(sid, by_player.get(sid) or {"id": sid, "name": name or str(sid)})
        id_to_name = {row["id"]: row["name"] for row in records}
        name = raw.get("name") or ""
        assembled = assemble_team({
            "key": key,
            "name": name,
            "short": raw.get("short") or name,
            "captain": raw.get("captain") or "",
            "roster": raw.get("roster") or [],
            "record": raw.get("record") or "",
            "rank": raw.get("rank") or 0,
            "matchIds": list(raw.get("matchIds") or []),
        }, empty, id_to_name, team_games)
        assembled["league"] = raw.get("league") or rd2l.get("league") or "RD2L"
        assembled["rd2lId"] = raw.get("id")
        teams.append(assembled)
        if raw.get("id"):
            added[raw["id"]] = (assembled, raw)
    standings = []
    for assembled, raw in added.values():
        standings.append({
            "name": assembled["name"],
            "short": assembled["short"],
            "key": assembled["key"],
            "wins": raw.get("wins") or 0,
            "losses": raw.get("losses") or 0,
            "record": raw.get("record") or "",
            "captain": assembled.get("captain") or "",
            "rank": raw.get("rank") or 0,
            "league": assembled.get("league") or "",
        })
    matchups = []
    for row in rd2l.get("matchups") or []:
        home = added.get(row.get("homeId"))
        away = added.get(row.get("awayId"))
        if not home or not away:
            continue
        home_team, _home_raw = home
        away_team, _away_raw = away
        matchups.append({
            "a": home_team["name"],
            "aShort": home_team["short"],
            "aCaptain": home_team.get("captain") or "",
            "aKey": home_team["key"],
            "b": away_team["name"],
            "bShort": away_team["short"],
            "bCaptain": away_team.get("captain") or "",
            "bKey": away_team["key"],
            "league": home_team.get("league") or "",
        })
    return standings, matchups, team_matches


def _all_teamscout_steam32_ids(players, bbc, overrides):
    """Every steam32 build_payload will build a record for: signup snapshot,
    BBC posted/official players, and pulled overrides. RD2L-only players are
    added separately once RD2L is loaded (see `_league_history_seeds`)."""
    ids = {int(player["steam32"]) for player in players}
    ids.update(bbc["players"].keys())
    ids.update(bbc["official"].keys())
    for steam32_str in _all_pulled_players(overrides):
        try:
            ids.add(int(steam32_str))
        except (TypeError, ValueError):
            continue
    return ids


def _league_history_seeds(bbc, rd2l=None):
    """Free leagueid seeds: BBC's official matches are always LD2L, and RD2L's
    own match cache already carries a real leagueid from OpenDota."""
    bbc_match_ids = set()
    for rows in (bbc or {}).get("official", {}).values():
        for row in rows or []:
            try:
                bbc_match_ids.add(int(row.get("match_id")))
            except (TypeError, ValueError):
                continue
    rd2l_matches = load_rd2l_matches(rd2l, offline=True) if rd2l else {}
    return bbc_match_ids, rd2l_matches


def _refresh_targets(season, bbc_root=None, overrides_path=None):
    """Everyone Team Scout builds a record for, posted roster players first
    (so a pass cut short by OpenDota trouble still covers the rosters), plus
    the free leagueid seeds. None when there is no cached player pool."""
    cache = Cache()
    od = OpenDota()
    _, players = players_from_snapshot(cache, season)
    if not players:
        return None
    hero_map = load_hero_map(od, cache, offline=True)
    bbc = load_bbc_data(hero_map, root=bbc_root)
    overrides = load_overrides(overrides_path)
    ids = _all_teamscout_steam32_ids(players, bbc, overrides)
    rostered = set(bbc["players"].keys())
    rd2l = load_rd2l()
    if rd2l:
        for player in rd2l.get("players") or []:
            try:
                ids.add(int(player["id"]))
                rostered.add(int(player["id"]))
            except (KeyError, TypeError, ValueError):
                continue
    ordered = sorted(ids, key=lambda sid: (sid not in rostered, sid))
    bbc_match_ids, rd2l_matches = _league_history_seeds(bbc, rd2l)
    return cache, od, ordered, bbc_match_ids, rd2l_matches


def refresh_esports_history(season, bbc_root=None, overrides_path=None):
    """`--refresh-esports`: resolve league history for every player Team
    Scout would build a record for. Online only; never starts the server."""
    targets = _refresh_targets(season, bbc_root, overrides_path)
    if targets is None:
        print("  ✗ No cached player pool. Run the scout once first.")
        raise SystemExit(1)
    cache, od, ids, bbc_match_ids, rd2l_matches = targets
    return refresh_league_history(
        od, cache, ids, bbc_match_ids=bbc_match_ids, rd2l_matches=rd2l_matches,
    )


def refresh_pub_sections(od, cache, steam32):
    """Only the sections Team Scout reads, on Team Scout's own schedule.

    The full scout run fetches eight sections per player; Recon and the
    player pages need just the recent match sample (kept fresh), plus rank
    and lifetime heroes (slow-moving). Returns the calls spent."""
    before = od.calls
    plan = (
        ("profile", config.TEAMSCOUT_SLOW_TTL_HOURS, lambda: od.player(steam32)),
        ("heroes", config.TEAMSCOUT_SLOW_TTL_HOURS, lambda: od.player_heroes(steam32)),
        (MATCHES_SECTION, config.TEAMSCOUT_MATCHES_TTL_HOURS, lambda: od.matches(
            steam32,
            limit=config.MATCH_SAMPLE_LIMIT,
            date=config.MATCH_SAMPLE_DAYS,
            project=MATCH_PROJECTION,
        )),
    )
    for section, hours, fetcher in plan:
        if cache.get_section(steam32, section, hours) is not None:
            continue
        data = fetcher()
        if data is not None:  # a failed call keeps the last good copy
            cache.set_section(steam32, section, data)
    return od.calls - before


def auto_refresh_cycle(season, bbc_root=None, overrides_path=None):
    """One background pass: fresh pub samples, then a slice of esports
    classification. Returns a summary line, or None with no player pool."""
    targets = _refresh_targets(season, bbc_root, overrides_path)
    if targets is None:
        return None
    cache, od, ids, bbc_match_ids, rd2l_matches = targets
    started = time.time()
    refreshed = sum(1 for sid in ids if refresh_pub_sections(od, cache, sid))
    pub_calls = od.calls
    refresh_league_history(
        od, cache, ids, budget=config.TEAMSCOUT_ESPORTS_BUDGET,
        bbc_match_ids=bbc_match_ids, rd2l_matches=rd2l_matches,
    )
    return (f"{len(ids)} players, {refreshed} pub samples refreshed "
            f"({pub_calls} calls), {od.calls - pub_calls} esports calls, "
            f"{round(time.time() - started)}s")


def build_payload(season, offline=False, bbc_root=None, overrides_path=None):
    """Build the browser payload without refetching every player profile."""
    cache = Cache()
    od = OpenDota()
    label, players = players_from_snapshot(cache, season)
    if not players:
        return None
    patches = load_patch_timeline(od, cache, offline=offline)
    hero_map = load_hero_map(od, cache, offline=offline)
    full_heroes = load_full_heroes(od, cache, offline=offline)
    # The BBC show kit is the authoritative current-season source: its feed
    # carries posted rosters and its cache carries the already-downloaded full
    # LD2L match payloads. No BBC credential is read or copied.
    bbc = load_bbc_data(hero_map, root=bbc_root)
    overrides = load_overrides(overrides_path)
    meta = cache.get_blob("hero_meta_stats") or {}
    rd2l = load_rd2l()

    if not offline:
        # Best-effort: a failed or slow league-history refresh must never
        # block a Team Scout rebuild. --refresh-esports is the deliberate,
        # patient way to run this; this is just so a manual online run
        # doesn't serve stale esports data indefinitely.
        try:
            ids_for_refresh = _all_teamscout_steam32_ids(players, bbc, overrides)
            bbc_match_ids, rd2l_matches_seed = _league_history_seeds(bbc, rd2l)
            refresh_league_history(
                od, cache, ids_for_refresh,
                bbc_match_ids=bbc_match_ids, rd2l_matches=rd2l_matches_seed,
            )
        except Exception as exc:
            print(f"  ⚠ League history refresh failed: {exc}", flush=True)

    records = []
    indexed = set()
    for player in players:
        sections, _ = fetch_player_sections(od, cache, player, offline=True)
        deep = load_player_deep_stats(
            od, cache, player, sections.get("matches") or [], offline=True
        )
        rec = build_player_record(
            player, sections, hero_map, patches, deep,
            bbc["official"].get(int(player["steam32"])),
            cache=cache, meta=meta,
        )
        records.append(rec)
        indexed.add(rec["id"])

    # Mid-season roster changes may not exist in the original signup
    # snapshot. Keep the posted team complete and expose the official rows
    # BBC does have, while leaving unavailable public fields honest.
    for steam32, player in bbc["players"].items():
        if steam32 in indexed:
            continue
        records.append(build_player_record(
            {"steam32": steam32, "name": player["name"], "mmr": 0,
             "pref_role": "Unknown"},
            {"profile": {"rank_tier": player.get("rank_tier")}},
            hero_map, patches, [], bbc["official"].get(steam32),
            cache=cache, meta=meta,
        ))
        indexed.add(steam32)

    # Real replacements/standins: any steam32 that played an official match
    # but never appeared in a signup or a posted roster.
    for steam32, rows in bbc["official"].items():
        if steam32 in indexed:
            continue
        name = next((row.get("player_name") for row in rows if row.get("player_name")), None)
        records.append(build_player_record(
            {"steam32": steam32, "name": name or f"Player {steam32}", "mmr": 0,
             "pref_role": "Unknown"},
            {}, hero_map, patches, [], rows,
            cache=cache, meta=meta,
        ))
        indexed.add(steam32)

    # Pulled players saved to overrides (from POST /api/player), rebuilt from
    # their now-cached sections rather than refetched every rebuild. Account
    # buckets are included so a rebuild still has the cached sections; the
    # request view decides which sign-in is allowed to see them.
    for steam32_str, info in _all_pulled_players(overrides).items():
        try:
            steam32 = int(steam32_str)
        except (TypeError, ValueError):
            continue
        if steam32 in indexed:
            continue
        name = str((info or {}).get("name") or f"Player {steam32}")
        player = {"steam32": steam32, "name": name, "mmr": 0, "pref_role": "Unknown"}
        sections, _ = fetch_player_sections(od, cache, player, offline=True)
        deep = load_player_deep_stats(
            od, cache, player, sections.get("matches") or [], offline=True
        )
        records.append(build_player_record(
            player, sections, hero_map, patches, deep,
            bbc["official"].get(steam32),
            cache=cache, meta=meta,
        ))
        indexed.add(steam32)

    records.sort(key=lambda row: (-row["mmr"], row["name"].lower()))
    id_to_name = {row["id"]: row["name"] for row in records}
    league_name = bbc["league"]
    teams = [assemble_team(team, overrides, id_to_name, bbc.get("team_games"))
             for team in bbc["teams"]]
    for team in teams:
        team["league"] = league_name
    standings = [dict(row) for row in bbc["standings"]]
    matchups = [dict(row) for row in (bbc.get("matchups") or [])]
    for row in standings:
        row.setdefault("league", league_name)
    for row in matchups:
        row.setdefault("league", league_name)
    rd2l_matches = []
    if rd2l:
        raw_matches = load_rd2l_matches(
            rd2l, fetcher=None if offline else od.match, offline=offline,
        )
        extra_standings, extra_matchups, rd2l_matches = _merge_rd2l(
            teams, records, indexed, rd2l, hero_map, patches, raw_matches,
            cache=cache, meta=meta,
        )
        standings.extend(extra_standings)
        matchups.extend(extra_matchups)
        print(
            f"  RD2L: {rd2l.get('league') or 'division'} · {len(extra_standings)} teams"
            f" · {len(raw_matches)} cached games",
            flush=True,
        )
        _attach_pub_wards(records, teams, od, cache, patches, offline=offline)
    heroes_out = {hid: {"n": info.get("n"), "key": info.get("key")}
                  for hid, info in full_heroes.items()}
    latest_match = max((row["lastMatch"] for row in records), default=0)
    return {
        "season": label or f"Season {season}",
        "seasonId": season,
        "generatedAt": int(time.time()),
        "latestMatch": latest_match,
        "patches": patches,
        "teams": teams,
        "matchups": matchups,
        "standings": standings,
        "teamMatches": list(bbc["teamMatches"] or []) + list(rd2l_matches or []),
        "heroes": heroes_out,
        "officialSource": {
            "available": bbc["available"],
            "league": bbc["league"],
            "generated": bbc["generated"],
            "week": bbc["week"],
        },
        "players": records,
    }


def write_team_scout(payload, output_file):
    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(render_page(payload))
    return os.path.abspath(output_file)


def search_players(payload, query):
    """Search for a player by id/URL, then by pool name, then OpenDota name."""
    direct_id = parse_steam_id_query(query)
    if direct_id is not None:
        od = OpenDota()
        profile = od.player(direct_id)
        if not isinstance(profile, dict) or not profile.get("profile"):
            return []
        inner = profile["profile"]
        pool_ids = {row["id"] for row in payload.get("players", [])}
        return [{
            "id": direct_id,
            "name": inner.get("personaname") or f"Player {direct_id}",
            "avatar": inner.get("avatarmedium"),
            "inPool": direct_id in pool_ids,
        }]

    results = []
    seen = set()
    needle = query.casefold()
    for row in payload.get("players", []):
        if needle in str(row.get("name") or "").casefold():
            results.append({"id": row["id"], "name": row["name"], "avatar": None, "inPool": True})
            seen.add(row["id"])
            if len(results) >= 10:
                break

    if len(results) < 10:
        od = OpenDota()
        raw = od.search(query)
        if isinstance(raw, list):
            for row in raw:
                if len(results) >= 10:
                    break
                try:
                    account_id = int(row.get("account_id"))
                except (TypeError, ValueError):
                    continue
                if account_id in seen:
                    continue
                results.append({
                    "id": account_id,
                    "name": row.get("personaname") or f"Player {account_id}",
                    "avatar": row.get("avatarfull"),
                    "inPool": False,
                })
                seen.add(account_id)
    return results


def _account_bucket(overrides, account):
    """Where this sign-in stores roster edits and pulled players.

    A locked sign-in writes its own bucket. An unlocked sign-in keeps using
    the shared top-level maps, which is the original single-password file.
    """
    if not account or not account.get("locked") or not account.get("user"):
        return overrides
    accounts = overrides.setdefault("accounts", {})
    bucket = accounts.setdefault(account["user"], {})
    bucket.setdefault("players", {})
    bucket.setdefault("rosters", {})
    bucket.setdefault("replaced", {})
    return bucket


def pull_player_online(steam32, overrides_path=None, account=None):
    """Fetch one player fresh from OpenDota (ignoring --offline), save them
    to overrides, and return their built record. Raises PlayerNotFound if
    OpenDota has no profile for this id."""
    cache = Cache()
    od = OpenDota()
    placeholder = {"steam32": steam32, "name": f"Player {steam32}", "mmr": 0,
                   "pref_role": "Unknown"}
    sections, _ = fetch_player_sections(od, cache, placeholder, offline=False)
    profile = sections.get("profile")
    if not isinstance(profile, dict) or not profile.get("profile"):
        raise PlayerNotFound(str(steam32))
    name = profile["profile"].get("personaname") or placeholder["name"]
    player = dict(placeholder, name=name)
    deep = load_player_deep_stats(
        od, cache, player, sections.get("matches") or [], offline=False
    )
    hero_map = load_hero_map(od, cache, offline=True)
    patches = load_patch_timeline(od, cache, offline=True)
    bbc = load_bbc_data(hero_map)
    meta = cache.get_blob("hero_meta_stats") or {}
    record = build_player_record(
        player, sections, hero_map, patches, deep, bbc["official"].get(steam32),
        cache=cache, meta=meta,
    )
    overrides = load_overrides(overrides_path)
    bucket = _account_bucket(overrides, account)
    bucket["players"][str(steam32)] = {"name": record["name"], "added": int(time.time())}
    save_overrides(overrides, overrides_path)
    return record


def _validate_id_list(values, field, max_len):
    """Return (True, cleaned_list) or (False, error_message)."""
    if not isinstance(values, list) or len(values) > max_len:
        return False, f"{field} must be a list of at most {max_len} player ids"
    cleaned = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            return False, f"{field} ids must be integers"
        if value in cleaned:
            return False, f"{field} ids must be unique"
        cleaned.append(value)
    return True, cleaned


def _validate_roster(roster):
    return _validate_id_list(roster, "roster", 5)


def _team_after_roster_change(old_team, new_roster, edited, replaced=None):
    """Cheap, immediate view of a team after a roster/replaced override,
    without waiting on a full payload rebuild."""
    roster_set = set(new_roster)
    replaced_ids = list(
        replaced if replaced is not None else old_team.get("replaced") or []
    )
    replaced_set = set(replaced_ids)
    replacements = [
        row for row in (old_team.get("replacements") or [])
        if row["id"] not in roster_set and row["id"] not in replaced_set
    ]
    names, games = {}, {}
    for row in (old_team.get("replacedPlayers") or []) + (old_team.get("replacements") or []):
        names[row["id"]] = row.get("name") or names.get(row["id"])
        if row.get("games") is not None:
            games[row["id"]] = row["games"]
    replaced_players = [
        {"id": sid, "name": names.get(sid, f"Player {sid}"), "games": games.get(sid, 0)}
        for sid in replaced_ids
    ]
    result = dict(old_team)
    result.update({
        "roster": list(new_roster),
        "edited": edited,
        "replacements": replacements,
        "replaced": replaced_ids,
        "replacedPlayers": replaced_players,
    })
    return result


class TeamScoutState:
    """Holds the current payload/page and rebuilds them under a lock so
    concurrent POSTs (roster edits, player pulls) never interleave a write."""

    def __init__(self, season, offline=False):
        self.season = season
        self.offline = offline
        self._rebuild_lock = threading.Lock()
        self._data_lock = threading.Lock()
        self.payload = None
        self.page = b""

    def build_sync(self):
        with self._rebuild_lock:
            payload = build_payload(self.season, offline=self.offline)
            if payload is None:
                raise RuntimeError("no cached player pool")
            output = f"LD2L_{payload['season']}_Team_Scout.html".replace(" ", "_")
            path = write_team_scout(payload, output)
            with open(path, "rb") as handle:
                page = handle.read()
            with self._data_lock:
                self.payload = payload
                self.page = page
            return payload

    def rebuild_async(self):
        threading.Thread(target=self._safe_build, daemon=True).start()

    def _safe_build(self):
        try:
            self.build_sync()
        except Exception as exc:  # keep serving the last-good page
            print(f"  ⚠ Team Scout rebuild failed: {exc}")

    def snapshot(self):
        with self._data_lock:
            return self.payload, self.page

    def auto_refresh(self, hours=None, first_delay=None):
        """Keep the cache fresh from inside the always-on service: every few
        hours pull new pub samples and classify more esports lobbies, then
        rebuild. The page itself is still built from cache only."""
        hours = config.TEAMSCOUT_REFRESH_HOURS if hours is None else hours
        first_delay = (config.TEAMSCOUT_REFRESH_FIRST_DELAY
                       if first_delay is None else first_delay)
        threading.Thread(
            target=self._auto_refresh, args=(hours, first_delay), daemon=True
        ).start()

    def _auto_refresh(self, hours, first_delay):
        time.sleep(first_delay)
        while True:
            try:
                print("  ↻ Auto-refresh: pulling fresh OpenDota data", flush=True)
                summary = auto_refresh_cycle(self.season)
                if summary:
                    print(f"  ↻ Auto-refresh done: {summary}", flush=True)
                    self._safe_build()
            except Exception as exc:  # never take the server down with it
                print(f"  ⚠ Auto-refresh failed: {exc}", flush=True)
            time.sleep(hours * 3600)

    def watch_bbc(self, interval=None):
        """Rebuild when BBC's feed or match cache is rewritten (new week)."""
        interval = config.TEAMSCOUT_BBC_POLL_SECONDS if interval is None else interval
        threading.Thread(
            target=self._watch_bbc, args=(interval,), daemon=True
        ).start()

    def _watch_bbc(self, interval):
        stamp = bbc_source_stamp()
        while True:
            time.sleep(interval)
            next_stamp = bbc_source_stamp()
            if next_stamp == stamp:
                continue
            stamp = next_stamp
            print("  ↻ BBC feed changed — rebuilding Team Scout", flush=True)
            self.rebuild_async()


def _legacy_account(password):
    return {
        "user": None,
        "password": password,
        "team": None,
        "league": None,
        "locked": False,
    }


def parse_teamscout_accounts(text):
    """Sign-ins from teamscout_auth.txt.

    A file with no colons is the original single shared password: any username
    works and the login can see every team. A line with no colon still means
    that, even next to team lines. Otherwise each line is
    `username:password:league:Team Name`. That login is locked to Team Name.
    It can scout other teams in the same league, and it receives nothing from
    any other league. A password here cannot contain a colon.
    """
    rows = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line)
    if not rows:
        return []
    if not any(":" in row for row in rows):
        return [_legacy_account(rows[0])]
    accounts = []
    seen = set()
    for row in rows:
        if ":" not in row:
            accounts.append(_legacy_account(row))
            continue
        user, sep, rest = row.partition(":")
        user = user.strip()
        if not sep or not user or user in seen:
            continue
        password, sep2, rest = rest.partition(":")
        if not password:
            continue
        league, team = "", ""
        if sep2:
            league, sep3, team = rest.partition(":")
            if not sep3:
                if league.strip() == "*":
                    team, league = "", "*"
                else:
                    team, league = league, ""
        team = team.strip()
        league = league.strip()
        admin = league == "*"
        if admin:
            team = ""
            league = "*"
        seen.add(user)
        accounts.append({
            "user": user,
            "password": password,
            "team": team or None,
            "league": None if admin else (league or None),
            "locked": bool(team) and not admin,
            "admin": admin,
        })
    return accounts


def _read_auth_file(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def load_teamscout_accounts(path=None):
    """Sign-ins from $TEAMSCOUT_PASSWORD or teamscout_auth.txt.

    The environment variable is the original single shared password, even if
    it contains a colon. Two team sign-ins live in the file.
    """
    env = os.environ.get("TEAMSCOUT_PASSWORD", "").strip()
    if env:
        return [_legacy_account(env)]
    if path is None:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo_root, AUTH_FILE)
    return parse_teamscout_accounts(_read_auth_file(path))


def load_teamscout_password(path=None):
    """The shared password, when the auth file is still the one-line form."""
    accounts = load_teamscout_accounts(path)
    if len(accounts) == 1 and accounts[0].get("user") is None and not accounts[0].get("locked"):
        return accounts[0]["password"]
    return ""


def _coerce_accounts(password_or_accounts):
    if isinstance(password_or_accounts, str):
        if not password_or_accounts:
            return []
        return [_legacy_account(password_or_accounts)]
    return list(password_or_accounts or [])


def _basic_credentials(header):
    """(username, password) from an Authorization: Basic header, or None.

    Every malformed shape returns None rather than raising, so a junk header
    is a 401 and not a 500 an attacker can use to probe.
    """
    if not header:
        return None
    scheme, _, encoded = header.partition(" ")
    encoded = encoded.strip()
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    user, _, password = decoded.partition(":")
    return user, password


def authenticate(header, accounts):
    """The matching sign-in, or None. Compares every account so a miss does
    not reveal which usernames exist."""
    creds = _basic_credentials(header)
    if creds is None or not accounts:
        return None
    user, password = creds
    matched = None
    for account in accounts:
        expected = account.get("user")
        user_ok = expected is None or hmac.compare_digest(
            user.encode("utf-8"), str(expected).encode("utf-8")
        )
        pass_ok = hmac.compare_digest(
            password.encode("utf-8"), str(account.get("password") or "").encode("utf-8")
        )
        if user_ok and pass_ok and matched is None:
            matched = account
    return matched


def _public_account(account, team_key_value=None):
    account = account or {}
    return {
        "user": account.get("user") or "",
        "locked": bool(account.get("locked")),
        "team": account.get("team"),
        "teamKey": team_key_value,
        "league": account.get("league"),
        "admin": bool(account.get("admin")),
    }


def _league_hit(league_name, token):
    if not token:
        return False
    return str(token).casefold() in str(league_name or "").casefold()


def _posted_team(team):
    """Roster as the league posted it, without another sign-in's edits."""
    team = copy.deepcopy(team)
    posted = _int_ids(team.get("postedRoster") or team.get("roster"))
    team["postedRoster"] = posted
    team["roster"] = list(posted)
    team["edited"] = False
    team["replaced"] = []
    team["replacedPlayers"] = []
    return team


def _lookup_ids(mapping, key):
    if not isinstance(mapping, dict) or key not in mapping:
        return None
    return _int_ids(mapping.get(key))


def _names_from(players):
    names = {}
    for row in players or []:
        if not isinstance(row, dict):
            continue
        try:
            sid = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        names[sid] = row.get("name") or f"Player {sid}"
    return names


def _apply_private(team, roster_ids, replaced_ids, names):
    if roster_ids is not None:
        team["roster"] = list(roster_ids)
        team["edited"] = True
    if replaced_ids is not None:
        team["replaced"] = list(replaced_ids)
        team["replacedPlayers"] = [
            {"id": sid, "name": names.get(sid, f"Player {sid}"), "games": 0}
            for sid in replaced_ids
        ]
    return team


def _team_player_ids(team):
    ids = []
    for field in ("roster", "postedRoster", "replaced"):
        ids.extend(_int_ids(team.get(field)))
    for row in (team.get("replacements") or []) + (team.get("replacedPlayers") or []):
        if isinstance(row, dict):
            ids.extend(_int_ids([row.get("id")]))
    return ids


def _filter_player(player, visible_keys):
    player = copy.deepcopy(player)
    official = player.get("official") if isinstance(player.get("official"), dict) else {}
    matches = [
        row for row in (official.get("matches") or [])
        if isinstance(row, dict) and row.get("team_key") in visible_keys
    ]
    wins = sum(row.get("result") == "W" for row in matches)
    player["official"] = {
        "status": "bbc" if matches else "unavailable",
        "games": len(matches),
        "wins": wins,
        "winrate": round(wins / len(matches) * 100, 1) if matches else None,
        "matches": matches,
    }
    return player


def _pulled_ids(mapping):
    ids = set()
    for sid in mapping or []:
        try:
            ids.add(int(sid))
        except (TypeError, ValueError):
            continue
    return ids


def _same_league(row, league):
    if not league or not isinstance(row, dict):
        return True
    tagged = str(row.get("league") or "")
    if not tagged:
        return True
    return tagged.casefold() == str(league).casefold()


def _primary_league_view(payload):
    """Shared password sees the BBC league. Other leagues stay on their own sign-in."""
    league = str((payload.get("officialSource") or {}).get("league") or "")
    teams = [
        team for team in (payload.get("teams") or [])
        if isinstance(team, dict) and _same_league(team, league)
    ]
    kept_ids = set()
    other_ids = set()
    other_keys = set()
    for team in payload.get("teams") or []:
        if not isinstance(team, dict):
            continue
        ids = set(_team_player_ids(team))
        if _same_league(team, league):
            kept_ids.update(ids)
        else:
            other_ids.update(ids)
            if team.get("key"):
                other_keys.add(team["key"])
    only_other = other_ids - kept_ids
    players = []
    for player in payload.get("players") or []:
        if not isinstance(player, dict):
            players.append(player)
            continue
        try:
            pid = int(player.get("id"))
        except (TypeError, ValueError):
            players.append(player)
            continue
        if pid in only_other:
            continue
        players.append(player)

    def keep_row(row):
        return isinstance(row, dict) and _same_league(row, league)

    team_matches = []
    for row in payload.get("teamMatches") or []:
        if not isinstance(row, dict):
            continue
        radiant = row.get("radiant") if isinstance(row.get("radiant"), dict) else {}
        dire = row.get("dire") if isinstance(row.get("dire"), dict) else {}
        if radiant.get("team_key") in other_keys or dire.get("team_key") in other_keys:
            continue
        team_matches.append(row)
    out = dict(payload)
    out["teams"] = teams
    out["players"] = players
    out["standings"] = [row for row in (payload.get("standings") or []) if keep_row(row)]
    out["matchups"] = [row for row in (payload.get("matchups") or []) if keep_row(row)]
    out["teamMatches"] = team_matches
    return out


def view_for_account(payload, account, overrides=None, accounts=None):
    """Payload this sign-in is allowed to receive.

    An unlocked login gets the BBC league only. A locked login gets its own team,
    other teams in the same league (posted rosters only), and players those
    teams actually use. Another league's teams, private roster edits, and
    privately pulled players are left out.
    """
    payload = payload if isinstance(payload, dict) else {}
    account = account or _legacy_account("")
    overrides = overrides if isinstance(overrides, dict) else {}
    if not account.get("locked"):
        if account.get("admin"):
            return _admin_view(payload, account, overrides, accounts)
        out = _primary_league_view(payload)
        hidden = set()
        for other in accounts or []:
            if not other.get("locked"):
                continue
            bucket = (overrides.get("accounts") or {}).get(other.get("user")) or {}
            hidden.update(_pulled_ids(bucket.get("players")))
        if hidden:
            on_teams = set()
            for team in out.get("teams") or []:
                if isinstance(team, dict):
                    on_teams.update(_team_player_ids(team))
            kept = []
            for player in out.get("players") or []:
                if not isinstance(player, dict):
                    kept.append(player)
                    continue
                try:
                    pid = int(player.get("id"))
                except (TypeError, ValueError):
                    kept.append(player)
                    continue
                if pid in hidden and pid not in on_teams:
                    continue
                kept.append(player)
            out["players"] = kept
        out["account"] = _public_account(account)
        return out

    source_league = str((payload.get("officialSource") or {}).get("league") or "")
    own_key = team_key(account.get("team"))
    league_token = account.get("league") or ""
    names = _names_from(payload.get("players"))
    bucket = (overrides.get("accounts") or {}).get(account.get("user")) or {}

    visible = []
    own_team = None
    for team in payload.get("teams") or []:
        if not isinstance(team, dict):
            continue
        league_name = team.get("league") or source_league
        same_league = _league_hit(league_name, league_token)
        if team.get("key") == own_key and (not league_token or same_league):
            own_team = copy.deepcopy(team)
            continue
        if same_league:
            visible.append(_posted_team(team))

    roster_ids = _lookup_ids(bucket.get("rosters"), own_key)
    replaced_ids = _lookup_ids(bucket.get("replaced"), own_key)
    if own_team is None:
        own_team = {
            "key": own_key,
            "name": account.get("team") or "My Team",
            "short": account.get("team") or "My Team",
            "record": "",
            "captain": "",
            "postedRoster": [],
            "roster": [],
            "edited": False,
            "replacements": [],
            "replaced": [],
            "replacedPlayers": [],
            "league": account.get("league") or "",
        }
        if roster_ids is None:
            roster_ids = _lookup_ids(overrides.get("rosters"), own_key)
        if replaced_ids is None:
            replaced_ids = _lookup_ids(overrides.get("replaced"), own_key)
        _apply_private(own_team, roster_ids, replaced_ids, names)
    elif roster_ids is not None or replaced_ids is not None:
        baked_replaced = list(own_team.get("replaced") or [])
        own_team = _posted_team(own_team)
        _apply_private(
            own_team,
            roster_ids,
            replaced_ids if replaced_ids is not None else baked_replaced,
            names,
        )

    teams = [own_team] + visible
    visible_keys = {team.get("key") for team in teams if team.get("key")}
    needed = set()
    for team in teams:
        needed.update(_team_player_ids(team))
    needed.update(_pulled_ids(bucket.get("players")))
    if _league_hit(source_league, league_token):
        needed.update(_pulled_ids(overrides.get("players")))

    players = []
    for player in payload.get("players") or []:
        if not isinstance(player, dict):
            continue
        try:
            pid = int(player.get("id"))
        except (TypeError, ValueError):
            continue
        if pid in needed:
            players.append(_filter_player(player, visible_keys))

    def _both(row, left, right):
        return isinstance(row, dict) and row.get(left) in visible_keys and row.get(right) in visible_keys

    matchups = [
        row for row in (payload.get("matchups") or [])
        if _both(row, "aKey", "bKey")
    ]
    standings = [
        row for row in (payload.get("standings") or [])
        if isinstance(row, dict) and row.get("key") in visible_keys
    ]
    team_matches = []
    for row in payload.get("teamMatches") or []:
        if not isinstance(row, dict):
            continue
        radiant = row.get("radiant") if isinstance(row.get("radiant"), dict) else {}
        dire = row.get("dire") if isinstance(row.get("dire"), dict) else {}
        if radiant.get("team_key") in visible_keys and dire.get("team_key") in visible_keys:
            team_matches.append(copy.deepcopy(row))

    out = dict(payload)
    out["teams"] = teams
    out["players"] = players
    out["matchups"] = matchups
    out["standings"] = standings
    out["teamMatches"] = team_matches
    out["account"] = _public_account(account, own_key)
    return out


def _admin_view(payload, account, overrides, accounts):
    """Full league plus every locked sign-in's private team.

    Team passwords still cannot see each other. This view is only built for
    an admin sign-in (`username:password:*`).
    """
    out = dict(payload)
    teams = [copy.deepcopy(team) for team in (payload.get("teams") or []) if isinstance(team, dict)]
    by_key = {team.get("key"): index for index, team in enumerate(teams)}
    players = [player for player in (payload.get("players") or []) if isinstance(player, dict)]
    seen_players = set()
    for player in players:
        try:
            seen_players.add(int(player.get("id")))
        except (TypeError, ValueError):
            continue
    signins = []
    for other in accounts or []:
        if not other.get("locked"):
            continue
        private = view_for_account(payload, other, overrides)
        info = private.get("account") or {}
        own_key = info.get("teamKey")
        signins.append({
            "user": other.get("user") or "",
            "team": other.get("team"),
            "league": other.get("league"),
            "teamKey": own_key,
        })
        own = next(
            (team for team in (private.get("teams") or []) if team.get("key") == own_key),
            None,
        )
        if own is not None:
            own = copy.deepcopy(own)
            own["signin"] = other.get("user") or ""
            if own_key in by_key:
                teams[by_key[own_key]] = own
            else:
                by_key[own_key] = len(teams)
                teams.append(own)
        for player in private.get("players") or []:
            try:
                pid = int(player.get("id"))
            except (TypeError, ValueError):
                continue
            if pid not in seen_players:
                seen_players.add(pid)
                players.append(player)
    out["teams"] = teams
    out["players"] = players
    public = _public_account(account)
    public["signins"] = signins
    out["account"] = public
    return out


def _log_auth_failure(path, forwarded_for):
    # stdout is what the service wrapper tees into logs	eamscout.log.
    when = datetime.now(timezone.utc).isoformat()
    print(
        f"  ⚠ Team Scout auth failure {when} path={path} "
        f"from={forwarded_for or 'local'}",
        flush=True,
    )


def _make_handler(state, password_or_accounts):
    accounts = _coerce_accounts(password_or_accounts)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _challenge(self, log=True, delay=True):
            if delay:
                time.sleep(AUTH_FAIL_DELAY)
            if log:
                # X-Forwarded-For carries the real public IP when the request
                # came in through the funnel. Never log the attempted password.
                _log_auth_failure(self.path, self.headers.get("X-Forwarded-For"))
            body = b"Team Scout requires a password.\n"
            self.send_response(401)
            self.send_header(
                "WWW-Authenticate", f'Basic realm="{AUTH_REALM}", charset="UTF-8"'
            )
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authenticated(self):
            account = authenticate(self.headers.get("Authorization"), accounts)
            if account is not None:
                self.account = account
                return True
            self._challenge()
            return False

        def _view(self):
            payload, _page = state.snapshot()
            if payload is None:
                return None
            return view_for_account(payload, self.account, load_overrides(), accounts)

        def _send(self, code, content_type, body):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

        def _error(self, code, message):
            self._json(code, {"error": message})

        def _read_body(self):
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                length = 0
            if length <= 0:
                return {}
            if length > MAX_REQUEST_BODY:
                raise ValueError("request body too large")
            raw = self.rfile.read(length)
            data = json.loads(raw or b"{}")
            return data if isinstance(data, dict) else {}

        def do_GET(self):
            parts = urlsplit(self.path)
            path = parts.path
            if path == "/logout":
                self._challenge(log=False, delay=False)
                return
            if not self._authenticated():
                return
            if path in ("/", "/index.html"):
                view = self._view()
                if view is None:
                    self._error(503, "not ready yet")
                    return
                page = render_page(view).encode("utf-8")
                self._send(200, "text/html; charset=utf-8", page)
                return
            if path == "/api/search":
                query = parse_qs(parts.query).get("q", [""])[0]
                self._handle_search(query)
                return
            self.send_error(404)

        def _handle_search(self, query):
            query = str(query or "").strip()
            if not (2 <= len(query) <= 64):
                self._error(400, "q must be 2 to 64 characters")
                return
            view = self._view()
            if view is None:
                self._error(503, "not ready yet")
                return
            try:
                results = search_players(view, query)
            except Exception as exc:
                self._error(502, f"search failed: {exc}")
                return
            self._json(200, {"results": results})

        def do_POST(self):
            if not self._authenticated():
                return
            path = urlsplit(self.path).path
            try:
                body = self._read_body()
            except (ValueError, json.JSONDecodeError):
                self._error(400, "invalid request body")
                return
            if path == "/api/player":
                self._handle_pull_player(body)
            elif path == "/api/roster":
                self._handle_roster(body)
            else:
                self.send_error(404)

        def _handle_pull_player(self, body):
            raw_id = body.get("id")
            if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
                self._error(400, "id must be a positive integer")
                return
            try:
                record = pull_player_online(raw_id, account=self.account)
            except PlayerNotFound:
                self._error(404, "no OpenDota profile for that id")
                return
            except Exception as exc:
                self._error(502, f"could not pull player: {exc}")
                return
            self._json(200, {"player": record})
            state.rebuild_async()

        def _handle_roster(self, body):
            team_key_value = body.get("team")
            if not isinstance(team_key_value, str) or not team_key_value:
                self._error(400, "team is required")
                return
            view = self._view()
            if view is None:
                self._error(503, "not ready yet")
                return
            account_info = view.get("account") or {}
            if account_info.get("locked") and team_key_value != account_info.get("teamKey"):
                self._error(403, "this sign-in can only edit its own team")
                return
            old_team = next(
                (t for t in (view.get("teams") or []) if t.get("key") == team_key_value),
                None,
            )
            if old_team is None:
                self._error(404, "unknown team")
                return
            overrides = load_overrides()
            owner = old_team.get("signin") if account_info.get("admin") else None
            bucket = _account_bucket(
                overrides,
                {"user": owner, "locked": True} if owner else self.account,
            )
            roster_changed = False
            replaced_changed = False
            if body.get("reset"):
                bucket["rosters"].pop(team_key_value, None)
                new_roster, edited = list(old_team.get("postedRoster") or []), False
                roster_changed = True
            elif "roster" in body:
                ok, result = _validate_roster(body.get("roster"))
                if not ok:
                    self._error(400, result)
                    return
                bucket["rosters"][team_key_value] = result
                new_roster, edited = result, True
                roster_changed = True
            else:
                new_roster = list(old_team.get("roster") or [])
                edited = bool(old_team.get("edited"))
            if body.get("resetReplaced"):
                bucket.setdefault("replaced", {}).pop(team_key_value, None)
                replaced_ids = []
                replaced_changed = True
            elif "replaced" in body:
                ok, result = _validate_id_list(body.get("replaced"), "replaced", 20)
                if not ok:
                    self._error(400, result)
                    return
                bucket.setdefault("replaced", {})[team_key_value] = result
                replaced_ids = result
                replaced_changed = True
            else:
                replaced_ids = _int_ids(old_team.get("replaced"))
            if not roster_changed and not replaced_changed:
                self._error(400, "roster or replaced is required")
                return
            save_overrides(overrides)
            self._json(200, {"team": _team_after_roster_change(
                old_team, new_roster, edited, replaced_ids
            )})
            state.rebuild_async()

    return Handler


class _TeamScoutServer(ThreadingHTTPServer):
    # allow_reuse_address defaults to True, which on Windows lets a second Team
    # Scout silently co-bind 127.0.0.1:8324 while the first is still alive, so the
    # OSError guard below never fires and the bookmark hits either process.
    # Same loud-failure policy as mockdraft/herodraft.
    allow_reuse_address = False


def run_team_scout(season, port=None, offline=False, open_browser=True,
                   auto_refresh=False):
    # Fail closed: no password, no server. This app is funnel-exposed, so falling
    # back to serving unauthenticated would silently publish the roster endpoints.
    accounts = load_teamscout_accounts()
    if not accounts:
        print(f"  ✗ No Team Scout password. Put one in {AUTH_FILE} at the repo")
        print("    root (or set $TEAMSCOUT_PASSWORD). Team Scout will not start without it.")
        raise SystemExit(1)
    state = TeamScoutState(season, offline=offline)
    try:
        state.build_sync()
    except RuntimeError:
        print("  ✗ No cached player pool. Run the scout once first.")
        raise SystemExit(1)
    payload, _ = state.snapshot()
    port = port or config.TEAMSCOUT_PORT
    try:
        server = _TeamScoutServer(("127.0.0.1", port), _make_handler(state, accounts))
    except OSError as error:
        print(f"  ✗ Port {port} is already in use ({error}).")
        raise SystemExit(1) from error
    state.watch_bbc()
    if auto_refresh:
        state.auto_refresh()
    url = f"http://127.0.0.1:{port}/"
    print("\n" + "=" * 60)
    print("  TEAM SCOUT — mirrored roster intelligence")
    print(f"  {payload['season']} | {len(payload['players'])} players")
    week = (payload.get("officialSource") or {}).get("week")
    if week:
        print(f"  Week {week} | {len(payload.get('matchups') or [])} upcoming matchups")
    locked = [row for row in accounts if row.get("locked")]
    admins = [row["user"] for row in accounts if row.get("admin")]
    if locked or admins:
        parts = [f"{row['user']} → {row['team']}" for row in locked]
        if admins:
            parts.append("admin " + ", ".join(admins))
        print("  Sign-ins: " + ", ".join(parts))
    else:
        print("  Sign-in: one shared password")
    print(f"  App: {url}")
    print("  Ctrl+C to stop")
    print("=" * 60 + "\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Team Scout stopped.")
    finally:
        server.server_close()
