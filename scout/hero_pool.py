"""Pub hero analysis and hidden-gem detection. Pure functions, no I/O."""

import time
from collections import Counter, defaultdict

PUB_WINDOW_DAYS = 180
GEM_MAX_RESULTS = 6
GEM_MIN_COMBINED_GAMES = 6
GEM_MAX_OFFICIAL_GAMES = 1
GEM_MIN_SCORE_FLOOR = 0.53
GEM_SCORE_MARGIN = 0.03
GEM_MIN_KDA_DELTA = -0.2
COMFORT_TOP_N = 5


def _kda(rows):
    if not rows:
        return None
    kills = sum(row.get("kills") or 0 for row in rows)
    deaths = sum(row.get("deaths") or 0 for row in rows)
    assists = sum(row.get("assists") or 0 for row in rows)
    return (kills + assists) / max(deaths, 1)


def _summary_rows(rows):
    games = len(rows)
    wins = sum(1 for row in rows if row.get("win"))
    return {
        "games": games,
        "wins": wins,
        "winrate": round(wins / games * 100, 1) if games else None,
        "kda": _kda(rows),
    }


def _gem_reason(record, position):
    lifetime, recent = record["lifetime"], record["recent"]
    official, esports = record["official"], record["esports"]
    lead = []
    if recent["games"]:
        lead.append(
            f"{recent['wins']}-{recent['games'] - recent['wins']} in pubs "
            "over the last 6 months"
        )
        if recent.get("kdaDelta") is not None:
            sign = "+" if recent["kdaDelta"] >= 0 else ""
            pos_txt = f" at P{position}" if position else ""
            lead.append(
                f"KDA {sign}{recent['kdaDelta']:.1f} over their norm{pos_txt}"
            )
    rest = []
    if lifetime["games"]:
        life = f"{lifetime['wins']}-{lifetime['games'] - lifetime['wins']} lifetime"
        if not recent["games"] and lifetime.get("last"):
            life += f" (last played {time.strftime('%b %Y', time.gmtime(lifetime['last']))})"
        rest.append(life)
    if official["games"] == 0:
        rest.append("never picked in officials")
    else:
        rest.append(f"{official['wins']}-{official['games'] - official['wins']} in officials")
    if esports["games"]:
        rest.append(f"{esports['wins']}-{esports['games'] - esports['wins']} in esports")
    segments = ([", ".join(lead)] if lead else []) + rest
    reason = "; ".join(segments)
    return f"{reason}." if reason else "Clears the bar on limited data."


def build_hero_pool(record_heroes, pub_rows, official_rows, esports_heroes,
                     meta=None, now=None, player_lifetime=None):
    """Combine lifetime, recent-pub, official, and esports hero records.

    `record_heroes` is the player's lifetime OpenDota hero list. `pub_rows`
    are compact match rows already filtered to real pubs (any lobby/game_mode
    filtering is the caller's job); this function applies the 180-day window
    itself. `official_rows` are BBC official rows (hero_id, result). `meta` is
    the optional {hero_id_str: {"g":,"w":}} pub meta blob.
    """
    now = now if now is not None else time.time()
    floor = now - PUB_WINDOW_DAYS * 86400
    recent_rows = [
        row for row in (pub_rows or [])
        if isinstance(row, dict) and (row.get("at") or 0) >= floor
    ]
    baseline = _summary_rows(recent_rows)

    lifetime_by_id = {}
    for row in record_heroes or []:
        try:
            hero_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        lifetime_by_id[hero_id] = row

    recent_by_id = defaultdict(list)
    for row in recent_rows:
        hero_id = row.get("hero")
        if hero_id:
            recent_by_id[hero_id].append(row)

    official_by_id = defaultdict(lambda: {"games": 0, "wins": 0})
    for row in official_rows or []:
        if not isinstance(row, dict):
            continue
        hero_id = row.get("hero_id")
        if not hero_id:
            continue
        bucket = official_by_id[hero_id]
        bucket["games"] += 1
        if row.get("result") == "W":
            bucket["wins"] += 1

    esports_by_id = {}
    for row in esports_heroes or []:
        try:
            hero_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        esports_by_id[hero_id] = {
            "games": int(row.get("games") or 0), "wins": int(row.get("wins") or 0),
        }

    meta = meta or {}
    position_rows = defaultdict(list)
    for row in recent_rows:
        pos = row.get("position")
        if pos:
            position_rows[pos].append(row)
    position_kda = {pos: _kda(rows) for pos, rows in position_rows.items()}

    all_ids = set(lifetime_by_id) | set(recent_by_id) | set(official_by_id) | set(esports_by_id)
    records = []
    for hero_id in all_ids:
        lifetime_row = lifetime_by_id.get(hero_id)
        lifetime_games = int(lifetime_row.get("games") or 0) if lifetime_row else 0
        lifetime_wins = int(lifetime_row.get("wins") or 0) if lifetime_row else 0
        lifetime_last = int(lifetime_row.get("last") or 0) if lifetime_row else 0

        rows = recent_by_id.get(hero_id, [])
        recent_games = len(rows)
        recent_wins = sum(1 for row in rows if row.get("win"))
        recent_kda = _kda(rows) if rows else None
        gpm_values = [row.get("gpm") for row in rows if isinstance(row.get("gpm"), (int, float))]
        recent_gpm = sum(gpm_values) / len(gpm_values) if gpm_values else None

        position = None
        counts = Counter(row.get("position") for row in rows if row.get("position"))
        if counts:
            position = counts.most_common(1)[0][0]
        elif lifetime_row:
            position = lifetime_row.get("primaryPosition")

        kda_delta = None
        if recent_games >= 3 and recent_kda is not None:
            base_kda = position_kda.get(position)
            if base_kda is None:
                base_kda = baseline["kda"]
            if base_kda is not None:
                kda_delta = round(recent_kda - base_kda, 3)

        official = dict(official_by_id.get(hero_id, {"games": 0, "wins": 0}))
        esports = dict(esports_by_id.get(hero_id, {"games": 0, "wins": 0}))

        weighted_wins = lifetime_wins + 2 * recent_wins
        weighted_games = lifetime_games + 2 * recent_games
        score = round((weighted_wins + 5) / (weighted_games + 10), 4)

        stale = bool(lifetime_last) and (now - lifetime_last > 365 * 86400) and recent_games == 0
        league_proven = (
            (official["games"] >= 3 and official["wins"] / official["games"] >= 0.55)
            or (esports["games"] >= 5 and esports["wins"] / esports["games"] >= 0.55)
        )
        league_only = esports["games"] >= 3 and esports["games"] > lifetime_games * 0.5

        meta_row = meta.get(str(hero_id)) or meta.get(hero_id)
        meta_wr = None
        if isinstance(meta_row, dict) and meta_row.get("g"):
            meta_wr = round(meta_row["w"] / meta_row["g"] * 100, 1)

        records.append({
            "id": hero_id,
            "lifetime": {"games": lifetime_games, "wins": lifetime_wins, "last": lifetime_last},
            "recent": {
                "games": recent_games, "wins": recent_wins,
                "kda": round(recent_kda, 3) if recent_kda is not None else None,
                "gpm": round(recent_gpm, 1) if recent_gpm is not None else None,
                "kdaDelta": kda_delta,
            },
            "official": official,
            "esports": esports,
            "position": position,
            "score": score,
            "tags": [],
            "metaWr": meta_wr,
            "_weightedGames": weighted_games,
            "_stale": stale,
            "_leagueProven": league_proven,
            "_leagueOnly": league_only,
            "_combinedGames": lifetime_games + recent_games,
        })

    records.sort(key=lambda row: -row["_combinedGames"])
    comfort_ids = {row["id"] for row in records[:COMFORT_TOP_N]}
    for row in records:
        tags = []
        if row["id"] in comfort_ids:
            tags.append("comfort")
        if row["_leagueProven"]:
            tags.append("league-proven")
        if row["_leagueOnly"]:
            tags.append("league-only")
        if row["_stale"]:
            tags.append("stale")
        row["tags"] = tags

    if baseline["games"]:
        baseline_wr = baseline["winrate"] / 100
    elif player_lifetime and player_lifetime.get("games"):
        baseline_wr = player_lifetime["wins"] / player_lifetime["games"]
    else:
        baseline_wr = 0.5
    gem_floor = max(GEM_MIN_SCORE_FLOOR, baseline_wr + GEM_SCORE_MARGIN)

    candidates = []
    for row in records:
        if "comfort" in row["tags"] or "stale" in row["tags"]:
            continue
        if row["_combinedGames"] < GEM_MIN_COMBINED_GAMES:
            continue
        if row["official"]["games"] > GEM_MAX_OFFICIAL_GAMES:
            continue
        if row["score"] < gem_floor:
            continue
        delta = row["recent"]["kdaDelta"]
        if row["recent"]["games"] >= 3 and delta is not None and delta < GEM_MIN_KDA_DELTA:
            continue
        candidates.append(row)
    candidates.sort(
        key=lambda row: (row["score"] - 0.5) * row["_weightedGames"] / (row["_weightedGames"] + 10),
        reverse=True,
    )
    gem_ids = {row["id"] for row in candidates[:GEM_MAX_RESULTS]}
    for row in records:
        if row["id"] in gem_ids:
            row["tags"].append("gem")

    gems = []
    for row in candidates[:GEM_MAX_RESULTS]:
        reason = _gem_reason(row, row["position"])
        gems.append({
            key: value for key, value in row.items() if not key.startswith("_")
        } | {"reason": reason})

    for row in records:
        for key in ("_weightedGames", "_stale", "_leagueProven", "_leagueOnly", "_combinedGames"):
            row.pop(key, None)

    records.sort(key=lambda row: (-row["score"], -(row["lifetime"]["games"] + row["recent"]["games"])))
    kept_ids = {row["id"] for row in records[:60]} | comfort_ids | gem_ids
    heroes_out = [row for row in records if row["id"] in kept_ids]

    return {
        "heroes": heroes_out,
        "gems": gems,
        "baseline": {
            "games": baseline["games"], "wins": baseline["wins"],
            "winrate": baseline["winrate"],
            "kda": round(baseline["kda"], 3) if baseline["kda"] is not None else None,
        },
        "pubWindowDays": PUB_WINDOW_DAYS,
    }
