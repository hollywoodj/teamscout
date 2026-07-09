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

from . import config

HISTORY_BLOB = "auction_history"
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
            has_team = a.get("data-team", "0") not in ("", "0")
            cost = int(cost_raw) if cost_raw.isdigit() and int(cost_raw) > 0 else None
            self.rows.append({
                "steam32": steam32,
                "mmr": mmr,
                "cost": cost,
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


def annotate_players(players_with_data, history, current_base=500):
    """Attach last_cost / est_cost to each player's data dict."""
    pool = []  # (mmr, cost) normalized to the current auction base
    for season in history:
        scale = current_base / season["base"] if season["base"] else 1.0
        for r in season["players"]:
            if r["cost"]:
                pool.append((r["mmr"], r["cost"] * scale))
    pool.sort()

    def estimate(mmr):
        if len(pool) < KNN:
            return None
        nearest = sorted(pool, key=lambda t: abs(t[0] - mmr))[:KNN]
        est = statistics.median(c for _, c in nearest)
        return int(round(est / 5) * 5)  # auction resolution is 5

    for pd in players_with_data:
        p, d = pd["player"], pd["data"]
        d["est_cost"] = estimate(p["mmr"])
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
    return players_with_data
