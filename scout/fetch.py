"""Cache-aware fetching of per-player OpenDota data."""

from . import config

# NOTE: leagueid is NOT in this list on purpose — the player-matches endpoint
# never populates it (league games are detected via lobby_type/game_mode instead).
# Per-match kills/deaths/assists/gpm/xpm let us profile performance over the
# full 200-game sample (per lane, vs lobby strength) instead of just the
# 20-game recentMatches window — same single API call.
MATCH_PROJECTION = [
    "average_rank", "party_size", "lane", "lane_role", "is_roaming",
    "lane_efficiency_pct", "version", "patch", "hero_id",
    "start_time", "player_slot", "radiant_win", "lobby_type", "game_mode",
    "kills", "deaths", "assists", "gold_per_min", "xp_per_min", "duration",
    "last_hits", "denies", "hero_damage", "tower_damage", "hero_healing",
    "teamfight_participation",
    "purchase_ward_observer", "purchase_ward_sentry",
    "cluster",  # server/region the match was played on
]

# Cache section name for the match sample. Bumped when the projection grows, so
# old caches refetch instead of silently missing fields (_v4 added parsed lane
# efficiency, roaming and ward-purchase fields).
MATCHES_SECTION = "matches_v5"
_MATCHES_FALLBACKS = ["matches_v4", "matches_v3", "matches_v2", "matches"]


def fetch_player_sections(od, cache, player, force=False, offline=False):
    """Fetch (or reuse cached) raw data sections for one player.

    offline=True never touches the network: cached data is used regardless of
    TTL (missing sections stay None).

    Returns (sections dict, api_calls_used).
    """
    sid = player["steam32"]
    calls_before = od.calls
    sections = {}

    def load(name, fetcher, cache_name=None):
        cache_name = cache_name or name
        max_age = None if offline else config.TTL_HOURS[name]
        data = cache.get_section(sid, cache_name, max_age, force=force and not offline)
        if data is None and not offline:
            data = fetcher()
            if data is not None:
                cache.set_section(sid, cache_name, data)
        sections[name] = data

    load("profile", lambda: od.player(sid))
    load("wl", lambda: od.wl(sid))
    load("wl30", lambda: od.wl(sid, date=30))
    load("wl90", lambda: od.wl(sid, date=90))
    load("recent", lambda: od.recent_matches(sid))
    load("heroes", lambda: od.player_heroes(sid))
    load("wordcloud", lambda: od.wordcloud(sid))
    load("matches", lambda: od.matches(
        sid,
        limit=config.MATCH_SAMPLE_LIMIT,
        date=config.MATCH_SAMPLE_DAYS,
        project=MATCH_PROJECTION,
    ), cache_name=MATCHES_SECTION)
    if offline and sections["matches"] is None:
        # fall back to an older sample rather than nothing (region needs a
        # re-fetch, but the rest still works from the prior projection)
        for name in _MATCHES_FALLBACKS:
            sections["matches"] = cache.get_section(sid, name, None)
            if sections["matches"] is not None:
                break

    return sections, od.calls - calls_before


def signup_delta(cache, season_id, players, season_label=None):
    """Mark new signups and MMR changes vs the previous run's snapshot.

    Mutates players (adds is_new / mmr_change) and returns (new, changed) lists.
    """
    snap_name = f"signups_s{season_id}"
    prev = cache.get_blob(snap_name) or {}
    new_players, mmr_changes = [], []

    for p in players:
        key = str(p["steam32"])
        old = prev.get(key)
        p["is_new"] = old is None and bool(prev)  # first ever run: nobody is "new"
        p["mmr_change"] = 0
        if old is None:
            if p["is_new"]:
                new_players.append(p)
        elif old.get("mmr") != p["mmr"]:
            p["mmr_change"] = p["mmr"] - old.get("mmr", 0)
            mmr_changes.append(p)

    # Full player dicts are snapshotted so --offline runs can rebuild the pool
    snap = {str(p["steam32"]): dict(p) for p in players}
    snap["_meta"] = {"label": season_label}
    cache.set_blob(snap_name, snap)
    return new_players, mmr_changes


def apply_mmr_baseline(cache, season_id, players):
    """Record each player's listed MMR the first time we see them, then hold it
    fixed. Sets player['signup_mmr'] so climb = current listed - signup listed.

    The baseline is immutable per player: it's what they were listed at when
    they first appeared in the signups, so later re-rates show up as a climb.
    """
    name = f"mmr_baseline_s{season_id}"
    base = cache.get_blob(name) or {}
    changed = False
    for p in players:
        key = str(p["steam32"])
        if key not in base:
            base[key] = p["mmr"]
            changed = True
        p["signup_mmr"] = base[key]
    if changed:
        cache.set_blob(name, base)
    return players


def players_from_snapshot(cache, season_id):
    """Rebuild (season_label, players) from the last run's snapshot (--offline)."""
    prev = cache.get_blob(f"signups_s{season_id}") or {}
    label = (prev.get("_meta") or {}).get("label")
    players = [dict(v) for v in prev.values() if isinstance(v, dict) and "steam32" in v]
    for p in players:
        p.setdefault("is_new", False)
        p.setdefault("mmr_change", 0)
    return label, players
