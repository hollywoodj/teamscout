"""League-relative team metrics from cached official match payloads."""

from collections import defaultdict
from math import isfinite


METRICS = (
    ("win_rate", "Win rate"),
    ("kills", "Kills"), ("deaths", "Deaths"),
    ("teamfight", "Teamfight"), ("first_blood", "First blood"),
    ("observers", "Observers"), ("sentries", "Sentries"),
    ("dewards", "Dewards"), ("obs_lost", "Obs lost"),
    ("gpm", "GPM"), ("xpm", "XPM"),
    ("lane_eff", "Lane efficiency"), ("stacks", "Stacks"),
    ("towers", "Towers"), ("roshan", "Roshan"),
    ("buybacks", "Buybacks"),
)

_SUM_FIELDS = {
    "kills": "kills", "deaths": "deaths", "observers": "obs_placed",
    "sentries": "sen_placed", "dewards": ("obs_kills", "sen_kills"),
    "gpm": "gpm", "xpm": "xpm", "stacks": "camps_stacked",
    "towers": "towers_killed", "roshan": "roshans_killed",
    "buybacks": "buybacks",
}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _side_sum(players, fields):
    """Skip incomplete team totals so missing players do not look like zero."""
    if isinstance(fields, str):
        fields = (fields,)
    if len(players) != 5 or any(not isinstance(p, dict) or
                                not all(_number(p.get(f)) for f in fields)
                                for p in players):
        return None
    return sum(p[f] for p in players for f in fields)


def _average(values):
    return sum(values) / len(values) if values else None


def _team_values(games):
    values = defaultdict(list)
    for match, side in games:
        players = (match.get(side) or {}).get("players") or []
        opponent = "dire" if side == "radiant" else "radiant"
        if isinstance(match.get("radiant_win"), bool):
            values["win_rate"].append(int(match["radiant_win"] == (side == "radiant")) * 100)
        for metric, field in _SUM_FIELDS.items():
            amount = _side_sum(players, field)
            if amount is not None:
                values[metric].append(amount)
        if len(players) == 5 and all(isinstance(p, dict) for p in players):
            rates = [p.get("teamfight") for p in players]
            if all(_number(v) for v in rates):
                values["teamfight"].append(_average([v * 100 if v <= 1 else v for v in rates]))
            lane = [p.get("lane_eff") for p in players]
            if all(_number(v) for v in lane):
                values["lane_eff"].append(_average(lane))
            if all("firstblood" in p for p in players):
                values["first_blood"].append(int(any(p["firstblood"] for p in players)) * 100)
        placed = _side_sum(players, "obs_placed")
        enemy_kills = _side_sum((match.get(opponent) or {}).get("players") or [], "obs_kills")
        if placed is not None and placed > 0 and enemy_kills is not None:
            values["obs_lost"].append(enemy_kills / placed * 100)
    return {metric: _average(values[metric]) for metric, _ in METRICS}


def team_rankings(payload):
    """Return {team key: {games, metrics}} with competition ranks per league.

    A rank's denominator counts teams with observed values for that metric.
    Rank 1 always means the highest value, including deaths and buybacks.
    """
    teams = [team for team in payload.get("teams") or [] if team.get("key")]
    by_key = {team["key"]: team for team in teams}
    games = defaultdict(list)
    for match in payload.get("teamMatches") or []:
        if not isinstance(match, dict):
            continue
        for side in ("radiant", "dire"):
            key = (match.get(side) or {}).get("team_key")
            if key in by_key:
                games[key].append((match, side))
    result = {key: {"games": len(games[key]), "metrics": _team_values(games[key])}
              for key in by_key}
    for metric, _ in METRICS:
        leagues = defaultdict(list)
        for key, team in by_key.items():
            league = team.get("league") or (payload.get("officialSource") or {}).get("league") or ""
            value = result[key]["metrics"][metric]
            if value is not None:
                leagues[league].append((key, value))
        for rows in leagues.values():
            ordered = sorted(rows, key=lambda pair: -pair[1])
            for key, value in rows:
                rank = 1 + sum(other > value for _, other in ordered)
                result[key]["metrics"][metric] = {
                    "rank": rank, "total": len(rows), "value": value,
                }
        for key, team in by_key.items():
            if result[key]["metrics"][metric] is None:
                league = team.get("league") or (payload.get("officialSource") or {}).get("league") or ""
                result[key]["metrics"][metric] = {
                    "rank": None, "total": len(leagues[league]), "value": None,
                }
    return result
