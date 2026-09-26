"""Scrape LD2L signups and the weekly schedule from ld2l.org.

The signup table carries structured data attributes on each <tr>:
  data-steamid (steam64), data-linear (listed MMR), data-captain (0=no/1=yes/2=maybe),
  data-draftable, data-vouched, data-standin, data-core-mmr, data-support-mmr,
  data-unified-mmr, data-mmr-valid, data-mmr-screenshot, data-pos1..data-pos5.
Position prefs are 1-5 ratings where 1 = most preferred (ties allowed).
Player name lives in the hovercard div's data-title; statement is the last <td>.
"""

import json
import os
import re
import time
from html import unescape
from html.parser import HTMLParser

import requests

from . import config

YMN = {"1": "Y", "2": "M", "0": "N"}


class SignupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.players = []
        self._row = None       # player dict being built
        self._td_texts = None  # text content of each td in the row
        self._in_td = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "data-steamid" in a:
            self._row = a
            self._td_texts = []
        elif self._row is not None:
            if tag == "td":
                self._in_td = True
                self._td_texts.append("")
            elif tag == "div" and a.get("data-hovercard-type") == "profile":
                # first hovercard in the row is the player
                self._row.setdefault("_name", a.get("data-title", ""))

    def handle_data(self, data):
        if self._row is not None and self._in_td:
            self._td_texts[-1] += data

    def handle_endtag(self, tag):
        if self._row is None:
            return
        if tag == "td":
            self._in_td = False
        elif tag == "tr":
            self._finish_row()

    def _finish_row(self):
        a, self._row = self._row, None
        try:
            steam64 = int(a["data-steamid"])
        except (KeyError, ValueError):
            return
        steam32 = steam64 - config.STEAM64_OFFSET

        def num(key, default=0):
            try:
                return int(a.get(key, default))
            except ValueError:
                return default

        # Statement is the last td; strip link-only cells like "DB OD"
        statement = ""
        if self._td_texts:
            statement = re.sub(r"\s+", " ", self._td_texts[-1]).strip()

        pos_prefs = [num(f"data-pos{i}", 3) for i in range(1, 6)]
        preferred = [str(i + 1) for i, v in enumerate(pos_prefs) if v <= 2]
        if len(preferred) == 5 or len(set(pos_prefs)) == 1:
            pref_role = "Any"  # everything rated the same = no stated preference
        elif preferred:
            pref_role = "/".join(preferred)
        else:
            # nothing rated 1-2: fall back to their best-rated positions
            best = min(pos_prefs)
            pref_role = "/".join(str(i + 1) for i, v in enumerate(pos_prefs) if v == best)

        self.players.append({
            "name": (a.get("_name") or f"Player {steam32}").strip(),
            "steam64": steam64,
            "steam32": steam32,
            "mmr": num("data-linear"),
            "unified_mmr": num("data-unified-mmr"),
            "core_mmr": num("data-core-mmr"),
            "support_mmr": num("data-support-mmr"),
            "captain": YMN.get(a.get("data-captain", "0"), "?"),
            "draftable": YMN.get(a.get("data-draftable", "0"), "?"),
            "vouched": "Y" if a.get("data-vouched") == "1" else "N",
            "standin": a.get("data-standin") == "1",
            "mmr_valid": a.get("data-mmr-valid") == "1",
            "mmr_screenshot": a.get("data-mmr-screenshot", ""),
            "pos_prefs": pos_prefs,
            "pref_role": pref_role,
            "statement": statement,
        })


def scrape_budgets(season_id):
    """Scrape team budgets from the season teams page (/teams/{id}).

    The table shows Captain (hovercard) plus "$Total Money" and "$Unspent"
    columns. Returns [{captain, steam64, team, budget, unspent}], or [] until
    teams are posted for the season.
    """
    url = f"{config.LD2L_BASE}/teams/{season_id}"
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "ld2l-scout/2.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"  ⚠ Couldn't fetch teams page: {e}")
        return []

    teams = []
    for row in re.findall(r"<tr>(.*?)</tr>", r.text, re.S):
        cap = re.search(r'data-title="([^"]*)"', row)
        sid = re.search(r'data-hovercard-id="(\d+)"', row)
        name = re.search(r'href="/teams/about/(\d+)">([^<]*)', row)
        money = re.findall(r"\$(\d+)", row)
        if not (cap and money):
            continue
        teams.append({
            "captain": unescape(cap.group(1)).strip(),
            "steam64": int(sid.group(1)) if sid else None,
            # team_id is the site's internal id — it's what the draft page's
            # data-team attribute carries, so the live follower can map a pick
            # to the winning captain
            "team_id": name.group(1) if name else None,
            "team": unescape(name.group(2)).strip() if name else "",
            "budget": int(money[0]),
            "unspent": int(money[1]) if len(money) > 1 else None,
        })
    return teams


def scrape_signups(season_id):
    """Fetch and parse the signup page. Returns (season_label, players)."""
    url = f"{config.LD2L_BASE}/seasons/{season_id}/signups"
    print(f"\n🔍 Scraping signups from {url}...")
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "ld2l-scout/2.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"  ✗ Failed to fetch signup page: {e}")
        return f"Season {season_id}", []

    m = re.search(r"<h2>\s*Season\s+(\d+)", r.text)
    season_label = f"S{m.group(1)}" if m else f"Season {season_id}"

    parser = SignupParser()
    parser.feed(r.text)

    # Deduplicate by steam32, keep first occurrence
    seen, unique = set(), []
    for p in parser.players:
        if p["steam32"] not in seen:
            seen.add(p["steam32"])
            unique.append(p)

    caps_y = sum(1 for p in unique if p["captain"] == "Y")
    caps_m = sum(1 for p in unique if p["captain"] == "M")
    print(f"  ✅ Found {len(unique)} players ({season_label}) — "
          f"captains: {caps_y} yes / {caps_m} maybe")
    return season_label, unique


_WEEK_HEADING = re.compile(r"<h3>\s*Week\s+(\d+)\s*</h3>", re.I)
_SERIES_ROW = re.compile(r'<tr class="clickable"[^>]*>(.*?)</tr>', re.S)
_SCHEDULE_TEAM = re.compile(r'href="/teams/about/(\d+)">([^<]*)</a>')
_SERIES_SCORE = re.compile(r"<td[^>]*>\s*(\d+\s*-\s*\d+)\s*</td>")


def parse_schedule(html):
    """Every posted week on /schedule/{season}: [{week, series: [...]}].

    Each series is {homeId, home, awayId, away, score}. The site lists the
    newest week first; callers pick by week number, not position.
    """
    html = html or ""
    headings = list(_WEEK_HEADING.finditer(html))
    weeks = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        series = []
        for row in _SERIES_ROW.findall(html[heading.end():end]):
            teams = _SCHEDULE_TEAM.findall(row)
            if len(teams) != 2:
                continue
            score = _SERIES_SCORE.search(row)
            series.append({
                "homeId": teams[0][0],
                "home": unescape(teams[0][1]).strip(),
                "awayId": teams[1][0],
                "away": unescape(teams[1][1]).strip(),
                "score": re.sub(r"\s+", " ", score.group(1)) if score else "",
            })
        if series:
            weeks.append({"week": int(heading.group(1)), "series": series})
    return weeks


def current_week(weeks):
    """The newest posted week: this week's opponent, played or not."""
    return max(weeks, key=lambda row: row["week"]) if weeks else None


def _schedule_cache_path(path=None):
    if path:
        return path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, config.LD2L_SCHEDULE_CACHE_FILE)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path, data):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def fetch_schedule(season_id):
    url = f"{config.LD2L_BASE}/schedule/{season_id}"
    r = requests.get(url, timeout=25, headers={"User-Agent": "ld2l-scout/2.0"})
    r.raise_for_status()
    week = current_week(parse_schedule(r.text))
    return {
        "seasonId": season_id,
        "week": week["week"] if week else None,
        "series": week["series"] if week else [],
        "fetchedAt": int(time.time()),
    }


def load_schedule(season_id, path=None, force=False):
    """This week's LD2L series, cached for LD2L_SCHEDULE_CACHE_HOURS.

    A failed fetch keeps the previous cache; no cache and no network returns
    None so callers fall back to BBC's posted matchups.
    """
    path = _schedule_cache_path(path)
    cached = _read_json(path)
    if cached and cached.get("seasonId") != season_id:
        cached = None
    if cached and not force:
        try:
            age = time.time() - float(cached.get("fetchedAt") or 0)
        except (TypeError, ValueError):
            age = float("inf")
        if age < config.LD2L_SCHEDULE_CACHE_HOURS * 3600:
            return cached
    try:
        data = fetch_schedule(season_id)
    except (requests.RequestException, OSError, ValueError) as exc:
        print(f"  ⚠ LD2L schedule fetch failed: {exc}", flush=True)
        return cached
    if not data["series"] and cached and cached.get("series"):
        return cached  # an empty page is a site hiccup, not a cleared week
    try:
        _write_json(path, data)
    except OSError as exc:
        print(f"  ⚠ LD2L schedule cache write failed: {exc}", flush=True)
    return data


def refresh_schedule_if_new_week(season_id, path=None):
    """Refetch the schedule; True when this week's series changed."""
    before = _read_json(_schedule_cache_path(path)) or {}
    after = load_schedule(season_id, path=path, force=True) or {}
    key = lambda data: (data.get("week"), [(row.get("homeId"), row.get("awayId"))
                                          for row in data.get("series") or []])
    return bool(after.get("series")) and key(before) != key(after)
