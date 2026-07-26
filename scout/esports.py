"""Verified OpenDota ticketed-match history.

OpenDota's regular player-match projection omits ``leagueid``. This module
uses one pool-wide Explorer query, then normalizes and aggregates the rows for
the dashboard and per-player reports.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone


RESULT_LIMIT = 10_000
RECENT_SECONDS = 183 * 86400
CACHE_HOURS = 24
CACHE_VERSION = 1

FIELDS = (
    "account_id",
    "match_id",
    "start_time",
    "leagueid",
    "league_name",
    "player_slot",
    "radiant_win",
    "hero_id",
    "kills",
    "deaths",
    "assists",
    "gold_per_min",
    "xp_per_min",
)


def build_query(player_ids, limit=RESULT_LIMIT):
    """Return the pool query, accepting only integer-like Steam32 IDs."""
    ids = sorted({int(value) for value in player_ids})
    if not ids:
        raise ValueError("ticketed history requires at least one player ID")
    joined = ",".join(str(value) for value in ids)
    return (
        "SELECT pm.account_id, pm.match_id, m.start_time, m.leagueid, "
        "l.name AS league_name, pm.player_slot, m.radiant_win, pm.hero_id, "
        "pm.kills, pm.deaths, pm.assists, pm.gold_per_min, pm.xp_per_min "
        "FROM player_matches pm "
        "JOIN matches m USING (match_id) "
        "LEFT JOIN leagues l ON l.leagueid = m.leagueid "
        f"WHERE pm.account_id IN ({joined}) AND m.leagueid > 0 "
        "ORDER BY m.start_time DESC "
        f"LIMIT {int(limit)}"
    )


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_row(row):
    if not isinstance(row, dict):
        return None
    out = {field: row.get(field) for field in FIELDS}
    for field in (
        "account_id",
        "match_id",
        "start_time",
        "leagueid",
        "player_slot",
        "hero_id",
        "kills",
        "deaths",
        "assists",
        "gold_per_min",
        "xp_per_min",
    ):
        out[field] = _int_or_none(out[field])
    if not all(
        out.get(field) is not None
        for field in ("account_id", "match_id", "start_time", "leagueid")
    ):
        return None
    if out["leagueid"] <= 0:
        return None
    if out["radiant_win"] not in (True, False):
        out["radiant_win"] = None
    out["league_name"] = str(out.get("league_name") or "").strip()
    return out


def _won(row):
    slot, radiant_win = row.get("player_slot"), row.get("radiant_win")
    if slot is None or radiant_win is None:
        return None
    return (slot < 128) == radiant_win


def unavailable_history():
    """Return the stable shape used when no cache or network data exists."""
    return {
        "status": "unavailable",
        "incomplete": False,
        "games": 0,
        "wins": 0,
        "losses": 0,
        "winrate": None,
        "league_count": 0,
        "first": None,
        "latest": None,
        "six_month": {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "winrate": None,
        },
        "leagues": [],
        "recent_matches": [],
        "recent_mode": "none",
    }


def _summary(rows):
    decided = [(row, _won(row)) for row in rows]
    decided = [(row, won) for row, won in decided if won is not None]
    wins = sum(1 for _, won in decided if won)
    losses = len(decided) - wins
    return {
        "games": len(decided),
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / len(decided) * 100, 1) if decided else None,
    }


def _match_record(row, hero_map):
    won = _won(row)
    return {
        "match_id": row["match_id"],
        "start_time": row["start_time"],
        "league_id": row["leagueid"],
        "league_name": row["league_name"] or f"League {row['leagueid']}",
        "hero": hero_map.name(row["hero_id"]) if row.get("hero_id") else "Unknown",
        "result": "W" if won is True else "L" if won is False else "?",
        "kills": row.get("kills"),
        "deaths": row.get("deaths"),
        "assists": row.get("assists"),
        "gpm": row.get("gold_per_min"),
        "xpm": row.get("xp_per_min"),
    }


def aggregate_histories(
    rows,
    player_ids,
    hero_map,
    now=None,
    status="fresh",
    incomplete=False,
):
    """Aggregate normalized ticketed rows into one stable record per player."""
    now = int(
        now
        if now is not None
        else datetime.now(tz=timezone.utc).timestamp()
    )
    ids = sorted({int(value) for value in player_ids})
    grouped = defaultdict(list)
    seen = set()
    for raw in rows or []:
        row = _normalize_row(raw)
        if row is None or row["account_id"] not in ids:
            continue
        key = (row["account_id"], row["match_id"])
        if key in seen:
            continue
        seen.add(key)
        grouped[row["account_id"]].append(row)

    result = {}
    for account_id in ids:
        player_rows = sorted(
            grouped[account_id],
            key=lambda row: row["start_time"],
            reverse=True,
        )
        career = _summary(player_rows)
        recent_rows = [
            row
            for row in player_rows
            if row["start_time"] >= now - RECENT_SECONDS
        ]
        six_month = _summary(recent_rows)
        league_rows = defaultdict(list)
        for row in player_rows:
            league_rows[row["leagueid"]].append(row)

        leagues = []
        for league_id, entries in league_rows.items():
            summary = _summary(entries)
            heroes = Counter(
                hero_map.name(row["hero_id"])
                for row in entries
                if row.get("hero_id")
            )
            leagues.append(
                {
                    "league_id": league_id,
                    "name": entries[0]["league_name"] or f"League {league_id}",
                    **summary,
                    "first": min(row["start_time"] for row in entries),
                    "latest": max(row["start_time"] for row in entries),
                    "heroes": [
                        {"name": name, "games": games}
                        for name, games in heroes.most_common(3)
                    ],
                }
            )
        leagues.sort(key=lambda league: league["latest"], reverse=True)

        if recent_rows:
            selected, mode = recent_rows, "six_months"
        elif leagues:
            league_ids = {league["league_id"] for league in leagues[:3]}
            selected = [
                row for row in player_rows if row["leagueid"] in league_ids
            ]
            mode = "latest_leagues"
        else:
            selected, mode = [], "none"

        result[account_id] = {
            "status": status,
            "incomplete": bool(incomplete),
            **career,
            "league_count": len(leagues),
            "first": min(
                (row["start_time"] for row in player_rows),
                default=None,
            ),
            "latest": max(
                (row["start_time"] for row in player_rows),
                default=None,
            ),
            "six_month": six_month,
            "leagues": leagues,
            "recent_matches": [
                _match_record(row, hero_map) for row in selected
            ],
            "recent_mode": mode,
        }
    return result


def _cache_name(season_id):
    return f"ticketed_history_s{int(season_id)}_v{CACHE_VERSION}"


def _valid_payload(payload):
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("player_ids"), list)
        and isinstance(payload.get("rows"), list)
    )


def _covered(payload, player_ids):
    if not _valid_payload(payload):
        return False
    try:
        cached_ids = {int(value) for value in payload.get("player_ids", [])}
    except (TypeError, ValueError):
        return False
    return set(player_ids).issubset(cached_ids)


def _from_payload(payload, player_ids, hero_map, status, now):
    requested = sorted({int(value) for value in player_ids})
    try:
        covered_ids = {
            int(value) for value in (payload or {}).get("player_ids", [])
        }
    except (TypeError, ValueError):
        covered_ids = set()
    available_ids = [value for value in requested if value in covered_ids]
    incomplete = bool((payload or {}).get("incomplete"))
    if incomplete:
        print(
            "Warning: OpenDota ticketed history reached the Explorer row "
            "limit; esports totals may be incomplete."
        )
    result = aggregate_histories(
        (payload or {}).get("rows", []),
        available_ids,
        hero_map,
        now=now,
        status=status,
        incomplete=incomplete,
    )
    for player_id in requested:
        result.setdefault(player_id, unavailable_history())
    return result


def load_ticketed_histories(
    od,
    cache,
    season_id,
    player_ids,
    hero_map,
    offline=False,
    force=False,
    now=None,
):
    """Load one cached or live Explorer result for the full player pool."""
    ids = sorted({int(value) for value in player_ids})
    if not ids:
        return {}
    name = _cache_name(season_id)
    fresh = None if force else cache.get_blob(name, CACHE_HOURS)
    if _covered(fresh, ids):
        return _from_payload(fresh, ids, hero_map, "fresh", now)

    stale = cache.get_blob(name)
    if offline:
        if _valid_payload(stale):
            return _from_payload(stale, ids, hero_map, "stale", now)
        return {player_id: unavailable_history() for player_id in ids}

    rows = od.explorer(build_query(ids))
    if rows is not None:
        payload = {
            "player_ids": ids,
            "rows": rows,
            "incomplete": len(rows) >= RESULT_LIMIT,
        }
        cache.set_blob(name, payload)
        return _from_payload(payload, ids, hero_map, "fresh", now)

    if _valid_payload(stale):
        print(
            "Warning: OpenDota Explorer was unavailable; using cached "
            "ticketed history."
        )
        return _from_payload(stale, ids, hero_map, "stale", now)
    return {player_id: unavailable_history() for player_id in ids}
