"""Hero draft practice — Captains Mode pick/ban against a scouting-driven bot.

Practice the ACTUAL Dota draft (heroes, not players) against the team you're
about to face. Fully local; nothing is sent to ld2l.org or Steam.

  - Rosters: you assemble your team and the enemy team from the cached signup
    pool (searchable picker, persisted to herodraft_teams.json between runs).
  - The bot drafts for the enemy using their real data: each player's lifetime
    hero stats (OpenDota /heroes), their 180-day match sample (current form),
    and specifically their organized-league games (lobby fingerprint — the
    heroes they actually pull out when it counts). Bans target YOUR roster's
    comfort picks the same way.
  - Draft order is Captains Mode as of patch 7.40 (2025-12-15): first-pick
    bans 3-2-2 / second-pick 4-1-2, picks 1-3-1 both sides, 15s first ban
    phase, 30s everything else, 130s reserve each. Timed out ban = no ban;
    timed out pick = random hero — same as the real client.
  - First pick / side can be chosen or coin-flipped in the UI.

Server layout mirrors mockdraft.py: ThreadingHTTPServer + JSON polling.
"""

import json
import math
import os
import random
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .analysis import is_organized_match
from .cache import Cache
from .fetch import fetch_player_sections, players_from_snapshot
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
    }


def hero_score(prof, hid, now=None):
    """Comfort score (0..~2) of this hero for this player, with a reason.

    Volume × quality on lifetime stats, decayed if unplayed for months, plus
    current-form and league-play bonuses. Returns (score, reason_str).
    """
    now = now or time.time()
    score, bits = 0.0, []
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
        hids = set(prof["heroes"]) | set(prof["recent"]) | set(prof["league"])
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


def load_meta(offline=False):
    """Patch hero winrates + hero-vs-hero advantage matrix + synergy proxy.

    base — {hid: pub winrate % in the LD2L brackets, current patch window}
    adv  — {a: {b: % advantage of a vs b}}, from a's own matchup sample so
           it's internally consistent (wr(a vs b) − a's overall matchup wr)
    syn  — {a: {b: ± coverage synergy}} (see _coverage_synergy)
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
    return {"base": base, "adv": adv, "syn": syn}


# --------------------------------------------------------------------------
# Pool loading
# --------------------------------------------------------------------------

def load_pool(season, offline=True):
    """(label, [player rows], {steam32: profile}) from the scout cache."""
    cache = Cache()
    od = OpenDota()
    label, players = players_from_snapshot(cache, season)
    if not players:
        return None, [], {}, {}
    profiles = {}
    for p in players:
        sections, _ = fetch_player_sections(od, cache, p, offline=True)
        profiles[p["steam32"]] = build_profile(p, sections)
    heroes = load_full_heroes(od, cache, offline=offline)
    rows = [{"steam32": p["steam32"], "name": p["name"],
             "mmr": p.get("mmr") or 0, "role": p.get("pref_role") or "Any"}
            for p in players]
    rows.sort(key=lambda r: -r["mmr"])
    return label, rows, profiles, heroes


# --------------------------------------------------------------------------
# Draft state
# --------------------------------------------------------------------------

class DraftState:
    """One practice draft. team index: 0 = first pick, 1 = second pick."""

    def __init__(self, season, label, pool, profiles, heroes, meta=None):
        self._lock = threading.RLock()
        self.season = season
        self.label = label
        self.pool = pool                    # [{steam32,name,mmr,role}]
        self.profiles = profiles            # steam32 -> profile
        self.heroes = heroes                # hid -> {n,key,attr}
        self.meta = meta or {"base": {}, "adv": {}, "syn": {}}
        self.events = []
        self.rng = random.Random()

        self.phase = "setup"                # setup | drafting | done
        self.my_roster = []                 # steam32s
        self.enemy_roster = []
        self.enemy_name = "The Dire"
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
        except (OSError, ValueError, TypeError):
            pass

    def _save_rosters(self):
        try:
            with open(config.HERODRAFT_TEAMS_FILE, "w", encoding="utf-8") as f:
                json.dump({"mine": self.my_roster, "enemy": self.enemy_roster,
                           "enemy_name": self.enemy_name}, f, indent=2)
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
        self.summary = None

    def set_teams(self, mine, enemy, enemy_name):
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
            if enemy_name:
                self.enemy_name = str(enemy_name)[:40]
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
        """Give the picked hero to the roster player who plays it best."""
        best, best_s = None, -1.0
        for prof in self._roster_profiles(ti):
            if prof["steam32"] in self.assigned_players[ti]:
                continue
            s, _ = hero_score(prof, hid)
            if s > best_s:
                best, best_s = prof, s
        if best is None:
            return None
        self.assigns[ti][hid] = best["name"]
        self.assigned_players[ti].add(best["steam32"])
        return best["name"] if best_s > 0.1 else None

    def _reason_for(self, ti, hid, kind):
        """Short 'why' for the feed: whose comfort hero this touches."""
        table = self.threats[1 - ti] if kind == "ban" else self.threats[ti]
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

    def rating(self, ti, hid, now=None):
        """Dotabuff-style board rating of hero hid for team ti, right now.

        Breakdown dict: comfort (roster evidence, best still-unassigned player
        preferred), patch (pub winrate dev from 50 in the LD2L brackets),
        vs (Σ matchup advantage over enemy picks), with (Σ coverage synergy
        with own picks). total is the weighted sum shown as e.g. +4.10.
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
        total = (config.HERODRAFT_W_COMFORT * comfort
                 + config.HERODRAFT_W_PATCH * patch
                 + config.HERODRAFT_W_VS * vs
                 + config.HERODRAFT_W_WITH * wth)
        return {"total": round(total, 2), "c": round(comfort, 2),
                "p": round(patch, 2), "v": round(vs, 2), "w": round(wth, 2),
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
        OPPONENT's pool), ranked by the full board rating — comfort + patch
        winrate + matchups — from the pool owner's perspective.
        """
        with self._lock:
            rate_ti = (1 - ti) if kind == "ban" else ti
            table = self.threats[rate_ti]
            if not table:
                return []
            cands = []
            for hid in table:
                if hid in self.taken:
                    continue
                r = self.rating(rate_ti, hid)
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
                           "base": r["base"]},
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
                "teams": rosters,
                "suggestions": self.suggestions() if self.phase == "drafting" else [],
                "events": self.events[-40:],
                "summary": self.summary,
                "now_ms": int(now * 1000),
            }


# --------------------------------------------------------------------------
# Engine thread + HTTP server
# --------------------------------------------------------------------------

def _engine_loop(state, stop):
    while not stop.is_set():
        try:
            state.tick()
        except Exception as e:  # keep the clock alive no matter what
            print(f"  ⚠ engine tick error: {e}")
        stop.wait(0.25)


def _make_handler(state, page_bytes):
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
                self._send(200, "text/html; charset=utf-8", page_bytes)
            elif path == "/draft/state":
                self._json(200, state.snapshot())
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = self.path.split("?")[0]
            body = self._body()
            if path == "/draft/teams":
                ok, msg = state.set_teams(
                    body.get("mine", []),
                    body.get("enemy", []),
                    body.get("enemy_name"))
                self._json(200 if ok else 400, {"ok": ok, "msg": msg})
            elif path == "/draft/start":
                ok, msg = state.start(body.get("first", "random"),
                                      body.get("side", "random"))
                self._json(200 if ok else 400, {"ok": ok, "msg": msg})
            elif path == "/draft/act":
                ok, msg = state.act(state.my_team_index(), body.get("hid"))
                self._json(200 if ok else 400, {"ok": ok, "msg": msg})
            elif path == "/draft/reset":
                state.reset()
                self._json(200, {"ok": True})
            else:
                self._send(404, "text/plain", b"not found")

    return Handler


class _DraftServer(ThreadingHTTPServer):
    allow_reuse_address = False  # same loud-failure policy as --mock


def run_herodraft(season, port=None, offline=False, open_browser=True):
    from .herodraft_html import render_page

    port = port or config.HERODRAFT_PORT
    print("\n⚔ Loading hero-draft pool from cache...")
    label, pool, profiles, heroes = load_pool(season, offline=offline)
    if not pool:
        print("  ✗ No cached player pool. Run the scout once first "
              "(python ld2l_scout.py), then start --herodraft.")
        return
    league_players = sum(1 for p in profiles.values() if p["league"])
    print(f"  📜 {len(pool)} players, {len(heroes)} heroes "
          f"({league_players} players with league match history)")
    meta = load_meta(offline=offline)
    if meta["base"] or meta["adv"]:
        print(f"  📈 Patch meta: winrates for {len(meta['base'])} heroes, "
              f"matchup rows for {len(meta['adv'])} (ratings + win% on)")
    else:
        print("  ⚠ No patch meta cached (offline, never fetched) — ratings "
              "fall back to roster comfort only")

    state = DraftState(season, label, pool, profiles, heroes, meta)
    page = render_page(pool, heroes, label).encode("utf-8")

    try:
        server = _DraftServer(("127.0.0.1", port), _make_handler(state, page))
    except OSError as e:
        print(f"\n  ✗ Port {port} is already in use ({e}).\n    Close the other "
              f"window first (or change --port), then relaunch.\n")
        return

    stop = threading.Event()
    threading.Thread(target=_engine_loop, args=(state, stop), daemon=True).start()

    url = f"http://localhost:{port}/"
    print("\n" + "=" * 60)
    print("  ⚔ HERO DRAFT PRACTICE — Captains Mode vs the bot (patch 7.40 order)")
    print(f"  Pool: {label} | Build both rosters, flip for first pick, draft.")
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
        stop.set()
        server.server_close()
