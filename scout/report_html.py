"""Self-contained HTML dashboard with draft-day tooling.

Single file, no external requests (works offline). Draft state persists in
localStorage keyed by season, so a mid-draft refresh keeps its state.
"""

import base64
import json
import os
from datetime import datetime
from urllib.parse import quote

from . import config, pricing
from .analysis import value_tier
from .captains import normalized_name
from .report_xlsx import db_url, ld2l_url, od_url, steam_url

# The premium algorithm's cross-language contract: the dashboard's JS reprice
# (rankPremWith / premWith below) replays these vectors at load and logs a
# console error on any drift from the Python spec in pricing.py.
_PRICING_VECTORS_PATH = os.path.join(os.path.dirname(__file__),
                                     "pricing_vectors.json")


def _pricing_vectors_json():
    """The committed golden fixture, embedded for the JS self-check. Falls back
    to generating it in-memory if the file is missing (never blocks a report)."""
    try:
        with open(_PRICING_VECTORS_PATH, encoding="utf-8") as f:
            return f.read().replace("</", "<\\/")
    except OSError:
        return json.dumps(pricing.golden_vectors()).replace("</", "<\\/")

# Dota medal badge art (base shield per tier + star overlay), downloaded once
# into the cache and embedded as data URIs so the dashboard stays offline-safe.
RANK_ICON_URL = "https://www.opendota.com/assets/images/dota2/rank_icons/"
RANK_ICON_NAMES = ([f"rank_icon_{t}" for t in range(1, 9)]
                   + [f"rank_star_{s}" for s in range(1, 6)])


def _rank_icon_uris(offline=False):
    """{name: data URI} for the medal images. Missing files are fetched from
    OpenDota and cached; with no network the cached set (possibly empty, then
    the dashboard falls back to medal text) is used."""
    icon_dir = os.path.join(config.CACHE_DIR, "rank_icons")
    os.makedirs(icon_dir, exist_ok=True)
    uris = {}
    for name in RANK_ICON_NAMES:
        path = os.path.join(icon_dir, name + ".png")
        if not os.path.exists(path):
            if offline:
                continue
            try:
                import requests
                r = requests.get(RANK_ICON_URL + name + ".png", timeout=10)
                r.raise_for_status()
                with open(path, "wb") as f:
                    f.write(r.content)
            except Exception:
                continue
        with open(path, "rb") as f:
            uris[name] = ("data:image/png;base64,"
                          + base64.b64encode(f.read()).decode("ascii"))
    return uris


def _fmt_form(form):
    if not form:
        return ""
    return f"{form['winrate']}% ({form['games']}g)"


def _captain_id_map(all_data, budgets):
    """Map budget-row names to unambiguous signup Steam32 IDs."""
    by_name = {}
    for pd in all_data:
        player = pd["player"]
        by_name.setdefault(normalized_name(player.get("name")), []).append(player)

    result = {}
    for captain in budgets or {}:
        matches = by_name.get(normalized_name(captain), [])
        if len(matches) == 1:
            result[captain] = int(matches[0]["steam32"])
    return result


def _player_record(pd):
    p, d = pd["player"], pd["data"]
    return {
        "name": p["name"],
        "id": p["steam32"],
        "mmr": p["mmr"],
        "captain": p["captain"],
        "draftable": p["draftable"],
        "vouched": p["vouched"],
        "new": bool(p.get("is_new")),
        "mmrValid": bool(p.get("mmr_valid")) or bool(p.get("mmr_screenshot")),
        "private": d["private_profile"],
        "statement": p["statement"],
        "rank": d["rank_str"],
        "rankTier": d["rank_tier"],
        "mmrCheck": d["mmr_check"],
        "skill": d["adj_skill"],
        "skillUnc": d["skill_unc"],
        "skillSrcs": d["skill_srcs"],
        "skillNote": d["skill_note"],
        "momentum": d["momentum"],
        "rust": d["rust"],
        "climb": d["mmr_climb"],
        "signupMmr": d["signup_mmr"],
        "climbing": d["climbing"],
        "falling": d["falling"],
        "gap": d["value_gap"],
        "tier": value_tier(d),
        "suspect": d["listed_suspect"],
        "worth": d["worth_cost"],
        "worthBase": d["worth_base"],
        "edge": d["edge_cost"],
        "z30": d["z30"],
        "hot": d["hot"],
        "cold": d["cold"],
        "hotColdZ": d["hot_cold_z"],
        "upN": d["up_n"],
        "upW": d["up_w"],
        "upWr": d["up_wr"],
        "farmZ": d["farm_z"],
        "farmPeers": d["farm_peers"],
        "kdaZ": d["kda_z"],
        "laneGpm": d["lane_gpm"],
        "statsN": d["stats_n"],
        "wr": d["winrate"],
        "games": d["total_matches"],
        "form30": _fmt_form(d["form30"]),
        "form90": _fmt_form(d["form90"]),
        "form30wr": d["form30"]["winrate"] if d["form30"] else None,
        "last": d["last_match_days"],
        "kda": d["avg_kda"],
        "gpm": d["avg_gpm"],
        "xpm": d["avg_xpm"],
        "pool": d["versatility"],
        "topHeroes": d["top_heroes"],
        "recentHeroes": d["recent_heroes"][:10],
        "sig": [f"{s['hero']} ({s['games']}g {s['winrate']}%)" for s in d["signature_heroes"]],
        "lobby": d["lobby_rank_str"],
        "lobbyTier": d["lobby_median_tier"],
        "punch": d["punches_above"],
        "punchGap": d["punch_gap_stars"],
        "soloPct": d["solo_pct"],
        "soloWr": d["solo_wr"],
        "partyWr": d["party_wr"],
        "lanes": d["lane_pcts"],
        "laneN": d["lane_n"],
        "server": d["server_main"],
        "serverMix": d["server_mix"],
        "serverN": d["server_n"],
        "useWr": d["use_wr"],
        "useN": d["use_n"],
        "useW": d["use_w"],
        "esportsStatus": d["esports_status"],
        "esports6moGames": d["esports_6mo_games"],
        "esports6moWr": d["esports_6mo_winrate"],
        "tox": d["toxicity_score"],
        "toxLabel": d["toxicity_label"],
        "estCost": d["est_cost"],
        "estBase": d["est_base"],
        "lastCost": d["last_cost"],
        "lastCostSeason": d["last_cost_season"],
        "lastDraftMmr": d["last_draft_mmr"],
        "wasCaptainLast": d["was_captain_last"],
        "db": db_url(p),
        "od": od_url(p),
        "ld2l": ld2l_url(p),
        "steam": steam_url(p),
    }


def generate_dashboard(players_with_data, output_file, season_label, season_id,
                       budgets=None, report_map=None, offline=False):
    records = []
    for pd in sorted(players_with_data, key=lambda x: -x["player"]["mmr"]):
        rec = _player_record(pd)
        if report_map:
            fn = report_map.get(pd["player"]["steam32"])
            rec["report"] = "scout_reports/" + quote(fn) if fn else None
        records.append(rec)
    payload = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    budgets_payload = json.dumps(budgets or {}, ensure_ascii=False).replace("</", "<\\/")
    captain_ids_payload = json.dumps(
        _captain_id_map(players_with_data, budgets or {}),
        ensure_ascii=False,
    ).replace("</", "<\\/")
    now = datetime.now()
    gen_date = f"{now.month}/{now.day}/{now.year % 100}"
    html = (TEMPLATE
            .replace("{{SEASON}}", season_label)
            .replace("{{SEASON_ID}}", str(season_id))
            .replace("{{GENERATED}}", gen_date)
            .replace("{{BUDGETS}}", budgets_payload)
            .replace("{{CAPTAIN_IDS}}", captain_ids_payload)
            .replace("{{RANKICONS}}", json.dumps(_rank_icon_uris(offline=offline)))
            .replace("{{PRICING}}", json.dumps(pricing.pricing_payload()))
            .replace("{{PRICINGVECTORS}}", _pricing_vectors_json())
            .replace("{{DATA}}", payload))
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Dashboard saved to {output_file}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LD2L {{SEASON}} Scouting Dashboard</title>
<style>
:root {
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #1baf7a; --s3: #eda100;
  --good: #006300; --warn: #b25f00; --crit: #d03b3b;
  --tint-good: rgba(12,163,12,0.12); --tint-warn: rgba(250,178,25,0.15);
  --tint-accent: rgba(42,120,214,0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #199e70; --s3: #c98500;
    --good: #0ca30c; --warn: #fab219; --crit: #e66767;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
header { padding: 20px 24px 0; display: flex; align-items: flex-start;
         justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.headbtns { display: flex; gap: 8px; flex-wrap: wrap; }
h1 { font-size: 20px; margin: 0 0 0px; }
.sub { color: var(--muted); font-size: 11px; margin-bottom: 8px; }

.tiles { display: flex; gap: 4px; flex-wrap: wrap; padding: 0 24px 4px; }
.tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
  padding: 3px 8px; min-width: 70px;
}
.tile .v { font-size: 14px; font-weight: 650; }
.tile .l { font-size: 9px; color: var(--ink2); }

.controls {
  display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  padding: 0 24px 12px; position: sticky; top: 0; z-index: 30;
  background: var(--page); padding-top: 8px;
}
.controls input[type=search], .controls select {
  background: var(--surface); color: var(--ink); border: 1px solid var(--grid);
  border-radius: 6px; padding: 6px 10px; font: inherit;
}
.chip {
  border: 1px solid var(--grid); background: var(--surface); color: var(--ink2);
  border-radius: 999px; padding: 5px 12px; cursor: pointer; font: inherit; font-size: 13px;
}
.chip.on { background: var(--tint-accent); border-color: var(--s1); color: var(--ink); font-weight: 600; }
label.ck { display: inline-flex; gap: 5px; align-items: center; color: var(--ink2); font-size: 13px; cursor: pointer; }
.count { color: var(--muted); font-size: 12px; margin-left: auto; }

/* .wrap is the scroll container (both axes) so the sticky header pins to ITS top —
   sticky-to-viewport can't work from inside an overflow-x:auto ancestor */
.wrap { margin: 0 24px 16px; overflow: auto; max-height: calc(100vh - 260px); }
/* border-collapse must stay 'separate': Chromium mis-renders sticky th in collapsed tables */
table { border-collapse: separate; border-spacing: 0; width: 100%; background: var(--surface);
        border: 1px solid var(--border); border-radius: 8px; font-size: 13px; }
thead th {
  position: sticky; top: 0; z-index: 20; background: var(--surface);
  text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .03em;
  color: var(--ink2); padding: 8px 8px; border-bottom: 2px solid var(--grid);
  cursor: pointer; white-space: nowrap; user-select: none;
}
thead th .arr { color: var(--s1); }
thead th.hashelp { text-decoration: underline dotted; text-underline-offset: 3px; text-decoration-color: var(--muted); }
thead th.hashelp:hover { color: var(--ink); text-decoration-color: var(--s1); }
tbody td { padding: 7px 8px; border-bottom: 1px solid var(--grid); vertical-align: middle; white-space: nowrap; }
tbody tr.main:hover { background: var(--tint-accent); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.pname { font-weight: 600; cursor: pointer; }
.pname:hover { text-decoration: underline; }
.repl { text-decoration: none; font-size: 12px; opacity: .5; margin-left: 3px; cursor: pointer; }
.repl:hover { opacity: 1; }
tr.drafted td { opacity: .38; }
tr.drafted .pname { text-decoration: line-through; }
tr.excluded td { opacity: .4; }
tr.excluded .pname { text-decoration: line-through; color: var(--crit); }
/* withdrawn = off the auction, still on your board: dimmed but NOT struck out
   (they're readable scouting, not a rejection) */
tr.withdrawn td { opacity: .5; }
tr.withdrawn .pname { color: var(--warn); }

/* Pinned columns: the compare-tick + player-name cells stay put while the rest
   of the table scrolls horizontally. They need opaque backgrounds (the hover
   tint is translucent, so it's layered over the surface with a gradient). */
#tbl thead th:first-child, #tbl tbody tr.main td:first-child {
  position: sticky; left: 0; background: var(--surface);
  width: 34px; min-width: 34px; max-width: 34px; box-sizing: border-box;
}
#tbl thead th:nth-child(2), #tbl tbody tr.main td:nth-child(2) {
  position: sticky; left: 34px; background: var(--surface);
  border-right: 1px solid var(--grid);
}
#tbl tbody tr.main td:nth-child(-n+2) { z-index: 15; }
#tbl thead th:nth-child(-n+2) { z-index: 25; }  /* above the other sticky headers */
#tbl tbody tr.main:hover td:nth-child(-n+2) {
  background: linear-gradient(var(--tint-accent), var(--tint-accent)) var(--surface);
}
/* drafted/excluded rows: dim the CONTENT of pinned cells, not the cell — a
   translucent cell would let the scrolled columns show through beneath it */
tr.drafted td:nth-child(-n+2), tr.excluded td:nth-child(-n+2),
tr.withdrawn td:nth-child(-n+2) { opacity: 1; }
tr.drafted td:nth-child(-n+2) > * { opacity: .38; }
tr.excluded td:nth-child(-n+2) > * { opacity: .4; }
tr.withdrawn td:nth-child(-n+2) > * { opacity: .5; }
.exbtn { width: 19px; height: 19px; border-radius: 4px; border: 1px solid var(--grid);
         background: var(--surface); color: var(--muted); font-size: 11px; font-weight: 700;
         cursor: pointer; padding: 0; line-height: 17px; text-align: center; margin-left: 4px; }
.exbtn:hover { border-color: var(--crit); color: var(--crit); }
.exbtn.on { background: var(--crit); border-color: var(--crit); color: #fff; }
.capbtn { border: 1px solid var(--grid); background: var(--surface); color: var(--muted);
          border-radius: 50%; width: 17px; height: 17px; font-size: 10px; font-weight: 700;
          cursor: pointer; padding: 0; line-height: 15px; margin-right: 5px; vertical-align: baseline; }
.capbtn:hover { border-color: var(--good); color: var(--good); }
.capbtn.on { background: var(--good); border-color: var(--good); color: #fff; }
.outbtn { border: 1px solid var(--grid); background: var(--surface); color: var(--muted);
          border-radius: 50%; width: 17px; height: 17px; font-size: 10px; font-weight: 700;
          cursor: pointer; padding: 0; line-height: 15px; margin-right: 5px; vertical-align: baseline; }
.outbtn:hover { border-color: var(--warn); color: var(--warn); }
.outbtn.on { background: var(--warn); border-color: var(--warn); color: #fff; }
.marks { display: inline-flex; gap: 3px; }
.markbtn { width: 19px; height: 19px; border-radius: 4px; border: 1px solid var(--grid);
           background: var(--surface); color: var(--muted); font-size: 11px; font-weight: 700;
           cursor: pointer; padding: 0; line-height: 17px; text-align: center; }
.markbtn:hover { border-color: var(--ink2); color: var(--ink2); }
.markbtn.tgt.on { background: var(--s1);   border-color: var(--s1);   color: #fff; }
.markbtn.app.on { background: var(--good); border-color: var(--good); color: #fff; }
.markbtn.sup.on { background: var(--s2);   border-color: var(--s2);   color: #fff; }
.notein { width: 130px; background: var(--surface); color: var(--ink); border: 1px solid var(--grid);
          border-radius: 5px; padding: 2px 6px; font: inherit; font-size: 12px; }
.notein::placeholder { color: var(--muted); }
.curmmrin { width: 62px; background: var(--surface); color: var(--ink); border: 1px solid var(--grid);
            border-radius: 5px; padding: 2px 5px; font: inherit; font-size: 12px; text-align: right; }
.curmmrin::placeholder { color: var(--muted); }
.bidin { width: 44px; background: var(--surface); color: var(--ink); border: 1px solid var(--grid);
         border-radius: 5px; padding: 2px 5px; font: inherit; font-size: 12px; text-align: right; }
.bidin::placeholder { color: var(--muted); }
.b-priv { background: var(--tint-warn); color: var(--warn); }
.exline { text-decoration: line-through; color: var(--crit); opacity: .6; }
.rolecircles { display: inline-flex; gap: 3px; }
.rolecirc { width: 19px; height: 19px; border-radius: 50%; border: 1px solid var(--grid);
  background: var(--surface); color: var(--muted); font-size: 10px; font-weight: 600;
  cursor: pointer; padding: 0; line-height: 17px; text-align: center; }
.rolecirc:hover { border-color: var(--s1); }
.rolecirc.on { background: var(--s1); border-color: var(--s1); color: #fff; }
#budgetbar { margin-bottom: 10px; }
.bchip { display: inline-block; border: 1px solid var(--grid); background: var(--surface);
         border-radius: 6px; padding: 4px 9px; margin: 0 6px 6px 0; font-size: 12.5px; color: var(--ink2); }
.bchip b { color: var(--ink); }
.bchip.over b { color: var(--crit); }

.badge {
  display: inline-block; font-size: 10px; font-weight: 700; border-radius: 4px;
  padding: 1px 5px; margin-left: 5px; vertical-align: 1px; border: 1px solid var(--border);
}
.b-cap { background: var(--tint-good); color: var(--good); }
.b-out { background: var(--tint-warn); color: var(--warn); }
.b-capm { background: var(--tint-warn); color: var(--warn); }
.b-new { background: var(--tint-accent); color: var(--s1); }
.b-v { color: var(--muted); }

.lane { display: inline-flex; align-items: center; gap: 6px; }
.lanebar { display: inline-flex; width: 72px; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; background: transparent; }
.lanebar i { height: 100%; }
.lanebar .l1 { background: var(--s1); } .lanebar .l2 { background: var(--s2); } .lanebar .l3 { background: var(--s3); }
.lanetxt { color: var(--ink2); font-size: 11px; }
.srvchip { display: inline-block; border: 1px solid var(--grid); border-radius: 4px;
  padding: 1px 6px; font-size: 11px; font-weight: 600; color: var(--ink2); background: var(--surface); }

.medal { position: relative; display: inline-block; width: 28px; height: 28px; vertical-align: middle; }
.medal img { position: absolute; inset: 0; width: 100%; height: 100%; }

.good { color: var(--good); font-weight: 600; }
.bad { color: var(--crit); }
.warn { color: var(--warn); font-weight: 600; }
.dim { color: var(--muted); }
.tierchip { display: inline-block; border: 1px solid var(--grid); border-radius: 4px;
            padding: 1px 6px; font-size: 11px; font-weight: 600; }
.t-S, .t-A { background: var(--tint-good); color: var(--good); border-color: var(--good); }
.t-B { color: var(--good); }
.t-C { color: var(--ink2); }
.t-D { color: var(--warn); }
.t-E, .t-F { background: var(--tint-warn); color: var(--crit); border-color: var(--crit); }
.t-U { background: var(--tint-warn); color: var(--warn); }
a { color: var(--s1); text-decoration: none; } a:hover { text-decoration: underline; }

tr.detail td { background: var(--page); white-space: normal; padding: 10px 16px; font-size: 12.5px; }
.dgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 8px 24px; }
.dgrid h4 { margin: 0 0 3px; font-size: 11px; text-transform: uppercase; color: var(--muted); }
.dgrid p { margin: 0; color: var(--ink2); }

#bestpanel { display: none; padding: 0 24px 14px; }
#bestpanel.show { display: block; }
.bestgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.bestcol { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.bestcol h3 { margin: 0 0 6px; font-size: 12px; text-transform: uppercase; color: var(--ink2); }
.bestcol div { display: flex; justify-content: space-between; padding: 2px 0; font-size: 13px; }
.bestcol .m { color: var(--muted); font-variant-numeric: tabular-nums; }

#teamspanel { display: none; padding: 0 24px 14px; }
#teamspanel.show { display: block; }
.teamgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.teamcard { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.teamcard.over { border-color: var(--crit); }
.teamcard h3 { margin: 0 0 1px; font-size: 13px; display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.teamcard .bud { font-size: 12px; font-weight: 600; white-space: nowrap; color: var(--ink2); }
.teamcard .bud.over { color: var(--crit); }
.teamcard .cnt { color: var(--muted); font-size: 11px; margin-bottom: 5px; }
.teamcard .prow { display: flex; justify-content: space-between; gap: 8px; padding: 3px 0; font-size: 12.5px; border-top: 1px solid var(--grid); }
.teamcard .prow .pp { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.teamcard .empty { color: var(--muted); font-size: 12px; padding: 4px 0; border-top: 1px solid var(--grid); }
.teamcard .teamneeds { margin-top: 8px; padding-top: 7px; border-top: 1px solid var(--grid);
  font-size: 12px; color: var(--warn); display: flex; align-items: center; gap: 6px; }
.teamcard .teamneeds.full { color: var(--good); }
.teamcard .teamneeds .rolecircles { gap: 3px; }
.teamcard .needcirc { width: 19px; height: 19px; border-radius: 50%; font-size: 10px;
  font-weight: 600; line-height: 19px; text-align: center; background: var(--warn);
  border: 1px solid var(--warn); color: #fff; }
.moneybar { height: 11px; border-radius: 6px; overflow: hidden; margin: 10px 0 6px;
  background: var(--tint-good); border: 1px solid var(--grid); }
.moneybar i.spent { display: block; height: 100%; background: var(--s1); }
.moneybar.over i.spent { background: var(--crit); }
.moneyrow { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap;
  align-items: center; font-size: 12px; color: var(--ink2); }
.moneyrow b { color: var(--ink); }
.moneyrow .mleft.over b { color: var(--crit); }
.budgetin { width: 60px; background: var(--surface); color: var(--ink); border: 1px solid var(--grid);
  border-radius: 5px; padding: 1px 5px; font: inherit; font-size: 12px; }
.teamcard h3 .budgetin { font-weight: 400; }
.teamcard .poscov { margin-top: 7px; display: flex; gap: 3px; }
.poschip { font-size: 10px; border-radius: 3px; padding: 1px 5px; border: 1px solid var(--grid); color: var(--muted); }
.poschip.on { background: var(--tint-accent); color: var(--ink); border-color: var(--s1); font-weight: 600; }
.teamcard.unassigned { border-style: dashed; }
.teamcard .teamtargets { margin-top: 8px; padding-top: 7px; border-top: 1px solid var(--grid); }
.teamtargets .tt-head { font-size: 11px; text-transform: uppercase; letter-spacing: .03em;
  color: var(--ink2); margin-bottom: 5px; }
.tt-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 5px; }
.tt-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px;
  background: var(--tint-accent); border: 1px solid var(--s1); color: var(--ink);
  border-radius: 10px; padding: 1px 3px 1px 8px; }
.tt-chip.taken { background: var(--tint-warn); border-color: var(--warn); color: var(--warn); }
.tt-chip.taken .nm { text-decoration: line-through; }
.tt-chip .pp { color: var(--muted); font-variant-numeric: tabular-nums; }
.tt-x { cursor: pointer; border: none; background: none; color: var(--muted);
  font-size: 13px; line-height: 1; padding: 0 2px; }
.tt-x:hover { color: var(--crit); }
.tt-add { width: 100%; box-sizing: border-box; background: var(--surface); color: var(--ink);
  border: 1px solid var(--grid); border-radius: 5px; padding: 3px 6px; font: inherit; font-size: 12px; }
.tt-add::placeholder { color: var(--muted); }

#myteampanel { display: none; padding: 0 24px 14px; }
#myteampanel.show { display: block; }
.mt-wrap { display: grid; grid-template-columns: minmax(280px, 380px) 1fr; gap: 16px; align-items: start; }
@media (max-width: 760px){ .mt-wrap { grid-template-columns: 1fr; } }
.mt-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.mt-card h3 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; color: var(--ink2); }
.mt-member { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.mt-member input.nm { flex: 1; min-width: 60px; background: var(--surface); color: var(--ink);
  border: 1px solid var(--grid); border-radius: 5px; padding: 3px 6px; font: inherit; font-size: 12.5px; }
.mt-roles { display: inline-flex; gap: 2px; }
.rchip { font-size: 11px; border-radius: 4px; padding: 2px 6px; border: 1px solid var(--grid);
  background: var(--surface); color: var(--muted); cursor: pointer; user-select: none; }
.rchip.on { background: var(--tint-accent); border-color: var(--s1); color: var(--ink); font-weight: 700; }
.mt-x { cursor: pointer; color: var(--muted); border: none; background: none; font-size: 16px; line-height: 1; padding: 0 2px; }
.mt-x:hover { color: var(--crit); }
.mt-add { margin-top: 4px; }
.covstrip { display: flex; gap: 6px; margin: 2px 0 12px; flex-wrap: wrap; }
.covcell { flex: 1; min-width: 90px; border: 1px solid var(--grid); border-radius: 6px; padding: 6px 8px; }
.covcell .pos { font-size: 10px; text-transform: uppercase; letter-spacing: .03em; color: var(--muted); }
.covcell .who { font-size: 12.5px; font-weight: 600; margin-top: 1px; }
.covcell.need { border-color: var(--warn); background: var(--tint-warn); }
.covcell.need .who { color: var(--warn); }
.covcell.cov { border-color: var(--good); }
.covcell.cov .who { color: var(--good); }
.tgt-need { margin-bottom: 12px; }
.tgt-need h4 { margin: 0 0 4px; font-size: 12px; color: var(--s1); }
.tgt-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; padding: 2px 0; border-top: 1px solid var(--grid); }
.tgt-row .r { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.mt-hint { color: var(--muted); font-size: 11px; margin-top: 6px; }
.onetrick { color: var(--warn); font-size: 10px; border: 1px solid var(--warn); border-radius: 3px; padding: 0 3px; margin-left: 4px; }

#tray {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 40;
  background: var(--surface); border-top: 1px solid var(--grid);
  padding: 10px 24px; display: none; gap: 10px; align-items: center;
}
#tray.show { display: flex; }
#tray .names { color: var(--ink2); font-size: 13px; }

#cmp {
  position: fixed; inset: 4vh 4vw; z-index: 50; overflow: auto; display: none;
  background: var(--surface); border: 1px solid var(--grid); border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0,0,0,.35); padding: 18px 22px;
}
#cmp.show { display: block; }
#cmp table { border: none; }
#cmp td, #cmp th { white-space: normal; }
#cmp th { position: static; }
#cmp td:first-child { color: var(--ink2); font-weight: 600; }

#method {
  position: fixed; inset: 4vh 4vw; z-index: 50; overflow: auto; display: none;
  background: var(--surface); border: 1px solid var(--grid); border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0,0,0,.35); padding: 0 26px 26px;
}
#method.show { display: block; }
#method .doc { max-width: 820px; margin: 0 auto; }
#method .mhead { position: sticky; top: 0; display: flex; justify-content: space-between;
  align-items: center; background: var(--surface); padding: 18px 0 10px; margin-bottom: 4px;
  border-bottom: 1px solid var(--grid); }
#method h2 { font-size: 18px; margin: 0; }
#method h3 { font-size: 14px; margin: 22px 0 6px; color: var(--s1); }
#method p, #method li { color: var(--ink2); font-size: 13.5px; line-height: 1.62; }
#method .lead { font-size: 14.5px; color: var(--ink); margin: 14px 0 4px; }
#method ul { margin: 4px 0; padding-left: 18px; }
#method li { margin: 4px 0; }
#method b { color: var(--ink); }
#method i { color: var(--ink2); }
#method .formula { font-family: ui-monospace, "Cascadia Code", monospace; background: var(--page);
  border: 1px solid var(--grid); border-radius: 5px; padding: 1px 5px; font-size: 12px; color: var(--ink); }

/* live draft feed (only when served via --live) */
.livechip.ok { color: #2ecc71; border-color: #2ecc71; }
.livechip.bad { color: var(--ink2); }
#nomban { display: none; position: sticky; top: 0; z-index: 40;
  padding: 9px 16px; font-size: 13.5px; background: var(--surface);
  border-bottom: 2px solid #e67e22; box-shadow: 0 3px 10px rgba(0,0,0,.25); }
#nomban.show { display: block; }
#nomban b { color: #e67e22; }
tr.onblock td { background: rgba(230,126,34,.14) !important; }
tr.onblock .pname { font-weight: 700; }

/* Mock-draft controls — these now live INSIDE the header draft ticker (see
   #drafticker.mock below), which grows into a full auction console when the page
   is served by --mock. The dashboard is otherwise identical to --live. */
#drafticker .mb-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
#drafticker .mb-title { font-weight: 700; color: #a371f7; white-space: nowrap; font-size: 15px; }
#drafticker .mb-lbl { font-size: 12px; color: var(--ink2); }
#drafticker select, #drafticker input { font: inherit; color: var(--ink);
  background: var(--surface); border: 1px solid var(--grid); border-radius: 6px;
  padding: 5px 8px; }
#drafticker .mb-status { color: var(--ink2); font-size: 13px; }
#drafticker .mb-status b { color: var(--ink); }
#drafticker #mb-start { border-color: #a371f7; color: #a371f7; font-weight: 700; }
#drafticker #mb-pause { border-color: #e0a938; color: #e0a938; font-weight: 700; }
#drafticker #mb-pause.resume { border-color: #2ecc71; color: #2ecc71; }
#drafticker .mb-paused { color: #e0a938; font-weight: 700; }
#drafticker #mb-speed.ff { border-color: #2ecc71; color: #2ecc71; font-weight: 700; }
#drafticker .mb-ff { color: #2ecc71; font-weight: 700; }
#drafticker .mb-auction { min-height: 0; }
#drafticker .mb-auction.live { padding: 10px 14px; border-radius: 9px;
  background: rgba(163,113,247,.10); border: 1px solid rgba(163,113,247,.35); }
#drafticker .mb-onblock { font-size: 16px; }
#drafticker .mb-onblock b { color: var(--ink); }
#drafticker .mb-amt { font-size: 26px; font-weight: 800; color: #a371f7;
  font-variant-numeric: tabular-nums; }
#drafticker .mb-cd { font-size: 17px; font-weight: 700; color: #a371f7; }
#drafticker .mb-cd b { font-size: 30px; font-variant-numeric: tabular-nums; }
#drafticker .mb-time { font-size: 15px; font-variant-numeric: tabular-nums;
  color: var(--ink2); white-space: nowrap; }
#drafticker .mb-time b { font-size: 18px; }
#drafticker button.mb-bid { border-color: #a371f7; font-weight: 700;
  padding: 6px 12px; font-size: 14px; }
#drafticker button:disabled { opacity: .4; cursor: not-allowed; }
#drafticker .mb-win { color: #2ecc71; font-weight: 700; }
#drafticker .mb-last { margin-left: auto; color: var(--ink2); font-size: 13px;
  white-space: nowrap; }
#drafticker .mb-last b { color: var(--ink); }
#drafticker .mb-last .mb-price { color: #2ecc71; font-weight: 700; }
#feedpanel { display: none; position: fixed; right: 14px; bottom: 64px; z-index: 45;
  width: 330px; max-height: 46vh; overflow: hidden; flex-direction: column;
  background: var(--surface); border: 1px solid var(--grid); border-radius: 10px;
  box-shadow: 0 10px 30px rgba(0,0,0,.35); }
#feedpanel.show { display: flex; }
#feedpanel .fhead { display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; font-weight: 600; font-size: 13px; border-bottom: 1px solid var(--grid); }
#feedpanel .fhead button { background: none; border: none; color: var(--ink2);
  cursor: pointer; font-size: 15px; }
#feedlist { overflow-y: auto; padding: 6px 12px 10px; font-size: 12.5px; line-height: 1.5; }
#feedlist .fev { padding: 3px 0; border-bottom: 1px dotted var(--grid); }
#feedlist .fev .ft { color: var(--ink2); font-size: 11px; margin-right: 6px;
  font-family: ui-monospace, "Cascadia Code", monospace; }
#feedlist .fev.sold b { color: #2ecc71; }
#feedlist .fev.nom b { color: #e67e22; }

/* persistent draft ticker in the header — the live socket's glanceable strip
   (only revealed when the page is served via --live) */
#drafticker { display: none; flex: 1 1 300px; min-width: 240px; max-width: 720px;
  flex-direction: column; gap: 8px; padding: 6px 14px;
  border-radius: 10px; background: var(--surface); border: 1px solid var(--grid);
  overflow: hidden; }
#drafticker.on { display: flex; }
#drafticker .dt-head { display: flex; align-items: center; gap: 12px; min-width: 0;
  height: 42px; }
#drafticker.live { border-color: #e67e22;
  box-shadow: 0 0 0 1px rgba(230,126,34,.30), 0 4px 14px rgba(230,126,34,.16); }
/* --mock: the ticker becomes the full-width auction console. The mock control
   row (seat / start / pause / status) and the interactive bid row live inside it;
   the compact live glance (#dt-main) is hidden and its job is taken over here. */
#drafticker .dt-mock { display: none; }
#drafticker #mb-auction { display: none; }
#drafticker.mock { order: 9; flex-basis: 100%; max-width: none; padding: 10px 16px;
  border-color: #a371f7;
  box-shadow: 0 0 0 1px rgba(163,113,247,.30), 0 4px 16px rgba(163,113,247,.18); }
#drafticker.mock .dt-head { height: auto; flex-wrap: wrap; }
#drafticker.mock .dt-main { display: none; }
#drafticker.mock .dt-mock { display: flex; align-items: center; gap: 10px;
  flex-wrap: wrap; flex: 1; }
#drafticker.mock #mb-auction { display: flex; }
#drafticker .dt-lamp { display: flex; align-items: center; gap: 6px; white-space: nowrap;
  font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  color: var(--ink2); }
#drafticker.live .dt-lamp { color: #e67e22; }
#drafticker .dt-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted);
  flex: none; }
#drafticker[data-state=ok] .dt-dot { background: #2ecc71; }
#drafticker[data-state=block] .dt-dot { background: #e67e22; animation: dtpulse 1s infinite; }
@keyframes dtpulse { 0%,100% { opacity: 1; } 50% { opacity: .3; } }
#drafticker .dt-main { display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
  font-size: 13px; color: var(--ink); min-width: 0; }
#drafticker .dt-main > * + * { border-left: 1px solid var(--grid); padding-left: 20px; }
/* each data cell is a label stacked over its value */
#drafticker .dt-stack { display: flex; flex-direction: column; align-items: flex-start;
  line-height: 1.15; gap: 2px; }
#drafticker .dt-lbl { font-size: 9px; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: var(--ink2); white-space: nowrap; }
#drafticker .dt-bidrow { display: inline-flex; align-items: baseline; gap: 10px; }
#drafticker .dt-amt { font-size: 21px; font-weight: 800; color: var(--ink); letter-spacing: 0; }
#drafticker .dt-name { font-size: 16px; font-weight: 650; color: var(--ink); }
#drafticker .dt-capname { font-size: 15px; font-weight: 700; color: #e67e22; }
#drafticker .dt-time { font-variant-numeric: tabular-nums; white-space: nowrap; }
#drafticker #dt-timer b { font-size: 16px; }
#drafticker .dt-idle { color: var(--ink2); }
#drafticker .dt-idle b { color: var(--ink); }
</style>
</head>
<body>
<header>
  <div>
    <h1>LD2L {{SEASON}} Scouting Dashboard</h1>
    <div class="sub">Last ran: {{GENERATED}}</div>
  </div>
  <div id="drafticker" data-state="bad">
    <div class="dt-head">
      <div class="dt-lamp"><span class="dt-dot"></span><span id="dt-state">connecting…</span></div>
      <div class="dt-main" id="dt-main"></div>
      <div class="dt-mock" id="dt-mock">
        <span class="mb-title">🎲 Mock draft</span>
        <label class="mb-lbl">Seat <select id="mb-seat"></select></label>
        <button class="chip" id="mb-start">▶ Start</button>
        <button class="chip" id="mb-pause" style="display:none">⏸ Pause</button>
        <label class="mb-lbl" title="Fast-forward the auction. Drops back to 1x on its own the moment a player you haven't cut (✕) is nominated — or when it's your turn to nominate.">⏩ <select id="mb-speed"></select></label>
        <button class="chip" id="mb-reset">Reset</button>
        <span class="mb-status" id="mb-status"></span>
      </div>
    </div>
    <div class="mb-row mb-auction" id="mb-auction"></div>
  </div>
  <div class="headbtns">
    <select class="chip" id="mycap" style="display:none"
            title="Which captain are you? Powers the bid assistant: remaining budget + roster slots"></select>
    <span class="chip livechip" id="livechip" style="display:none"
          title="Live draft feed — the local server polls the ld2l.org draft page (read-only)"></span>
    <button class="chip" id="feedbtn" style="display:none"
            title="Running ticker of nominations, bids and picks">Feed</button>
    <button class="chip" id="methodmode" title="How every number is calculated">Methodology</button>
    <button class="chip" id="clearroles" title="Blank every player's role circles so you can set them all by hand">Clear roles</button>
    <button class="chip" id="exportcaps" title="Save the captains you've marked (with their budgets) to captains.json for the --mock draft. Put the downloaded file next to ld2l_scout.py.">⬇ Captains → mock</button>
    <button class="chip" id="opendb" title="Open the Dotabuff of every player you haven't cut (✕) or removed from the draft (⊘), excluding captains, each in its own tab in this window. Requires pop-ups allowed for this page.">🔗 Dotabuff all</button>
    <button class="chip" id="resetdraft" title="Clear all drafted marks">Reset draft</button>
  </div>
</header>

<div id="nomban"></div>

<div id="feedpanel">
  <div class="fhead"><span>📡 Live draft feed</span><button id="feedclose" title="Close">×</button></div>
  <div id="feedlist"></div>
</div>

<div class="tiles" id="tiles"></div>

<div class="controls">
  <input type="search" id="q" placeholder="Search name / statement…">
  <span id="poschips"></span>
  <button class="chip" id="fitneeds" title="Show only players who can fill a position your roster still needs">🎯 Fit my needs</button>
  <label class="ck"><input type="checkbox" id="fcaptains"> hide captains</label>
  <label class="ck"><input type="checkbox" id="fdrafted"> hide drafted</label>
  <label class="ck"><input type="checkbox" id="fexcluded"> hide cut <span id="exct"></span></label>
  <label class="ck" title="Players you've taken off the draft (⊘) — they stay scouted here, just out of the auction"><input type="checkbox" id="fwithdrawn"> hide removed <span id="outct"></span></label>
  <button class="chip" id="draftmode">Roles Board</button>
  <button class="chip" id="teamsmode">Teams</button>
  <button class="chip" id="myteammode">My Team</button>
  <span class="count" id="count"></span>
</div>

<div id="bestpanel"><div id="budgetbar"></div><div class="bestgrid" id="bestgrid"></div></div>
<div id="teamspanel"><datalist id="playerlist"></datalist><div class="teamgrid" id="teamgrid"></div></div>
<div id="myteampanel"><div class="mt-wrap">
  <div class="mt-card">
    <h3>My roster</h3>
    <div id="mt-members"></div>
    <button class="chip mt-add" id="mt-add">+ Add player</button>
    <div class="mt-hint">Set each player's role(s) — pick several for a flex player. These roles (yours to
      set, since sheet prefs are unreliable) drive the needs and targets on the right.</div>
  </div>
  <div class="mt-card">
    <h3>Coverage &amp; targets</h3>
    <div class="covstrip" id="mt-cov"></div>
    <div id="mt-tgts"></div>
  </div>
</div></div>

<div class="wrap"><table id="tbl">
  <thead><tr id="hdr"></tr></thead>
  <tbody id="rows"></tbody>
</table></div>

<div id="tray">
  <strong>Compare:</strong> <span class="names" id="traynames"></span>
  <button class="chip" id="docmp">Open comparison</button>
  <button class="chip" id="clearcmp">Clear</button>
</div>
<div id="cmp"></div>

<div id="method"><div class="doc">
  <div class="mhead"><h2>How the numbers are made — methodology &amp; philosophy</h2>
    <button class="chip" id="methodclose">Close (Esc)</button></div>

  <p class="lead">Every draft is a market, and edges come from <b>disagreements between what a
  player actually is and what they're listed or priced at</b>. So this tool estimates true skill
  from behaviour, independently of the listed MMR, and then hunts for the gaps. Nothing here is a
  verdict — each number is a starting anchor with an error bar.</p>

  <h3>Principle 1 — Estimate skill without looking at the listing</h3>
  <p>To judge whether a listed MMR is right, the skill estimate can't be built from that same
  number. <b>Plays Like</b> uses only behavioural evidence:</p>
  <ul>
    <li><b>Medal-implied MMR</b> — the player's rank tier, at roughly
      <span class="formula">154 MMR per star</span>.</li>
    <li><b>Lobby median</b> — the median skill of the games they <i>actually queue into</i> over
      the last ~200 matches / 6 months (ranked lobbies preferred). The bracket you keep landing in
      is a hard-to-fake read on your level.</li>
  </ul>
  <p>OpenDota's own <span class="formula">computed_mmr</span> is deliberately excluded: for this
  player pool it squashes everyone from Guardian to Divine into ~3700–4300 and correlates only about
  0.5 with everything else, so it adds noise, not signal.</p>

  <h3>Principle 2 — Weight every source by how much you can trust it</h3>
  <p>The two inputs are combined by <b>inverse-variance weighting</b>: the more reliable source
  (more games, less scatter) gets more say, and the result carries an uncertainty band — the
  <span class="formula">±</span> beside Plays Like. A wide band means "we're guessing"; a tight one
  means the signals agree. When the two sources <i>disagree by a lot</i>, the tie-break is
  deliberately asymmetric:</p>
  <ul>
    <li><b>Lobbies far above the medal → trust the lobbies.</b> Medals decay when you stop playing
      ranked; the lobbies you're winning right now don't.</li>
    <li><b>Medal far above the lobbies → trust the medal more.</b> You're probably queuing down in
      parties, which drags the lobby average below your real level.</li>
  </ul>

  <h3>Principle 3 — Adjust for form, but only when it's real</h3>
  <p><b>Momentum</b> nudges the estimate up or down for a hot or cold streak — but only once the
  last 30 days clears a statistical bar. A 58% run over 20 games <i>feels</i> hot; it sits inside
  coin-flip range (z ≈ 0.7) and moves nothing. <b>Rust</b> applies a decay for inactivity, because a
  number from three months ago is a claim about the past, not the present.</p>

  <h3>Watch the listing move — the Climb column</h3>
  <p>The <b>Climb</b> column tracks something simple and concrete: how much a player's
  <i>listed</i> MMR has moved since they first signed up. The number they put on the sheet at signup
  is captured once and held fixed; Climb is today's listing minus that baseline. So when an admin
  re-rates someone, or a player updates their own MMR before the draft, it shows as ▲ +N or ▼ −N —
  otherwise it reads "—" (unchanged). It's a freshness signal, not a skill estimate: it tells you
  whether the listed number in front of you is still the one they signed up with. Read it alongside
  <b>Gap</b> — a big Gap with no Climb is a player whose listing hasn't been touched, exactly the
  kind other captains may not have re-scouted. (Because the baseline is captured the first time this
  tool sees a player, Climb starts at "—" for everyone and fills in as listings change through the
  signup and re-rate period.)</p>

  <h3>The payoff — Gap and Value Tier</h3>
  <p><span class="formula">Gap = Plays Like − Listed MMR</span>. Positive means they play above their
  price. <b>Value Tier</b> grades that gap from S (big steal) to F (big reach). A trailing
  <span class="formula">?</span> means the gap is smaller than the estimate's own uncertainty — a
  lead worth investigating, not a conclusion. This gap <i>is</i> the tool: it points at every place
  the listing and the behaviour disagree.</p>

  <h3>Unrated ≠ bargain</h3>
  <p>Some players sign up at the 1000-MMR floor while queuing in Archon+ lobbies with thousands of
  games. That isn't a steal — it's an <b>unpriced</b> player who will be re-rated before the draft.
  Those are flagged <span class="formula">★ Unrated</span> instead of being dressed up as value, so a
  placeholder number never reads as the deal of the draft.</p>

  <h3>Pricing — Est$, Worth$, Edge$</h3>
  <p>Past auctions are the only ground truth for what players actually cost.</p>
  <ul>
    <li><b>Est$</b> — expected winning bid at the <i>listed</i> MMR: the median price of the 7
      nearest-MMR players across the last 4 auction seasons, normalized to this season's auction
      base, plus a <b>board-position premium</b> (below).</li>
    <li><b>Worth$</b> — the same model applied to the <i>true-skill</i> estimate.</li>
    <li><b>Edge$ = Worth − Est</b> — the surplus you capture if they go for their listing-implied
      price but play at their real level.</li>
  </ul>
  <p>Why a plain nearest-neighbour median rather than something fancier? It was leave-one-out
  cross-validated against isotonic regression and percentile-normalized models — all of them tie at
  an error of about ±36 draft-dollars, which is simply the noise floor of real human bidding. When
  models tie, the simplest and most transparent one wins.</p>
  <p><b>The scarcity premium.</b> MMR-vs-history alone systematically lowballs the top of the
  board: in all 4 tracked auctions the #1 player went for 215–257 on a 500 base — a bidding war on
  the known quantities worth ~+60 over the raw model — while picks past ~rank 17 went for
  <i>less</i> than their MMR implied as budgets dried up (the late-round steals). So the estimate
  is shifted by where the player ranks in <i>this</i> pool: roughly +80 for the top slot, fading
  to zero around rank 14, and about −15 deep in the tail. Calibrated by comparing the k-th
  priciest actual sale against the k-th priciest raw estimate in each past season.</p>
  <p>Scarcity is also positional: every captain needs all five positions filled, so the best
  support in the pool never goes for a steal even when their raw MMR rank says they should. The
  <b>top 3 available at each position</b> carry a premium of their own (+40 / +25 / +12 —
  anchored to what the calibrated curve pays at overall slots 5, 8 and 14, since past drafts
  record no position labels to calibrate against directly). A player gets the <i>larger</i> of
  the overall and positional premiums, never both, so nothing double-counts. Positions come from
  the Roles circles — measured lanes seed the cores, but supports can't be read from lane data,
  so <b>hand-set the 4/5 circles</b> to price the support market properly. The whole premium
  recomputes live as you mark captains, edit roles, or correct MMRs.</p>
  <p>Practical read: budget honestly for the elite names and the best player at every position,
  and expect your value picks to come from the mid-board on down.</p>

  <h3>Outliers, stated honestly — the z-score discipline</h3>
  <p>The governing rule: <b>call something unusual only when it's unlikely to be luck.</b> Raw
  thresholds ("&gt;55% win rate", "&gt;600 GPM") fire constantly on small samples. Every outlier flag
  here is a z-score — distance from the expected value in standard deviations — so sample size is
  baked in.</p>
  <ul>
    <li><b>Hot / cold (▲▼)</b> — a binomial z-test on the 30-day record, not just a winning week.
      The bar rises with the size of the pool: testing every player means a fixed |z| ≥ 1.65 cutoff
      would light up ~10 badges per 100 signups on luck alone, so it is corrected (Bonferroni) to
      hold the odds of <i>any</i> false badge on the board at ~10%. Hover a badge for the live bar.</li>
    <li><b>Farm &amp; KDA vs peers</b> — robust z-scores using median/MAD (so one stomp or one feed
      can't distort the scale), measured against players within ±700 listed MMR. The question is
      "unusual <i>for their bracket</i>," not in the abstract.</li>
    <li><b>Holds up a bracket</b> — win rate in lobbies 2+ stars above their own medal, reported with
      a Wilson lower bound so a 3–1 sample can't masquerade as proof.</li>
    <li><b>Punch</b> — the raw behavioural signal: how many stars their median lobby sits above their
      own medal. It reads against the <i>medal</i>, so a decayed medal inflates it — Gap is the
      price-relevant version.</li>
  </ul>

  <h3>What this can't tell you</h3>
  <p>None of this measures role fit, hero pool versus the current meta, team synergy, communication,
  attitude, or whether someone will even show up. It narrows the field and prices it. Captains'
  reads, package deals, and draft-day strategy set the real number. <b>Treat every figure as an
  anchor with an error bar — a better place to start a decision, never the decision itself.</b></p>
</div></div>

<script>
const DATA = {{DATA}};
const BUDGETS = {{BUDGETS}};
const CAPTAIN_IDS = {{CAPTAIN_IDS}};
const RANK_ICONS = {{RANKICONS}};
const SEASON = "{{SEASON_ID}}";
const LSKEY = "ld2l-draft2-s" + SEASON;

// Mock-draft mode (server includes a `mock` object in /live/state). The mock
// engine is then the single source of truth: budgets and drafted state mirror
// it exactly, and NOTHING is persisted — practice runs must not pollute the
// hand-curated draft-day state in localStorage.
let MOCKMODE = false, MOCKBUDGETS = {}, MOCKCAPTAINS = new Set(),
    mockDraftSig = null;

// draft state: {playerId: {p: pricePaid|null, t: winningCaptain|""}}
let draftInfo = JSON.parse(localStorage.getItem(LSKEY) || "{}");
// migrate v1 state (plain array of drafted ids)
JSON.parse(localStorage.getItem("ld2l-drafted-s" + SEASON) || "[]").forEach(id=>{
  if (!(id in draftInfo)) draftInfo[id] = {p: null, t: ""};
});
const isDrafted = id => id in draftInfo;
const draftedCount = () => Object.keys(draftInfo).length;
const saveDraft = () => { if (!MOCKMODE) localStorage.setItem(LSKEY, JSON.stringify(draftInfo)); };

// personal "don't want to play with" list (client-side only, per season)
const EXKEY = "ld2l-excluded-s" + SEASON;
let excluded = new Set(JSON.parse(localStorage.getItem(EXKEY) || "[]"));
const isExcluded = id => excluded.has(id);
const saveExcluded = () => {
  localStorage.setItem(EXKEY, JSON.stringify([...excluded]));
  pushCuts();
};
// The mock's fast-forward brakes for anyone NOT cut, so the engine needs a copy
// of this list to know who to blow past. This stays the source of truth — the
// server's copy is transient and used for nothing else. (mockPost is a hoisted
// function declaration, so calling it from up here is fine.)
let cutsSynced = false;
function pushCuts(){
  if (MOCKMODE) mockPost("/mock/cuts", {cuts: [...excluded]});
}

// per-player call marks: Target (want), Approved (vetted), Support (vetted
// dedicated support). All independent; all persist per season.
let targets  = new Set(JSON.parse(localStorage.getItem("ld2l-targets-s"  + SEASON) || "[]"));
let approved = new Set(JSON.parse(localStorage.getItem("ld2l-approved-s" + SEASON) || "[]"));
let supports = new Set(JSON.parse(localStorage.getItem("ld2l-supports-s" + SEASON) || "[]"));
const saveMarks = () => {
  localStorage.setItem("ld2l-targets-s"  + SEASON, JSON.stringify([...targets]));
  localStorage.setItem("ld2l-approved-s" + SEASON, JSON.stringify([...approved]));
  localStorage.setItem("ld2l-supports-s" + SEASON, JSON.stringify([...supports]));
};
function toggleTarget(id){
  targets.has(id) ? targets.delete(id) : targets.add(id);
  saveMarks();
}
function toggleApproved(id){
  approved.has(id) ? approved.delete(id) : approved.add(id);
  saveMarks();
}
function toggleSupport(id){
  supports.has(id) ? supports.delete(id) : supports.add(id);
  saveMarks();
}
function markSort(p){
  return (targets.has(p.id)?4:0) + (supports.has(p.id)?2:0) + (approved.has(p.id)?1:0);
}
function markCell(p){
  const t = targets.has(p.id), a = approved.has(p.id), s = supports.has(p.id);
  const ex = isExcluded(p.id)
    ? `<button class="exbtn on" data-ex="${p.id}" title="Restore — add back to your lists">↩</button>`
    : `<button class="exbtn" data-ex="${p.id}" title="Cut — don't want to play with">✕</button>`;
  return `<span class="marks">`
    + `<button class="markbtn tgt ${t?"on":""}" data-mark="t:${p.id}" title="Target — a player you want">🎯</button>`
    + `<button class="markbtn app ${a?"on":""}" data-mark="a:${p.id}" title="Approved — you've vetted this player">✓</button>`
    + `<button class="markbtn sup ${s?"on":""}" data-mark="s:${p.id}" title="Dedicated support — a support player you've vetted">S</button>`
    + ex
    + `</span>`;
}

// Roles a player can play this season. Signup-declared prefs are ignored on
// purpose (the site's role data is unreliable). Default is derived from the
// lanes they ACTUALLY play (measured); you set the truth by hand via the row
// circles, stored per season in localStorage.
const ROLESKEY = "ld2l-roles-s" + SEASON;
let manualRoles = JSON.parse(localStorage.getItem(ROLESKEY) || "{}"); // {id:[1..5]}
const saveRoles = () => localStorage.setItem(ROLESKEY, JSON.stringify(manualRoles));
function roleDefault(p){  // measured lanes -> core positions (supports set by hand)
  const L = p.lanes || {}, r = [];
  if ((L.Safe||0) >= 15) r.push(1);
  if ((L.Mid ||0) >= 15) r.push(2);
  if ((L.Off ||0) >= 15) r.push(3);
  return r;
}
const getRoles = p => manualRoles[p.id] || roleDefault(p);
function toggleRole(id, pos){
  const p = DATA.find(x=>x.id===id);
  const cur = (manualRoles[id] || roleDefault(p)).slice();
  const i = cur.indexOf(pos);
  i>=0 ? cur.splice(i,1) : cur.push(pos);
  manualRoles[id] = cur.sort((a,b)=>a-b);
  saveRoles();
}
// Captains are set BY HAND (the website flag is unreliable). Seed once from the
// site's captain:yes as a starting point, then it's fully editable. Effective
// captains drop off the draft board and get a card in the Teams tab.
const CAPKEY = "ld2l-captains-s" + SEASON;
let manualCaptains;
{
  const saved = localStorage.getItem(CAPKEY);
  if (saved === null){
    manualCaptains = new Set(DATA.filter(p=>p.captain==="Y").map(p=>p.id));
    localStorage.setItem(CAPKEY, JSON.stringify([...manualCaptains]));
  } else {
    manualCaptains = new Set(JSON.parse(saved));
  }
}
const isCaptain = id => (MOCKMODE ? MOCKCAPTAINS : manualCaptains).has(id);
const saveCaptains = () => localStorage.setItem(CAPKEY, JSON.stringify([...manualCaptains]));
function toggleCaptain(id){
  isCaptain(id) ? manualCaptains.delete(id) : manualCaptains.add(id);
  saveCaptains();
}
// Removed from the draft: players who aren't up for auction this season (pulled
// out, went to a team outside the draft, banned, no-showed…). Deliberately NOT
// the same thing as a cut (✕, "don't want to play with") — you keep scouting
// them here in full, they're just not buyable, so they drop out of the auction
// pool: the mock draft, best-available, scarcity pricing and the board count.
// Exported to captains.json so --mock honours the same list.
const OUTKEY = "ld2l-outofdraft-s" + SEASON;
let withdrawn = new Set(JSON.parse(localStorage.getItem(OUTKEY) || "[]"));
const isWithdrawn = id => withdrawn.has(id);
const saveWithdrawn = () => localStorage.setItem(OUTKEY, JSON.stringify([...withdrawn]));
function toggleWithdrawn(id){
  isWithdrawn(id) ? withdrawn.delete(id) : withdrawn.add(id);
  saveWithdrawn();
}
// the draftable pool: everyone who can still be bought at the auction
const inPool = p => !isCaptain(p.id) && !isWithdrawn(p.id);

// captain NAMES for the Teams tab / draft-team dropdown: scraped budget teams
// plus anyone marked captain by hand
function captainList(){
  const names = Object.keys(BUDGETS).slice();
  DATA.filter(p=>isCaptain(p.id)).forEach(p=>{ if(!names.includes(p.name)) names.push(p.name); });
  return names;
}

// short free-text note per player (persisted, capped so it stays compact)
const NOTEKEY = "ld2l-notes-s" + SEASON;
const NOTE_MAX = 30;
let notes = JSON.parse(localStorage.getItem(NOTEKEY) || "{}");
const saveNotes = () => localStorage.setItem(NOTEKEY, JSON.stringify(notes));

// Current MMR, set BY HAND: Dotabuff can't be auto-scraped (Cloudflare 403) and
// Valve hides exact MMR, so the signup number is often a stale placeholder you
// correct here (e.g. Hollywood 1000 → 1700). Used to rank the draft tooling.
const CURMMRKEY = "ld2l-curmmr-s" + SEASON;
let currentMmr = JSON.parse(localStorage.getItem(CURMMRKEY) || "{}");
const saveCurMmr = () => localStorage.setItem(CURMMRKEY, JSON.stringify(currentMmr));

// Your intended max bid per player, typed BY HAND (up to 3 chars). Persisted.
const BIDKEY = "ld2l-bid-s" + SEASON;
let bids = JSON.parse(localStorage.getItem(BIDKEY) || "{}");
const saveBids = () => localStorage.setItem(BIDKEY, JSON.stringify(bids));
// best number we have for ranking: hand-set current MMR > skill (for unrated) > signup
function effMmr(p){
  if (currentMmr[p.id] != null) return currentMmr[p.id];
  return (p.suspect && p.skill!=null) ? p.skill : p.mmr;
}

// ---- Live auction pricing ----
// estBase/worthBase are the premium-free kNN estimates from past auctions
// (at the listed MMR / at the skill estimate). The scarcity premium is
// recomputed HERE from the current board state — effective captains,
// hand-set roles, corrected MMRs — so Est$/Worth$/Edge$ move as you edit
// the board. Overall curve: calibrated rank premium (the top of the board
// gets bid up, the tail goes for steals). Positional: the top 3 available
// at each position carry a premium too, max()-combined with the overall
// curve so nothing double-counts.
const PRICING = {{PRICING}};
// Premium algorithm — the JS twin of scout/pricing.py. rankPremWith / premWith
// take their control points as arguments so the exact same functions the live
// reprice uses can be replayed against pricing_vectors.json at load (checkPricing
// below). A drift from the Python spec then logs a console error, instead of
// mispricing silently.
function rankPremWith(rank, pts){
  if (rank <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++){
    const [r0, p0] = pts[i-1], [r1, p1] = pts[i];
    if (rank <= r1) return p0 + (p1 - p0) * (rank - r0) / (r1 - r0);
  }
  return pts[pts.length - 1][1];
}
function premWith(mmr, roles, ranked, posRanked, rankPts, posPts){
  let pr = rankPremWith(1 + ranked.filter(m => m > mmr).length, rankPts);
  for (const r of roles){
    const rk = 1 + (posRanked[r] || []).filter(m => m > mmr).length;
    if (rk <= posPts.length) pr = Math.max(pr, posPts[rk-1]);
  }
  return pr;
}
const round5 = x => Math.max(5, Math.round(x/5)*5);
function repriceAll(){
  const pool = DATA.filter(inPool);   // captains + withdrawn players don't compete
  const mmrs = pool.map(effMmr).filter(v => v != null).sort((a,b)=>b-a);
  const posPools = {1:[], 2:[], 3:[], 4:[], 5:[]};
  for (const p of pool){
    const v = effMmr(p);
    if (v == null) continue;
    for (const r of getRoles(p)) posPools[r].push(v);
  }
  const prem = (v, roles) => premWith(v, roles, mmrs, posPools, PRICING.rank, PRICING.pos);
  for (const p of DATA){
    const roles = getRoles(p);
    p.estCost = p.estBase == null ? null : round5(p.estBase + prem(effMmr(p), roles));
    p.worth   = p.worthBase == null ? null : round5(p.worthBase + prem(p.skill, roles));
    p.edge    = (p.worth == null || p.estCost == null) ? null : p.worth - p.estCost;
  }
}
// Cross-language contract check: replay pricing_vectors.json through the exact
// functions above. Runs once at load, never throws (guarded), silent on success.
const PRICING_VECTORS = {{PRICINGVECTORS}};
function checkPricing(){
  try {
    const {rank, pos, cases} = PRICING_VECTORS;
    let bad = 0;
    for (const c of cases){
      const got = premWith(c.mmr, c.roles, c.ranked, c.posRanked, rank, pos);
      if (Math.abs(got - c.premium) > 1e-6){
        bad++;
        console.error(`[pricing] JS premium drifted from spec: mmr=${c.mmr} `
          + `roles=[${c.roles}] expected ${c.premium}, got ${got}`);
      }
    }
    if (!bad) console.debug(`[pricing] ${cases.length} golden vectors OK`);
  } catch (e) { /* a broken check must never break the dashboard */ }
}
checkPricing();

// per-captain budgets, set BY HAND in the Teams tab (overrides any scraped value)
const BUDGKEY = "ld2l-budgets-s" + SEASON;
let manualBudgets = JSON.parse(localStorage.getItem(BUDGKEY) || "{}");  // {captainName: number}
const saveBudgets = () => localStorage.setItem(BUDGKEY, JSON.stringify(manualBudgets));
// In mock mode the engine's budgets (captains.json) win: they're what the
// auction actually enforces, so the display can never disagree with the rules.
const teamBudget = c => (MOCKMODE && MOCKBUDGETS[c] != null) ? MOCKBUDGETS[c]
                       : manualBudgets[c] != null ? manualBudgets[c]
                       : (BUDGETS[c] != null ? BUDGETS[c] : null);

// per-team suspected targets, set BY HAND in the Teams tab: players you think a
// rival captain is chasing. {captainName: [playerName,...]}, persisted per season.
const TTKEY = "ld2l-teamtargets-s" + SEASON;
let teamTargets = JSON.parse(localStorage.getItem(TTKEY) || "{}");
const saveTeamTargets = () => localStorage.setItem(TTKEY, JSON.stringify(teamTargets));
const DATA_BY_NAME = Object.fromEntries(DATA.map(p=>[p.name.toLowerCase(), p]));

// suspected-targets section for one captain's card: chips (struck through once
// the player is drafted, so a chased name that's gone is obvious) + add box.
function teamTargetsSection(c){
  const list = teamTargets[c] || [];
  const chips = list.map((nm,i)=>{
    const p = DATA_BY_NAME[nm.toLowerCase()];
    const taken = p && isDrafted(p.id);
    const mmr = p ? ` <span class="pp">${p.mmr}</span>` : "";
    return `<span class="tt-chip ${taken?"taken":""}"${taken?' title="already drafted"':""}>`
         + `<span class="nm">${esc(nm)}</span>${mmr}`
         + `<button class="tt-x" data-team="${esc(c)}" data-i="${i}" title="Remove">×</button></span>`;
  }).join("");
  return `<div class="teamtargets"><div class="tt-head">Suspected targets</div>`
       + (chips ? `<div class="tt-chips">${chips}</div>` : "")
       + `<input class="tt-add" data-team="${esc(c)}" list="playerlist" placeholder="add player + Enter"></div>`;
}

// my-team roster planner: [{name, roles:[1..5]}], persisted per season
const MTKEY = "ld2l-myteam-s" + SEASON;
let roster = JSON.parse(localStorage.getItem(MTKEY) || "[]");
const saveRoster = () => localStorage.setItem(MTKEY, JSON.stringify(roster));
let myNeeds = {covered:new Set(), needs:[1,2,3,4,5], matchPos:{}, coverCount:{}};

let cmpSel = new Set();
let posFilter = new Set();
let sortCol = "mmr", sortDir = -1;

const COLS = [
  {k:"_cmp",  t:"⇄",     num:false, sort:null, d:"Tick to add this player to the head-to-head compare tray (up to 5)"},
  {k:"name",  t:"Player", num:false, sort:(a)=>a.name.toLowerCase(), d:"Click the name to expand full detail; 🔍 opens the full scouting report. C marks captain; ⊘ removes the player from the draft (they stay on the board and keep their scouting, but leave the auction pool, the pricing math and the mock draft). Badges: CAPT, OUT, NEW, 🔒 private, ✓ vouched"},
  {k:"bid",   t:"Bid",    num:true,  sort:(a)=>{const v=parseFloat(bids[a.id]); return isNaN(v)?-1:v;}, d:"Your intended max bid — type it in (up to 3 chars). Saved in your browser; sort to see your priciest targets"},
  {k:"mark",  t:"Mark",   num:false, sort:(a)=>markSort(a), d:"Your call: 🎯 = target (want), ✓ = approved (vetted), S = dedicated support (vetted), ✕ = cut (click again to restore). All independent. Sort to group your marked players."},
  {k:"mmr",   t:"Website MMR",num:true, sort:(a)=>a.mmr, d:"MMR currently listed on the LD2L website — exactly what captains will see on draft day. Re-scraped every run, so admin re-rates and self-updates flow through (the movement shows in Climb). Can still be a stale placeholder (e.g. the 1000 floor)"},
  {k:"curMmr",t:"Current MMR",num:true, sort:(a)=>currentMmr[a.id]??-1, d:"Real current MMR, set BY HAND. Dotabuff can't be auto-scraped (Cloudflare) and Valve hides exact MMR, so type the true value here (placeholder shows the website number). Used to rank the draft tooling"},
  {k:"rank",  t:"Medal",  num:false, sort:(a)=>a.rankTier||0, d:"Current Dota medal (rank tier) from OpenDota. Can be stale if the player hasn't recalibrated — e.g. shows Herald though they play far higher. Hover for the name"},
  {k:"skill", t:"Plays like",num:true, sort:(a)=>a.skill==null?-1:a.skill, d:"Behavioural estimate of true current skill from medal + the ranked lobbies they actually play, adjusted for hot/cold form and inactivity. ± is the uncertainty. Does NOT use the listed MMR, so it can be compared against it"},
  {k:"gap",   t:"Gap",    num:true,  sort:(a)=>a.gap==null?-9999:a.gap, d:"Plays like − listed MMR. Big positive = likely underpriced; big negative = risk. ★unrated = placeholder listed MMR (expect a re-rate)"},
  {k:"tier",  t:"Value",  num:false, sort:(a)=>a.gap==null?-9999:a.gap, d:"Letter grade of the Gap: S ≥ +500 (steal), A ≥ +300, B ≥ +150, C fair, D/E/F listed above how they play. ? = gap smaller than the estimate's uncertainty"},
  {k:"edge",  t:"Edge$",  num:true,  sort:(a)=>a.edge==null?-9999:a.edge, d:"Auction edge: what a player of this TRUE skill usually costs, minus their expected price at the LISTED MMR. Positive = surplus if they go near their listing"},
  {k:"estCost",t:"Est$",num:true,sort:(a)=>a.estCost==null?-1:a.estCost, d:"Expected winning bid at the listed MMR — median price of the 7 nearest-MMR players across the last 4 auction seasons, plus a scarcity premium: top-of-pool names get bid up (~+80 for the #1 slot), the top 3 at each position carry a premium (+40/+25/+12, so set the Roles circles!), the tail goes for steals (~−15). Recomputes live as you edit captains, roles and current MMRs"},
  {k:"lastCost",t:"Last$",num:true,sort:(a)=>a.lastCost==null?-1:a.lastCost, d:"What this player actually cost at their most recent past auction (or captain / undrafted)"},
  {k:"roles", t:"Roles",   num:false, sort:(a)=>getRoles(a).join(), d:"Positions the player can play this season. Seeded from the lanes they actually play (Safe→1, Mid→2, Off→3); click the circles to set the truth by hand"},
  {k:"note",  t:"Note",    num:false, sort:(a)=>(notes[a.id]||"").toLowerCase(), d:"Your own short scouting note (max 30 chars), saved in your browser — e.g. \"wants to stick to one role\""},
  {k:"lanes", t:"Lanes (6mo)",num:false,sort:(a)=>-(a.laneN||0), d:"Lanes actually played over the last 6 months (Safe/Mid/Off %), from match history. '1-trick' = one lane ≥ 70% of games"},
  {k:"server",t:"Server",  num:false, sort:(a)=>a.server||"zzz", d:"Server region played most over the last 3 months (USE/USW/SEA/EU…), from match clusters. Hover for the full mix"},
  {k:"useWr", t:"East WR%", num:true,  sort:(a)=>a.useWr==null?-1:a.useWr, d:"Win rate on US East servers over the last 6 months — the server LD2L games are played on. Games in parens; — = no US East games on record. Low n is noisy"},
  {k:"wr",    t:"WR%",    num:true,  sort:(a)=>a.wr, d:"Lifetime win rate across all recorded games"},
  {k:"form30",t:"Form 30d",num:false, sort:(a)=>a.form30wr==null?-1:a.form30wr, d:"Win rate over the last 30 days (games in parens). ▲/▼ = statistically hot/cold against a bar corrected for the number of players tested"},
  {k:"games", t:"Games",  num:true,  sort:(a)=>a.games, d:"Total recorded games (lifetime win+loss)"},
  {k:"last",  t:"Last",   num:true,  sort:(a)=>a.last==null?99999:a.last, d:"Days since their last recorded match (⚠ = inactive 90+ days)"},
  {k:"kda",   t:"KDA",    num:true,  sort:(a)=>a.kda, d:"(Kills + Assists) / Deaths, median over the last ~200 games"},
  {k:"gpm",   t:"GPM",    num:true,  sort:(a)=>a.gpm, d:"Gold per minute, median over the last ~200 games"},
  {k:"lobby", t:"Lobby",  num:false, sort:(a)=>a.lobbyTier==null?-1:a.lobbyTier, d:"Median medal of the lobbies they actually queue into — a hard-to-fake read on their level"},
  {k:"punchGap",t:"Punch",num:true,  sort:(a)=>a.punchGap==null?-99:a.punchGap, d:"Stars between their median lobby and their own medal. +3★ or more = queues well above their rank (green). Reads vs the medal, so a decayed medal inflates it"},
  {k:"climb", t:"Climb",  num:true,  sort:(a)=>a.climb==null?-99999:a.climb, d:"Change in the website MMR since we first recorded them (admin re-rate or self-update). — = unchanged. A freshness signal, read alongside Gap"},
  {k:"soloPct",t:"Solo%", num:true,  sort:(a)=>a.soloPct==null?-1:a.soloPct, d:"Share of games played solo vs in a party (last ~200 games)"},
  {k:"esports6moWr",t:"Esports 6mo WR",num:true,sort:esportsSort, d:"Win rate in verified OpenDota ticketed matches (leagueid > 0) during the last 6 months. Shown as win rate plus game count; — means no ticketed games or unavailable data"},
  {k:"tox",   t:"Toxicity",num:true, sort:(a)=>a.tox==null?-1:a.tox, d:"Chat toxicity score 0-100 from the OpenDota word cloud (multilingual flame/curse/slur, slurs weighted heaviest). Clean < 15 · Mild · Salty · Toxic ≥ 65. — = no public chat data. Full breakdown in the 🔍 scouting report"},
  {k:"_links",t:"Links",  num:false, sort:null, d:"External profiles — DB: Dotabuff · OD: OpenDota · L2: LD2L · St: Steam"},
];

function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

// rated 1-2, or their best-rated position (covers players who left the form blank)
// role membership now comes from the (measured-seeded, hand-editable) role set
function playsPos(p, pos){ return getRoles(p).includes(pos); }

function rolesCell(p){
  const roles = getRoles(p);
  const circles = [1,2,3,4,5].map(pos=>
    `<button class="rolecirc ${roles.includes(pos)?"on":""}" data-role="${p.id}:${pos}" title="Toggle Pos ${pos}">${pos}</button>`).join("");
  const edited = manualRoles[p.id] ? "" : ' <span class="dim" title="default from measured lanes — click to set">·</span>';
  return `<span class="rolecircles">${circles}</span>${edited}`;
}

function laneCell(p){
  if (!p.laneN) return '<span class="dim">—</span>';
  const order = ["Safe","Mid","Off","Jungle"];
  const parts = order.filter(k=>p.lanes[k]).map(k=>[k, p.lanes[k]]);
  const cls = {Safe:"l1", Mid:"l2", Off:"l3", Jungle:"l3"};
  const bar = parts.map(([k,v])=>`<i class="${cls[k]}" style="width:${v}%" title="${k} ${v}%"></i>`).join("");
  const txt = parts.map(([k,v])=>`${k[0]}${v}`).join(" ");
  return `<span class="lane"><span class="lanebar">${bar}</span><span class="lanetxt">${txt}</span></span>${oneTrickTag(p)}`;
}

function serverCell(p){
  if (!p.server) return '<span class="dim">—</span>';
  return `<span class="srvchip" title="${esc(p.serverMix)} · over ${p.serverN} games (3mo)">${esc(p.server)}</span>`;
}

function toxCell(p){
  if (p.tox==null) return '<span class="dim">—</span>';
  const cls = p.tox>=65 ? "bad" : (p.tox>=40 ? "warn" : (p.tox<15 ? "good" : ""));
  return `<span class="${cls}" title="${esc(p.toxLabel)} chat — from OpenDota word cloud">${p.tox}</span>`
       + ` <span class="dim">${esc(p.toxLabel)}</span>`;
}

// Medal badge from a rank tier (e.g. 45 = Archon 5): base shield + star
// overlay, tooltip carries the text. Falls back to text when the tier is
// unknown or the icon art isn't cached yet (first run offline).
function medalIcon(tier, label){
  const base = tier ? RANK_ICONS["rank_icon_" + Math.floor(tier/10)] : null;
  if (!base) return `<span class="dim">${esc(label)}</span>`;
  const star = RANK_ICONS["rank_star_" + (tier%10)];
  return `<span class="medal" title="${esc(label)}"><img src="${base}" alt="${esc(label)}">`
       + (star ? `<img src="${star}" alt="">` : "") + `</span>`;
}

function useWrCell(p){
  if (!p.useN) return '<span class="dim">—</span>';
  const cls = p.useWr>=53 ? "good" : (p.useWr<48 && p.useN>=30 ? "bad" : "");
  return `<span class="${cls}" title="${p.useW}-${p.useN-p.useW} on US East (6mo sample)">${p.useWr}</span> <span class="dim">(${p.useN})</span>`;
}

function nameCell(p){
  const cap = isCaptain(p.id);
  const out = isWithdrawn(p.id);
  let b = cap ? ' <span class="badge b-cap">CAPT</span>' : "";
  if (out) b += '<span class="badge b-out" title="Removed from the draft — still scouted here, but out of the auction pool and the mock draft">OUT</span>';
  if (p.new) b += '<span class="badge b-new">NEW</span>';
  if (p.private) b += '<span class="badge b-priv" title="Private profile — match data not exposed on OpenDota; stats may be missing">🔒 private</span>';
  if (p.vouched==="Y") b += '<span class="badge b-v" title="vouched">✓</span>';
  const capBtn = `<button class="capbtn ${cap?"on":""}" data-cap="${p.id}" title="${cap
    ? "Captain — off the draft board, shown in Teams. Click to unset"
    : "Mark as captain (removes from draft board, adds a Teams card)"}">C</button>`;
  const outBtn = `<button class="outbtn ${out?"on":""}" data-out="${p.id}" title="${out
    ? "Removed from the draft — still on your board, but out of the auction pool, pricing and the mock draft. Click to put back"
    : "Remove from the draft — keeps them on your scouting board, but takes them out of the auction pool, pricing and the mock draft"}">⊘</button>`;
  const rep = p.report
    ? ` <a class="repl" href="${p.report}" target="_blank" rel="noopener" title="Open ${esc(p.name)}'s full scouting report">🔍</a>`
    : "";
  return `${capBtn}${outBtn}<span class="pname" data-x="${p.id}">${esc(p.name)}</span>${b}${rep}`;
}

function wrCell(v, games){
  if (!games) return '<span class="dim">—</span>';
  const cls = v>=53 ? "good" : (v<48 && games>100 ? "bad" : "");
  return `<span class="${cls}">${v}</span>`;
}

function lastCostCell(p){
  if (!p.lastCostSeason) return '<span class="dim">—</span>';
  const t = `title="${esc(p.lastCostSeason)}${p.lastDraftMmr?" · MMR then "+p.lastDraftMmr:""}"`;
  if (p.wasCaptainLast) return `<span class="dim" ${t}>capt</span>`;
  if (p.lastCost==null) return `<span class="dim" ${t}>undrafted</span>`;
  return `<span ${t}>${p.lastCost}</span>`;
}

function skillCell(p){
  if (p.skill==null) return '<span class="dim">—</span>';
  const parts = [p.skillSrcs];
  if (p.momentum) parts.push(`momentum ${p.momentum>0?"+":""}${p.momentum}`);
  if (p.rust) parts.push(`rust −${p.rust}`);
  if (p.skillNote) parts.push(p.skillNote);
  return `<span title="${esc(parts.filter(Boolean).join(" · "))}">${p.skill}<span class="dim">±${p.skillUnc}</span></span>`;
}

function gapCell(p){
  if (p.gap==null) return '<span class="dim">—</span>';
  if (p.suspect) return `<span class="warn" title="listed MMR looks like a placeholder — expect a re-rate before draft">★unrated</span>`;
  const cls = p.gap>=250 ? "good" : (p.gap<=-250 ? "bad" : "dim");
  return `<span class="${cls}">${p.gap>0?"+":""}${p.gap}</span>`;
}

function punchCell(p){
  if (p.punchGap==null) return '<span class="dim">—</span>';
  const g = p.punchGap;
  const cls = g>=3 ? "good" : (g<=-3 ? "bad" : "");
  const t = `median lobby is ${Math.abs(g)} star${Math.abs(g)===1?"":"s"} ${g>=0?"above":"below"} their own medal`;
  return `<span class="${cls}" title="${t}">${g>0?"+":""}${g}★</span>`;
}

function climbCell(p){
  if (!p.climb) return '<span class="dim">—</span>';  // null or 0 = no change since signup
  const t = `listed MMR ${p.signupMmr} at signup → ${p.mmr} now`;
  if (p.climb>0) return `<span class="good" title="${t}">+${p.climb}▲</span>`;
  return `<span class="bad" title="${t}">${p.climb}▼</span>`;
}

function tierCell(p){
  if (p.tier === "—") return '<span class="dim">—</span>';
  const letter = p.tier.startsWith("★") ? "U" : p.tier[0];
  const short = p.tier.startsWith("★") ? "★" : p.tier[0] + (p.tier.endsWith("?") ? "?" : "");
  return `<span class="tierchip t-${letter}" title="${esc(p.tier)}${p.gap!=null?" · gap "+(p.gap>0?"+":"")+p.gap:""}">${short}</span>`;
}

function edgeCell(p){
  if (p.edge==null) return '<span class="dim">—</span>';
  const cls = p.edge>=20 ? "good" : (p.edge<=-20 ? "bad" : "dim");
  return `<span class="${cls}" title="worth ~${p.worth}$ (at true skill) vs expected price ~${p.estCost}$">${p.edge>0?"+":""}${p.edge}</span>`;
}

function formCell(p){
  if (!p.form30) return '<span class="dim">—</span>';
  let mark = "";
  if (p.hot) mark = ` <span class="good" title="statistically hot (z=+${p.z30}, pool bar ${p.hotColdZ})">▲</span>`;
  else if (p.cold) mark = ` <span class="bad" title="statistically cold (z=${p.z30}, pool bar ${p.hotColdZ})">▼</span>`;
  return esc(p.form30) + mark;
}

function esportsSort(p){
  if (p.esportsStatus==="unavailable" || !p.esports6moGames || p.esports6moWr==null)
    return -1;
  return p.esports6moWr * 100000 + Math.min(p.esports6moGames, 99999);
}

function esportsCell(p){
  if (p.esportsStatus==="unavailable")
    return '<span class="dim" title="Ticketed OpenDota history unavailable for this run">—</span>';
  if (!p.esports6moGames || p.esports6moWr==null)
    return '<span class="dim" title="No ticketed matches in the last six months">—</span>';
  const cls = p.esports6moWr>=53 ? "good" : (p.esports6moWr<48 ? "bad" : "");
  return `<span class="${cls}" title="Verified OpenDota ticketed matches (leagueid > 0)">${p.esports6moWr}% <span class="dim">(${p.esports6moGames}g)</span></span>`;
}

function rowHtml(p){
  const dcls = (isDrafted(p.id) ? "drafted " : "") + (isExcluded(p.id) ? "excluded " : "")
             + (isWithdrawn(p.id) ? "withdrawn " : "")
             + (p.id === liveNomId ? "onblock" : "");
  return `<tr class="main ${dcls}" data-id="${p.id}">
    <td><input type="checkbox" class="cmpck" data-x="${p.id}" ${cmpSel.has(p.id)?"checked":""}></td>
    <td>${nameCell(p)}</td>
    <td class="num"><input class="bidin" data-bid="${p.id}" maxlength="3" inputmode="numeric"
        value="${esc(bids[p.id]||"")}" placeholder="$" title="Your max bid (up to 3 chars)"></td>
    <td>${markCell(p)}</td>
    <td class="num">${p.mmr}</td>
    <td class="num"><input class="curmmrin" data-cur="${p.id}" type="number" min="0" step="10"
        value="${currentMmr[p.id]??""}" placeholder="${p.mmr}" title="Set real current MMR (medal: ${esc(p.rank)})"></td>
    <td>${medalIcon(p.rankTier, p.rank)}</td>
    <td class="num">${skillCell(p)}</td>
    <td class="num">${gapCell(p)}</td>
    <td>${tierCell(p)}</td>
    <td class="num">${edgeCell(p)}</td>
    <td class="num">${p.estCost==null?'<span class="dim">—</span>':"~"+p.estCost}</td>
    <td class="num">${lastCostCell(p)}</td>
    <td>${rolesCell(p)}</td>
    <td><input class="notein" data-note="${p.id}" maxlength="${NOTE_MAX}" value="${esc(notes[p.id]||"")}" placeholder="note…"></td>
    <td>${laneCell(p)}</td>
    <td>${serverCell(p)}</td>
    <td class="num">${useWrCell(p)}</td>
    <td class="num">${wrCell(p.wr, p.games)}</td>
    <td>${formCell(p)}</td>
    <td class="num">${p.games}</td>
    <td class="num">${p.last==null ? '<span class="dim">?</span>' : (p.last>90 ? `<span class="warn">${p.last}d ⚠</span>` : p.last+"d")}</td>
    <td class="num">${p.kda}</td>
    <td class="num">${p.gpm}</td>
    <td>${medalIcon(p.lobbyTier, p.lobby)}</td>
    <td class="num">${punchCell(p)}</td>
    <td class="num">${climbCell(p)}</td>
    <td class="num">${p.soloPct==null?'<span class="dim">—</span>':p.soloPct}</td>
    <td class="num">${esportsCell(p)}</td>
    <td class="num">${toxCell(p)}</td>
    <td><a href="${p.db}" target="_blank">DB</a> · <a href="${p.od}" target="_blank">OD</a> · <a href="${p.ld2l}" target="_blank">L2</a> · <a href="${p.steam}" target="_blank">St</a></td>
  </tr>`;
}

function detailHtml(p){
  const li = (arr)=>arr.length?arr.map(esc).join(", "):"—";
  const skillBits = [];
  if (p.skill!=null){
    skillBits.push(`${esc(p.skillSrcs)}`);
    if (p.momentum) skillBits.push(`momentum ${p.momentum>0?"+":""}${p.momentum}`);
    if (p.rust) skillBits.push(`rust −${p.rust}`);
    if (p.skillNote) skillBits.push(esc(p.skillNote));
  }
  const climbTxt = (p.signupMmr==null) ? "—"
    : (!p.climb ? `unchanged since signup (${p.signupMmr})`
       : `listed ${p.signupMmr} at signup → ${p.mmr} now (${p.climb>0?"+":""}${p.climb})`);
  const upRec = p.upN>=10 ? `${p.upW}-${p.upN-p.upW} (${p.upWr}%) in lobbies 2+ stars above medal` : "—";
  const laneGpm = Object.keys(p.laneGpm||{}).length
    ? Object.entries(p.laneGpm).map(([k,v])=>`${k} ${v}`).join(" · ") : "—";
  const zline = [
    p.farmZ!=null?`farm ${p.farmZ>0?"+":""}${p.farmZ}σ vs ${p.farmPeers} MMR-peer cores`:null,
    p.kdaZ!=null?`KDA ${p.kdaZ>0?"+":""}${p.kdaZ}σ vs MMR peers`:null,
  ].filter(Boolean).join(" · ") || "—";
  return `<tr class="detail" data-for="${p.id}"><td colspan="${COLS.length}"><div class="dgrid">
    <div><h4>Skill estimate</h4><p>${p.skill!=null?`~${p.skill}±${p.skillUnc} — `+skillBits.join(" · "):"no data"}
      ${p.mmrCheck?`<br>${esc(p.mmrCheck)}`:""}</p></div>
    <div><h4>Performance (${p.statsN}g sample)</h4><p>GPM by lane: ${laneGpm}<br>
      Peer z: ${zline}<br>Up-lobby record: ${upRec}</p></div>
    <div><h4>Website MMR since signup</h4><p>${climbTxt}</p></div>
    <div><h4>Server (last 3mo)</h4><p>${p.server?`${esc(p.serverMix)} — over ${p.serverN} games`:"—"}<br>
      East record (6mo): ${p.useN?`${p.useW}-${p.useN-p.useW} (${p.useWr}%)`:"—"}</p></div>
    <div><h4>Statement</h4><p>${esc(p.statement)||"—"}</p></div>
    <div><h4>Top heroes</h4><p>${li(p.topHeroes)}</p></div>
    <div><h4>Signature heroes (100g/53%+)</h4><p>${li(p.sig)}</p></div>
    <div><h4>Recent heroes</h4><p>${li(p.recentHeroes)}</p></div>
    <div><h4>More</h4><p>Roles: ${posBadge(p)}${manualRoles[p.id]?"":" (from lanes)"} · Form 90d: ${esc(p.form90)||"—"} ·
      Solo WR: ${p.soloWr==null?"—":p.soloWr+"%"} · Party WR: ${p.partyWr==null?"—":p.partyWr+"%"} ·
      Hero pool: ${p.pool} · XPM: ${p.xpm} · MMR screenshot: ${p.mmrValid?"yes":"no"}</p></div>
    <div><h4>Auction</h4><p>Est. price: ${p.estCost==null?"—":"~"+p.estCost} ·
      Worth at true skill: ${p.worth==null?"—":"~"+p.worth} ·
      Edge: ${p.edge==null?"—":(p.edge>0?"+":"")+p.edge} ·
      Last draft: ${p.lastCostSeason ? (p.wasCaptainLast?"captain":(p.lastCost==null?"undrafted":"cost "+p.lastCost)) + " (" + esc(p.lastCostSeason) + (p.lastDraftMmr?", MMR then "+p.lastDraftMmr:"") + ")" : "no history"}</p></div>
  </div></td></tr>`;
}

function filtered(){
  const q = document.getElementById("q").value.toLowerCase();
  const hideCaptains = document.getElementById("fcaptains").checked;
  const hideDrafted = document.getElementById("fdrafted").checked;
  const hideExcluded = document.getElementById("fexcluded").checked;
  const hideWithdrawn = document.getElementById("fwithdrawn").checked;
  const fitNeeds = document.getElementById("fitneeds").classList.contains("on");
  return DATA.filter(p=>{
    if (q && !(p.name.toLowerCase().includes(q) || (p.statement||"").toLowerCase().includes(q))) return false;
    if (hideCaptains && isCaptain(p.id)) return false;
    // keep drafted-but-unassigned players visible until the feed names the
    // winning team; they drop out of the list once it lands
    if (hideDrafted && isDrafted(p.id) && draftInfo[p.id].t) return false;
    if (hideExcluded && isExcluded(p.id)) return false;
    if (hideWithdrawn && isWithdrawn(p.id)) return false;
    if (fitNeeds && myNeeds.needs.length && myNeeds.needs.length<5
        && !myNeeds.needs.some(pos=>canPlay(p,pos))) return false;
    if (posFilter.size){
      let ok=false;
      posFilter.forEach(i=>{ if(playsPos(p,i)) ok=true; });
      if(!ok) return false;
    }
    return true;
  });
}

function render(){
  repriceAll();              // prices track live captains / roles / MMR edits
  myNeeds = computeNeeds();  // needed by the Fit filter even when the panel is closed
  const col = COLS.find(c=>c.k===sortCol);
  const list = filtered().slice().sort((a,b)=>{
    const va=col.sort(a), vb=col.sort(b);
    return (va<vb?-1:va>vb?1:0)*sortDir;
  });
  document.getElementById("hdr").innerHTML = COLS.map(c=>
    `<th class="${c.num?"num":""}${c.d?" hashelp":""}" data-k="${c.k}"${c.d?` title="${esc(c.d)}"`:""}>${c.t}${c.k===sortCol?` <span class="arr">${sortDir<0?"▼":"▲"}</span>`:""}</th>`).join("");
  document.getElementById("rows").innerHTML = list.map(rowHtml).join("");
  document.getElementById("count").textContent =
    `${list.length}/${DATA.length} players · ${draftedCount()} drafted`
    + (excluded.size ? ` · ${excluded.size} cut` : "")
    + (withdrawn.size ? ` · ${withdrawn.size} off the draft` : "");
  document.getElementById("exct").textContent = excluded.size ? `(${excluded.size})` : "";
  document.getElementById("outct").textContent = withdrawn.size ? `(${withdrawn.size})` : "";
  renderTiles(); renderBest(); renderTeams(); renderMyTeam(); renderTray();
}

function renderTiles(){
  const caps = manualCaptains.size;
  const news = DATA.filter(p=>p.new).length;
  const active = DATA.filter(p=>p.last!=null && p.last<=30).length;
  const mmrs = DATA.map(effMmr).sort((a,b)=>a-b);
  const med = mmrs.length? mmrs[Math.floor(mmrs.length/2)] : 0;
  const mean = mmrs.length? Math.round(mmrs.reduce((s,v)=>s+v,0)/mmrs.length) : 0;
  const spent = Object.values(draftInfo).reduce((s,i)=>s+(i.p||0), 0);
  const tiles = [
    [DATA.length, "signups"],
    [caps, "captains (set by you)"],
    [news, "new since last run"],
    [active + "/" + DATA.length, "active last 30d"],
    [med, "median MMR (current/website)"],
    [mean, "mean MMR (current/website)"],
    [DATA.length - draftedCount(), "still available"],
  ];
  if (spent) tiles.push([spent, "market spent so far"]);
  document.getElementById("tiles").innerHTML = tiles
    .map(([v,l])=>`<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
}

function renderBudgets(){
  const bar = document.getElementById("budgetbar");
  const spentBy = {}; let total = 0, unassigned = 0;
  Object.values(draftInfo).forEach(i=>{
    if (!i.p) return;
    total += i.p;
    if (i.t) spentBy[i.t] = (spentBy[i.t]||0) + i.p; else unassigned += i.p;
  });
  const caps = captainList().filter(c=>teamBudget(c)!=null);
  if (caps.length){
    const chips = caps.map(c=>{
      const b = teamBudget(c), left = b - (spentBy[c]||0);
      return `<span class="bchip ${left<0?"over":""}">${esc(c)}: <b>${left}</b> / ${b}</span>`;
    }).join("");
    bar.innerHTML = chips
      + `<span class="bchip">market spent: <b>${total}</b></span>`
      + (unassigned ? `<span class="bchip over">unassigned: <b>${unassigned}</b></span>` : "");
  } else if (total){
    bar.innerHTML = `<span class="bchip">market spent: <b>${total}</b></span>`
      + `<span class="dim" style="font-size:12px"> — set each captain's budget in the Teams tab to track per-team</span>`;
  } else {
    bar.innerHTML = `<span class="dim" style="font-size:12px">Tip: run with --live (or --mock) to pull picks, prices and winning teams from the draft; set each captain's budget in the Teams tab.</span>`;
  }
}

function renderBest(){
  const grid = document.getElementById("bestgrid");
  if (!document.getElementById("bestpanel").classList.contains("show")) return;
  renderBudgets();
  const names = ["Pos 1 (Carry)","Pos 2 (Mid)","Pos 3 (Offlane)","Pos 4 (Soft)","Pos 5 (Hard)"];
  grid.innerHTML = names.map((nm,ix)=>{
    // captains run teams and withdrawn players aren't for sale — neither is
    // in the draftable pool
    const cand = DATA.filter(p=>!isDrafted(p.id) && inPool(p) && playsPos(p, ix+1))
                     .sort((a,b)=>effMmr(b)-effMmr(a)).slice(0,5);
    const rows = cand.length ? cand.map(p=>{
      const tag = p.suspect ? " ★" : (p.gap!=null && p.gap>=250 ? " ▲" : (p.gap!=null && p.gap<=-250 ? " ▼" : ""));
      const ex = isExcluded(p.id) ? ' class="exline"' : '';
      return `<div><span${ex}>${esc(p.name)}${tag}</span><span class="m">${effMmr(p)}${p.estCost!=null?" · ~"+p.estCost:""}</span></div>`;
    }).join("")
      : '<div class="dim">none left</div>';
    return `<div class="bestcol"><h3>${nm}</h3>${rows}</div>`;
  }).join("");
}

function posBadge(p){
  const r = getRoles(p);
  return r.length ? r.map(x=>"P"+x).join("/") : "?";
}

function rosterRow(p, price){
  return `<div class="prow"><span>${esc(p.name)} <span class="dim">${posBadge(p)}</span></span>`
       + `<span class="pp">${p.mmr}${price!=null?" · $"+price:""}</span></div>`;
}

// positions a roster still needs, via matching each drafted player to one
// distinct position they can play (a flex player fills one slot, not all)
const NEED_LABEL = {1:"P1 carry", 2:"P2 mid", 3:"P3 off", 4:"P4 soft sup", 5:"P5 hard sup"};
function needsFor(players){
  const matchPos = {};
  function assign(pi, seen){
    for (const pos of getRoles(players[pi])){
      if (seen.has(pos)) continue;
      seen.add(pos);
      if (!(pos in matchPos) || assign(matchPos[pos], seen)){ matchPos[pos]=pi; return true; }
    }
    return false;
  }
  players.forEach((_,pi)=>assign(pi, new Set()));
  const covered = new Set(Object.keys(matchPos).map(Number));
  return [1,2,3,4,5].filter(pos=>!covered.has(pos));
}

function renderTeams(){
  if (!document.getElementById("teamspanel").classList.contains("show")) return;
  const byId = Object.fromEntries(DATA.map(p=>[p.id, p]));
  const teams = {};
  const ensure = c => (teams[c] = teams[c] || {players: [], spent: 0});
  const caps = captainList();
  caps.forEach(ensure);  // seed so empty teams still show
  const unassigned = [];
  Object.entries(draftInfo).forEach(([id, info])=>{
    const p = byId[+id]; if (!p) return;
    if (info.t){ const t = ensure(info.t); t.players.push({p, price: info.p}); t.spent += info.p||0; }
    else unassigned.push({p, price: info.p});
  });
  const order = [...caps, ...Object.keys(teams).filter(c=>!caps.includes(c))];
  const cards = order.map(c=>{
    const t = teams[c];
    const budget = teamBudget(c);
    const left = budget!=null ? budget - t.spent : null;
    const over = left!=null && left<0;
    const rows = t.players.length
      ? t.players.slice().sort((a,b)=>b.p.mmr-a.p.mmr).map(x=>rosterRow(x.p, x.price)).join("")
      : '<div class="empty">no players yet</div>';
    const needs = needsFor(t.players.map(x=>x.p));
    const needsLine = needs.length
      ? `<div class="teamneeds" title="Positions this roster still needs">Needs`
        + `<span class="rolecircles">${needs.map(pos=>`<span class="needcirc" title="${esc(NEED_LABEL[pos])}">${pos}</span>`).join("")}</span></div>`
      : '<div class="teamneeds full">Roster full — all 5 roles covered</div>';
    // money: budget (had to begin) vs spent, with a mini bar + remaining
    const pct = budget ? Math.round(t.spent / budget * 100) : 0;
    const bar = budget!=null
      ? `<div class="moneybar ${over?"over":""}" title="spent $${t.spent} of $${budget} (${pct}%)"><i class="spent" style="width:${Math.min(100,pct)}%"></i></div>`
      : "";
    const money = `<div class="moneyrow">
        <span>Spent <b>$${t.spent}</b></span>
        <span class="mleft ${over?"over":""}">Left <b>${budget!=null?"$"+left:"—"}</b>${budget?` <span class="dim">(${pct}% used)</span>`:""}</span>
      </div>`;
    return `<div class="teamcard ${over?"over":""}">
      <h3><span>${esc(c)}</span><span class="bud">Budget <input class="budgetin" data-team="${esc(c)}" type="number" min="0" step="5" value="${budget!=null?budget:""}" placeholder="set $"></span></h3>
      ${bar}${money}${rows}${needsLine}${teamTargetsSection(c)}</div>`;
  });
  if (unassigned.length){
    const rows = unassigned.slice().sort((a,b)=>b.p.mmr-a.p.mmr).map(x=>rosterRow(x.p, x.price)).join("");
    cards.push(`<div class="teamcard unassigned">
      <h3><span>Unassigned</span><span class="bud">set team in row</span></h3>
      <div class="cnt">drafted, no team picked yet</div>${rows}</div>`);
  }
  document.getElementById("teamgrid").innerHTML =
    cards.length ? cards.join("") : '<div class="dim">No teams yet. Rosters build themselves here as picks come in from --live (or --mock).</div>';
  document.getElementById("playerlist").innerHTML =
    DATA.map(p=>`<option value="${esc(p.name)}"></option>`).join("");
}

// ---- My Team roster planner ----
const POS_NAMES = {1:"Pos 1 · Carry", 2:"Pos 2 · Mid", 3:"Pos 3 · Off", 4:"Pos 4 · Soft", 5:"Pos 5 · Hard"};

// a pool player "can play" a position per their role set (measured-seeded,
// hand-editable via the row circles) — declared signup prefs are not used.
function canPlay(p, pos){ return playsPos(p, pos); }

function dominantLane(p){
  if (!p.laneN || !p.lanes) return null;
  let best=null, bv=-1;
  for (const [k,v] of Object.entries(p.lanes)) if (v>bv){ bv=v; best=k; }
  return best ? {lane:best, share:bv} : null;
}
// behavioural "only plays one thing" flag, independent of stated prefs
function oneTrick(p){
  const d = dominantLane(p);
  return (d && p.laneN>=20 && d.share>=70) ? d : null;
}
function oneTrickTag(p){
  const d = oneTrick(p);
  return d ? `<span class="onetrick" title="plays ${d.lane} lane ${d.share}% of games — narrow role">1-trick ${d.lane}</span>` : "";
}

// bipartite max-matching of roster members -> positions (Kuhn's). Positions
// left unmatched are genuine needs; this is why two Pos-1-only players leave
// four needs, and a flex player slots into whatever's still open.
function computeNeeds(){
  const matchPos = {};  // pos -> member index
  function assign(mi, seen){
    for (const pos of (roster[mi].roles||[])){
      if (seen.has(pos)) continue;
      seen.add(pos);
      if (!(pos in matchPos) || assign(matchPos[pos], seen)){ matchPos[pos]=mi; return true; }
    }
    return false;
  }
  roster.forEach((_,mi)=>assign(mi, new Set()));
  const covered = new Set(Object.keys(matchPos).map(Number));
  const needs = [1,2,3,4,5].filter(pos=>!covered.has(pos));
  const coverCount = {};
  [1,2,3,4,5].forEach(pos=> coverCount[pos]=roster.filter(m=>(m.roles||[]).includes(pos)).length);
  return {matchPos, covered, needs, coverCount};
}

function renderMembers(){
  const box = document.getElementById("mt-members");
  box.innerHTML = roster.map((m,i)=>{
    const chips = [1,2,3,4,5].map(pos=>
      `<span class="rchip ${(m.roles||[]).includes(pos)?"on":""}" data-mi="${i}" data-pos="${pos}">P${pos}</span>`).join("");
    return `<div class="mt-member">
      <input class="nm" data-mi="${i}" placeholder="player ${i+1}" value="${esc(m.name||"")}">
      <span class="mt-roles">${chips}</span>
      <button class="mt-x" data-mi="${i}" title="remove">×</button></div>`;
  }).join("") || '<div class="mt-hint">No players yet — add yourself and your locked-in teammates.</div>';
}

function renderCoverage(){
  myNeeds = computeNeeds();
  const {matchPos, covered, needs, coverCount} = myNeeds;
  document.getElementById("mt-cov").innerHTML = [1,2,3,4,5].map(pos=>{
    const who = matchPos[pos]!=null ? (roster[matchPos[pos]].name || ("player "+(matchPos[pos]+1))) : "";
    const cls = covered.has(pos) ? "cov" : "need";
    const label = covered.has(pos)
      ? esc(who) + (coverCount[pos]>1?` <span class="dim">(+${coverCount[pos]-1})</span>`:"")
      : "NEED";
    return `<div class="covcell ${cls}"><div class="pos">${POS_NAMES[pos]}</div><div class="who">${label}</div></div>`;
  }).join("");

  const box = document.getElementById("mt-tgts");
  if (!roster.length){
    box.innerHTML = '<div class="mt-hint">Add your roster to see which positions you still need and the best available players for each.</div>';
    return;
  }
  if (!needs.length){
    box.innerHTML = '<div class="mt-hint">All five positions are covered by your roster. Use “Fit my needs” off; target best-available or upgrades.</div>';
    return;
  }
  box.innerHTML = needs.map(pos=>{
    const cand = DATA.filter(p=>!isDrafted(p.id) && inPool(p) && canPlay(p,pos))
                     .sort((a,b)=>effMmr(b)-effMmr(a)).slice(0,5);
    const rows = cand.length ? cand.map(p=>{
      const g = p.gap!=null && !p.suspect ? ` <span class="${p.gap>=250?"good":p.gap<=-250?"bad":"dim"}">${p.gap>0?"+":""}${p.gap}</span>` : (p.suspect?' <span class="warn">★</span>':"");
      const ex = isExcluded(p.id) ? ' class="exline"' : '';
      return `<div class="tgt-row"><span${ex}>${esc(p.name)}${p.climbing?' <span class="good">▲</span>':""} ${oneTrickTag(p)}</span>`
           + `<span class="r">${effMmr(p)}${g}${p.estCost!=null?" · ~$"+p.estCost:""}</span></div>`;
    }).join("") : '<div class="mt-hint">none available</div>';
    return `<div class="tgt-need"><h4>${POS_NAMES[pos]} — best available</h4>${rows}</div>`;
  }).join("");
}

function renderMyTeam(){
  if (!document.getElementById("myteampanel").classList.contains("show")) return;
  renderMembers();
  renderCoverage();
}

function renderTray(){
  const tray = document.getElementById("tray");
  if (!cmpSel.size){ tray.classList.remove("show"); return; }
  tray.classList.add("show");
  const names = DATA.filter(p=>cmpSel.has(p.id)).map(p=>p.name);
  document.getElementById("traynames").textContent = names.join(" · ");
}

function openCompare(){
  const sel = DATA.filter(p=>cmpSel.has(p.id));
  if (!sel.length) return;
  const stats = [
    ["Website MMR", p=>p.mmr], ["Medal", p=>`${medalIcon(p.rankTier, p.rank)} ${esc(p.rank)}`],
    ["Plays like", p=>skillCell(p)], ["Gap", p=>gapCell(p)],
    ["Value tier", p=>tierCell(p)], ["Edge$", p=>edgeCell(p)],
    ["Est. cost", p=>p.estCost==null?"—":"~"+p.estCost],
    ["Last cost", p=>lastCostCell(p)],
    ["Captain", p=>isCaptain(p.id)?"yes":"—"], ["Roles", p=>posBadge(p)],
    ["Mark", p=>[targets.has(p.id)?"target":"", approved.has(p.id)?"✓ approved":"", supports.has(p.id)?"S support":""].filter(Boolean).join(" · ")||"—"],
    ["Note", p=>esc(notes[p.id]||"")||"—"],
    ["Lanes", p=>laneCell(p)], ["Server (3mo)", p=>p.server?esc(p.serverMix):"—"],
    ["East WR (6mo)", p=>useWrCell(p)],
    ["Lifetime WR", p=>p.games?p.wr+"%":"—"],
    ["Form 30d", p=>formCell(p)], ["Form 90d", p=>esc(p.form90)||"—"],
    ["MMR since signup", p=>climbCell(p)],
    ["Up-lobby record", p=>p.upN>=10?`${p.upW}-${p.upN-p.upW} (${p.upWr}%)`:"—"],
    ["Farm vs peers", p=>p.farmZ==null?"—":(p.farmZ>0?"+":"")+p.farmZ+"σ"],
    ["Games", p=>p.games], ["Last played", p=>p.last==null?"?":p.last+"d"],
    ["KDA", p=>p.kda], ["GPM", p=>p.gpm], ["Hero pool", p=>p.pool],
    ["Lobby median", p=>`${medalIcon(p.lobbyTier, p.lobby)} ${esc(p.lobby)}`],
    ["Punch (stars)", p=>punchCell(p)],
    ["Solo WR", p=>p.soloWr==null?"—":p.soloWr+"%"],
    ["Esports 6mo WR", p=>esportsCell(p)],
    ["Signature heroes", p=>p.sig.slice(0,4).map(esc).join("<br>")||"—"],
    ["Top heroes", p=>p.topHeroes.slice(0,3).map(esc).join("<br>")||"—"],
    ["Statement", p=>esc(p.statement)||"—"],
  ];
  const cmp = document.getElementById("cmp");
  cmp.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center">
      <h2 style="margin:0;font-size:16px">Head-to-head</h2>
      <button class="chip" onclick="document.getElementById('cmp').classList.remove('show')">Close</button>
    </div>
    <table><thead><tr><th></th>${sel.map(p=>`<th>${esc(p.name)}</th>`).join("")}</tr></thead>
    <tbody>${stats.map(([n,f])=>`<tr><td>${n}</td>${sel.map(p=>`<td>${f(p)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  cmp.classList.add("show");
}

// ---- events ----
document.querySelector(".controls").addEventListener("input", ()=>{ saveFilters(); render(); });
document.getElementById("poschips").innerHTML =
  [1,2,3,4,5].map(i=>`<button class="chip posck" data-p="${i}">P${i}</button>`).join(" ");
document.getElementById("poschips").addEventListener("click", e=>{
  const b = e.target.closest(".posck"); if(!b) return;
  const v = +b.dataset.p;
  posFilter.has(v) ? posFilter.delete(v) : posFilter.add(v);
  b.classList.toggle("on");
  saveFilters();
  render();
});
document.getElementById("hdr").addEventListener("click", e=>{
  const th = e.target.closest("th"); if(!th) return;
  const col = COLS.find(c=>c.k===th.dataset.k);
  if (!col || !col.sort) return;
  if (sortCol===col.k) sortDir=-sortDir; else { sortCol=col.k; sortDir=-1; }
  render();
});
// per-team budget edits (Teams tab) — save on change so focus is kept while typing
document.getElementById("teamgrid").addEventListener("change", e=>{
  const bi = e.target.closest(".budgetin");
  if (!bi) return;
  const c = bi.dataset.team;
  if (bi.value === "") delete manualBudgets[c]; else manualBudgets[c] = Math.max(0, +bi.value);
  saveBudgets(); renderTeams(); renderBudgets();
});
// suspected-targets: Enter in the add box appends a target; ✕ removes one
document.getElementById("teamgrid").addEventListener("keydown", e=>{
  const inp = e.target.closest(".tt-add");
  if (!inp || e.key !== "Enter") return;
  e.preventDefault();
  const c = inp.dataset.team, v = inp.value.trim();
  if (!v) return;
  (teamTargets[c] = teamTargets[c] || []).push(v);
  saveTeamTargets(); renderTeams();
  const again = document.querySelector('.tt-add[data-team="' + CSS.escape(c) + '"]');
  if (again) again.focus();  // keep focus so you can add several in a row
});
document.getElementById("teamgrid").addEventListener("click", e=>{
  const x = e.target.closest(".tt-x");
  if (!x) return;
  const c = x.dataset.team, i = +x.dataset.i;
  if (!teamTargets[c]) return;
  teamTargets[c].splice(i, 1);
  if (!teamTargets[c].length) delete teamTargets[c];
  saveTeamTargets(); renderTeams();
});
// notes save per keystroke (no re-render, so focus/caret are kept while typing)
document.getElementById("rows").addEventListener("input", e=>{
  const ni = e.target.closest(".notein");
  if (ni){
    const id = +ni.dataset.note;
    const v = ni.value.slice(0, NOTE_MAX).trim();
    if (v) notes[id] = v; else delete notes[id];
    saveNotes(); return;
  }
  const ci = e.target.closest(".curmmrin");
  if (ci){
    const id = +ci.dataset.cur;
    if (ci.value === "") delete currentMmr[id]; else currentMmr[id] = +ci.value;
    saveCurMmr();
    repriceAll();  // premium ranks move with the corrected MMR
    renderTiles(); renderBest(); renderMyTeam();  // ranking uses current MMR
    return;
  }
  const bi = e.target.closest(".bidin");
  if (bi){
    const id = +bi.dataset.bid;
    const v = bi.value.slice(0, 3).trim();
    if (v) bids[id] = v; else delete bids[id];
    saveBids();
  }
});
document.getElementById("rows").addEventListener("click", e=>{
  const mb = e.target.closest(".markbtn");
  if (mb){
    const [kind, idStr] = mb.dataset.mark.split(":");
    const id = +idStr;
    if (kind === "t") toggleTarget(id);
    else if (kind === "s") toggleSupport(id);
    else toggleApproved(id);
    render();  // re-render so the button on/off state updates
    return;
  }
  const rc = e.target.closest(".rolecirc");
  if (rc){
    const [id, pos] = rc.dataset.role.split(":").map(Number);
    toggleRole(id, pos);
    render();  // ripples into pos filter, best-available, My Team needs
    return;
  }
  const cb = e.target.closest(".capbtn");
  if (cb){
    toggleCaptain(+cb.dataset.cap);
    render();  // ripples into draft board, Teams tab, tiles
    return;
  }
  const ob = e.target.closest(".outbtn");
  if (ob){
    toggleWithdrawn(+ob.dataset.out);
    render();  // ripples into pricing, best-available and the board count
    return;
  }
  const xbtn = e.target.closest(".exbtn");
  if (xbtn){
    const id = +xbtn.dataset.ex;
    isExcluded(id) ? excluded.delete(id) : excluded.add(id);
    saveExcluded();
    render(); return;
  }
  const ck = e.target.closest(".cmpck");
  if (ck){
    const id = +ck.dataset.x;
    if (ck.checked && cmpSel.size>=5){ ck.checked=false; return; }
    ck.checked ? cmpSel.add(id) : cmpSel.delete(id);
    renderTray(); return;
  }
  const nm = e.target.closest(".pname");
  if (nm){
    const id = +nm.dataset.x;
    const open = document.querySelector(`tr.detail[data-for="${id}"]`);
    if (open){ open.remove(); return; }
    const p = DATA.find(x=>x.id===id);
    document.querySelector(`tr.main[data-id="${id}"]`)
      .insertAdjacentHTML("afterend", detailHtml(p));
  }
});
// the three panels share the strip above the table — only one shows at a time
const PANELS = {draftmode:"bestpanel", teamsmode:"teamspanel", myteammode:"myteampanel"};
function togglePanel(btnId){
  const target = PANELS[btnId];
  const showing = document.getElementById(target).classList.toggle("show");
  for (const [b, panel] of Object.entries(PANELS)){
    const on = panel===target ? showing : false;
    document.getElementById(panel).classList.toggle("show", on);
    document.getElementById(b).classList.toggle("on", on);
  }
  renderBest(); renderTeams(); renderMyTeam();
  sizeWrap();
}
Object.keys(PANELS).forEach(b=>
  document.getElementById(b).addEventListener("click", ()=>togglePanel(b)));

// Fit-my-needs filter toggle (a button, so it needs its own click handler)
document.getElementById("fitneeds").addEventListener("click", e=>{
  e.target.classList.toggle("on");
  saveFilters();
  render();
});

// roster editing
document.getElementById("mt-add").addEventListener("click", ()=>{
  roster.push({name:"", roles:[]}); saveRoster(); renderMyTeam();
});
document.getElementById("mt-members").addEventListener("input", e=>{
  const nm = e.target.closest(".nm"); if(!nm) return;
  roster[+nm.dataset.mi].name = nm.value; saveRoster(); renderCoverage();
});
document.getElementById("mt-members").addEventListener("click", e=>{
  const rc = e.target.closest(".rchip");
  if (rc){
    const mi = +rc.dataset.mi, pos = +rc.dataset.pos, m = roster[mi];
    m.roles = m.roles || [];
    const i = m.roles.indexOf(pos);
    i>=0 ? m.roles.splice(i,1) : m.roles.push(pos);
    rc.classList.toggle("on");
    saveRoster(); renderCoverage(); return;
  }
  const x = e.target.closest(".mt-x");
  if (x){ roster.splice(+x.dataset.mi, 1); saveRoster(); renderMyTeam(); }
});
document.getElementById("resetdraft").addEventListener("click", ()=>{
  if (!draftedCount() || confirm("Clear all " + draftedCount() + " drafted marks (and their prices)?")){
    draftInfo = {};
    // purge storage directly (not via saveDraft, which is a no-op in mock mode)
    // so stale marks from old runs are gone for draft day too
    localStorage.removeItem(LSKEY);
    localStorage.removeItem("ld2l-drafted-s" + SEASON);
    mockDraftSig = null;
    render();
  }
});
// "Dotabuff all" — open the Dotabuff of every player not cut (✕) and not a
// captain, each as a tab in this window. Passing no window features is what
// keeps them tabs: hand open() a width/height and the browser spawns a detached
// pop-up window instead. This needs pop-ups allowed for the page — the blocker
// otherwise lets only the first through.
document.getElementById("opendb").addEventListener("click", ()=>{
  const players = DATA.filter(p => !isExcluded(p.id) && inPool(p));
  if (!players.length){ alert("No draftable players left to open."); return; }
  const url = id => "https://www.dotabuff.com/players/" + id;
  // The first open() doubles as the blocked-check, so it can't carry "noopener":
  // the spec returns null whenever that is set, which would make the check below
  // fire on every click. Severing .opener by hand is the same anti-tabnabbing
  // guarantee and still leaves us a real handle to test.
  const win = window.open(url(players[0].id), "_blank");
  if (!win){
    alert("Your browser blocked the pop-ups. Allow pop-ups for this page, then click again.");
    return;
  }
  try { win.opener = null; } catch (e) {}
  for (let i = 1; i < players.length; i++) window.open(url(players[i].id), "_blank", "noopener");
});
document.getElementById("clearroles").addEventListener("click", ()=>{
  if (confirm("Blank every player's role circles? All roles are cleared for you "
      + "to set by hand (this also drops the measured-lane defaults).")){
    manualRoles = {};
    DATA.forEach(p => manualRoles[p.id] = []);  // explicit empty = stays blank
    saveRoles();
    render();
  }
});
// Export the curated captains (+ their budgets + top role), the role circles and
// the removed-from-draft list to captains.json for the --mock draft. This is the
// bridge: the Python mock can't read this browser's localStorage, so it reads
// the file you drop next to ld2l_scout.py.
document.getElementById("exportcaps").addEventListener("click", ()=>{
  const rows = [], seen = new Set();
  DATA.filter(p => isCaptain(p.id)).forEach(p => {
    const roles = manualRoles[p.id];
    rows.push({
      name: p.name,
      steam32: p.id,
      budget: teamBudget(p.name),
      // full role SET — the mock lets the captain flex across all of them
      pos: (roles && roles.length) ? roles.slice().sort() : null,
    });
    seen.add(p.name);
  });
  // any budget-only captain names (scraped teams with no marked signup row)
  captainList().forEach(name => {
    if (!seen.has(name)){
      const steam32 = CAPTAIN_IDS[name] ?? null;
      const player = steam32 == null ? null : DATA.find(p => p.id === steam32);
      const roles = player ? manualRoles[player.id] : null;
      rows.push({
        name,
        steam32,
        budget: teamBudget(name),
        pos: (roles && roles.length) ? roles.slice().sort() : null,
      });
    }
  });
  if (!rows.length){
    alert("No captains marked yet. Use the C button on a player's row to mark captains first.");
    return;
  }
  // players you've taken off the draft (⊘): the mock drops them from its pool
  const removed = DATA.filter(p => isWithdrawn(p.id)).map(p => p.id);
  // the role circles YOU set, for every player that has any — the mock's main
  // role signal (steam32 -> [positions]); unmarked players fall back to
  // measured lanes on the mock side
  const roles = {};
  DATA.forEach(p => {
    const r = manualRoles[p.id];
    if (r && r.length) roles[p.id] = r.slice().sort();
  });
  const payload = {captains: rows, roles, removed};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "captains.json";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
});
document.getElementById("docmp").addEventListener("click", openCompare);
document.getElementById("clearcmp").addEventListener("click", ()=>{ cmpSel.clear(); render(); });

const methodEl = document.getElementById("method");
document.getElementById("methodmode").addEventListener("click", ()=>methodEl.classList.add("show"));
document.getElementById("methodclose").addEventListener("click", ()=>methodEl.classList.remove("show"));
methodEl.addEventListener("click", e=>{ if (e.target===methodEl) methodEl.classList.remove("show"); });
document.addEventListener("keydown", e=>{
  if (e.key==="Escape"){
    methodEl.classList.remove("show");
    document.getElementById("cmp").classList.remove("show");
  }
});

// size the table region to the viewport so it scrolls inside .wrap
// (leaving room for the compare tray at the bottom)
function sizeWrap(){
  const w = document.querySelector(".wrap");
  w.style.maxHeight = Math.max(300, window.innerHeight - w.offsetTop - 70) + "px";
}
window.addEventListener("resize", sizeWrap);

// Filter persistence: position chips, Fit-my-needs, and the hide checkboxes
// survive a refresh (saved per season, like marks). Search text stays fresh.
const FILTKEY = "ld2l-filters-s" + SEASON;
function saveFilters(){
  localStorage.setItem(FILTKEY, JSON.stringify({
    pos: [...posFilter],
    fit: document.getElementById("fitneeds").classList.contains("on"),
    caps: document.getElementById("fcaptains").checked,
    drafted: document.getElementById("fdrafted").checked,
    cut: document.getElementById("fexcluded").checked,
    out: document.getElementById("fwithdrawn").checked,
  }));
}
(function restoreFilters(){
  const f = JSON.parse(localStorage.getItem(FILTKEY) || "null");
  if (!f) return;
  (f.pos || []).forEach(v=>posFilter.add(v));
  document.querySelectorAll(".posck").forEach(b=>{
    b.classList.toggle("on", posFilter.has(+b.dataset.p));
  });
  document.getElementById("fitneeds").classList.toggle("on", !!f.fit);
  document.getElementById("fcaptains").checked = !!f.caps;
  document.getElementById("fdrafted").checked = !!f.drafted;
  document.getElementById("fexcluded").checked = !!f.cut;
  document.getElementById("fwithdrawn").checked = !!f.out;
})();

// ---- Live draft feed + bid assistant (read-only) ----
// Active only when the page is served by `python ld2l_scout.py --live`; a
// plain file:// open stays fully manual. The local server polls the public
// ld2l.org draft page (and, if available, listens to the same read-only
// socket broadcast every spectator browser gets). NOTHING is sent to the
// site: the assistant advises, you bid by hand in the real draft room.
const LIVE = location.protocol === "http:" || location.protocol === "https:";
let liveOk = false, liveSock = false, liveNomId = null, lastNom = null;

// which captain am I? (persisted; drives budget/slots in the assistant)
const MYCAPKEY = "ld2l-mycap-s" + SEASON;
let myCap = localStorage.getItem(MYCAPKEY) || "";
function renderMyCapSel(){
  return;  // captain dropdown retired — the header ticker is the only live UI
  const el = document.getElementById("mycap");
  if (!LIVE) return;
  el.style.display = "";
  const names = captainList();
  if (myCap && !names.includes(myCap)) names.unshift(myCap);
  const html = `<option value="">I am… (pick for bid help)</option>`
    + names.map(c=>`<option value="${esc(c)}"${c===myCap?" selected":""}>I am ${esc(c)}</option>`).join("");
  if (el.dataset.sig === html) return;  // don't rebuild (and close) an open dropdown
  el.dataset.sig = html;
  el.innerHTML = html;
}
document.getElementById("mycap").addEventListener("change", e=>{
  myCap = e.target.value;
  localStorage.setItem(MYCAPKEY, myCap);
  renderNomBanner(lastNom);
});

// roster math: LD2L teams draft 4 players around the captain
function myDraftState(){
  if (!myCap) return null;
  let spent = 0, count = 0;
  for (const [id, info] of Object.entries(draftInfo)){
    if (info.t === myCap){ spent += info.p || 0; count += 1; }
  }
  const budget = teamBudget(myCap);
  const slotsLeft = Math.max(0, 4 - count);
  const remaining = budget == null ? null : budget - spent;
  // keep the $5 minimum in hand for every other seat you still have to fill
  const maxBid = remaining == null ? null : remaining - 5 * Math.max(0, slotsLeft - 1);
  return {budget, spent, remaining, slotsLeft, maxBid};
}

function assistLine(p, nom){
  const me = myDraftState();
  const bits = [];
  if (p){
    if (myNeeds.needs.length && myNeeds.needs.length < 5){
      const fills = myNeeds.needs.filter(pos=>canPlay(p, pos));
      bits.push(fills.length ? `fills your pos ${fills.join("/")}` : "fills no open role");
    }
    if (isExcluded(p.id)) bits.push("YOU CUT THIS PLAYER");
    if (isWithdrawn(p.id)) bits.push("YOU MARKED THIS PLAYER OFF THE DRAFT");
  }
  if (me){
    if (me.slotsLeft === 0) return `roster full — $${me.remaining ?? "?"} left · let it go`;
    if (me.remaining != null) bits.push(`you: $${me.remaining} left, ${me.slotsLeft} slots`);
    const worth = p ? p.worth : null;
    let cap = me.maxBid;
    if (cap != null || worth != null){
      const rec = Math.min(...[cap, worth].filter(v=>v!=null));
      const cur = (nom && nom.amount) || 0;
      bits.push(rec >= cur + 5
        ? `<b>bid up to ~$${Math.floor(rec/5)*5}</b>` + (worth!=null && cap!=null && cap<worth ? " (budget-capped)" : "")
        : `<b>let it go</b> (${worth!=null && cur>=worth ? "over worth" : "can't afford"})`);
    }
  } else {
    bits.push(`<span class="dim">pick “I am…” (top right) for budget-aware max bid</span>`);
  }
  return bits.join(" · ");
}

// The header ticker is the single live-draft surface now — the old sliding
// banner is retired. This just keeps nomination state + the timer in sync and
// re-renders the ticker.
function renderNomBanner(nom){
  lastNom = nom;
  // render FIRST, then start the clock: startBidClock ticks immediately, so the
  // freshly rewritten #dt-timer gets its real value in the same frame instead
  // of sitting on the "⏱ …" placeholder until the next interval tick
  renderTicker();
  if (nom) startBidClock(nom); else clearInterval(bidClockTimer);
}

// ---- persistent header ticker (the live socket's always-on strip) ----
// Mirrors the nomination banner's data at a glance in the header. lastState is
// the most recent /live/state snapshot, so idle info (round, board count, last
// sale) stays fresh between nominations.
let lastState = null;
function undraftedCount(){
  let n = 0;
  for (const p of DATA) if (!isDrafted(p.id) && inPool(p)) n++;
  return n;
}
function lastSale(){
  const evs = (lastState && lastState.events) || [];
  for (let i = evs.length - 1; i >= 0; i--){
    const e = evs[i];
    if (e.kind === "pick" && !e.is_captain) return e;
  }
  return null;
}
function renderTicker(){
  const box = document.getElementById("drafticker");
  if (!box || !LIVE) return;
  box.classList.add("on");
  const nom = lastNom;
  let lampTxt, html, state;
  if (nom){
    if (!lastMock) box.classList.add("live");  // mock keeps its own purple accent
    state = "block";
    lampTxt = "";   // dot-only live light; the "Nominated" label names the block
    html =
        `<span class="dt-stack"><span class="dt-lbl">Nominated</span>`
      + `<span class="dt-name">${esc(nom.name || "?")}</span></span>`
      + `<span class="dt-stack"><span class="dt-lbl">Bid</span>`
      + `<span class="dt-bidrow"><span class="dt-amt">$${nom.amount || 0}</span>`
      + `<span class="dt-capname">${esc(nom.by || "—")}</span></span></span>`
      + `<span class="dt-time"><span id="dt-timer">⏱ …</span></span>`;
  } else {
    if (!lastMock) box.classList.remove("live");
    state = liveOk ? "ok" : "bad";
    lampTxt = liveOk ? (liveSock ? "Live" : "Live · picks only") : "reconnecting…";
    const bits = [];
    if (lastState && lastState.round != null) bits.push(`Round ${esc(String(lastState.round))}`);
    bits.push(`<b>${undraftedCount()}</b> on board`);
    const ls = lastSale();
    if (ls) bits.push(`last: ${esc(nameOf(ls.steam32))}${ls.cost ? ` $${ls.cost}` : ""}`);
    html = `<span class="dt-idle">`
      + (bits.length ? bits.join(" · ") : "waiting for a nomination…") + `</span>`;
  }
  box.dataset.state = state;
  const lamp = document.getElementById("dt-state");
  if (lamp.textContent !== lampTxt) lamp.textContent = lampTxt;
  // Only touch the DOM when the content actually changes. The 2s poll calls this
  // every cycle; rewriting innerHTML would destroy #dt-timer and reset it to "⏱ …"
  // for a frame each time — that was the blink. The timer placeholder is constant
  // in `html`, so an unchanged nomination skips the rewrite and the interval keeps
  // ticking the SAME element smoothly.
  const main = document.getElementById("dt-main");
  if (main.dataset.sig !== html){
    main.dataset.sig = html;
    main.innerHTML = html;
  }
}

// ticking countdown mirroring the site's bid timer (15s window, resets per
// bid and shrinks — the remaining ms rides along on each bid event).
// measured_at_ms lets us know how long the event took to reach us, so we
// can adjust for network latency.
let bidClockTimer = null, measuredLatency = 0;
function startBidClock(nom){
  clearInterval(bidClockTimer);
  if (!nom) return;
  // measure network latency: how long did this event take to arrive?
  if (nom.measured_at_ms){
    measuredLatency = Math.round(Date.now() - nom.measured_at_ms);
  }
  // Time reference for the countdown. Prefer the latency beacon (SSE path), but
  // fall back to the nomination's server timestamp: the 2s /live/state poll
  // delivers nominations WITHOUT measured_at_ms, so keying only off it made the
  // timer read NaN every poll and stutter. ts is always present.
  const refMs = nom.measured_at_ms ?? (nom.ts ? nom.ts * 1000 : Date.now());
  const tick = ()=>{
    const dt = document.getElementById("dt-timer");
    if (!dt){ clearInterval(bidClockTimer); return; }
    if (mockPaused){ dt.innerHTML = `⏸ <b>paused</b>`; return; }  // frozen while paused
    // elapsed = time since the follower recorded this event
    const left = ((nom.bid_ms ?? 15000) - (Date.now() - refMs)) / 1000;
    dt.innerHTML = `⏱ <b>${Math.max(0, Math.ceil(left))}s</b>`;
  };
  tick();
  bidClockTimer = setInterval(tick, 200);  // tighter update cadence now that we're more accurate
}

// ---- live feed panel (ticker of nominations / bids / picks) ----
const FEEDKEY = "ld2l-feedopen-s" + SEASON;
let lastFeedSig = "";
const nameOf = (s32, fb) => {
  const p = s32 && DATA.find(x=>x.id===s32);
  return p ? p.name : (fb || (s32 ? "#"+s32 : "?"));
};
function feedLine(ev){
  const t = new Date(ev.ts*1000).toTimeString().slice(0,8);
  let cls = "", txt = "";
  if (ev.kind === "pick"){
    const who = ev.captain || (ev.team_id ? "team "+ev.team_id : "?");
    txt = ev.is_captain ? `👑 <b>${esc(nameOf(ev.steam32))}</b> is captain of ${esc(who)}`
        : `🔨 <b>${esc(nameOf(ev.steam32))}</b> — ${ev.cost ? "$"+ev.cost+" to " : ""}${esc(who)}`;
  } else if (ev.kind === "nominate"){
    cls = "nom";
    txt = `🔔 <b>${esc(nameOf(ev.steam32, ev.name))}</b> on the block (by ${esc(ev.by||"?")})`;
  } else if (ev.kind === "bid"){
    txt = `💰 ${esc(ev.by||"?")} bids <b>$${ev.amount ?? "?"}</b>`;
  } else if (ev.kind === "sold"){
    cls = "sold";
    txt = `✅ <b>${esc(nameOf(ev.steam32, ev.name))}</b> sold`;
  } else if (ev.kind === "round"){
    txt = `— round ${ev.round} —`;
  } else {
    txt = esc(ev.text || "");
  }
  return `<div class="fev ${cls}"><span class="ft">${t}</span>${txt}</div>`;
}
function renderFeed(events){
  const sig = events.length + ":" + (events.length ? events[events.length-1].ts : 0);
  if (sig === lastFeedSig) return;   // untouched: don't fight the scrollbar
  lastFeedSig = sig;
  document.getElementById("feedlist").innerHTML =
    events.length ? events.slice().reverse().map(feedLine).join("")
                  : `<div class="dim" style="padding:6px 0">Waiting for draft activity…</div>`;
}
function setFeedOpen(open){
  document.getElementById("feedpanel").classList.toggle("show", open);
  document.getElementById("feedbtn").classList.toggle("on", open);
  localStorage.setItem(FEEDKEY, open ? "1" : "");
}
document.getElementById("feedbtn").addEventListener("click", ()=>
  setFeedOpen(!document.getElementById("feedpanel").classList.contains("show")));
document.getElementById("feedclose").addEventListener("click", ()=>setFeedOpen(false));

function liveApply(st){
  lastState = st;
  liveSock = !!st.socket_on;
  if (st.mock){
    // ---- MOCK MODE: the auction engine is the single source of truth ----
    // Drafted state is REPLACED from the server's picks each poll (a merge
    // would accumulate purchases across runs/resets and show captains
    // overspending), and nothing is written to localStorage.
    MOCKMODE = true;
    MOCKBUDGETS = st.budgets || {};
    MOCKCAPTAINS = new Set(
      (st.mock.teams || [])
        .filter(t => t.steam32 != null)
        .map(t => Number(t.steam32))
    );
    const fresh = {};
    for (const pk of st.picks || []){
      if (pk.is_captain) continue;
      const p = DATA.find(x => x.id === pk.steam32);
      if (p) fresh[p.id] = {p: pk.cost ?? null, t: pk.captain || ""};
    }
    const sig = JSON.stringify(fresh);
    const nomId = st.nomination ? (st.nomination.steam32 || null) : null;
    const nomChanged = nomId !== liveNomId;
    if (nomChanged) liveNomId = nomId;
    if (sig !== mockDraftSig || nomChanged){
      mockDraftSig = sig;
      draftInfo = fresh;               // in-memory only; saveDraft() is gated
      render();
    }
    renderNomBanner(st.nomination);
    renderFeed(st.events || []);
    applyMock(st.mock);
    return;
  }
  // scraped budgets flow in once teams are posted (hand-set values still win)
  if (st.budgets) for (const [c, b] of Object.entries(st.budgets))
    if (BUDGETS[c] == null) BUDGETS[c] = b;
  let changed = false;
  for (const pk of st.picks || []){
    if (pk.is_captain) continue;            // captains joining their own team
    const p = DATA.find(x => x.id === pk.steam32);
    if (!p) continue;
    const cap = pk.captain || "";
    if (!isDrafted(p.id)){
      draftInfo[p.id] = {p: pk.cost ?? null, t: cap};
      changed = true;
    } else {                                 // fill blanks; never fight your edits
      const info = draftInfo[p.id];
      if (info.p == null && pk.cost != null){ info.p = pk.cost; changed = true; }
      if (!info.t && cap){ info.t = cap; changed = true; }
    }
  }
  const nomId = st.nomination ? (st.nomination.steam32 || null) : null;
  if (nomId !== liveNomId){ liveNomId = nomId; changed = true; }
  if (changed){ saveDraft(); render(); }
  renderNomBanner(st.nomination);           // after render so Worth$ is fresh
  renderFeed(st.events || []);
  renderMyCapSel();
  applyMock(st.mock);                        // mock-draft interactive controls
}

function liveChip(){
  return;  // LIVE status now lives in the ticker lamp — no separate chip
  const el = document.getElementById("livechip");
  el.style.display = "";
  el.textContent = liveOk ? (liveSock ? "● LIVE" : "● LIVE (picks only)")
                          : "○ live: reconnecting…";
  el.className = "chip livechip " + (liveOk ? "ok" : "bad");
}

async function livePoll(){
  try{
    const st = await (await fetch("/live/state", {cache: "no-store"})).json();
    liveOk = !!st.poll_ok;
    liveApply(st);
  }catch(e){ liveOk = false; }
  liveChip();
}

// real-time SSE events from the follower: bid/nominate/sold/round push immediately,
// no 2-second poll latency. the polling cycle is a fallback for everything else.
let liveEventSource = null;
function liveSSE(){
  if (liveEventSource) return;
  liveEventSource = new EventSource("/live/events", {withCredentials: false});
  liveEventSource.addEventListener("message", (e)=>{
    try{
      const ev = JSON.parse(e.data);
      if (ev.kind === "nominate"){
        // live nomination: update state immediately, with latency beacon for timer accuracy
        lastNom = {
          steam32: ev.steam32, name: ev.name, by: ev.by, amount: ev.amount,
          // the mock sends its real window (which fast-forward compresses);
          // only the read-only --live follower falls back to the site's 15s
          bid_ms: ev.bid_ms ?? 15000,
          ts: ev.ts, measured_at_ms: ev.measured_at_ms
        };
        liveNomId = ev.steam32 || null;
        renderNomBanner(lastNom);
        mockPatch({phase:"bidding", nominee:{steam32:ev.steam32, name:ev.name},
                   high_bid:ev.amount, high_bidder:ev.by});
        const p = DATA.find(x=>x.id===ev.steam32);
        if (p){ render(); }  // highlight the player row
      } else if (ev.kind === "bid"){
        // live bid: update nomination with new amount + timer
        if (lastNom){
          lastNom.amount = ev.amount ?? lastNom.amount;
          lastNom.bid_ms = ev.bid_ms ?? lastNom.bid_ms;
          lastNom.by = ev.by ?? lastNom.by;
          lastNom.ts = ev.ts;
          lastNom.measured_at_ms = ev.measured_at_ms;  // latency beacon
          renderNomBanner(lastNom);
        }
        mockPatch({phase:"bidding", high_bid:ev.amount, high_bidder:ev.by});
      } else if (ev.kind === "sold"){
        // live hammer: clear nomination, next poll will mark the pick
        liveNomId = null;
        lastNom = null;
        renderNomBanner(null);
        mockPatch({phase:"sold", last_sold: (ev.to != null)
          ? {steam32:ev.steam32, name:ev.name, to:ev.to, price:ev.price, is_me:ev.is_me}
          : (lastMock && lastMock.last_sold)});
      } else if (ev.kind === "pause"){
        // mock pause/resume: freeze or restart the countdown without a poll
        mockPaused = !!ev.paused;
        if (!ev.paused && lastNom && ev.bid_ms != null){
          // resumed mid-bid: restart the clock from the remaining time so it
          // doesn't read as already expired against the stale reference
          lastNom.bid_ms = ev.bid_ms;
          lastNom.measured_at_ms = ev.measured_at_ms;
          lastNom.ts = ev.ts;
          renderNomBanner(lastNom);
        }
        mockPatch({paused: ev.paused});   // repaint the bar (rebuilds the row)
        if (ev.paused) renderNomBanner(lastNom);  // freeze the ticker display
      } else if (ev.kind === "speed"){
        // fast-forward changed (by you, or by the engine braking itself). A live
        // window was rescaled in place, so restart the countdown from the new
        // remaining time — same fix-up resume() needs coming out of a pause.
        if (lastNom && ev.bid_ms != null){
          lastNom.bid_ms = ev.bid_ms;
          lastNom.measured_at_ms = ev.measured_at_ms;
          lastNom.ts = ev.ts;
          renderNomBanner(lastNom);
        }
        mockPatch({speed: ev.speed});
      } else if (ev.kind === "round"){
        // live round change: just for feed, doesn't affect state
      }
    }catch(e){}
  });
  liveEventSource.addEventListener("error", ()=>{
    if (liveEventSource) liveEventSource.close();
    liveEventSource = null;
  });
}
if (LIVE){ setTimeout(liveSSE, 100); }  // start SSE stream after the initial poll

// ---- Mock draft interactive controls -------------------------------------
// Only active when the page is served by `--mock` (the server includes a `mock`
// object in /live/state). Everything else on the board — picks, ticker, feed,
// budgets — already flows through the shared live path; this adds the Start /
// nominate / bid controls the read-only live mode doesn't need.
let lastMock = null, mockOffset = 0, mockPaused = false;
async function mockPost(path, body){
  try{
    const r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(body||{})});
    return await r.json().catch(()=>({}));
  }catch(e){ return {}; }
}
// patch cached mock state from an SSE event so the bar reacts without waiting
// for the next 2s poll
function mockPatch(p){
  if (!lastMock) return;
  Object.assign(lastMock, p);
  mockPaused = !!lastMock.paused;
  lastMock.i_am_high = lastMock.high_bidder === lastMock.me;
  lastMock.can_bid = lastMock.phase === "bidding" && !lastMock.i_am_high && !mockPaused;
  renderMockBar();
}
function applyMock(mock){
  // The mock controls now live inside the header draft ticker; `.mock` grows it
  // into the full auction console (and hides the compact live glance).
  const box = document.getElementById("drafticker");
  if (!box) return;
  if (!mock){ box.classList.remove("mock"); return; }
  lastMock = mock;
  mockPaused = !!mock.paused;
  mockOffset = (mock.now_ms || Date.now()) - Date.now();
  box.classList.add("on", "mock");
  // one-shot sync of the ✕ cut list on entering mock mode, so a page reload or a
  // fresh browser re-arms the fast-forward brake without touching a single ✕
  if (!cutsSynced){ cutsSynced = true; pushCuts(); }
  if (mock.me && myCap !== mock.me){ myCap = mock.me; localStorage.setItem(MYCAPKEY, myCap); }
  renderMockBar();
}
function renderMockBar(){
  const m = lastMock; if (!m) return;
  const seat = document.getElementById("mb-seat");
  const opts = (m.teams||[]).map(t=>t.captain);
  const sig = opts.join("|");
  if (seat.dataset.sig !== sig){ seat.dataset.sig = sig;
    seat.innerHTML = opts.map(c=>`<option>${esc(c)}</option>`).join(""); }
  if (m.me && seat.value !== m.me) seat.value = m.me;
  document.getElementById("mb-start").style.display = (m.phase==="setup") ? "" : "none";
  // Pause only makes sense once a timed window is live (not in setup/done).
  const pauseBtn = document.getElementById("mb-pause");
  const running = ["countdown","nominating","bidding"].includes(m.phase);
  pauseBtn.style.display = running ? "" : "none";
  if (running){
    pauseBtn.textContent = m.paused ? "▶ Resume" : "⏸ Pause";
    pauseBtn.classList.toggle("resume", !!m.paused);
  }
  // speed dial: options come from the server, and the VALUE is read back from it
  // too — so when the engine brakes itself the dial snaps to 1x in front of you
  const sp = document.getElementById("mb-speed");
  const spOpts = (m.speeds||[1]).join("|");
  if (sp.dataset.sig !== spOpts){ sp.dataset.sig = spOpts;
    sp.innerHTML = (m.speeds||[1]).map(x=>`<option value="${x}">${x}x</option>`).join(""); }
  const spNow = String(m.speed || 1);
  if (sp.value !== spNow) sp.value = spNow;
  sp.classList.toggle("ff", (m.speed||1) > 1);

  const meT = (m.teams||[]).find(t=>t.is_me);
  const rosterLabel = m.roster_source === "official" ? "Official" : "Curated";
  let status = `Roster: <b>${rosterLabel}</b>`;
  if (meT)
    status += ` · you: <b>${esc(m.me)}</b> · $${meT.budget} left · ${meT.slots_left} slots`;
  if (meT && (meT.open_pos||[]).length)
    status += ` · need <b>P${meT.open_pos.join("/P")}</b>`;
  if ((m.speed||1) > 1)
    status += ` · <span class="mb-ff">⏩ ${m.speed}x — skipping to your next uncut player</span>`;
  if (m.paused) status += ` · <span class="mb-paused">⏸ paused</span>`;
  if (m.phase==="done") status += " · draft complete";
  document.getElementById("mb-status").innerHTML = status;
  renderMockAuction();
}
// seconds left on the current bid clock (from the last nominate/bid event's
// latency-corrected timestamp) — shared by the render and the 200ms tick so a
// rewrite never shows a placeholder
function mockBidLeft(){
  if (!lastNom) return null;
  const refMs = lastNom.measured_at_ms ?? (lastNom.ts ? lastNom.ts*1000 : Date.now());
  return Math.max(0, Math.ceil(((lastNom.bid_ms ?? 15000) - (Date.now() - refMs)) / 1000));
}
function mockCdLeft(){
  const m = lastMock;
  if (!m || !m.deadline_ms) return null;
  return Math.max(0, Math.ceil((m.deadline_ms - (Date.now()+mockOffset)) / 1000));
}
// update the bid-war parts of the row IN PLACE: amount, high bidder, button
// labels/enabled state, input min. The input element itself is never replaced
// while the same player is on the block, so typing a custom bid survives
// incoming bids (a full rewrite would wipe the field mid-keystroke).
function updateBidRow(m){
  const hb = m.high_bid||0, canBid = !!m.can_bid;
  const amt = document.getElementById("mb-amt");
  if (!amt) return;
  amt.textContent = `$${hb}`;
  const high = document.getElementById("mb-high");
  if (high) high.innerHTML = m.high_bidder
    ? `high: ${esc(m.high_bidder)}${m.i_am_high?" (you)":""}` : "opening";
  const b1 = document.getElementById("mb-b1");
  if (b1) b1.textContent = `+1 ($${hb+1})`;
  ["mb-b1","mb-b5","mb-b25","mb-cust","mb-go"].forEach(id=>{
    const n = document.getElementById(id);
    if (n) n.disabled = !canBid;
  });
  const inp = document.getElementById("mb-cust");
  if (inp){
    inp.min = hb+1;
    // Auto-track the price ONLY while the field is untouched. A focus check
    // alone isn't enough: the moment the user reaches for the Bid button the
    // field blurs, and the next incoming AI bid would wipe their typed number
    // before the click lands. Once they've typed (dirty), the field is theirs
    // until they submit or the next player comes up.
    if (document.activeElement !== inp && !inp.dataset.dirty) inp.value = hb+1;
  }
  const win = document.getElementById("mb-win");
  if (win) win.style.display = m.i_am_high ? "" : "none";
}
function mockBidStep(n){ if (lastMock) mockBid((lastMock.high_bid||0)+n); }
function mockBidCustom(){
  const i = document.getElementById("mb-cust");
  if (!i) return;
  const v = parseInt(i.value, 10);
  delete i.dataset.dirty;   // submitted — resume price tracking
  mockBid(v);
}
function renderMockAuction(){
  const m = lastMock; const el = document.getElementById("mb-auction");
  const nomId = m.nominee ? m.nominee.steam32 : "";
  const ls = m.last_sold;
  // STRUCTURAL signature only — high_bid / high_bidder / can_bid are updated
  // in place by updateBidRow so the input isn't rebuilt on every bid
  const sig = [m.phase, m.my_turn, nomId, m.paused,
               (m.pool||[]).length, ls ? ls.steam32+":"+ls.price : ""].join("|");
  if (el.dataset.sig === sig){
    if (m.phase==="bidding") updateBidRow(m);
    return;
  }
  el.dataset.sig = sig;
  // who bought whom for how much — rides on the right of every active phase
  const lastHtml = ls
    ? `<span class="mb-last">last: <b>${esc(ls.to)}</b>${ls.is_me?" (you)":""} bought `
      + `<b>${esc(ls.name)}</b> for <span class="mb-price">$${ls.price}</span></span>`
    : "";
  if (m.phase==="countdown"){
    el.className = "mb-row mb-auction live";
    el.innerHTML = `<span class="mb-cd">The draft is starting in <b id="mb-cd">${mockCdLeft() ?? ""}</b></span>`;
  } else if (m.phase==="nominating" && m.my_turn){
    const pool = m.pool||[];
    const dis = m.paused ? " disabled" : "";
    el.className = "mb-row mb-auction live";
    el.innerHTML =
        `<span class="mb-onblock">🟡 <b>Your nomination</b> — pick a player:</span>`
      + `<select id="mb-nom"${dis}>${pool.map(p=>`<option value="${p.steam32}">${esc(p.name)}`
          + (p.worth!=null?` ($${p.worth})`:"")+`</option>`).join("")}</select>`
      + `<label class="mb-lbl">open $<input id="mb-open" type="number" min="${m.min_bid||1}" value="${m.min_bid||1}" style="width:58px"${dis}></label>`
      + `<button class="chip mb-bid" id="mb-nom-go"${dis}>Nominate</button>`
      + (m.paused ? `<span class="mb-paused">⏸ paused</span>` : "")
      + lastHtml;
  } else if (m.phase==="nominating"){
    el.className = "mb-row mb-auction live";
    el.innerHTML = `<span class="mb-onblock">Waiting for <b>${esc(m.nominator||"…")}</b> to nominate…</span>`
      + lastHtml;
  } else if (m.phase==="bidding" && m.nominee){
    el.className = "mb-row mb-auction live";
    el.innerHTML =
        `<span class="mb-onblock">🔨 <b>${esc(m.nominee.name)}</b></span>`
      + `<span class="mb-amt" id="mb-amt"></span>`
      + `<span class="mb-onblock" id="mb-high"></span>`
      + `<span class="mb-time" id="mb-time">`
        + (m.paused ? `<span class="mb-paused">⏸ paused</span>`
                    : `⏱ <b>${mockBidLeft() ?? "–"}s</b>`) + `</span>`
      + `<button class="chip mb-bid" id="mb-b1" onclick="mockBidStep(1)"></button>`
      + `<button class="chip mb-bid" id="mb-b5" onclick="mockBidStep(5)">+5</button>`
      + `<button class="chip mb-bid" id="mb-b25" onclick="mockBidStep(25)">+25</button>`
      + `<input id="mb-cust" type="number" style="width:62px">`
      + `<button class="chip mb-bid" id="mb-go" onclick="mockBidCustom()">Bid</button>`
      + `<span class="mb-win" id="mb-win" style="display:none">you're winning</span>`
      + lastHtml;
    updateBidRow(m);
  } else {
    el.className = "mb-row mb-auction";
    el.innerHTML = (m.phase==="setup"
      ? `<span class="mb-onblock dim">Pick your seat and press Start.</span>` : "")
      + lastHtml;
  }
}
async function mockBid(amount){
  if (!amount || amount<=0) return;
  const r = await mockPost("/mock/bid", {amount});
  if (!r.ok && r.msg) flashMock(r.msg);
}
function flashMock(msg){
  const s = document.getElementById("mb-status");
  if (!s) return;
  s.innerHTML = `<b style="color:#e67e22">${esc(msg)}</b>`;
  setTimeout(()=>{ if (lastMock) renderMockBar(); }, 1600);
}
document.getElementById("mb-seat").addEventListener("change", e=> mockPost("/mock/me", {captain:e.target.value}));
document.getElementById("mb-start").addEventListener("click", ()=> mockPost("/mock/start"));
document.getElementById("mb-pause").addEventListener("click", ()=>
  mockPost("/mock/pause").then(r=>{ if (r && r.paused != null) mockPatch({paused: r.paused}); }));
document.getElementById("mb-speed").addEventListener("change", e=>
  mockPost("/mock/speed", {x: parseFloat(e.target.value)})
    .then(r=>{ if (r && r.speed != null) mockPatch({speed: r.speed}); }));
document.getElementById("mb-reset").addEventListener("click", ()=>{
  if (confirm("Reset the mock draft? (targets are kept)")) mockPost("/mock/reset"); });
document.getElementById("mb-auction").addEventListener("keydown", e=>{
  if (e.target.id === "mb-cust" && e.key === "Enter") mockBidCustom();
});
document.getElementById("mb-auction").addEventListener("input", e=>{
  if (e.target.id !== "mb-cust") return;
  // typed = theirs; cleared = resume auto-tracking the price
  if (e.target.value) e.target.dataset.dirty = "1";
  else delete e.target.dataset.dirty;
});
document.getElementById("mb-auction").addEventListener("click", e=>{
  if (e.target.id !== "mb-nom-go") return;
  const sel = document.getElementById("mb-nom");
  const open = parseInt((document.getElementById("mb-open")||{}).value||"1", 10);
  if (sel && sel.value) mockPost("/mock/nominate", {steam32:parseInt(sel.value,10), opening:open})
    .then(r=>{ if (!r.ok && r.msg) flashMock(r.msg); });
});
setInterval(()=>{
  const m = lastMock; if (!m) return;
  if (m.paused) return;              // clock frozen — leave the display put
  if (m.phase==="countdown"){
    const el = document.getElementById("mb-cd");
    const left = mockCdLeft();
    if (el && left != null) el.textContent = left;
  } else if (m.phase==="bidding"){
    const el = document.getElementById("mb-time");
    const left = mockBidLeft();
    if (el && left != null) el.innerHTML = `⏱ <b>${left}s</b>`;
  }
}, 200);

render();
sizeWrap();
if (LIVE){
  renderTicker();          // the header draft ticker is the single live surface
  livePoll();
  setInterval(livePoll, 2000);
}
</script>
</body>
</html>
"""
