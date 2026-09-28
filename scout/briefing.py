"""Scout Bot "Briefing": build Discord Components V2 pages from a Team Scout
payload. Pure functions, no network, no Discord import - the caller (the
bot) owns posting.

Three pages are produced, each a single Container component:
  build_briefing_page() - league ranks, key reads, draft, compact player summaries.
  build_wards_page()    - separate Radiant/Dire map images for every player.
  build_recon_page()    - this week's public games for the opponent roster.

Stat computation (the _*_stats helpers) is kept separate from rendering (the
_*_lines / build_* functions) so either can change independently.
"""

from datetime import datetime, timedelta, timezone

from .bbc_source import team_key as _team_key
from .medals import medal_prefix
from .team_rankings import team_rankings
from .ward_render import (
    ward_patch_id as _ward_patch_id,
    player_side_wards as _player_side_wards,
    render_player_ward_rows as _render_player_ward_rows,
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
    """Official heroes by win rate, then games: [(hero_id, games, wins)]."""
    stats = {}
    for row in rows:
        hero_id = row.get("hero_id")
        if hero_id is None:
            continue
        bucket = stats.setdefault(hero_id, [0, 0])
        bucket[0] += 1
        if row.get("result") == "W":
            bucket[1] += 1
    ranked = sorted(stats.items(), key=lambda kv: (-kv[1][1] / kv[1][0], -kv[1][0]))
    return [(hid, games, wins) for hid, (games, wins) in ranked]


def _hero_result(hero_id, games, wins, heroes_map, hero_emoji):
    return f"{_hero_token(heroes_map, hero_emoji, hero_id)} {wins}-{games - wins}"


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
    league = team_row.get("league") or official_source.get("league") or "League"
    return f"-# \U0001F50E SCOUT BRIEFING · {league}"


def _team_profile_content(stats, buckets):
    def bucket_line(name):
        w, g = buckets[name]
        return "-" if not g else f"{w}-{g - w}"

    lines = [
        "### __Team profile__",
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


def _team_rankings_content(payload, key):
    row = team_rankings(payload).get(key)
    if not row:
        return None
    metrics = row["metrics"]

    def place(metric):
        value = metrics[metric]
        return (f"#{value['rank']}/{value['total']}" if value["rank"] is not None
                else "—")

    return "\n".join([
        "### __League ranks__",
        f"-# {row['games']} official games · #1 means most · only teams with data count",
        f"⚔️ **Fighting** · Win rate {place('win_rate')} · Kills {place('kills')} · "
        f"Deaths {place('deaths')} · Teamfight {place('teamfight')} · First blood {place('first_blood')}",
        f"👁️ **Vision** · Observers {place('observers')} · Sentries {place('sentries')} · "
        f"Dewards {place('dewards')} · Obs lost {place('obs_lost')}",
        f"💰 **Economy** · GPM {place('gpm')} · XPM {place('xpm')} · "
        f"Lane efficiency {place('lane_eff')} · Stacks {place('stacks')}",
        f"🏰 **Objectives** · Towers {place('towers')} · Roshan {place('roshan')} · "
        f"Buybacks {place('buybacks')}",
    ])


def _draft_content(sample, heroes_map, hero_emoji):
    picks, bans, banned_vs = _draft_stats(sample)

    def render(counter):
        rows = _top3(counter)
        if not rows:
            return "-"
        return " · ".join(f"{_hero_token(heroes_map, hero_emoji, hid)} {n}" for hid, n in rows)

    lines = [
        "### __Draft__",
        f"**Most picked** {render(picks)}",
        f"**Their bans** {render(bans)}",
        f"**Banned against them** {render(banned_vs)}",
    ]
    return "\n".join(lines)


def _player_section(player, key, heroes_map, hero_emoji, medal_emoji=None):
    rows = _player_team_rows(player, key)
    position = _player_position_mode(rows)
    keycap = POSITION_KEYCAPS.get(position, UNKNOWN_KEYCAP)
    rank = player.get("rank") or "Unranked"
    name = player.get("name") or "Unknown"
    medal = medal_prefix(player.get("rankTier"), medal_emoji)
    header = f"{keycap} {medal}**__{name}__**"
    if not medal:
        header += f" · {rank}"

    if not rows:
        hero_line = "**Heroes** No official games for this team yet"
        content = "\n".join([header, hero_line])
    else:
        kda = _player_kda(rows)
        gpm = _avg_field(rows, "gpm")
        stats_line = (f"**Stats** {kda:.1f} KDA · {_fmtint(gpm)} GPM · "
                      f"{len(rows)} game{'s' if len(rows) != 1 else ''}")

        hero_rows = _hero_wl_stats(rows)
        heroes_line = "**Heroes** " + (
            " · ".join(
                _hero_result(hid, g, w, heroes_map, hero_emoji)
                for hid, g, w in hero_rows
            ) or "-"
        )

        content = "\n".join([header, stats_line, heroes_line])

    avatar_url = player.get("avatar")
    if isinstance(avatar_url, str) and avatar_url.startswith("https://"):
        return _section(content, accessory=_thumbnail(avatar_url))
    return _text(content)


def _key_reads_content(payload, key, sample, roster_players, limit=3):
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


def build_briefing_page(payload, team, vs=None, hero_emoji=None, medal_emoji=None):
    """Build the "Briefing" Components V2 page for `team`: {"components":
    [...], "files": []}. `hero_emoji` maps hero_id (str or int) -> a Discord custom
    emoji token; `medal_emoji` maps rank tiers to Discord emoji tokens.
    Player thumbnails use Steam avatars from the payload when available."""
    heroes_map = payload.get("heroes") or {}
    players_by_id = {p.get("id"): p for p in payload.get("players") or []}

    team_row = _find_team(payload, team)
    key = team_row.get("key")

    if vs:
        _find_team(payload, vs)

    official_source = payload.get("officialSource") or {}

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

    standin_names = ", ".join(
        row.get("name") for row in (team_row.get("replacements") or []) if row.get("name")
    ) or "none"

    components = [
        _text("\n".join((_header_lines(official_source, team_row),
                          f"## {team_row.get('short') or team_row.get('name') or team} · "
                          f"{team_row.get('record') or '-'}"))),
    ]
    ranks = _team_rankings_content(payload, key)
    if ranks:
        components.extend([_separator(), _text(ranks)])
    key_reads_index = None
    key_reads_content = _key_reads_content(payload, key, sample, roster_players)
    if key_reads_content:
        components.append(_separator())
        components.append(_text(key_reads_content))
        key_reads_index = len(components) - 1

    components.extend([
        _separator(),
        _text(_draft_content(sample, heroes_map, hero_emoji)),
        _separator(),
        _text("### __Players__"),
    ])
    player_nodes = [_player_section(player, key, heroes_map, hero_emoji, medal_emoji)
                    for player in roster_players]
    components.extend(player_nodes)

    footer_text = _footer_content(f"{games} official games", payload.get("generatedAt"), standin_names)
    components.append(_text(footer_text))

    _enforce_page_limits(
        components, player_nodes,
        key_reads_index=key_reads_index,
        key_reads_getter=lambda limit: _key_reads_content(payload, key, sample, roster_players, limit=limit),
    )

    return {"components": [_container(components)], "files": []}


def _enforce_page_limits(components, player_nodes, key_reads_index=None, key_reads_getter=None):
    """Keep the full official hero lists while fitting Discord's text budget."""
    def total_chars():
        return _text_chars(components)

    if total_chars() <= LIMIT_TEXT_TOTAL and _count_components(components) <= LIMIT_COMPONENTS:
        return

    # 1) Trim Key reads bullets one at a time.
    if key_reads_getter and key_reads_index is not None:
        for limit in range(2, -1, -1):
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

    # 2) Make room with lower-priority summary sections. Each hero needs its
    # icon (or a short text fallback) to remain identifiable.
    for title in ("__Draft__",):
        for index, node in enumerate(components):
            if title not in (node.get("content") or ""):
                continue
            del components[index]
            if index and components[index - 1].get("type") == TYPE_SEPARATOR:
                del components[index - 1]
            break
        if total_chars() <= LIMIT_TEXT_TOTAL:
            return

    # 3) On unusually large rosters, trim supporting player stats before
    # touching official hero lists.
    ranked = sorted(player_nodes, key=lambda node: _text_chars([node]), reverse=True)
    for node in ranked:
        inner = node["components"][0] if node.get("type") == TYPE_SECTION else node
        lines = (inner.get("content") or "").split("\n")
        lines = [ln for ln in lines if not ln.startswith("**Stats**")]
        inner["content"] = "\n".join(lines)
        if total_chars() <= LIMIT_TEXT_TOTAL:
            return

    # 4) Final safety for a pathological roster larger than one Discord page.
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
        text_nodes = sorted(all_text_nodes(components),
                            key=lambda n: ("**Heroes**" in (n.get("content") or ""),
                                           -len(n.get("content") or "")))
        if not text_nodes or not (text_nodes[0].get("content") or ""):
            break
        biggest = text_nodes[0]
        biggest["content"] = biggest["content"][:-200] if len(biggest["content"]) > 200 else ""


# --------------------------------------------------------------------------
# Wards page
# --------------------------------------------------------------------------

def build_wards_page(payload, team, vs=None, hero_emoji=None, extra_images=None,
                     game_mode="individual"):
    """Build a Wards page with Mid/4/5 lane maps and support full maps.

    The CLI supplies Mid/Top/Bottom images for those selected players.
    Each image gets its own gallery so it can be opened at full resolution.
    """
    if game_mode not in ("heatmap", "individual"):
        raise ValueError(f"Unknown game ward mode: {game_mode}")
    team_row = dict(_find_team(payload, team))
    lane_players = _select_map_players(payload, team_row, positions=(2, 4, 5),
                                       excluded_names=("Mareth",))
    supports = _select_map_players(payload, team_row, positions=(4, 5),
                                   excluded_names=("Mareth",))
    team_row["roster"] = [player.get("id") for _position, player in supports]
    key = team_row.get("key")
    patch_id = _ward_patch_id(payload)
    ward_players = [player for _position, player in lane_players]
    has_ward_data = any(
        any(wards[side][kind] for side in ("radiant", "dire") for kind in ("obs", "sen"))
        for wards in (_player_side_wards(player, key, patch_id) for player in ward_players)
    )

    components = []
    if not has_ward_data:
        components.append(_text("Not enough ward data yet."))

    files = []
    def add_gallery(images):
        for filename, data, description in images:
            item = {"media": {"url": f"attachment://{filename}"}}
            if description:
                item["description"] = description
            components.append(_media_gallery([item]))
            files.append((filename, data))

    if extra_images:
        components.append(_text("### Lane Wards"))
        add_gallery(extra_images)
    player_maps = _render_player_ward_rows(payload, team_row,
                                           heatmap=game_mode == "heatmap")
    if extra_images and player_maps:
        components.append(_text("### Game Wards"))
    if player_maps and game_mode == "heatmap":
        components.append(_text("-# Gold: observers · Cyan: sentries · Brighter: more placements"))
    add_gallery(player_maps)

    return {"components": [_container(components)], "files": files}


# --------------------------------------------------------------------------
# Recon page
# --------------------------------------------------------------------------

def _recon_monday(now):
    """Monday midnight in the bot host's local timezone, like Team Scout."""
    today = datetime.fromtimestamp(now)
    monday = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return monday.timestamp()


def _recon_rows(player, floor):
    return [m for m in player.get("matches") or []
            if (m.get("at") or 0) >= floor
            and m.get("lobby") in (0, 7) and m.get("mode") != 23]


def build_recon_page(payload, team, vs=None, hero_emoji=None, now=None,
                     medal_emoji=None):
    """Show this week's public games for the team being scouted."""
    team_row = _find_team(payload, team)
    now = datetime.now().timestamp() if now is None else now
    floor = _recon_monday(now)
    since = datetime.fromtimestamp(floor).strftime("%a %b %d").replace(" 0", " ")
    name = team_row.get("name") or team_row.get("short") or team
    nodes = [_text(f"-# \U0001F50E SCOUT RECON · {name}\n## {name} · Recon\n-# Public games since {since} · ranked by volume")]

    by_id = {p.get("id"): p for p in payload.get("players") or []}
    replaced = set(team_row.get("replaced") or [])
    players = [by_id[pid] for pid in (team_row.get("roster") or [])
               if pid in by_id and pid not in replaced][:5]
    if not players:
        nodes.append(_text("No roster is available for recon."))
        return {"components": [_container(nodes)], "files": []}

    by_player = [(p, _recon_rows(p, floor)) for p in players]
    all_rows = [m for _p, rows in by_player for m in rows]
    hero_stats = {}
    shared = {}
    for player, rows in by_player:
        for match in rows:
            hero_id = match.get("hero")
            if hero_id is not None:
                stat = hero_stats.setdefault(hero_id, {"games": 0, "wins": 0, "players": set()})
                stat["games"] += 1
                stat["wins"] += bool(match.get("win"))
                stat["players"].add(player.get("name") or "?")
            match_id = match.get("id")
            if match_id:
                shared.setdefault(match_id, []).append((player, match))
    ranking = sorted(hero_stats.items(), key=lambda item: (-item[1]["games"],
                     -len(item[1]["players"]), -item[1]["wins"]))
    wins = sum(bool(m.get("win")) for m in all_rows)
    active = sum(bool(rows) for _p, rows in by_player)
    private = [p.get("name") or "?" for p in players if p.get("private")]
    top = ranking[0] if ranking else None
    top_name = _hero_name(payload.get("heroes") or {}, top[0]) if top else "—"
    metrics = [f"**This week** {wins}–{len(all_rows)-wins} · {len(all_rows)} player-games",
               f"**Players active** {active}/{len(players)} · **Unique heroes** {len(ranking)}",
               f"**Most played** {top_name}" + (f" · {top[1]['games']}g · {', '.join(sorted(top[1]['players']))}" if top else ""),
               "**Private profiles** " + (", ".join(private) if private else "None")]
    nodes += [_separator(), _text("\n".join(metrics))]

    if ranking:
        hero_lines = ["### Most played this week"]
        for hero_id, stat in ranking[:12]:
            hero = _hero_name(payload.get("heroes") or {}, hero_id)
            token = _hero_prefix(hero_emoji, hero_id)
            hero_lines.append(f"{token}**{hero}** · {stat['games']}g · {stat['wins']}–{stat['games']-stat['wins']} · {', '.join(sorted(stat['players']))}")
        nodes += [_separator(), _text("\n".join(hero_lines))]
    else:
        nodes.append(_text("No cached public games since Monday."))

    together = [(mid, rows) for mid, rows in shared.items()
                if len({p.get("id") for p, _m in rows}) >= 2]
    together.sort(key=lambda item: -max(m.get("at") or 0 for _p, m in item[1]))
    if together:
        lines = ["### Together this week", "-# Same public match, two or more of them."]
        for mid, rows in together[:5]:
            who = " · ".join(f"{p.get('name') or '?'} {_hero_name(payload.get('heroes') or {}, m.get('hero'))} {'W' if m.get('win') else 'L'}" for p, m in rows)
            lines.append(f"[Match {mid}](https://www.opendota.com/matches/{mid}) · {who}")
        nodes += [_separator(), _text("\n".join(lines))]

    player_lines = ["### By player"]
    for player, rows in by_player:
        won = sum(bool(m.get("win")) for m in rows)
        badge = medal_prefix(player.get("rankTier"), medal_emoji)
        rank = player.get("rank") or "Unranked"
        player_heading = f"{badge}**{player.get('name') or '?'}**"
        if not badge:
            player_heading += f" · {rank}"
        player_lines.append(f"{player_heading} · {len(rows)} games · {won}–{len(rows)-won}" if rows
                            else f"{player_heading} · quiet this week")
        stats = {}
        for m in rows:
            hid = m.get("hero")
            if hid is not None:
                games, hero_wins = stats.get(hid, (0, 0))
                stats[hid] = (games + 1, hero_wins + bool(m.get("win")))
        for hid, (games, hero_wins) in sorted(stats.items(), key=lambda item: (-item[1][0], -item[1][1]))[:5]:
            player_lines.append(f"  {_hero_prefix(hero_emoji, hid)}{_hero_name(payload.get('heroes') or {}, hid)} {games}g · {hero_wins}–{games-hero_wins}")
    nodes += [_separator(), _text("\n".join(player_lines))]

    # Trim detail rows first if a roster's names or weekly hero pool are large.
    while _text_chars(nodes) > LIMIT_TEXT_TOTAL or any(
            len(n.get("content") or "") > 2000 for n in nodes if n["type"] == TYPE_TEXT_DISPLAY):
        candidates = [n for n in nodes if n["type"] == TYPE_TEXT_DISPLAY
                      and "\n" in n["content"]]
        if not candidates:
            break
        longest = max(candidates, key=lambda n: len(n["content"]))
        longest["content"] = longest["content"].rsplit("\n", 1)[0]
    return {"components": [_container(nodes)], "files": []}


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
