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
    "wordcloud": 24, # chat word counts (toxicity report) — changes slowly
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

# ---- Skill estimate (ensemble of medal + lobby median; listed MMR is NOT
# an input, so the estimate can be compared against it) ----
STAR_MMR = 154              # linear MMR width of one medal star
SIGMA_MEDAL = 180           # assumed noise of medal-implied MMR
SIGMA_LOBBY_BASE = 500      # lobby-median sigma at n=20 matches (shrinks with sqrt n)
SIGMA_LOBBY_MIN, SIGMA_LOBBY_MAX = 140, 450
LOBBY_RANKED_MIN = 30       # prefer ranked-only lobby median when this many ranked games
SOURCE_DISAGREE_MMR = 500   # medal vs lobby gap beyond which one source is distrusted
STALE_MEDAL_LOBBY_W = 0.75  # lobby weight when lobby >> medal (decayed/uncalibrated medal)
STALE_MEDAL_EXTREME = 1200  # beyond this the medal is meaningless (deep decay)
STALE_MEDAL_LOBBY_W_EXTREME = 0.9
QUEUE_DOWN_MEDAL_W = 0.65   # medal weight when medal >> lobby (parties down etc.)

# Momentum: shift the estimate only when the 30d record is statistically real
MOMENTUM_MIN_Z = 1.28       # ~90% one-sided
MOMENTUM_MMR_PER_Z = 30
MOMENTUM_CAP = 120
# Rust: linear penalty per day idle past 30 days
RUST_PER_DAY = 1.5
RUST_CAP = 180

# MMR climb: change in the player's LISTED MMR since they first signed up
# (baseline captured the first time we see them, then held fixed). Catches
# players whose website number was re-rated / updated before the draft.
CLIMB_FLAG_MMR = 100        # |change| worth flagging as raised / lowered

# Value tier: letter grade of (skill estimate - listed MMR). Descending bands;
# anything below the last threshold is an F. A "?" is appended when the gap is
# smaller than the estimate's uncertainty.
VALUE_TIER_BANDS = [
    (500, "S", "Steal"),
    (300, "A", "Great value"),
    (150, "B", "Good value"),
    (-150, "C", "Fair price"),
    (-300, "D", "Reach"),
    (-500, "E", "Overpriced"),
]
VALUE_TIER_FLOOR = ("F", "Big reach")

# ---- Auction rank premium ----
# Past drafts show the top of the board goes for MORE than MMR-vs-history
# implies (bidding wars on the known quantities — the #1 slot has gone 215-257
# on a 500 base in all 4 tracked auctions) while the tail goes for less
# (budgets dry up -> steals). Calibrated by order statistics: k-th priciest
# actual price minus k-th priciest kNN estimate, per season. Season-holdout
# validation: top-8 bias +60 -> +31, rank-17+ bias -23 -> -15.
# (pool_rank, $ at base 500); linear interpolation, flat outside the ends.
AUCTION_RANK_PREMIUM = [
    (1, 80), (2, 55), (3, 45), (5, 40), (8, 30),
    (12, 15), (16, 8), (22, -5), (28, -15),
]
# Positional scarcity: the top 3 available at each position get bid up even
# when their overall MMR rank wouldn't say so — the best support in the pool
# never goes for a steal. Past drafts carry no position labels, so this can't
# be calibrated like the curve above; magnitudes are anchored to it instead
# (#1 at a position ≈ overall slot 5, #2 ≈ slot 8, #3 ≈ slot 14) and combined
# with it via max(), so nothing double-counts or exceeds the calibrated top
# slot. Index = position rank - 1; $ at base 500.
AUCTION_POS_PREMIUM = [40, 25, 12]

# Value gap / outlier flags
VALUE_GAP_MMR = 250         # |skill - listed| worth flagging
PLACEHOLDER_LISTED = 1100   # listed <= this + big positive gap = unrated signup, not value
PLACEHOLDER_MIN_GAP = 800
# Hot/cold floor for a SINGLE player: 1.65 is ~90% two-sided (95% needs 1.96).
# Every player with a 30d record gets tested, so the bar actually applied is
# raised for pool size in analysis.pool_analysis — see HOT_COLD_FAMILY_ALPHA.
HOT_COLD_Z = 1.65
HOT_COLD_FAMILY_ALPHA = 0.10  # chance of ANY false hot/cold flag across the pool
PEER_MMR_WINDOW = 700       # pool z-scores compare players within this listed-MMR window
PEER_MIN = 10               # minimum peers for a robust z (MAD needs the sample)
PEER_Z_FLAG = 1.5
UP_LOBBY_STARS = 2          # "up-lobby" = match average_rank >= own medal + this many stars
UP_LOBBY_MIN_GAMES = 15

# ---- Mock draft (local practice auction against AI captains) ----
MOCK_TEAM_SIZE = 5          # players per team INCLUDING the captain
MOCK_BUYS = MOCK_TEAM_SIZE - 1   # players each captain buys in the auction (4)
MOCK_DEFAULT_ME = "Hollywood"    # default human seat (changeable in the UI)
MOCK_MIN_BID = 1            # opening / minimum bid ($)
MOCK_BID_INCREMENT = 1      # smallest AI raise step ($), used near the top
# Captains come from the dashboard: the "Export captains.json" button writes the
# captains YOU curated (the C button) plus their hand-set budgets to this file.
# The mock reads it as the authoritative captain/bidder list; if it's missing it
# falls back to the scraped teams page (which can mis-tag roster players).
MOCK_CAPTAINS_FILE = "captains.json"
MOCK_DEFAULT_BUDGET = 500   # $ for a captain with no budget in captains.json/teams
# Real-auction bidding: people click the +1 button most of the time, +5 now and
# then, +25 rarely. Each AI raise draws a step from this weighted set (clamped to
# never overshoot its own ceiling), so contested players grind up in small
# increments like a live draft instead of resolving in a couple of big jumps.
MOCK_BID_STEPS = [1, 5, 25]
MOCK_BID_STEP_WEIGHTS = [0.80, 0.16, 0.04]
MOCK_START_COUNTDOWN = 10      # "the draft is starting in N…" beat after Start
# Bid clock, replicating the site exactly (routes/draft.js in gmalysa/ld2l):
# a nomination opens at BID_TIME_LIMIT (15s); every bid resets the clock to
# 15s − 1s × (bids so far on this player), floored at MIN_BID_TIME (8s) — so
# the 7th bid onward always resets to 8s.
MOCK_NOMINATION_SECONDS = 15   # site: BID_TIME_LIMIT = 15000
MOCK_BID_SECONDS_FLOOR = 8     # site: MIN_BID_TIME = 8000
# Tempo. One bid is rolled per tick (see _ai_bid_round), so the mean seconds
# between bids is MOCK_AI_TICK / MOCK_AI_RAISE_PROB — here ~2.5 / 0.75 ≈ 3.3s, a
# watchable real-draft pace (~10x slower than the original spike). Slow it more by
# raising MOCK_AI_TICK; speed it up by lowering it.
MOCK_AI_TICK = 2.5         # seconds between AI raise opportunities
MOCK_AI_RAISE_PROB = 0.75  # chance a raise actually lands on a given tick
MOCK_AI_NOMINATE_DELAY = 3.5   # pause before an AI nominates, for readability
# Fast-forward. The dial divides EVERY timed window (bid clock, AI tick, nominate
# delay, sold beat) by the same factor, so MOCK_AI_TICK / window — which sets how
# many raises land per auction — is preserved and players sell for the same price
# at 8x as at 1x. The auction just plays out faster.
MOCK_SPEEDS = (1, 2, 4, 8)     # dial notches offered in the dashboard
MOCK_MAX_SPEED = 8             # server-side clamp, so a bad POST can't spin the
                               # engine thread on a zero-length sleep
MOCK_TARGET_PREMIUM = 1.2   # an AI will pay up to this ×value for a flagged target
                            # (a real but bounded overpay above market)
MOCK_RESERVE_PER_SLOT = MOCK_MIN_BID  # $ an AI keeps in reserve per unfilled slot
# Role need is decided by assignment, not by counting: captain (their role set)
# + every bought player (their playable set) must map to DISTINCT positions 1-5.
# A candidate who extends that matching fills a real hole -> market value. One
# who doesn't can still be bought OFF-ROLE: captains will burn a seat and move
# someone off-role for a clearly better player, valued at MOCK_OFFROLE_MULT ×
# worth — but only when that discounted value still beats the best on-role
# player left on the board (a Legend core outbids a Crusader support filler;
# it loses to an Ancient filler). Otherwise redundant = bench money only.
MOCK_NEED_FILLS = 1.0       # multiplier when the player fills an open seat
MOCK_OFFROLE_MULT = 0.75    # worth retained when buying a star who forces an
                            # off-role seat (the real cost of the shuffle)
MOCK_NEED_REDUNDANT = 0.15  # bench multiplier when not even worth the shuffle
# Hard overbid ceiling: an AI never bids beyond this × the player's worth, no
# matter how target premium / aggression stack up. Kills the "obvious overbid".
MOCK_MAX_OVERPAY = 1.25
# Price realism (keep talent from collapsing when its role is saturated). The mock
# is a real English auction, so a player only stays contested while MORE THAN ONE
# team values him near market; a strong player nominated after his role is filled
# elsewhere otherwise hammers for bench money.
# Behavioral floor: the top MOCK_BPA_STARS players by value are "known quantities" —
# every captain with an open roster slot chases them even OFF-ROLE (real drafts bid
# up best-player-available), so they stay contested and clear near market.
MOCK_BPA_STARS = 8
MOCK_BPA_FLOOR_MULT = 0.55   # min fraction of worth a star pulls off-role
# Hard backstop: no player hammers below this fraction of worth if the winner can
# afford it (capped at the winner's budget, so it never overdrafts). Catches any
# remaining single-/zero-bidder collapse — e.g. a mid Archon nominated into a dead
# room — that the behavioral floor (top-N only) doesn't cover.
MOCK_SALE_FLOOR_MULT = 0.4
# Specialization premium (applied to each player's base_value, the auction's market
# anchor). Two market truths, keyed off where the player sits on the value board and
# how narrow/committed their role profile is:
#   - At the TOP, specialists get bid up: a high-value player committed to a narrow
#     set of core roles (a pos-1/2 specialist) is worth more than an equally-priced
#     jack-of-all-roles, who drifts down (champ plays everything but specializes in
#     nothing -> no top-end premium).
#   - At the BOTTOM, flexibility gets valued more: a cheap player who can cover many
#     positions beats a cheap one-trick.
# Roles come from the slots the mock already trusts (measured lanes / dashboard tags);
# an untagged player with no clear lane history reads as flex.
MOCK_SPECIALIST_PREMIUM = 0.12  # top-end premium for a committed core specialist
MOCK_GENERALIST_SHADE = 0.07    # top-end shade for a play-anything generalist
MOCK_FLEX_BONUS = 0.10          # bottom-end premium for positional flexibility
MOCK_AI_AGGR_RANGE = (0.9, 1.08)  # deterministic per-captain value jitter band,
                                   # centered on market so the top sale lands ~worth_cost
MOCK_TARGETS_FILE = "mock_targets.json"  # per-captain target lists (persisted)

# ---- Hero draft practice (--herodraft: Captains Mode pick/ban vs a bot) ----
# Draft order is patch 7.40 (2025-12-15), verified against Liquipedia: first-pick
# bans 3-2-2 / second-pick 4-1-2, picks 1-3-1 for both — see herodraft.CM_PHASES.
HERODRAFT_PORT = 8323          # own default so --mock and --herodraft can coexist
HERODRAFT_TEAMS_FILE = "herodraft_teams.json"  # saved rosters between sessions
HERODRAFT_BAN1_SECONDS = 15    # first ban phase (7.34 shortened it from 30)
HERODRAFT_STEP_SECONDS = 30    # every other ban/pick
HERODRAFT_RESERVE_SECONDS = 130  # per-team bonus clock, drains after step time
# Timeout rules (per CM): ban times out -> no hero banned; pick -> random hero.
HERODRAFT_BOT_DELAY = (2.5, 7.0)   # bot acts after a random pause in this band
# Hero comfort scoring: shrunk winrate + volume + recency + league play.
HERODRAFT_WR_PRIOR = (4, 8)    # laplace (wins, games) shrink for small samples
HERODRAFT_FULL_COMFORT_GAMES = 40  # games at which volume factor saturates
HERODRAFT_RECENT_BONUS = 0.04  # per game on the hero in the 180d match sample
HERODRAFT_RECENT_BONUS_CAP = 0.25
HERODRAFT_LEAGUE_BONUS = 0.15  # per league/captains-mode game on the hero
HERODRAFT_LEAGUE_BONUS_CAP = 0.45   # league play = what they draft when it counts
HERODRAFT_STALE_180D = 0.8     # comfort multiplier when hero unplayed 180+ days
HERODRAFT_STALE_365D = 0.6     # ... 365+ days
HERODRAFT_STACK_WEIGHT = 0.35  # threat credit for the 2nd-best player on a hero
HERODRAFT_BOT_TOP_K = 4        # bot samples its move from the top K candidates
HERODRAFT_BOT_SHARPNESS = 3.0  # weight ∝ score^sharpness (higher = greedier)
HERODRAFT_SUGGESTIONS = 6      # hints shown on your turn

# Hero meta (patch winrates + hero-vs-hero matchups, both from OpenDota).
HERODRAFT_STATS_TTL_HOURS = 24 * 3   # /heroStats refresh (patch winrates)
HERODRAFT_META_TTL_HOURS = 24 * 7    # matchup matrix refresh (127 calls)
HERODRAFT_BRACKETS = (3, 4, 5, 6)    # Crusader..Divine ≈ the LD2L MMR band
HERODRAFT_MATCHUP_MIN_GAMES = 15     # ignore noisier hero-pair samples
HERODRAFT_TOP_META = 30              # most-picked heroes used for the
                                     # 'with' coverage-synergy proxy
# Rating = Σ weighted terms, displayed Dotabuff-style as e.g. "+4.10":
#   comfort (0..~2, roster hero evidence)  × W_COMFORT
#   patch   (base winrate − 50, in %)      × W_PATCH
#   vs      (Σ advantage vs enemy picks, %)× W_VS
#   with    (Σ coverage synergy w/ allies) × W_WITH
HERODRAFT_W_COMFORT = 2.0
HERODRAFT_W_PATCH = 0.4
HERODRAFT_W_VS = 0.35
HERODRAFT_W_WITH = 0.25
HERODRAFT_WINPROB_K = 0.10     # logistic slope: rating gap -> win probability
HERODRAFT_WINPROB_CLAMP = 12.0 # win prob shown within [12, 88]%
