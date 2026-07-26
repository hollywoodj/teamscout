"""Local MOCK auction draft — practice drafting against AI captains.

Fully local and self-contained. Nothing is ever sent to ld2l.org.

  - The player pool is rebuilt from the last scout run's cache (same offline
    path as `--offline`), so every player carries the tool's skill / role /
    price estimates.
  - Captain and budget authority is explicit: curated mode uses captains.json
    for preseason practice; official mode uses the finalized LD2L teams page
    (with a season-scoped offline cache). Dashboard-exported roles and the ⊘
    list apply in either mode.
  - A full English auction runs locally: a captain nominates a player, everyone
    bids up on a countdown, the highest bid wins. You (Hollywood by default)
    draft; the other seats are rational AI captains that value players by role
    need, remaining budget, and a set of per-captain target players you assign.
    Targets persist to mock_targets.json.
  - A ⏩ speed dial fast-forwards the dead air. Every timed window is divided by
    the same factor, so the auction plays out identically — just faster — and
    prices at 8x match prices at 1x. It brakes itself back to 1x the moment a
    player you HAVEN'T cut (✕ on the dashboard) is nominated, or when it's your
    turn, so you never blow past someone you wanted to bid on.

This serves your REAL scouting dashboard (the same file as --live) and drives
its ticker / feed / budgets / pick-marking off the auction, translating the mock
state into the same /live/state + /live/events shape the live follower emits. A
`mock` object in that snapshot powers the dashboard's interactive Start / seat /
nominate / bid controls — the one thing read-only live mode doesn't have.
"""

import atexit
import json
import os
import random
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

from . import config
from .broadcast import SSEHub, draft_snapshot, make_handler
from .captains import (load_official_teams, normalized_name,
                       override_team_budgets, resolve_team_identities)
from .analysis import position_ratings, value_tier
from .auction import annotate_players, load_history
from .cache import Cache
from .fetch import fetch_player_sections, players_from_snapshot
from .heroes import load_hero_map
from .analysis import build_metrics, pool_analysis
from .opendota import OpenDota
from .user_config import load_target_sets


# --------------------------------------------------------------------------
# Pool + captains
# --------------------------------------------------------------------------

def _player_slots(d, dash_roles=None):
    """Playable positions -> per-position skill (MMR) for a pool player.

    PRIMARY signal: the role circles set by hand on the dashboard (exported in
    captains.json's roles map) — they're the user's ground truth, and the only
    source that marks supports. Per-position skill comes from the measured
    rating where one exists, else the overall skill estimate.

    Fallback (player unmarked / no export): the tool's position_ratings —
    measured / part-time lanes plus the inferred primary, or all five at the
    estimated MMR when there's no signal at all.
    """
    pr = position_ratings(d)
    ratings = pr["ratings"] if pr else {}

    if dash_roles:
        est = d.get("adj_skill") or 0
        slots = {}
        for pos in dash_roles:
            r = ratings.get(pos)
            slots[pos] = r["mmr"] if r else est
        slots = {p: m for p, m in slots.items() if m}
        if slots:
            return slots

    if not pr:
        return {}
    primary = pr["primary"]
    slots = {pos: r["mmr"] for pos, r in ratings.items()
             if r["conf"] in ("measured", "part-time") or pos == primary}
    if not slots and primary:
        slots = {primary: ratings[primary]["mmr"]}
    if not slots:
        slots = {pos: r["mmr"] for pos, r in ratings.items()}
    return slots


def _base_value(d):
    """Best available $ anchor for a player (skill-priced, else listed price)."""
    for key in ("worth_cost", "est_cost"):
        v = d.get(key)
        if v:
            return v
    return config.MOCK_MIN_BID


def _spec_mult(slots, board_w):
    """Specialization/flexibility multiplier on a player's value.

    board_w is the player's spot on the value board, 1.0 = top, 0.0 = bottom.
    Specialization (a narrow, core-committed role profile) is rewarded at the top;
    flexibility (playing many positions) is rewarded at the bottom. A high-value
    play-anything generalist earns neither premium and is shaded a touch.
    """
    positions = {p for p in (slots or ()) if p in (1, 2, 3, 4, 5)}
    if not positions:
        return 1.0
    b = len(positions)
    core = 1.0 if positions & {1, 2} else 0.0          # can play carry/mid at all
    support = 1.0 if positions & {4, 5} else 0.0       # also queues support
    narrowness = (5 - b) / 4.0                          # b=1 -> 1.0, b=5 -> 0.0
    flexibility = (b - 1) / 4.0                         # b=1 -> 0.0, b=5 -> 1.0
    # committed core specialist: narrow, plays a core, doesn't moonlight support
    spec = core * narrowness * (1.0 - 0.5 * support)
    premium = config.MOCK_SPECIALIST_PREMIUM * board_w * spec
    shade = config.MOCK_GENERALIST_SHADE * board_w * flexibility
    flex_bonus = config.MOCK_FLEX_BONUS * (1.0 - board_w) * flexibility
    return 1.0 + premium - shade + flex_bonus


def _load_captains_file(all_data):
    """Read captains.json (exported from the dashboard).

    New shape: {"captains": [{name, steam32, budget, pos:[...]}], "roles":
    {steam32: [positions]}, "removed": [steam32]} — the roles map is the role
    circles the user set on the dashboard, the mock's PRIMARY role signal for the
    whole pool, and `removed` is the ⊘ list: players who are still on the
    scouting board but aren't in this draft, so they never enter the mock pool.
    The legacy plain-list shape (captains only) is still accepted. Returns
    (rows, roles, removed) where rows match scrape_budgets' shape ({captain,
    steam64, team_id, budget}), roles is {steam32: [pos]} and removed is a set of
    steam32; (None, {}, set()) when the file is absent/invalid.
    """
    path = config.MOCK_CAPTAINS_FILE
    if not os.path.exists(path):
        return None, {}, set()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  ⚠ Couldn't read {path}: {e}")
        return None, {}, set()
    roles, removed = {}, set()
    if isinstance(raw, dict):
        for k, v in (raw.get("roles") or {}).items():
            try:
                pos = sorted({int(x) for x in v if int(x) in (1, 2, 3, 4, 5)})
                if pos:
                    roles[int(k)] = pos
            except (TypeError, ValueError):
                continue
        for s in (raw.get("removed") or []):
            try:
                removed.add(int(s))
            except (TypeError, ValueError):
                continue
        raw = raw.get("captains")
    if not isinstance(raw, list):
        return None, {}, removed

    rows = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or c.get("captain") or "").strip()
        if not name:
            continue
        try:
            s32 = int(c["steam32"]) if c.get("steam32") is not None else None
        except (TypeError, ValueError):
            s32 = None
        try:
            budget = int(c["budget"]) if c.get("budget") is not None else None
        except (TypeError, ValueError):
            budget = None
        raw_pos = c.get("pos")
        try:  # accept a list (multi-role captain), a single int, or null
            if isinstance(raw_pos, (list, tuple)):
                pos = sorted({int(x) for x in raw_pos if x}) or None
            elif raw_pos is not None:
                pos = [int(raw_pos)]
            else:
                pos = None
        except (TypeError, ValueError):
            pos = None
        rows.append({
            "captain": name,
            "steam64": (s32 + config.STEAM64_OFFSET) if s32 is not None else None,
            "team_id": None,
            "budget": budget if budget is not None else config.MOCK_DEFAULT_BUDGET,
            "pos": pos,
        })
    if not rows:
        return None, {}, removed
    return rows, roles, removed


def _captains_from_signups(all_data):
    """Fallback captains: signup players flagged captain:yes (the dashboard's seed).

    Unlike the teams-page scrape, this can only ever return real signed-up
    players, so it never puts a regular player in a bidding seat. Budgets aren't
    known here, so each gets the default; export captains.json for real budgets.
    """
    rows = []
    for pd in all_data:
        p = pd["player"]
        if p.get("captain") == "Y":
            rows.append({
                "captain": p["name"],
                "steam64": p.get("steam64"),
                "team_id": None,
                "budget": config.MOCK_DEFAULT_BUDGET,
                "pos": None,
            })
    return rows


def _load_pool(season, offline, roster_source="curated"):
    """Build (label, pool, captains_raw, by_steam).

    pool     — draftable players (captains removed), each a dict the UI/AI use
    captains_raw — [{captain, steam64, team_id, budget, ...}] from ld2l.org/cache
    by_steam — steam32 -> data dict for everyone (so captain roles can be read)
    """
    cache = Cache()
    od = OpenDota()

    label, players = players_from_snapshot(cache, season)
    if not players:
        return None, [], [], {}

    hero_map = load_hero_map(od, cache, offline=offline)
    all_data = []
    for player in players:
        sections, _ = fetch_player_sections(od, cache, player, offline=True)
        data = build_metrics(player, sections, hero_map)
        all_data.append({"player": player, "data": data})

    blob = cache.get_blob("auction_history_v2") or {}
    history = blob.get("seasons", []) if isinstance(blob, dict) else []
    estimator = annotate_players(all_data, history)
    pool_analysis(all_data, price_estimator=estimator)

    # Browser-only roles/removals are independent of captain authority. This
    # keeps one dashboard/export bridge while preventing an old export from
    # replacing a finalized website roster.
    curated_rows, roles_map, removed = _load_captains_file(all_data)
    if roles_map:
        print(f"  🎯 Dashboard roles for {len(roles_map)} players "
              f"(primary role signal)")
    else:
        print(f"  ⚠ No roles in {config.MOCK_CAPTAINS_FILE} — falling back to "
              f"measured lanes")

    if roster_source == "official":
        captains_raw, official_from, roster_err = load_official_teams(
            season, cache, offline=offline
        )
        if roster_err:
            print(f"  ⚠ {roster_err}")
        if captains_raw:
            print(f"  👑 Official captains from {official_from}: "
                  + ", ".join(t["captain"] for t in captains_raw))
    else:
        captains_raw = curated_rows or _captains_from_signups(all_data)
        if curated_rows:
            print(f"  👑 Curated captains from {config.MOCK_CAPTAINS_FILE}: "
                  + ", ".join(t["captain"] for t in captains_raw))
        elif captains_raw:
            print(f"  👑 Using signup captain:yes as captains: "
                  + ", ".join(t["captain"] for t in captains_raw))
        else:
            captains_raw, official_from, roster_err = load_official_teams(
                season, cache, offline=offline
            )
            if roster_err:
                print(f"  ⚠ {roster_err}")
            elif captains_raw:
                print(f"  👑 No curated captains; fallback from {official_from}: "
                      + ", ".join(t["captain"] for t in captains_raw))
        _, budgets_err = override_team_budgets(captains_raw)
        if budgets_err:
            print(f"  ⚠ budgets.json ignored: {budgets_err}")

    players_only = [pd["player"] for pd in all_data]
    captains_raw, unresolved = resolve_team_identities(
        captains_raw or [], players_only
    )
    if unresolved:
        print("  ⚠ Unresolved captains excluded: " + ", ".join(unresolved))

    # Official identities and budgets still use the captain's exported role
    # circles when available.
    for row in captains_raw:
        s32 = int(row["steam64"]) - config.STEAM64_OFFSET
        if roles_map.get(s32):
            row["pos"] = roles_map[s32]

    captain_s32 = set()
    for t in captains_raw:
        if t.get("steam64"):
            captain_s32.add(int(t["steam64"]) - config.STEAM64_OFFSET)

    by_steam = {pd["player"]["steam32"]: pd["data"] for pd in all_data}

    # Players you removed from the draft on the dashboard (the ⊘ button): they
    # stay in the scouting board and in by_steam, they're just never for sale.
    dropped = [pd["player"]["name"] for pd in all_data
               if pd["player"]["steam32"] in removed]
    if dropped:
        print(f"  ⊘ Off the draft ({len(dropped)}, from "
              f"{config.MOCK_CAPTAINS_FILE}): " + ", ".join(dropped))

    pool = []
    unresolved_names = {normalized_name(name) for name in unresolved}
    for pd in all_data:
        p, d = pd["player"], pd["data"]
        s32 = p["steam32"]
        if s32 in captain_s32:
            continue  # captains (from captains.json / teams page) aren't draftable
        if normalized_name(p.get("name")) in unresolved_names:
            continue  # ambiguous identity: neither bidder nor buyable player
        if s32 in removed:
            continue  # you took them off the draft — not in the auction at all
        slots = _player_slots(d, roles_map.get(s32))
        if not slots:
            continue
        pool.append({
            "steam32": s32,
            "name": p["name"],
            "mmr": p.get("mmr") or 0,
            "adj_skill": d.get("adj_skill"),
            "worth": d.get("worth_cost"),
            "est": d.get("est_cost"),
            "value_tier": value_tier(d),
            "base_value": _base_value(d),
            "slots": {int(k): int(v) for k, v in slots.items()},
            "primary": position_ratings(d).get("primary"),
        })
    # Specialization premium: top-end specialists bid up, top-end generalists shaded,
    # flexibility rewarded down the board (see _spec_mult). board_w is the player's
    # value rank, so it's computed off the pre-premium base_value. Moves both the
    # market anchor (base_value) and the displayed worth so prices, the star cut and
    # the hard floor stay coherent.
    n = len(pool)
    ranked = sorted(range(n), key=lambda i: -(pool[i]["base_value"] or 0))
    board_w = {i: (1.0 - r / (n - 1)) if n > 1 else 1.0 for r, i in enumerate(ranked)}
    for i, pl in enumerate(pool):
        mult = _spec_mult(pl["slots"], board_w[i])
        if mult != 1.0:
            pl["base_value"] = max(config.MOCK_MIN_BID,
                                   int(round((pl["base_value"] or config.MOCK_MIN_BID) * mult)))
            if pl["worth"]:
                pl["worth"] = int(round(pl["worth"] * mult))
    pool.sort(key=lambda pl: -(pl["base_value"] or 0))
    # Mark the top MOCK_BPA_STARS by value as "stars": the known quantities every
    # captain chases even off-role, so they stay contested (see Team.valuation).
    cut = sorted((pl["base_value"] or 0 for pl in pool), reverse=True)
    cut = cut[config.MOCK_BPA_STARS - 1] if len(cut) >= config.MOCK_BPA_STARS else 0
    for pl in pool:
        pl["is_star"] = bool(pl["base_value"]) and pl["base_value"] >= cut
    return label, pool, captains_raw, by_steam


# --------------------------------------------------------------------------
# Teams + AI strategy
# --------------------------------------------------------------------------

POSITIONS = (1, 2, 3, 4, 5)


def _match_positions(units):
    """Maximum bipartite matching of units -> distinct positions.

    units: list of position lists, each ordered by that unit's preference
    (strongest first). Returns {unit_index: position} for a maximum matching;
    earlier units keep their preferred seats when possible, later flexes fill in.
    """
    owner = {}  # position -> unit index

    def assign(i, seen):
        for p in units[i]:
            if p in seen:
                continue
            seen.add(p)
            if p not in owner or assign(owner[p], seen):
                owner[p] = i
                return True
        return False

    for i in range(len(units)):
        assign(i, set())
    return {i: p for p, i in owner.items()}


def _pref_order(slots):
    """Playable positions ordered strongest-first (by per-position MMR)."""
    return sorted(slots, key=lambda p: -slots[p])


class Team:
    def __init__(self, captain, budget, team_id, captain_pos, is_me, aggr,
                 steam32=None):
        self.captain = captain
        self.steam32 = steam32
        self.team_id = team_id
        self.start_budget = budget
        self.budget = budget
        # positions the captain can cover — a SET now; the captain flexes onto
        # whichever of their roles the drafted players leave open
        self.cap_pos = set(captain_pos or ())
        self.is_me = is_me
        self.aggr = aggr                    # deterministic value jitter
        self.roster = []                    # [{steam32,name,price,pos,prefs}]
        self.targets = set()                # steam32s this captain is gunning for

    @property
    def full(self):
        return len(self.roster) >= config.MOCK_BUYS

    @property
    def slots_left(self):
        return config.MOCK_BUYS - len(self.roster)

    # ---- role assignment (captain + bought players -> distinct positions) ----
    def _units(self, extra=None):
        units = []
        if self.cap_pos:
            units.append(sorted(self.cap_pos))
        units.extend(r["prefs"] for r in self.roster)
        if extra is not None:
            units.append(extra)
        return units

    def open_positions(self):
        """Positions no current assignment of captain+roster can cover."""
        assign = _match_positions(self._units())
        return set(POSITIONS) - set(assign.values())

    def fills_open(self, player):
        """True iff adding this player covers a position the team otherwise
        can't — computed against everyone's full flexibility, so a P3/P4 flex
        still counts as filling P4 when P3 is already spoken for."""
        base = len(_match_positions(self._units()))
        return len(_match_positions(self._units(_pref_order(player["slots"])))) > base

    def affordable(self):
        """Most this team can spend now and still keep $ for its other slots."""
        reserve = max(0, self.slots_left - 1) * config.MOCK_RESERVE_PER_SLOT
        return self.budget - reserve

    def valuation(self, player, avail=None):
        """(value$, best_pos) — what this player is worth to THIS team.

        Fills an open seat -> market value. Redundant -> off-role logic: a
        captain WILL burn a seat and shuffle someone off-role for a clearly
        better player, worth MOCK_OFFROLE_MULT × their value — but only when
        that discounted value still beats the best on-role player left in
        `avail` (the opportunity cost of the seat). A Legend core therefore
        outbids a Crusader support filler but not an Ancient one. Hard-capped
        at MOCK_MAX_OVERPAY × worth so nothing stacks into an obvious overbid.
        """
        slots = player["slots"]
        if not slots:
            return 0, None
        prefs = _pref_order(slots)
        base_n = len(_match_positions(self._units()))
        with_p = _match_positions(self._units(prefs))
        fills = len(with_p) > base_n
        # the seat the matching actually gives them (candidate = last unit)
        seat = with_p.get(len(self._units()))
        base = player["base_value"] or config.MOCK_MIN_BID
        if fills:
            need = config.MOCK_NEED_FILLS
        else:
            # bench money only if the team has body slots to spare...
            spare = self.slots_left - (len(POSITIONS) - base_n)
            need = config.MOCK_NEED_REDUNDANT if spare > 0 else 0.0
            # ...unless they're a big enough talent to justify an off-role
            # shuffle: compare the discounted star to the best available filler
            if avail is not None:
                best_fill = 0
                for pl2 in avail:
                    if pl2["steam32"] == player["steam32"]:
                        continue
                    v2 = pl2["base_value"] or 0
                    if v2 > best_fill and self.fills_open(pl2):
                        best_fill = v2
                if base * config.MOCK_OFFROLE_MULT > best_fill:
                    need = max(need, config.MOCK_OFFROLE_MULT)
            # best-player-available: a genuine star still draws a competitive bid
            # even off-role, so the known quantities don't hammer for bench money.
            if player.get("is_star") and self.slots_left > 0:
                need = max(need, config.MOCK_BPA_FLOOR_MULT)
        best_pos = seat if fills else prefs[0]
        tgt = config.MOCK_TARGET_PREMIUM if player["steam32"] in self.targets else 1.0
        val = min(base * need * tgt * self.aggr,
                  base * config.MOCK_MAX_OVERPAY)   # hard overbid ceiling
        return val, best_pos

    def max_bid(self, player, avail=None):
        val, _ = self.valuation(player, avail)
        return max(0, int(min(round(val), self.affordable())))

    def acquire(self, player, price):
        if price > self.budget:  # every bid path should prevent this — surface it
            print(f"  ⚠ BUG: {self.captain} paid ${price} with only ${self.budget}")
        self.budget = max(0, self.budget - price)
        self.roster.append({"steam32": player["steam32"], "name": player["name"],
                            "price": price, "pos": None,
                            "prefs": _pref_order(player["slots"])})
        self._reassign()

    def _reassign(self):
        """Recompute every bought player's seat from the full-team matching —
        an early flex pick slides roles as later picks lock positions down."""
        assign = _match_positions(self._units())
        offset = 1 if self.cap_pos else 0   # unit 0 is the captain when present
        for idx, r in enumerate(self.roster):
            r["pos"] = assign.get(idx + offset, r["prefs"][0] if r["prefs"] else None)


def _captain_positions(by_steam, steam64):
    """Fallback role set for a captain: their measured primary position."""
    if not steam64:
        return set()
    d = by_steam.get(int(steam64) - config.STEAM64_OFFSET)
    if not d:
        return set()
    primary = position_ratings(d).get("primary")
    return {primary} if primary else set()


# --------------------------------------------------------------------------
# Targets persistence
# --------------------------------------------------------------------------

def _load_targets(path):
    try:
        return load_target_sets(path)
    except (OSError, ValueError) as e:
        if os.path.exists(path):
            print(f"  ⚠ {path} ignored: {e}")
        return {}


def _save_targets(path, teams):
    data = {t.captain: sorted(t.targets) for t in teams.values() if t.targets}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"  ⚠ couldn't save targets: {e}")


# --------------------------------------------------------------------------
# Mock state (thread-safe) + SSE
# --------------------------------------------------------------------------

class MockState:
    def __init__(self, season, label, pool, captains_raw, by_steam, me,
                 roster_source="curated"):
        self._lock = threading.RLock()
        self.hub = SSEHub()    # open SSE writers, fanned out by broadcast.py
        self.season = season
        self.label = label
        self.roster_source = roster_source
        self.pool = {pl["steam32"]: pl for pl in pool}
        self.drafted = set()
        self.by_steam = by_steam
        self.events = []
        self.targets_path = config.MOCK_TARGETS_FILE

        # build teams (nomination order = scrape order)
        saved = _load_targets(self.targets_path)
        self.order = []
        self.teams = {}
        for t in captains_raw:
            cap = t.get("captain")
            if not cap:
                continue
            aggr = random.Random(cap).uniform(*config.MOCK_AI_AGGR_RANGE)
            cpos = t.get("pos")  # dashboard-curated role set wins; else measured
            if not cpos:
                cpos = _captain_positions(by_steam, t.get("steam64"))
            steam32 = (int(t["steam64"]) - config.STEAM64_OFFSET
                       if t.get("steam64") else None)
            team = Team(cap, int(t.get("budget") or 0), t.get("team_id"),
                        cpos, is_me=False, aggr=aggr, steam32=steam32)
            team.targets = saved.get(cap, set()) & set(self.pool)
            self.teams[cap] = team
            self.order.append(cap)
        self.order.sort(key=lambda captain: self.teams[captain].start_budget)
        self.set_me(me, silent=True)

        # auction runtime
        self.phase = "setup"          # setup|countdown|nominating|bidding|sold|done
        self.order_idx = -1
        self.nominator = None
        self.nominee = None           # pool player dict | None
        self.high_bid = 0
        self.high_bidder = None
        self.deadline = 0
        self.window = 0               # length (s) of the current timed window
        self.bid_count = 0            # bids on the current nominee (clock shrink)
        self.last_sold = None         # {steam32, name, to, price} of last hammer

        self.started = threading.Event()
        self.human_nominated = threading.Event()
        self.reset_flag = threading.Event()
        self.paused = threading.Event()
        self._paused_remaining = 0.0   # seconds frozen on the clock while paused

        # fast-forward: every timed window is divided by `speed`, and the engine
        # brakes back to 1x when a player you HAVEN'T cut (✕) comes up. `cuts` is
        # a copy of the dashboard's localStorage cut list, pushed by the page.
        self.speed = 1.0
        self.cuts = set()

    # ---- seat ----
    def set_me(self, me, silent=False):
        with self._lock:
            for t in self.teams.values():
                t.is_me = False
            if me and me in self.teams:
                self.teams[me].is_me = True
                self.me = me
            else:
                # default: first captain if the requested name isn't present
                self.me = next(iter(self.teams), None)
                if self.me:
                    self.teams[self.me].is_me = True
        if not silent:
            self.add_event("status", text=f"You are drafting as {self.me}")

    # ---- events / SSE ----
    def add_event(self, kind, **fields):
        with self._lock:
            ts = time.time()
            # measured_at_ms + bid_ms are what the main dashboard's live ticker
            # reads to drive its countdown; carry them on every relevant event so
            # the mock feeds the exact same shape the --live follower emits.
            fields.update({"kind": kind, "ts": ts, "measured_at_ms": int(ts * 1000)})
            if kind in ("nominate", "bid"):
                fields.setdefault("bid_ms", int((self.window or 0) * 1000) or 15000)
            self.events.append(fields)
            del self.events[:-120]
        # fan out to connected SSE clients (outside the state lock)
        self.hub.broadcast(fields)

    # ---- live-shaped snapshot (drives the MAIN dashboard) ----
    # The dashboard was built to follow the real --live draft, so it already
    # renders picks, the nomination ticker + countdown, the feed and budgets from
    # this exact shape. We translate the mock auction into it, plus a `mock`
    # sub-object carrying everything the interactive controls need.
    FEED_KINDS = ("pick", "nominate", "bid", "sold", "status")

    def live_snapshot(self):
        with self._lock:
            now = time.time()
            picks = []
            for t in self.teams.values():
                for r in t.roster:
                    picks.append({
                        "steam32": r["steam32"], "cost": r["price"],
                        "team_id": t.team_id, "captain": t.captain,
                        "is_captain": False,
                    })
            nomination = None
            if self.phase == "bidding" and self.nominee:
                start = self.deadline - self.window          # when this clock began
                nomination = {
                    "steam32": self.nominee["steam32"],
                    "name": self.nominee["name"],
                    "by": self.high_bidder,
                    "amount": self.high_bid,
                    "bid_ms": int(self.window * 1000),
                    "ts": start,
                    "measured_at_ms": int(start * 1000),
                }
            events = [e for e in self.events[-60:] if e.get("kind") in self.FEED_KINDS]

            me_team = self.teams.get(self.me)
            my_turn = self.phase == "nominating" and bool(me_team and me_team.is_me
                                                          and self.nominator == self.me)
            avail = [{"steam32": s, "name": pl["name"],
                      "positions": sorted(pl["slots"]), "worth": pl["worth"]}
                     for s, pl in self.pool.items() if s not in self.drafted]
            avail.sort(key=lambda p: (p["worth"] is None, -(p["worth"] or 0)))
            teams = [{"captain": t.captain, "steam32": t.steam32,
                      "budget": t.budget,
                      "start_budget": t.start_budget, "slots_left": t.slots_left,
                      "is_me": t.is_me, "full": t.full,
                      "cap_pos": sorted(t.cap_pos),
                      "open_pos": sorted(t.open_positions())} for t in
                     (self.teams[c] for c in self.order)]
            mock = {
                "phase": self.phase,
                "roster_source": self.roster_source,
                "me": self.me,
                "started": self.started.is_set(),
                "paused": self.paused.is_set(),
                "nominator": self.nominator,
                "my_turn": my_turn,
                # the auction row (and its bid buttons) render off this; without it
                # every poll would wipe the buttons that an SSE event drew in
                "nominee": ({"steam32": self.nominee["steam32"],
                             "name": self.nominee["name"]}
                            if self.phase == "bidding" and self.nominee else None),
                "high_bid": self.high_bid,
                "high_bidder": self.high_bidder,
                "i_am_high": self.high_bidder == self.me,
                "can_bid": (self.phase == "bidding" and self.high_bidder != self.me
                            and not self.paused.is_set()
                            and bool(me_team and not me_team.full
                                     and me_team.affordable() > self.high_bid)),
                "deadline_ms": int(self.deadline * 1000)
                    if self.phase in ("bidding", "countdown") else None,
                "window_ms": int(self.window * 1000) if self.window else None,
                "now_ms": int(now * 1000),
                "buys": config.MOCK_BUYS,
                "min_bid": config.MOCK_MIN_BID,
                # the dial reads its value back from here, so the automatic
                # brake visibly snaps it to 1x instead of lying about the tempo
                "speed": self.speed,
                "speeds": list(config.MOCK_SPEEDS),
                "last_sold": dict(self.last_sold) if self.last_sold else None,
                "teams": teams,
                "pool": avail,
            }
            return draft_snapshot(
                season=self.season, mode="mock",
                picks=picks,
                captains={str(t.team_id): t.captain
                          for t in self.teams.values() if t.team_id},
                budgets={t.captain: t.start_budget for t in self.teams.values()},
                nomination=nomination,
                round=None,
                events=events,
                poll_ok=True, poll_error=None, socket_on=True,
                updated=now, mock=mock,
            )

    # ---- human actions (from POST handlers) ----
    def toggle_target(self, captain, steam32, on):
        with self._lock:
            t = self.teams.get(captain)
            if not t or steam32 not in self.pool:
                return False
            if on:
                t.targets.add(steam32)
            else:
                t.targets.discard(steam32)
        _save_targets(self.targets_path, self.teams)
        self.add_event("target", captain=captain, steam32=steam32, on=on)
        return True

    def human_nominate(self, steam32, opening):
        with self._lock:
            if self.paused.is_set():
                return False, "paused"
            if self.phase != "nominating" or not self.teams[self.nominator].is_me:
                return False, "not your nomination"
            pl = self.pool.get(steam32)
            if not pl or steam32 in self.drafted:
                return False, "player unavailable"
            me = self.teams[self.me]
            try:
                opening = max(
                    config.MOCK_MIN_BID,
                    int(opening or config.MOCK_MIN_BID),
                )
            except (TypeError, ValueError):
                return False, "invalid opening bid"
            cap = me.affordable()
            if opening > cap:
                return False, ("over budget" if opening > me.budget else
                               f"max ${max(cap, 0)} — keep ${config.MOCK_RESERVE_PER_SLOT}"
                               f"/slot for your other open seats")
            self._open_auction(pl, opening, self.me)
        self.human_nominated.set()
        return True, "ok"

    def human_bid(self, amount):
        with self._lock:
            if self.paused.is_set():
                return False, "paused"
            if self.phase != "bidding" or not self.nominee:
                return False, "no live auction"
            me = self.teams[self.me]
            if me.full:
                return False, "roster full"
            if self.high_bidder == self.me:
                return False, "you're already high"
            try:
                amount = int(amount or 0)
            except (TypeError, ValueError):
                return False, "invalid bid"
            if amount <= self.high_bid:
                return False, f"must beat ${self.high_bid}"
            cap = me.affordable()
            if amount > cap:
                # same reserve rule the AIs live by: never bid so much that a
                # remaining open slot can't even make a minimum bid
                return False, ("over budget" if amount > me.budget else
                               f"max ${max(cap, 0)} — keep ${config.MOCK_RESERVE_PER_SLOT}"
                               f"/slot for your other open seats")
            self._place_bid(self.me, amount)
        return True, "ok"

    # ---- internal auction transitions (call under lock) ----
    def _open_auction(self, player, opening, bidder):
        self.nominee = player
        self.high_bid = opening
        self.high_bidder = bidder
        self.bid_count = 0
        self.window = self.scale(config.MOCK_NOMINATION_SECONDS)
        self.deadline = time.time() + self.window
        self.phase = "bidding"
        self.add_event("nominate", steam32=player["steam32"], name=player["name"],
                       by=bidder, amount=opening)

    def _place_bid(self, bidder, amount):
        self.high_bid = amount
        self.high_bidder = bidder
        # site-faithful shrinking clock: reset = 15s − 1s per bid, floor 8s
        self.bid_count += 1
        self.window = self.scale(max(config.MOCK_NOMINATION_SECONDS - self.bid_count,
                                     config.MOCK_BID_SECONDS_FLOOR))
        self.deadline = time.time() + self.window
        self.add_event("bid", by=bidder, amount=amount,
                       steam32=self.nominee["steam32"])

    # ---- fast-forward (speed dial + automatic brake) ----
    def scale(self, seconds):
        """Turn a real-time duration into its fast-forwarded length."""
        return seconds / self.speed

    def set_speed(self, x):
        """Set the fast-forward factor, rescaling any live window in place.

        The REMAINING time is rescaled rather than the window restarted, so
        hitting 8x in the middle of a slow bid war compresses it immediately
        instead of only taking effect on the next player. Clamped to
        [1, MOCK_MAX_SPEED] so a hand-made POST can't drive a sleep to zero and
        spin the engine thread. Returns the speed actually applied.
        """
        with self._lock:
            try:
                new = max(1.0, min(float(config.MOCK_MAX_SPEED), float(x)))
            except (TypeError, ValueError):
                return self.speed
            old = self.speed
            if new == old:
                return old
            self.speed = new
            ratio = old / new
            fields = {"speed": new}
            if self.paused.is_set():
                # frozen — rescale the held remainder; resume() re-arms the clock
                self._paused_remaining *= ratio
                self.window = self._paused_remaining
            elif self.phase in ("countdown", "bidding"):
                rem = max(0.0, self.deadline - time.time()) * ratio
                self.deadline = time.time() + rem
                self.window = rem
                # the dashboard's countdown reads bid_ms off the last event, so
                # a live auction needs the new remaining time pushed to it (same
                # trick resume() uses coming out of a pause)
                if self.phase == "bidding" and self.nominee:
                    fields["bid_ms"] = int(rem * 1000)
        self.add_event("speed", **fields)
        return new

    def set_cuts(self, cuts):
        """Replace the ✕ cut list pushed by the dashboard.

        localStorage owns this list; the server keeps a transient copy purely so
        the brake can fire at nomination time, before the auction window opens.
        """
        clean = set()
        for s in cuts or ():
            try:
                clean.add(int(s))
            except (TypeError, ValueError):
                continue
        with self._lock:
            self.cuts = clean
        return len(clean)

    def brake(self, reason):
        """Leave fast-forward, announcing why. Call BEFORE opening a window.

        Resetting the speed first is what makes the brake useful: the auction
        that follows then opens on a full-length clock instead of the compressed
        tail of one, so there's actually time to react.
        """
        if self.speed <= 1.0:
            return False
        self.set_speed(1.0)
        self.add_event("status", text=f"⏩ stopped — {reason}")
        print(f"  ⏩ Fast-forward stopped — {reason}")
        return True

    # ---- pause / resume (freeze the live clock + AI, no site writes) ----
    def toggle_pause(self):
        """Flip pause on/off. Returns the resulting paused state."""
        if self.paused.is_set():
            self.resume()
        else:
            self.pause()
        return self.paused.is_set()

    def pause(self):
        """Freeze the auction: hold the countdown/bid clock and stall the AI.

        Only meaningful while a timed window is live (countdown / nominating /
        bidding). The seconds remaining are captured so resume picks up exactly
        where it left off; the engine loops keep the deadline pinned meanwhile.
        """
        with self._lock:
            if self.paused.is_set() or self.phase not in (
                    "countdown", "nominating", "bidding"):
                return False
            self.paused.set()
            if self.phase in ("countdown", "bidding"):
                rem = max(0.0, self.deadline - time.time())
                self._paused_remaining = rem
                self.deadline = time.time() + rem
                self.window = rem
            else:
                self._paused_remaining = 0.0
        self.add_event("pause", paused=True)
        print("  ⏸  Mock draft paused.")
        return True

    def resume(self):
        """Unfreeze: restart the clock from the frozen remaining time.

        For a live bid, the emitted event carries the remaining time so the
        dashboard's countdown restarts from where it stopped instead of the
        stale pre-pause reference (which would read as already expired).
        """
        with self._lock:
            if not self.paused.is_set():
                return False
            self.paused.clear()
            rem = self._paused_remaining
            self._paused_remaining = 0.0
            fields = {"paused": False}
            if self.phase in ("countdown", "bidding"):
                self.deadline = time.time() + rem
                self.window = rem
                if self.phase == "bidding" and self.nominee:
                    fields["bid_ms"] = int(rem * 1000)
        self.add_event("pause", **fields)
        print("  ▶  Mock draft resumed.")
        return True


# --------------------------------------------------------------------------
# Auction engine (background thread)
# --------------------------------------------------------------------------

def _paused_hold(state):
    """While paused, keep the live deadline pinned so nothing expires.

    Returns True when paused (the caller should idle-tick and skip its own AI /
    expiry work), False otherwise.
    """
    if not state.paused.is_set():
        return False
    with state._lock:
        if state.phase in ("countdown", "bidding"):
            state.deadline = time.time() + state._paused_remaining
    return True

def _next_nominator(state):
    """Advance round-robin to the next captain with roster space (or None)."""
    with state._lock:
        n = len(state.order)
        if not state.pool_available():
            return None
        for _ in range(n):
            state.order_idx = (state.order_idx + 1) % n
            cap = state.order[state.order_idx]
            team = state.teams[cap]
            if not team.full and team.affordable() >= config.MOCK_MIN_BID:
                return cap
    return None


def _ai_nominate(state, cap):
    with state._lock:
        team = state.teams[cap]
        avail = [pl for s, pl in state.pool.items() if s not in state.drafted]
        if not avail:
            return False
        if team.affordable() < config.MOCK_MIN_BID:
            # broke seat can't open an auction (shouldn't happen — the reserve
            # rule keeps $1 per open slot).
            print(f"  ⚠ {cap} can't preserve its slot reserve — skipping")
            return False
        pick = max(avail, key=lambda pl: team.valuation(pl, avail)[0])
        if team.valuation(pick, avail)[0] <= 0:
            # nobody left fills this team's open seats (supply exhausted) — a
            # body is still owed, so take the best value on the board
            pick = max(avail, key=lambda pl: pl["base_value"] or 0)
        # Brake BEFORE opening: a player you haven't cut (✕) is someone you may
        # want to bid on, so leave fast-forward first and let _open_auction give
        # them a full-length clock instead of a compressed tail.
        if pick["steam32"] not in state.cuts:
            state.brake(f"{pick['name']} is up")
        opening = min(config.MOCK_MIN_BID, team.budget)
        state._open_auction(pick, opening, cap)
        print(f"  🗣  {cap} nominates {pick['name']} (${opening})")
    return True


def _ai_bid_round(state):
    """Maybe place ONE AI raise this tick.

    The pacing gate is rolled once per tick (not per team): with many eager
    captains, a per-team roll would fire almost every tick and the tempo knob
    would do nothing. So the cadence is exactly MOCK_AI_TICK / MOCK_AI_RAISE_PROB
    seconds between bids, and a single random eager captain makes the raise.
    """
    with state._lock:
        if state.phase != "bidding" or not state.nominee:
            return
        if random.random() >= config.MOCK_AI_RAISE_PROB:
            return  # this tick nobody moves — spaces the bids out
        pl = state.nominee
        avail = [p for s, p in state.pool.items() if s not in state.drafted]
        eager = [state.teams[c] for c in state.order
                 if c != state.high_bidder and not state.teams[c].is_me
                 and not state.teams[c].full
                 and state.teams[c].max_bid(pl, avail) > state.high_bid]
        if not eager:
            return
        team = random.choice(eager)
        mb = team.max_bid(pl, avail)
        gap = mb - state.high_bid
        # People click +1 most of the time, +5 sometimes, +25 rarely —
        # clamped so a raise never overshoots this team's own ceiling.
        step = random.choices(config.MOCK_BID_STEPS,
                              weights=config.MOCK_BID_STEP_WEIGHTS)[0]
        step = min(step, max(config.MOCK_BID_INCREMENT, gap))
        amount = min(state.high_bid + step, mb)
        if amount > state.high_bid:
            state._place_bid(team.captain, amount)
            print(f"  💰 {team.captain} bids ${amount} on {pl['name']}")


def _resolve_sale(state):
    with state._lock:
        pl, winner, price = state.nominee, state.high_bidder, state.high_bid
        if pl is None or winner is None:
            return
        team = state.teams[winner]
        # Hard backstop: don't let a player hammer far below worth just because the
        # room went quiet. Bump to the floor, capped at the winner's budget so it
        # never overdrafts (they already cleared the auction within budget).
        worth = pl.get("worth") or pl.get("base_value") or 0
        if worth:
            floor = min(
                int(round(config.MOCK_SALE_FLOOR_MULT * worth)),
                max(0, team.affordable()),
            )
            if price < floor:
                price = floor
        team.acquire(pl, price)
        state.drafted.add(pl["steam32"])
        state.phase = "sold"
        tag = " (you)" if team.is_me else ""
        print(f"  🔨 SOLD: {pl['name']} -> {winner}{tag} for ${price}")
        state.last_sold = {"steam32": pl["steam32"], "name": pl["name"],
                           "to": winner, "price": price, "is_me": team.is_me}
        state.add_event("sold", steam32=pl["steam32"], name=pl["name"],
                        to=winner, price=price, is_me=team.is_me)
        # pick event mirrors the --live follower so the dashboard feed shows the
        # hammer ("$X to captain") and the row/budget marking flows in.
        state.add_event("pick", steam32=pl["steam32"], name=pl["name"], cost=price,
                        captain=winner, team_id=team.team_id, is_captain=False)
        state.nominee = None
        state.high_bid = 0
        state.high_bidder = None


def _run_open_auction(state, stop):
    while not stop.is_set() and not state.reset_flag.is_set():
        with state._lock:
            phase, deadline = state.phase, state.deadline
        if phase != "bidding":
            return
        if _paused_hold(state):
            stop.wait(0.1)
            continue
        if time.time() >= deadline:
            return
        _ai_bid_round(state)
        # scaled in lockstep with the bid window, so the expected number of
        # raises per auction — and therefore the sale price — is unchanged
        stop.wait(state.scale(config.MOCK_AI_TICK))


def _countdown(state, stop):
    """10-second 'the draft is starting in N…' beat right after Start is hit."""
    if config.MOCK_START_COUNTDOWN <= 0:
        return True
    with state._lock:
        secs = state.scale(config.MOCK_START_COUNTDOWN)
        state.phase = "countdown"
        state.window = secs
        state.deadline = time.time() + secs
    state.add_event("status",
                    text=f"The draft is starting in {int(round(secs))}…")
    last = None
    while not stop.is_set() and not state.reset_flag.is_set():
        if _paused_hold(state):
            stop.wait(0.1)
            continue
        with state._lock:
            left = state.deadline - time.time()
        if left <= 0:
            return True
        n = int(left) + 1
        if n != last:                      # one console line per second
            print(f"  ⏳ The draft is starting in {n}…")
            last = n
        stop.wait(0.1)
    return False  # interrupted (stop/reset)


def _run_draft(state, stop):
    if not _countdown(state, stop):
        return
    while not stop.is_set() and not state.reset_flag.is_set():
        cap = _next_nominator(state)
        if cap is None:
            with state._lock:
                state.phase = "done"
                complete = all(t.full for t in state.teams.values())
            text = ("Draft complete — all rosters full." if complete else
                    "Draft ended — no team can make another valid nomination.")
            state.add_event("status", text=text)
            print(f"\n  {'✅' if complete else '⚠'} {text}\n")
            state.started.clear()
            return
        with state._lock:
            state.phase = "nominating"
            state.nominator = cap
            is_me = state.teams[cap].is_me
            # your own turn always ends the fast-forward — the engine blocks on
            # you here regardless, and without this the auction YOU open would
            # run on a compressed clock
            if is_me:
                state.brake("your nomination")
        state.add_event("turn", nominator=cap, is_me=is_me)
        if is_me:
            state.human_nominated.clear()
            while not stop.is_set() and not state.reset_flag.is_set():
                if state.human_nominated.wait(0.2):
                    break
            if stop.is_set() or state.reset_flag.is_set():
                return
        else:
            stop.wait(state.scale(config.MOCK_AI_NOMINATE_DELAY))
            # hold the AI's nomination while paused so the board stays frozen
            while state.paused.is_set() and not stop.is_set() \
                    and not state.reset_flag.is_set():
                stop.wait(0.1)
            if stop.is_set() or state.reset_flag.is_set():
                return
            _ai_nominate(state, cap)
        _run_open_auction(state, stop)
        if state.reset_flag.is_set():
            return
        _resolve_sale(state)
        stop.wait(state.scale(0.6))  # brief 'sold' beat


def _auction_loop(state, stop):
    while not stop.is_set():
        if not state.started.wait(0.3):
            if state.reset_flag.is_set():
                state.reset_flag.clear()
            continue
        # Consume a reset that's still pending as we enter the draft. Without
        # this, hitting Reset and then Start before the loop came back around
        # left the flag set: _run_draft would bail out instantly, and because the
        # flag was only cleared on the not-started path above, the loop spun on a
        # core and the draft never actually began.
        state.reset_flag.clear()
        _run_draft(state, stop)


# add small helpers to MockState used above (kept here to keep the class lean)
def _pool_available(self):
    return any(s not in self.drafted for s in self.pool)


MockState.pool_available = _pool_available


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

class _MockServer(ThreadingHTTPServer):
    # See run_mock: refuse to co-bind a port an older --mock/--live still holds.
    allow_reuse_address = False


def _mock_post(state):
    """Route the dashboard's interactive Mock-bar POSTs to engine actions.

    Returns ``post_handler(path, body) -> (code, obj) | None`` for
    broadcast.make_handler; ``None`` means an unmatched path (404). This is the
    one thing read-only --live deliberately lacks.
    """
    def post_handler(path, body):
        if path == "/mock/start":
            state.started.set()
            return 200, {"ok": True}
        if path == "/mock/pause":
            return 200, {"ok": True, "paused": state.toggle_pause()}
        if path == "/mock/reset":
            state.reset_flag.set()
            state.started.clear()
            _reset_state(state)
            return 200, {"ok": True}
        if path == "/mock/speed":
            return 200, {"ok": True, "speed": state.set_speed(body.get("x"))}
        if path == "/mock/cuts":
            # the dashboard's ✕ list (localStorage owns it) — used only to
            # decide who fast-forward should NOT brake for
            return 200, {"ok": True, "cuts": state.set_cuts(body.get("cuts"))}
        if path == "/mock/me":
            state.set_me(body.get("captain"))
            return 200, {"ok": True, "me": state.me}
        if path == "/mock/target":
            try:
                steam32 = int(body.get("steam32", 0))
            except (TypeError, ValueError):
                steam32 = 0
            ok = state.toggle_target(body.get("captain"), steam32,
                                     bool(body.get("on")))
            return (200 if ok else 400), {"ok": ok}
        if path == "/mock/nominate":
            try:
                steam32 = int(body.get("steam32", 0))
            except (TypeError, ValueError):
                steam32 = 0
            ok, msg = state.human_nominate(steam32, body.get("opening"))
            return (200 if ok else 400), {"ok": ok, "msg": msg}
        if path == "/mock/bid":
            ok, msg = state.human_bid(body.get("amount"))
            return (200 if ok else 400), {"ok": ok, "msg": msg}
        return None

    return post_handler


def _reset_state(state):
    """Clear rosters/budgets/drafted back to setup, keeping targets and seat."""
    with state._lock:
        for t in state.teams.values():
            t.budget = t.start_budget
            t.roster = []
        state.drafted = set()
        state.paused.clear()
        state._paused_remaining = 0.0
        state.speed = 1.0        # cuts are kept, like targets — the dial isn't
        state.order_idx = -1
        state.phase = "setup"
        state.nominator = None
        state.nominee = None
        state.high_bid = 0
        state.high_bidder = None
        state.window = 0
        state.bid_count = 0
        state.last_sold = None
    state.add_event("status", text="Draft reset.")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def run_mock(html_path, season, me=None, port=8322, offline=False,
             open_browser=True, roster_source="curated"):
    print("\n🎲 Loading mock-draft pool from cache...")
    label, pool, captains_raw, by_steam = _load_pool(
        season, offline, roster_source=roster_source
    )
    if not pool:
        print("  ✗ No cached player pool. Run the scout once first "
              "(python ld2l_scout.py), then start --mock.")
        return
    if not captains_raw:
        print("  ✗ No captains found. In the dashboard, mark your captains (the C "
              "button) and click '⬇ Captains → mock', drop captains.json next to "
              "ld2l_scout.py, then retry --mock. (No signup captain:yes flags or "
              "cached teams to fall back on either.)")
        return

    state = MockState(
        season,
        label,
        pool,
        captains_raw,
        by_steam,
        me or config.MOCK_DEFAULT_ME,
        roster_source=roster_source,
    )
    atexit.register(lambda: _save_targets(state.targets_path, state.teams))

    # allow_reuse_address defaults to True, which on Windows lets a SECOND --mock
    # silently bind the same port while an older one is still alive — then requests
    # get routed to either, and a stale pre-restart process serves the old page.
    # Refuse to reuse so a second launch fails loudly instead of stacking.
    try:
        handler = make_handler(html_path, state.live_snapshot, state.hub,
                               post_handler=_mock_post(state))
        server = _MockServer(("127.0.0.1", port), handler)
    except OSError as e:
        print(f"\n  ✗ Port {port} is already in use — another --mock or --live "
              f"window is still running ({e}).\n    Close that console window "
              f"first (or change --port), then relaunch.\n")
        return

    stop = threading.Event()
    engine = threading.Thread(target=_auction_loop, args=(state, stop), daemon=True)
    engine.start()

    url = f"http://localhost:{port}/"
    print("\n" + "=" * 60)
    print("  🎲 MOCK DRAFT (in your dashboard — nothing is sent to ld2l.org)")
    print(f"  Pool: {len(pool)} draftable players ({label})")
    print(f"  Captains: {len(state.teams)}  |  You: {state.me}")
    print(f"  Dashboard: {url}")
    print("  Pick your seat in the Mock bar, then press Start.")
    print("  Ctrl+C to stop")
    print("=" * 60 + "\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Mock draft stopped.")
    finally:
        stop.set()
        _save_targets(state.targets_path, state.teams)
        server.server_close()
