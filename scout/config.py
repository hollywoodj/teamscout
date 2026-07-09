"""Configuration for LD2L Scout."""

import os

# ---- LD2L site ----
LD2L_BASE = "https://ld2l.org"
DEFAULT_SEASON_ID = 53  # Season 22 (ld2l.org internal season id)
STEAM64_OFFSET = 76561197960265728  # Steam64 - this = Steam32

# ---- OpenDota API ----
API_BASE = "https://api.opendota.com/api"
API_KEY = os.environ.get("OPENDOTA_API_KEY", "").strip()
# Free tier: 60 calls/min and a daily cap. Keyed tier allows much more.
API_DELAY = 0.3 if API_KEY else 1.1  # seconds between calls
API_MAX_RETRIES = 3
DAILY_CALL_WARNING = 1800  # warn when a single run uses this many calls

# ---- Caching ----
CACHE_DIR = "cache"
# Freshness TTLs in hours, per cached section
TTL_HOURS = {
    "profile": 24,   # rank_tier changes slowly
    "wl": 24,        # lifetime W/L
    "wl30": 24,      # last-30-days W/L
    "wl90": 24,      # last-90-days W/L
    "recent": 2,     # activity + recent KDA -> keep fresh each loop
    "heroes": 24,    # lifetime hero stats
    "matches": 24,   # 200-match sample (lobby rank / lanes / league)
}
HEROES_CONSTANTS_TTL_HOURS = 24 * 7

# ---- Analysis thresholds ----
SIGNATURE_MIN_GAMES = 100
SIGNATURE_MIN_WINRATE = 53.0
INACTIVE_DAYS = 90
MATCH_SAMPLE_LIMIT = 200
MATCH_SAMPLE_DAYS = 180
# "Punches above": median lobby rank this many stars above own medal (1 star ~ 150 MMR)
PUNCH_STAR_GAP = 3
# MMR sanity check: flag when medal-implied MMR differs from listed MMR by this much
MMR_CHECK_GAP = 700
