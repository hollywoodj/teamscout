"""Derived scouting signals from OpenDota raw data."""

import statistics
from datetime import datetime, timezone

from . import config

MEDALS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
          5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}

LANE_NAMES = {1: "Safe", 2: "Mid", 3: "Off", 4: "Jungle"}


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
    return (stars // 5 + 1) * 10 + (stars % 5 + 1)


def approx_mmr_from_tier(tier):
    """Midpoint MMR implied by a medal (each star ~154 MMR from Herald 1 = 0)."""
    stars = tier_to_stars(tier)
    if stars is None:
        return None
    if tier >= 80:
        return 5600
    return stars * 154 + 77


def days_since(unix_ts):
    if not unix_ts:
        return None
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - dt).days


def _won(m):
    is_radiant = m.get("player_slot", 0) < 128
    return is_radiant == bool(m.get("radiant_win"))


def _wl_rate(wl):
    if not wl:
        return None
    w, l = wl.get("win", 0), wl.get("lose", 0)
    total = w + l
    if total == 0:
        return None
    return {"wins": w, "losses": l, "games": total, "winrate": round(w / total * 100, 1)}


def build_metrics(player, sections, hero_map):
    """Turn raw cached sections into the scouting data dict used by reports."""
    d = {
        "rank_tier": None, "rank_str": "?",
        "approx_mmr": None, "mmr_gap": None, "mmr_check": "",
        "wins": 0, "losses": 0, "winrate": 0, "total_matches": 0,
        "form30": None, "form90": None,
        "last_match_days": None, "avg_kda": 0, "avg_gpm": 0, "avg_xpm": 0,
        "recent_heroes": [], "top_heroes": [], "versatility": 0,
        "signature_heroes": [],
        # lobby quality (average_rank based)
        "lobby_median_tier": None, "lobby_rank_str": "—", "lobby_sample": 0,
        "punches_above": False, "punch_gap_stars": None,
        # queue habits
        "solo_pct": None, "solo_wr": None, "party_wr": None,
        "solo_n": 0, "party_n": 0,
        # actual lanes (parsed matches only)
        "lane_str": "—", "lane_n": 0, "lane_pcts": {},
        # real league history (leagueid > 0)
        "league_matches": 0, "league_wins": 0, "league_losses": 0,
        "league_winrate": 0, "league_heroes": [], "has_league_exp": False,
        # auction history (filled in by auction.annotate_players)
        "est_cost": None, "last_cost": None, "last_cost_season": None,
        "last_draft_mmr": None, "was_captain_last": False,
    }

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

    # ---- recent matches: activity + KDA/GPM/XPM ----
    recent = sections.get("recent") or []
    if isinstance(recent, list) and recent:
        d["last_match_days"] = days_since(recent[0].get("start_time"))
        kills = sum(m.get("kills", 0) for m in recent)
        deaths = sum(m.get("deaths", 0) for m in recent)
        assists = sum(m.get("assists", 0) for m in recent)
        gpms = [m["gold_per_min"] for m in recent if m.get("gold_per_min")]
        xpms = [m["xp_per_min"] for m in recent if m.get("xp_per_min")]
        d["avg_kda"] = round((kills + assists) / max(deaths, 1), 2)
        d["avg_gpm"] = round(sum(gpms) / len(gpms)) if gpms else 0
        d["avg_xpm"] = round(sum(xpms) / len(xpms)) if xpms else 0
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
            games, wins = int(h.get("games", 0)), int(h.get("win", 0))
            if games >= config.SIGNATURE_MIN_GAMES:
                wr = round(wins / games * 100, 1)
                if wr >= config.SIGNATURE_MIN_WINRATE:
                    d["signature_heroes"].append({
                        "hero": hero_map.name(int(h["hero_id"])),
                        "games": games, "wins": wins, "winrate": wr,
                    })
        d["signature_heroes"].sort(key=lambda s: -s["winrate"])

    # ---- match sample: lobby rank, solo/party, lanes, league games ----
    matches = sections.get("matches") or []
    if isinstance(matches, list) and matches:
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

        # League/inhouse games: practice or tournament lobbies played as Captains
        # Mode or full 10-stacks. (OpenDota's player-matches projection does NOT
        # populate leagueid, so lobby fingerprint is the reliable signal.)
        for m in matches:
            if m.get("lobby_type") not in (1, 2):
                continue
            if m.get("game_mode") != 2 and m.get("party_size") != 10:
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

    return d


def value_tier(mmr, d):
    """S-F tier from listed MMR, with performance/activity markers."""
    bonus = ""
    if d["winrate"] > 53 and d["total_matches"] > 200:
        bonus = " ↑WR"
    if d["last_match_days"] is not None and d["last_match_days"] > config.INACTIVE_DAYS:
        bonus += " ⚠INACTIVE"
    if mmr >= 4300: return "S - Elite" + bonus
    if mmr >= 4000: return "A - Premium" + bonus
    if mmr >= 3500: return "B - Solid" + bonus
    if mmr >= 3000: return "C - Average" + bonus
    if mmr >= 2500: return "D - Budget" + bonus
    if mmr >= 2000: return "E - Bargain" + bonus
    return "F - Minimum" + bonus


def is_strong_value_signal(d):
    """A single signal strong enough to justify a Value Picks entry on its own."""
    f30 = d["form30"]
    return (d["punches_above"]
            or (d["mmr_gap"] is not None and d["mmr_gap"] >= config.MMR_CHECK_GAP)
            or (f30 and f30["games"] >= 20 and f30["winrate"] >= 58)
            or (d["solo_wr"] is not None and d["solo_wr"] >= 55 and d["solo_n"] >= 30))


def value_pick_signals(p, d):
    """Reasons a player may outperform their MMR, and risk flags."""
    reasons, risks = [], []
    mmr = p["mmr"]

    # NB: thresholds are calibrated to LD2L signups, where a 5000-game veteran
    # with league experience is the norm — only genuinely unusual traits count.
    if d["winrate"] > 52 and d["total_matches"] > 200 and mmr < 3000:
        reasons.append(f"Win% {d['winrate']}% over {d['total_matches']} games at only {mmr} MMR")
    if d["total_matches"] > 8000:
        reasons.append(f"{d['total_matches']} total games - extremely experienced")
    if d["avg_kda"] > 4.5:
        reasons.append(f"Recent KDA {d['avg_kda']} - performing well")
    f30 = d["form30"]
    if f30 and f30["games"] >= 20 and f30["winrate"] >= 58:
        reasons.append(f"Hot streak: {f30['winrate']}% over last 30d ({f30['games']}g)")
    if d["mmr_gap"] is not None and d["mmr_gap"] >= config.MMR_CHECK_GAP:
        reasons.append(f"Medal {d['rank_str']} implies ~{d['approx_mmr']} MMR vs {mmr} listed")
    if d["punches_above"]:
        reasons.append(f"Queues into {d['lobby_rank_str']} lobbies (median) vs own {d['rank_str']}")
    if d["solo_wr"] is not None and d["solo_wr"] >= 55 and d["solo_n"] >= 30:
        reasons.append(f"Solo queue {d['solo_wr']}% WR ({d['solo_n']}g) - self-sufficient")
    # (versatility deliberately not a reason: lifetime unique-heroes is ~max
    # for every veteran account, so it can't differentiate LD2L signups)
    if len(d["signature_heroes"]) >= 5:
        names = [s["hero"] for s in d["signature_heroes"][:3]]
        reasons.append(f"{len(d['signature_heroes'])} signature heroes inc. {', '.join(names)}")
    if d["league_matches"] >= 30:
        reasons.append(f"{d['league_matches']} league games in last 6mo ({d['league_winrate']}% WR)")
    if mmr <= 1000 and d["total_matches"] > 500:
        reasons.append(f"Listed at minimum MMR but {d['total_matches']} games played")
    if d["last_draft_mmr"] and mmr and d["last_draft_mmr"] - mmr >= 300:
        reasons.append(f"Listed {mmr} now vs {d['last_draft_mmr']} at their "
                       f"{d['last_cost_season']} draft (-{d['last_draft_mmr'] - mmr})")

    if d["last_match_days"] is not None and d["last_match_days"] > 60:
        risks.append(f"Inactive {d['last_match_days']}d")
    if d["winrate"] < 48 and d["total_matches"] > 200:
        risks.append(f"Sub-48% WR over {d['total_matches']} games")
    if f30 and f30["games"] >= 20 and f30["winrate"] <= 42:
        risks.append(f"Cold streak: {f30['winrate']}% over last 30d")
    if d["mmr_gap"] is not None and d["mmr_gap"] <= -config.MMR_CHECK_GAP:
        risks.append(f"Listed {mmr} but medal {d['rank_str']} implies ~{d['approx_mmr']}")
    if d["total_matches"] < 100:
        risks.append("Very few games on record")
    if not p.get("mmr_valid") and not p.get("mmr_screenshot"):
        risks.append("MMR not validated")

    return reasons, risks
