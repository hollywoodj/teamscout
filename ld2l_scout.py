#!/usr/bin/env python3
"""
LD2L Season 21 - Dota 2 Scouting Tool
Pulls player data from OpenDota API and generates a scouting spreadsheet.

Requirements: pip install requests openpyxl

Usage: python ld2l_scout.py
Output: LD2L_S21_Scouting.xlsx
"""

import requests
import time
import json
from datetime import datetime, timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ============================================================
# CONFIGURATION
# ============================================================
API_BASE = "https://api.opendota.com/api"
API_DELAY = 1.2  # seconds between calls (free tier = 60/min)
OUTPUT_FILE = "LD2L_S21_Scouting.xlsx"

# Hero ID -> Name mapping (top ~130 heroes)
HERO_MAP = {
    1:"Anti-Mage",2:"Axe",3:"Bane",4:"Bloodseeker",5:"Crystal Maiden",
    6:"Drow Ranger",7:"Earthshaker",8:"Juggernaut",9:"Mirana",10:"Morphling",
    11:"Shadow Fiend",12:"Phantom Lancer",13:"Puck",14:"Pudge",15:"Razor",
    16:"Sand King",17:"Storm Spirit",18:"Sven",19:"Tiny",20:"Vengeful Spirit",
    21:"Windranger",22:"Zeus",23:"Kunkka",25:"Lina",26:"Lion",27:"Shadow Shaman",
    28:"Slardar",29:"Tidehunter",30:"Witch Doctor",31:"Lich",32:"Riki",
    33:"Enigma",34:"Tinker",35:"Sniper",36:"Necrophos",37:"Warlock",
    38:"Beastmaster",39:"Queen of Pain",40:"Venomancer",41:"Faceless Void",
    42:"Wraith King",43:"Death Prophet",44:"Phantom Assassin",45:"Pugna",
    46:"Templar Assassin",47:"Viper",48:"Luna",49:"Dragon Knight",50:"Dazzle",
    51:"Clockwerk",52:"Leshrac",53:"Nature's Prophet",54:"Lifestealer",
    55:"Dark Seer",56:"Clinkz",57:"Omniknight",58:"Enchantress",59:"Huskar",
    60:"Night Stalker",61:"Broodmother",62:"Bounty Hunter",63:"Weaver",
    64:"Jakiro",65:"Batrider",66:"Chen",67:"Spectre",68:"Ancient Apparition",
    69:"Doom",70:"Ursa",71:"Spirit Breaker",72:"Gyrocopter",73:"Alchemist",
    74:"Invoker",75:"Silencer",76:"Outworld Destroyer",77:"Lycan",78:"Brewmaster",
    79:"Shadow Demon",80:"Lone Druid",81:"Chaos Knight",82:"Meepo",
    83:"Treant Protector",84:"Ogre Magi",85:"Undying",86:"Rubick",87:"Disruptor",
    88:"Nyx Assassin",89:"Naga Siren",90:"Keeper of the Light",91:"Io",
    92:"Visage",93:"Slark",94:"Medusa",95:"Troll Warlord",96:"Centaur Warrunner",
    97:"Magnus",98:"Timbersaw",99:"Bristleback",100:"Tusk",101:"Skywrath Mage",
    102:"Abaddon",103:"Elder Titan",104:"Legion Commander",105:"Techies",
    106:"Ember Spirit",107:"Earth Spirit",108:"Underlord",109:"Terrorblade",
    110:"Phoenix",111:"Oracle",112:"Winter Wyvern",113:"Arc Warden",
    114:"Monkey King",119:"Dark Willow",120:"Pangolier",121:"Grimstroke",
    123:"Hoodwink",126:"Void Spirit",128:"Snapfire",129:"Mars",131:"Ringmaster",
    135:"Dawnbreaker",136:"Marci",137:"Primal Beast",138:"Muerta",
    145:"Kez"
}

# ============================================================
# PLAYER DATA - AUTO-SCRAPED FROM LD2L
# ============================================================
SIGNUP_URL = "https://ld2l.gg/seasons/51/signups"
STEAM64_OFFSET = 76561197960265728  # Steam64 - this = Steam32

def scrape_signups():
    """Scrape the LD2L signup page and return player list."""
    print(f"\n🔍 Scraping signups from {SIGNUP_URL}...")
    try:
        r = requests.get(SIGNUP_URL, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  ✗ Failed to fetch signup page: {e}")
        return []

    from html.parser import HTMLParser

    class LD2LParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.players = []
            self.in_table = False
            self.in_row = False
            self.in_cell = False
            self.current_row = []
            self.current_cell = ""
            self.current_links = []
            self.cell_index = 0
            self.skip_header = True

        def handle_starttag(self, tag, attrs):
            attrs_d = dict(attrs)
            if tag == "table":
                self.in_table = True
            elif tag == "tr" and self.in_table:
                self.in_row = True
                self.current_row = []
                self.current_links = []
                self.cell_index = 0
            elif tag == "td" and self.in_row:
                self.in_cell = True
                self.current_cell = ""
                self.cell_index += 1
            elif tag == "a" and self.in_row:
                href = attrs_d.get("href", "")
                self.current_links.append(href)
                # Extract name from profile link
                if "/profile/" in href:
                    pass  # name comes from text content
                # Text content of link
            elif tag == "img":
                pass

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell += data.strip()

        def handle_endtag(self, tag):
            if tag == "td" and self.in_cell:
                self.in_cell = False
                self.current_row.append(self.current_cell)
            elif tag == "tr" and self.in_row:
                self.in_row = False
                if self.skip_header:
                    self.skip_header = False
                    return
                if len(self.current_row) >= 4:
                    self._process_row()
            elif tag == "table":
                self.in_table = False

        def _process_row(self):
            # Find the dotabuff link to extract steam32 ID
            steam32 = None
            for link in self.current_links:
                if "dotabuff.com/players/" in link:
                    try:
                        steam32 = int(link.split("/players/")[-1].split("/")[0].split("?")[0])
                    except ValueError:
                        pass
                    break
                elif "opendota.com/players/" in link:
                    try:
                        steam32 = int(link.split("/players/")[-1].split("/")[0].split("?")[0])
                    except ValueError:
                        pass
                    break

            if steam32 is None:
                # Try from profile link: /profile/STEAM64
                for link in self.current_links:
                    if "/profile/" in link:
                        try:
                            steam64 = int(link.split("/profile/")[-1].split("/")[0])
                            steam32 = steam64 - STEAM64_OFFSET
                        except ValueError:
                            pass
                        break

            if steam32 is None:
                return

            # Parse row data
            # Row format: [#, (avatar is img, may be empty), MMR, Name, (DB/OD links), Statement]
            # The exact structure varies, so we work with what we have
            try:
                mmr = None
                name = None
                statement = ""

                for cell in self.current_row:
                    # Try to find MMR (a number between 0 and 10000)
                    try:
                        val = int(cell)
                        if 0 < val <= 15000 and mmr is None and val > 50:
                            mmr = val
                            continue
                    except ValueError:
                        pass

                    # Skip pure numbers (row index)
                    try:
                        int(cell)
                        continue
                    except ValueError:
                        pass

                    # Skip empty cells and link text like "DB" "OD"
                    if cell in ["", "DB", "OD", "DBOD"]:
                        continue

                    # First non-numeric non-empty cell is likely the name
                    if name is None and len(cell) > 0 and cell not in ["DB", "OD"]:
                        name = cell
                    elif name is not None and len(cell) > 2:
                        # Remaining text is the statement
                        if cell not in ["DB", "OD", "DBOD"]:
                            statement = cell

                if name and mmr is not None:
                    # Guess role from statement
                    pref_role = parse_role(statement)
                    self.players.append({
                        "name": name,
                        "mmr": mmr,
                        "steam32": steam32,
                        "pref_role": pref_role,
                        "statement": statement,
                    })
            except Exception as e:
                print(f"  ⚠ Error parsing row: {e}")

    parser = LD2LParser()
    parser.feed(r.text)

    # Deduplicate by steam32
    seen = set()
    unique = []
    for p in parser.players:
        if p["steam32"] not in seen:
            seen.add(p["steam32"])
            unique.append(p)

    print(f"  ✅ Found {len(unique)} players")

    # Now scrape each player's profile page for Captain/Draftable status + position prefs
    print(f"\n🔍 Scraping individual profiles for captain status & position prefs...")
    for i, p in enumerate(unique):
        steam64 = p["steam32"] + STEAM64_OFFSET
        profile_url = f"https://ld2l.gg/profile/{steam64}"
        try:
            pr = requests.get(profile_url, timeout=15)
            time.sleep(0.5)  # be nice to their server
            if pr.status_code == 200:
                text = pr.text.lower()

                # Parse Captain status
                if "captain: y" in text:
                    p["captain"] = "Y"
                elif "captain: m" in text:
                    p["captain"] = "M"
                else:
                    p["captain"] = "N"

                # Parse Draftable status
                if "draftable: y" in text:
                    p["draftable"] = "Y"
                elif "draftable: m" in text:
                    p["draftable"] = "M"
                else:
                    p["draftable"] = "N"

                # Parse Vouched status
                p["vouched"] = "Y" if "vouched" in text and "not vouched" not in text else "N"

                # Parse Draft Value
                import re
                dv_match = re.search(r'draft value[:\s]*(\d+)', text)
                p["draft_value"] = int(dv_match.group(1)) if dv_match else p["mmr"]

                # Parse position preferences from profile (more reliable than statement)
                pos_match = re.search(r'position preferences?[:\s]*([^\n<]+)', text)
                if pos_match:
                    pos_str = pos_match.group(1).strip()
                    if pos_str and len(pos_str) > 1:
                        p["profile_positions"] = pos_str
                        # Override role guess with profile data
                        p["pref_role"] = parse_role(pos_str)
                else:
                    p["profile_positions"] = ""

                print(f"  [{i+1}/{len(unique)}] {p['name']}: Captain={p['captain']}, Draftable={p['draftable']}, DV={p['draft_value']}")
            else:
                p["captain"] = "?"
                p["draftable"] = "?"
                p["vouched"] = "?"
                p["draft_value"] = p["mmr"]
                p["profile_positions"] = ""
                print(f"  [{i+1}/{len(unique)}] {p['name']}: HTTP {pr.status_code} (couldn't read profile)")
        except Exception as e:
            p["captain"] = "?"
            p["draftable"] = "?"
            p["vouched"] = "?"
            p["draft_value"] = p["mmr"]
            p["profile_positions"] = ""
            print(f"  [{i+1}/{len(unique)}] {p['name']}: Error ({e})")

    captains_y = sum(1 for p in unique if p.get("captain") == "Y")
    captains_m = sum(1 for p in unique if p.get("captain") == "M")
    print(f"\n  ✅ Captains: {captains_y} confirmed, {captains_m} maybe, {len(unique) - captains_y - captains_m} no/unknown")
    return unique


def parse_role(statement):
    """Guess preferred role from signup statement."""
    s = statement.lower()
    roles = []
    if any(x in s for x in ["pos 1", "carry", "position 1", "safelane"]):
        roles.append("Pos 1")
    if any(x in s for x in ["pos 2", "mid", "position 2"]):
        roles.append("Pos 2")
    if any(x in s for x in ["pos 3", "offlane", "position 3", "off lane"]):
        roles.append("Pos 3")
    if any(x in s for x in ["pos 4", "position 4", "soft support", "roam"]):
        roles.append("Pos 4")
    if any(x in s for x in ["pos 5", "position 5", "hard support"]):
        roles.append("Pos 5")
    if any(x in s for x in ["support"]) and not roles:
        roles.append("Pos 4/5")
    if any(x in s for x in ["all positions", "any role", "any position", "flexible", "all roles"]):
        roles.append("Flex")
    if any(x in s for x in ["shot call", "igl", "captain", "strategist"]):
        if roles:
            roles[-1] += "/IGL"
        else:
            roles.append("Flex/IGL")

    return "/".join(roles) if roles else "Unknown"

# ============================================================
# API HELPERS
# ============================================================
def api_get(path, params=None):
    """Make a rate-limited GET to OpenDota API."""
    url = f"{API_BASE}{path}"
    try:
        r = requests.get(url, params=params, timeout=15)
        time.sleep(API_DELAY)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  ⚠ HTTP {r.status_code} for {path}")
            return None
    except Exception as e:
        print(f"  ✗ Error for {path}: {e}")
        return None

def get_hero_name(hero_id):
    return HERO_MAP.get(hero_id, f"Hero#{hero_id}")

def rank_tier_to_str(tier):
    """Convert rank_tier int to medal string."""
    if tier is None:
        return "Uncalibrated"
    medals = {1:"Herald",2:"Guardian",3:"Crusader",4:"Archon",5:"Legend",6:"Ancient",7:"Divine",8:"Immortal"}
    medal = medals.get(tier // 10, "?")
    stars = tier % 10
    if tier >= 80:
        return "Immortal"
    return f"{medal} {stars}" if stars else medal

def days_since(unix_ts):
    """Days since a unix timestamp."""
    if not unix_ts:
        return None
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - dt).days

# ============================================================
# MAIN DATA COLLECTION
# ============================================================
def fetch_player_data(player):
    """Fetch all scouting data for a single player from OpenDota."""
    sid = player["steam32"]
    print(f"  Fetching {player['name']} ({sid})...")

    data = {
        "profile": None,
        "rank_tier": None,
        "rank_str": "?",
        "wins": 0, "losses": 0, "winrate": 0,
        "total_matches": 0,
        "last_match_days": None,
        "top_heroes": [],
        "recent_heroes": [],
        "avg_kda": 0,
        "avg_gpm": 0,
        "avg_xpm": 0,
        "versatility": 0,
        "estimated_mmr": None,
        "signature_heroes": [],  # 100+ games, 53%+ WR
        # Lobby skill analysis
        "skill_normal": 0, "skill_high": 0, "skill_very_high": 0,
        "skill_pct_vh": 0,  # % of recent games in Very High
        "skill_pct_high_plus": 0,  # % in High + Very High
        "punches_above": False,  # True if playing in lobbies above their MMR bracket
        # Tournament / League data
        "league_matches": 0,
        "league_wins": 0,
        "league_losses": 0,
        "league_winrate": 0,
        "league_heroes": [],  # heroes used in league play
        "has_league_exp": False,
    }

    # 1) Player profile + rank
    profile = api_get(f"/players/{sid}")
    if profile:
        data["profile"] = profile.get("profile", {})
        data["rank_tier"] = profile.get("rank_tier")
        data["rank_str"] = rank_tier_to_str(profile.get("rank_tier"))
        data["estimated_mmr"] = profile.get("competitive_rank") or profile.get("solo_competitive_rank")

    # 2) Win/Loss
    wl = api_get(f"/players/{sid}/wl")
    if wl:
        data["wins"] = wl.get("win", 0)
        data["losses"] = wl.get("lose", 0)
        total = data["wins"] + data["losses"]
        data["total_matches"] = total
        data["winrate"] = round(data["wins"] / total * 100, 1) if total > 0 else 0

    # 3) Recent matches (last 20) - for activity + recent KDA
    recent = api_get(f"/players/{sid}/recentMatches")
    if recent and isinstance(recent, list):
        if len(recent) > 0:
            last_ts = recent[0].get("start_time")
            data["last_match_days"] = days_since(last_ts)

            # Calc recent KDA and GPM
            kills = sum(m.get("kills", 0) for m in recent)
            deaths = sum(m.get("deaths", 0) for m in recent)
            assists = sum(m.get("assists", 0) for m in recent)
            gpms = [m.get("gold_per_min", 0) for m in recent if m.get("gold_per_min")]
            xpms = [m.get("xp_per_min", 0) for m in recent if m.get("xp_per_min")]

            data["avg_kda"] = round((kills + assists) / max(deaths, 1), 2)
            data["avg_gpm"] = round(sum(gpms) / len(gpms)) if gpms else 0
            data["avg_xpm"] = round(sum(xpms) / len(xpms)) if xpms else 0

            # Recent hero IDs
            recent_hero_ids = [m.get("hero_id") for m in recent[:10] if m.get("hero_id")]
            data["recent_heroes"] = [get_hero_name(h) for h in recent_hero_ids]

    # 4) Top heroes by games played
    heroes = api_get(f"/players/{sid}/heroes")
    if heroes and isinstance(heroes, list):
        # Sort by games (already sorted by API usually)
        top = heroes[:10]
        hero_list = []
        unique_heroes_played = sum(1 for h in heroes if int(h.get("games", 0)) > 0)
        data["versatility"] = unique_heroes_played

        for h in top[:5]:
            hid = int(h.get("hero_id", 0))
            games = int(h.get("games", 0))
            wins = int(h.get("win", 0))
            wr = round(wins / games * 100) if games > 0 else 0
            hero_list.append(f"{get_hero_name(hid)} ({games}g {wr}%)")
        data["top_heroes"] = hero_list

        # Signature heroes: 100+ games AND 53%+ win rate
        for h in heroes:
            hid = int(h.get("hero_id", 0))
            games = int(h.get("games", 0))
            wins = int(h.get("win", 0))
            if games >= 100:
                wr = round(wins / games * 100, 1)
                if wr >= 53:
                    data["signature_heroes"].append({
                        "hero": get_hero_name(hid),
                        "games": games,
                        "wins": wins,
                        "winrate": wr,
                    })

    # 5) Lobby skill distribution (last 200 matches)
    #    skill: 1=Normal (<3.2k), 2=High (3.2k-3.8k), 3=Very High (3.8k+)
    matches = api_get(f"/players/{sid}/matches", params={"limit": 200, "date": 180})
    if matches and isinstance(matches, list):
        for m in matches:
            sk = m.get("skill")
            if sk == 1: data["skill_normal"] += 1
            elif sk == 2: data["skill_high"] += 1
            elif sk == 3: data["skill_very_high"] += 1

        total_skilled = data["skill_normal"] + data["skill_high"] + data["skill_very_high"]
        if total_skilled > 0:
            data["skill_pct_vh"] = round(data["skill_very_high"] / total_skilled * 100, 1)
            data["skill_pct_high_plus"] = round(
                (data["skill_high"] + data["skill_very_high"]) / total_skilled * 100, 1
            )

        # Determine if they punch above their MMR bracket
        expected_bracket = 1  # Normal
        if player["mmr"] >= 3800: expected_bracket = 3
        elif player["mmr"] >= 3200: expected_bracket = 2

        if expected_bracket == 1 and data["skill_pct_high_plus"] > 30:
            data["punches_above"] = True
        elif expected_bracket == 2 and data["skill_pct_vh"] > 30:
            data["punches_above"] = True

    # 6) Tournament / League matches (lobby_type=1 = league, lobby_type=2 = tournament)
    for ltype in [1, 2]:
        league_m = api_get(f"/players/{sid}/matches", params={"lobby_type": ltype, "limit": 100})
        if league_m and isinstance(league_m, list):
            for m in league_m:
                data["league_matches"] += 1
                player_slot = m.get("player_slot", 0)
                radiant_win = m.get("radiant_win", False)
                is_radiant = player_slot < 128
                won = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)
                if won:
                    data["league_wins"] += 1
                else:
                    data["league_losses"] += 1

                hid = m.get("hero_id")
                if hid:
                    hname = get_hero_name(hid)
                    if hname not in data["league_heroes"]:
                        data["league_heroes"].append(hname)

    if data["league_matches"] > 0:
        data["has_league_exp"] = True
        data["league_winrate"] = round(data["league_wins"] / data["league_matches"] * 100, 1)

    return data

# ============================================================
# SPREADSHEET GENERATION
# ============================================================
def generate_spreadsheet(players_with_data):
    wb = Workbook()

    # Styles
    hdr_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    hdr_fill = PatternFill("solid", fgColor="1F1F1F")
    hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    data_font = Font(name="Arial", size=9)
    link_font = Font(name="Arial", size=9, color="0563C1", underline="single")
    center = Alignment(horizontal="center", vertical="top")
    wrap = Alignment(vertical="top", wrap_text=True)
    border = Border(
        left=Side(style='thin', color='D0D0D0'),
        right=Side(style='thin', color='D0D0D0'),
        top=Side(style='thin', color='D0D0D0'),
        bottom=Side(style='thin', color='D0D0D0'),
    )

    tier_colors = {
        "S": "FFD700", "A": "C0C0C0", "B": "CD7F32", "C": "87CEEB",
        "D": "98FB98", "E": "DDA0DD", "F": "D3D3D3", "🔥": "FF6347",
    }

    def value_tier(mmr, wr, activity_days, total_matches):
        """Smart value tier based on MMR + performance signals."""
        bonus = ""
        if wr and wr > 53 and total_matches > 200:
            bonus = " ↑WR"
        if activity_days is not None and activity_days > 90:
            bonus += " ⚠INACTIVE"
        if mmr >= 4300: return "S - Elite" + bonus
        if mmr >= 4000: return "A - Premium" + bonus
        if mmr >= 3500: return "B - Solid" + bonus
        if mmr >= 3000: return "C - Average" + bonus
        if mmr >= 2500: return "D - Budget" + bonus
        if mmr >= 2000: return "E - Bargain" + bonus
        return "F - Minimum" + bonus

    # ==================== SHEET 1: MAIN ROSTER ====================
    ws = wb.active
    ws.title = "Scouting Board"

    headers = [
        "#", "Player", "Captain", "Draftable", "Draft Value", "Vouched",
        "Listed MMR", "OD Rank", "Win%", "W", "L",
        "Total Games", "Last Played (days)", "Recent KDA", "Avg GPM", "Avg XPM",
        "Heroes Played", "Pref Role", "Top 5 Heroes",
        "Recent Heroes (last 10)", "Signature Heroes (100g/53%+)",
        "% Very High", "% High+VH", "Punches Up?",
        "League Games", "League W%", "League Heroes",
        "Value Tier", "Your Rating",
        "Draft Target Rd", "Notes", "Dotabuff", "OpenDota", "Statement"
    ]

    # Captain color definitions
    captain_fill_y = PatternFill("solid", fgColor="92D050")   # Green = confirmed captain
    captain_fill_m = PatternFill("solid", fgColor="FFD966")   # Yellow = maybe captain
    captain_font_y = Font(name="Arial", size=9, bold=True, color="006100")
    captain_font_m = Font(name="Arial", size=9, bold=True, color="806000")

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align
        cell.border = border
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(players_with_data)+1}"

    # Sort by MMR descending for the main view
    sorted_players = sorted(players_with_data, key=lambda x: x["player"]["mmr"], reverse=True)

    for i, pd in enumerate(sorted_players, 2):
        p = pd["player"]
        d = pd["data"]
        sid = p["steam32"]
        tier = value_tier(p["mmr"], d["winrate"], d["last_match_days"], d["total_matches"])
        db_url = f"https://www.dotabuff.com/players/{sid}"
        od_url = f"https://www.opendota.com/players/{sid}"

        # Build signature heroes summary string
        sig_str = "\n".join(
            f"{sh['hero']} ({sh['games']}g {sh['winrate']}%)"
            for sh in sorted(d["signature_heroes"], key=lambda x: -x["winrate"])
        ) if d["signature_heroes"] else "—"

        league_heroes_str = ", ".join(d["league_heroes"][:8]) if d["league_heroes"] else "—"
        punches = "✅ YES" if d["punches_above"] else ""

        captain = p.get("captain", "?")
        draftable = p.get("draftable", "?")
        draft_value = p.get("draft_value", p["mmr"])
        vouched = p.get("vouched", "?")

        row_data = [
            i-1, p["name"], captain, draftable, draft_value, vouched,
            p["mmr"], d["rank_str"],
            d["winrate"], d["wins"], d["losses"],
            d["total_matches"], d["last_match_days"],
            d["avg_kda"], d["avg_gpm"], d["avg_xpm"],
            d["versatility"], p["pref_role"],
            "\n".join(d["top_heroes"]),
            ", ".join(d["recent_heroes"][:6]),
            sig_str,
            d["skill_pct_vh"], d["skill_pct_high_plus"], punches,
            d["league_matches"], d["league_winrate"] if d["league_matches"] > 0 else "—",
            league_heroes_str,
            tier, "", "", "",
            db_url, od_url, p["statement"]
        ]

        # +4 cols offset from captain/draftable/dv/vouched insertion
        wrap_cols = [19, 20, 21, 27, 31, 34]
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.font = data_font
            cell.border = border
            cell.alignment = wrap if col in wrap_cols else center

        # Captain row coloring — entire row gets tinted
        if captain == "Y":
            for col in range(1, len(headers)+1):
                c = ws.cell(row=i, column=col)
                if not c.fill or c.fill.fgColor.rgb in ["00000000", "FFFFFF"]:
                    c.fill = PatternFill("solid", fgColor="E2EFDA")  # light green tint
            ws.cell(row=i, column=3).fill = captain_fill_y
            ws.cell(row=i, column=3).font = captain_font_y
        elif captain == "M":
            for col in range(1, len(headers)+1):
                c = ws.cell(row=i, column=col)
                if not c.fill or c.fill.fgColor.rgb in ["00000000", "FFFFFF"]:
                    c.fill = PatternFill("solid", fgColor="FFF2CC")  # light yellow tint
            ws.cell(row=i, column=3).fill = captain_fill_m
            ws.cell(row=i, column=3).font = captain_font_m

        # Hyperlinks (cols 32 and 33)
        ws.cell(row=i, column=32).font = link_font
        ws.cell(row=i, column=32).hyperlink = db_url
        ws.cell(row=i, column=33).font = link_font
        ws.cell(row=i, column=33).hyperlink = od_url

        # Win rate coloring (col 9)
        wr_cell = ws.cell(row=i, column=9)
        if d["winrate"] >= 53:
            wr_cell.font = Font(name="Arial", size=9, bold=True, color="006400")
        elif d["winrate"] < 48 and d["total_matches"] > 100:
            wr_cell.font = Font(name="Arial", size=9, color="CC0000")

        # Very High % coloring (col 22)
        vh_cell = ws.cell(row=i, column=22)
        if d["skill_pct_vh"] >= 50:
            vh_cell.font = Font(name="Arial", size=9, bold=True, color="006400")
            vh_cell.fill = PatternFill("solid", fgColor="C6EFCE")
        elif d["skill_pct_vh"] >= 25:
            vh_cell.font = Font(name="Arial", size=9, color="006400")

        # Punches above (col 24)
        if d["punches_above"]:
            ws.cell(row=i, column=24).fill = PatternFill("solid", fgColor="C6EFCE")
            ws.cell(row=i, column=24).font = Font(name="Arial", size=9, bold=True, color="006400")

        # League experience (col 25)
        if d["league_matches"] > 0:
            ws.cell(row=i, column=25).fill = PatternFill("solid", fgColor="D9E2F3")
            ws.cell(row=i, column=25).font = Font(name="Arial", size=9, bold=True)

        # Tier coloring (col 28)
        tier_cell = ws.cell(row=i, column=28)
        tier_key = tier[0] if tier[0] in tier_colors else None
        if tier_key:
            tier_cell.fill = PatternFill("solid", fgColor=tier_colors[tier_key])

        # Inactive warning - highlight row
        if d["last_match_days"] is not None and d["last_match_days"] > 90:
            for col in range(1, len(headers)+1):
                ws.cell(row=i, column=col).fill = PatternFill("solid", fgColor="FFF3CD")

    # Column widths
    widths = {
        'A':4,'B':26,'C':9,'D':10,'E':10,'F':9,
        'G':10,'H':14,'I':7,'J':6,'K':6,'L':10,'M':14,
        'N':10,'O':9,'P':9,'Q':10,'R':14,'S':38,'T':40,'U':38,
        'V':10,'W':10,'X':12,'Y':12,'Z':10,'AA':35,
        'AB':20,'AC':10,'AD':12,'AE':30,'AF':38,'AG':38,'AH':50
    }
    for c, w in widths.items():
        ws.column_dimensions[c].width = w

    # ==================== SHEET 2: BY ROLE ====================
    ws2 = wb.create_sheet("By Role")
    ws2.sheet_properties.tabColor = "4472C4"

    role_keywords = {
        "Pos 1 (Carry)": ["Pos 1"],
        "Pos 2 (Mid)": ["Pos 2"],
        "Pos 3 (Offlane)": ["Pos 3"],
        "Pos 4/5 (Support)": ["Pos 4", "Pos 5"],
        "Flex / Unknown": ["Flex", "Unknown", "IGL", "Coachable"],
    }

    row = 1
    for role_name, keywords in role_keywords.items():
        role_players = [pd for pd in sorted_players
                       if any(kw in pd["player"]["pref_role"] for kw in keywords)]

        cell = ws2.cell(row=row, column=1, value=f"{role_name} ({len(role_players)} players)")
        cell.font = Font(bold=True, size=12, name="Arial", color="FFFFFF")
        for c in range(1, 10):
            ws2.cell(row=row, column=c).fill = PatternFill("solid", fgColor="2D2D2D")
        ws2.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        row += 1

        sub_headers = ["Name", "MMR", "Captain", "Rank", "Win%", "KDA", "GPM", "Last Played", "Top Heroes"]
        for c, h in enumerate(sub_headers, 1):
            cell = ws2.cell(row=row, column=c, value=h)
            cell.font = Font(bold=True, name="Arial", size=9)
            cell.fill = PatternFill("solid", fgColor="D9E2F3")
        row += 1

        for pd in sorted(role_players, key=lambda x: x["player"]["mmr"], reverse=True):
            p, d = pd["player"], pd["data"]
            ws2.cell(row=row, column=1, value=p["name"]).font = data_font
            ws2.cell(row=row, column=2, value=p["mmr"]).font = data_font
            cap = p.get("captain", "?")
            cap_cell = ws2.cell(row=row, column=3, value=cap)
            cap_cell.font = data_font
            if cap == "Y":
                cap_cell.fill = PatternFill("solid", fgColor="92D050")
                cap_cell.font = Font(name="Arial", size=9, bold=True, color="006100")
            elif cap == "M":
                cap_cell.fill = PatternFill("solid", fgColor="FFD966")
                cap_cell.font = Font(name="Arial", size=9, bold=True, color="806000")
            ws2.cell(row=row, column=4, value=d["rank_str"]).font = data_font
            ws2.cell(row=row, column=5, value=d["winrate"]).font = data_font
            ws2.cell(row=row, column=6, value=d["avg_kda"]).font = data_font
            ws2.cell(row=row, column=7, value=d["avg_gpm"]).font = data_font
            lp = f"{d['last_match_days']}d ago" if d["last_match_days"] is not None else "?"
            ws2.cell(row=row, column=8, value=lp).font = data_font
            ws2.cell(row=row, column=9, value=", ".join(d["top_heroes"][:3])).font = data_font
            row += 1
        row += 1

    for c, w in {'A':26,'B':8,'C':9,'D':14,'E':7,'F':7,'G':7,'H':12,'I':55}.items():
        ws2.column_dimensions[c].width = w

    # ==================== SHEET 3: VALUE PICKS ====================
    ws3 = wb.create_sheet("🔥 Value Picks")
    ws3.sheet_properties.tabColor = "FF6347"

    ws3.cell(row=1, column=1, value="🔥 POTENTIAL VALUE PICKS - Players Who May Outperform Their MMR").font = Font(bold=True, size=13, name="Arial")
    ws3.merge_cells("A1:H1")

    val_headers = ["Player", "MMR", "Rank", "Win%", "Total Games", "KDA", "Why They're Interesting", "Risk"]
    for c, h in enumerate(val_headers, 1):
        cell = ws3.cell(row=3, column=c, value=h)
        cell.font = hdr_font
        cell.fill = PatternFill("solid", fgColor="CC3300")
        cell.alignment = hdr_align

    # Auto-detect value picks
    value_picks = []
    for pd in sorted_players:
        p, d = pd["player"], pd["data"]
        reasons = []
        risks = []

        # High winrate at low MMR
        if d["winrate"] > 52 and d["total_matches"] > 200 and p["mmr"] < 3000:
            reasons.append(f"Win% {d['winrate']}% w/ {d['total_matches']} games at only {p['mmr']} MMR")
        # Massive game count
        if d["total_matches"] > 3000:
            reasons.append(f"{d['total_matches']} total games - extremely experienced")
        # Strong KDA
        if d["avg_kda"] > 4.0:
            reasons.append(f"Recent KDA {d['avg_kda']} - performing well")
        # High GPM for MMR bracket
        if d["avg_gpm"] > 500 and p["mmr"] < 3500:
            reasons.append(f"GPM {d['avg_gpm']} is high for {p['mmr']} bracket")
        # Rank higher than listed MMR suggests
        if d["rank_tier"] and d["rank_tier"] > 50 and p["mmr"] < 3000:
            reasons.append(f"Rank {d['rank_str']} suggests higher than {p['mmr']} MMR")
        # Wide hero pool
        if d["versatility"] > 60:
            reasons.append(f"{d['versatility']} heroes played - very versatile")
        # Signature heroes
        if len(d["signature_heroes"]) >= 3:
            names = [sh["hero"] for sh in d["signature_heroes"][:3]]
            reasons.append(f"{len(d['signature_heroes'])} signature heroes inc. {', '.join(names)}")
        # Punches above their MMR in lobbies
        if d["punches_above"]:
            reasons.append(f"Playing in higher skill lobbies ({d['skill_pct_high_plus']}% High+VH) despite {p['mmr']} MMR")
        # Very High lobby specialist
        if d["skill_pct_vh"] >= 40 and p["mmr"] < 3800:
            reasons.append(f"{d['skill_pct_vh']}% of recent games in Very High skill bracket")
        # League/tournament experience
        if d["has_league_exp"]:
            reasons.append(f"{d['league_matches']} league/tournament games ({d['league_winrate']}% WR)")
        # Low MMR but lots of games
        if p["mmr"] <= 1000 and d["total_matches"] > 500:
            reasons.append(f"Listed at minimum MMR but {d['total_matches']} games played")

        # Risks
        if d["last_match_days"] is not None and d["last_match_days"] > 60:
            risks.append(f"Inactive {d['last_match_days']}d")
        if d["winrate"] < 48 and d["total_matches"] > 200:
            risks.append(f"Sub-48% WR over {d['total_matches']} games")
        if d["total_matches"] < 100:
            risks.append("Very few games on record")

        if reasons:
            value_picks.append({
                "player": p, "data": d,
                "reasons": reasons, "risks": risks
            })

    row = 4
    for vp in sorted(value_picks, key=lambda x: x["player"]["mmr"]):
        p, d = vp["player"], vp["data"]
        ws3.cell(row=row, column=1, value=p["name"]).font = Font(name="Arial", size=10, bold=True)
        ws3.cell(row=row, column=2, value=p["mmr"]).font = data_font
        ws3.cell(row=row, column=3, value=d["rank_str"]).font = data_font
        ws3.cell(row=row, column=4, value=d["winrate"]).font = data_font
        ws3.cell(row=row, column=5, value=d["total_matches"]).font = data_font
        ws3.cell(row=row, column=6, value=d["avg_kda"]).font = data_font
        ws3.cell(row=row, column=7, value=" | ".join(vp["reasons"])).font = data_font
        ws3.cell(row=row, column=7).alignment = wrap
        ws3.cell(row=row, column=8, value=" | ".join(vp["risks"]) if vp["risks"] else "Low risk").font = data_font
        ws3.cell(row=row, column=8).alignment = wrap

        ws3.row_dimensions[row].height = 40
        for c in range(1, 9):
            ws3.cell(row=row, column=c).border = border
            ws3.cell(row=row, column=c).fill = PatternFill("solid", fgColor="FFF0E0")
        row += 1

    for c, w in {'A':26,'B':8,'C':14,'D':7,'E':10,'F':7,'G':65,'H':35}.items():
        ws3.column_dimensions[c].width = w

    # ==================== SHEET 4: SIGNATURE HEROES ====================
    ws_sig = wb.create_sheet("🎯 Signature Heroes")
    ws_sig.sheet_properties.tabColor = "7030A0"

    ws_sig.cell(row=1, column=1, value="🎯 SIGNATURE HEROES — 100+ Games & 53%+ Win Rate").font = Font(bold=True, size=13, name="Arial")
    ws_sig.merge_cells("A1:G1")
    ws_sig.cell(row=2, column=1, value="These are heroes players can reliably perform on. Target these in draft or ban them against opponents.").font = Font(italic=True, name="Arial", size=9, color="666666")
    ws_sig.merge_cells("A2:G2")

    sig_headers = ["Player", "MMR", "Hero", "Games", "Wins", "Win Rate", "Pref Role"]
    for c, h in enumerate(sig_headers, 1):
        cell = ws_sig.cell(row=4, column=c, value=h)
        cell.font = hdr_font
        cell.fill = PatternFill("solid", fgColor="4A1A7A")
        cell.alignment = hdr_align
        cell.border = border

    sig_row = 5
    total_sigs = 0

    # Collect all signature heroes across all players, sort by winrate desc
    all_sigs = []
    for pd in sorted_players:
        p, d = pd["player"], pd["data"]
        for sh in d["signature_heroes"]:
            all_sigs.append({"player": p, "hero_data": sh})

    # Sort by win rate descending so the nastiest picks float to top
    all_sigs.sort(key=lambda x: (-x["hero_data"]["winrate"], -x["hero_data"]["games"]))

    for sig in all_sigs:
        p = sig["player"]
        sh = sig["hero_data"]
        total_sigs += 1

        ws_sig.cell(row=sig_row, column=1, value=p["name"]).font = Font(name="Arial", size=10, bold=True)
        ws_sig.cell(row=sig_row, column=2, value=p["mmr"]).font = data_font
        ws_sig.cell(row=sig_row, column=2).alignment = center
        ws_sig.cell(row=sig_row, column=3, value=sh["hero"]).font = Font(name="Arial", size=10, bold=True, color="4A1A7A")
        ws_sig.cell(row=sig_row, column=4, value=sh["games"]).font = data_font
        ws_sig.cell(row=sig_row, column=4).alignment = center
        ws_sig.cell(row=sig_row, column=5, value=sh["wins"]).font = data_font
        ws_sig.cell(row=sig_row, column=5).alignment = center

        wr_val = sh["winrate"]
        wr_cell = ws_sig.cell(row=sig_row, column=6, value=f"{wr_val}%")
        wr_cell.alignment = center
        if wr_val >= 60:
            wr_cell.font = Font(name="Arial", size=10, bold=True, color="006400")
            wr_cell.fill = PatternFill("solid", fgColor="C6EFCE")
        elif wr_val >= 55:
            wr_cell.font = Font(name="Arial", size=10, bold=True, color="006400")
        else:
            wr_cell.font = data_font

        ws_sig.cell(row=sig_row, column=7, value=p["pref_role"]).font = data_font
        ws_sig.cell(row=sig_row, column=7).alignment = center

        for c in range(1, 8):
            ws_sig.cell(row=sig_row, column=c).border = border
        # Alternate row shading
        if sig_row % 2 == 0:
            for c in range(1, 8):
                ws_sig.cell(row=sig_row, column=c).fill = PatternFill("solid", fgColor="F3E8FF")

        sig_row += 1

    # Summary at bottom
    sig_row += 1
    ws_sig.cell(row=sig_row, column=1, value=f"Total signature heroes found: {total_sigs}").font = Font(bold=True, name="Arial", size=10)
    players_with_sigs = len(set(s["player"]["name"] for s in all_sigs))
    ws_sig.cell(row=sig_row+1, column=1, value=f"Players with at least one: {players_with_sigs}/{len(sorted_players)}").font = Font(name="Arial", size=10)

    for c, w in {'A':28,'B':8,'C':22,'D':8,'E':8,'F':10,'G':16}.items():
        ws_sig.column_dimensions[c].width = w

    # ==================== SHEET 5: LOBBY SKILL & LEAGUE EXP ====================
    ws_lobby = wb.create_sheet("🏆 Lobby & League Intel")
    ws_lobby.sheet_properties.tabColor = "0070C0"

    ws_lobby.cell(row=1, column=1, value="🏆 LOBBY SKILL ANALYSIS & LEAGUE/TOURNAMENT EXPERIENCE").font = Font(bold=True, size=13, name="Arial")
    ws_lobby.merge_cells("A1:L1")
    ws_lobby.cell(row=2, column=1, value="Skill brackets: Normal (<3.2k avg), High (3.2-3.8k avg), Very High (3.8k+ avg). Players in higher brackets than their MMR suggests are undervalued.").font = Font(italic=True, name="Arial", size=9, color="666666")
    ws_lobby.merge_cells("A2:L2")

    lobby_headers = ["Player", "MMR", "Rank", "% Normal", "% High", "% Very High",
                     "% High+VH", "Punches Up?", "League Games", "League W%",
                     "League Heroes", "Verdict"]
    for c, h in enumerate(lobby_headers, 1):
        cell = ws_lobby.cell(row=4, column=c, value=h)
        cell.font = hdr_font
        cell.fill = PatternFill("solid", fgColor="003366")
        cell.alignment = hdr_align
        cell.border = border

    lobby_row = 5
    for pd in sorted(sorted_players, key=lambda x: -x["data"]["skill_pct_vh"]):
        p, d = pd["player"], pd["data"]
        total_skilled = d["skill_normal"] + d["skill_high"] + d["skill_very_high"]
        if total_skilled == 0:
            continue

        pct_normal = round(d["skill_normal"] / total_skilled * 100, 1)
        pct_high = round(d["skill_high"] / total_skilled * 100, 1)

        # Build verdict
        verdict = ""
        if d["punches_above"]:
            verdict = "🔥 UNDERVALUED - plays above MMR bracket"
        elif d["skill_pct_vh"] >= 60:
            verdict = "Consistently in Very High lobbies"
        elif d["has_league_exp"] and d["league_winrate"] >= 50:
            verdict = f"League veteran ({d['league_matches']}g, {d['league_winrate']}%)"
        elif d["has_league_exp"]:
            verdict = f"Has league exp ({d['league_matches']} games)"
        elif d["skill_pct_high_plus"] >= 50 and p["mmr"] < 3500:
            verdict = "Plays in higher brackets frequently"

        ws_lobby.cell(row=lobby_row, column=1, value=p["name"]).font = Font(name="Arial", size=10, bold=True)
        ws_lobby.cell(row=lobby_row, column=2, value=p["mmr"]).font = data_font
        ws_lobby.cell(row=lobby_row, column=2).alignment = center
        ws_lobby.cell(row=lobby_row, column=3, value=d["rank_str"]).font = data_font
        ws_lobby.cell(row=lobby_row, column=3).alignment = center
        ws_lobby.cell(row=lobby_row, column=4, value=pct_normal).font = data_font
        ws_lobby.cell(row=lobby_row, column=4).alignment = center
        ws_lobby.cell(row=lobby_row, column=5, value=pct_high).font = data_font
        ws_lobby.cell(row=lobby_row, column=5).alignment = center

        vh_cell = ws_lobby.cell(row=lobby_row, column=6, value=d["skill_pct_vh"])
        vh_cell.alignment = center
        if d["skill_pct_vh"] >= 50:
            vh_cell.font = Font(name="Arial", size=10, bold=True, color="006400")
            vh_cell.fill = PatternFill("solid", fgColor="C6EFCE")
        else:
            vh_cell.font = data_font

        hp_cell = ws_lobby.cell(row=lobby_row, column=7, value=d["skill_pct_high_plus"])
        hp_cell.alignment = center
        hp_cell.font = data_font

        punch_cell = ws_lobby.cell(row=lobby_row, column=8)
        if d["punches_above"]:
            punch_cell.value = "✅ YES"
            punch_cell.font = Font(name="Arial", size=10, bold=True, color="006400")
            punch_cell.fill = PatternFill("solid", fgColor="C6EFCE")
        else:
            punch_cell.value = ""
            punch_cell.font = data_font
        punch_cell.alignment = center

        lg_cell = ws_lobby.cell(row=lobby_row, column=9, value=d["league_matches"] if d["league_matches"] > 0 else "—")
        lg_cell.font = data_font
        lg_cell.alignment = center
        if d["league_matches"] > 0:
            lg_cell.fill = PatternFill("solid", fgColor="D9E2F3")

        ws_lobby.cell(row=lobby_row, column=10, value=d["league_winrate"] if d["league_matches"] > 0 else "—").font = data_font
        ws_lobby.cell(row=lobby_row, column=10).alignment = center
        ws_lobby.cell(row=lobby_row, column=11, value=", ".join(d["league_heroes"][:6]) if d["league_heroes"] else "—").font = data_font
        ws_lobby.cell(row=lobby_row, column=11).alignment = wrap
        ws_lobby.cell(row=lobby_row, column=12, value=verdict).font = data_font
        ws_lobby.cell(row=lobby_row, column=12).alignment = wrap

        for c in range(1, 13):
            ws_lobby.cell(row=lobby_row, column=c).border = border
        if d["punches_above"]:
            for c in range(1, 13):
                if not ws_lobby.cell(row=lobby_row, column=c).fill.fgColor or \
                   ws_lobby.cell(row=lobby_row, column=c).fill.fgColor.rgb == "00000000":
                    ws_lobby.cell(row=lobby_row, column=c).fill = PatternFill("solid", fgColor="E8F5E9")

        lobby_row += 1

    for c, w in {'A':26,'B':8,'C':14,'D':9,'E':9,'F':10,'G':10,'H':12,'I':12,'J':10,'K':35,'L':42}.items():
        ws_lobby.column_dimensions[c].width = w

    # ==================== SHEET 6: QUICK COMPARE ====================
    ws4 = wb.create_sheet("Head-to-Head Compare")
    ws4.sheet_properties.tabColor = "70AD47"
    ws4.cell(row=1, column=1, value="Use this sheet to compare players side-by-side during draft").font = Font(bold=True, size=11, name="Arial")
    ws4.merge_cells("A1:F1")

    comp_headers = ["Stat", "Player A", "Player B", "Player C", "Player D", "Player E"]
    for c, h in enumerate(comp_headers, 1):
        cell = ws4.cell(row=3, column=c, value=h)
        cell.font = hdr_font
        cell.fill = PatternFill("solid", fgColor="2D7D2D")

    stats = ["Name", "Listed MMR", "OD Rank", "Win%", "Total Games", "Recent KDA",
             "Avg GPM", "Avg XPM", "Heroes Played", "Pref Role", "Last Active (days)",
             "% Very High Lobbies", "% High+ Lobbies", "Punches Above?",
             "League Games", "League Win%",
             "Top Hero #1", "Top Hero #2", "Top Hero #3",
             "Signature Heroes", "Statement", "Your Notes"]
    for r, s in enumerate(stats, 4):
        cell = ws4.cell(row=r, column=1, value=s)
        cell.font = Font(name="Arial", size=10, bold=True)
        cell.fill = PatternFill("solid", fgColor="E2EFDA")

    for c, w in {'A':18,'B':25,'C':25,'D':25,'E':25,'F':25}.items():
        ws4.column_dimensions[c].width = w

    # Save
    wb.save(OUTPUT_FILE)
    print(f"\n✅ Spreadsheet saved to {OUTPUT_FILE}")

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    import argparse
    import signal
    import sys

    parser = argparse.ArgumentParser(description="LD2L Season 21 Scouting Tool")
    parser.add_argument("--loop", action="store_true", help="Run every 2 hours in a loop")
    parser.add_argument("--interval", type=int, default=7200, help="Loop interval in seconds (default: 7200 = 2hrs)")
    parser.add_argument("--output", type=str, default=None, help="Output file path (overrides default)")
    args = parser.parse_args()

    if args.output:
        OUTPUT_FILE = args.output

    def run_scout():
        """Run one full scouting cycle."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "=" * 60)
        print(f"  LD2L Season 21 - Scouting Tool")
        print(f"  Run started at: {now}")
        print("=" * 60)

        # Step 1: Scrape signups
        players = scrape_signups()
        if not players:
            print("  ✗ No players found! Check if the signup page is accessible.")
            print("  URL: " + SIGNUP_URL)
            return False

        print(f"\n  Fetching OpenDota data for {len(players)} players...")
        print("  (This will take ~6-8 minutes due to rate limiting)")
        print("  Pulling: profile, W/L, recent matches, heroes,")
        print("  lobby skill brackets, and tournament/league history")

        # Step 2: Fetch all player data
        all_data = []
        for i, player in enumerate(players):
            print(f"\n[{i+1}/{len(players)}] {player['name']} (MMR: {player['mmr']})")
            data = fetch_player_data(player)
            all_data.append({"player": player, "data": data})

        # Step 3: Generate spreadsheet
        print("\n" + "=" * 60)
        print("  Generating spreadsheet...")
        print("=" * 60)

        generate_spreadsheet(all_data)

        # Quick summary
        print("\n📊 QUICK STATS:")
        active = sum(1 for d in all_data if d["data"]["last_match_days"] is not None and d["data"]["last_match_days"] < 30)
        high_wr = sum(1 for d in all_data if d["data"]["winrate"] > 52 and d["data"]["total_matches"] > 200)
        league_exp = sum(1 for d in all_data if d["data"]["has_league_exp"])
        punchers = sum(1 for d in all_data if d["data"]["punches_above"])
        print(f"  Total players scraped: {len(players)}")
        print(f"  Active in last 30 days: {active}/{len(all_data)}")
        print(f"  Players with 52%+ WR (200+ games): {high_wr}")
        print(f"  Players with league experience: {league_exp}")
        print(f"  Players punching above MMR: {punchers}")
        print(f"\n  📁 Saved to: {OUTPUT_FILE}")
        print(f"  ⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return True

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\n👋 Scout shutting down. See you at the draft!")
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)

    if args.loop:
        interval_min = args.interval // 60
        print("=" * 60)
        print(f"  🔄 LOOP MODE: Running every {interval_min} minutes")
        print(f"  Press Ctrl+C to stop")
        print("=" * 60)

        while True:
            success = run_scout()
            next_run = datetime.now().strftime("%H:%M:%S")
            if success:
                print(f"\n  ⏳ Next update in {interval_min} minutes...")
                print(f"     (sleeping until ~{next_run} + {interval_min}min)")
            else:
                print(f"\n  ⚠ Run failed. Retrying in {interval_min} minutes...")

            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n\n👋 Scout shutting down. See you at the draft!")
                break
    else:
        # Single run
        run_scout()
        print(f"\n  💡 TIP: Run with --loop to auto-update every 2 hours:")
        print(f"     python {sys.argv[0]} --loop")
        print(f"     python {sys.argv[0]} --loop --interval 3600  (every hour)")

