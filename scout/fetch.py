"""Cache-aware fetching of per-player OpenDota data."""

from . import config

# NOTE: leagueid is NOT in this list on purpose — the player-matches endpoint
# never populates it (league games are detected via lobby_type/game_mode instead).
MATCH_PROJECTION = [
    "average_rank", "party_size", "lane_role", "hero_id",
    "start_time", "player_slot", "radiant_win", "lobby_type", "game_mode",
]


def fetch_player_sections(od, cache, player, force=False):
    """Fetch (or reuse cached) raw data sections for one player.

    Returns (sections dict, api_calls_used).
    """
    sid = player["steam32"]
    calls_before = od.calls
    sections = {}

    def load(name, fetcher):
        data = cache.get_section(sid, name, config.TTL_HOURS[name], force=force)
        if data is None:
            data = fetcher()
            if data is not None:
                cache.set_section(sid, name, data)
        sections[name] = data

    load("profile", lambda: od.player(sid))
    load("wl", lambda: od.wl(sid))
    load("wl30", lambda: od.wl(sid, date=30))
    load("wl90", lambda: od.wl(sid, date=90))
    load("recent", lambda: od.recent_matches(sid))
    load("heroes", lambda: od.player_heroes(sid))
    load("matches", lambda: od.matches(
        sid,
        limit=config.MATCH_SAMPLE_LIMIT,
        date=config.MATCH_SAMPLE_DAYS,
        project=MATCH_PROJECTION,
    ))

    return sections, od.calls - calls_before


def signup_delta(cache, season_id, players):
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

    cache.set_blob(snap_name, {str(p["steam32"]): {"mmr": p["mmr"], "name": p["name"]}
                               for p in players})
    return new_players, mmr_changes
