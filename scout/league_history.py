"""Dotabuff-equivalent esports record, built from OpenDota alone.

Dotabuff cannot be scraped (Cloudflare blocks automated requests) and
OpenDota's Explorer excludes amateur leagues like LD2L entirely (tier
"excluded" leagues return zero rows). This module resolves the same
ticketed-match history a different way: pull every practice lobby a player
has ever queued into, resolve each one's leagueid one call at a time, and
once a league is discovered, pull its full match id list for free (that list
also covers amateur/excluded tiers). Resolution results are cached forever
(a match's league never changes); only a league's match id list is ever
refreshed, since a league can still be adding new weeks.
"""

import time
from collections import defaultdict

LOBBY_SECTION = "lobby_matches_v1"
INDEX_BLOB = "league_match_index_v1"

DETAIL_BUDGET = 250
LOBBY_TTL_HOURS = 24
LEAGUE_REFRESH_HOURS = 12
ACTIVE_LEAGUE_DAYS = 45

SIX_MONTH_SECONDS = 183 * 86400
MAX_RECENT_MATCHES = 60

BBC_LEAGUE_ID = 19389  # LD2L's OpenDota leagueid, used to seed the index for free

PROJECT_FIELDS = [
    "match_id", "start_time", "player_slot", "radiant_win", "hero_id",
    "kills", "deaths", "assists", "gold_per_min", "xp_per_min",
    "duration", "game_mode", "lane_role", "last_hits",
]

_INT_FIELDS = (
    "match_id", "start_time", "player_slot", "hero_id", "kills", "deaths",
    "assists", "gold_per_min", "xp_per_min", "duration", "game_mode",
    "lane_role", "last_hits",
)


def unavailable_history():
    """Stable shape used when no lobby-match section has ever been cached."""
    return {
        "status": "unavailable",
        "games": 0, "wins": 0, "winrate": None,
        "sixMonth": {"games": 0, "wins": 0, "winrate": None},
        "lobbyGames": 0,
        "unresolved": 0,
        "inhouse": 0,
        "leagues": [],
        "heroes": [],
        "matches": [],
    }


def _won(row):
    slot = row.get("player_slot")
    radiant_win = row.get("radiant_win")
    if slot is None or radiant_win is None:
        return None
    return (slot < 128) == radiant_win


def _summary(rows):
    decided = [(row, _won(row)) for row in rows]
    decided = [(row, won) for row, won in decided if won is not None]
    wins = sum(1 for _, won in decided if won)
    games = len(decided)
    return {
        "games": games,
        "wins": wins,
        "winrate": round(wins / games * 100, 1) if games else None,
    }


def _normalize_lobby_row(row):
    if not isinstance(row, dict):
        return None
    out = {field: row.get(field) for field in PROJECT_FIELDS}
    for field in _INT_FIELDS:
        value = out.get(field)
        if value is None:
            continue
        try:
            out[field] = int(value)
        except (TypeError, ValueError):
            out[field] = None
    if out.get("radiant_win") not in (True, False):
        out["radiant_win"] = None
    if out.get("match_id") is None or out.get("start_time") is None:
        return None
    return out


def _load_index(cache):
    blob = cache.get_blob(INDEX_BLOB)
    if not isinstance(blob, dict):
        return {"matches": {}, "leagues": {}}
    matches = blob.get("matches")
    leagues = blob.get("leagues")
    return {
        "matches": dict(matches) if isinstance(matches, dict) else {},
        "leagues": dict(leagues) if isinstance(leagues, dict) else {},
    }


def _save_index(cache, index):
    cache.set_blob(INDEX_BLOB, index)


def _refresh_lobby_matches(od, cache, sid):
    """Cached practice-lobby list for one player, refetched past its TTL."""
    rows = cache.get_section(sid, LOBBY_SECTION, LOBBY_TTL_HOURS)
    if rows is None:
        raw = od.matches(sid, lobby_type=1, significant=0, project=PROJECT_FIELDS)
        if not isinstance(raw, list):
            # A failed call is not "no lobbies": keep the last good list (any
            # age) and never cache the failure.
            stale = cache.get_section(sid, LOBBY_SECTION, None)
            return stale if isinstance(stale, list) else []
        normalized = [row for row in (
            _normalize_lobby_row(item) for item in (raw or [])
        ) if row]
        cache.set_section(sid, LOBBY_SECTION, normalized)
        rows = normalized
    return rows if isinstance(rows, list) else []


def _extract_match_ids(rows):
    """OpenDota's /leagues/{id}/matchIds can return bare ints or row objects."""
    out = []
    for row in rows or []:
        value = row.get("match_id") if isinstance(row, dict) else row
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def refresh_league_history(od, cache, steam32_ids, budget=DETAIL_BUDGET,
                            bbc_match_ids=None, rd2l_matches=None):
    """Online-only: resolve as many unknown lobby matches to a league as the
    call budget allows, print a one-line summary, and return it."""
    ids = sorted({int(sid) for sid in steam32_ids or []})
    index = _load_index(cache)
    matches_idx = index["matches"]
    leagues_idx = index["leagues"]

    calls_before = od.calls
    lobby_total = 0
    id_start = {}
    for sid in ids:
        rows = _refresh_lobby_matches(od, cache, sid)
        lobby_total += len(rows)
        for row in rows:
            mid = row.get("match_id")
            if mid is None:
                continue
            id_start[mid] = max(id_start.get(mid, 0), row.get("start_time") or 0)

    # Free seeds: full match payloads already cached elsewhere, plus BBC/RD2L
    # loaders the caller already ran (both carry a real leagueid for free).
    for mid in id_start:
        key = str(mid)
        if key in matches_idx:
            continue
        payload = cache.get_match(mid)
        if isinstance(payload, dict) and "leagueid" in payload:
            try:
                matches_idx[key] = int(payload.get("leagueid") or 0)
            except (TypeError, ValueError):
                pass
    for mid in (bbc_match_ids or []):
        try:
            matches_idx.setdefault(str(int(mid)), BBC_LEAGUE_ID)
        except (TypeError, ValueError):
            continue
    for mid, payload in (rd2l_matches or {}).items():
        if not isinstance(payload, dict):
            continue
        try:
            key = str(int(mid))
            matches_idx.setdefault(key, int(payload.get("leagueid") or 0))
        except (TypeError, ValueError):
            continue
    _save_index(cache, index)

    now = time.time()

    def expand(leagueid):
        """Name, tier and full match list for a league first seen this run."""
        info = od.league(leagueid)
        ids = od.league_match_ids(leagueid)
        if ids is None:
            return 0  # retry next run rather than record an empty league
        leagues_idx[str(leagueid)] = {
            "name": info.get("name") if isinstance(info, dict) else None,
            "tier": info.get("tier") if isinstance(info, dict) else None,
            "ids_fetched_at": now,
        }
        added = 0
        for eid in _extract_match_ids(ids):
            if str(eid) not in matches_idx:
                matches_idx[str(eid)] = leagueid
                added += 1
        _save_index(cache, index)
        return added

    # Leagues known only from a seed (BBC, RD2L, a cached match) have no name
    # or sibling list yet.
    seeded = {matches_idx.get(str(mid)) for mid in id_start}
    for lid in sorted(lid for lid in seeded if lid and str(lid) not in leagues_idx):
        expand(lid)

    # Refresh match-id lists for leagues still active, so a new week resolves
    # without spending detail-call budget on it.
    league_latest = defaultdict(int)
    for mid, start in id_start.items():
        lid = matches_idx.get(str(mid))
        if lid:
            league_latest[lid] = max(league_latest[lid], start)
    for league_key, info in list(leagues_idx.items()):
        try:
            lid = int(league_key)
        except (TypeError, ValueError):
            continue
        if league_latest.get(lid, 0) < now - ACTIVE_LEAGUE_DAYS * 86400:
            continue
        if now - (info.get("ids_fetched_at") or 0) < LEAGUE_REFRESH_HOURS * 3600:
            continue
        expanded = _extract_match_ids(od.league_match_ids(lid))
        changed = False
        for eid in expanded:
            if matches_idx.get(str(eid)) != lid:
                matches_idx[str(eid)] = lid
                changed = True
        info["ids_fetched_at"] = now
        leagues_idx[league_key] = info
        if changed:
            _save_index(cache, index)

    # Resolve the rest one detail call at a time, newest match first.
    queue = sorted(
        (mid for mid in id_start if str(mid) not in matches_idx),
        key=lambda mid: -id_start[mid],
    )
    resolved_count = 0
    budget_left = budget
    while queue and budget_left > 0:
        mid = queue.pop(0)
        if str(mid) in matches_idx:
            continue
        payload = od.match(mid)
        budget_left -= 1
        if not isinstance(payload, dict):
            continue  # unresolved: never guess, leave it for next run
        try:
            leagueid = int(payload.get("leagueid") or 0)
        except (TypeError, ValueError):
            leagueid = 0
        matches_idx[str(mid)] = leagueid
        resolved_count += 1
        if leagueid > 0 and str(leagueid) not in leagues_idx:
            resolved_count += expand(leagueid)
            queue = [m for m in queue if str(m) not in matches_idx]

    _save_index(cache, index)

    ticketed = sum(1 for mid in id_start if matches_idx.get(str(mid), 0))
    unresolved_remaining = sum(1 for mid in id_start if str(mid) not in matches_idx)
    calls_used = od.calls - calls_before
    summary = (
        f"League history: {len(ids)} players, {lobby_total} lobby games, "
        f"{resolved_count} resolved, {ticketed} ticketed, "
        f"{unresolved_remaining} unresolved, {calls_used} calls"
    )
    print(f"  {summary}", flush=True)
    return summary


def league_history_for(cache, steam32, hero_map, now=None):
    """Offline aggregation from whatever is already cached for this player."""
    rows = cache.get_section(steam32, LOBBY_SECTION, None)
    if rows is None:
        return unavailable_history()
    now = int(now if now is not None else time.time())

    index = _load_index(cache)
    matches_idx = index["matches"]
    leagues_idx = index["leagues"]

    resolved = []
    unresolved = 0
    inhouse = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("match_id")
        if mid is None:
            continue
        key = str(mid)
        if key not in matches_idx:
            unresolved += 1
            continue
        leagueid = matches_idx[key]
        if not leagueid:
            inhouse += 1
            continue
        resolved.append((row, leagueid))
    resolved.sort(key=lambda pair: pair[0].get("start_time") or 0, reverse=True)

    overall = _summary([row for row, _ in resolved])
    six_month_rows = [
        row for row, _ in resolved
        if (row.get("start_time") or 0) >= now - SIX_MONTH_SECONDS
    ]
    six_month = _summary(six_month_rows)

    league_groups = defaultdict(list)
    for row, leagueid in resolved:
        league_groups[leagueid].append(row)
    leagues_out = []
    for leagueid, entries in league_groups.items():
        starts = [entry.get("start_time") or 0 for entry in entries]
        summary = _summary(entries)
        info = leagues_idx.get(str(leagueid)) or {}
        leagues_out.append({
            "id": leagueid,
            "name": info.get("name") or f"League {leagueid}",
            "tier": info.get("tier"),
            "games": summary["games"],
            "wins": summary["wins"],
            "first": min(starts) if starts else None,
            "latest": max(starts) if starts else None,
        })
    leagues_out.sort(key=lambda row: row["latest"] or 0, reverse=True)

    hero_groups = defaultdict(lambda: {"games": 0, "wins": 0})
    for row, _ in resolved:
        hero_id = row.get("hero_id")
        if not hero_id:
            continue
        bucket = hero_groups[hero_id]
        bucket["games"] += 1
        if _won(row):
            bucket["wins"] += 1
    heroes_out = sorted(
        ({"id": hid, **stats} for hid, stats in hero_groups.items()),
        key=lambda row: -row["games"],
    )

    matches_out = []
    for row, leagueid in resolved[:MAX_RECENT_MATCHES]:
        matches_out.append({
            "id": row.get("match_id"),
            "at": row.get("start_time"),
            "hero": row.get("hero_id"),
            "win": _won(row),
            "kills": row.get("kills"),
            "deaths": row.get("deaths"),
            "assists": row.get("assists"),
            "gpm": row.get("gold_per_min"),
            "xpm": row.get("xp_per_min"),
            "duration": row.get("duration"),
            "league": leagueid,
        })

    return {
        "status": "ok",
        "games": overall["games"],
        "wins": overall["wins"],
        "winrate": overall["winrate"],
        "sixMonth": six_month,
        "lobbyGames": len(rows),
        "unresolved": unresolved,
        "inhouse": inhouse,
        "leagues": leagues_out,
        "heroes": heroes_out,
        "matches": matches_out,
    }
