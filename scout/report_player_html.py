"""Per-player HTML scout reports.

One self-contained page per player (embedded CSS + medal art data URIs, no
external requests — opens straight off disk), plus an index.html linking them.
Presents the metrics analysis.py already computes: winrate breakdowns, an
east-server (US East = the LD2L server) vulnerability read, strongest heroes,
a template career narrative, per-position ratings on the tool's Plays-Like
scale, and a chat toxicity report from the OpenDota word cloud.
"""

import glob
import html
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

from .analysis import (POS_NAMES, career_narrative, measured_roles,
                       position_ratings, value_tier)
from .report_html import _rank_icon_uris
from .report_xlsx import db_url, ld2l_url, od_url, steam_url

E = html.escape


# ---------------------------------------------------------------- small bits
def _medal_html(tier, icons, size=44):
    """Layered medal badge (base shield + star overlay) as inline <img>s."""
    if not tier or not icons:
        return ""
    base = icons.get(f"rank_icon_{tier // 10}")
    if not base:
        return ""
    star_uri = icons.get(f"rank_star_{tier % 10}") if (tier % 10 and tier < 80) else None
    star = f'<img src="{star_uri}" alt="">' if star_uri else ""
    return (f'<span class="medal" style="width:{size}px;height:{size}px">'
            f'<img src="{base}" alt="">{star}</span>')


def _wr_class(wr):
    return "good" if wr >= 55 else "warn" if wr >= 48 else "crit"


def _wr_row(label, wr, games, wins=None, losses=None):
    if wr is None or not games:
        return (f'<tr><td>{E(label)}</td>'
                f'<td class="dim" colspan="2">no data</td></tr>')
    if wins is not None and losses is not None:
        rec = f"{wins}–{losses}"
    else:
        rec = f"{games}g"
    cls = _wr_class(wr)
    return (f'<tr><td>{E(label)}</td>'
            f'<td class="num">{wr}% <span class="dim">({rec})</span></td>'
            f'<td class="barcell"><span class="bar">'
            f'<i class="{cls}" style="width:{min(100, wr)}%"></i></span></td></tr>')


def _chip(text, cls=""):
    return f'<span class="chip {cls}">{E(text)}</span>'


def _word_cloud(words, toxic_words):
    if not words:
        return '<p class="dim">no chat words</p>'
    counts = [c for _, c in words]
    lo, hi = math.log(min(counts) + 1), math.log(max(counts) + 1)
    span = (hi - lo) or 1.0
    out = []
    for w, c in words:
        t = (math.log(c + 1) - lo) / span
        size = 11 + round(t * 15)
        cls = "tox" if w in toxic_words else ""
        out.append(f'<span class="{cls}" style="font-size:{size}px" '
                   f'title="{c}×">{E(w)}</span>')
    return '<div class="cloud">' + " ".join(out) + "</div>"


# ---------------------------------------------------------------- CSS
PAGE_CSS = """
:root{
  --page:#0e1116; --surface:#161b22; --card:#12171e; --raised:#1c222c;
  --ink:#ece4d6; --ink2:#b7bcc4; --muted:#7b8595;
  --grid:#28303b; --border:rgba(236,231,221,.09);
  --gold:#d9a441; --gold-soft:rgba(217,164,65,.12); --gold-line:rgba(217,164,65,.35);
  --good:#57a86b; --warn:#d99a3c; --crit:#cf5442; --accent:#5b93d6;
  --tint-good:rgba(87,168,107,.15); --tint-warn:rgba(217,154,60,.16);
  --tint-crit:rgba(207,84,66,.16); --tint-accent:rgba(91,147,214,.14);
  /* legacy aliases kept so existing bar/tag classes still resolve */
  --s1:var(--accent); --s2:var(--good); --s3:var(--gold);
  --mono:ui-monospace,"Cascadia Code","SF Mono","Segoe UI Mono",Menlo,Consolas,monospace;
  --sans:"Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;
}
@media (prefers-color-scheme:light){
  /* parchment dossier — warm paper, brass, Radiant/Dire deepened */
  :root{ --page:#e9e2d3; --surface:#f7f2e7; --card:#fffdf6; --raised:#fffdf6;
    --ink:#241d12; --ink2:#4b4437; --muted:#8a8271;
    --grid:#d8cfbb; --border:rgba(36,29,18,.12);
    --gold:#a9761b; --gold-soft:rgba(169,118,27,.11); --gold-line:rgba(169,118,27,.4);
    --good:#3f8a54; --warn:#a9711d; --crit:#b23a2c; --accent:#37639e;
    --tint-good:rgba(63,138,84,.14); --tint-warn:rgba(169,113,29,.14);
    --tint-crit:rgba(178,58,44,.13); --tint-accent:rgba(55,99,158,.12); }
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:14px/1.55 var(--sans);
  background-image:radial-gradient(1200px 480px at 12% -8%,var(--gold-soft),transparent 60%);
  background-attachment:fixed;}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--gold);outline-offset:2px;border-radius:3px}
.wrap{max-width:1060px;margin:0 auto;padding:18px 20px 64px}

/* utility: mono signage voice */
.kick{font:600 10.5px/1 var(--mono);letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.up{color:var(--good);font-weight:700} .down{color:var(--crit);font-weight:700}

/* ---- top bar ---- */
.topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding-bottom:12px;margin-bottom:16px;border-bottom:1px solid var(--gold-line)}
.brand{font:600 11px/1 var(--mono);letter-spacing:.24em;text-transform:uppercase;color:var(--muted)}
.brand b{color:var(--gold);font-weight:700}
.back{font:600 11px/1 var(--mono);letter-spacing:.08em;color:var(--muted)}
.back a{color:var(--muted)} .back a:hover{color:var(--gold);text-decoration:none}

/* ---- hero / dossier head ---- */
header.player{display:grid;grid-template-columns:auto 1fr auto;gap:8px 20px;
  align-items:center;margin-bottom:14px}
.medal{position:relative;display:inline-block;flex:0 0 auto;grid-column:1;grid-row:1;
  filter:drop-shadow(0 0 10px var(--gold-soft))}
.medal img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
.who{grid-column:2;grid-row:1}
.who h1{margin:0;font:800 30px/1.04 var(--sans);letter-spacing:-.015em}
.who .rank{color:var(--ink2);font-size:13px;margin-top:4px}
.who .chips{margin-top:8px}
.grade{grid-column:3;grid-row:1;justify-self:end;text-align:center;min-width:96px;
  border:1px solid var(--gold-line);border-radius:10px;padding:8px 14px 9px;
  background:linear-gradient(180deg,var(--gold-soft),transparent)}
.grade .gl{font:800 40px/1 var(--sans);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.grade .gt{font:600 9.5px/1.2 var(--mono);letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);margin-top:4px}
.grade.g-hi .gl,.grade.g-good .gl{color:var(--good)}
.grade.g-hi{border-color:var(--good)} .grade.g-good .gl{opacity:.92}
.grade.g-mid .gl{color:var(--ink)}
.grade.g-lo .gl{color:var(--warn)} .grade.g-lo{border-color:var(--warn)}
.grade.g-crit .gl{color:var(--crit)} .grade.g-crit{border-color:var(--crit)}
.grade.g-u .gl{color:var(--gold);font-size:30px} .grade.g-u{border-color:var(--gold-line)}
.links{grid-column:2/-1;grid-row:2;font:600 11px/1 var(--mono);letter-spacing:.05em;
  display:flex;gap:16px;flex-wrap:wrap;margin-top:2px}

/* ---- readout strip (instrument panel) ---- */
.readout{display:flex;flex-wrap:wrap;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;overflow:hidden;margin:2px 0 14px}
.readout .cell{flex:1 1 0;min-width:104px;padding:9px 14px;
  border-left:1px solid var(--grid)}
.readout .cell:first-child{border-left:none}
.readout .rl{font:600 9px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);margin-bottom:5px}
.readout .rv{font:700 20px/1 var(--sans);font-variant-numeric:tabular-nums}
.readout .rv small{font-size:12px;font-weight:600;color:var(--muted)}

/* ---- gap gauge (signature) ---- */
.gauge{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:24px 22px 16px;margin:0 0 16px}
.gauge-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  flex-wrap:wrap;margin:0 0 26px}
.gauge-head .lg{font-size:12px;color:var(--ink2)}
.gauge-head .lg b{color:var(--ink)}
.gauge-track{position:relative;height:8px;border-radius:5px;background:var(--grid);
  margin:0 4px}
.gauge-unc{position:absolute;top:-2px;height:12px;border-radius:6px;
  background:var(--gold-soft);border:1px solid var(--gold-line)}
.gauge-span{position:absolute;top:0;height:8px;border-radius:5px}
.gauge-span.up{background:linear-gradient(90deg,var(--grid),var(--good))}
.gauge-span.down{background:linear-gradient(90deg,var(--crit),var(--grid))}
.gauge-mk{position:absolute;top:-5px;width:2px;height:18px;transform:translateX(-50%)}
.gauge-mk.listed{background:var(--ink2)}
.gauge-mk.plays{background:var(--gold);width:3px;box-shadow:0 0 6px var(--gold-line)}
.gauge-lab{position:absolute;transform:translateX(-50%);white-space:nowrap;
  font:600 10.5px/1.2 var(--mono);letter-spacing:.02em;text-align:center}
.gauge-lab.plays{top:-24px;color:var(--gold)}
.gauge-lab.listed{top:22px;color:var(--ink2)}
.gauge-axis{display:flex;justify-content:space-between;margin:34px 2px 0;
  font:500 9.5px/1 var(--mono);letter-spacing:.08em;color:var(--muted)}
@keyframes gaugegrow{from{width:0}}
@media(prefers-reduced-motion:no-preference){
  .gauge-span,.gauge-unc{animation:gaugegrow .7s cubic-bezier(.2,.7,.3,1) both}
}

/* ---- chips ---- */
.chip{display:inline-block;border:1px solid var(--grid);background:var(--raised);
  color:var(--ink2);border-radius:5px;padding:3px 9px;
  font:600 11px/1.3 var(--mono);letter-spacing:.04em;margin:2px 4px 0 0}
.chip.good{background:var(--tint-good);border-color:var(--good);color:var(--good)}
.chip.warn{background:var(--tint-warn);border-color:var(--warn);color:var(--warn)}
.chip.crit{background:var(--tint-crit);border-color:var(--crit);color:var(--crit)}
.chip.accent{background:var(--tint-accent);border-color:var(--accent);color:var(--accent)}

/* ---- assessment / field note ---- */
.narrative{position:relative;background:var(--card);border:1px solid var(--border);
  border-left:2px solid var(--gold);border-radius:8px;padding:14px 16px 15px;
  margin-bottom:18px;font-size:14.5px;line-height:1.62;color:var(--ink2)}
.narrative .fl{display:block;margin-bottom:6px}

/* ---- cards ---- */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.card h2{margin:0 0 12px;font:600 10.5px/1 var(--mono);letter-spacing:.18em;
  text-transform:uppercase;color:var(--gold);display:flex;align-items:center;gap:9px}
.card h2::before{content:"";width:12px;height:2px;background:var(--gold);
  opacity:.75;flex:none;border-radius:1px}
.card.span2{grid-column:1/-1}
table.kv{width:100%;border-collapse:collapse;font-size:13px}
table.kv td{padding:6px 4px;border-bottom:1px solid var(--grid);vertical-align:middle}
table.kv tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.dim{color:var(--muted)}
.table-scroll{overflow-x:auto}
.table-scroll .postbl{min-width:720px}
.esports-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:8px;margin-bottom:14px}
.esports-stat{background:var(--raised);border:1px solid var(--grid);border-radius:7px;
  padding:9px 11px}
.esports-stat b{display:block;font-size:17px;font-variant-numeric:tabular-nums}
.esports-stat span{font:600 9px/1 var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted)}
.result-w{color:var(--good);font-weight:700}.result-l{color:var(--crit);font-weight:700}
.barcell{width:34%} .bar{display:block;height:7px;background:var(--grid);border-radius:5px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:5px} .bar i.good{background:var(--good)}
.bar i.warn{background:var(--warn)} .bar i.crit{background:var(--crit)} .bar i.accent{background:var(--accent)}
.verdict{font:700 15px/1.3 var(--sans);margin:2px 0 10px}
.verdict.good{color:var(--good)} .verdict.warn{color:var(--warn)} .verdict.crit{color:var(--crit)}
.postbl{width:100%;border-collapse:collapse;font-size:13px}
.postbl th{text-align:left;font:600 9.5px/1 var(--mono);letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);padding:4px 4px 6px;border-bottom:1px solid var(--grid)}
.postbl td{padding:6px 4px;border-bottom:1px solid var(--grid)}
.postbl tr.primary{background:var(--tint-accent)}
.tag{font:600 9.5px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;
  border-radius:4px;padding:2px 6px;border:1px solid var(--grid);color:var(--muted)}
.tag.measured{color:var(--good);border-color:var(--good)}
.tag.est,.tag.part-time{color:var(--warn);border-color:var(--warn)}
/* signed bar: centre line is the player's base skill, bars run both ways */
.dbar{position:relative;display:block;height:5px;width:76px;margin-top:3px;
  background:var(--grid);border-radius:3px}
.dbar::before{content:"";position:absolute;left:50%;top:-1px;width:1px;
  height:7px;background:var(--muted);opacity:.65}
.dbar i{position:absolute;top:0;height:5px;border-radius:3px}
.dbar i.good{background:var(--good)} .dbar i.crit{background:var(--crit)}
.why summary{cursor:pointer;color:var(--muted);font-size:12px}
.why summary::marker{color:var(--muted)}
.why ul{margin:5px 0 2px;padding-left:14px;list-style:none}
.why li{display:flex;justify-content:space-between;gap:10px;font-size:11.5px;
  color:var(--ink2);padding:1px 0}
.why li b{font:600 11px/1.5 var(--mono);flex:none}
.why li b.good{color:var(--good)} .why li b.crit{color:var(--crit)}
.meter{height:12px;background:var(--grid);border-radius:7px;overflow:hidden;margin:8px 0}
.meter i{display:block;height:100%;border-radius:7px}
.cloud{line-height:2.15} .cloud span{color:var(--ink2);margin-right:7px}
.cloud span.tox{color:var(--crit);font-weight:700}
.hero{display:inline-block;background:var(--raised);border:1px solid var(--grid);
  border-radius:6px;padding:3px 9px;margin:2px 3px 2px 0;font-size:12.5px}
.hero.sig{border-color:var(--good);color:var(--good)}
footer{margin-top:28px;color:var(--muted);font:500 11px/1.55 var(--mono);
  letter-spacing:.02em;border-top:1px solid var(--grid);padding-top:14px}
.note{color:var(--muted);font-size:11px;margin-top:8px}

@media(max-width:560px){
  header.player{grid-template-columns:auto 1fr}
  .grade{grid-column:1/-1;justify-self:start;margin-top:6px}
  .links{grid-column:1/-1}
  .who h1{font-size:24px}
}
"""

INDEX_CSS = PAGE_CSS + """
.idxhead{margin:2px 0 18px}
.idxhead h1{margin:0;font:800 30px/1.04 var(--sans);letter-spacing:-.015em}
.idxhead .sub{color:var(--muted);font:600 11px/1 var(--mono);
  letter-spacing:.08em;margin-top:8px}
table.idx{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);
  border:1px solid var(--border);border-radius:10px;overflow:hidden;font-size:13px}
table.idx th{text-align:left;font:600 9.5px/1 var(--mono);letter-spacing:.12em;
  text-transform:uppercase;color:var(--gold);
  padding:11px 12px;border-bottom:1px solid var(--gold-line);background:var(--surface)}
table.idx td{padding:9px 12px;border-bottom:1px solid var(--grid)}
table.idx tr:last-child td{border-bottom:none}
table.idx tbody tr:hover td{background:var(--tint-accent)}
table.idx td:first-child{font-weight:600}
.vg{font:800 13px/1 var(--sans);font-variant-numeric:tabular-nums}
.vg.g-hi,.vg.g-good{color:var(--good)} .vg.g-mid{color:var(--ink)}
.vg.g-lo{color:var(--warn)} .vg.g-crit{color:var(--crit)} .vg.g-u{color:var(--gold)}
"""


# ---------------------------------------------------------------- cards
def _winrate_card(d):
    rows = [_wr_row("Lifetime", d["winrate"] if d["total_matches"] else None,
                    d["total_matches"], d["wins"], d["losses"])]
    f30, f90 = d["form30"], d["form90"]
    rows.append(_wr_row("Last 30 days", f30["winrate"] if f30 else None,
                        f30["games"] if f30 else 0,
                        f30["wins"] if f30 else None, f30["losses"] if f30 else None))
    rows.append(_wr_row("Last 90 days", f90["winrate"] if f90 else None,
                        f90["games"] if f90 else 0,
                        f90["wins"] if f90 else None, f90["losses"] if f90 else None))
    rows.append(_wr_row("Solo queue", d["solo_wr"], d["solo_n"],
                        d["solo_w"], (d["solo_n"] - d["solo_w"]) if d["solo_n"] else None))
    rows.append(_wr_row("Party queue", d["party_wr"], d["party_n"]))
    if d["up_n"]:
        rows.append(_wr_row("Above own bracket", d["up_wr"], d["up_n"],
                            d["up_w"], d["up_n"] - d["up_w"]))
    flags = ""
    if d["hot"]:
        flags += _chip("Hot streak", "good")
    if d["cold"]:
        flags += _chip("Cold streak", "crit")
    return (f'<div class="card"><h2>Winrate breakdown</h2>'
            f'<table class="kv">{"".join(rows)}</table>{flags}</div>')


def _date(unix_ts):
    if not unix_ts:
        return "—"
    try:
        return datetime.fromtimestamp(
            int(unix_ts), tz=timezone.utc
        ).strftime("%Y-%m-%d")
    except (OSError, OverflowError, TypeError, ValueError):
        return "—"


def _record(wins, losses):
    return f"{wins}–{losses}"


def _league_row(league):
    first, latest = _date(league.get("first")), _date(league.get("latest"))
    dates = latest if first == latest else f"{first} – {latest}"
    heroes = ", ".join(
        f'{E(str(hero.get("name") or "Unknown"))} ({hero.get("games", 0)}g)'
        for hero in (league.get("heroes") or [])
    ) or "—"
    wr = league.get("winrate")
    wr_text = f"{wr}%" if wr is not None else "—"
    return (
        f'<tr><td>{E(str(league.get("name") or "Unknown league"))}</td>'
        f'<td>{dates}</td>'
        f'<td class="num">{league.get("games", 0)}</td>'
        f'<td class="num">{_record(league.get("wins", 0), league.get("losses", 0))}</td>'
        f'<td class="num">{wr_text}</td><td>{heroes}</td></tr>'
    )


def _match_row(match):
    result = match.get("result") or "?"
    result_cls = "result-w" if result == "W" else "result-l" if result == "L" else "dim"
    kda = "/".join(
        "—" if match.get(key) is None else str(match[key])
        for key in ("kills", "deaths", "assists")
    )
    match_id = match.get("match_id")
    link = (
        f'<a href="https://www.opendota.com/matches/{E(str(match_id))}" '
        f'target="_blank" rel="noopener">{E(str(match_id))}</a>'
        if match_id is not None else "—"
    )
    return (
        f'<tr><td>{_date(match.get("start_time"))}</td>'
        f'<td>{E(str(match.get("league_name") or "Unknown league"))}</td>'
        f'<td>{E(str(match.get("hero") or "Unknown"))}</td>'
        f'<td class="{result_cls}">{E(str(result))}</td>'
        f'<td class="num">{kda}</td>'
        f'<td class="num">{match.get("gpm") if match.get("gpm") is not None else "—"}</td>'
        f'<td class="num">{match.get("xpm") if match.get("xpm") is not None else "—"}</td>'
        f'<td>{link}</td></tr>'
    )


def _esports_card(d):
    """Verified ticketed career and recent league history from OpenDota."""
    status = d.get("esports_status", "unavailable")
    if status == "unavailable":
        return (
            '<div class="card span2"><h2>Ticketed esports history</h2>'
            '<p class="dim">Ticketed history unavailable. Run online to query '
            'OpenDota Explorer.</p></div>'
        )
    if not d.get("esports_games"):
        return (
            '<div class="card span2"><h2>Ticketed esports history</h2>'
            '<p class="dim">No ticketed matches found for this player.</p></div>'
        )

    career_wr = d.get("esports_winrate")
    recent_wr = d.get("esports_6mo_winrate")
    summaries = [
        (
            "Career",
            f'{_record(d.get("esports_wins", 0), d.get("esports_losses", 0))} '
            f'({career_wr}%) · {d.get("esports_games", 0)} games',
        ),
        (
            "Last 6 months",
            (
                f'{_record(d.get("esports_6mo_wins", 0), d.get("esports_6mo_losses", 0))} '
                f'({recent_wr}%) · {d.get("esports_6mo_games", 0)} games'
                if d.get("esports_6mo_games") else "No ticketed games"
            ),
        ),
        (
            "Leagues",
            f'{d.get("esports_league_count", 0)} · '
            f'{_date(d.get("esports_first"))} to {_date(d.get("esports_latest"))}',
        ),
    ]
    summary_html = "".join(
        f'<div class="esports-stat"><span>{E(label)}</span><b>{E(value)}</b></div>'
        for label, value in summaries
    )

    league_rows = "".join(
        _league_row(league) for league in d.get("esports_leagues", [])
    )
    leagues = (
        '<h2 style="margin-top:16px">League history · all time</h2>'
        '<div class="table-scroll"><table class="postbl"><thead><tr>'
        '<th>League</th><th>Dates</th><th>Games</th><th class="num">Record</th>'
        '<th class="num">WR</th><th>Top heroes</th></tr></thead>'
        f'<tbody>{league_rows}</tbody></table></div>'
    )

    mode = d.get("esports_recent_mode")
    if mode == "six_months":
        recent_label = "Last 6 months"
        fallback_note = ""
    elif mode == "latest_leagues":
        recent_label = "Recent match detail"
        fallback_note = (
            '<p class="note">No ticketed matches in the last 6 months; showing '
            'matches from the 3 most recent leagues.</p>'
        )
    else:
        recent_label, fallback_note = "Recent match detail", ""
    match_rows = "".join(
        _match_row(match) for match in d.get("esports_recent_matches", [])
    )
    matches = (
        f'<h2 style="margin-top:16px">{E(recent_label)}</h2>{fallback_note}'
        '<div class="table-scroll"><table class="postbl"><thead><tr>'
        '<th>Date</th><th>League</th><th>Hero</th><th>Result</th>'
        '<th class="num">K/D/A</th><th class="num">GPM</th>'
        '<th class="num">XPM</th><th>Match</th></tr></thead>'
        f'<tbody>{match_rows}</tbody></table></div>'
    )

    warnings = ""
    if status == "stale":
        warnings += '<p class="note warn">Showing cached data because OpenDota Explorer was unavailable.</p>'
    if d.get("esports_incomplete"):
        warnings += '<p class="note warn">Explorer returned its row limit; totals may be incomplete.</p>'
    return (
        '<div class="card span2"><h2>Ticketed esports history</h2>'
        f'<div class="esports-summary">{summary_html}</div>'
        f'{warnings}{leagues}{matches}</div>'
    )


def _east_card(d):
    n, w, wr = d["use_n"], d["use_w"], d["use_wr"]
    if not n:
        body = ('<p class="dim">No US East games in the sample — can’t read '
                'their form on the LD2L server yet (needs an online run).</p>')
        return f'<div class="card"><h2>US East vulnerability</h2>{body}</div>'
    if n < 10:
        vcls, vtxt = "warn", f"Thin sample on East ({n} games)"
    elif wr < 45:
        vcls, vtxt = "crit", f"Vulnerable on East — {wr}%"
    elif wr < 50:
        vcls, vtxt = "warn", f"Below even on East — {wr}%"
    else:
        vcls, vtxt = "good", f"Holds up on East — {wr}%"
    diff = ""
    if d["winrate"] and n >= 10:
        delta = round(wr - d["winrate"], 1)
        sign = "+" if delta >= 0 else ""
        diff = (f'<tr><td>vs lifetime {d["winrate"]}%</td>'
                f'<td class="num">{sign}{delta} pts</td><td></td></tr>')
    mix = (f'<p class="note">Recent server mix: {E(d["server_mix"])}</p>'
           if d["server_mix"] else "")
    bar = (f'<span class="bar"><i class="{_wr_class(wr)}" '
           f'style="width:{min(100, wr)}%"></i></span>')
    return (f'<div class="card"><h2>US East vulnerability</h2>'
            f'<div class="verdict {vcls}">{E(vtxt)}</div>'
            f'<table class="kv"><tr><td>Record on US East</td>'
            f'<td class="num">{w}–{n - w} ({wr}%)</td>'
            f'<td class="barcell">{bar}</td></tr>{diff}</table>{mix}</div>')


def _heroes_card(d):
    top = "".join(f'<span class="hero">{E(h)}</span>' for h in d["top_heroes"]) \
        or '<span class="dim">no hero data</span>'
    sig = ""
    if d["signature_heroes"]:
        sig = "<h2 style='margin-top:12px'>Signature heroes (100g+, 53%+)</h2>" + "".join(
            f'<span class="hero sig">{E(s["hero"])} '
            f'<span class="dim">{s["games"]}g {s["winrate"]}%</span></span>'
            for s in d["signature_heroes"][:8])
    vers = (f'<p class="note">{d["versatility"]} heroes played; '
            f'{len(d["recent_heroes"])} distinct in recent games.</p>'
            if d["versatility"] else "")
    return (f'<div class="card"><h2>Strongest heroes</h2>{top}{sig}{vers}</div>')


def _lanes_card(d):
    lanes = d["lane_pcts"] or {}
    rows = ""
    for lane in ("Safe", "Mid", "Off"):
        pct = lanes.get(lane, 0)
        gpm = d["lane_gpm"].get(lane)
        gtxt = f' <span class="dim">{gpm} gpm</span>' if gpm else ""
        rows += (f'<tr><td>{lane}{gtxt}</td><td class="num">{pct}%</td>'
                 f'<td class="barcell"><span class="bar"><i class="accent" '
                 f'style="width:{min(100, pct)}%"></i></span></td></tr>')
    if not rows:
        rows = '<tr><td class="dim" colspan="3">no lane data</td></tr>'

    pr = position_ratings(d)
    ptbl = ""
    if pr:
        # scale every delta bar against the widest swing on the page, so the
        # bars compare positions against each other rather than a fixed cap
        widest = max((abs(r["delta"]) for r in pr["ratings"].values()), default=0) or 1
        body = ""
        for pos in range(1, 6):
            r = pr["ratings"][pos]
            cls = "primary" if pr.get("primary") == pos else ""
            star = " ★" if pr.get("primary") == pos else ""
            delta = r["delta"]
            width = min(50, abs(delta) / widest * 50)
            # anchor both directions on the centre line: positives grow right
            # from it, negatives grow left with their right edge pinned to it
            side = "left:50%" if delta >= 0 else "right:50%"
            dcls = "good" if delta >= 0 else "crit"
            dbar = (f'<span class="dbar"><i class="{dcls}" '
                    f'style="{side};width:{width}%"></i></span>')
            why = "".join(
                f'<li><span>{E(w["reason"])}</span>'
                f'<b class="{"good" if w["mmr"] >= 0 else "crit"}">'
                f'{w["mmr"]:+}</b></li>'
                for w in r["why"])
            detail = (f'<details class="why"><summary>{E(r["note"])}</summary>'
                      f'<ul>{why}</ul></details>') if why else \
                     f'<span class="dim">{E(r["note"])}</span>'
            body += (f'<tr class="{cls}"><td>{E(POS_NAMES[pos])}{star}</td>'
                     f'<td>{E(r["rank"])}</td>'
                     f'<td class="num">~{r["mmr"]}<span class="dim"> '
                     f'±{r["unc"]}</span></td>'
                     f'<td class="num">{delta:+}{dbar}</td>'
                     f'<td><span class="tag {r["conf"]}">{r["conf"]}</span></td>'
                     f'<td>{detail}</td></tr>')
        ptbl = (f'<h2 style="margin-top:14px">Position ratings (Plays-Like scale)</h2>'
                f'<table class="postbl"><tr><th>Position</th><th>Medal</th>'
                f'<th class="num">MMR</th><th class="num">vs base</th>'
                f'<th>Basis</th><th>Why</th></tr>{body}</table>'
                f'<p class="note">{E(pr["note"])}</p>')
    return (f'<div class="card span2"><h2>Lanes &amp; positions</h2>'
            f'<table class="kv">{rows}</table>{ptbl}</div>')


def _tox_meter_cls(score):
    return "crit" if score >= 55 else "warn" if score >= 25 else \
        "accent" if score >= 8 else "good"


def _tox_chip_cls(label):
    return {"Toxic": "crit", "Salty": "warn", "Mild": "accent",
            "Clean": "good"}.get(label, "")


def _toxicity_card(d):
    if d["private_chat"] or d["toxicity_score"] is None:
        return ('<div class="card span2"><h2>Toxicity report</h2>'
                '<p class="dim">No public chat data (private profile, or matches '
                'not parsed by OpenDota).</p></div>')
    score, label = d["toxicity_score"], d["toxicity_label"]
    bd = d["toxicity_breakdown"]
    meter = (f'<div class="meter"><i class="{_tox_meter_cls(score)}" '
             f'style="width:{score}%"></i></div>')
    breakdown = (f'{_chip(f"{bd["flame"]} flame")}{_chip(f"{bd["curse"]} curse", "warn")}'
                 f'{_chip(f"{bd["slur"]} slur/harassment", "crit")}')
    flagged = ""
    if d["toxicity_hits"]:
        flagged = "<h2 style='margin-top:12px'>Flagged words</h2>" + "".join(
            f'<span class="hero" style="border-color:var(--crit);color:var(--crit)">'
            f'{E(w)} <span class="dim">{c}×</span></span>'
            for w, c in d["toxicity_hits"][:20])
    toxic_set = {w for w, _ in d["toxicity_hits"]}
    cloud = ("<h2 style='margin-top:12px'>Chat word cloud</h2>"
             + _word_cloud(d["chat_top_words"], toxic_set))
    return (f'<div class="card span2"><h2>Toxicity report</h2>'
            f'<div style="display:flex;gap:12px;align-items:baseline;flex-wrap:wrap">'
            f'<span style="font-size:30px;font-weight:800">{score}</span>'
            f'<span class="dim">/100</span>{_chip(label, _tox_chip_cls(label))}'
            f'<span class="dim">over {d["chat_total_words"]} chat words '
            f'({d["chat_unique_words"]} unique)</span></div>'
            f'{meter}{breakdown}{flagged}{cloud}'
            f'<p class="note">Heuristic: weighted flame/curse/slur rate per 1000 '
            f'chat words. Words shown are the player’s own typed chat.</p></div>')


# ---------------------------------------------------------------- hero
# value_tier() returns full strings ("S - Big steal", "★ Unrated", "—"); the
# hero badge shows just the leading grade with the label beneath.
def _grade_parts(vt):
    vt = (vt or "").strip()
    if not vt or vt == "—":
        return None
    uncertain = vt.endswith("?")
    core = vt[:-1].strip() if uncertain else vt
    if core.startswith("★"):  # ★ Unrated placeholder
        return "★", "Unrated", uncertain
    letter, _, label = core.partition(" - ")
    return letter.strip(), label.strip(), uncertain


def _grade_cls(letter):
    return {"S": "g-hi", "A": "g-hi", "B": "g-good", "C": "g-mid",
            "D": "g-lo", "E": "g-crit", "F": "g-crit",
            "★": "g-u"}.get(letter, "g-mid")


def _grade_badge(vt):
    parts = _grade_parts(vt)
    if not parts:
        return ""
    letter, label, uncertain = parts
    sub = (label or "Value")[:12] + ("?" if uncertain else "")
    return (f'<div class="grade {_grade_cls(letter)}">'
            f'<div class="gl">{E(letter)}</div><div class="gt">{E(sub)}</div></div>')


def _value_cell(vt):
    """Compact colored grade letter + label for the index table."""
    parts = _grade_parts(vt)
    if not parts:
        return '<span class="dim">—</span>'
    letter, label, uncertain = parts
    return (f'<span class="vg {_grade_cls(letter)}">{E(letter)}{"?" if uncertain else ""}</span>'
            f' <span class="dim">{E(label)}</span>')


# Fixed MMR domain so the gauge reads the same across every player's report; a
# captain flips through many, and a shared scale makes the gaps comparable.
_GAUGE_LO, _GAUGE_HI = 1000, 6000


def _gauge_pct(mmr, lo=2, hi=98):
    """Position on the fixed domain, clamped a hair inside so edge markers and
    their labels never fall off the track."""
    t = (mmr - _GAUGE_LO) / (_GAUGE_HI - _GAUGE_LO) * 100
    return max(lo, min(hi, t))


def _gap_gauge(p, d):
    """The signature: Listed vs Plays-Like on one scale, the span between them
    filled Radiant-green (plays above price) or Dire-red (reach)."""
    listed, plays = p["mmr"], d["adj_skill"]
    if plays is None or not listed:
        return ""
    unc = d.get("skill_unc") or 0
    lp, pp = _gauge_pct(listed), _gauge_pct(plays)
    lo, hi = sorted((lp, pp))
    up = plays >= listed
    gap = plays - listed
    verb = "plays above price" if gap > 0 else "priced above play" if gap < 0 else "priced on the nose"
    unc_html = ""
    if unc:
        ul, uh = _gauge_pct(plays - unc), _gauge_pct(plays + unc)
        unc_html = f'<div class="gauge-unc" style="left:{ul:.1f}%;width:{max(0, uh - ul):.1f}%"></div>'
    return (
        f'<div class="gauge">'
        f'<div class="gauge-head"><span class="kick">Listed vs plays-like</span>'
        f'<span class="lg"><b>{"+" if gap > 0 else ""}{gap}</b> MMR · {verb}</span></div>'
        f'<div class="gauge-track" role="img" '
        f'aria-label="Listed {listed}, plays like about {plays}">'
        f'{unc_html}'
        f'<div class="gauge-span {"up" if up else "down"}" '
        f'style="left:{lo:.1f}%;width:{max(0, hi - lo):.1f}%"></div>'
        f'<div class="gauge-mk listed" style="left:{lp:.1f}%"></div>'
        f'<div class="gauge-mk plays" style="left:{pp:.1f}%"></div>'
        f'<div class="gauge-lab plays" style="left:{pp:.1f}%">plays ~{plays}</div>'
        f'<div class="gauge-lab listed" style="left:{lp:.1f}%">listed {listed}</div>'
        f'</div>'
        f'<div class="gauge-axis"><span>1k</span><span>2k</span><span>3k</span>'
        f'<span>4k</span><span>5k</span><span>6k</span></div></div>')


def _readout(p, d):
    """Instrument strip: the five numbers a captain scans first."""
    skill = d["adj_skill"]
    unc = d.get("skill_unc")
    plays = (f'~{skill}<small> ±{unc}</small>' if skill is not None and unc
             else f'~{skill}' if skill is not None else "—")
    if skill is None:
        gap = '<span class="dim">—</span>'
    else:
        g = skill - p["mmr"]
        gap = (f'<span class="up">▲ +{g}</span>' if g > 0
               else f'<span class="down">▼ {g}</span>' if g < 0 else "±0")
    wr = f'{d["winrate"]}<small>%</small>' if d["winrate"] else "—"
    games = f'{d["total_matches"]:,}' if d["total_matches"] else "—"
    cells = [
        ("Listed MMR", str(p["mmr"])),
        ("Plays like", plays),
        ("Gap", gap),
        ("Lifetime WR", wr),
        ("Games", games),
    ]
    inner = "".join(f'<div class="cell"><div class="rl">{E(l)}</div>'
                    f'<div class="rv">{v}</div></div>' for l, v in cells)
    return f'<div class="readout">{inner}</div>'


# ---------------------------------------------------------------- pages
def _player_page(pd, icons, season_label):
    p, d = pd["player"], pd["data"]
    medal = _medal_html(d["rank_tier"], icons, 52)
    vt = value_tier(d)
    tox_chip = (_chip(f"Chat: {d['toxicity_label']}", _tox_chip_cls(d["toxicity_label"]))
                if d["toxicity_score"] is not None else "")
    cap = _chip("Captain", "accent") if p.get("captain") == "Y" else ""
    priv = _chip("\U0001f512 Private", "warn") if d["private_profile"] else ""

    links = (f'<a href="{od_url(p)}">OpenDota</a>'
             f'<a href="{db_url(p)}">Dotabuff</a>'
             f'<a href="{ld2l_url(p)}">LD2L</a>'
             f'<a href="{steam_url(p)}">Steam</a>')
    chips = f'{cap}{priv}{tox_chip}'

    body = (
        _winrate_card(d) + _east_card(d) + _esports_card(d) + _heroes_card(d)
        + _lanes_card(d) + _toxicity_card(d)
    )
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(p['name'])} — LD2L Scout</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap">
<div class="topbar">
  <span class="brand"><b>LD2L</b> Scout · Dossier</span>
  <span class="back"><a href="index.html">← All players · {E(season_label)}</a></span>
</div>
<header class="player">{medal}
  <div class="who"><h1>{E(p['name'])}</h1>
    <div class="rank">{E(d['rank_str'])}</div>
    <div class="chips">{chips}</div>
  </div>
  {_grade_badge(vt)}
  <div class="links">{links}</div>
</header>
{_readout(p, d)}
{_gap_gauge(p, d)}
<div class="narrative"><span class="kick fl">Assessment</span>{E(career_narrative(p, d))}</div>
<div class="grid">{body}</div>
<footer>Generated {gen} · LD2L Scout. Ratings are behavioral estimates from
OpenDota (medal + lobby signals); support (4/5) ratings and career tenure are
inferred, not measured. Not affiliated with Valve or LD2L staff.</footer>
</div></body></html>"""


def _report_filename(name, steam32, used):
    """`<name> scouting report.html`, sanitized for Windows and de-duplicated."""
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name or "")).strip()
    base = re.sub(r"\s+", " ", base).rstrip(" .")
    if not base:
        base = f"Player {steam32}"
    fname = f"{base} scouting report.html"
    if fname.lower() in used:  # two players share a display name
        fname = f"{base} scouting report ({steam32}).html"
    used.add(fname.lower())
    return fname


def report_filenames(all_data):
    """Deterministic {steam32: filename} map — identical to what
    generate_player_reports writes (same order → same de-duplication), so the
    dashboard can link to reports without a circular import."""
    used = set()
    return {pd["player"]["steam32"]:
            _report_filename(pd["player"]["name"], pd["player"]["steam32"], used)
            for pd in all_data}


def _index_page(all_data, season_label, fname_map):
    ranked = sorted(all_data, key=lambda pd: -(pd["data"]["adj_skill"] or 0))
    rows = ""
    for pd in ranked:
        p, d = pd["player"], pd["data"]
        pr = position_ratings(d)
        primary = POS_NAMES.get(pr.get("primary"), "—") if pr else "—"
        tox = (f'<span class="chip {_tox_chip_cls(d["toxicity_label"])}">{d["toxicity_label"]}</span>'
               if d["toxicity_score"] is not None else '<span class="dim">—</span>')
        vt = value_tier(d)
        skill = f'~{d["adj_skill"]}' if d["adj_skill"] is not None else "—"
        href = quote(fname_map[p["steam32"]])
        rows += (f'<tr><td><a href="{href}">{E(p["name"])}</a>'
                 f'{" \U0001f6a9" if p.get("captain") == "Y" else ""}</td>'
                 f'<td class="num">{p["mmr"]}</td><td class="num">{skill}</td>'
                 f'<td>{_value_cell(vt)}</td><td>{E(primary.split(" (")[0])}</td>'
                 f'<td>{E(d["rank_str"])}</td><td>{tox}</td></tr>')
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LD2L Scout — {E(season_label)} players</title>
<style>{INDEX_CSS}</style></head><body><div class="wrap">
<div class="topbar">
  <span class="brand"><b>LD2L</b> Scout · Draft Board</span>
  <span class="back">Sorted by plays-like</span>
</div>
<div class="idxhead">
  <h1>Player Scout — {E(season_label)}</h1>
  <div class="sub">{len(all_data)} players · click a name for the full dossier</div>
</div>
<table class="idx">
<thead><tr><th>Player</th><th class="num">Listed</th>
<th class="num">Plays Like</th><th>Value</th><th>Role</th><th>Medal</th><th>Chat</th></tr></thead>
<tbody>{rows}</tbody></table>
<footer>Generated {gen} · sorted by Plays-Like skill estimate.</footer>
</div></body></html>"""


def generate_player_reports(all_data, season_label, out_dir="scout_reports",
                            offline=False):
    """Write one `<name> scouting report.html` per player + an index.html.

    The output dir is cleared of stale *.html first (players/names change run to
    run, and the dir is exclusively ours). Returns the output dir.
    """
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.html")):
        try:
            os.remove(old)
        except OSError:
            pass

    icons = _rank_icon_uris(offline=offline)
    fname_map = report_filenames(all_data)
    for pd in all_data:
        page = _player_page(pd, icons, season_label)
        path = os.path.join(out_dir, fname_map[pd["player"]["steam32"]])
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(_index_page(all_data, season_label, fname_map))
    return out_dir
