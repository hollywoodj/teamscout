"""Scrape LD2L signups from ld2l.org.

The signup table carries structured data attributes on each <tr>:
  data-steamid (steam64), data-linear (listed MMR), data-captain (0=no/1=yes/2=maybe),
  data-draftable, data-vouched, data-standin, data-core-mmr, data-support-mmr,
  data-unified-mmr, data-mmr-valid, data-mmr-screenshot, data-pos1..data-pos5.
Position prefs are 1-5 ratings where 1 = most preferred (ties allowed).
Player name lives in the hovercard div's data-title; statement is the last <td>.
"""

import re
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
