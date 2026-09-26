"""Scout Bot "Briefing": build Discord Components V2 pages from a Team Scout
payload. Pure functions, no network, no Discord import - the caller (the
bot) owns posting.

Two pages are produced, each a single Container component:
  build_briefing_page() - team profile, draft, players, key reads.
  build_wards_page()    - ward placement summary + a rendered PNG map sheet.

Stat computation (the _*_stats helpers) is kept separate from rendering (the
_*_lines / build_* functions) so either can change independently.
"""

from datetime import datetime, timezone

from .bbc_source import team_key as _team_key
from .ward_render import (
    ward_patch_id as _ward_patch_id,
    player_side_wards as _player_side_wards,
    render_ward_sheet as _render_ward_sheet,
    select_map_players as _select_map_players,
)

ACCENT_COLOR = 0xE74C3C

POSITION_KEYCAPS = {
    1: "1️⃣", 2: "2️⃣", 3: "3️⃣",
    4: "4️⃣", 5: "5️⃣",
}
UNKNOWN_KEYCAP = "\N{WHITE QUESTION MARK ORNAMENT}"

# Discord Components V2 component types.
TYPE_ACTION_ROW = 1
TYPE_BUTTON = 2
TYPE_SECTION = 9
TYPE_TEXT_DISPLAY = 10
TYPE_THUMBNAIL = 11
TYPE_MEDIA_GALLERY = 12
TYPE_SEPARATOR = 14
TYPE_CONTAINER = 17

LIMIT_COMPONENTS = 40
LIMIT_TEXT_TOTAL = 4000

KEY_READS_HEADER = "### \U0001F6A8 __Key reads__"

SHORT_HERO_NAMES = {
    "Outworld Destroyer": "OD", "Outworld Devourer": "OD",
    "Vengeful Spirit": "VS", "Earth Spirit": "ES", "Enchantress": "Ench",
    "Ancient Apparition": "AA", "Nature's Prophet": "NP",
    "Shadow Shaman": "Shaman", "Spirit Breaker": "SB",
    "Faceless Void": "Void", "Templar Assassin": "TA",
    "Phantom Assassin": "PA", "Phantom Lancer": "PL", "Wraith King": "WK",
    "Keeper of the Light": "KotL", "Skywrath Mage": "Sky",
    "Storm Spirit": "Storm", "Ember Spirit": "Ember",
    "Queen of Pain": "QoP", "Crystal Maiden": "CM", "Dark Willow": "Willow",
    "Treant Protector": "Treant", "Nyx Assassin": "Nyx",
    "Monkey King": "MK", "Lone Druid": "LD", "Dragon Knight": "DK",
    "Death Prophet": "DP", "Winter Wyvern": "Wyvern",
    "Centaur Warrunner": "Centaur", "Legion Commander": "LC",
    "Elder Titan": "ET", "Chaos Knight": "CK", "Witch Doctor": "WD",
    "Shadow Fiend": "SF", "Night Stalker": "NS", "Sand King": "SK",
    "Bounty Hunter": "BH", "Ogre Magi": "Ogre", "Naga Siren": "Naga",
    "Troll Warlord": "Troll", "Arc Warden": "Arc", "Primal Beast": "PB",
}


# --------------------------------------------------------------------------
# Team / roster resolution (unchanged fuzzy-matching behaviour)
# --------------------------------------------------------------------------

def _find_team(payload, query):
    """Resolve a fuzzy team name/key. Raises ValueError if nothing matches."""
    teams = payload.get("teams") or []
    q_key = _team_key(query)
    if not q_key:
        raise ValueError(f"No team name given (got {query!r})")

    for row in teams:
        if row.get("key") == q_key:
            return row

    for row in teams:
        if _team_key(row.get("short")) == q_key or _team_key(row.get("name")) == q_key:
            return row

    candidates = []
    for row in teams:
        keys = {row.get("key") or "", _team_key(row.get("short") or ""),
                 _team_key(row.get("name") or "")}
        if any(k and (q_key in k or k in q_key) for k in keys):
            candidates.append(row)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        candidates.sort(key=lambda row: abs(len(row.get("key") or "") - len(q_key)))
        return candidates[0]

    raise ValueError(f"No team found matching {query!r}")


def _team_by_key(payload, key):
    for row in payload.get("teams") or []:
        if row.get("key") == key:
            return row
    return None


def _find_matchup_opponent(payload, key):
    for matchup in payload.get("matchups") or []:
        if matchup.get("aKey") == key:
            other_key = matchup.get("bKey")
            row = _team_by_key(payload, other_key)
            if row:
                return row
            return {"key": other_key, "name": matchup.get("b"),
                    "short": matchup.get("bShort"), "record": ""}
        if matchup.get("bKey") == key:
            other_key = matchup.get("aKey")
            row = _team_by_key(payload, other_key)
            if row:
                return row
            return {"key": other_key, "name": matchup.get("a"),
                    "short": matchup.get("aShort"), "record": ""}
    return None


def _standing_for(payload, key):
    for row in payload.get("standings") or []:
        if row.get("key") == key:
            return row
    return {}


# --------------------------------------------------------------------------
# Hero naming / emoji tokens
# --------------------------------------------------------------------------

def _hero_name(heroes_map, hero_id):
    if hero_id is None:
        return "Unknown"
    row = heroes_map.get(hero_id)
    if row is None:
        row = heroes_map.get(str(hero_id))
    if row is None:
        try:
            row = heroes_map.get(int(hero_id))
        except (TypeError, ValueError):
            row = None
    if row and row.get("n"):
        return row["n"]
    return f"Hero {hero_id}"


def _hero_short_name(name):
    return SHORT_HERO_NAMES.get(name, name)


def _hero_emoji(hero_emoji, hero_id):
    if not hero_emoji:
        return None
    return hero_emoji.get(str(hero_id)) or hero_emoji.get(hero_id)


def _hero_token(heroes_map, hero_emoji, hero_id):
    """Emoji-or-short-name token used in the Draft section (no hero name
    shown alongside it, so an emoji-less hero needs a readable short name)."""
    emoji = _hero_emoji(hero_emoji, hero_id)
    if emoji:
        return emoji
    return _hero_short_name(_hero_name(heroes_map, hero_id))


def _hero_prefix(hero_emoji, hero_id):
    """Emoji prefix used before a full hero name in the Players section.
    Empty string when there's no emoji for this hero (the full name is
    already shown, so no short-name fallback is needed here)."""
    emoji = _hero_emoji(hero_emoji, hero_id)
    return f"{emoji} " if emoji else ""


# --------------------------------------------------------------------------
# Stat computation
# --------------------------------------------------------------------------

def _team_sample(payload, key):
    """teamMatches entries this team played in, newest first."""
    out = []
    for entry in payload.get("teamMatches") or []:
        radiant_key = (entry.get("radiant") or {}).get("team_key")
        dire_key = (entry.get("dire") or {}).get("team_key")
        if radiant_key == key:
            out.append((entry, "radiant", "dire"))
        elif dire_key == key:
            out.append((entry, "dire", "radiant"))
    out.sort(key=lambda row: row[0].get("start_time") or 0, reverse=True)
    return out


def _side_win(entry, side):
    radiant_win = bool(entry.get("radiant_win"))
    return radiant_win if side == "radiant" else not radiant_win


def _numeric(values):
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _game_side_sum(entry, side, field):
    players = (entry.get(side) or {}).get("players") or []
    vals = _numeric(p.get(field) for p in players)
    if not vals:
        return None
    return sum(vals)


def _avg_per_game_sum(sample, field):
    totals = []
    for entry, our_side, _opp_side in sample:
        v = _game_side_sum(entry, our_side, field)
        if v is not None:
            totals.append(v)
    if not totals:
        return None
    return sum(totals) / len(totals)


def _avg_player_field(sample, field):
    """Average of a per-player field across all of OUR side's player rows in
    the sample (not summed per game first)."""
    vals = []
    for entry, our_side, _opp_side in sample:
        players = (entry.get(our_side) or {}).get("players") or []
        vals.extend(_numeric(p.get(field) for p in players))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _sum_player_field(sample, side_selector, field):
    total = 0.0
    seen = False
    for entry, our_side, opp_side in sample:
        side = our_side if side_selector == "our" else opp_side
        players = (entry.get(side) or {}).get("players") or []
        for v in _numeric(p.get(field) for p in players):
            total += v
            seen = True
    return total if seen else None


def _fmt1(value):
    return "-" if value is None else f"{value:.1f}"


def _fmtint(value):
    return "-" if value is None else f"{round(value):d}"


def _fmtpct(value):
    return "-" if value is None else f"{round(value):d}"


def _fmt_duration(seconds):
    if seconds is None:
        return "-"
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _form_strip_and_streak(sample):
    # sample is newest-first: (entry, our_side, opp_side)
    results_desc = [_side_win(entry, our_side) for entry, our_side, _ in sample]
    last5 = list(reversed(results_desc[:5]))  # oldest -> newest
    strip = "".join("\U0001F7E9" if win else "\U0001F7E5" for win in last5)
    streak = ""
    if results_desc:
        first = results_desc[0]
        count = 0
        for win in results_desc:
            if win == first:
                count += 1
            else:
                break
        streak = f"{'W' if first else 'L'}{count}"
    return strip, streak


def _radiant_dire_split(sample):
    r_w = r_g = d_w = d_g = 0
    for entry, our_side, _opp in sample:
        win = _side_win(entry, our_side)
        if our_side == "radiant":
            r_g += 1
            r_w += 1 if win else 0
        else:
            d_g += 1
            d_w += 1 if win else 0
    return {"radiant": (r_w, r_g - r_w, r_g), "dire": (d_w, d_g - d_w, d_g)}


def _length_buckets(sample):
    buckets = {"<30m": [0, 0], "30-40m": [0, 0], "40m+": [0, 0]}
    for entry, our_side, _opp in sample:
        duration = entry.get("duration")
        if not isinstance(duration, (int, float)):
            continue
        win = _side_win(entry, our_side)
        if duration < 1800:
            key = "<30m"
        elif duration < 2400:
            key = "30-40m"
        else:
            key = "40m+"
        buckets[key][0] += 1 if win else 0
        buckets[key][1] += 1
    return buckets


def _draft_stats(sample):
    picks = {}
    bans = {}
    banned_vs = {}
    for entry, our_side, _opp in sample:
        our_idx = 0 if our_side == "radiant" else 1
        opp_idx = 1 - our_idx
        for entry_pb in entry.get("picks_bans") or []:
            hero_id = entry_pb.get("hero_id")
            if hero_id is None:
                continue
            is_pick = bool(entry_pb.get("is_pick"))
            team = entry_pb.get("team")
            if is_pick and team == our_idx:
                picks[hero_id] = picks.get(hero_id, 0) + 1
            elif not is_pick and team == our_idx:
                bans[hero_id] = bans.get(hero_id, 0) + 1
            elif not is_pick and team == opp_idx:
                banned_vs[hero_id] = banned_vs.get(hero_id, 0) + 1
    return picks, bans, banned_vs


def _top3(counter):
    return sorted(counter.items(), key=lambda kv: -kv[1])[:3]


def _player_team_rows(player, key):
    matches = (player.get("official") or {}).get("matches") or []
    return [row for row in matches if row.get("team_key") == key]


def _avg_field(rows, field):
    vals = _numeric(row.get(field) for row in rows)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _sum_field(rows, field):
    vals = _numeric(row.get(field) for row in rows)
    return sum(vals) if vals else 0


def _player_kda(rows):
    k = _sum_field(rows, "kills")
    d = _sum_field(rows, "deaths")
    a = _sum_field(rows, "assists")
    return (k + a) / max(d, 1)


def _player_position_mode(rows):
    counts = {}
    for row in rows:
        pos = row.get("position")
        if pos:
            counts[pos] = counts.get(pos, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _hero_wl_stats(rows):
    """Top 3 heroes by games from official rows: [(hero_id, games, wins)]."""
    stats = {}
    for row in rows:
        hero_id = row.get("hero_id")
        if hero_id is None:
            continue
        bucket = stats.setdefault(hero_id, [0, 0])
        bucket[0] += 1
        if row.get("result") == "W":
            bucket[1] += 1
    ranked = sorted(stats.items(), key=lambda kv: -kv[1][0])[:3]
    return [(hid, games, wins) for hid, (games, wins) in ranked]


def _hero_pool_wl_stats(player):
    heroes = ((player.get("heroPool") or {}).get("heroes")) or []
    out = []
    for row in heroes[:3]:
        games = (row.get("lifetime") or {}).get("games") or 0
        wins = (row.get("lifetime") or {}).get("wins") or 0
        if not games:
            games = (row.get("recent") or {}).get("games") or 0
            wins = (row.get("recent") or {}).get("wins") or 0
        hero_id = row.get("id")
        out.append((hero_id, games, wins))
    return out


def _tf_bar(pct):
    if pct is None:
        return "▱" * 10
    filled = max(0, min(10, round(pct / 10)))
    return "▰" * filled + "▱" * (10 - filled)


def _team_profile_stats(sample, games):
    team_kills = _avg_per_game_sum(sample, "kills")
    team_deaths = _avg_per_game_sum(sample, "deaths")
    tf_avg = _avg_player_field(sample, "teamfight")
    tf_avg_pct = None if tf_avg is None else (tf_avg * 100 if tf_avg <= 1 else tf_avg)
    fb_games = fb_hits = 0
    for entry, our_side, _opp in sample:
        players = (entry.get(our_side) or {}).get("players") or []
        if not players:
            continue
        fb_games += 1
        if any(p.get("firstblood") for p in players):
            fb_hits += 1
    fb_pct = (fb_hits / fb_games * 100) if fb_games else None

    obs_pg = _avg_per_game_sum(sample, "obs_placed")
    sen_pg = _avg_per_game_sum(sample, "sen_placed")
    dewards_pg = None
    obs_kills_sum = _sum_player_field(sample, "our", "obs_kills")
    sen_kills_sum = _sum_player_field(sample, "our", "sen_kills")
    if games and (obs_kills_sum is not None or sen_kills_sum is not None):
        dewards_pg = ((obs_kills_sum or 0) + (sen_kills_sum or 0)) / games
    our_obs_total = _sum_player_field(sample, "our", "obs_placed")
    enemy_obs_kills_total = _sum_player_field(sample, "opp", "obs_kills")
    obs_lost_pct = None
    if our_obs_total:
        obs_lost_pct = (enemy_obs_kills_total or 0) / our_obs_total * 100

    gpm_pg = _avg_per_game_sum(sample, "gpm")
    xpm_pg = _avg_per_game_sum(sample, "xpm")
    lane_eff = _avg_player_field(sample, "lane_eff")
    stacks_pg = _avg_per_game_sum(sample, "camps_stacked")

    towers_pg = _avg_per_game_sum(sample, "towers_killed")
    rosh_pg = _avg_per_game_sum(sample, "roshans_killed")
    buybacks_pg = _avg_per_game_sum(sample, "buybacks")

    return {
        "kills": team_kills, "deaths": team_deaths, "tf_pct": tf_avg_pct, "fb_pct": fb_pct,
        "obs_pg": obs_pg, "sen_pg": sen_pg, "dewards_pg": dewards_pg, "obs_lost_pct": obs_lost_pct,
        "gpm_pg": gpm_pg, "xpm_pg": xpm_pg, "lane_eff": lane_eff, "stacks_pg": stacks_pg,
        "towers_pg": towers_pg, "rosh_pg": rosh_pg, "buybacks_pg": buybacks_pg,
    }


def _key_read_stats(payload, key, sample, roster_players):
    """Return a list of (score, lead_in, evidence) tuples, highest score
    first is NOT guaranteed here - caller sorts. Mirrors the old _key_reads
    scoring, reworded to the "Lead-in: evidence" bullet format."""
    bullets = []

    split = _radiant_dire_split(sample)
    r_w, r_l, r_g = split["radiant"]
    d_w, d_l, d_g = split["dire"]
    if r_g >= 2 and d_g >= 2:
        r_wr = r_w / r_g * 100
        d_wr = d_w / d_g * 100
        if abs(r_wr - d_wr) >= 25:
            better = "Radiant" if r_wr > d_wr else "Dire"
            better_wr = r_wr if better == "Radiant" else d_wr
            worse_wr = d_wr if better == "Radiant" else r_wr
            bullets.append((abs(r_wr - d_wr), f"{better}-sided",
                             f"{round(better_wr)}% on {better}, {round(worse_wr)}% on "
                             f"{'Dire' if better == 'Radiant' else 'Radiant'}"))

    buckets = _length_buckets(sample)
    valid = [(name, w, g) for name, (w, g) in buckets.items() if g >= 2]
    if len(valid) >= 2:
        rated = [(name, w / g * 100, g, w) for name, w, g in valid]
        best = max(rated, key=lambda row: row[1])
        worst = min(rated, key=lambda row: row[1])
        if worst[0] == "40m+":
            lead_in = "Fades late"
        elif best[0] == "40m+":
            lead_in = "Scales late"
        else:
            lead_in = "Game length"
        under30 = buckets["<30m"]
        over40 = buckets["40m+"]
        evidence = (f"{under30[0]}-{under30[1] - under30[0]} under 30m, "
                    f"{over40[0]}-{over40[1] - over40[0]} past 40m")
        if best[0] != worst[0] and (best[1] - worst[1]) >= 1:
            bullets.append((best[1] - worst[1], lead_in, evidence))

    # Vision load: player with the largest share of team obs_placed.
    obs_totals = {}
    for player in roster_players:
        rows = _player_team_rows(player, key)
        total = _sum_field(rows, "obs_placed")
        if total:
            obs_totals[player.get("name") or "?"] = (total, len(rows))
    team_obs_total = sum(v[0] for v in obs_totals.values())
    if team_obs_total and obs_totals:
        top_name, (top_total, top_games) = max(obs_totals.items(), key=lambda kv: kv[1][0])
        if top_games >= 2:
            share = top_total / team_obs_total * 100
            bullets.append((share * 0.6, f"Vision runs through {top_name}",
                             f"{round(share)}% of team observers"))

    # TF anchor: highest TF%, and lowest if below 55%.
    tf_rows = []
    for player in roster_players:
        rows = _player_team_rows(player, key)
        if len(rows) < 2:
            continue
        tf_raw = _avg_field(rows, "teamfight")
        if tf_raw is None:
            continue
        tf_pct = tf_raw * 100 if tf_raw <= 1 else tf_raw
        tf_rows.append((player.get("name") or "?", tf_pct))
    if tf_rows:
        top_name, top_tf = max(tf_rows, key=lambda kv: kv[1])
        bullets.append((top_tf * 0.5, "Teamfight anchor", f"{top_name} at {round(top_tf)}%"))
        low_name, low_tf = min(tf_rows, key=lambda kv: kv[1])
        if low_tf < 55 and low_name != top_name:
            bullets.append((100 - low_tf, "Hard to find in fights",
                             f"{low_name} at just {round(low_tf)}% teamfight participation"))

    # Deaths: player with most deaths/g.
    death_rows = []
    for player in roster_players:
        rows = _player_team_rows(player, key)
        if len(rows) < 2:
            continue
        avg_deaths = _avg_field(rows, "deaths")
        if avg_deaths is not None:
            death_rows.append((player.get("name") or "?", avg_deaths))
    if death_rows:
        name, avg_deaths = max(death_rows, key=lambda kv: kv[1])
        bullets.append((avg_deaths * 3, "Most deaths", f"{name} at {avg_deaths:.1f} per game"))

    # Dewarding: player with most dewards/g.
    deward_rows = []
    for player in roster_players:
        rows = _player_team_rows(player, key)
        if len(rows) < 2:
            continue
        obs_kills = _sum_field(rows, "obs_kills")
        sen_kills = _sum_field(rows, "sen_kills")
        per_game = (obs_kills + sen_kills) / len(rows)
        if per_game:
            deward_rows.append((player.get("name") or "?", per_game))
    if deward_rows:
        name, per_game = max(deward_rows, key=lambda kv: kv[1])
        bullets.append((per_game * 3, "Top dewarder", f"{name} at {per_game:.1f} per game"))

    # First blood rate.
    fb_games = 0
    fb_hits = 0
    for entry, our_side, _opp in sample:
        players = (entry.get(our_side) or {}).get("players") or []
        if not players:
            continue
        fb_games += 1
        if any(p.get("firstblood") for p in players):
            fb_hits += 1
    if fb_games >= 2:
        fb_pct = fb_hits / fb_games * 100
        if fb_pct >= 60:
            bullets.append((abs(fb_pct - 45), "First blood hunters", f"{round(fb_pct)}% of games"))
        elif fb_pct <= 30:
            bullets.append((abs(fb_pct - 45), "Slow to first blood", f"{round(fb_pct)}% of games"))

    bullets.sort(key=lambda row: -row[0])
    return bullets


# --------------------------------------------------------------------------
# Components V2 primitives
# --------------------------------------------------------------------------

def _text(content):
    return {"type": TYPE_TEXT_DISPLAY, "content": content}


def _separator(divider=True, spacing=1):
    return {"type": TYPE_SEPARATOR, "divider": divider, "spacing": spacing}


def _container(components):
    return {"type": TYPE_CONTAINER, "accent_color": ACCENT_COLOR, "components": components}


def _thumbnail(url):
    return {"type": TYPE_THUMBNAIL, "media": {"url": url}}


def _section(text_content, accessory=None):
    node = {"type": TYPE_SECTION, "components": [_text(text_content)]}
    if accessory is not None:
        node["accessory"] = accessory
    return node


def _media_gallery(items):
    return {"type": TYPE_MEDIA_GALLERY, "items": items}


def _count_components(nodes):
    """Count every component object, including nested ones (section
    children + accessory), which is what Discord's <=40 limit counts
    against. Media-gallery items aren't component objects and don't count."""
    total = 0
    for node in nodes:
        total += 1
        if isinstance(node.get("components"), list):
            total += _count_components(node["components"])
        accessory = node.get("accessory")
        if isinstance(accessory, dict):
            total += _count_components([accessory])
    return total


def _text_chars(nodes):
    total = 0
    for node in nodes:
        if node.get("type") == TYPE_TEXT_DISPLAY:
            total += len(node.get("content") or "")
        if isinstance(node.get("components"), list):
            total += _text_chars(node["components"])
    return total


# --------------------------------------------------------------------------
# Briefing page
# --------------------------------------------------------------------------

def _header_lines(official_source, team_row):
    week = official_source.get("week")
    league = official_source.get("league") or team_row.get("league") or "League"
    return f"-# \U0001F50E SCOUT BRIEFING · {league} · WEEK {week if week is not None else '?'}"


def _record_line(team_row, standing, vs_row):
    record = team_row.get("record") or "-"
    rank = standing.get("rank")
    rank_part = f"#{rank}" if rank is not None else "#?"
    if vs_row:
        vs_short = vs_row.get("short") or vs_row.get("name") or "?"
        vs_record = vs_row.get("record") or "-"
        return (f"**{record}** · {rank_part} · Up next vs "
                f"**__{vs_short}__** ({vs_record})")
    return f"**{record}** · {rank_part} · No upcoming matchup posted."


def _form_line(sample):
    strip, streak = _form_strip_and_streak(sample)
    split = _radiant_dire_split(sample)
    r_w, r_l, _r_g = split["radiant"]
    d_w, d_l, _d_g = split["dire"]
    durations = _numeric(entry.get("duration") for entry, _o, _p in sample)
    avg_duration = sum(durations) / len(durations) if durations else None
    games = len(sample)
    return (f"**Form** {strip or '-'} · **{streak or '-'}**   "
            f"**Radiant** {r_w}-{r_l} · **Dire** {d_w}-{d_l} · "
            f"**Avg length** {_fmt_duration(avg_duration)} · **Games** {games}")


def _team_profile_content(stats, buckets):
    def bucket_line(name):
        w, g = buckets[name]
        return "-" if not g else f"{w}-{g - w}"

    lines = [
        "### \U0001F4CA __Team profile__",
        (f"⚔️ **Fighting** · Kills {_fmt1(stats['kills'])} · "
         f"Deaths {_fmt1(stats['deaths'])} · Teamfight {_fmtpct(stats['tf_pct'])}% · "
         f"First blood {_fmtpct(stats['fb_pct'])}%"),
        (f"\U0001F441️ **Vision** · Obs {_fmt1(stats['obs_pg'])} · "
         f"Sentries {_fmt1(stats['sen_pg'])} · Dewards {_fmt1(stats['dewards_pg'])} · "
         f"Obs lost {_fmtpct(stats['obs_lost_pct'])}%"),
        (f"\U0001F4B0 **Economy** · GPM {_fmtint(stats['gpm_pg'])} · "
         f"XPM {_fmtint(stats['xpm_pg'])} · Lane eff {_fmtpct(stats['lane_eff'])}% · "
         f"Stacks {_fmt1(stats['stacks_pg'])}"),
        (f"\U0001F3F0 **Objectives** · Towers {_fmt1(stats['towers_pg'])} · "
         f"Rosh {_fmt1(stats['rosh_pg'])} · Buybacks {_fmt1(stats['buybacks_pg'])}"),
        (f"⏳ **By length** · <30m {bucket_line('<30m')} · "
         f"30-40m {bucket_line('30-40m')} · 40m+ {bucket_line('40m+')}"),
    ]
    return "\n".join(lines)


def _draft_content(sample, heroes_map, hero_emoji):
    picks, bans, banned_vs = _draft_stats(sample)

    def render(counter):
        rows = _top3(counter)
        if not rows:
            return "-"
        return " · ".join(f"{_hero_token(heroes_map, hero_emoji, hid)} {n}" for hid, n in rows)

    lines = [
        "### \U0001F9E0 __Draft__",
        f"**Picks** {render(picks)}",
        f"**Bans** {render(bans)}",
        f"**Banned vs** {render(banned_vs)}",
    ]
    return "\n".join(lines)


def _player_section(player, key, heroes_map, hero_emoji, portraits):
    rows = _player_team_rows(player, key)
    position = _player_position_mode(rows)
    keycap = POSITION_KEYCAPS.get(position, UNKNOWN_KEYCAP)
    rank = player.get("rank") or "Unranked"
    name = player.get("name") or "Unknown"
    header = f"{keycap} **__{name}__** · Pos {position or '?'} · {rank}"

    if not rows:
        hero_rows = _hero_pool_wl_stats(player)
        hero_line = "**Heroes (pubs)** " + (
            " · ".join(
                f"{_hero_prefix(hero_emoji, hid)}{_hero_name(heroes_map, hid)} {w}-{g - w}"
                for hid, g, w in hero_rows
            ) or "no pub data"
        )
        content = "\n".join([header, "No official games for this team yet", hero_line])
    else:
        k = _avg_field(rows, "kills")
        d = _avg_field(rows, "deaths")
        a = _avg_field(rows, "assists")
        kda = _player_kda(rows)
        gpm = _avg_field(rows, "gpm")
        tf_raw = _avg_field(rows, "teamfight")
        tf_pct = None if tf_raw is None else (tf_raw * 100 if tf_raw <= 1 else tf_raw)
        bar = _tf_bar(tf_pct)

        combat_line = (f"**Combat** {_fmt1(k)} / {_fmt1(d)} / {_fmt1(a)} · "
                        f"KDA {kda:.1f} · {_fmtint(gpm)} GPM")
        tf_line = f"**Teamfight** {_fmtpct(tf_pct)}% {bar}"

        obs = _avg_field(rows, "obs_placed")
        sen = _avg_field(rows, "sen_placed")
        obs_kills = _sum_field(rows, "obs_kills")
        sen_kills = _sum_field(rows, "sen_kills")
        dewards_per_game = (obs_kills + sen_kills) / len(rows) if rows else None
        stuns = _avg_field(rows, "stuns")
        stacks = _avg_field(rows, "camps_stacked")
        vision_line = (f"**Vision** {_fmt1(obs)} obs · {_fmt1(sen)} sen · "
                        f"{_fmt1(dewards_per_game)} dewards · "
                        f"**Utility** {_fmt1(stuns)}s stuns · {_fmt1(stacks)} stacks")

        if len(rows) < 2:
            hero_rows = _hero_pool_wl_stats(player)
            label = "**Heroes (pubs)**"
        else:
            hero_rows = _hero_wl_stats(rows)
            label = "**Heroes**"
        heroes_line = label + " " + (
            " · ".join(
                f"{_hero_prefix(hero_emoji, hid)}{_hero_name(heroes_map, hid)} {w}-{g - w}"
                for hid, g, w in hero_rows
            ) or "-"
        )

        content = "\n".join([header, combat_line, tf_line, vision_line, heroes_line])

    portrait_url = None
    if portraits:
        best_hero = None
        best_games = -1
        counts = {}
        for row in rows:
            hid = row.get("hero_id")
            if hid is None:
                continue
            counts[hid] = counts.get(hid, 0) + 1
        for hid, games in counts.items():
            if games > best_games:
                best_games = games
                best_hero = hid
        if best_hero is not None:
            portrait_url = portraits.get(str(best_hero)) or portraits.get(best_hero)

    if portrait_url:
        return _section(content, accessory=_thumbnail(portrait_url))
    return _text(content)


def _key_reads_content(payload, key, sample, roster_players, limit=5):
    bullets = _key_read_stats(payload, key, sample, roster_players)[:limit]
    if not bullets:
        return None
    lines = [KEY_READS_HEADER]
    lines.extend(f"- **{lead_in}:** {evidence}." for _score, lead_in, evidence in bullets)
    return "\n".join(lines)


def _footer_content(middle, generated_at, standin_names):
    generated = "-"
    if generated_at:
        generated = datetime.fromtimestamp(generated_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"-# Team Scout · {middle} · data {generated} · standins: {standin_names}"


def build_briefing_page(payload, team, vs=None, hero_emoji=None, portraits=None):
    """Build the "Briefing" Components V2 page for `team`: {"components":
    [...], "files": []}. `vs` defaults to the team's current-week matchup
    opponent. `hero_emoji` maps hero_id (str or int) -> a Discord custom
    emoji token; `portraits` maps hero_id -> a portrait image URL for player
    thumbnails. Both are optional - without them the page just uses text."""
    heroes_map = payload.get("heroes") or {}
    players_by_id = {p.get("id"): p for p in payload.get("players") or []}

    team_row = _find_team(payload, team)
    key = team_row.get("key")

    if vs:
        vs_row = _find_team(payload, vs)
    else:
        vs_row = _find_matchup_opponent(payload, key)

    official_source = payload.get("officialSource") or {}
    standing = _standing_for(payload, key)

    sample = _team_sample(payload, key)
    games = len(sample)

    roster_ids = team_row.get("roster") or []
    roster_players = []
    for pid in roster_ids:
        player = players_by_id.get(pid)
        if player is None:
            player = {"id": pid, "name": f"Player {pid}", "rank": None,
                       "official": {"matches": []}, "heroPool": {"heroes": []}}
        roster_players.append(player)

    def player_sort_key(player):
        rows = _player_team_rows(player, key)
        pos = _player_position_mode(rows)
        return (pos is None, pos or 0)

    roster_players.sort(key=player_sort_key)

    stats = _team_profile_stats(sample, games)
    buckets = _length_buckets(sample)

    standin_names = ", ".join(
        row.get("name") for row in (team_row.get("replacements") or []) if row.get("name")
    ) or "none"

    components = [
        _text("\n".join((_header_lines(official_source, team_row),
                          f"## {team_row.get('short') or team_row.get('name') or team}",
                          _record_line(team_row, standing, vs_row)))),
        _text(_form_line(sample)),
        _separator(),
        _text(_team_profile_content(stats, buckets)),
        _separator(),
        _text(_draft_content(sample, heroes_map, hero_emoji)),
        _separator(),
        _text("### \U0001F465 __Players__"),
    ]
    player_nodes = [_player_section(player, key, heroes_map, hero_emoji, portraits)
                     for player in roster_players]
    components.extend(player_nodes)

    key_reads_index = None
    key_reads_content = _key_reads_content(payload, key, sample, roster_players)
    if key_reads_content:
        components.append(_separator())
        components.append(_text(key_reads_content))
        key_reads_index = len(components) - 1

    footer_text = _footer_content(f"{games} official games", payload.get("generatedAt"), standin_names)
    components.append(_text(footer_text))

    _enforce_page_limits(
        components, player_nodes,
        key_reads_index=key_reads_index,
        key_reads_getter=lambda limit: _key_reads_content(payload, key, sample, roster_players, limit=limit),
    )

    return {"components": [_container(components)], "files": []}


def _enforce_page_limits(components, player_nodes, key_reads_index=None, key_reads_getter=None):
    """Trim, in order: Key reads bullets, then player hero lines, to stay
    under the 4000-char text budget. Never exceeds LIMIT_COMPONENTS either
    (this page's fixed layout never gets close, but a defensive trim keeps
    the promise absolute)."""
    def total_chars():
        return _text_chars(components)

    if total_chars() <= LIMIT_TEXT_TOTAL and _count_components(components) <= LIMIT_COMPONENTS:
        return

    # 1) Trim Key reads bullets one at a time.
    if key_reads_getter and key_reads_index is not None:
        for limit in range(4, -1, -1):
            new_content = key_reads_getter(limit)
            if new_content is None:
                # No bullets left: drop the header/text node and its
                # preceding separator.
                if components[key_reads_index].get("type") == TYPE_TEXT_DISPLAY:
                    del components[key_reads_index]
                    if (key_reads_index - 1 >= 0
                            and components[key_reads_index - 1].get("type") == TYPE_SEPARATOR):
                        del components[key_reads_index - 1]
                break
            components[key_reads_index]["content"] = new_content
            if total_chars() <= LIMIT_TEXT_TOTAL:
                return
        if total_chars() <= LIMIT_TEXT_TOTAL:
            return

    # 2) Trim player hero lines (drop the "**Heroes" line from each player
    # section, largest sections first) until under budget.
    ranked = sorted(player_nodes, key=lambda node: _text_chars([node]), reverse=True)
    for node in ranked:
        inner = node["components"][0] if node.get("type") == TYPE_SECTION else node
        lines = (inner.get("content") or "").split("\n")
        lines = [ln for ln in lines if not ln.startswith("**Heroes")]
        inner["content"] = "\n".join(lines)
        if total_chars() <= LIMIT_TEXT_TOTAL:
            return

    # 3) Still over (an unusually large roster): drop the Vision and
    # Teamfight lines too, largest sections first.
    ranked = sorted(player_nodes, key=lambda node: _text_chars([node]), reverse=True)
    for node in ranked:
        inner = node["components"][0] if node.get("type") == TYPE_SECTION else node
        lines = (inner.get("content") or "").split("\n")
        lines = [ln for ln in lines if not ln.startswith(("**Vision**", "**Teamfight**"))]
        inner["content"] = "\n".join(lines)
        if total_chars() <= LIMIT_TEXT_TOTAL:
            return

    # 4) Last resort, guaranteed to terminate: hard-truncate the largest
    # remaining TextDisplay contents until the total is back under budget.
    # "Never exceed" wins over prettiness once every softer trim is spent.
    def all_text_nodes(nodes):
        found = []
        for node in nodes:
            if node.get("type") == TYPE_TEXT_DISPLAY:
                found.append(node)
            if isinstance(node.get("components"), list):
                found.extend(all_text_nodes(node["components"]))
        return found

    guard = 0
    while total_chars() > LIMIT_TEXT_TOTAL and guard < 10000:
        guard += 1
        text_nodes = sorted(all_text_nodes(components), key=lambda n: len(n.get("content") or ""),
                             reverse=True)
        if not text_nodes or not (text_nodes[0].get("content") or ""):
            break
        biggest = text_nodes[0]
        biggest["content"] = biggest["content"][:-200] if len(biggest["content"]) > 200 else ""


# --------------------------------------------------------------------------
# Wards page
# --------------------------------------------------------------------------

def _ward_side_games(payload, key, patch_id):
    r_games = set()
    d_games = set()
    for entry in payload.get("teamMatches") or []:
        if entry.get("patch") != patch_id:
            continue
        radiant_key = (entry.get("radiant") or {}).get("team_key")
        dire_key = (entry.get("dire") or {}).get("team_key")
        match_id = entry.get("match_id")
        if radiant_key == key:
            r_games.add(match_id)
        elif dire_key == key:
            d_games.add(match_id)
    return len(r_games), len(d_games)


def _mid_ward_summary_line(label, side_summary):
    """One text line summarizing a side's mid-ward result, from the summary
    dict ward_render.render_mid_ward() returns per side."""
    games = side_summary.get("games") or 0
    with_obs = side_summary.get("withObserver") or 0
    top = side_summary.get("topSpotCount") or 0
    spots = side_summary.get("spots") or 0
    by_teammate = side_summary.get("byTeammate") or 0

    if not with_obs:
        verdict = "no early observer"
    elif top / max(with_obs, 1) >= 0.5:
        verdict = f"one main spot ({top} of {with_obs})"
    else:
        verdict = f"spread over {spots} spots"

    line = f"**{label}** {with_obs} of {games} games · {verdict}"
    if by_teammate:
        line += f" · {by_teammate}* by a teammate"
    return line


def build_wards_page(payload, team, vs=None, hero_emoji=None, extra_images=None,
                      mid_ward_summary=None):
    """Build the "Wards" Components V2 page for `team`: {"components": [...],
    "files": [(filename, bytes), ...]}.

    `extra_images` is an optional list of (filename, bytes, description)
    tuples. Without `mid_ward_summary` they're simply appended to the main
    sheet's media gallery (e.g. a zoomed detail) - the original, simple
    shape. When `mid_ward_summary` is also given (the per-side {"games",
    "withObserver", "byTeammate", "topSpotCount", "spots"} dict that
    ward_render.render_mid_ward() returns), `extra_images[0]` is treated as
    the mid ward image: it gets its own heading, summary text and media
    gallery placed ahead of the existing supports sheet, so the page reads
    top-down (mid ward, then supports); any further `extra_images[1:]` join
    the supports gallery alongside wards.png, same as before."""
    team_row = _find_team(payload, team)
    key = team_row.get("key")
    official_source = payload.get("officialSource") or {}

    patch_id = _ward_patch_id(payload)
    r_games, d_games = _ward_side_games(payload, key, patch_id)

    players_by_id = {p.get("id"): p for p in payload.get("players") or []}
    roster_ids = team_row.get("roster") or []
    roster_players = [players_by_id[pid] for pid in roster_ids if pid in players_by_id]

    def side_team_totals(side, side_games):
        obs_total = sen_total = 0
        for player in roster_players:
            wards = _player_side_wards(player, key, patch_id)
            obs_total += len(wards[side]["obs"])
            sen_total += len(wards[side]["sen"])
        obs_avg = obs_total / side_games if side_games else None
        sen_avg = sen_total / side_games if side_games else None
        return obs_avg, sen_avg

    r_obs_avg, r_sen_avg = side_team_totals("radiant", r_games)
    d_obs_avg, d_sen_avg = side_team_totals("dire", d_games)

    who_wards_rows = []
    for player in roster_players:
        wards = _player_side_wards(player, key, patch_id)
        r_obs = len(wards["radiant"]["obs"])
        r_sen = len(wards["radiant"]["sen"])
        d_obs = len(wards["dire"]["obs"])
        d_sen = len(wards["dire"]["sen"])
        total = r_obs + r_sen + d_obs + d_sen
        r_games_p = wards["radiant"]["games"]
        d_games_p = wards["dire"]["games"]
        r_obs_avg_p = r_obs / r_games_p if r_games_p else 0
        r_sen_avg_p = r_sen / r_games_p if r_games_p else 0
        d_obs_avg_p = d_obs / d_games_p if d_games_p else 0
        d_sen_avg_p = d_sen / d_games_p if d_games_p else 0
        position = _player_position_mode(_player_team_rows(player, key))
        who_wards_rows.append((total, player.get("name") or "?", position,
                                r_obs_avg_p, r_sen_avg_p, d_obs_avg_p, d_sen_avg_p))
    who_wards_rows.sort(key=lambda row: -row[0])

    who_lines = ["### \U0001F9ED __Who wards__"]
    for i, (total, name, position, r_o, r_s, d_o, d_s) in enumerate(who_wards_rows):
        pos_part = f" (Pos {position})" if position else ""
        if total == 0:
            who_lines.append(f"**{name}**{pos_part} · none placed")
        elif i == 0:
            who_lines.append(f"**{name}**{pos_part} · **R** {r_o:.1f} obs / {r_s:.1f} sen "
                              f"· **D** {d_o:.1f} / {d_s:.1f}")
        else:
            who_lines.append(f"**{name}**{pos_part} · **R** {r_o:.1f} / {r_s:.1f} "
                              f"· **D** {d_o:.1f} / {d_s:.1f}")

    sheet_bytes = _render_ward_sheet(payload, team_row, positions=(1, 4, 5))

    def _gallery_item(entry):
        filename, data, description = entry
        item = {"media": {"url": f"attachment://{filename}"}}
        if description:
            item["description"] = description
        return item, (filename, data)

    supports_heading = _text("\n".join((
        "### \U0001F5FA️ __Supports and carry__",
        "-# Pos 1, 4 and 5 · gold = observer, teal = sentry, larger = more often")))

    if mid_ward_summary:
        extras = list(extra_images or [])
        mid_entry, rest = (extras[0], extras[1:]) if extras else (None, [])

        files = []
        wards_block = []

        mid_lines = ["### \U0001F3AF __Mid ward__"]
        for side, label in (("radiant", "Radiant"), ("dire", "Dire")):
            mid_lines.append(_mid_ward_summary_line(label, mid_ward_summary.get(side) or {}))
        wards_block.append(_text("\n".join(mid_lines)))

        if mid_entry:
            item, file_entry = _gallery_item(mid_entry)
            wards_block.append(_media_gallery([item]))
            files.append(file_entry)

        wards_block.append(_separator())
        wards_block.append(supports_heading)

        supports_items = [{"media": {"url": "attachment://wards.png"}}]
        files.append(("wards.png", sheet_bytes))
        for entry in rest:
            item, file_entry = _gallery_item(entry)
            supports_items.append(item)
            files.append(file_entry)
        wards_block.append(_media_gallery(supports_items))
    else:
        gallery_items = [{"media": {"url": "attachment://wards.png"}}]
        files = [("wards.png", sheet_bytes)]
        for entry in extra_images or []:
            item, file_entry = _gallery_item(entry)
            gallery_items.append(item)
            files.append(file_entry)
        wards_block = [supports_heading, _media_gallery(gallery_items)]

    standin_names = ", ".join(
        row.get("name") for row in (team_row.get("replacements") or []) if row.get("name")
    ) or "none"

    components = [
        _text("\n".join((_header_lines(official_source, team_row),
                          f"## \U0001F5FA️ {team_row.get('short') or team_row.get('name') or team} · Wards",
                          f"**Patch** 7.41 · **Officials only** · "
                          f"**Radiant** {r_games} games · **Dire** {d_games} games"))),
        _separator(),
        _text("\n".join(("### \U0001F441️ __Team per game__",
                          f"**Radiant** {_fmt1(r_obs_avg)} obs · {_fmt1(r_sen_avg)} sen",
                          f"**Dire** {_fmt1(d_obs_avg)} obs · {_fmt1(d_sen_avg)} sen"))),
        _text("\n".join(who_lines)),
        _separator(),
    ] + wards_block + [
        _text(_footer_content("7.41 officials", payload.get("generatedAt"), standin_names)),
    ]

    return {"components": [_container(components)], "files": files}


# --------------------------------------------------------------------------
# Plain-text preview renderer
# --------------------------------------------------------------------------

def page_text(components):
    """Render a Components V2 tree (a top-level components list, as
    returned in build_*_page()["components"]) as plain text for a terminal
    preview."""
    lines = []

    def walk(node):
        t = node.get("type")
        if t == TYPE_TEXT_DISPLAY:
            lines.append(node.get("content") or "")
        elif t == TYPE_SEPARATOR:
            lines.append("---")
        elif t == TYPE_SECTION:
            for child in node.get("components") or []:
                walk(child)
            accessory = node.get("accessory")
            if accessory and accessory.get("type") == TYPE_THUMBNAIL:
                url = (accessory.get("media") or {}).get("url")
                lines.append(f"[thumbnail: {url}]")
        elif t == TYPE_CONTAINER:
            for child in node.get("components") or []:
                walk(child)
        elif t == TYPE_MEDIA_GALLERY:
            for item in node.get("items") or []:
                url = (item.get("media") or {}).get("url")
                lines.append(f"[image: {url}]")
        elif t == TYPE_ACTION_ROW:
            for child in node.get("components") or []:
                walk(child)
        elif t == TYPE_BUTTON:
            lines.append(f"[button: {node.get('label')}]")

    for node in components:
        walk(node)
    return "\n\n".join(lines)
