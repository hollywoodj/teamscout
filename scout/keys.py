"""Keys to victory: only statistically sharp win/loss splits.

Used as the reference implementation for the matchup-page logic in
team_scout_html.py. Keep the constants and the 2x2 rules in sync with the JS.
"""

import statistics

from .stats import fisher_exact

# High bar on purpose: an empty list is the correct answer when the sample
# cannot support a claim. These are associations, not causal proofs.
MIN_GROUP = 5
MIN_GAP = 0.30
MAX_BAD_WR = 0.40
MIN_GOOD_WR = 0.55
MIN_GPM_MEDIAN_GAP = 60
LANE_WIN_EFF = 55
LANE_LOSS_EFF = 45
ALPHA = 0.05
MAX_GPM_KEYS = 2

LANE_ACTION = {
    1: "Win the safelane",
    2: "Win mid",
    3: "Win the offlane",
    4: "Win the offlane",
    5: "Win the safelane",
}


def lane_outcome(match):
    """Exact parsed result if present; otherwise a 10-point dead band on lane efficiency."""
    result = match.get("laneResult")
    if result in ("win", "loss", "draw"):
        return result
    eff = match.get("laneEff")
    if not isinstance(eff, (int, float)) or isinstance(eff, bool):
        return None
    if eff >= LANE_WIN_EFF:
        return "win"
    if eff <= LANE_LOSS_EFF:
        return "loss"
    return "draw"


def primary_position(rows):
    counts = {}
    for match in rows:
        pos = match.get("position")
        if pos in LANE_ACTION:
            counts[pos] = counts.get(pos, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda pos: (counts[pos], -pos))


def _wl(rows):
    wins = sum(1 for match in rows if match.get("win"))
    return wins, len(rows)


def _record(wins, n):
    return f"{wins}–{n - wins}"


def _pct(wins, n):
    return f"{int(round(wins / n * 100))}%"


def _fmt_p(p):
    if p < 0.001:
        return "p < 0.001"
    return f"p = {p:.3f}"


def _round_to_50(value):
    return int((value / 50 + 0.5) // 1 * 50)


def _qualifies(good_rows, bad_rows):
    good_w, good_n = _wl(good_rows)
    bad_w, bad_n = _wl(bad_rows)
    if good_n < MIN_GROUP or bad_n < MIN_GROUP:
        return False
    good_wr = good_w / good_n
    bad_wr = bad_w / bad_n
    if good_wr - bad_wr < MIN_GAP:
        return False
    if bad_wr > MAX_BAD_WR or good_wr < MIN_GOOD_WR:
        return False
    return True


def _split_p(good_rows, bad_rows):
    good_w, good_n = _wl(good_rows)
    bad_w, bad_n = _wl(bad_rows)
    return fisher_exact(good_w, good_n - good_w, bad_w, bad_n - bad_w)


def _key(action, reason, p, good_rows, bad_rows, kind, player_id, source):
    good_w, good_n = _wl(good_rows)
    bad_w, bad_n = _wl(bad_rows)
    return {
        "action": action,
        "reason": reason,
        "p": p,
        "gap": good_w / good_n - bad_w / bad_n,
        "kind": kind,
        "player_id": player_id,
        "source": source,
        "dedupe": f"{player_id}:{kind}",
    }


def lane_key(player, rows, source):
    won, lost = [], []
    for match in rows:
        outcome = lane_outcome(match)
        if outcome == "win":
            won.append(match)
        elif outcome == "loss":
            lost.append(match)
    if not _qualifies(won, lost):
        return None
    p = _split_p(won, lost)
    if p is None or p >= ALPHA:
        return None
    name = player["name"]
    action = LANE_ACTION.get(primary_position(rows), f"Win {name}'s lane")
    won_w, won_n = _wl(won)
    lost_w, lost_n = _wl(lost)
    reason = (
        f"In {source}, {name} is {_record(lost_w, lost_n)} ({_pct(lost_w, lost_n)}) "
        f"when losing the lane, versus {_record(won_w, won_n)} "
        f"({_pct(won_w, won_n)}) when winning it ({_fmt_p(p)})."
    )
    return _key(action, reason, p, won, lost, "lane", player["id"], source)


def gpm_key(player, rows, side, source):
    if primary_position(rows) in (4, 5):
        return None
    with_gpm = [
        match for match in rows
        if isinstance(match.get("gpm"), (int, float)) and not isinstance(match.get("gpm"), bool)
    ]
    win_gpm = [match["gpm"] for match in with_gpm if match.get("win")]
    loss_gpm = [match["gpm"] for match in with_gpm if not match.get("win")]
    if len(win_gpm) < MIN_GROUP or len(loss_gpm) < MIN_GROUP:
        return None
    win_med = statistics.median(win_gpm)
    loss_med = statistics.median(loss_gpm)
    if win_med - loss_med < MIN_GPM_MEDIAN_GAP:
        return None
    cut = _round_to_50((win_med + loss_med) / 2)
    if cut < 500 or cut > 800:
        return None
    high = [match for match in with_gpm if match["gpm"] >= cut]
    low = [match for match in with_gpm if match["gpm"] < cut]
    if not _qualifies(high, low):
        return None
    p = _split_p(high, low)
    if p is None or p >= ALPHA:
        return None
    name = player["name"]
    high_w, high_n = _wl(high)
    low_w, low_n = _wl(low)
    if side == "enemy":
        action = f"Keep {name} under {cut} GPM"
    else:
        action = f"Get {name} over {cut} GPM"
    reason = (
        f"In {source}, {name} is {_record(low_w, low_n)} ({_pct(low_w, low_n)}) "
        f"below {cut} GPM, versus {_record(high_w, high_n)} ({_pct(high_w, high_n)}) "
        f"at {cut}+ ({_fmt_p(p)})."
    )
    return _key(action, reason, p, high, low, "gpm", player["id"], source)


def player_keys(player, rows, side, source):
    found = []
    lane = lane_key(player, rows, source)
    if lane:
        found.append(lane)
    gpm = gpm_key(player, rows, side, source)
    if gpm:
        found.append(gpm)
    return found


def merge_keys(keys):
    """Collapse identical actions (e.g. both offlaners) and keep the sharpest GPM cuts."""
    gpm = [key for key in keys if key["kind"] == "gpm"]
    other = [key for key in keys if key["kind"] != "gpm"]
    gpm.sort(key=lambda key: (key["p"], -key["gap"]))
    kept = other + gpm[:MAX_GPM_KEYS]
    grouped = {}
    for key in kept:
        current = grouped.get(key["action"])
        if current is None:
            grouped[key["action"]] = {
                "action": key["action"],
                "reasons": [key["reason"]],
                "p": key["p"],
                "gap": key["gap"],
            }
            continue
        current["reasons"].append(key["reason"])
        current["p"] = min(current["p"], key["p"])
        current["gap"] = max(current["gap"], key["gap"])
    return sorted(grouped.values(), key=lambda row: (row["p"], -row["gap"]))


def keys_to_victory(mine, enemy):
    """mine/enemy: iterable of {id, name, official_rows}. Public rows are ignored."""
    found = []
    for side, players in (("mine", mine), ("enemy", enemy)):
        for player in players:
            found.extend(player_keys(
                player, player.get("official_rows") or [], side, "LD2L officials",
            ))
    return merge_keys(found)
