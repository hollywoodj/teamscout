"""Scout Bot "Briefing": build a one-page Discord embed from a Team Scout
payload. Pure function, no network, no Discord import - the caller (the bot)
owns posting.
"""

from datetime import datetime, timezone

from .bbc_source import team_key as _team_key

EMBED_COLOR = 0xE74C3C

POSITION_KEYCAPS = {n: f"{n}️⃣" for n in range(1, 6)}
UNKNOWN_KEYCAP = "\N{WHITE QUESTION MARK ORNAMENT}"

# Discord embed limits (docs.discord.com/resources/message#embed-object-limits).
LIMIT_TITLE = 256
LIMIT_DESCRIPTION = 4096
LIMIT_FIELD_NAME = 256
LIMIT_FIELD_VALUE = 1024
LIMIT_FOOTER = 2048
LIMIT_FIELDS = 25
LIMIT_TOTAL = 6000

KEY_READS_FIELD_NAME = "\N{POLICE CARS REVOLVING LIGHT} Key reads"


def _clip(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[:limit - 1].rstrip() + "…"


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


def _draft_lines(sample, heroes_map):
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

    def top3(counter):
        rows = sorted(counter.items(), key=lambda kv: -kv[1])[:3]
        return ", ".join(f"{_hero_name(heroes_map, hid)} ({n})" for hid, n in rows) or "-"

    return (
        f"Picks: {top3(picks)}",
        f"Bans: {top3(bans)}",
        f"Banned vs: {top3(banned_vs)}",
    )


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


def _hero_wl_lines(rows, heroes_map):
    """Top 3 heroes by games from official rows (hero_id, result)."""
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
    return [f"{_hero_name(heroes_map, hid)} {wins}-{games - wins}"
            for hid, (games, wins) in ranked]


def _hero_pool_wl_lines(player):
    heroes = ((player.get("heroPool") or {}).get("heroes")) or []
    lines = []
    for row in heroes[:3]:
        games = (row.get("lifetime") or {}).get("games") or 0
        wins = (row.get("lifetime") or {}).get("wins") or 0
        if not games:
            games = (row.get("recent") or {}).get("games") or 0
            wins = (row.get("recent") or {}).get("wins") or 0
        hero_id = row.get("id")
        lines.append((hero_id, games, wins))
    return lines


def _tf_bar(pct):
    if pct is None:
        return "▱" * 10
    filled = max(0, min(10, round(pct / 10)))
    return "▰" * filled + "▱" * (10 - filled)


def _build_player_field(player, key, heroes_map):
    rows = _player_team_rows(player, key)
    position = _player_position_mode(rows)
    keycap = POSITION_KEYCAPS.get(position, UNKNOWN_KEYCAP)
    rank = player.get("rank") or "Unranked"
    name = f"{keycap} {player.get('name') or 'Unknown'} · Pos {position or '?'} · {rank}"

    if not rows:
        hero_rows = _hero_pool_wl_lines(player)
        hero_line = "\U0001F9B8 pubs: " + (
            ", ".join(f"{_hero_name(heroes_map, hid)} {w}-{g - w}" for hid, g, w in hero_rows)
            or "no pub data"
        )
        value = "No official games for this team yet\n" + hero_line
        return {"name": name, "value": value, "inline": False}

    k = _avg_field(rows, "kills")
    d = _avg_field(rows, "deaths")
    a = _avg_field(rows, "assists")
    kda = _player_kda(rows)
    gpm = _avg_field(rows, "gpm")
    tf_raw = _avg_field(rows, "teamfight")
    tf_pct = None if tf_raw is None else (tf_raw * 100 if tf_raw <= 1 else tf_raw)
    bar = _tf_bar(tf_pct)

    line1 = (f"⚔️ {_fmt1(k)}/{_fmt1(d)}/{_fmt1(a)} · KDA {kda:.1f} · "
              f"\U0001F4B0 {_fmtint(gpm)} · \U0001F91D {_fmtpct(tf_pct)}% {bar}")

    obs = _avg_field(rows, "obs_placed")
    sen = _avg_field(rows, "sen_placed")
    obs_kills = _sum_field(rows, "obs_kills")
    sen_kills = _sum_field(rows, "sen_kills")
    dewards_per_game = (obs_kills + sen_kills) / len(rows) if rows else None
    stuns = _avg_field(rows, "stuns")
    stacks = _avg_field(rows, "camps_stacked")

    line2 = (f"\U0001F7E1 {_fmt1(obs)} · \U0001F535 {_fmt1(sen)} · "
              f"\U0001F9F9 {_fmt1(dewards_per_game)} · \U0001F300 {_fmt1(stuns)}s · "
              f"\U0001F392 {_fmt1(stacks)}")

    if len(rows) < 2:
        hero_rows = _hero_pool_wl_lines(player)
        line3 = "\U0001F9B8 pubs: " + (
            ", ".join(f"{_hero_name(heroes_map, hid)} {w}-{g - w}" for hid, g, w in hero_rows)
            or "no pub data"
        )
    else:
        top_heroes = _hero_wl_lines(rows, heroes_map)
        line3 = "\U0001F9B8 " + (", ".join(top_heroes) or "-")

    value = "\n".join((line1, line2, line3))
    return {"name": name, "value": value, "inline": False}


def _key_reads(payload, key, sample, roster_players):
    bullets = []

    split = _radiant_dire_split(sample)
    r_w, r_l, r_g = split["radiant"]
    d_w, d_l, d_g = split["dire"]
    if r_g >= 2 and d_g >= 2:
        r_wr = r_w / r_g * 100
        d_wr = d_w / d_g * 100
        if abs(r_wr - d_wr) >= 25:
            better = "Radiant" if r_wr > d_wr else "Dire"
            worse = "Dire" if better == "Radiant" else "Radiant"
            bullets.append((abs(r_wr - d_wr),
                             f"\U0001F7E2 Much stronger on {better} ({round(r_wr if better == 'Radiant' else d_wr)}%) "
                             f"than {worse} ({round(d_wr if better == 'Radiant' else r_wr)}%)."))

    buckets = _length_buckets(sample)
    valid = [(name, w, g) for name, (w, g) in buckets.items() if g >= 2]
    if len(valid) >= 2:
        rated = [(name, w / g * 100, g) for name, w, g in valid]
        best = max(rated, key=lambda row: row[1])
        worst = min(rated, key=lambda row: row[1])
        if best[0] != worst[0] and (best[1] - worst[1]) >= 1:
            bullets.append((best[1] - worst[1],
                             f"⏳ Best by length: {best[0]} ({round(best[1])}%), "
                             f"worst {worst[0]} ({round(worst[1])}%)."))

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
            bullets.append((share * 0.6,
                             f"\U0001F7E1 {top_name} carries {round(share)}% of the team's "
                             f"observer wards."))

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
        bullets.append((top_tf * 0.5,
                         f"\U0001F91D {top_name} is the teamfight anchor at {round(top_tf)}%."))
        low_name, low_tf = min(tf_rows, key=lambda kv: kv[1])
        if low_tf < 55 and low_name != top_name:
            bullets.append((100 - low_tf,
                             f"\U0001F91D {low_name} sits at just {round(low_tf)}% teamfight "
                             f"participation."))

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
        bullets.append((avg_deaths * 3,
                         f"\U0001F480 {name} dies the most, {avg_deaths:.1f} deaths/game."))

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
        bullets.append((per_game * 3,
                         f"\U0001F9F9 {name} leads dewarding at {per_game:.1f}/game."))

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
        if fb_pct >= 60 or fb_pct <= 30:
            bullets.append((abs(fb_pct - 45),
                             f"\U0001FA78 First blood claimed in {round(fb_pct)}% of their games."))

    bullets.sort(key=lambda row: -row[0])
    return [text for _score, text in bullets[:5]]


def build_briefing(payload, team, vs=None):
    """Build a Discord embed dict (the JSON shape the REST API takes) for a
    one-page opponent scouting briefing on `team`. `vs` defaults to the
    team's current-week matchup opponent."""
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

    strip, streak = _form_strip_and_streak(sample)
    split = _radiant_dire_split(sample)
    r_w, r_l, _r_g = split["radiant"]
    d_w, d_l, _d_g = split["dire"]
    durations = _numeric(entry.get("duration") for entry, _o, _p in sample)
    avg_duration = sum(durations) / len(durations) if durations else None

    if vs_row:
        desc_line1 = (f"Up next vs **{vs_row.get('short') or vs_row.get('name') or '?'}** "
                       f"({vs_row.get('record') or '-'})")
    else:
        desc_line1 = "No upcoming matchup posted."
    desc_line2 = f"Form {strip or '-'}  ·  {streak or '-'}"
    desc_line3 = (f"\U0001F31E Radiant {r_w}-{r_l} · \U0001F319 Dire {d_w}-{d_l} · "
                   f"⏱️ {_fmt_duration(avg_duration)} · \U0001F4C8 {games} games")
    description = "\n".join((desc_line1, desc_line2, desc_line3))

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

    fighting_value = (
        f"Kills {_fmt1(team_kills)}\n"
        f"Deaths {_fmt1(team_deaths)}\n"
        f"\U0001F91D TF {_fmtpct(tf_avg_pct)}%\n"
        f"\U0001FA78 First blood {_fmtpct(fb_pct)}%"
    )

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

    vision_value = (
        f"\U0001F7E1 Obs {_fmt1(obs_pg)}\n"
        f"\U0001F535 Sen {_fmt1(sen_pg)}\n"
        f"\U0001F9F9 Dewards {_fmt1(dewards_pg)}\n"
        f"\U0001F480 Obs lost {_fmtpct(obs_lost_pct)}%"
    )

    gpm_pg = _avg_per_game_sum(sample, "gpm")
    xpm_pg = _avg_per_game_sum(sample, "xpm")
    lane_eff = _avg_player_field(sample, "lane_eff")
    stacks_pg = _avg_per_game_sum(sample, "camps_stacked")

    economy_value = (
        f"GPM {_fmtint(gpm_pg)}\n"
        f"XPM {_fmtint(xpm_pg)}\n"
        f"\U0001F6E3️ Lane eff {_fmtpct(lane_eff)}%\n"
        f"\U0001F392 Stacks {_fmt1(stacks_pg)}"
    )

    towers_pg = _avg_per_game_sum(sample, "towers_killed")
    rosh_pg = _avg_per_game_sum(sample, "roshans_killed")
    buybacks_pg = _avg_per_game_sum(sample, "buybacks")

    objectives_value = (
        f"Towers {_fmt1(towers_pg)}\n"
        f"Rosh {_fmt1(rosh_pg)}\n"
        f"\U0001F501 Buybacks {_fmt1(buybacks_pg)}"
    )

    buckets = _length_buckets(sample)

    def bucket_line(name):
        w, g = buckets[name]
        return "-" if not g else f"{w}-{g - w}"

    length_value = (
        f"<30m {bucket_line('<30m')}\n"
        f"30-40m {bucket_line('30-40m')}\n"
        f"40m+ {bucket_line('40m+')}"
    )

    draft_lines = _draft_lines(sample, heroes_map)
    draft_value = "\n".join(draft_lines)

    fields = [
        {"name": "⚔️ Fighting", "value": fighting_value, "inline": True},
        {"name": "\U0001F441️ Vision", "value": vision_value, "inline": True},
        {"name": "\U0001F4B0 Economy", "value": economy_value, "inline": True},
        {"name": "\U0001F3F0 Objectives", "value": objectives_value, "inline": True},
        {"name": "⏳ By length", "value": length_value, "inline": True},
        {"name": "\U0001F9E0 Draft", "value": draft_value, "inline": True},
    ]

    for player in roster_players:
        fields.append(_build_player_field(player, key, heroes_map))

    bullets = _key_reads(payload, key, sample, roster_players)
    if bullets:
        fields.append({
            "name": KEY_READS_FIELD_NAME,
            "value": "\n".join(f"• {b}" for b in bullets),
            "inline": False,
        })

    standin_names = ", ".join(
        row.get("name") for row in (team_row.get("replacements") or []) if row.get("name")
    ) or "none"

    footer_text = (f"Team Scout · {games} official games · "
                    f"data {official_source.get('generated') or '-'} · "
                    f"standins: {standin_names}")

    generated_at = payload.get("generatedAt")
    timestamp = (datetime.fromtimestamp(generated_at, tz=timezone.utc).isoformat()
                 if generated_at else None)

    week = official_source.get("week")
    league = official_source.get("league") or team_row.get("league") or "League"
    author_name = f"\U0001F50E SCOUT BRIEFING · {league} · Week {week if week is not None else '?'}"

    title = (f"{team_row.get('short') or team_row.get('name') or team}  "
              f"({team_row.get('record') or '-'} · #{standing.get('rank') or '?'})")

    embed = {
        "author": {"name": _clip(author_name, LIMIT_FIELD_NAME)},
        "title": _clip(title, LIMIT_TITLE),
        "description": _clip(description, LIMIT_DESCRIPTION),
        "color": EMBED_COLOR,
        "fields": fields,
        "footer": {"text": _clip(footer_text, LIMIT_FOOTER)},
    }
    if timestamp:
        embed["timestamp"] = timestamp

    _enforce_limits(embed)
    return embed


def _embed_total_chars(embed):
    total = len(embed.get("title") or "")
    total += len(embed.get("description") or "")
    total += len((embed.get("footer") or {}).get("text") or "")
    total += len((embed.get("author") or {}).get("name") or "")
    for field in embed.get("fields") or []:
        total += len(field.get("name") or "") + len(field.get("value") or "")
    return total


def _enforce_limits(embed):
    embed["title"] = _clip(embed.get("title"), LIMIT_TITLE)
    embed["description"] = _clip(embed.get("description"), LIMIT_DESCRIPTION)
    if embed.get("footer"):
        embed["footer"]["text"] = _clip(embed["footer"].get("text"), LIMIT_FOOTER)
    fields = embed.get("fields") or []
    for field in fields:
        field["name"] = _clip(field.get("name"), LIMIT_FIELD_NAME)
        field["value"] = _clip(field.get("value"), LIMIT_FIELD_VALUE)
    if len(fields) > LIMIT_FIELDS:
        embed["fields"] = fields[:LIMIT_FIELDS]
        fields = embed["fields"]

    # Drop Key reads bullets (least notable first) if the whole embed runs
    # over the 6000-character Discord total.
    key_reads = next((f for f in fields if f.get("name") == KEY_READS_FIELD_NAME), None)
    while _embed_total_chars(embed) > LIMIT_TOTAL and key_reads is not None:
        bullets = key_reads["value"].split("\n")
        if len(bullets) <= 1:
            fields.remove(key_reads)
            embed["fields"] = fields
            key_reads = None
            break
        bullets.pop()
        key_reads["value"] = "\n".join(bullets)

    # Last-resort fallback: trim the description if still over budget.
    while _embed_total_chars(embed) > LIMIT_TOTAL and len(embed.get("description") or "") > 0:
        embed["description"] = embed["description"][:max(0, len(embed["description"]) - 200)]


def briefing_text(embed):
    """Render an embed dict as plain text for a terminal preview."""
    lines = []
    author = (embed.get("author") or {}).get("name")
    if author:
        lines.append(author)
    if embed.get("title"):
        lines.append(embed["title"])
    if embed.get("description"):
        lines.append("")
        lines.append(embed["description"])
    for field in embed.get("fields") or []:
        lines.append("")
        lines.append(f"** {field.get('name')} **")
        lines.append(field.get("value") or "")
    footer = (embed.get("footer") or {}).get("text")
    if footer:
        lines.append("")
        lines.append(footer)
    if embed.get("timestamp"):
        lines.append(embed["timestamp"])
    return "\n".join(lines)
