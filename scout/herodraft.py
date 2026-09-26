"""Hero draft practice — Captains Mode pick/ban against a scouting-driven bot.

Practice the ACTUAL Dota draft (heroes, not players) against the team you're
about to face. Fully local; nothing is sent to ld2l.org or Steam.

  - Rosters: pick the same BBC / Team Scout teams you're scouting, or assemble
    from the cached signup pool (persisted to herodraft_teams.json).
  - The bot drafts for the enemy from Team Scout's official pick/ban book
    (first-pick openers, undefeated and most successful heroes, their real
    bans), each roster player's OWN official hero record (a player who is
    3-0 on a hero in league play reaches for it again), and each player's
    lifetime / 180-day / league comfort. Bans deny YOUR comfort heroes and
    signature openers the same way, and are discounted when the banner
    would rather just pick the hero.
  - Role coverage: every pick is scored against the seats (pos 1-5) the
    team's earlier picks already cover, so the bot doesn't stack three
    carries, and each pick is seated with the player whose comfort AND
    measured position fit it best.
  - Patch meta: OpenDota's live bracket winrates + matchup matrix (when
    online) plus a curated, hand-editable current-patch tier list
    (scout/meta_heroes.json) so key meta heroes are recognised offline.
  - Draft order is the Captains Mode sequence introduced in 7.34 and still
    current on 7.41f: first-pick bans 3-2-2 / second-pick 4-1-2, picks 1-3-1
    both sides, 15s first ban phase, 30s everything else, 130s reserve each.
    Timed out ban = no ban; timed out pick = random hero — as in the client.
  - First pick / side can be chosen or coin-flipped in the UI.

Runs standalone (--herodraft, ThreadingHTTPServer + JSON polling) or embedded
in Team Scout behind its sign-in (HeroDraftHub: one draft per sign-in).
"""

import json
import math
import os
import random
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .analysis import is_organized_match
from .cache import Cache
from .creators import creator_signal, creator_value, refresh_creators
from .fetch import fetch_player_sections, players_from_snapshot
from .hero_positions import POS_WEIGHTS, affinity
from .heroes import HERO_FALLBACK
from .opendota import OpenDota

# --------------------------------------------------------------------------
# Captains Mode sequence — patch 7.40 (verified vs Liquipedia, 2025-12-15).
# Team F = first pick, S = second pick. 14 bans + 10 picks = 24 steps.
# --------------------------------------------------------------------------

F, S = 0, 1
CM_PHASES = [
    ("ban",  [F, F, S, S, F, S, S], config.HERODRAFT_BAN1_SECONDS),
    ("pick", [F, S],                config.HERODRAFT_STEP_SECONDS),
    ("ban",  [F, F, S],             config.HERODRAFT_STEP_SECONDS),
    ("pick", [S, F, F, S, S, F],    config.HERODRAFT_STEP_SECONDS),
    ("ban",  [F, S, F, S],          config.HERODRAFT_STEP_SECONDS),
    ("pick", [F, S],                config.HERODRAFT_STEP_SECONDS),
]

def _build_sequence():
    """Flatten CM_PHASES -> [{type, team(F/S), secs, phase_idx}] (24 steps)."""
    seq = []
    for pi, (kind, teams, secs) in enumerate(CM_PHASES):
        for t in teams:
            seq.append({"type": kind, "team": t, "secs": secs, "phase": pi})
    return seq

CM_SEQUENCE = _build_sequence()


# --------------------------------------------------------------------------
# Hero constants (id -> name / img key / attribute)
# --------------------------------------------------------------------------

def load_full_heroes(od, cache, offline=False):
    """Rich hero map {id: {n, key, attr}}; key is the Steam CDN image slug.

    Fresh cache -> API (unless offline) -> stale cache -> bundled names only.
    """
    blob = cache.get_blob("heroes_full",
                          max_age_hours=config.HEROES_CONSTANTS_TTL_HOURS)
    if not blob and not offline:
        data = od.constants_heroes()
        if data and isinstance(data, dict):
            blob = {}
            for k, h in data.items():
                try:
                    hid = int(k)
                except (TypeError, ValueError):
                    continue
                blob[str(hid)] = {
                    "n": h.get("localized_name") or f"Hero#{hid}",
                    "key": (h.get("name") or "").replace("npc_dota_hero_", ""),
                    "attr": h.get("primary_attr") or "all",
                }
            if blob:
                cache.set_blob("heroes_full", blob)
    if not blob:
        blob = cache.get_blob("heroes_full")  # stale beats nothing
    if not blob:
        blob = {str(k): {"n": v, "key": "", "attr": "all"}
                for k, v in HERO_FALLBACK.items()}
    return {int(k): dict(v) for k, v in blob.items()}


# --------------------------------------------------------------------------
# Player hero profiles + comfort scoring
# --------------------------------------------------------------------------

def _won(m):
    return (m.get("player_slot", 0) < 128) == bool(m.get("radiant_win"))


def build_profile(player, sections):
    """One player's hero evidence: lifetime, 180d form, league games."""
    heroes = {}
    for h in sections.get("heroes") or []:
        try:
            hid, g = int(h["hero_id"]), int(h.get("games", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if g:
            heroes[hid] = {"g": g, "w": int(h.get("win", 0)),
                           "last": int(h.get("last_played", 0) or 0)}
    recent, league = {}, {}
    for m in sections.get("matches") or []:
        hid = m.get("hero_id")
        if not hid:
            continue
        recent[hid] = recent.get(hid, 0) + 1
        if is_organized_match(m):
            e = league.setdefault(hid, {"g": 0, "w": 0})
            e["g"] += 1
            e["w"] += 1 if _won(m) else 0
    return {
        "steam32": player["steam32"],
        "name": player["name"],
        "mmr": player.get("mmr") or 0,
        "pref_role": player.get("pref_role") or "Any",
        "heroes": heroes, "recent": recent, "league": league,
        # {hid: {g, w}} from BBC / league official matches, attached by
        # load_league_context when Team Scout data is available.
        "official": {},
    }


def is_undefeated(rec, min_games=None):
    """True for a {g, w} record with no losses and enough games to count."""
    if not rec:
        return False
    min_games = (config.HERODRAFT_UNDEFEATED_MIN_GAMES
                 if min_games is None else min_games)
    g, w = int(rec.get("g") or 0), int(rec.get("w") or 0)
    return g >= min_games and w == g


def player_affinity(prof):
    """Cached {pos: share} of where this player's hero pool actually sits."""
    aff = prof.get("_aff")
    if aff is None:
        games = {hid: e["g"] for hid, e in (prof.get("heroes") or {}).items()}
        aff, _ = affinity(games)
        prof["_aff"] = aff
    return aff


def hero_score(prof, hid, now=None):
    """Comfort score (0..~2) of this hero for this player, with a reason.

    Volume × quality on lifetime stats, decayed if unplayed for months, plus
    current-form and league-play bonuses. Returns (score, reason_str).
    """
    now = now or time.time()
    score, bits = 0.0, []
    off = (prof.get("official") or {}).get(hid)
    if off and off.get("g"):
        bonus = min(config.HERODRAFT_OFFICIAL_BONUS_CAP,
                    config.HERODRAFT_OFFICIAL_BONUS * off["g"])
        wr = off["w"] / off["g"]
        score += bonus * (0.5 + wr)        # 0-2 counts a little, 2-0 a lot
        tag = f"{off['w']}–{off['g'] - off['w']} in officials"
        if is_undefeated(off):
            score += config.HERODRAFT_UNDEFEATED_PLAYER_BONUS
            tag += " (undefeated)"
        bits.append(tag)
    e = prof["heroes"].get(hid)
    if e:
        pw, pg = config.HERODRAFT_WR_PRIOR
        wr = (e["w"] + pw) / (e["g"] + pg)
        vol = min(1.0, math.log1p(e["g"])
                  / math.log1p(config.HERODRAFT_FULL_COMFORT_GAMES))
        score = vol * (0.35 + max(0.0, wr - 0.35))
        raw_wr = round(e["w"] / e["g"] * 100) if e["g"] else 0
        bits.append(f"{e['g']}g {raw_wr}% lifetime")
        days = (now - e["last"]) / 86400 if e.get("last") else 9999
        if days > 365:
            score *= config.HERODRAFT_STALE_365D
            bits.append("shelved 1y+")
        elif days > 180:
            score *= config.HERODRAFT_STALE_180D
            bits.append("shelved 6mo+")
    rec = prof["recent"].get(hid, 0)
    if rec:
        score += min(config.HERODRAFT_RECENT_BONUS_CAP,
                     config.HERODRAFT_RECENT_BONUS * rec)
        bits.append(f"{rec} in last 6mo")
    lg = prof["league"].get(hid)
    if lg and lg["g"]:
        bonus = min(config.HERODRAFT_LEAGUE_BONUS_CAP,
                    config.HERODRAFT_LEAGUE_BONUS * lg["g"])
        score += bonus * (0.7 + 0.6 * lg["w"] / lg["g"])
        bits.append(f"{lg['g']} league game{'s' if lg['g'] > 1 else ''}")
    return score, ", ".join(bits)


def team_threats(profiles, now=None):
    """{hid: (threat, reason)} for a roster — best player + stacked-comfort credit."""
    now = now or time.time()
    per_hero = {}
    for prof in profiles:
        hids = (set(prof["heroes"]) | set(prof["recent"]) | set(prof["league"])
                | set(prof.get("official") or {}))
        for hid in hids:
            s, why = hero_score(prof, hid, now)
            if s > 0.05:
                per_hero.setdefault(hid, []).append((s, prof["name"], why))
    out = {}
    for hid, entries in per_hero.items():
        entries.sort(reverse=True)
        threat = entries[0][0]
        if len(entries) > 1:
            threat += config.HERODRAFT_STACK_WEIGHT * entries[1][0]
        s, name, why = entries[0]
        out[hid] = (threat, f"{name}: {why}")
    return out


# --------------------------------------------------------------------------
# Team Scout official draft book (same matches as --teamscout)
# --------------------------------------------------------------------------

def first_pick_side(picks_bans):
    """Radiant=0 / Dire=1 of the first actual pick, or None if no draft data."""
    picks = []
    for i, entry in enumerate(picks_bans or []):
        if not entry.get("is_pick"):
            continue
        order = entry.get("order")
        order = i if order is None else order
        picks.append((order, 1 if entry.get("team") == 1 else 0))
    if not picks:
        return None
    picks.sort()
    return picks[0][1]


def _stat():
    return {"g": 0, "w": 0}


def build_draft_book(team_matches, team_key):
    """Pick/ban frequencies for one BBC team_key from Team Scout match rows.

    picks   {hid: {g, w, slots: {pick_index: {g, w}}}}  team record per hero
    openers {is_first_pick: {hid: {g, w}}}               their first pick
    bans    {hid: n}                                      bans they make
    players {steam32: {hid: {g, w}}}                      who played what
    """
    picks, bans = {}, {}
    openers = {True: {}, False: {}}
    players = {}
    games = 0
    for match in team_matches or []:
        radiant = (match.get("radiant") or {}).get("team_key")
        dire = (match.get("dire") or {}).get("team_key")
        if radiant == team_key:
            team_num, win = 0, bool(match.get("radiant_win"))
        elif dire == team_key:
            team_num, win = 1, not bool(match.get("radiant_win"))
        else:
            continue
        games += 1
        side_rows = ((match.get("radiant") if team_num == 0 else match.get("dire"))
                     or {}).get("players") or []
        for row in side_rows:
            try:
                sid, hid = int(row.get("id")), int(row.get("hero_id"))
            except (TypeError, ValueError):
                continue
            rec = players.setdefault(sid, {}).setdefault(hid, _stat())
            rec["g"] += 1
            rec["w"] += int(win)
        pb = match.get("picks_bans") or []
        fp = first_pick_side(pb)
        is_fp = fp is not None and fp == team_num
        their_picks = []
        for entry in pb:
            try:
                hid = int(entry.get("hero_id"))
            except (TypeError, ValueError):
                continue
            side = 1 if entry.get("team") == 1 else 0
            if side != team_num:
                continue
            if entry.get("is_pick"):
                their_picks.append(hid)
            else:
                bans[hid] = bans.get(hid, 0) + 1
        if their_picks:
            opener = openers[is_fp].setdefault(their_picks[0], _stat())
            opener["g"] += 1
            opener["w"] += int(win)
        for slot, hid in enumerate(their_picks):
            rec = picks.setdefault(hid, {"g": 0, "w": 0, "slots": {}})
            rec["g"] += 1
            rec["w"] += int(win)
            sl = rec["slots"].setdefault(slot, _stat())
            sl["g"] += 1
            sl["w"] += int(win)
    return {"games": games, "picks": picks, "openers": openers, "bans": bans,
            "players": players}


def record_edge(rec):
    """Success-ranked evidence for a {g, w} record: shrunk winrate above 50%
    scaled by sqrt(games), so 3-0 (+0.52) > 6-4 (+0.29) > 5-5 (0) > 0-3.
    A raw games×winrate product would rank a 5-5 habit above a 3-0 hero."""
    g, w = int(rec.get("g") or 0), int(rec.get("w") or 0)
    if not g:
        return 0.0
    wr = (w + 1) / (g + 2)
    return (wr - 0.5) * math.sqrt(g)


def undefeated_bonus(rec):
    if not is_undefeated(rec):
        return 0.0
    extra = rec["g"] - config.HERODRAFT_UNDEFEATED_MIN_GAMES
    return min(config.HERODRAFT_UNDEFEATED_TEAM_CAP,
               config.HERODRAFT_UNDEFEATED_TEAM_BONUS
               + config.HERODRAFT_UNDEFEATED_TEAM_STEP * extra)


def scout_pick_value(book, hid, pick_index, is_first_pick_team):
    """How strongly this team's official drafts point at hid right now.

    Success-ranked, not volume-ranked: the record's edge (record_edge), a
    small familiarity credit for simply being in their draft pool, an
    undefeated bonus that grows with the streak, slot habit, and on the
    opening pick their first-pick record with the hero.
    """
    if not book:
        return 0.0
    try:
        hid = int(hid)
    except (TypeError, ValueError):
        return 0.0
    score = 0.0
    rec = book["picks"].get(hid)
    if rec and rec["g"]:
        score += 2.0 * record_edge(rec)
        score += 0.25 * min(1.0, rec["g"] / 4.0)
        score += undefeated_bonus(rec)
        sl = rec.get("slots", {}).get(pick_index)
        if sl and sl["g"]:
            score += 0.15 * sl["g"]
    if pick_index == 0:
        opener = book["openers"].get(bool(is_first_pick_team), {}).get(hid)
        if opener and opener["g"]:
            # Wins on the opener dominate: 3-0 first pick >> 0-3 habit.
            score += opener["w"] * 0.6 + (opener["g"] - opener["w"]) * 0.05
    return score


def book_cards(book, names=None, limit=None):
    """Success-ranked hero cards from a team's official book, for the hints
    drawer: undefeated heroes first, then by record edge. names maps
    steam32 -> display name for the 'who' line."""
    if not book or not book.get("picks"):
        return []
    limit = limit or config.HERODRAFT_SCOUT_CARDS
    names = names or {}
    who_by_hero = {}
    for sid, recs in (book.get("players") or {}).items():
        for hid, rec in recs.items():
            cur = who_by_hero.get(hid)
            if cur is None or (rec["w"], rec["g"]) > (cur[1]["w"], cur[1]["g"]):
                who_by_hero[hid] = (sid, rec)
    cards = []
    for hid, rec in book["picks"].items():
        if not rec["g"]:
            continue
        und = is_undefeated(rec)
        who = ""
        hit = who_by_hero.get(hid)
        if hit:
            sid, prec = hit
            who = f"{names.get(sid, sid)} {prec['w']}–{prec['g'] - prec['w']}"
        cards.append({
            "hid": hid, "g": rec["g"], "w": rec["w"], "undefeated": und,
            "edge": round(record_edge(rec), 2), "who": who,
        })
    cards.sort(key=lambda c: (-int(c["undefeated"]), -c["edge"], -c["g"]))
    return cards[:limit]


def scout_ban_value(book, hid):
    if not book:
        return 0.0
    try:
        hid = int(hid)
    except (TypeError, ValueError):
        return 0.0
    return book["bans"].get(hid, 0) * 0.55


def scout_why(book, hid, kind, pick_index, is_first_pick_team):
    """Short feed line from the official book, or ''."""
    if not book:
        return ""
    try:
        hid = int(hid)
    except (TypeError, ValueError):
        return ""
    if kind == "ban":
        n = book["bans"].get(hid, 0)
        return f"banned {n}× in LD2L" if n else ""
    if pick_index == 0:
        opener = book["openers"].get(bool(is_first_pick_team), {}).get(hid)
        if opener and opener["g"]:
            losses = opener["g"] - opener["w"]
            tag = "first-picked" if is_first_pick_team else "opened"
            return f"{tag} {opener['w']}–{losses} in LD2L"
    rec = book["picks"].get(hid)
    if rec and rec["g"]:
        tag = "undefeated " if is_undefeated(rec) else ""
        return f"{tag}{rec['w']}–{rec['g'] - rec['w']} official"
    return ""


def load_league_context(od, cache, profiles, rows, offline=True):
    """BBC teams + official draft books, same source as Team Scout.

    Players on posted/override rosters who aren't in the signup snapshot are
    appended to `rows` / `profiles` so the picker can seat them.
    """
    from .bbc_source import load_bbc_data
    from .heroes import load_hero_map
    from .overrides import load_overrides
    from .team_scout import assemble_team

    hero_map = load_hero_map(od, cache, offline=offline)
    bbc = load_bbc_data(hero_map)
    overrides = load_overrides()
    # Team Scout stores each sign-in's roster edits in its own bucket. Fold
    # those into the shared maps so a locked team's posted lineup still seats.
    for bucket in (overrides.get("accounts") or {}).values():
        if not isinstance(bucket, dict):
            continue
        overrides["rosters"].update(bucket.get("rosters") or {})
        overrides["replaced"].update(bucket.get("replaced") or {})
    id_to_name = {p["steam32"]: p["name"] for p in rows}
    for sid, info in (bbc.get("players") or {}).items():
        id_to_name.setdefault(sid, info.get("name") or f"Player {sid}")
    teams, books = [], {}
    extra_ids = []
    for team in bbc.get("teams") or []:
        assembled = assemble_team(
            team, overrides, id_to_name, bbc.get("team_games"))
        key = assembled["key"]
        roster = list(assembled.get("roster") or [])[:5]
        teams.append({
            "key": key,
            "name": assembled.get("name") or key,
            "short": assembled.get("short") or assembled.get("name") or key,
            "roster": roster,
        })
        books[key] = build_draft_book(bbc.get("teamMatches") or [], key)
        extra_ids.extend(roster)
    known = {p["steam32"] for p in rows}
    for sid in extra_ids:
        if sid in known:
            continue
        info = (bbc.get("players") or {}).get(sid) or {}
        player = {
            "steam32": sid,
            "name": info.get("name") or id_to_name.get(sid) or f"Player {sid}",
            "mmr": 0,
            "pref_role": "Any",
        }
        sections, _ = fetch_player_sections(od, cache, player, offline=True)
        profiles[sid] = build_profile(player, sections)
        rows.append({"steam32": sid, "name": player["name"],
                     "mmr": 0, "role": "Any"})
        known.add(sid)
    # Each player's own official hero record - the strongest comfort signal.
    for sid, matches in (bbc.get("official") or {}).items():
        prof = profiles.get(sid)
        if not prof:
            continue
        recs = {}
        for row in matches or []:
            try:
                hid = int(row.get("hero_id"))
            except (TypeError, ValueError):
                continue
            rec = recs.setdefault(hid, _stat())
            rec["g"] += 1
            rec["w"] += 1 if row.get("result") == "W" else 0
        prof["official"] = recs
        prof.pop("_aff", None)
    rows.sort(key=lambda r: -r["mmr"])
    teams.sort(key=lambda t: t["name"].casefold())
    return {"teams": teams, "books": books}


# --------------------------------------------------------------------------
# Curated current-patch meta (scout/meta_heroes.json) + role coverage
# --------------------------------------------------------------------------

META_HEROES_FILE = os.path.join(os.path.dirname(__file__), "meta_heroes.json")


def load_meta_heroes(heroes, path=None, creators=None):
    """{patch, updated, sources, heroes: {hid: {tier, pos, note, creators}}}.

    Names are resolved against the live hero map first, then the bundled
    fallback names, so a Valve rename doesn't silently drop a hero.
    `creators` is creators.creator_signal()'s {hero name: [video rows]}; a
    hero named only by creators still gets a tag (tier "") so it is on the
    bot's radar and carries the video reference in the hints."""
    empty = {"patch": "", "updated": "", "sources": [], "heroes": {}}
    try:
        with open(path or META_HEROES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    by_name = {}
    for hid, h in (heroes or {}).items():
        name = h.get("n") if isinstance(h, dict) else h
        if name:
            by_name[str(name).casefold()] = int(hid)
    for hid, name in HERO_FALLBACK.items():
        by_name.setdefault(name.casefold(), hid)
    tags = {}
    for name, info in (data.get("heroes") or {}).items():
        hid = by_name.get(str(name).casefold())
        if hid is None or not isinstance(info, dict):
            continue
        tier = str(info.get("tier") or "").upper()
        if tier not in config.HERODRAFT_META_TIER_VALUE:
            continue
        pos = []
        for p in info.get("pos") or []:
            try:
                p = int(p)
            except (TypeError, ValueError):
                continue
            if 1 <= p <= 5:
                pos.append(p)
        tags[hid] = {"tier": tier, "pos": pos,
                     "note": str(info.get("note") or "")[:160], "creators": []}
    for name, rows in (creators or {}).items():
        hid = by_name.get(str(name).casefold())
        if hid is None or not rows:
            continue
        tag = tags.setdefault(hid, {"tier": "", "pos": [], "note": "", "creators": []})
        tag["creators"] = [dict(r) for r in rows]
        for r in rows:
            for p in r.get("pos") or []:
                if p not in tag["pos"]:
                    tag["pos"].append(p)
    if not tags:
        return empty
    return {"patch": str(data.get("patch") or "")[:16],
            "updated": str(data.get("updated") or "")[:32],
            "sources": [str(x) for x in (data.get("sources") or [])],
            "heroes": tags}


def meta_value(tags, hid):
    """Curated tier value plus the creator-video credit."""
    info = (tags or {}).get(hid)
    if not info:
        return 0.0
    return round(config.HERODRAFT_META_TIER_VALUE.get(info.get("tier"), 0.0)
                 + creator_value(info.get("creators")), 2)


def creator_names(tags, hid):
    info = (tags or {}).get(hid) or {}
    seen = []
    for r in info.get("creators") or []:
        who = r.get("who")
        if who and who not in seen:
            seen.append(who)
    return seen


def creator_videos(tags, limit=10):
    """Recent creator videos across all tagged heroes, newest first, for the
    hints drawer: [{who, title, date, url, heroes: [hid...]}]."""
    by_key = {}
    for hid, info in (tags or {}).items():
        for r in info.get("creators") or []:
            key = r.get("url") or r.get("title")
            row = by_key.setdefault(key, {"who": r.get("who"), "title": r.get("title"),
                                          "date": r.get("date"), "url": r.get("url"),
                                          "heroes": []})
            if hid not in row["heroes"]:
                row["heroes"].append(hid)
    rows = sorted(by_key.values(), key=lambda r: r.get("date") or "", reverse=True)
    return rows[:limit]


def role_coverage(picks):
    """{pos: 0..1} how much of each seat the picked heroes already cover."""
    cov = {p: 0.0 for p in range(1, 6)}
    for hid in picks:
        for pos, w in POS_WEIGHTS.get(hid, {}).items():
            cov[pos] = min(1.0, cov[pos] + w)
    return cov


def role_fill(picks, hid):
    """0..1 share of hid's positional profile that lands on still-open seats,
    or None when the hero has no position prior."""
    w = POS_WEIGHTS.get(hid)
    if not w:
        return None
    cov = role_coverage(picks)
    return sum(share * (1.0 - cov[pos]) for pos, share in w.items())


def role_term(picks, hid):
    """Signed role-coverage term for a candidate pick (before the weight)."""
    fill = role_fill(picks, hid)
    if fill is None:
        return 0.0
    idx = min(len(picks), len(config.HERODRAFT_ROLE_URGENCY) - 1)
    return (fill - 0.5) * config.HERODRAFT_ROLE_URGENCY[idx]


# --------------------------------------------------------------------------
# Hero meta: patch winrates + vs-matchups + 'with' coverage synergy
# --------------------------------------------------------------------------

def _coverage_synergy(adv, top_meta):
    """Pairwise 'with' proxy from the vs matrix: two heroes whose counters
    DIFFER cover more of the meta together than two who beat the same things.
    (OpenDota exposes no true ally-winrate matrix, so 'with' is this coverage
    complement, centered so the average pair scores 0.) Returns {a: {b: ±val}}."""
    pairs, vals = {}, []
    hids = list(adv)
    for i, a in enumerate(hids):
        ra = adv[a]
        for b in hids[i + 1:]:
            rb = adv[b]
            acc, n = 0.0, 0
            for c in top_meta:
                va, vb = ra.get(c), rb.get(c)
                if va is None or vb is None:
                    continue
                acc += abs(va - vb) / 2
                n += 1
            if n >= 10:
                pairs[(a, b)] = acc / n
                vals.append(acc / n)
    if not vals:
        return {}
    mean = sum(vals) / len(vals)
    out = {}
    for (a, b), v in pairs.items():
        d = round(v - mean, 2)
        out.setdefault(a, {})[b] = d
        out.setdefault(b, {})[a] = d
    return out


def load_meta(offline=False, heroes=None):
    """Patch hero winrates + hero-vs-hero advantage matrix + synergy proxy.

    base — {hid: pub winrate % in the LD2L brackets, current patch window}
    adv  — {a: {b: % advantage of a vs b}}, from a's own matchup sample so
           it's internally consistent (wr(a vs b) − a's overall matchup wr)
    syn  — {a: {b: ± coverage synergy}} (see _coverage_synergy)
    tags — {hid: {tier, pos, note}} curated meta (scout/meta_heroes.json)
    patch — the curated file's patch label, e.g. "7.41f"
    """
    cache = Cache()
    od = OpenDota()

    stats = cache.get_blob("hero_meta_stats",
                           max_age_hours=config.HERODRAFT_STATS_TTL_HOURS)
    if not stats and not offline:
        raw = od.hero_stats()
        if isinstance(raw, list):
            stats = {}
            for h in raw:
                try:
                    hid = int(h["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                g = sum(int(h.get(f"{b}_pick") or 0) for b in config.HERODRAFT_BRACKETS)
                w = sum(int(h.get(f"{b}_win") or 0) for b in config.HERODRAFT_BRACKETS)
                if g:
                    stats[str(hid)] = {"g": g, "w": w}
            if stats:
                cache.set_blob("hero_meta_stats", stats)
    stats = stats or cache.get_blob("hero_meta_stats") or {}
    base = {int(k): round(v["w"] / v["g"] * 100, 2)
            for k, v in stats.items() if v.get("g")}

    mu = cache.get_blob("hero_matchups",
                        max_age_hours=config.HERODRAFT_META_TTL_HOURS)
    stale_mu = cache.get_blob("hero_matchups") or {}
    if mu is None and not offline:
        ids = sorted(base) or sorted(HERO_FALLBACK)
        print(f"  🌐 Fetching hero matchup matrix ({len(ids)} heroes — one "
              f"call each, cached {config.HERODRAFT_META_TTL_HOURS // 24} days)...")
        refreshed, failed = {}, []
        for i, hid in enumerate(ids, 1):
            rows = od.hero_matchups(hid)
            if rows is None:
                failed.append(hid)
                if str(hid) in stale_mu:
                    refreshed[str(hid)] = stale_mu[str(hid)]
                continue
            refreshed[str(hid)] = {
                str(r["hero_id"]): [
                    int(r.get("games_played") or 0),
                    int(r.get("wins") or 0),
                ]
                for r in rows if r.get("hero_id")
            }
            if i % 20 == 0:
                print(f"    ... {i}/{len(ids)}")
        mu = dict(stale_mu)
        mu.update(refreshed)
        if failed:
            print(f"  ⚠ Matchups unavailable for {len(failed)} heroes; "
                  "kept stale rows and will retry next run")
        else:
            cache.set_blob("hero_matchups", mu)
    if mu is None:
        mu = stale_mu

    adv, row_wr = {}, {}
    for a, row in mu.items():
        g = sum(v[0] for v in row.values())
        w = sum(v[1] for v in row.values())
        row_wr[int(a)] = w / g * 100 if g else 50.0
    for a, row in mu.items():
        a = int(a)
        for b, (g, w) in row.items():
            if g >= config.HERODRAFT_MATCHUP_MIN_GAMES:
                adv.setdefault(a, {})[int(b)] = round(w / g * 100 - row_wr[a], 2)

    top_meta = [h for h, _ in sorted(((int(k), v["g"]) for k, v in stats.items()),
                                     key=lambda x: -x[1])[:config.HERODRAFT_TOP_META]]
    syn = _coverage_synergy(adv, top_meta) if adv else {}
    names = [h.get("n") for h in (heroes or {}).values() if isinstance(h, dict)]
    if not offline and cache.get_blob(
            "creator_videos", max_age_hours=config.HERODRAFT_CREATOR_TTL_HOURS) is None:
        print("  🎥 Refreshing creator meta videos (BSJ, Speeed...)")
        try:
            print(f"    {refresh_creators(cache, names)}")
        except Exception as exc:  # feeds are optional
            print(f"  ⚠ creator refresh failed: {exc}")
    signal = creator_signal(cache, names) if names else {}
    curated = load_meta_heroes(heroes or {}, creators=signal)
    return {"base": base, "adv": adv, "syn": syn,
            "tags": curated["heroes"], "patch": curated["patch"],
            "meta_updated": curated["updated"],
            "videos": creator_videos(curated["heroes"])}


def reload_meta_tags(meta, heroes):
    """Re-read the curated file + the creator cache into an existing meta dict
    (offline; used when the creator cache is refreshed by another pass)."""
    names = [h.get("n") for h in (heroes or {}).values() if isinstance(h, dict)]
    signal = creator_signal(Cache(), names) if names else {}
    curated = load_meta_heroes(heroes or {}, creators=signal)
    meta["tags"] = curated["heroes"]
    meta["patch"] = curated["patch"]
    meta["videos"] = creator_videos(curated["heroes"])
    return meta


# --------------------------------------------------------------------------
# Pool loading
# --------------------------------------------------------------------------

def load_pool(season, offline=True):
    """(label, [player rows], {steam32: profile}, heroes, league) from cache."""
    cache = Cache()
    od = OpenDota()
    label, players = players_from_snapshot(cache, season)
    if not players:
        return None, [], {}, {}, {"teams": [], "books": {}}
    profiles = {}
    for p in players:
        sections, _ = fetch_player_sections(od, cache, p, offline=True)
        profiles[p["steam32"]] = build_profile(p, sections)
    heroes = load_full_heroes(od, cache, offline=offline)
    rows = [{"steam32": p["steam32"], "name": p["name"],
             "mmr": p.get("mmr") or 0, "role": p.get("pref_role") or "Any"}
            for p in players]
    rows.sort(key=lambda r: -r["mmr"])
    try:
        league = load_league_context(od, cache, profiles, rows, offline=offline)
    except OSError as exc:
        print(f"  ⚠ Team Scout data unavailable: {exc}")
        league = {"teams": [], "books": {}}
    return label, rows, profiles, heroes, league


# --------------------------------------------------------------------------
# Draft state
# --------------------------------------------------------------------------

class DraftState:
    """One practice draft. team index: 0 = first pick, 1 = second pick."""

    def __init__(self, season, label, pool, profiles, heroes, meta=None,
                 league=None):
        self._lock = threading.RLock()
        self.season = season
        self.label = label
        self.pool = pool                    # [{steam32,name,mmr,role}]
        self.profiles = profiles            # steam32 -> profile
        self.heroes = heroes                # hid -> {n,key,attr}
        self.meta = meta or {"base": {}, "adv": {}, "syn": {}}
        self.meta.setdefault("tags", {})
        self.meta.setdefault("patch", "")
        league = league or {}
        self.league_teams = league.get("teams") or []
        self.books = league.get("books") or {}
        self.events = []
        self.rng = random.Random()

        self.phase = "setup"                # setup | drafting | done
        self.my_roster = []                 # steam32s
        self.enemy_roster = []
        self.enemy_name = "The Dire"
        self.my_team_key = None
        self.enemy_team_key = None
        self.me_first = None                # True = I am team F
        self.my_side = "radiant"            # cosmetic

        self._load_saved_rosters()
        self._reset_draft()

    # ---- persistence ----
    def _load_saved_rosters(self):
        try:
            with open(config.HERODRAFT_TEAMS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            known = {p["steam32"] for p in self.pool}
            self.my_roster = [int(s) for s in saved.get("mine", []) if int(s) in known][:5]
            self.enemy_roster = [int(s) for s in saved.get("enemy", []) if int(s) in known][:5]
            self.enemy_name = str(saved.get("enemy_name") or "The Dire")[:40]
            keys = {t["key"] for t in self.league_teams}
            mine_key = saved.get("mine_key")
            enemy_key = saved.get("enemy_key")
            self.my_team_key = mine_key if mine_key in keys else None
            self.enemy_team_key = enemy_key if enemy_key in keys else None
        except (OSError, ValueError, TypeError):
            pass

    def _save_rosters(self):
        try:
            with open(config.HERODRAFT_TEAMS_FILE, "w", encoding="utf-8") as f:
                json.dump({"mine": self.my_roster, "enemy": self.enemy_roster,
                           "enemy_name": self.enemy_name,
                           "mine_key": self.my_team_key,
                           "enemy_key": self.enemy_team_key}, f, indent=2)
        except OSError as e:
            print(f"  ⚠ couldn't save rosters: {e}")

    # ---- events ----
    def add_event(self, kind, text, **fields):
        with self._lock:
            fields.update({"kind": kind, "text": text, "ts": time.time()})
            self.events.append(fields)
            del self.events[:-80]

    # ---- draft lifecycle ----
    def _reset_draft(self):
        self.idx = -1                       # current step in CM_SEQUENCE
        self.picks = [[], []]               # [team][hid]
        self.bans = [[], []]
        self.history = []                   # [{idx,type,team,hid|None}] per step
        self.taken = set()                  # banned or picked hids
        self.assigns = [{}, {}]             # [team]{hid: player name}
        self.assigned_players = [set(), set()]
        self.reserve = [float(config.HERODRAFT_RESERVE_SECONDS)] * 2
        self.step_start = 0.0
        self.bot_delay = 0.0
        self.threats = [None, None]         # threat tables, built at start
        self.scout_cards = [[], []]         # official-book cards per team
        self.summary = None

    def _valid_team_key(self, key):
        if not key:
            return None
        key = str(key)
        return key if any(t["key"] == key for t in self.league_teams) else None

    def set_teams(self, mine, enemy, enemy_name, mine_key=None, enemy_key=None):
        with self._lock:
            if self.phase == "drafting":
                return False, "draft in progress"
            known = {p["steam32"] for p in self.pool}

            def normalize(values):
                if not isinstance(values, (list, tuple)):
                    return None
                result = []
                for value in values:
                    if isinstance(value, bool):
                        return None
                    try:
                        steam32 = int(value)
                    except (TypeError, ValueError):
                        return None
                    if steam32 in known and steam32 not in result:
                        result.append(steam32)
                return result[:5]

            mine, enemy = normalize(mine), normalize(enemy)
            if mine is None or enemy is None:
                return False, "invalid roster"
            if set(mine) & set(enemy):
                return False, "a player cannot be on both rosters"
            self.my_roster = mine
            self.enemy_roster = enemy
            self.my_team_key = self._valid_team_key(mine_key)
            self.enemy_team_key = self._valid_team_key(enemy_key)
            if enemy_name:
                self.enemy_name = str(enemy_name)[:40]
            elif self.enemy_team_key:
                for team in self.league_teams:
                    if team["key"] == self.enemy_team_key:
                        self.enemy_name = team["name"][:40]
                        break
        self._save_rosters()
        return True, "ok"

    def start(self, first, side):
        with self._lock:
            if self.phase == "drafting":
                return False, "already drafting"
            if not self.my_roster or not self.enemy_roster:
                return False, "set both rosters first"
            self._reset_draft()
            if first == "random":
                self.me_first = self.rng.random() < 0.5
                who = "You" if self.me_first else self.enemy_name
                self.add_event("flip", f"🪙 Coin flip: {who} pick{'s' if not self.me_first else ''} first!")
            else:
                self.me_first = (first == "me")
            if side == "random":
                self.my_side = self.rng.choice(["radiant", "dire"])
            else:
                self.my_side = side if side in ("radiant", "dire") else "radiant"
            # threat tables: what each team would draft / fears
            mine = [self.profiles[s] for s in self.my_roster if s in self.profiles]
            enemy = [self.profiles[s] for s in self.enemy_roster if s in self.profiles]
            now = time.time()
            my_ti, en_ti = (0, 1) if self.me_first else (1, 0)
            self.threats = [None, None]
            self.threats[my_ti] = team_threats(mine, now)     # what team F/S=me plays
            self.threats[en_ti] = team_threats(enemy, now)
            names = {p["steam32"]: p["name"] for p in self.profiles.values()}
            self.scout_cards = [book_cards(self._book_for(ti), names)
                                for ti in (0, 1)]
            self.phase = "drafting"
            self.add_event("status",
                           f"⚔ Draft begins — {'you' if self.me_first else self.enemy_name} "
                           f"ha{'ve' if self.me_first else 's'} first pick.")
            self._advance()
        return True, "ok"

    def reset(self):
        with self._lock:
            self.phase = "setup"
            self._reset_draft()
        self.add_event("status", "Draft reset — set up the next scrim.")

    # ---- helpers ----
    def my_team_index(self):
        return 0 if self.me_first else 1

    def _team_label(self, ti):
        return "You" if ti == self.my_team_index() else self.enemy_name

    def _step(self):
        return CM_SEQUENCE[self.idx] if 0 <= self.idx < len(CM_SEQUENCE) else None

    def _advance(self):
        """Move to the next step (call under lock)."""
        self.idx += 1
        step = self._step()
        if step is None:
            self.phase = "done"
            self.summary = self._build_summary()
            self.add_event("done", "🏁 Draft complete. GLHF on the real one.")
            return
        self.step_start = time.time()
        lo, hi = config.HERODRAFT_BOT_DELAY
        self.bot_delay = self.rng.uniform(lo, hi)
        ti = step["team"]
        verb = "ban" if step["type"] == "ban" else "pick"
        self.add_event("turn", f"{self._team_label(ti)} to {verb} "
                               f"({self._phase_name(step)})",
                       team=ti, type=step["type"])

    @staticmethod
    def _phase_name(step):
        names = ["Ban Phase 1", "Pick Phase 1", "Ban Phase 2",
                 "Pick Phase 2", "Ban Phase 3", "Pick Phase 3"]
        return names[step["phase"]]

    def _roster_profiles(self, ti):
        s32s = self.my_roster if ti == self.my_team_index() else self.enemy_roster
        return [self.profiles[s] for s in s32s if s in self.profiles]

    def _key_for(self, ti):
        return self.my_team_key if ti == self.my_team_index() else self.enemy_team_key

    def _book_for(self, ti):
        key = self._key_for(ti)
        return self.books.get(key) if key else None

    # ---- acting ----
    def act(self, ti, hid, auto=False):
        """Apply a ban/pick by team ti. hid None on a timed-out ban."""
        with self._lock:
            step = self._step()
            if self.phase != "drafting" or step is None or step["team"] != ti:
                return False, "not your turn"
            if hid is not None:
                try:
                    hid = int(hid)
                except (TypeError, ValueError):
                    return False, "invalid hero"
                if hid in self.taken or hid not in self.heroes:
                    return False, "hero unavailable"
            # burn reserve for time used past the step clock
            over = (time.time() - self.step_start) - step["secs"]
            if over > 0:
                self.reserve[ti] = max(0.0, self.reserve[ti] - over)
            name = self.heroes[hid]["n"] if hid is not None else None
            # rating measured against the board BEFORE the hero lands on it
            rate = self.rating(ti, hid) if hid is not None else None
            self.history.append({"idx": self.idx, "type": step["type"],
                                 "team": ti, "hid": hid,
                                 "rating": rate["total"] if rate else None})
            if step["type"] == "ban":
                if hid is None:
                    self.add_event("ban", f"⏱ {self._team_label(ti)} ran out of "
                                          f"time — no hero banned!", team=ti)
                else:
                    self.bans[ti].append(hid)
                    self.taken.add(hid)
                    why = self._reason_for(ti, hid, "ban") if not auto else ""
                    verb = "ban" if ti == self.my_team_index() else "bans"
                    self.add_event("ban", f"🚫 {self._team_label(ti)} {verb} {name}"
                                          + (f" — {why}" if why else ""),
                                   team=ti, hid=hid)
            else:
                self.picks[ti].append(hid)
                self.taken.add(hid)
                who = self._assign_pick(ti, hid)
                tag = f" ({who})" if who else ""
                why = self._reason_for(ti, hid, "pick") if not auto else ""
                pre = "🎲 Time! Random pick:" if auto else "✅"
                verb = "pick" if ti == self.my_team_index() else "picks"
                rtag = f" ({rate['total']:+.1f})" if rate else ""
                self.add_event("pick", f"{pre} {self._team_label(ti)} {verb} "
                                       f"{name}{rtag}{tag}"
                                       + (f" — {why}" if why else ""),
                               team=ti, hid=hid)
            self._advance()
        return True, "ok"

    def _assign_pick(self, ti, hid):
        """Seat the picked hero with the roster player who plays it best:
        comfort on the hero first, then whose measured position profile
        matches where the hero is played (a carry player gets the carry)."""
        best, best_total, best_s, best_fit = None, -1.0, 0.0, 0.0
        weights = POS_WEIGHTS.get(hid, {})
        for prof in self._roster_profiles(ti):
            if prof["steam32"] in self.assigned_players[ti]:
                continue
            s, _ = hero_score(prof, hid)
            aff = player_affinity(prof)
            fit = sum(w * aff.get(pos, 0.0) for pos, w in weights.items())
            total = s + config.HERODRAFT_ASSIGN_ROLE_WEIGHT * fit
            if total > best_total:
                best, best_total, best_s, best_fit = prof, total, s, fit
        if best is None:
            return None
        self.assigns[ti][hid] = best["name"]
        self.assigned_players[ti].add(best["steam32"])
        return best["name"] if (best_s > 0.1 or best_fit > 0.3) else None

    def _reason_for(self, ti, hid, kind):
        """Short 'why' for the feed: official draft book, else comfort."""
        if kind == "pick":
            why = scout_why(self._book_for(ti), hid, "pick",
                            max(len(self.picks[ti]) - 1, 0), ti == 0)
            if why:
                return why
            table = self.threats[ti]
        else:
            why = scout_why(self._book_for(ti), hid, "ban", 0, False)
            deny = scout_why(self._book_for(1 - ti), hid, "pick",
                             len(self.picks[1 - ti]), (1 - ti) == 0)
            if why and deny:
                return f"{why}; they {deny}"
            if why:
                return why
            if deny:
                return deny
            table = self.threats[1 - ti]
        if table and hid in table:
            return table[hid][1]
        return ""

    # ---- meta lookups ----
    def _mu_adv(self, a, b):
        """% advantage of hero a over hero b (antisymmetric fallback)."""
        row = self.meta["adv"].get(a)
        if row and b in row:
            return row[b]
        row = self.meta["adv"].get(b)
        if row and a in row:
            return -row[a]
        return 0.0

    def _mu_syn(self, a, b):
        row = self.meta["syn"].get(a)
        return row.get(b, 0.0) if row else 0.0

    def rating(self, ti, hid, now=None, kind="pick", banner_ti=None):
        """Dotabuff-style board rating of hero hid for team ti, right now.

        Breakdown dict: comfort (roster evidence, best still-unassigned player
        preferred), patch (pub winrate dev from 50 in the LD2L brackets),
        vs (Σ matchup advantage over enemy picks), with (Σ coverage synergy
        with own picks), scout (Team Scout official first picks / wins / bans).
        total is the weighted sum shown as e.g. +4.10.
        """
        now = now or time.time()
        best_un, best_any = (0.0, ""), (0.0, "")
        for prof in self._roster_profiles(ti):
            s, why = hero_score(prof, hid, now)
            if s > best_any[0]:
                best_any = (s, f"{prof['name']}: {why}")
            if prof["steam32"] not in self.assigned_players[ti] and s > best_un[0]:
                best_un = (s, f"{prof['name']}: {why}")
        comfort, who = best_un if best_un[0] > 0 else best_any
        base = self.meta["base"].get(hid)
        patch = (base - 50.0) if base is not None else 0.0
        other = 1 - ti
        vs = sum(self._mu_adv(hid, e) for e in self.picks[other])
        wth = sum(self._mu_syn(hid, a) for a in self.picks[ti])
        pick_index = len(self.picks[ti])
        scout = scout_pick_value(self._book_for(ti), hid, pick_index, ti == 0)
        if kind == "ban":
            banner = self._book_for(banner_ti if banner_ti is not None else other)
            scout = scout + scout_ban_value(banner, hid)
        role = role_term(self.picks[ti], hid)
        meta = meta_value(self.meta.get("tags"), hid)
        total = (config.HERODRAFT_W_COMFORT * comfort
                 + config.HERODRAFT_W_PATCH * patch
                 + config.HERODRAFT_W_VS * vs
                 + config.HERODRAFT_W_WITH * wth
                 + config.HERODRAFT_W_SCOUT * scout
                 + config.HERODRAFT_W_ROLE * role
                 + config.HERODRAFT_W_META * meta)
        scout_line = scout_why(
            self._book_for(ti), hid, "pick", pick_index, ti == 0)
        if kind == "ban":
            scout_line = scout_why(
                banner, hid, "ban", 0, False) or scout_line
        if scout_line:
            who = f"{scout_line}" + (f"; {who}" if who else "")
        tag = (self.meta.get("tags") or {}).get(hid)
        return {"total": round(total, 2), "c": round(comfort, 2),
                "p": round(patch, 2), "v": round(vs, 2), "w": round(wth, 2),
                "s": round(scout, 2), "r": round(role, 2), "m": round(meta, 2),
                "tier": (tag["tier"] or None) if tag else None,
                "creators": creator_names(self.meta.get("tags"), hid),
                "base": base, "who": who}

    def win_probability(self):
        """P(my team wins) % from the picked heroes so far: assigned-player
        comfort + patch winrates + cross-team matchups + in-team synergy."""
        if not self.picks[0] and not self.picks[1]:
            return 50.0

        def solo(ti):
            tot = 0.0
            profs = {p["name"]: p for p in self._roster_profiles(ti)}
            for hid in self.picks[ti]:
                prof = profs.get(self.assigns[ti].get(hid))
                if prof:
                    tot += config.HERODRAFT_W_COMFORT * hero_score(prof, hid)[0]
                b = self.meta["base"].get(hid)
                if b is not None:
                    tot += config.HERODRAFT_W_PATCH * (b - 50.0)
            for i, a in enumerate(self.picks[ti]):
                for b in self.picks[ti][i + 1:]:
                    tot += config.HERODRAFT_W_WITH * self._mu_syn(a, b)
            # lineup balance: seats covered minus heroes picked is 0 for a
            # clean 1-5 and negative when picks overlap the same position
            cov = role_coverage(self.picks[ti])
            tot += config.HERODRAFT_W_ROLE * 0.6 * (
                sum(cov.values()) - len(self.picks[ti]))
            return tot

        cross = sum(self._mu_adv(a, b)
                    for a in self.picks[0] for b in self.picks[1])
        delta = solo(0) - solo(1) + config.HERODRAFT_W_VS * cross
        if self.my_team_index() == 1:
            delta = -delta
        p = 100.0 / (1.0 + math.exp(-config.HERODRAFT_WINPROB_K * delta))
        lo = config.HERODRAFT_WINPROB_CLAMP
        return round(min(100.0 - lo, max(lo, p)), 1)

    # ---- bot ----
    def bot_candidates(self, ti, kind, k):
        """Top-k (hid, rating_dict) for team ti's ban or pick.

        Candidates come from the acting side's comfort pool (a ban denies the
        OPPONENT's pool) plus Team Scout's official pick/ban book, ranked by
        the full board rating from the pool owner's perspective.
        """
        with self._lock:
            rate_ti = (1 - ti) if kind == "ban" else ti
            table = self.threats[rate_ti] or {}
            hids = set(table)
            pick_book = self._book_for(rate_ti)
            if pick_book:
                hids.update(pick_book["picks"])
                if kind == "ban":
                    for side in pick_book["openers"].values():
                        hids.update(side)
            if kind == "ban":
                ban_book = self._book_for(ti)
                if ban_book:
                    hids.update(ban_book["bans"])
            # key meta heroes are always on the table, comfort or not
            hids.update(h for h, t in (self.meta.get("tags") or {}).items()
                        if t.get("tier") in ("S", "A") or t.get("creators"))
            cands = []
            for hid in hids:
                if hid in self.taken or hid not in self.heroes:
                    continue
                r = self.rating(rate_ti, hid, kind=kind, banner_ti=ti)
                if kind == "ban":
                    # a hero the banner wants MORE than the target is a pick,
                    # not a ban - spend the ban where the threat is
                    mine = self.rating(ti, hid)["total"]
                    self_discount = config.HERODRAFT_BAN_SELF_DISCOUNT * max(
                        0.0, mine - r["total"])
                    if self_discount:
                        r = dict(r, total=round(r["total"] - self_discount, 2),
                                 threat=r["total"], self_discount=round(self_discount, 2))
                cands.append((r["total"], hid, r))
            cands.sort(key=lambda x: -x[0])
            return [(h, r) for _, h, r in cands[:k]]

    def bot_act(self):
        """The enemy's move: sharpness-weighted sample from its best options."""
        with self._lock:
            step = self._step()
            if step is None or self.phase != "drafting":
                return
            ti = step["team"]
            cands = self.bot_candidates(ti, step["type"], config.HERODRAFT_BOT_TOP_K)
            if not cands:
                if step["type"] == "ban":
                    self.act(ti, None, auto=True)     # nothing scored — skip ban
                else:
                    self.act(ti, self._random_hero(), auto=True)
                return
            floor = min(r["total"] for _, r in cands)
            weights = [max(r["total"] - floor + 0.25, 0.01)
                       ** config.HERODRAFT_BOT_SHARPNESS for _, r in cands]
            hid = self.rng.choices([h for h, _ in cands], weights=weights)[0]
            self.act(ti, hid)

    def _random_hero(self):
        avail = [h for h in self.heroes if h not in self.taken]
        return self.rng.choice(avail) if avail else None

    # ---- timing tick (engine thread) ----
    def tick(self):
        with self._lock:
            step = self._step()
            if self.phase != "drafting" or step is None:
                return
            ti = step["team"]
            elapsed = time.time() - self.step_start
            is_bot = ti != self.my_team_index()
            if is_bot and elapsed >= self.bot_delay:
                pass  # act outside the elif chain below
            elif elapsed <= step["secs"] + self.reserve[ti]:
                return
            if is_bot:
                self.bot_act()
                return
            # my clock fully expired: CM rules — ban skipped, pick randomized
            if step["type"] == "ban":
                self.act(ti, None, auto=True)
            else:
                # random from my own comfort list when possible, like a tilted
                # captain smashing a hero they at least know
                cands = self.bot_candidates(ti, "pick", 12)
                hid = self.rng.choice([h for h, _ in cands]) if cands \
                    else self._random_hero()
                self.act(ti, hid, auto=True)

    # ---- state for the UI ----
    def suggestions(self):
        """Hints for MY current turn, with the full rating breakdown."""
        step = self._step()
        if step is None or step["team"] != self.my_team_index():
            return []
        cands = self.bot_candidates(step["team"], step["type"],
                                    config.HERODRAFT_SUGGESTIONS)
        return [{"hid": h, "rating": r["total"],
                 "parts": {"c": r["c"], "p": r["p"], "v": r["v"], "w": r["w"],
                           "s": r["s"], "r": r["r"], "m": r["m"],
                           "tier": r.get("tier"), "creators": r.get("creators") or [],
                           "base": r["base"], "self": r.get("self_discount")},
                 "why": r["who"]} for h, r in cands]

    def _build_summary(self):
        out = []
        for ti in (0, 1):
            lineup = []
            for hid in self.picks[ti]:
                lineup.append({"hid": hid, "hero": self.heroes[hid]["n"],
                               "player": self.assigns[ti].get(hid)})
            out.append({"team": self._team_label(ti), "is_me": ti == self.my_team_index(),
                        "lineup": lineup,
                        "bans": [self.heroes[h]["n"] for h in self.bans[ti]]})
        return out

    def snapshot(self):
        with self._lock:
            now = time.time()
            step = self._step()
            my_ti = self.my_team_index() if self.me_first is not None else 0
            turn = None
            if self.phase == "drafting" and step:
                turn = {
                    "idx": self.idx, "type": step["type"], "team": step["team"],
                    "is_me": step["team"] == my_ti,
                    "phase_name": self._phase_name(step),
                    "step_secs": step["secs"],
                    "elapsed_ms": int((now - self.step_start) * 1000),
                }
            rosters = []
            for ti in (0, 1):
                s32s = self.my_roster if ti == my_ti else self.enemy_roster
                rosters.append({
                    "label": self._team_label(ti),
                    "is_me": ti == my_ti,
                    "side": (self.my_side if ti == my_ti else
                             ("dire" if self.my_side == "radiant" else "radiant")),
                    "players": [{"name": self.profiles[s]["name"],
                                 "mmr": self.profiles[s]["mmr"],
                                 "role": self.profiles[s]["pref_role"]}
                                for s in s32s if s in self.profiles],
                    "picks": [{"hid": h, "player": self.assigns[ti].get(h)}
                              for h in self.picks[ti]],
                    "bans": self.bans[ti],
                    "reserve_ms": int(self.reserve[ti] * 1000),
                })
            return {
                "phase": self.phase, "label": self.label,
                "me_first": self.me_first, "my_side": self.my_side,
                "enemy_name": self.enemy_name,
                "my_roster": self.my_roster, "enemy_roster": self.enemy_roster,
                "seq": [{"type": s["type"], "team": s["team"]} for s in CM_SEQUENCE],
                "idx": self.idx, "turn": turn,
                "history": list(self.history),
                "taken": sorted(self.taken),
                "winprob": (self.win_probability()
                            if self.phase in ("drafting", "done") else None),
                "ratings": ({str(h): self.rating(my_ti, h)["total"]
                             for h in self.heroes if h not in self.taken}
                            if turn and turn["is_me"] else None),
                "has_meta": bool(self.meta["base"] or self.meta["adv"]),
                "meta_patch": self.meta.get("patch") or "",
                "meta_tags": {str(h): {"tier": t.get("tier") or "",
                                       "creators": creator_names(self.meta.get("tags"), h)}
                              for h, t in (self.meta.get("tags") or {}).items()},
                "creator_videos": self.meta.get("videos") or [],
                "scout_cards": self.scout_cards,
                "league_teams": self.league_teams,
                "mine_key": self.my_team_key,
                "enemy_key": self.enemy_team_key,
                "teams": rosters,
                "suggestions": self.suggestions() if self.phase == "drafting" else [],
                "events": self.events[-40:],
                "summary": self.summary,
                "now_ms": int(now * 1000),
            }


# --------------------------------------------------------------------------
# Hub: pool + meta loaded once, one draft per sign-in, one engine thread.
# Used standalone (--herodraft) and embedded in Team Scout (/draft).
# --------------------------------------------------------------------------

SOUND_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SOUND_EXTS = {".mp3": "audio/mpeg", ".ogg": "audio/ogg",
              ".wav": "audio/wav", ".webm": "audio/webm"}
SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "assets", "sounds")


def _resolve_sound_path(filename):
    """Plain filename, allowed extension, no path traversal -> abs path or None.

    Optional real-audio override for the herodraft board: if the user drops
    their own exported Dota sounds into scout/assets/sounds/, GET/HEAD
    /sounds/<filename> serves them; anything else (or a missing file) 404s.
    """
    if not filename or ".." in filename or not SOUND_NAME_RE.match(filename):
        return None
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SOUND_EXTS:
        return None
    path = os.path.abspath(os.path.join(SOUNDS_DIR, filename))
    sounds_dir_abs = os.path.abspath(SOUNDS_DIR)
    if os.path.commonpath([path, sounds_dir_abs]) != sounds_dir_abs:
        return None
    if not os.path.isfile(path):
        return None
    return path, SOUND_EXTS[ext]


def _file_stamp(path):
    try:
        info = os.stat(path)
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return (0, 0)


def _league_stamp():
    """Identity of the Team Scout inputs the league context is built from."""
    from .bbc_source import bbc_source_stamp
    from .overrides import overrides_path
    return (bbc_source_stamp(), _file_stamp(overrides_path()))


def _meta_stamp():
    """Identity of the offline meta inputs (curated file + creator cache)."""
    return (_file_stamp(META_HEROES_FILE),
            _file_stamp(os.path.join(config.CACHE_DIR, "creator_videos.json")))


class HeroDraftHub:
    """Everything the draft board needs, loaded once per process.

    `state_for(key)` hands out one DraftState per sign-in (Team Scout) or
    the single "local" one (--herodraft). A single engine thread ticks every
    live draft. The league context (teams, official books, per-player
    official records) is rebuilt when BBC's feed or the roster overrides
    change on disk, so a Team Scout roster edit shows up in the next draft.
    """

    def __init__(self, season, offline=False):
        self.season = season
        self.offline = offline
        self._lock = threading.RLock()
        self.label = None
        self.pool = []
        self.profiles = {}
        self.heroes = {}
        self.league = {"teams": [], "books": {}}
        self.meta = {"base": {}, "adv": {}, "syn": {}, "tags": {}, "patch": ""}
        self.page = b""
        self.states = {}
        self.ready = False
        self.error = None
        self._stamp = None
        self._meta_stamp = None
        self._stop = threading.Event()
        self._engine = None

    # ---- loading ----
    def load(self, verbose=True):
        """Load the pool, league context and meta from cache (network only
        for the meta when not offline). Returns True when a pool exists."""
        from .herodraft_html import render_page

        label, pool, profiles, heroes, league = load_pool(
            self.season, offline=self.offline)
        if not pool:
            self.error = ("No cached player pool. Run the scout once first "
                          "(python ld2l_scout.py).")
            if verbose:
                print(f"  ✗ {self.error}")
            return False
        meta = load_meta(offline=self.offline, heroes=heroes)
        with self._lock:
            self.label, self.pool, self.profiles = label, pool, profiles
            self.heroes, self.league, self.meta = heroes, league, meta
            self.page = render_page(pool, heroes, label, league["teams"]).encode("utf-8")
            self._stamp = _league_stamp()
            self._meta_stamp = _meta_stamp()
            self.ready = True
            self.error = None
        if verbose:
            self.describe()
        self.start_engine()
        return True

    def load_async(self):
        def run():
            try:
                self.load()
            except Exception as exc:  # keep Team Scout up; the board reports it
                self.error = f"hero draft failed to load: {exc}"
                print(f"  ⚠ {self.error}")
        threading.Thread(target=run, daemon=True).start()

    def describe(self):
        league_players = sum(1 for p in self.profiles.values() if p["league"])
        official_players = sum(1 for p in self.profiles.values() if p.get("official"))
        print(f"  📜 {len(self.pool)} players, {len(self.heroes)} heroes "
              f"({league_players} with league lobby history, "
              f"{official_players} with official hero records)")
        n_books = sum(1 for b in self.league["books"].values() if b["games"])
        if self.league["teams"]:
            print(f"  🧭 Team Scout: {len(self.league['teams'])} teams, "
                  f"{n_books} with official draft history")
        else:
            print("  ⚠ No Team Scout / BBC teams loaded — bot falls back to "
                  "player comfort only")
        meta = self.meta
        if meta["base"] or meta["adv"]:
            print(f"  📈 Patch meta: winrates for {len(meta['base'])} heroes, "
                  f"matchup rows for {len(meta['adv'])} (ratings + win% on)")
        else:
            print("  ⚠ No OpenDota patch meta cached (offline, never fetched) "
                  "— ratings use roster comfort + the curated meta list")
        if meta.get("tags"):
            print(f"  🗺 Curated meta {meta.get('patch') or '?'}: "
                  f"{len(meta['tags'])} heroes tagged")
        videos = meta.get("videos") or []
        if videos:
            print(f"  🎥 Creator watch: {len(videos)} recent meta videos "
                  f"({', '.join(sorted({v['who'] for v in videos}))})")
        else:
            print("  🎥 Creator watch: no recent videos cached — run "
                  "python ld2l_scout.py --refresh-creators")

    def refresh_meta_if_changed(self):
        """Re-read the curated meta + creator videos when either file moved
        (the auto-refresh pass writes the creator cache)."""
        if not self.ready:
            return False
        stamp = _meta_stamp()
        if stamp == self._meta_stamp:
            return False
        with self._lock:
            reload_meta_tags(self.meta, self.heroes)   # shared dict: every state sees it
            self._meta_stamp = stamp
        return True

    def refresh_league_if_changed(self):
        """Rebuild teams/books/official records when Team Scout inputs moved."""
        if not self.ready:
            return False
        self.refresh_meta_if_changed()
        stamp = _league_stamp()
        if stamp == self._stamp:
            return False
        from .herodraft_html import render_page
        cache = Cache()
        od = OpenDota()
        rows = list(self.pool)
        try:
            league = load_league_context(od, cache, self.profiles, rows, offline=True)
        except OSError as exc:
            print(f"  ⚠ Team Scout data unavailable: {exc}")
            return False
        with self._lock:
            self.pool = rows
            self.league = league
            self.page = render_page(rows, self.heroes, self.label,
                                    league["teams"]).encode("utf-8")
            self._stamp = stamp
            for state in self.states.values():
                if state.phase != "drafting":
                    state.pool = rows
                    state.league_teams = league["teams"]
                    state.books = league["books"]
        return True

    # ---- drafts ----
    def state_for(self, key="local"):
        key = str(key or "local")
        with self._lock:
            state = self.states.get(key)
            if state is None:
                if len(self.states) >= config.HERODRAFT_MAX_STATES:
                    idle = [k for k, st in self.states.items() if st.phase != "drafting"]
                    for k in idle[:len(self.states) - config.HERODRAFT_MAX_STATES + 1]:
                        del self.states[k]
                state = DraftState(self.season, self.label, self.pool, self.profiles,
                                   self.heroes, self.meta, self.league)
                self.states[key] = state
            return state

    def tick_all(self):
        with self._lock:
            states = list(self.states.values())
        for state in states:
            try:
                state.tick()
            except Exception as e:  # keep the clock alive no matter what
                print(f"  ⚠ engine tick error: {e}")

    def start_engine(self):
        with self._lock:
            if self._engine is not None:
                return
            self._engine = threading.Thread(target=self._engine_loop, daemon=True)
            self._engine.start()

    def _engine_loop(self):
        while not self._stop.is_set():
            self.tick_all()
            self._stop.wait(0.25)

    def stop(self):
        self._stop.set()

    # ---- routing (shared by the standalone server and Team Scout) ----
    def route_get(self, path, key="local", head=False):
        """(status, content_type, body) for a GET/HEAD, or None if not ours."""
        if path in ("/draft", "/draft/"):
            if not self.ready:
                msg = (self.error or "Hero draft is still loading — refresh in a moment.")
                body = (f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh "
                        f"content=3><title>Mock draft</title><body style='font:15px "
                        f"system-ui;padding:40px;background:#1c242c;color:#d6dde3'>"
                        f"<p>{html_escape(msg)}</p>").encode("utf-8")
                return 503, "text/html; charset=utf-8", body
            self.refresh_league_if_changed()
            return 200, "text/html; charset=utf-8", self.page
        if path == "/draft/state":
            if not self.ready:
                return 503, "application/json", json.dumps(
                    {"phase": "loading", "error": self.error}).encode()
            return 200, "application/json", json.dumps(
                self.state_for(key).snapshot()).encode()
        if path.startswith("/sounds/"):
            resolved = _resolve_sound_path(path[len("/sounds/"):])
            if not resolved:
                return 404, "text/plain", b"" if head else b"not found"
            spath, ctype = resolved
            if head:
                return 200, ctype, b""
            with open(spath, "rb") as f:
                return 200, ctype, f.read()
        return None

    def route_post(self, path, body, key="local"):
        """(status, json_obj) for a POST, or None if not ours."""
        if not path.startswith("/draft/"):
            return None
        if not self.ready:
            return 503, {"ok": False, "msg": self.error or "still loading"}
        body = body if isinstance(body, dict) else {}
        state = self.state_for(key)
        if path == "/draft/teams":
            ok, msg = state.set_teams(
                body.get("mine", []), body.get("enemy", []), body.get("enemy_name"),
                body.get("mine_key"), body.get("enemy_key"))
            return (200 if ok else 400), {"ok": ok, "msg": msg}
        if path == "/draft/start":
            ok, msg = state.start(body.get("first", "random"), body.get("side", "random"))
            return (200 if ok else 400), {"ok": ok, "msg": msg}
        if path == "/draft/act":
            ok, msg = state.act(state.my_team_index(), body.get("hid"))
            return (200 if ok else 400), {"ok": ok, "msg": msg}
        if path == "/draft/reset":
            state.reset()
            return 200, {"ok": True}
        return None


def html_escape(text):
    import html as _html
    return _html.escape(str(text or ""))


def _make_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json", json.dumps(obj).encode())

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                return body if isinstance(body, dict) else {}
            except (ValueError, json.JSONDecodeError):
                return {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                path = "/draft"
            hit = hub.route_get(path)
            if hit is None:
                self._send(404, "text/plain", b"not found")
            else:
                self._send(*hit)

        def do_HEAD(self):
            path = self.path.split("?")[0]
            hit = hub.route_get(path, head=True) if path.startswith("/sounds/") else None
            if hit is None:
                self._send(404, "text/plain", b"")
                return
            code, ctype, _ = hit
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_POST(self):
            path = self.path.split("?")[0]
            hit = hub.route_post(path, self._body())
            if hit is None:
                self._send(404, "text/plain", b"not found")
            else:
                self._json(*hit)

    return Handler


class _DraftServer(ThreadingHTTPServer):
    allow_reuse_address = False  # same loud-failure policy as --mock


def run_herodraft(season, port=None, offline=False, open_browser=True):
    port = port or config.HERODRAFT_PORT
    print("\n⚔ Loading hero-draft pool from cache...")
    hub = HeroDraftHub(season, offline=offline)
    if not hub.load():
        print("    Then start --herodraft.")
        return
    try:
        server = _DraftServer(("127.0.0.1", port), _make_handler(hub))
    except OSError as e:
        print(f"\n  ✗ Port {port} is already in use ({e}).\n    Close the other "
              f"window first (or change --port), then relaunch.\n")
        return

    url = f"http://localhost:{port}/"
    patch = hub.meta.get("patch") or "current"
    print("\n" + "=" * 60)
    print(f"  ⚔ HERO DRAFT PRACTICE — Captains Mode vs the bot (patch {patch} meta)")
    print(f"  Pool: {hub.label} | Pick Team Scout sides, flip for first pick, draft.")
    print(f"  Board: {url}")
    print("  Ctrl+C to stop")
    print("=" * 60 + "\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Draft practice stopped.")
    finally:
        hub.stop()
        server.server_close()
