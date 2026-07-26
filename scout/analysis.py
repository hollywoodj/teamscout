"""Derived scouting signals from OpenDota raw data.

Two passes:
  build_metrics(player, sections, hero_map)  — per-player signals
  pool_analysis(all_data, price_estimator)   — pool-relative signals
    (peer z-scores, auction worth/edge) that need every player fetched first

The centrepiece is a "true skill" estimate built ONLY from behavioral data
(medal + the ranked lobbies the player actually queues into), so it can be
compared honestly against the listed draft MMR:  value_gap = skill - listed.
OpenDota's computed_mmr is deliberately ignored — for sub-Immortal players it
compresses everyone into ~3700-4300 (r≈0.5 with everything) and carries no
signal for this pool.
"""

import statistics
from datetime import datetime, timezone

from . import config, hero_positions, toxicity
from .stats import binom_z, clamp, family_z, ivw_mean, robust_z, wilson_lower

MEDALS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
          5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}

LANE_NAMES = {1: "Safe", 2: "Mid", 3: "Off", 4: "Jungle"}

REQUESTED_HEROES = (
    (80, "Lone Druid"),
    (82, "Meepo"),
    (59, "Huskar"),
    (12, "Phantom Lancer"),
    (94, "Medusa"),
    (35, "Sniper"),
    (47, "Viper"),
    (30, "Witch Doctor"),
    (22, "Zeus"),
    (36, "Necrophos"),
)
RECENT_SECONDS = 183 * 86400

# server region a match was played on, from its cluster id (Dota clusters group
# by hundreds → region). Short codes; unknown clusters fall through to None.
REGION_RANGES = [
    (111, 120, "USW"), (121, 130, "USE"), (131, 140, "EU"), (141, 150, "JP"),
    (151, 160, "SEA"), (161, 170, "ME"), (171, 180, "AU"), (181, 199, "EU"),
    (200, 210, "SA"), (211, 220, "ZA"), (221, 240, "CN"), (241, 250, "SA"),
    (251, 260, "SA"), (261, 270, "IN"), (271, 290, "SEA"),
]


def cluster_region(cluster):
    if cluster is None:
        return None
    for lo, hi, short in REGION_RANGES:
        if lo <= cluster <= hi:
            return short
    return None


# Chat-toxicity scoring (lexicons + scan) lives in scout/toxicity.py — a
# self-contained subsystem lifted out of this module; see build_metrics.

# ---- Per-position rating (Plays-Like skill, weighted by measured lane) ----
SUPPORT_GPM_HINT = 380     # median GPM below this reads as a support tendency
POS_NAMES = {1: "Pos 1 (Safe)", 2: "Pos 2 (Mid)", 3: "Pos 3 (Off)",
             4: "Pos 4 (Soft Sup)", 5: "Pos 5 (Hard Sup)"}
LANE_TO_POS = {"Safe": 1, "Mid": 2, "Off": 3}
POS_TO_LANE = {p: l for l, p in LANE_TO_POS.items()}
# Lane a support shares with its core, so lane share counts for them too. The
# tag is ambiguous — a Safe-lane match is a pos 1 AND a pos 5 — so this term is
# gated on support comfort, which decides which of the two the player was.
SUPPORT_LANE = {4: "Off", 5: "Safe"}
SUPPORT_LANE_W = 0.5       # lane evidence is weaker for supports than cores

# ---- position-rating model ------------------------------------------------
# A position's rating is the player's base skill plus four independent evidence
# channels, each damped by n/(n+k) on the sample standing behind that channel.
# The caps below are the most any one channel may move a rating; a thin sample
# shrinks toward base rather than inventing a spread it can't support.
POS_SPREAD_CAP = 700       # furthest any position may sit from base skill
LANE_CHANNEL_CAP = 280     # measured lane share (cores only)
HERO_CHANNEL_CAP = 300     # hero-pool position affinity (the only 4-vs-5 signal)
PERF_CHANNEL_CAP = 160     # win rate within a lane vs the player's own overall
SUPP_CHANNEL_CAP = 220     # support-comfort gradient (positions 4/5)

LANE_SHRINK_K = 40         # lane-tagged matches for the lane channel's half-say
HERO_SHRINK_K = 60         # games on known heroes, for the hero channel
PERF_SHRINK_K = 25         # matches in a given lane, for the win-rate channel
SUPP_SHRINK_K = 40         # matches with GPM/KDA, for the support gradient

LANE_FULL_SHARE = 35       # % of matches in a lane that counts as a full-time role
HERO_FLAT_SHARE = 0.20     # fallback neutral affinity when the pool is too thin
HERO_BASELINE_MIN_PLAYERS = 8   # players with usable hero pools to re-baseline
PERF_FULL_WR_GAP = 12      # win-rate points vs own average for a full swing


def rank_tier_to_str(tier):
    if not tier:
        return "Uncalibrated"
    if tier >= 80:
        return "Immortal"
    medal = MEDALS.get(tier // 10, "?")
    stars = tier % 10
    return f"{medal} {stars}" if stars else medal


def tier_to_stars(tier):
    """Linearize a rank tier (e.g. 64 = Ancient 4) to a 0-based star index."""
    if not tier:
        return None
    if tier >= 80:
        return 36  # Immortal, above Divine 5 (index 34)
    medal, stars = tier // 10, tier % 10
    return (medal - 1) * 5 + max(stars - 1, 0)


def stars_to_tier(stars):
    if stars is None:
        return None
    if stars >= 35:
        return 80
    return (int(stars) // 5 + 1) * 10 + (int(stars) % 5 + 1)


def stars_to_mmr(stars):
    """Continuous star index -> linear MMR (star width from config)."""
    if stars is None:
        return None
    return stars * config.STAR_MMR + config.STAR_MMR / 2


def approx_mmr_from_tier(tier):
    """Midpoint MMR implied by a medal."""
    stars = tier_to_stars(tier)
    if stars is None:
        return None
    if tier >= 80:
        return 5600
    return round(stars_to_mmr(stars))


def days_since(unix_ts):
    if not unix_ts:
        return None
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - dt).days


def _won(m):
    is_radiant = m.get("player_slot", 0) < 128
    return is_radiant == bool(m.get("radiant_win"))


def is_organized_match(m):
    """True for the Captains Mode / 10-stack lobbies used as league evidence."""
    return (m.get("lobby_type") in (1, 2)
            and (m.get("game_mode") == 2 or m.get("party_size") == 10))


def _wl_rate(wl):
    if not wl:
        return None
    w, l = wl.get("win", 0), wl.get("lose", 0)
    total = w + l
    if total == 0:
        return None
    return {"wins": w, "losses": l, "games": total, "winrate": round(w / total * 100, 1)}


def beta_posterior_rate(wins, n, prior_games=10):
    """Posterior mean WR with a neutral 50% beta prior."""
    if n is None or n < 0:
        return None
    return round((wins + prior_games / 2) / (n + prior_games) * 100, 1)


def league_proof(d):
    status = d.get("esports_status", "unavailable")
    if status == "unavailable":
        return {
            "label": "Unavailable",
            "posterior_wr": None,
            "wilson_lower": None,
        }
    n = int(d.get("esports_games") or 0)
    wins = int(d.get("esports_wins") or 0)
    leagues = int(d.get("esports_league_count") or 0)
    posterior = beta_posterior_rate(wins, n)
    lower = wilson_lower(wins, n, z=1.96) if n else None
    if not n:
        label = "No verified history"
    elif n >= 20 and leagues >= 2 and lower is not None and lower >= 0.5:
        label = "Proven winner"
    elif n >= 10 and posterior > 52:
        label = "Winning record"
    elif n >= 20:
        label = "Experienced"
    else:
        label = "Limited sample"
    return {
        "label": label,
        "posterior_wr": posterior,
        "wilson_lower": round(lower * 100, 1) if lower is not None else None,
    }


def exact_lane_result(sample, xp_weight):
    """Win/draw/loss from both sides' minute-ten lane resources."""
    needed = (
        "ally_lane_gold10",
        "enemy_lane_gold10",
        "ally_lane_xp10",
        "enemy_lane_xp10",
    )
    if not isinstance(sample, dict) or any(sample.get(key) is None for key in needed):
        return None
    ally = sample["ally_lane_gold10"] + xp_weight * sample["ally_lane_xp10"]
    enemy = sample["enemy_lane_gold10"] + xp_weight * sample["enemy_lane_xp10"]
    if max(ally, enemy) <= 0:
        return None
    edge = (ally - enemy) / max(ally, enemy)
    if edge >= 0.05:
        return "win"
    if edge <= -0.05:
        return "loss"
    return "draw"


def role_fit(d, ratings=None):
    ratings = ratings if ratings is not None else position_ratings(d)
    if not ratings or not ratings.get("ratings"):
        return {
            "best": None,
            "secondary": [],
            "credible": [],
            "label": "Unclear",
        }
    rows = ratings["ratings"]
    best = ratings.get("primary")
    if best is None:
        return {
            "best": None,
            "secondary": [],
            "credible": [],
            "label": "Unclear",
        }
    best_mmr = rows[best]["mmr"]
    secondary = sorted(
        (
            pos for pos, row in rows.items()
            if pos != best and (
                (
                    row.get("conf") == "measured"
                    and best_mmr - row["mmr"] <= 175
                ) or (
                    row.get("conf") == "part-time"
                    and best_mmr - row["mmr"] <= 100
                )
            )
        ),
        key=lambda pos: rows[pos]["mmr"],
        reverse=True,
    )[:2]
    credible = [best, *secondary]
    return {
        "best": best,
        "secondary": secondary,
        "credible": credible,
        "label": "Versatile" if secondary else "Specialist",
    }


def _requested_hero_label(lifetime_games, lifetime_wins, recent_games,
                          ticketed_games, ticketed_wins):
    posterior = beta_posterior_rate(lifetime_wins, lifetime_games)
    if (
        lifetime_games >= 20 and posterior is not None and posterior >= 52
    ) or (
        ticketed_games >= 5 and ticketed_wins * 2 > ticketed_games
    ):
        return "Proven"
    if recent_games >= 3:
        return "Current"
    if lifetime_games >= 5:
        return "Historical"
    if lifetime_games:
        return "Tried"
    return "No evidence"


def _requested_hero_matrix(lifetime, recent, ticketed):
    rows = []
    for hero_id, name in REQUESTED_HEROES:
        life = lifetime.get(hero_id, {})
        rec = recent.get(hero_id, {})
        tic = ticketed.get(name, {})
        lg, lw = int(life.get("games", 0)), int(life.get("wins", 0))
        rg, rw = int(rec.get("games", 0)), int(rec.get("wins", 0))
        tg, tw = int(tic.get("games", 0)), int(tic.get("wins", 0))
        rows.append({
            "hero_id": hero_id,
            "hero": name,
            "lifetime_games": lg,
            "lifetime_wins": lw,
            "lifetime_wr": round(lw / lg * 100, 1) if lg else None,
            "recent_games": rg,
            "recent_wins": rw,
            "recent_wr": round(rw / rg * 100, 1) if rg else None,
            "ticketed_games": tg,
            "ticketed_wins": tw,
            "ticketed_wr": round(tw / tg * 100, 1) if tg else None,
            "label": _requested_hero_label(lg, lw, rg, tg, tw),
        })
    return rows


def _skill_estimate(d, matches):
    """Combine medal-implied MMR and ranked-lobby median into one estimate.

    Fills skill_mmr / skill_unc / skill_srcs / skill_note. Listed MMR is not
    used, so the result is comparable against it.
    """
    medal_est = d["approx_mmr"]

    ranks_all = [m["average_rank"] for m in matches if m.get("average_rank")]
    ranks_rk = [m["average_rank"] for m in matches
                if m.get("average_rank") and m.get("lobby_type") == 7]
    if len(ranks_rk) >= config.LOBBY_RANKED_MIN:
        ranks, lobby_kind = ranks_rk, f"ranked n={len(ranks_rk)}"
    elif ranks_all:
        ranks, lobby_kind = ranks_all, f"all-queue n={len(ranks_all)}"
    else:
        ranks, lobby_kind = [], ""

    lobby_est = sigma_lobby = None
    if len(ranks) >= 10:
        med_stars = statistics.median(sorted(tier_to_stars(r) for r in ranks))
        lobby_est = stars_to_mmr(med_stars)
        sigma_lobby = clamp(config.SIGMA_LOBBY_BASE / (len(ranks) / 20) ** 0.5,
                            config.SIGMA_LOBBY_MIN, config.SIGMA_LOBBY_MAX)

    srcs = []
    if medal_est is not None:
        srcs.append(f"medal {d['rank_str']} ≈{medal_est}")
    if lobby_est is not None:
        srcs.append(f"lobbies ({lobby_kind}) ≈{round(lobby_est)}")
    d["skill_srcs"] = " · ".join(srcs)

    if medal_est is not None and lobby_est is not None:
        gap = lobby_est - medal_est
        if abs(gap) <= config.SOURCE_DISAGREE_MMR:
            est, sigma = ivw_mean([(medal_est, config.SIGMA_MEDAL),
                                   (lobby_est, sigma_lobby)])
            unc = max(sigma, abs(gap) / 2, 120)
        elif gap > 0:
            # queues far above the medal: medal is stale/uncalibrated
            w = (config.STALE_MEDAL_LOBBY_W_EXTREME
                 if gap > config.STALE_MEDAL_EXTREME else config.STALE_MEDAL_LOBBY_W)
            est = w * lobby_est + (1 - w) * medal_est
            unc = clamp(abs(gap) / 2, 200, 600)
            d["skill_note"] = "medal looks stale — trusting lobbies"
        else:
            # medal far above lobbies: likely queuing down / party games
            w = config.QUEUE_DOWN_MEDAL_W
            est = w * medal_est + (1 - w) * lobby_est
            unc = clamp(abs(gap) / 2, 200, 600)
            d["skill_note"] = "queues below own medal"
    elif lobby_est is not None:
        est, unc = lobby_est, sigma_lobby * 1.2
        d["skill_note"] = "no medal — lobbies only"
    elif medal_est is not None:
        est, unc = medal_est, 250
        d["skill_note"] = "no match sample — medal only"
    else:
        d["skill_mmr"] = d["skill_unc"] = None
        return

    d["skill_mmr"] = round(est)
    d["skill_unc"] = round(unc)


def build_metrics(player, sections, hero_map):
    """Turn raw cached sections into the scouting data dict used by reports."""
    d = {
        "rank_tier": None, "rank_str": "?",
        "approx_mmr": None, "mmr_gap": None, "mmr_check": "",
        "wins": 0, "losses": 0, "winrate": 0, "total_matches": 0,
        "form30": None, "form90": None, "z30": None, "z90": None,
        "hot": False, "cold": False, "hot_cold_z": None,
        "last_match_days": None, "avg_kda": 0, "avg_gpm": 0, "avg_xpm": 0,
        "stats_n": 0,  # matches behind avg_kda/gpm/xpm (20 = recent fallback)
        # assists per death: separates the sacrificial pos 5 from the pos 4,
        # both of which sit below the support GPM line
        "avg_apd": None,
        "recent_heroes": [], "top_heroes": [], "versatility": 0,
        "signature_heroes": [],
        # hero_id -> lifetime games, for hero->position priors (hero_positions)
        "hero_games": {},
        "hero_stats": {}, "recent_hero_stats": {}, "requested_heroes": [],
        # pool-median affinity per position, filled by pool_analysis
        "hero_pos_baseline": None,
        # skill estimate (behavioral, independent of listed MMR)
        "skill_mmr": None, "skill_unc": None, "skill_srcs": "", "skill_note": "",
        "momentum": 0, "rust": 0, "adj_skill": None,
        "value_gap": None, "listed_suspect": False,
        # listed-MMR climb since signup (current listed - baseline at first sighting)
        "signup_mmr": None, "mmr_climb": None, "climbing": False, "falling": False,
        # private profile = hasn't exposed public matchmaking data (OpenDota fh_unavailable)
        "private_profile": False,
        # pool-relative (filled by pool_analysis)
        "farm_z": None, "farm_peers": 0, "kda_z": None, "kda_peers": 0,
        "worth_cost": None, "worth_base": None, "edge_cost": None,
        # lobby quality (average_rank based)
        "lobby_median_tier": None, "lobby_rank_str": "—", "lobby_sample": 0,
        "punches_above": False, "punch_gap_stars": None,
        # record in matches >= 2 stars above own medal
        "up_n": 0, "up_w": 0, "up_wr": None, "up_z": None,
        # queue habits
        "solo_pct": None, "solo_wr": None, "party_wr": None,
        "solo_n": 0, "party_n": 0, "solo_w": 0,
        # actual lanes (all matches with lane_role)
        "lane_str": "—", "lane_n": 0, "lane_pcts": {}, "lane_gpm": {},
        # per-lane record: {lane: {"n","w","wr"}} — lets a lane the player
        # actually wins in rate above one they merely show up in
        "lane_wr": {},
        "lane_eff_n": 0, "lane_eff_median": None, "lane_eff_by_lane": {},
        "vision_n": 0, "observer_per30": None, "sentry_per30": None,
        "deep_samples": [], "deep_parsed_n": 0,
        "lane_win_n": 0, "lane_decided_n": 0, "lane_wins": 0,
        "lane_draws": 0, "lane_losses": 0, "lane_win_pct": None,
        "lane_draw_pct": None, "lane_score_pct": None,
        "lane_results_by_lane": {},
        "deward_n": 0, "observer_kills_per30": None,
        "sentry_kills_per30": None, "dewards_per30": None,
        "vision_score": None, "vision_reliability": 0.0,
        # server region played most over the last 3 months
        "server_main": None, "server_mix": "", "server_n": 0,
        # record on US East servers over the full sample (LD2L plays on USE)
        "use_n": 0, "use_w": 0, "use_wr": None,
        # real league history (lobby fingerprint)
        "league_matches": 0, "league_wins": 0, "league_losses": 0,
        "league_winrate": 0, "league_heroes": [], "has_league_exp": False,
        # verified OpenDota ticketed matches (leagueid > 0)
        "esports_status": "unavailable", "esports_incomplete": False,
        "esports_games": 0, "esports_wins": 0, "esports_losses": 0,
        "esports_winrate": None, "esports_league_count": 0,
        "esports_first": None, "esports_latest": None,
        "esports_6mo_games": 0, "esports_6mo_wins": 0,
        "esports_6mo_losses": 0, "esports_6mo_winrate": None,
        "esports_leagues": [], "esports_recent_matches": [],
        "esports_recent_mode": "none", "esports_hero_stats": {},
        "league_proof": {},
        "role_fit": {}, "draft_value_score": None, "draft_value_rank": None,
        "draft_value_confidence": "low", "draft_value_channels": {},
        "draft_value_verdict": "",
        # auction history (filled in by auction.annotate_players)
        "est_cost": None, "est_base": None, "last_cost": None,
        "last_cost_season": None, "last_draft_mmr": None,
        "was_captain_last": False,
        # chat / toxicity (from OpenDota wordcloud my_word_counts)
        "chat_total_words": 0, "chat_unique_words": 0, "chat_top_words": [],
        "toxicity_hits": [], "toxicity_breakdown": {"flame": 0, "curse": 0, "slur": 0},
        "toxicity_score": None, "toxicity_label": "—", "private_chat": False,
    }

    esports = sections.get("esports")
    if isinstance(esports, dict):
        recent_esports = esports.get("six_month") or {}
        d.update({
            "esports_status": esports.get("status", "unavailable"),
            "esports_incomplete": bool(esports.get("incomplete")),
            "esports_games": esports.get("games", 0),
            "esports_wins": esports.get("wins", 0),
            "esports_losses": esports.get("losses", 0),
            "esports_winrate": esports.get("winrate"),
            "esports_league_count": esports.get("league_count", 0),
            "esports_first": esports.get("first"),
            "esports_latest": esports.get("latest"),
            "esports_6mo_games": recent_esports.get("games", 0),
            "esports_6mo_wins": recent_esports.get("wins", 0),
            "esports_6mo_losses": recent_esports.get("losses", 0),
            "esports_6mo_winrate": recent_esports.get("winrate"),
            "esports_leagues": esports.get("leagues") or [],
            "esports_recent_matches": esports.get("recent_matches") or [],
            "esports_recent_mode": esports.get("recent_mode", "none"),
            "esports_hero_stats": esports.get("hero_stats") or {},
        })

    # ---- profile / rank ----
    profile = sections.get("profile") or {}
    d["rank_tier"] = profile.get("rank_tier")
    d["rank_str"] = rank_tier_to_str(d["rank_tier"])
    d["approx_mmr"] = approx_mmr_from_tier(d["rank_tier"])
    listed = player.get("mmr") or 0
    if d["approx_mmr"] and listed:
        gap = d["approx_mmr"] - listed
        d["mmr_gap"] = gap
        if gap >= config.MMR_CHECK_GAP:
            d["mmr_check"] = f"⚠ medal implies ~+{gap}"
        elif gap <= -config.MMR_CHECK_GAP:
            d["mmr_check"] = f"listed ~{-gap} above medal"

    # ---- lifetime W/L + recent form ----
    wl = _wl_rate(sections.get("wl"))
    if wl:
        d["wins"], d["losses"] = wl["wins"], wl["losses"]
        d["total_matches"] = wl["games"]
        d["winrate"] = wl["winrate"]
    d["form30"] = _wl_rate(sections.get("wl30"))
    d["form90"] = _wl_rate(sections.get("wl90"))
    for form_key, z_key in (("form30", "z30"), ("form90", "z90")):
        f = d[form_key]
        if f and f["games"] >= 10:
            d[z_key] = round(binom_z(f["wins"], f["games"]), 2)
    # NB: hot/cold flags are NOT set here. The bar depends on how many players
    # get tested, which isn't known until the pool is loaded — pool_analysis.

    # ---- recent matches: activity + fallback KDA/GPM ----
    recent = sections.get("recent") or []
    if isinstance(recent, list) and recent:
        d["last_match_days"] = days_since(recent[0].get("start_time"))
        d["recent_heroes"] = [hero_map.name(m["hero_id"]) for m in recent[:10] if m.get("hero_id")]

    # ---- lifetime hero stats ----
    heroes = sections.get("heroes") or []
    if isinstance(heroes, list) and heroes:
        d["versatility"] = sum(1 for h in heroes if int(h.get("games", 0)) > 0)
        top = sorted(heroes, key=lambda h: -int(h.get("games", 0)))[:5]
        for h in top:
            games, wins = int(h.get("games", 0)), int(h.get("win", 0))
            if games == 0:
                continue
            wr = round(wins / games * 100)
            d["top_heroes"].append(f"{hero_map.name(int(h['hero_id']))} ({games}g {wr}%)")
        for h in heroes:
            games = int(h.get("games", 0))
            if games > 0:
                try:
                    hero_id = int(h["hero_id"])
                    wins = int(h.get("win", 0))
                    d["hero_games"][hero_id] = games
                    d["hero_stats"][hero_id] = {
                        "games": games,
                        "wins": wins,
                    }
                except (KeyError, ValueError, TypeError):
                    pass
        for h in heroes:
            games, wins = int(h.get("games", 0)), int(h.get("win", 0))
            if games >= config.SIGNATURE_MIN_GAMES:
                wr = round(wins / games * 100, 1)
                if wr >= config.SIGNATURE_MIN_WINRATE:
                    d["signature_heroes"].append({
                        "hero": hero_map.name(int(h["hero_id"])),
                        "games": games, "wins": wins, "winrate": wr,
                    })
        d["signature_heroes"].sort(key=lambda s: -s["winrate"])

    # ---- match sample: lobby rank, performance, solo/party, lanes, league ----
    matches = sections.get("matches") or []
    if not isinstance(matches, list):
        matches = []
    if matches:
        if d["last_match_days"] is None:
            d["last_match_days"] = days_since(matches[0].get("start_time"))

        ranks = [m["average_rank"] for m in matches if m.get("average_rank")]
        if ranks:
            d["lobby_sample"] = len(ranks)
            med_stars = statistics.median(sorted(tier_to_stars(r) for r in ranks))
            med_tier = stars_to_tier(round(med_stars))
            d["lobby_median_tier"] = med_tier
            d["lobby_rank_str"] = rank_tier_to_str(med_tier)
            own = tier_to_stars(d["rank_tier"])
            if own is not None:
                gap = round(med_stars) - own
                d["punch_gap_stars"] = gap
                d["punches_above"] = gap >= config.PUNCH_STAR_GAP

        # performance over the full sample (projection >= _v2); recent fallback
        with_stats = [m for m in matches if m.get("gold_per_min") is not None
                      and m.get("deaths") is not None]
        if len(with_stats) >= 30:
            k = sum(m.get("kills", 0) for m in with_stats)
            dd = sum(m.get("deaths", 0) for m in with_stats)
            a = sum(m.get("assists", 0) for m in with_stats)
            d["avg_kda"] = round((k + a) / max(dd, 1), 2)
            d["avg_apd"] = round(a / max(dd, 1), 2)
            d["avg_gpm"] = round(statistics.median(m["gold_per_min"] for m in with_stats))
            xpms = [m["xp_per_min"] for m in with_stats if m.get("xp_per_min")]
            d["avg_xpm"] = round(statistics.median(xpms)) if xpms else 0
            d["stats_n"] = len(with_stats)
            for lr, lname in LANE_NAMES.items():
                lg = [m["gold_per_min"] for m in with_stats if m.get("lane_role") == lr]
                if len(lg) >= 8:
                    d["lane_gpm"][lname] = round(statistics.median(lg))

        # per-lane record over the whole sample (not just the stats subset)
        for lr, lname in LANE_NAMES.items():
            in_lane = [m for m in matches if m.get("lane_role") == lr]
            if len(in_lane) >= 8:
                w = sum(1 for m in in_lane if _won(m))
                d["lane_wr"][lname] = {
                    "n": len(in_lane), "w": w,
                    "wr": round(w / len(in_lane) * 100, 1),
                }

        lane_eff = [
            m for m in matches
            if m.get("version")
            and not m.get("is_roaming")
            and m.get("lane_role") in LANE_NAMES
            and m.get("lane_efficiency_pct") is not None
        ]
        d["lane_eff_n"] = len(lane_eff)
        if lane_eff:
            d["lane_eff_median"] = round(statistics.median(
                float(m["lane_efficiency_pct"]) for m in lane_eff
            ), 1)
            for lane_id, lane_name in LANE_NAMES.items():
                values = [
                    float(m["lane_efficiency_pct"]) for m in lane_eff
                    if m.get("lane_role") == lane_id
                ]
                if values:
                    d["lane_eff_by_lane"][lane_name] = {
                        "n": len(values),
                        "median": round(statistics.median(values), 1),
                    }

        vision_rows = [
            m for m in matches
            if m.get("version") and (m.get("duration") or 0) > 0
            and (
                m.get("purchase_ward_observer") is not None
                or m.get("purchase_ward_sentry") is not None
            )
        ]
        d["vision_n"] = len(vision_rows)
        if vision_rows:
            duration30 = sum(m["duration"] for m in vision_rows) / 1800
            if duration30:
                d["observer_per30"] = round(sum(
                    int(m.get("purchase_ward_observer") or 0)
                    for m in vision_rows
                ) / duration30, 2)
                d["sentry_per30"] = round(sum(
                    int(m.get("purchase_ward_sentry") or 0)
                    for m in vision_rows
                ) / duration30, 2)

        cutoff = int(datetime.now(tz=timezone.utc).timestamp()) - RECENT_SECONDS
        for m in matches:
            hero_id = m.get("hero_id")
            if not hero_id or (m.get("start_time") or 0) < cutoff:
                continue
            try:
                hero_id = int(hero_id)
            except (TypeError, ValueError):
                continue
            entry = d["recent_hero_stats"].setdefault(
                hero_id, {"games": 0, "wins": 0}
            )
            entry["games"] += 1
            if _won(m):
                entry["wins"] += 1

        # record when queuing >= UP_LOBBY_STARS above own medal
        own = tier_to_stars(d["rank_tier"])
        if own is not None:
            up = [m for m in matches if m.get("average_rank")
                  and tier_to_stars(m["average_rank"]) >= own + config.UP_LOBBY_STARS]
            d["up_n"] = len(up)
            if up:
                d["up_w"] = sum(1 for m in up if _won(m))
                d["up_wr"] = round(d["up_w"] / len(up) * 100, 1)
                if len(up) >= 10:
                    d["up_z"] = round(binom_z(d["up_w"], len(up)), 2)

        solo_w = solo_l = party_w = party_l = 0
        for m in matches:
            ps = m.get("party_size")
            if ps is None:
                continue
            if ps <= 1:
                if _won(m): solo_w += 1
                else: solo_l += 1
            else:
                if _won(m): party_w += 1
                else: party_l += 1
        d["solo_n"], d["party_n"] = solo_w + solo_l, party_w + party_l
        d["solo_w"] = solo_w
        known = d["solo_n"] + d["party_n"]
        if known:
            d["solo_pct"] = round(d["solo_n"] / known * 100)
        if d["solo_n"]:
            d["solo_wr"] = round(solo_w / d["solo_n"] * 100, 1)
        if d["party_n"]:
            d["party_wr"] = round(party_w / d["party_n"] * 100, 1)

        lanes = {}
        for m in matches:
            lr = m.get("lane_role")
            if lr in LANE_NAMES:
                lanes[lr] = lanes.get(lr, 0) + 1
        d["lane_n"] = sum(lanes.values())
        if d["lane_n"]:
            d["lane_pcts"] = {LANE_NAMES[k]: round(v / d["lane_n"] * 100)
                              for k, v in sorted(lanes.items())}
            d["lane_str"] = " · ".join(f"{n} {p}%" for n, p in d["lane_pcts"].items())

        # server region played most over the last 3 months
        servers = {}
        for m in matches:
            days = days_since(m.get("start_time"))
            if days is None or days > 90:
                continue
            reg = cluster_region(m.get("cluster"))
            if reg:
                servers[reg] = servers.get(reg, 0) + 1
        d["server_n"] = sum(servers.values())
        if d["server_n"]:
            ranked = sorted(servers.items(), key=lambda kv: -kv[1])
            d["server_main"] = ranked[0][0]
            d["server_mix"] = " · ".join(f"{r} {round(n / d['server_n'] * 100)}%"
                                         for r, n in ranked[:3])

        # W/L on US East servers — the region LD2L games are played on. Full
        # sample (not the 3mo server-mix window) for a usable n.
        for m in matches:
            if cluster_region(m.get("cluster")) != "USE":
                continue
            d["use_n"] += 1
            if _won(m):
                d["use_w"] += 1
        if d["use_n"]:
            d["use_wr"] = round(d["use_w"] / d["use_n"] * 100, 1)

        # League/inhouse games: practice or tournament lobbies played as Captains
        # Mode or full 10-stacks. (OpenDota's player-matches projection does NOT
        # populate leagueid, so lobby fingerprint is the reliable signal.)
        for m in matches:
            if not is_organized_match(m):
                continue
            d["league_matches"] += 1
            if _won(m):
                d["league_wins"] += 1
            else:
                d["league_losses"] += 1
            if m.get("hero_id"):
                hname = hero_map.name(m["hero_id"])
                if hname not in d["league_heroes"]:
                    d["league_heroes"].append(hname)
        if d["league_matches"]:
            d["has_league_exp"] = True
            d["league_winrate"] = round(d["league_wins"] / d["league_matches"] * 100, 1)

    # fallback performance stats from the 20-game recent window
    if not d["stats_n"] and isinstance(recent, list) and recent:
        kills = sum(m.get("kills", 0) for m in recent)
        deaths = sum(m.get("deaths", 0) for m in recent)
        assists = sum(m.get("assists", 0) for m in recent)
        gpms = [m["gold_per_min"] for m in recent if m.get("gold_per_min")]
        xpms = [m["xp_per_min"] for m in recent if m.get("xp_per_min")]
        d["avg_kda"] = round((kills + assists) / max(deaths, 1), 2)
        d["avg_gpm"] = round(sum(gpms) / len(gpms)) if gpms else 0
        d["avg_xpm"] = round(sum(xpms) / len(xpms)) if xpms else 0
        d["stats_n"] = len(recent)

    # ---- skill estimate + momentum/rust adjustments ----
    _skill_estimate(d, matches)
    if d["z30"] is not None and abs(d["z30"]) >= config.MOMENTUM_MIN_Z:
        d["momentum"] = round(clamp(config.MOMENTUM_MMR_PER_Z * d["z30"],
                                    -config.MOMENTUM_CAP, config.MOMENTUM_CAP))
    if d["last_match_days"] is not None and d["last_match_days"] > 30:
        d["rust"] = round(min(config.RUST_PER_DAY * (d["last_match_days"] - 30),
                              config.RUST_CAP))
    if d["skill_mmr"] is not None:
        d["adj_skill"] = d["skill_mmr"] + d["momentum"] - d["rust"]
        if listed:
            d["value_gap"] = d["adj_skill"] - listed
            d["listed_suspect"] = (listed <= config.PLACEHOLDER_LISTED
                                   and d["value_gap"] >= config.PLACEHOLDER_MIN_GAP)

    # ---- private profile: no exposed match history ----
    inner = profile.get("profile") or {}
    d["private_profile"] = (bool(inner.get("fh_unavailable"))
                            or (d["total_matches"] == 0 and not matches and not recent))

    # ---- listed-MMR climb since signup (website number movement) ----
    d["signup_mmr"] = player.get("signup_mmr")
    if d["signup_mmr"] is not None and listed:
        d["mmr_climb"] = listed - d["signup_mmr"]
        d["climbing"] = d["mmr_climb"] >= config.CLIMB_FLAG_MMR
        d["falling"] = d["mmr_climb"] <= -config.CLIMB_FLAG_MMR

    # ---- chat toxicity (wordcloud my_word_counts) — see scout/toxicity.py ----
    d.update(toxicity.score(sections.get("wordcloud")))
    d["deep_samples"] = [
        sample for sample in (sections.get("deep") or [])
        if isinstance(sample, dict)
    ]
    d["deep_parsed_n"] = sum(
        1 for sample in d["deep_samples"] if sample.get("parsed")
    )
    d["league_proof"] = league_proof(d)
    d["requested_heroes"] = _requested_hero_matrix(
        d["hero_stats"],
        d["recent_hero_stats"],
        d["esports_hero_stats"],
    )

    return d


def measured_roles(d):
    """Positions implied by the lanes actually played: Safe→1, Mid→2, Off→3.

    Declared signup prefs are ignored (the site's role data is unreliable).
    Support roles (4/5) can't be inferred from lane alone — the dashboard lets
    you set those by hand; here we only key off the measured lanes.
    """
    lanes = d.get("lane_pcts") or {}
    roles = []
    if lanes.get("Safe", 0) >= 15:
        roles.append(1)
    if lanes.get("Mid", 0) >= 15:
        roles.append(2)
    if lanes.get("Off", 0) >= 15:
        roles.append(3)
    return roles


def _measured_core(d):
    """True when the player actually plays a core lane (safe/mid/off)."""
    return bool(measured_roles(d))


def _peer_values(target_pd, pool, metric):
    """Metric values of pool members near target's listed MMR (widening once)."""
    mmr = target_pd["player"]["mmr"]
    vals = [(abs(pd["player"]["mmr"] - mmr), pd["data"][metric])
            for pd in pool if pd is not target_pd and pd["data"][metric]]
    near = [v for dist, v in vals if dist <= config.PEER_MMR_WINDOW]
    if len(near) >= config.PEER_MIN:
        return near
    return [v for _, v in vals] if len(vals) >= config.PEER_MIN else []


def flag_hot_cold(all_data):
    """Owner of the family-wise hot/cold streak flag (the pool-relative half of
    the value signal that build_metrics deliberately leaves unset).

    Hot/cold is a multiple-comparisons problem. HOT_COLD_Z is the bar for
    testing ONE player, but every player with a 30d record gets tested, so at
    1.65 a ~100-player board shows ~10 streaks that are pure luck. Raise the bar
    with the pool size so HOT_COLD_FAMILY_ALPHA is the odds of any false flag on
    the whole board. Never drops below the single-test floor. Returns the bar
    that was applied.
    """
    tested = [pd for pd in all_data if pd["data"]["z30"] is not None]
    bar = max(family_z(len(tested), config.HOT_COLD_FAMILY_ALPHA) or 0,
              config.HOT_COLD_Z)
    for pd in tested:
        d = pd["data"]
        d["hot_cold_z"] = round(bar, 2)
        d["hot"] = d["z30"] >= bar
        d["cold"] = d["z30"] <= -bar
    return bar


def _set_hero_pos_baseline(all_data):
    """Neutral hero-pool affinity per position, measured from this pool.

    Position affinity can't be compared against a flat 1-in-5: the hero table
    is honestly lopsided, because pos 4 is the most shared role in Dota (only
    ~6 heroes are played there and nowhere else, against ~17 for pos 5). Scored
    against a flat baseline every player looks like a hard support and nobody
    looks like a soft support. Taking the pool's own median as neutral cancels
    that, so a rating says "supports more than his peers do" rather than
    "matches an arbitrary prior".
    """
    per_pos = {p: [] for p in range(1, 6)}
    for pd in all_data:
        shares, counted = hero_positions.affinity(pd["data"].get("hero_games"))
        if counted >= HERO_SHRINK_K:
            for p in range(1, 6):
                per_pos[p].append(shares[p])

    sampled = [v for vals in per_pos.values() for v in vals]
    if len(sampled) < 5 * HERO_BASELINE_MIN_PLAYERS:
        return  # too thin a pool to re-baseline; the flat prior stays
    baseline = {p: statistics.median(vals) if vals else HERO_FLAT_SHARE
                for p, vals in per_pos.items()}
    for pd in all_data:
        pd["data"]["hero_pos_baseline"] = baseline


def pool_analysis(all_data, price_estimator=None):
    """Pool-relative pass: hot/cold flags, peer z-scores and auction worth/edge.

    Call after every player is fetched and auction.annotate_players has run.
    """
    flag_hot_cold(all_data)
    _set_hero_pos_baseline(all_data)

    cores = [pd for pd in all_data if _measured_core(pd["data"])
             and pd["data"]["stats_n"] >= 30]
    scored = [pd for pd in all_data if pd["data"]["stats_n"] >= 30]

    for pd in all_data:
        p, d = pd["player"], pd["data"]

        if d["stats_n"] >= 30 and _measured_core(d):
            peers = _peer_values(pd, cores, "avg_gpm")
            d["farm_peers"] = len(peers)
            z = robust_z(d["avg_gpm"], peers)
            d["farm_z"] = round(z, 2) if z is not None else None

        if d["stats_n"] >= 30:
            peers = _peer_values(pd, scored, "avg_kda")
            d["kda_peers"] = len(peers)
            z = robust_z(d["avg_kda"], peers)
            d["kda_z"] = round(z, 2) if z is not None else None

        if price_estimator and d["adj_skill"] is not None:
            d["worth_base"] = price_estimator(d["adj_skill"], with_premium=False)
            d["worth_cost"] = price_estimator(d["adj_skill"], measured_roles(d))
            if d["worth_cost"] is not None and d["est_cost"] is not None:
                d["edge_cost"] = d["worth_cost"] - d["est_cost"]

    _finalize_deep_and_role_metrics(all_data)
    score_draft_values(all_data)


def value_tier(d):
    """Letter grade of value = skill estimate vs listed MMR.

    S/A/B = plays above their price, C = fairly listed, D/E/F = listed above
    how they actually play. '?' marks gaps smaller than the estimate's
    uncertainty; unrated placeholders and no-data players aren't graded.
    """
    if d["listed_suspect"]:
        return "★ Unrated"
    g = d["value_gap"]
    if g is None:
        return "—"
    letter, label = config.VALUE_TIER_FLOOR
    for thresh, lt, lb in config.VALUE_TIER_BANDS:
        if g >= thresh:
            letter, label = lt, lb
            break
    tier = f"{letter} - {label}"
    if letter != "C" and d["skill_unc"] and abs(g) < d["skill_unc"]:
        tier += " ?"
    return tier


def is_strong_value_signal(d):
    """A single signal strong enough to justify a Value Picks entry on its own."""
    return ((d["value_gap"] is not None and d["value_gap"] >= config.VALUE_GAP_MMR
             and not d["listed_suspect"])
            or d["hot"]
            or d["punches_above"]
            or (d["up_n"] >= config.UP_LOBBY_MIN_GAMES and d["up_wr"] is not None
                and d["up_wr"] >= 52)
            or (d["farm_z"] is not None and d["farm_z"] >= config.PEER_Z_FLAG))


def value_pick_signals(p, d):
    """Reasons a player may outperform their MMR, and risk flags (z-grounded)."""
    reasons, risks = [], []
    mmr = p["mmr"]

    # NB: calibrated to LD2L signups, where a 5000-game veteran with league
    # experience is the norm — only statistically unusual traits count.
    if d["value_gap"] is not None and d["value_gap"] >= config.VALUE_GAP_MMR:
        if d["listed_suspect"]:
            reasons.append(f"Unrated signup: plays like ~{d['adj_skill']} "
                           f"({d['skill_srcs']}) but listed {mmr}")
        else:
            reasons.append(f"Plays like ~{d['adj_skill']}±{d['skill_unc']} "
                           f"vs listed {mmr} (+{d['value_gap']})")
    if d["hot"]:
        f30 = d["form30"]
        reasons.append(f"Hot: {f30['wins']}-{f30['losses']} last 30d "
                       f"(z=+{d['z30']} vs {d['hot_cold_z']} pool bar)")
    if (d["up_n"] >= config.UP_LOBBY_MIN_GAMES and d["up_wr"] is not None
            and wilson_lower(d["up_w"], d["up_n"]) >= 0.5):
        reasons.append(f"Holds up a bracket: {d['up_w']}-{d['up_n'] - d['up_w']} "
                       f"({d['up_wr']}%) in lobbies {config.UP_LOBBY_STARS}+ stars above medal")
    elif d["punches_above"]:
        reasons.append(f"Queues into {d['lobby_rank_str']} lobbies (median) vs own {d['rank_str']}")
    if d["farm_z"] is not None and d["farm_z"] >= config.PEER_Z_FLAG:
        reasons.append(f"Farms +{d['farm_z']}σ vs {d['farm_peers']} similar-MMR cores "
                       f"({d['avg_gpm']} median GPM)")
    if d["kda_z"] is not None and d["kda_z"] >= config.PEER_Z_FLAG:
        reasons.append(f"KDA {d['avg_kda']} is +{d['kda_z']}σ vs {d['kda_peers']} "
                       f"MMR peers (over {d['stats_n']}g)")
    if d["solo_n"] >= 30 and d["solo_wr"] is not None \
            and wilson_lower(d["solo_w"], d["solo_n"]) >= 0.52:
        reasons.append(f"Solo queue {d['solo_wr']}% WR ({d['solo_n']}g) - self-sufficient")
    if len(d["signature_heroes"]) >= 5:
        names = [s["hero"] for s in d["signature_heroes"][:3]]
        reasons.append(f"{len(d['signature_heroes'])} signature heroes inc. {', '.join(names)}")
    if d["league_matches"] >= 30 and d["league_winrate"] >= 50:
        reasons.append(f"{d['league_matches']} league games in last 6mo ({d['league_winrate']}% WR)")
    if d["total_matches"] > 8000:
        reasons.append(f"{d['total_matches']} total games - extremely experienced")
    if d["last_draft_mmr"] and mmr and d["last_draft_mmr"] - mmr >= 300:
        reasons.append(f"Listed {mmr} now vs {d['last_draft_mmr']} at their "
                       f"{d['last_cost_season']} draft (-{d['last_draft_mmr'] - mmr})")

    if d["value_gap"] is not None and d["value_gap"] <= -config.VALUE_GAP_MMR:
        risks.append(f"Listed {mmr} but plays like ~{d['adj_skill']} "
                     f"({d['value_gap']})")
    if d["cold"]:
        f30 = d["form30"]
        risks.append(f"Cold: {f30['wins']}-{f30['losses']} last 30d "
                     f"(z={d['z30']} vs {d['hot_cold_z']} pool bar)")
    if d["last_match_days"] is not None and d["last_match_days"] > 60:
        risks.append(f"Inactive {d['last_match_days']}d")
    if d["farm_z"] is not None and d["farm_z"] <= -config.PEER_Z_FLAG:
        risks.append(f"Farms {d['farm_z']}σ below similar-MMR cores")
    if d["total_matches"] < 100:
        risks.append("Very few games on record")
    if d["lobby_sample"] and d["lobby_sample"] < 20:
        risks.append(f"Thin match sample ({d['lobby_sample']} rated games in 6mo)")
    if not p.get("mmr_valid") and not p.get("mmr_screenshot"):
        risks.append("MMR not validated")

    return reasons, risks


def select_value_picks(all_data):
    """(picks, unrated): value-board entries and placeholder-MMR signups.

    picks are sorted by auction edge (worth$ - expected$), falling back to
    the MMR value gap when no auction history covers the pool.
    """
    picks, unrated = [], []
    for pd in all_data:
        d = pd["data"]
        if d["listed_suspect"]:
            unrated.append(pd)
            continue
        reasons, risks = value_pick_signals(pd["player"], d)
        if len(reasons) >= 2 or (reasons and is_strong_value_signal(d)):
            picks.append((pd, reasons, risks))

    def edge_key(item):
        d = item[0]["data"]
        if d["edge_cost"] is not None:
            return -d["edge_cost"]
        if d["value_gap"] is not None:
            return -d["value_gap"] / 10
        return 0.0

    picks.sort(key=edge_key)
    unrated.sort(key=lambda pd: -(pd["data"]["value_gap"] or 0))
    return picks, unrated


def _mmr_to_rank_str(mmr):
    """Inverse of stars_to_mmr: MMR -> nearest medal string (for display)."""
    if mmr is None:
        return "—"
    stars = (mmr - config.STAR_MMR / 2) / config.STAR_MMR
    stars = max(0, min(36, stars))
    return rank_tier_to_str(stars_to_tier(round(stars)))


def _shrink(n, k):
    """n/(n+k): how much of a channel's swing a sample of size n has earned."""
    if not n or n <= 0:
        return 0.0
    return n / (n + k)


def _support_comfort(d):
    """0..1 on how support-like the farm profile is, or None without stats.

    Replaces the old boolean GPM threshold: a 379 GPM player and a 180 GPM
    player are not equally likely to be supports, and the old test called them
    both one.
    """
    gpm = d.get("avg_gpm") or 0
    if not gpm:
        return None
    lo, hi = 200, SUPPORT_GPM_HINT + 60
    return clamp((hi - gpm) / (hi - lo), 0.0, 1.0)


def _hard_support_tilt(d):
    """-1 (reads pos 4) .. +1 (reads pos 5), or None without stats.

    Hard supports buy the wards, take the bad trades and farm least; soft
    supports keep more farm and die less for it. Assists-per-death rather than
    KDA, because a pos 5's deaths are the point rather than a mistake.
    """
    apd = d.get("avg_apd")
    gpm = d.get("avg_gpm") or 0
    if apd is None or not gpm:
        return None
    farm_part = clamp((300 - gpm) / 120.0, -1.0, 1.0)
    sac_part = clamp((apd - 2.2) / 1.2, -1.0, 1.0)
    return clamp((farm_part + sac_part) / 2, -1.0, 1.0)


def position_ratings(d, hero_map=None):
    """Estimated skill at each of the five positions, on the tool's Plays-Like
    scale (medal + MMR).

    Four evidence channels stack onto the base skill estimate:
      lane   - measured share of matches in that lane, on a saturating curve
      hero   - where the played hero pool sits positionally; the only signal
               that separates pos 4 from pos 5, or a pos 1 from the pos 5
               sharing their safelane
      perf   - win rate in that lane against the player's own overall
      supp   - support-comfort gradient from farm and assists-per-death

    Each is damped by the sample behind it and the total is capped at
    POS_SPREAD_CAP off base, so confident spreads stay wide and thin ones
    collapse toward the base estimate.

    Returns {"primary": pos|None, "ratings": {pos: {...}}, "note":} or {} when
    there's no skill estimate to build on.
    """
    base = d.get("adj_skill") or d.get("skill_mmr")
    if base is None:
        return {}

    lanes = d.get("lane_pcts") or {}
    lane_wr = d.get("lane_wr") or {}
    overall_wr = d.get("winrate") or 0
    hero_share, hero_n = hero_positions.affinity(d.get("hero_games"))
    baseline = d.get("hero_pos_baseline") or {}
    comfort = _support_comfort(d)
    tilt = _hard_support_tilt(d)

    lane_shrink = _shrink(d.get("lane_n") or 0, LANE_SHRINK_K)
    hero_shrink = _shrink(hero_n, HERO_SHRINK_K)
    supp_shrink = _shrink(d.get("stats_n") or 0, SUPP_SHRINK_K)

    ratings = {}
    for pos in range(1, 6):
        lane = POS_TO_LANE.get(pos)
        share = lanes.get(lane, 0) if lane else 0
        adj = 0.0
        why = []

        # --- lane familiarity (cores): saturating, so 12% and 24% differ
        if lane and lane_shrink:
            fam = min(1.0, (share / LANE_FULL_SHARE) ** 0.7) if share > 0 else 0.0
            a = LANE_CHANNEL_CAP * (2 * fam - 1) * lane_shrink
            adj += a
            why.append((f"{lane} lane {share}%", a))

        # --- hero-pool affinity (all five positions), against the pool's own
        # neutral point rather than a flat 1-in-5 (see _set_hero_pos_baseline)
        if hero_n:
            neutral = baseline.get(pos) or HERO_FLAT_SHARE
            dev = hero_share[pos] - neutral
            a = (HERO_CHANNEL_CAP
                 * clamp(dev / neutral, -1.0, 1.5) * hero_shrink)
            adj += a
            picks = hero_positions.top_heroes_for(d.get("hero_games"), pos,
                                                  hero_map)
            label = f"hero pool {round(hero_share[pos] * 100)}%"
            if picks:
                label += " — " + ", ".join(picks)
            why.append((label, a))

        # --- win rate in this lane vs the player's own average
        rec = lane_wr.get(lane) if lane else None
        if rec and overall_wr:
            delta = rec["wr"] - overall_wr
            a = (PERF_CHANNEL_CAP * clamp(delta / PERF_FULL_WR_GAP, -1.0, 1.0)
                 * _shrink(rec["n"], PERF_SHRINK_K))
            adj += a
            why.append((f"{rec['wr']}% in {lane} over {rec['n']} "
                        f"(vs {overall_wr}% overall)", a))

        # --- support comfort, then which support
        if pos in (4, 5):
            # lane share of the lane this support stands in, gated on comfort
            # so a farming safelaner earns no pos 5 credit from it
            sup_lane = SUPPORT_LANE[pos]
            sup_share = lanes.get(sup_lane, 0)
            if lane_shrink and comfort is not None:
                fam = (min(1.0, (sup_share / LANE_FULL_SHARE) ** 0.7)
                       if sup_share > 0 else 0.0)
                a = (LANE_CHANNEL_CAP * SUPPORT_LANE_W * (2 * fam - 1)
                     * lane_shrink * comfort)
                adj += a
                if abs(a) >= 15:
                    why.append((f"{sup_lane} lane {sup_share}%", a))
            if comfort is not None:
                a = SUPP_CHANNEL_CAP * 0.7 * (2 * comfort - 1) * supp_shrink
                adj += a
                why.append((f"{d.get('avg_gpm')} GPM", a))
            if tilt is not None:
                sign = 1 if pos == 5 else -1
                a = SUPP_CHANNEL_CAP * 0.3 * sign * tilt * supp_shrink
                adj += a
                if abs(a) >= 15:
                    why.append((f"{d.get('avg_apd')} assists per death", a))

        adj = clamp(adj, -POS_SPREAD_CAP, POS_SPREAD_CAP)
        mmr = max(0, round(base + adj))

        # evidence for THIS position: a strong hero pool can now carry a
        # support the way lane share carries a core
        lane_ev = min(1.0, share / 30.0) * lane_shrink if lane else 0.0
        neutral = baseline.get(pos) or HERO_FLAT_SHARE
        hero_ev = min(1.0, hero_share[pos] / (neutral * 1.75)) * hero_shrink
        ev = max(lane_ev, hero_ev)
        conf = "measured" if ev >= 0.55 else "part-time" if ev >= 0.25 else "est"

        spread = clamp(d.get("skill_unc") or 200, 80, 600)
        why.sort(key=lambda w: -abs(w[1]))
        ratings[pos] = {
            "mmr": mmr,
            "rank": _mmr_to_rank_str(mmr),
            "conf": conf,
            "note": " · ".join(t for t, _ in why[:2]) or "no positional signal",
            "unc": round(spread * (1.6 - 0.8 * ev)),
            "delta": round(adj),
            "why": [{"reason": t, "mmr": round(v)} for t, v in why],
        }

    # primary role: best-rated position that has real evidence behind it
    evidenced = [p for p, r in ratings.items() if r["conf"] != "est"]
    primary = max(evidenced, key=lambda p: ratings[p]["mmr"]) if evidenced else None

    return {"primary": primary, "ratings": ratings,
            "note": "Pos 4/5 are separated by hero pool and farm profile — "
                    "OpenDota's lane data alone cannot tell them apart."}


def _percentile_scores(values):
    """Return average-rank 0..100 percentiles for non-None values."""
    known = sorted((value, index) for index, value in enumerate(values)
                   if value is not None)
    if not known:
        return {}
    if len(known) == 1:
        return {known[0][1]: 50.0}
    result = {}
    start = 0
    while start < len(known):
        end = start
        while end + 1 < len(known) and known[end + 1][0] == known[start][0]:
            end += 1
        percentile = ((start + end) / 2) / (len(known) - 1) * 100
        for _, index in known[start:end + 1]:
            result[index] = percentile
        start = end + 1
    return result


def _finalize_deep_and_role_metrics(all_data):
    samples = [
        sample
        for pd in all_data
        for sample in (pd["data"].get("deep_samples") or [])
        if sample.get("parsed")
    ]
    gold = sum(
        (sample.get("ally_lane_gold10") or 0)
        + (sample.get("enemy_lane_gold10") or 0)
        for sample in samples
    )
    xp = sum(
        (sample.get("ally_lane_xp10") or 0)
        + (sample.get("enemy_lane_xp10") or 0)
        for sample in samples
    )
    xp_weight = gold / xp if xp else 0.6

    for pd in all_data:
        d = pd["data"]
        results = []
        by_lane = {}
        for sample in d.get("deep_samples") or []:
            result = exact_lane_result(sample, xp_weight)
            if result is None:
                continue
            results.append(result)
            lane = LANE_NAMES.get(sample.get("lane_role"), "Unknown")
            lane_rows = by_lane.setdefault(
                lane, {"n": 0, "wins": 0, "draws": 0, "losses": 0}
            )
            lane_rows["n"] += 1
            result_key = {
                "win": "wins",
                "draw": "draws",
                "loss": "losses",
            }[result]
            lane_rows[result_key] += 1
        d["lane_win_n"] = len(results)
        d["lane_wins"] = results.count("win")
        d["lane_draws"] = results.count("draw")
        d["lane_losses"] = results.count("loss")
        d["lane_decided_n"] = d["lane_wins"] + d["lane_losses"]
        if d["lane_win_n"]:
            d["lane_win_pct"] = round(
                d["lane_wins"] / d["lane_win_n"] * 100, 1
            )
            d["lane_draw_pct"] = round(
                d["lane_draws"] / d["lane_win_n"] * 100, 1
            )
            d["lane_score_pct"] = round(
                (
                    d["lane_wins"] + 0.5 * d["lane_draws"]
                ) / d["lane_win_n"] * 100,
                1,
            )
        for lane, row in by_lane.items():
            row["win_pct"] = (
                round(row["wins"] / row["n"] * 100, 1) if row["n"] else None
            )
            row["draw_pct"] = (
                round(row["draws"] / row["n"] * 100, 1) if row["n"] else None
            )
        d["lane_results_by_lane"] = by_lane

        deward_rows = [
            sample for sample in (d.get("deep_samples") or [])
            if sample.get("parsed")
            and (sample.get("duration") or 0) > 0
            and sample.get("observer_kills") is not None
            and sample.get("sentry_kills") is not None
        ]
        d["deward_n"] = len(deward_rows)
        if deward_rows:
            duration30 = sum(row["duration"] for row in deward_rows) / 1800
            obs = sum(row["observer_kills"] for row in deward_rows)
            sentry = sum(row["sentry_kills"] for row in deward_rows)
            d["observer_kills_per30"] = round(obs / duration30, 2)
            d["sentry_kills_per30"] = round(sentry / duration30, 2)
            d["dewards_per30"] = round((obs + sentry) / duration30, 2)

        d["role_fit"] = role_fit(d)
        d["league_proof"] = league_proof(d)

    support_indexes = [
        index for index, pd in enumerate(all_data)
        if (
            pd["data"].get("role_fit", {}).get("best") in (4, 5)
            or any(pos in (4, 5)
                   for pos in pd["data"].get("role_fit", {}).get("secondary", []))
        )
    ]
    sentry_values = [
        pd["data"].get("sentry_per30") if index in support_indexes else None
        for index, pd in enumerate(all_data)
    ]
    deward_values = [
        pd["data"].get("dewards_per30") if index in support_indexes else None
        for index, pd in enumerate(all_data)
    ]
    sentry_pct = _percentile_scores(sentry_values)
    deward_pct = _percentile_scores(deward_values)
    for index in support_indexes:
        effort = sentry_pct.get(index)
        success = deward_pct.get(index)
        d = all_data[index]["data"]
        effort_rel = _shrink(d.get("vision_n") or 0, 20)
        success_rel = _shrink(d.get("deward_n") or 0, 5)
        if effort is not None:
            effort = 50 + (effort - 50) * effort_rel
        if success is not None:
            success = 50 + (success - 50) * success_rel
        if effort is not None and success is not None:
            d["vision_score"] = round(
                0.7 * effort + 0.3 * success, 1
            )
            d["vision_reliability"] = round(
                0.7 * effort_rel + 0.3 * success_rel, 3
            )
        elif effort is not None:
            d["vision_score"] = round(effort, 1)
            d["vision_reliability"] = round(effort_rel, 3)
        elif success is not None:
            d["vision_score"] = round(success, 1)
            d["vision_reliability"] = round(success_rel, 3)


def score_draft_values(all_data):
    """Assign a transparent pool-relative 0..100 draft-value score."""
    if not all_data:
        return
    value_inputs = []
    for pd in all_data:
        d = pd["data"]
        value_inputs.append(d.get("edge_cost"))
    value_pct = _percentile_scores(value_inputs)
    weights = {
        "auction": 0.55,
        "league": 0.15,
        "lane": 0.12,
        "role": 0.08,
        "vision": 0.05,
        "heroes": 0.05,
    }

    for index, pd in enumerate(all_data):
        d = pd["data"]
        proof = d.get("league_proof") or league_proof(d)
        league_n = int(d.get("esports_games") or 0)
        posterior = proof.get("posterior_wr")
        league_score = 50
        if posterior is not None and league_n:
            league_score = clamp(
                50 + (posterior - 50) * 2 * _shrink(league_n, 10),
                0, 100,
            )

        lane_n = int(d.get("lane_win_n") or 0)
        lane_wr = d.get("lane_score_pct")
        lane_score = 50
        if lane_wr is not None and lane_n:
            lane_score = clamp(
                50 + (lane_wr - 50) * 2 * _shrink(lane_n, 10),
                0, 100,
            )

        fit = d.get("role_fit") or {}
        role_score = (
            62 if fit.get("label") == "Versatile"
            else 55 if fit.get("label") == "Specialist"
            else 50
        )
        vision_score = d.get("vision_score")
        if vision_score is None:
            vision_score = 50
        labels = [row.get("label") for row in d.get("requested_heroes") or []]
        hero_score = clamp(
            50 + labels.count("Proven") * 6 + labels.count("Current") * 3
            + labels.count("Historical"),
            0, 100,
        )
        channels = {
            "auction": round(value_pct.get(index, 50), 1),
            "league": round(league_score, 1),
            "lane": round(lane_score, 1),
            "role": round(role_score, 1),
            "vision": round(vision_score, 1),
            "heroes": round(hero_score, 1),
        }
        d["draft_value_channels"] = channels
        d["draft_value_score"] = round(sum(
            channels[name] * weight for name, weight in weights.items()
        ))

        coverage = 0.0
        if value_inputs[index] is not None:
            coverage += weights["auction"]
        coverage += weights["league"] * _shrink(league_n, 20)
        coverage += weights["lane"] * _shrink(lane_n, 10)
        if fit.get("label") and fit.get("label") != "Unclear":
            coverage += weights["role"]
        if d.get("vision_score") is not None:
            coverage += (
                weights["vision"] * (d.get("vision_reliability") or 0)
            )
        if any(label != "No evidence" for label in labels):
            coverage += weights["heroes"]
        d["draft_value_confidence"] = (
            "high" if coverage >= 0.75
            else "medium" if coverage >= 0.5
            else "low"
        )
        evidence = []
        edge = d.get("edge_cost")
        if edge is not None and edge > 0:
            evidence.append(f"Estimated auction surplus: +${edge}")
        if proof.get("label") == "Proven winner":
            evidence.append(
                f"Verified league winner over {league_n} ticketed games"
            )
        if d.get("lane_win_pct") is not None and lane_n >= 2:
            evidence.append(
                f"Wins {d['lane_win_pct']}% of {lane_n} exact recent lanes"
            )
        if d.get("dewards_per30") is not None and d.get("deward_n"):
            evidence.append(
                f"{d['dewards_per30']} successful dewards/30 "
                f"over {d['deward_n']} matches"
            )
        if fit.get("label") == "Versatile":
            evidence.append(
                f"Credible fit at {len(fit.get('credible') or [])} positions"
            )
        hero_hits = sum(
            label in ("Proven", "Current") for label in labels
        )
        if hero_hits:
            evidence.append(
                f"{hero_hits} requested heroes have current/proven evidence"
            )

        risks = []
        if edge is None:
            risks.append("No reliable auction-edge estimate")
        if proof.get("label") in (
            "No verified history", "Limited sample", "Unavailable"
        ):
            risks.append(f"League proof: {proof.get('label', 'Unavailable')}")
        if lane_n < 3:
            risks.append(
                "Exact lane sample is "
                + ("unavailable" if not lane_n else f"only {lane_n}")
            )
        if fit.get("label") == "Unclear":
            risks.append("No position has credible role evidence")
        if (
            fit.get("best") in (4, 5)
            and (d.get("deward_n") or 0) < 3
        ):
            risks.append("Successful-deward sample is thin")
        d["draft_value_evidence"] = evidence[:3] or [
            "No channel is materially above neutral"
        ]
        d["draft_value_risks"] = risks[:3] or [
            "No major evidence-based risk identified"
        ]

    ranked = sorted(
        (
            (index, pd) for index, pd in enumerate(all_data)
            if pd["player"].get("draftable") == "Y"
            and pd["player"].get("captain") != "Y"
        ),
        key=lambda pair: (
            -(pair[1]["data"].get("draft_value_score") or 0),
            -(
                pair[1]["data"]["edge_cost"]
                if pair[1]["data"].get("edge_cost") is not None
                else -9999
            ),
            str(pair[1]["player"].get("name") or "").lower(),
        ),
    )
    for pd in all_data:
        pd["data"]["draft_value_rank"] = None
    for rank, (_, pd) in enumerate(ranked, 1):
        d = pd["data"]
        d["draft_value_rank"] = rank
        edge = d.get("edge_cost")
        fit = d.get("role_fit") or {}
        role = fit.get("best")
        role_text = f"Pos {role}" if role else "role unclear"
        edge_text = (
            f"{edge:+d} auction edge" if edge is not None
            else "price evidence limited"
        )
        d["draft_value_verdict"] = f"{edge_text}; best fit {role_text}"


def _exp_phrase(total):
    if not total:
        return "has little public match history"
    if total >= 10000:
        return f"is a hardened veteran of {total:,}+ games"
    if total >= 5000:
        return f"is a seasoned ~{total:,}-game player"
    if total >= 2000:
        return f"is an experienced ~{total:,}-game player"
    if total >= 500:
        return f"is a developing player (~{total:,} games)"
    return f"is relatively new (~{total:,} games on record)"


def career_narrative(p, d):
    """Template-based, caster-ready scouting summary (no LLM).

    Assembled entirely from computed fields. Note: OpenDota exposes no
    account-creation date, so tenure is approximated from total game volume.
    """
    name = p.get("name", "This player")
    parts = []

    pr = position_ratings(d)
    primary = pr.get("primary")
    role_txt = ""
    if primary:
        role_txt = f", mainly a {POS_NAMES[primary].split(' (')[0].lower()} player"
    medal = d["rank_str"] if d["rank_str"] != "?" else "an uncalibrated"
    parts.append(f"{name} {_exp_phrase(d['total_matches'])}{role_txt}. "
                 f"Ranked {medal} on OpenDota.")

    if d["adj_skill"] is not None:
        vt = value_tier(d)
        s = f"Plays like about {d['adj_skill']} MMR"
        if d["skill_unc"]:
            s += f" (±{d['skill_unc']})"
        if vt != "—":
            s += f" — value tier {vt}"
        parts.append(s + ".")
    if d["punches_above"]:
        parts.append(f"Queues into {d['lobby_rank_str']} lobbies, above their own "
                     f"{d['rank_str']} medal.")

    lmd = d["last_match_days"]
    if lmd is not None:
        if lmd <= 7:
            parts.append("Currently active.")
        elif lmd <= 30:
            parts.append(f"Fairly active (last game {lmd} days ago).")
        else:
            parts.append(f"Has been quiet — last game {lmd} days ago.")

    if d["esports_status"] == "unavailable":
        parts.append("Verified OpenDota ticketed-match history is unavailable.")
    elif d["esports_games"]:
        s = (
            f"OpenDota records {d['esports_games']} ticketed matches across "
            f"{d['esports_league_count']} leagues at {d['esports_winrate']}% WR."
        )
        if d["esports_6mo_games"]:
            s += (
                f" In the last 6 months: {d['esports_6mo_wins']}-"
                f"{d['esports_6mo_losses']} ({d['esports_6mo_winrate']}%)."
            )
        parts.append(s)
    else:
        parts.append("No OpenDota ticketed matches found.")

    if d["use_n"] >= 10:
        parts.append(f"On US East (the LD2L server) they're {d['use_w']}-"
                     f"{d['use_n'] - d['use_w']} ({d['use_wr']}%) over the sample.")

    if d.get("last_cost") and d.get("last_cost_season"):
        parts.append(f"Went for ${d['last_cost']} at their {d['last_cost_season']} draft.")

    return " ".join(parts)
