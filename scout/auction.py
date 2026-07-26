"""Past auction-draft harvesting and cost estimation.

LD2L draft pages (/seasons/{id}/draft) carry one <tr name="draft-signup"> per
player with data-steamid, data-linear (MMR at draft time), data-team,
data-cost and data-drafted. Captains join teams without a cost (empty
data-cost but a team assigned).
"""

import re
import statistics
from html.parser import HTMLParser

import requests

from . import config, pricing
from .analysis import measured_roles

HISTORY_BLOB = "auction_history_v2"  # v2: rows carry team ids
HISTORY_TTL_HOURS = 24 * 7
MAX_SEASONS = 4   # how many past auction seasons feed the model
KNN = 7           # nearest-by-MMR neighbours used for the estimate


def _get(url):
    r = requests.get(url, timeout=25, headers={"User-Agent": "ld2l-scout/2.0"})
    r.raise_for_status()
    return r.text


class DraftParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and a.get("name") == "draft-signup" and "data-steamid" in a:
            try:
                steam32 = int(a["data-steamid"]) - config.STEAM64_OFFSET
                mmr = int(a.get("data-linear") or 0)
            except ValueError:
                return
            cost_raw = a.get("data-cost", "")
            team = a.get("data-team", "0")
            has_team = team not in ("", "0")
            cost = int(cost_raw) if cost_raw.isdigit() and int(cost_raw) > 0 else None
            self.rows.append({
                "steam32": steam32,
                "mmr": mmr,
                "cost": cost,
                "team": team if has_team else None,
                "captain": cost is None and has_team,
                "drafted": a.get("data-drafted") == "1",
            })


def _season_info(season_id):
    """Label, type and auction base from a season hub page."""
    hub = _get(f"{config.LD2L_BASE}/seasons/{season_id}")
    text = re.sub(r"<[^>]+>", " ", hub)
    label_m = re.search(r"<h2>\s*([^<]+?)\s*Hub", hub)
    base_m = re.search(r"Auction Base:\s*(\d+)", text)
    return {
        "label": label_m.group(1).strip() if label_m else f"Season {season_id}",
        "is_auction": "Auction Draft" in text,
        "base": int(base_m.group(1)) if base_m else None,
    }


def _harvest(current_season_id):
    """Walk season ids downward collecting recent completed auction drafts."""
    seasons = []
    for sid in range(current_season_id - 1, max(current_season_id - 12, 0), -1):
        if len(seasons) >= MAX_SEASONS:
            break
        try:
            info = _season_info(sid)
            if not info["is_auction"]:
                continue
            parser = DraftParser()
            parser.feed(_get(f"{config.LD2L_BASE}/seasons/{sid}/draft"))
            priced = [r for r in parser.rows if r["cost"]]
            if not priced:
                continue
            seasons.append({
                "id": sid,
                "label": info["label"],
                "base": info["base"] or 500,
                "players": parser.rows,
            })
            print(f"  ✅ {info['label']} (season {sid}): {len(priced)} auction prices")
        except Exception as e:
            print(f"  ⚠ season {sid}: {e}")
    return seasons


def load_history(cache, current_season_id):
    """Cached past-auction data: [{id, label, base, players}] newest first."""
    cached = cache.get_blob(HISTORY_BLOB, max_age_hours=HISTORY_TTL_HOURS)
    if cached is not None and cached.get("for_season") == current_season_id:
        return cached["seasons"]
    print("\n💰 Harvesting past auction drafts...")
    seasons = _harvest(current_season_id)
    cache.set_blob(HISTORY_BLOB, {"for_season": current_season_id, "seasons": seasons})
    return seasons


def measure_predictions(estimator, players_with_data, history):
    """Leave-one-out backtest of the base price model. Returns {metrics, errors}.

    Three things this has to get right to mean anything:
      * the player's own past sales are dropped from the kNN pool, or the model
        is partly graded on data it memorized and the MAE comes out flattering;
      * predict from the MMR they carried INTO that draft, not today's listed
        MMR — a player who has since climbed 800 isn't a model error;
      * no rank premium. The premium is a function of where they sit in the
        CURRENT signup pool, which says nothing about a season-old sale, so
        including it would score noise. This measures the kNN core only.
    """
    if not history or not estimator:
        return None
    # Only compare against completed drafts (where we know actual prices)
    metrics = {"mae": 0, "rmse": 0, "count": 0, "errors": []}
    errors = []
    for pd in players_with_data:
        p, d = pd["player"], pd["data"]
        actual = d.get("last_cost")
        draft_mmr = d.get("last_draft_mmr")
        if actual is None or not draft_mmr:
            continue
        predicted = estimator(draft_mmr, measured_roles(d), with_premium=False,
                              exclude_steam32=p["steam32"])
        if predicted is None:
            continue
        err = abs(actual - predicted)
        errors.append({"steam32": p["steam32"], "name": p["name"],
                       "predicted": predicted, "actual": actual, "error": err})
        metrics["mae"] += err
        metrics["rmse"] += err * err
        metrics["count"] += 1
    if metrics["count"]:
        metrics["mae"] = int(metrics["mae"] / metrics["count"])
        metrics["rmse"] = int((metrics["rmse"] / metrics["count"]) ** 0.5)
        errors.sort(key=lambda x: -x["error"])
    metrics["errors"] = errors[:20]  # top 20 biggest misses
    return metrics


def build_estimator(history, current_base=500, pool_mmrs=None, pos_pools=None):
    """MMR -> expected winning bid, from past auctions normalized to the
    current base. kNN-median: validated by LOOCV against 4 seasons of drafts
    (MAE ~36, unbiased across MMR bands — fancier models don't beat it).

    When pool_mmrs (the current signup pool, captains excluded) is given, a
    rank premium is added on top: every tracked draft bid its top players up
    well past what MMR-vs-history implies and let the tail go for steals, so
    the estimate is shifted by where the MMR ranks within this pool
    (config.AUCTION_RANK_PREMIUM). pos_pools ({position: [mmrs]}) extends
    that to positional scarcity: the top 3 available at each of the player's
    positions carry config.AUCTION_POS_PREMIUM, combined with the overall
    curve via max(). Returns None-returning stub when there's no usable
    history.
    """
    pool = []  # (steam32, mmr, cost) normalized to the current auction base
    for season in history:
        scale = current_base / season["base"] if season["base"] else 1.0
        for r in season["players"]:
            if r["cost"]:
                pool.append((r["steam32"], r["mmr"], r["cost"] * scale))
    pool.sort(key=lambda t: (t[1], t[2]))  # deterministic neighbour ties
    ranked = sorted((m for m in (pool_mmrs or []) if m), reverse=True)
    pos_ranked = {pos: sorted((m for m in mmrs if m), reverse=True)
                  for pos, mmrs in (pos_pools or {}).items()}

    def estimate(mmr, roles=(), with_premium=True, exclude_steam32=None):
        # exclude_steam32 drops that player's own past sales from the
        # neighbours — needed for honest backtesting (see measure_predictions),
        # a no-op for anyone who hasn't been through a tracked auction.
        if mmr is None:
            return None
        usable = pool if exclude_steam32 is None else \
            [t for t in pool if t[0] != exclude_steam32]
        if len(usable) < KNN:
            return None
        nearest = sorted(usable, key=lambda t: abs(t[1] - mmr))[:KNN]
        est = statistics.median(c for _, _, c in nearest)
        if with_premium and ranked:
            # premium algorithm lives in pricing.py; JS reprice mirrors it
            est += pricing.combined_premium(mmr, roles, ranked, pos_ranked) \
                * (current_base / 500)
        return pricing.round5(est)  # auction resolution is 5

    return estimate


def annotate_players(players_with_data, history, current_base=500):
    """Attach last_cost / est_cost / est_base to each player's data dict.

    Returns the pool-aware price estimator so callers can reuse it (e.g. for
    worth_cost in pool_analysis) with the same premiums applied.
    """
    # Purchasable pool = everyone but confirmed captains ("Y"; "M" maybes
    # still enter the auction more often than not). Positional pools come
    # from measured lanes, so supports (4/5) only exist where the dashboard's
    # hand-set roles say so — the dashboard reprices live from those.
    pool_pds = [pd for pd in players_with_data
                if pd["player"].get("captain") != "Y"]
    pool_mmrs = [pd["player"].get("mmr") for pd in pool_pds]
    pos_pools = {}
    for pd in pool_pds:
        mmr = pd["player"].get("mmr")
        if mmr:
            for pos in measured_roles(pd["data"]):
                pos_pools.setdefault(pos, []).append(mmr)
    estimate = build_estimator(history, current_base,
                               pool_mmrs=pool_mmrs, pos_pools=pos_pools)

    for pd in players_with_data:
        p, d = pd["player"], pd["data"]
        d["est_base"] = estimate(p["mmr"], with_premium=False)
        d["est_cost"] = estimate(p["mmr"], measured_roles(d))
        d["last_cost"] = None
        d["last_cost_season"] = None
        d["last_draft_mmr"] = None
        d["was_captain_last"] = False
        for season in history:  # newest first
            row = next((r for r in season["players"] if r["steam32"] == p["steam32"]), None)
            if row is None:
                continue
            d["last_cost_season"] = season["label"]
            d["last_draft_mmr"] = row["mmr"]
            if row["captain"]:
                d["was_captain_last"] = True
            else:
                d["last_cost"] = row["cost"]
            break
    return estimate
