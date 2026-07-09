"""Self-contained HTML dashboard with draft-day tooling.

Single file, no external requests (works offline). Draft state persists in
localStorage keyed by season, so a mid-draft refresh keeps its state.
"""

import json
from datetime import datetime

from .analysis import value_tier
from .report_xlsx import db_url, ld2l_url, od_url


def _fmt_form(form):
    if not form:
        return ""
    return f"{form['winrate']}% ({form['games']}g)"


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
        "pos": p["pos_prefs"],
        "prefRole": p["pref_role"],
        "statement": p["statement"],
        "rank": d["rank_str"],
        "mmrCheck": d["mmr_check"],
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
        "punch": d["punches_above"],
        "punchGap": d["punch_gap_stars"],
        "soloPct": d["solo_pct"],
        "soloWr": d["solo_wr"],
        "partyWr": d["party_wr"],
        "lanes": d["lane_pcts"],
        "laneN": d["lane_n"],
        "leagueN": d["league_matches"],
        "leagueWr": d["league_winrate"] if d["league_matches"] else None,
        "leagueHeroes": d["league_heroes"][:8],
        "tier": value_tier(p["mmr"], d),
        "estCost": d["est_cost"],
        "lastCost": d["last_cost"],
        "lastCostSeason": d["last_cost_season"],
        "lastDraftMmr": d["last_draft_mmr"],
        "wasCaptainLast": d["was_captain_last"],
        "db": db_url(p),
        "od": od_url(p),
        "ld2l": ld2l_url(p),
    }


def generate_dashboard(players_with_data, output_file, season_label, season_id):
    records = [_player_record(pd) for pd in
               sorted(players_with_data, key=lambda x: -x["player"]["mmr"])]
    payload = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATE
            .replace("{{SEASON}}", season_label)
            .replace("{{SEASON_ID}}", str(season_id))
            .replace("{{GENERATED}}", datetime.now().strftime("%Y-%m-%d %H:%M"))
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
header { padding: 20px 24px 0; }
h1 { font-size: 20px; margin: 0 0 2px; }
.sub { color: var(--muted); font-size: 12px; margin-bottom: 14px; }

.tiles { display: flex; gap: 12px; flex-wrap: wrap; padding: 0 24px 14px; }
.tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 16px; min-width: 120px;
}
.tile .v { font-size: 24px; font-weight: 650; }
.tile .l { font-size: 11px; color: var(--ink2); }

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
tbody td { padding: 7px 8px; border-bottom: 1px solid var(--grid); vertical-align: middle; white-space: nowrap; }
tbody tr.main:hover { background: var(--tint-accent); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.pname { font-weight: 600; cursor: pointer; }
.pname:hover { text-decoration: underline; }
tr.drafted td { opacity: .38; }
tr.drafted .pname { text-decoration: line-through; }

.badge {
  display: inline-block; font-size: 10px; font-weight: 700; border-radius: 4px;
  padding: 1px 5px; margin-left: 5px; vertical-align: 1px; border: 1px solid var(--border);
}
.b-cap { background: var(--tint-good); color: var(--good); }
.b-capm { background: var(--tint-warn); color: var(--warn); }
.b-new { background: var(--tint-accent); color: var(--s1); }
.b-v { color: var(--muted); }

.lane { display: inline-flex; align-items: center; gap: 6px; }
.lanebar { display: inline-flex; width: 72px; height: 8px; border-radius: 4px; overflow: hidden; gap: 2px; background: transparent; }
.lanebar i { height: 100%; }
.lanebar .l1 { background: var(--s1); } .lanebar .l2 { background: var(--s2); } .lanebar .l3 { background: var(--s3); }
.lanetxt { color: var(--ink2); font-size: 11px; }

.good { color: var(--good); font-weight: 600; }
.bad { color: var(--crit); }
.warn { color: var(--warn); font-weight: 600; }
.dim { color: var(--muted); }
.tierchip { display: inline-block; border: 1px solid var(--grid); border-radius: 4px;
            padding: 1px 6px; font-size: 11px; font-weight: 600; }
a { color: var(--s1); text-decoration: none; } a:hover { text-decoration: underline; }

button.draftbtn {
  border: 1px solid var(--grid); background: var(--surface); color: var(--ink2);
  border-radius: 6px; padding: 3px 10px; cursor: pointer; font: inherit; font-size: 12px;
}
button.draftbtn.on { background: var(--crit); border-color: var(--crit); color: #fff; }

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
</style>
</head>
<body>
<header>
  <h1>LD2L {{SEASON}} Scouting Dashboard</h1>
  <div class="sub">Generated {{GENERATED}} · data: ld2l.org + OpenDota · works offline</div>
</header>

<div class="tiles" id="tiles"></div>

<div class="controls">
  <input type="search" id="q" placeholder="Search name / statement…">
  <select id="fcap">
    <option value="">Captain: all</option><option value="Y">Captain: yes</option>
    <option value="M">Captain: maybe</option><option value="N">Captain: no</option>
  </select>
  <span id="poschips"></span>
  <label class="ck"><input type="checkbox" id="fnew"> new only</label>
  <label class="ck"><input type="checkbox" id="factive"> hide inactive 90d+</label>
  <label class="ck"><input type="checkbox" id="fdrafted"> hide drafted</label>
  <button class="chip" id="draftmode">Draft board</button>
  <button class="chip" id="resetdraft" title="Clear all drafted marks">Reset draft</button>
  <span class="count" id="count"></span>
</div>

<div id="bestpanel"><div class="bestgrid" id="bestgrid"></div></div>

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

<script>
const DATA = {{DATA}};
const SEASON = "{{SEASON_ID}}";
const LSKEY = "ld2l-drafted-s" + SEASON;

let drafted = new Set(JSON.parse(localStorage.getItem(LSKEY) || "[]"));
let cmpSel = new Set();
let posFilter = new Set();
let sortCol = "mmr", sortDir = -1;

const COLS = [
  {k:"_cmp",  t:"⇄",     num:false, sort:null},
  {k:"name",  t:"Player", num:false, sort:(a)=>a.name.toLowerCase()},
  {k:"mmr",   t:"MMR",    num:true,  sort:(a)=>a.mmr},
  {k:"rank",  t:"Medal",  num:false, sort:(a)=>a.rank},
  {k:"mmrCheck",t:"MMR check",num:false,sort:(a)=>a.mmrCheck},
  {k:"estCost",t:"Est$",num:true,sort:(a)=>a.estCost==null?-1:a.estCost},
  {k:"lastCost",t:"Last$",num:true,sort:(a)=>a.lastCost==null?-1:a.lastCost},
  {k:"prefRole",t:"Pref pos",num:false,sort:(a)=>a.prefRole},
  {k:"lanes", t:"Lanes (6mo)",num:false,sort:(a)=>-(a.laneN||0)},
  {k:"wr",    t:"WR%",    num:true,  sort:(a)=>a.wr},
  {k:"form30",t:"Form 30d",num:false, sort:(a)=>a.form30wr==null?-1:a.form30wr},
  {k:"games", t:"Games",  num:true,  sort:(a)=>a.games},
  {k:"last",  t:"Last",   num:true,  sort:(a)=>a.last==null?99999:a.last},
  {k:"kda",   t:"KDA",    num:true,  sort:(a)=>a.kda},
  {k:"gpm",   t:"GPM",    num:true,  sort:(a)=>a.gpm},
  {k:"lobby", t:"Lobby",  num:false, sort:(a)=>a.punchGap==null?-99:a.punchGap},
  {k:"soloPct",t:"Solo%", num:true,  sort:(a)=>a.soloPct==null?-1:a.soloPct},
  {k:"leagueN",t:"League",num:true,  sort:(a)=>a.leagueN},
  {k:"tier",  t:"Tier",   num:false, sort:(a)=>a.mmr},
  {k:"_links",t:"Links",  num:false, sort:null},
  {k:"_draft",t:"Draft",  num:false, sort:null},
];

function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

// rated 1-2, or their best-rated position (covers players who left the form blank)
function playsPos(p, pos){
  const v = p.pos[pos-1];
  return v <= 2 || v === Math.min(...p.pos);
}

function laneCell(p){
  if (!p.laneN) return '<span class="dim">—</span>';
  const order = ["Safe","Mid","Off","Jungle"];
  const parts = order.filter(k=>p.lanes[k]).map(k=>[k, p.lanes[k]]);
  const cls = {Safe:"l1", Mid:"l2", Off:"l3", Jungle:"l3"};
  const bar = parts.map(([k,v])=>`<i class="${cls[k]}" style="width:${v}%" title="${k} ${v}%"></i>`).join("");
  const txt = parts.map(([k,v])=>`${k[0]}${v}`).join(" ");
  return `<span class="lane"><span class="lanebar">${bar}</span><span class="lanetxt">${txt}</span></span>`;
}

function nameCell(p){
  let b = "";
  if (p.captain==="Y") b += '<span class="badge b-cap">CAPT</span>';
  else if (p.captain==="M") b += '<span class="badge b-capm">CAPT?</span>';
  if (p.new) b += '<span class="badge b-new">NEW</span>';
  if (p.vouched==="Y") b += '<span class="badge b-v" title="vouched">✓</span>';
  return `<span class="pname" data-x="${p.id}">${esc(p.name)}</span>${b}`;
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

function rowHtml(p){
  const dcls = drafted.has(p.id) ? "drafted" : "";
  const punch = p.punch ? ' <span class="good" title="queues above own medal">▲</span>' : '';
  const mc = p.mmrCheck ? `<span class="${p.mmrCheck.startsWith("⚠")?"warn":"dim"}">${esc(p.mmrCheck)}</span>` : '<span class="dim">—</span>';
  return `<tr class="main ${dcls}" data-id="${p.id}">
    <td><input type="checkbox" class="cmpck" data-x="${p.id}" ${cmpSel.has(p.id)?"checked":""}></td>
    <td>${nameCell(p)}</td>
    <td class="num">${p.mmr}</td>
    <td>${esc(p.rank)}</td>
    <td>${mc}</td>
    <td class="num">${p.estCost==null?'<span class="dim">—</span>':"~"+p.estCost}</td>
    <td class="num">${lastCostCell(p)}</td>
    <td>${esc(p.prefRole)}</td>
    <td>${laneCell(p)}</td>
    <td class="num">${wrCell(p.wr, p.games)}</td>
    <td>${p.form30 ? esc(p.form30) : '<span class="dim">—</span>'}</td>
    <td class="num">${p.games}</td>
    <td class="num">${p.last==null ? '<span class="dim">?</span>' : (p.last>90 ? `<span class="warn">${p.last}d ⚠</span>` : p.last+"d")}</td>
    <td class="num">${p.kda}</td>
    <td class="num">${p.gpm}</td>
    <td>${esc(p.lobby)}${punch}</td>
    <td class="num">${p.soloPct==null?'<span class="dim">—</span>':p.soloPct}</td>
    <td class="num">${p.leagueN ? `${p.leagueN} <span class="dim">(${p.leagueWr}%)</span>` : '<span class="dim">—</span>'}</td>
    <td><span class="tierchip">${esc(p.tier)}</span></td>
    <td><a href="${p.db}" target="_blank">DB</a> · <a href="${p.od}" target="_blank">OD</a> · <a href="${p.ld2l}" target="_blank">L2</a></td>
    <td><button class="draftbtn ${drafted.has(p.id)?"on":""}" data-x="${p.id}">${drafted.has(p.id)?"Drafted":"Draft"}</button></td>
  </tr>`;
}

function detailHtml(p){
  const li = (arr)=>arr.length?arr.map(esc).join(", "):"—";
  return `<tr class="detail" data-for="${p.id}"><td colspan="${COLS.length}"><div class="dgrid">
    <div><h4>Statement</h4><p>${esc(p.statement)||"—"}</p></div>
    <div><h4>Top heroes</h4><p>${li(p.topHeroes)}</p></div>
    <div><h4>Signature heroes (100g/53%+)</h4><p>${li(p.sig)}</p></div>
    <div><h4>Recent heroes</h4><p>${li(p.recentHeroes)}</p></div>
    <div><h4>League heroes (6mo)</h4><p>${li(p.leagueHeroes)}</p></div>
    <div><h4>More</h4><p>Pos prefs: ${p.pos.join("/")} · Form 90d: ${esc(p.form90)||"—"} ·
      Solo WR: ${p.soloWr==null?"—":p.soloWr+"%"} · Party WR: ${p.partyWr==null?"—":p.partyWr+"%"} ·
      Hero pool: ${p.pool} · XPM: ${p.xpm} · MMR screenshot: ${p.mmrValid?"yes":"no"}</p></div>
    <div><h4>Auction</h4><p>Est. cost: ${p.estCost==null?"—":"~"+p.estCost} ·
      Last draft: ${p.lastCostSeason ? (p.wasCaptainLast?"captain":(p.lastCost==null?"undrafted":"cost "+p.lastCost)) + " (" + esc(p.lastCostSeason) + (p.lastDraftMmr?", MMR then "+p.lastDraftMmr:"") + ")" : "no history"}</p></div>
  </div></td></tr>`;
}

function filtered(){
  const q = document.getElementById("q").value.toLowerCase();
  const cap = document.getElementById("fcap").value;
  const onlyNew = document.getElementById("fnew").checked;
  const hideInactive = document.getElementById("factive").checked;
  const hideDrafted = document.getElementById("fdrafted").checked;
  return DATA.filter(p=>{
    if (q && !(p.name.toLowerCase().includes(q) || (p.statement||"").toLowerCase().includes(q))) return false;
    if (cap && p.captain !== cap) return false;
    if (onlyNew && !p.new) return false;
    if (hideInactive && p.last!=null && p.last>90) return false;
    if (hideDrafted && drafted.has(p.id)) return false;
    if (posFilter.size){
      let ok=false;
      posFilter.forEach(i=>{ if(playsPos(p,i)) ok=true; });
      if(!ok) return false;
    }
    return true;
  });
}

function render(){
  const col = COLS.find(c=>c.k===sortCol);
  const list = filtered().slice().sort((a,b)=>{
    const va=col.sort(a), vb=col.sort(b);
    return (va<vb?-1:va>vb?1:0)*sortDir;
  });
  document.getElementById("hdr").innerHTML = COLS.map(c=>
    `<th class="${c.num?"num":""}" data-k="${c.k}">${c.t}${c.k===sortCol?` <span class="arr">${sortDir<0?"▼":"▲"}</span>`:""}</th>`).join("");
  document.getElementById("rows").innerHTML = list.map(rowHtml).join("");
  document.getElementById("count").textContent =
    `${list.length}/${DATA.length} players · ${drafted.size} drafted`;
  renderTiles(); renderBest(); renderTray();
}

function renderTiles(){
  const capsY = DATA.filter(p=>p.captain==="Y").length;
  const capsM = DATA.filter(p=>p.captain==="M").length;
  const news = DATA.filter(p=>p.new).length;
  const active = DATA.filter(p=>p.last!=null && p.last<=30).length;
  const mmrs = DATA.map(p=>p.mmr).sort((a,b)=>a-b);
  const med = mmrs.length? mmrs[Math.floor(mmrs.length/2)] : 0;
  document.getElementById("tiles").innerHTML = [
    [DATA.length, "signups"],
    [capsY + " / " + capsM, "captains yes / maybe"],
    [news, "new since last run"],
    [active + "/" + DATA.length, "active last 30d"],
    [med, "median listed MMR"],
    [DATA.length - drafted.size, "still available"],
  ].map(([v,l])=>`<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
}

function renderBest(){
  const grid = document.getElementById("bestgrid");
  if (!document.getElementById("bestpanel").classList.contains("show")) return;
  const names = ["Pos 1 (Carry)","Pos 2 (Mid)","Pos 3 (Offlane)","Pos 4 (Soft)","Pos 5 (Hard)"];
  grid.innerHTML = names.map((nm,ix)=>{
    const cand = DATA.filter(p=>!drafted.has(p.id) && playsPos(p, ix+1))
                     .sort((a,b)=>b.mmr-a.mmr).slice(0,5);
    const rows = cand.length ? cand.map(p=>
      `<div><span>${esc(p.name)}${p.captain==="Y"?" ©":""}</span><span class="m">${p.mmr}${p.estCost!=null?" · ~"+p.estCost:""}</span></div>`).join("")
      : '<div class="dim">none left</div>';
    return `<div class="bestcol"><h3>${nm}</h3>${rows}</div>`;
  }).join("");
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
    ["MMR", p=>p.mmr], ["Medal", p=>esc(p.rank)], ["MMR check", p=>esc(p.mmrCheck)||"—"],
    ["Est. cost", p=>p.estCost==null?"—":"~"+p.estCost],
    ["Last cost", p=>lastCostCell(p)],
    ["Captain", p=>p.captain], ["Pos prefs", p=>p.pos.join("/")],
    ["Lanes", p=>laneCell(p)], ["Lifetime WR", p=>p.games?p.wr+"%":"—"],
    ["Form 30d", p=>esc(p.form30)||"—"], ["Form 90d", p=>esc(p.form90)||"—"],
    ["Games", p=>p.games], ["Last played", p=>p.last==null?"?":p.last+"d"],
    ["KDA", p=>p.kda], ["GPM", p=>p.gpm], ["Hero pool", p=>p.pool],
    ["Lobby median", p=>esc(p.lobby)+(p.punch?" ▲":"")],
    ["Solo WR", p=>p.soloWr==null?"—":p.soloWr+"%"],
    ["League (6mo)", p=>p.leagueN?`${p.leagueN}g ${p.leagueWr}%`:"—"],
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
document.querySelector(".controls").addEventListener("input", render);
document.getElementById("poschips").innerHTML =
  [1,2,3,4,5].map(i=>`<button class="chip posck" data-p="${i}">P${i}</button>`).join(" ");
document.getElementById("poschips").addEventListener("click", e=>{
  const b = e.target.closest(".posck"); if(!b) return;
  const v = +b.dataset.p;
  posFilter.has(v) ? posFilter.delete(v) : posFilter.add(v);
  b.classList.toggle("on");
  render();
});
document.getElementById("hdr").addEventListener("click", e=>{
  const th = e.target.closest("th"); if(!th) return;
  const col = COLS.find(c=>c.k===th.dataset.k);
  if (!col || !col.sort) return;
  if (sortCol===col.k) sortDir=-sortDir; else { sortCol=col.k; sortDir=-1; }
  render();
});
document.getElementById("rows").addEventListener("click", e=>{
  const dbtn = e.target.closest(".draftbtn");
  if (dbtn){
    const id = +dbtn.dataset.x;
    drafted.has(id) ? drafted.delete(id) : drafted.add(id);
    localStorage.setItem(LSKEY, JSON.stringify([...drafted]));
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
document.getElementById("draftmode").addEventListener("click", e=>{
  document.getElementById("bestpanel").classList.toggle("show");
  e.target.classList.toggle("on");
  renderBest();
  sizeWrap();
});
document.getElementById("resetdraft").addEventListener("click", ()=>{
  if (!drafted.size || confirm("Clear all " + drafted.size + " drafted marks?")){
    drafted.clear(); localStorage.setItem(LSKEY, "[]"); render();
  }
});
document.getElementById("docmp").addEventListener("click", openCompare);
document.getElementById("clearcmp").addEventListener("click", ()=>{ cmpSel.clear(); render(); });

// size the table region to the viewport so it scrolls inside .wrap
// (leaving room for the compare tray at the bottom)
function sizeWrap(){
  const w = document.querySelector(".wrap");
  w.style.maxHeight = Math.max(300, window.innerHeight - w.offsetTop - 70) + "px";
}
window.addEventListener("resize", sizeWrap);

render();
sizeWrap();
</script>
</body>
</html>
"""
