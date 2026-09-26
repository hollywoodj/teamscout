"""Read-only scrape of one RD2L division season from rd2l.gg.

The site is server-rendered HTML. Team profile ids are Steam32. Results are
cached so Team Scout's offline rebuild does not have to refetch every time.
"""

import json
import os
import re
import time

import requests

from . import config
from .bbc_source import team_key

_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_TEAM_LINK = re.compile(
    r'href="[^"]+/teams/([^"]+)"[^>]*>([^<]+)</a>\s*<span>\s*\(([^)]*)\)</span>',
)
_RECORD = re.compile(r"Record:\s*(\d+)\s*-\s*(\d+)")
_DIVISION = re.compile(r"Division:\s*<a[^>]*>([^<]+)</a>")
_SEASON_NUM = re.compile(r"Season\s+(\d+)", re.I)
_CAPTAIN = re.compile(
    r"Captain</span></h5>.*?<a href=\"/profile/(\d+)\"><strong>([^<]+)</strong>",
    re.S,
)
_PLAYER = re.compile(
    r'<td><a href="/profile/(\d+)">([^<]+)</a></td>'
    r'.*?<img class="image rank[^"]*" src="[^"]*" alt="(\d+)"',
    re.S,
)
_MATCH_ID = re.compile(r"dotabuff\.com/matches/(\d+)")
_MATCHUP_WEEK = re.compile(r"Week\s+(\d+)\s+Matchups", re.I)


def _cache_path(path=None):
    if path:
        return path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, config.RD2L_CACHE_FILE)


def _read_cache(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(path, data):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _fresh(data):
    fetched = data.get("fetchedAt") if isinstance(data, dict) else 0
    try:
        age = time.time() - float(fetched)
    except (TypeError, ValueError):
        return False
    return age < config.RD2L_CACHE_HOURS * 3600


def _get(session, path):
    response = session.get(config.RD2L_BASE + path, timeout=30)
    response.raise_for_status()
    return response.text


def _rows(html):
    return _ROW.findall(html or "")


def parse_team_list(html):
    """One team link per row. Standings rows start with a place number, so
    they are skipped here and read by parse_standings."""
    rows = []
    seen = set()
    for row in _rows(html):
        if re.match(r"\s*<td>\d+</td>", row):
            continue
        links = _TEAM_LINK.findall(row)
        if len(links) != 1:
            continue
        team_id, name, captain = links[0]
        name = _clean(name)
        if not name or team_id in seen:
            continue
        seen.add(team_id)
        rows.append({
            "id": team_id,
            "name": name,
            "captain": _clean(captain),
        })
    return rows


def parse_standings(html):
    rows = []
    for row in _rows(html):
        place = re.match(r"\s*<td>(\d+)</td>", row)
        links = _TEAM_LINK.findall(row)
        after = row.split("</span></td>", 1)[-1]
        scores = re.findall(r"<td>(\d+)</td>", after)
        if not place or len(links) != 1 or len(scores) < 2:
            continue
        team_id, name, captain = links[0]
        name = _clean(name)
        if not name:
            continue
        rows.append({
            "place": int(place.group(1)),
            "id": team_id,
            "name": name,
            "captain": _clean(captain),
            "wins": int(scores[0]),
            "losses": int(scores[1]),
        })
    return rows


def parse_matchups(html):
    rows = []
    for row in _rows(html):
        links = _TEAM_LINK.findall(row)
        if len(links) != 2:
            continue
        home_id, home, _home_captain = links[0]
        away_id, away, _away_captain = links[1]
        rows.append({
            "homeId": home_id,
            "home": _clean(home),
            "awayId": away_id,
            "away": _clean(away),
        })
    return rows


def parse_matchup_week(html):
    """The week number from the matchups page title ("Season 39 Week 3 Matchups")."""
    found = _MATCHUP_WEEK.search(html or "")
    return int(found.group(1)) if found else None


def parse_roster_page(html):
    """Captain, teammates, record, and Dotabuff match ids from one team page."""
    players_at = html.find(">Players<")
    players_html = html[players_at:] if players_at >= 0 else ""
    series_at = players_html.find(">Series<")
    roster_html = players_html[:series_at] if series_at >= 0 else players_html
    captain = _CAPTAIN.search(html)
    record = _RECORD.search(html)
    division = _DIVISION.search(html)
    players = []
    seen = set()
    if captain:
        sid = int(captain.group(1))
        seen.add(sid)
        players.append({
            "id": sid,
            "name": _clean(captain.group(2)),
            "rankTier": None,
            "captain": True,
        })
    for sid, name, rank in _PLAYER.findall(roster_html):
        sid = int(sid)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            rank_tier = int(rank)
        except ValueError:
            rank_tier = None
        players.append({
            "id": sid,
            "name": _clean(name),
            "rankTier": rank_tier,
            "captain": False,
        })
    wins = int(record.group(1)) if record else 0
    losses = int(record.group(2)) if record else 0
    return {
        "players": players,
        "wins": wins,
        "losses": losses,
        "division": _clean(division.group(1)) if division else "",
        "matchIds": [int(match_id) for match_id in _MATCH_ID.findall(html)],
    }


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _league_label(division, season_number):
    division = division or "RD2L"
    if season_number:
        return f"RD2L {division} Season {season_number}"
    return f"RD2L {division}"


def parse_rd2l(team_html_by_id, standings_html, matchups_html, teams_html, season_number=None):
    """Turn fetched pages into Team Scout teams, standings, and matchups."""
    listed = {row["id"]: row for row in parse_team_list(teams_html)}
    standings = parse_standings(standings_html)
    division = ""
    teams = []
    players = {}
    for row in standings or [{"id": team_id, "name": info["name"], "captain": info["captain"],
                               "wins": 0, "losses": 0, "place": index}
                              for index, (team_id, info) in enumerate(listed.items(), start=1)]:
        page = parse_roster_page(team_html_by_id.get(row["id"]) or "")
        if page["division"]:
            division = page["division"]
        info = listed.get(row["id"]) or {}
        name = row.get("name") or info.get("name") or ""
        if not name:
            continue
        roster_players = page["players"]
        wins, losses = page["wins"], page["losses"]
        if not wins and not losses:
            wins, losses = row.get("wins") or 0, row.get("losses") or 0
        for player in roster_players:
            players.setdefault(player["id"], {
                "id": player["id"],
                "name": player["name"],
                "rankTier": player.get("rankTier"),
            })
        teams.append({
            "id": row["id"],
            "key": team_key(name),
            "name": name,
            "short": name,
            "captain": (roster_players[0]["name"] if roster_players and roster_players[0].get("captain")
                        else row.get("captain") or info.get("captain") or ""),
            "roster": [player["id"] for player in roster_players][:5],
            "wins": wins,
            "losses": losses,
            "record": f"{wins} - {losses}",
            "rank": row.get("place") or 0,
            "matchIds": page["matchIds"],
        })
    league = _league_label(division, season_number)
    for team in teams:
        team["league"] = league
    by_id = {team["id"]: team for team in teams}
    week = parse_matchup_week(matchups_html)
    matchups = []
    for row in parse_matchups(matchups_html):
        home = by_id.get(row["homeId"])
        away = by_id.get(row["awayId"])
        if not home or not away:
            continue
        matchups.append({
            "homeId": row["homeId"],
            "awayId": row["awayId"],
            "a": home["name"],
            "aShort": home["short"],
            "aCaptain": home["captain"],
            "aKey": home["key"],
            "b": away["name"],
            "bShort": away["short"],
            "bCaptain": away["captain"],
            "bKey": away["key"],
            "league": league,
            "week": week,
        })
    standings_out = [{
        "name": team["name"],
        "short": team["short"],
        "key": team["key"],
        "wins": team["wins"],
        "losses": team["losses"],
        "record": team["record"],
        "captain": team["captain"],
        "rank": team["rank"],
        "league": league,
    } for team in teams]
    return {
        "league": league,
        "division": division,
        "season": season_number,
        "teams": teams,
        "players": list(players.values()),
        "standings": standings_out,
        "matchups": matchups,
        "week": week,
    }


def fetch_rd2l(season_id=None, division_id=None):
    season_id = season_id or config.RD2L_SEASON_ID
    division_id = division_id or config.RD2L_DIVISION_ID
    prefix = f"/seasons/{season_id}/divisions/{division_id}"
    session = requests.Session()
    session.headers["User-Agent"] = "LD2L-Scout/rd2l"
    teams_html = _get(session, prefix + "/teams")
    standings_html = _get(session, prefix + "/standings")
    matchups_html = _get(session, prefix + "/matchups")
    season_number = None
    found = _SEASON_NUM.search(teams_html)
    if found:
        season_number = int(found.group(1))
    pages = {}
    for row in parse_team_list(teams_html):
        time.sleep(0.15)
        pages[row["id"]] = _get(session, prefix + "/teams/" + row["id"])
    data = parse_rd2l(pages, standings_html, matchups_html, teams_html, season_number)
    data["fetchedAt"] = int(time.time())
    return data


def match_ids(data):
    """Unique Dotabuff match ids listed on the cached team pages."""
    found = []
    seen = set()
    for team in (data or {}).get("teams") or []:
        for match_id in team.get("matchIds") or []:
            try:
                match_id = int(match_id)
            except (TypeError, ValueError):
                continue
            if match_id in seen:
                continue
            seen.add(match_id)
            found.append(match_id)
    return found


def _matches_path(path=None):
    if path:
        return path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, config.RD2L_MATCHES_FILE)


def _usable_match(payload):
    return isinstance(payload, dict) and isinstance(payload.get("players"), list) and bool(payload.get("players"))


def load_rd2l_matches(rd2l, fetcher=None, path=None, offline=False):
    """OpenDota payloads for this division, stored beside rd2l_cache.json.

    Completed games stay in the file. A later load only downloads match ids
    the team pages list that are not already cached. Offline returns whatever
    is already on disk.
    """
    path = _matches_path(path)
    cached = _read_cache(path) or {}
    stored = cached.get("matches") if isinstance(cached.get("matches"), dict) else {}
    stored = {str(key): value for key, value in stored.items()}
    missing = [match_id for match_id in match_ids(rd2l) if not _usable_match(stored.get(str(match_id)))]
    if missing and not offline and fetcher is not None:
        for index, match_id in enumerate(missing, start=1):
            try:
                payload = fetcher(match_id)
            except (requests.RequestException, OSError, ValueError) as exc:
                print(f"  ⚠ RD2L match {match_id} failed: {exc}", flush=True)
                continue
            if not _usable_match(payload):
                print(f"  ⚠ RD2L match {match_id} had no players", flush=True)
                continue
            stored[str(match_id)] = payload
            print(f"  RD2L match {index}/{len(missing)} cached ({match_id})", flush=True)
            try:
                _write_cache(path, {"fetchedAt": int(time.time()), "matches": stored})
            except OSError as exc:
                print(f"  ⚠ RD2L match cache write failed: {exc}", flush=True)
    usable = {}
    for key, payload in stored.items():
        if not _usable_match(payload):
            continue
        try:
            usable[int(key)] = payload
        except (TypeError, ValueError):
            continue
    return usable


def _pairings(rows):
    return sorted((row.get("homeId"), row.get("awayId")) for row in rows or [])


def refresh_rd2l_if_new_week(path=None, season_id=None, division_id=None):
    """Poll only the matchups page; refetch the division when it changed.

    Returns True when the cache was rewritten with new pairings, so the
    caller knows to rebuild. Network failures return False and keep the cache.
    """
    path = _cache_path(path)
    cached = _read_cache(path)
    season_id = season_id or config.RD2L_SEASON_ID
    division_id = division_id or config.RD2L_DIVISION_ID
    session = requests.Session()
    session.headers["User-Agent"] = "LD2L-Scout/rd2l"
    try:
        html = _get(session, f"/seasons/{season_id}/divisions/{division_id}/matchups")
    except (requests.RequestException, OSError) as exc:
        print(f"  ⚠ RD2L matchups check failed: {exc}", flush=True)
        return False
    posted = parse_matchups(html)
    if not posted:
        return False
    if (cached and _pairings(posted) == _pairings(cached.get("matchups"))
            and parse_matchup_week(html) == cached.get("week")):
        return False
    return load_rd2l(path, force=True) is not None


def load_rd2l(path=None, force=False):
    """Cached division. Refetches when the cache is older than RD2L_CACHE_HOURS.

    A failed refetch keeps the previous cache. No cache and no network returns
    None so Team Scout still serves LD2L.
    """
    path = _cache_path(path)
    cached = _read_cache(path)
    if cached and not force and _fresh(cached):
        return cached
    try:
        data = fetch_rd2l()
    except (requests.RequestException, OSError, ValueError) as exc:
        print(f"  ⚠ RD2L scrape failed: {exc}", flush=True)
        return cached
    try:
        _write_cache(path, data)
    except OSError as exc:
        print(f"  ⚠ RD2L cache write failed: {exc}", flush=True)
    return data
