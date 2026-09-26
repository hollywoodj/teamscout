"""Read-only adapter for the BBC show's current LD2L feed and match cache.

The BBC directory already owns season access and the expensive full-match
downloads. Team Scout deliberately reads those artifacts without importing the
show runtime or loading its credentials.
"""

import json
import os
import re

from . import config


def default_bbc_dir():
    configured = os.environ.get("BBC_DIR", "").strip()
    if configured:
        return configured
    return os.path.abspath(os.path.join(os.getcwd(), "..", "BBC"))


def _json(path, fallback):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError):
        return fallback


def team_key(name):
    """Normalize a team name for equality: casefold, drop a leading "the ",
    then strip everything that isn't a letter or digit.

    This makes "The Mad King's Gambit" (straight or curly apostrophe) and
    "roaring Arya" / "Roaring Arya" compare equal, and lets a name used
    without its article (OpenDota's radiant_name/dire_name sometimes drop it)
    still match the posted team name.
    """
    text = str(name or "").strip().casefold()
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


# Backwards-compatible internal alias; team_key supersedes the old _norm
# (same behaviour plus stripping a leading "the ").
_norm = team_key


def _steam32(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value >= config.STEAM64_OFFSET:
        value -= config.STEAM64_OFFSET
    return value if value >= 0 else None


# Public name; kept alongside _steam32 for the existing internal call sites.
to_steam32 = _steam32


def _ward_purchases(player):
    """Observers and sentries bought. OpenDota omits zeros on cores, so fall
    back to purchase{} / placed counts, then 0 when the match was parsed."""
    purchase = player.get("purchase") if isinstance(player.get("purchase"), dict) else {}
    obs = player.get("purchase_ward_observer")
    sen = player.get("purchase_ward_sentry")
    if obs is None:
        obs = purchase.get("ward_observer")
    if sen is None:
        sen = purchase.get("ward_sentry")
    if obs is None:
        obs = player.get("obs_placed")
        if obs is None:
            obs = player.get("observers_placed")
    if sen is None:
        sen = player.get("sen_placed")
    parsed = any(key in player for key in (
        "purchase", "obs_placed", "sen_placed", "observers_placed",
        "purchase_ward_observer", "purchase_ward_sentry",
    ))
    if parsed:
        obs = 0 if obs is None else obs
        sen = 0 if sen is None else sen
    return obs, sen


_WARD_KEY_RE = re.compile(r"\[(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\]")


def _ward_points(log):
    """Compact [x, y] or [x, y, t] placements from an OpenDota obs_log /
    sen_log. The third element, when present, is the log entry's integer
    `time` in seconds on the game clock (negative = pre-horn); it is left
    off when the entry has no time. Existing consumers only ever index
    [0]/[1], so the extra element is additive."""
    out = []
    if not isinstance(log, list):
        return out
    for entry in log:
        if not isinstance(entry, dict):
            continue
        x, y = entry.get("x"), entry.get("y")
        if x is None or y is None:
            match = _WARD_KEY_RE.search(str(entry.get("key") or ""))
            if not match:
                continue
            x, y = float(match.group(1)), float(match.group(2))
        try:
            point = [round(float(x), 1), round(float(y), 1)]
        except (TypeError, ValueError):
            continue
        t = entry.get("time")
        if t is not None:
            try:
                point.append(int(t))
            except (TypeError, ValueError):
                pass
        out.append(point)
    return out


def _won(player, match):
    if player.get("isRadiant") in (True, False):
        radiant = player["isRadiant"]
    else:
        try:
            radiant = int(player.get("player_slot") or 0) < 128
        except (TypeError, ValueError):
            radiant = True
    return radiant == bool(match.get("radiant_win"))


def _hero_name(hero_map, player):
    try:
        return hero_map.name(int(player.get("hero_id")))
    except (TypeError, ValueError):
        return str(player.get("hero") or "Unknown")


def _parse_record(value):
    """Parse a "W - L" style record string. Returns (wins, losses) or (0, 0)
    when the value is missing or malformed."""
    match = re.match(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$", str(value or ""))
    if not match:
        return 0, 0
    try:
        wins, losses = int(match.group(1)), int(match.group(2))
    except (TypeError, ValueError):
        return 0, 0
    return max(wins, 0), max(losses, 0)


def _competition_ranks(values):
    """Standard competition ranking (ties share a rank, e.g. 1, 1, 3) on a
    list of comparable values, ranked descending."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0] * len(values)
    current_rank = 0
    previous = None
    for position, index in enumerate(order, start=1):
        value = values[index]
        if value != previous:
            current_rank = position
            previous = value
        ranks[index] = current_rank
    return ranks


def _build_standings(feed):
    rows = feed.get("standings")
    entries = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        name = str(row["name"])
        short = str(row.get("nameShort") or name)
        wins, losses = _parse_record(row.get("value"))
        entries.append({
            "name": name,
            "short": short,
            "wins": wins,
            "losses": losses,
            "record": str(row.get("value") or "") or f"{wins} - {losses}",
            "captain": str(row.get("captain") or ""),
            "key": team_key(name),
        })
    ranks = _competition_ranks([row["wins"] for row in entries])
    for row, rank in zip(entries, ranks):
        row["rank"] = rank
    return entries


def bbc_source_paths(root=None):
    """feed.json and the OpenDota match cache BBC already maintains."""
    root = root or default_bbc_dir()
    return (
        os.path.join(root, "Show Graphics", "feed.json"),
        os.path.join(root, "scrapers", ".od_match_cache.json"),
    )


def bbc_source_stamp(root=None):
    """Identity of the BBC artifacts Team Scout reads. Changes when either
    file is rewritten (new week, new official result)."""
    stamp = []
    for path in bbc_source_paths(root):
        try:
            info = os.stat(path)
            stamp.append((path, info.st_mtime_ns, info.st_size))
        except OSError:
            stamp.append((path, 0, 0))
    return tuple(stamp)


def _compact_matchups(feed):
    """This week's posted series, without embedding full roster blobs."""
    out = []
    for matchup in feed.get("upcoming") or []:
        if not isinstance(matchup, dict):
            continue
        a = str(matchup.get("a") or "").strip()
        b = str(matchup.get("b") or "").strip()
        if not a or not b:
            continue
        out.append({
            "a": a,
            "aShort": str(matchup.get("aShort") or a),
            "aCaptain": str(matchup.get("ac") or ""),
            "aKey": team_key(a),
            "b": b,
            "bShort": str(matchup.get("bShort") or b),
            "bCaptain": str(matchup.get("bc") or ""),
            "bKey": team_key(b),
            "week": matchup.get("week"),
            "label": str(matchup.get("label") or ""),
            "matchId": matchup.get("matchId"),
        })
    return out


def index_official_matches(raw_matches, teams, hero_map, league_name,
                           name_to_id=None, extra_names=None):
    """Turn OpenDota match payloads into official rows, team games, and
    compact team matches.

    `teams` supplies posted rosters (`key`, `name`, `short`, `roster`). A side
    matches a team by name, then by roster overlap of at least three players.
    `extra_names` are additional name/short aliases (standings) with no roster.
    """
    teams = [row for row in (teams or []) if isinstance(row, dict) and row.get("key")]
    name_to_id = name_to_id or {}
    alias_to_key = {}

    def register(name, short):
        if not name:
            return
        canonical = team_key(name)
        if not canonical:
            return
        alias_to_key[canonical] = canonical
        if short:
            short_key = team_key(short)
            if short_key:
                alias_to_key.setdefault(short_key, canonical)

    for row in teams:
        register(row.get("name"), row.get("short"))
    for row in extra_names or []:
        if isinstance(row, dict):
            register(row.get("name"), row.get("short"))

    rosters = {}
    for row in teams:
        ids = set()
        for sid in row.get("roster") or []:
            sid = _steam32(sid)
            if sid is not None:
                ids.add(sid)
        rosters[row["key"]] = ids

    def resolve_side(name, ids):
        key = team_key(name)
        if key in alias_to_key:
            return alias_to_key[key]
        best_key, best_overlap = None, 0
        for team_key_name, roster in rosters.items():
            overlap = len(roster & ids)
            if overlap > best_overlap:
                best_overlap, best_key = overlap, team_key_name
        return best_key if best_overlap >= 3 else None

    def resolve_player_id(player):
        sid = _steam32(player.get("account_id"))
        if sid is None:
            sid = name_to_id.get(team_key(player.get("name") or player.get("personaname")))
        return sid

    def side_is_radiant(player):
        if player.get("isRadiant") in (True, False):
            return bool(player["isRadiant"])
        try:
            return int(player.get("player_slot") or 0) < 128
        except (TypeError, ValueError):
            return True

    if isinstance(raw_matches, dict):
        payloads = list(raw_matches.values())
    elif isinstance(raw_matches, list):
        payloads = raw_matches
    else:
        payloads = []

    official = {}
    team_matches = []
    team_games = {}
    league_name = str(league_name or "official")
    for raw in payloads:
        if not isinstance(raw, dict) or not isinstance(raw.get("players"), list):
            continue
        match_id = int(raw.get("match_id") or 0)
        start_time = int(raw.get("start_time") or 0)
        duration = int(raw.get("duration") or 0)
        radiant_win = bool(raw.get("radiant_win"))
        radiant_name = str(raw.get("radiant_name") or "Radiant")
        dire_name = str(raw.get("dire_name") or "Dire")
        patch = raw.get("patch")
        series_id = raw.get("series_id")

        radiant_rows = [p for p in raw["players"]
                        if isinstance(p, dict) and side_is_radiant(p)]
        dire_rows = [p for p in raw["players"]
                     if isinstance(p, dict) and not side_is_radiant(p)]
        radiant_rows.sort(key=lambda p: p.get("player_slot") or 0)
        dire_rows.sort(key=lambda p: p.get("player_slot") or 0)

        radiant_ids = {sid for sid in (resolve_player_id(p) for p in radiant_rows) if sid is not None}
        dire_ids = {sid for sid in (resolve_player_id(p) for p in dire_rows) if sid is not None}
        radiant_key = resolve_side(radiant_name, radiant_ids)
        dire_key = resolve_side(dire_name, dire_ids)

        for key, ids in ((radiant_key, radiant_ids), (dire_key, dire_ids)):
            if not key:
                continue
            bucket = team_games.setdefault(key, {})
            for sid in ids:
                bucket[sid] = bucket.get(sid, 0) + 1

        picks_bans = []
        for entry in raw.get("picks_bans") or []:
            if not isinstance(entry, dict):
                continue
            try:
                hero_id = int(entry.get("hero_id"))
            except (TypeError, ValueError):
                continue
            picks_bans.append({
                "hero_id": hero_id,
                "is_pick": bool(entry.get("is_pick")),
                "team": 1 if entry.get("team") == 1 else 0,
                "order": entry.get("order"),
            })

        def compact_side(rows):
            out = []
            for player in rows:
                sid = resolve_player_id(player)
                obs, sen = _ward_purchases(player)
                out.append({
                    "id": sid,
                    "name": str(player.get("name") or player.get("personaname") or "Unknown"),
                    "hero_id": player.get("hero_id"),
                    "kills": player.get("kills"),
                    "deaths": player.get("deaths"),
                    "assists": player.get("assists"),
                    "gpm": player.get("gold_per_min"),
                    "xpm": player.get("xp_per_min"),
                    "net_worth": player.get("net_worth"),
                    "last_hits": player.get("last_hits"),
                    "denies": player.get("denies"),
                    "lane_eff": player.get("lane_efficiency_pct"),
                    "obs": obs,
                    "sen": sen,
                    "obs_map": _ward_points(player.get("obs_log")),
                    "sen_map": _ward_points(player.get("sen_log")),
                    "teamfight": player.get("teamfight_participation"),
                    "obs_placed": player.get("obs_placed"),
                    "sen_placed": player.get("sen_placed"),
                    "obs_kills": player.get("observer_kills"),
                    "sen_kills": player.get("sentry_kills"),
                    "stuns": player.get("stuns"),
                    "camps_stacked": player.get("camps_stacked"),
                    "rune_pickups": player.get("rune_pickups"),
                    "towers_killed": player.get("towers_killed"),
                    "roshans_killed": player.get("roshans_killed"),
                    "buybacks": player.get("buyback_count"),
                    "firstblood": player.get("firstblood_claimed"),
                    "hero_damage": player.get("hero_damage"),
                })
            return out

        team_matches.append({
            "match_id": match_id,
            "start_time": start_time,
            "duration": duration,
            "series_id": series_id,
            "radiant": {"name": radiant_name, "team_key": radiant_key,
                        "players": compact_side(radiant_rows)},
            "dire": {"name": dire_name, "team_key": dire_key,
                     "players": compact_side(dire_rows)},
            "radiant_win": radiant_win,
            "picks_bans": picks_bans,
            "patch": patch,
            "radiant_score": raw.get("radiant_score"),
            "dire_score": raw.get("dire_score"),
            "first_blood_time": raw.get("first_blood_time"),
        })

        for player in raw["players"]:
            if not isinstance(player, dict):
                continue
            sid = resolve_player_id(player)
            if sid is None:
                continue
            radiant = side_is_radiant(player)
            team_name = radiant_name if radiant else dire_name
            opponent = dire_name if radiant else radiant_name
            resolved_key = radiant_key if radiant else dire_key
            opponent_key = dire_key if radiant else radiant_key
            obs, sen = _ward_purchases(player)
            official.setdefault(sid, []).append({
                "match_id": match_id,
                "start_time": start_time,
                "league_name": league_name,
                "patch": patch,
                "team": team_name,
                "opponent": opponent,
                "opponent_key": opponent_key,
                "team_key": resolved_key,
                "player_name": str(player.get("name") or player.get("personaname") or ""),
                "hero_id": player.get("hero_id"),
                "hero": _hero_name(hero_map, player),
                "result": "W" if _won(player, raw) else "L",
                "kills": player.get("kills"),
                "deaths": player.get("deaths"),
                "assists": player.get("assists"),
                "gpm": player.get("gold_per_min"),
                "xpm": player.get("xp_per_min"),
                "last_hits": player.get("last_hits"),
                "denies": player.get("denies"),
                "net_worth": player.get("net_worth"),
                "hero_damage": player.get("hero_damage"),
                "tower_damage": player.get("tower_damage"),
                "healing": player.get("hero_healing"),
                "lane_eff": player.get("lane_efficiency_pct"),
                "lane_role": player.get("lane_role"),
                "is_roaming": player.get("is_roaming"),
                "is_radiant": radiant,
                "observer_wards": obs,
                "sentry_wards": sen,
                "obs_map": _ward_points(player.get("obs_log")),
                "sen_map": _ward_points(player.get("sen_log")),
                "dewards": ((player.get("observer_kills") or 0)
                             + (player.get("sentry_kills") or 0)),
                "duration": duration,
                "teamfight": player.get("teamfight_participation"),
                "obs_placed": player.get("obs_placed"),
                "sen_placed": player.get("sen_placed"),
                "obs_kills": player.get("observer_kills"),
                "sen_kills": player.get("sentry_kills"),
                "stuns": player.get("stuns"),
                "camps_stacked": player.get("camps_stacked"),
                "rune_pickups": player.get("rune_pickups"),
                "towers_killed": player.get("towers_killed"),
                "roshans_killed": player.get("roshans_killed"),
                "buybacks": player.get("buyback_count"),
                "firstblood": player.get("firstblood_claimed"),
            })

    for rows in official.values():
        rows.sort(key=lambda row: row["start_time"], reverse=True)
    team_matches.sort(key=lambda row: row["start_time"], reverse=True)
    return official, team_matches, team_games


def load_bbc_data(hero_map, root=None):
    """Return current teams, standings, official match rows, and per-team
    official-match history by Steam32 id."""
    root = root or default_bbc_dir()
    feed_path, cache_path = bbc_source_paths(root)
    feed = _json(feed_path, {})
    raw_matches = _json(cache_path, {})

    standings_rows = _build_standings(feed)

    teams_by_name = {}
    name_to_id = {}
    roster_players = {}
    for matchup in feed.get("upcoming", []):
        if not isinstance(matchup, dict):
            continue
        for side in ("a", "b"):
            name = str(matchup.get(side) or "").strip()
            roster = (matchup.get("rosters") or {}).get(side) or []
            ids = []
            for player in roster:
                sid = _steam32(player.get("id")) if isinstance(player, dict) else None
                if sid is None:
                    continue
                ids.append(sid)
                name_to_id[team_key(player.get("name"))] = sid
                roster_players[sid] = {
                    "name": str(player.get("name") or sid),
                    "rank_tier": player.get("medal"),
                }
            if not name or not ids:
                continue
            key = team_key(name)
            standing = next((row for row in standings_rows if row["key"] == key), {})
            teams_by_name[key] = {
                "key": key,
                "name": name,
                "short": str(matchup.get(side + "Short") or name),
                "record": standing.get("record") or "",
                "captain": str(matchup.get(side + "c") or ""),
                "roster": ids[:5],
            }

    league_name = str(feed.get("league") or "LD2L official")
    official, team_matches, team_games = index_official_matches(
        raw_matches,
        list(teams_by_name.values()),
        hero_map,
        league_name,
        name_to_id,
        standings_rows,
    )
    teams = sorted(teams_by_name.values(), key=lambda row: row["name"].casefold())
    return {
        "available": bool(feed),
        "league": str(feed.get("league") or ""),
        "generated": feed.get("generated"),
        "week": feed.get("week"),
        "teams": teams,
        "matchups": _compact_matchups(feed),
        "standings": standings_rows,
        "players": roster_players,
        "official": official,
        "teamMatches": team_matches,
        "team_games": team_games,
    }
