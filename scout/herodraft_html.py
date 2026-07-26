"""The --herodraft board page: a faithful Dota 2 Captains Mode draft UI.

Laid out and skinned like the in-game CM screen: pick columns down the left
(Radiant) and right (Dire) edges, each team's ban strip under its own banner,
the phase clock centred between them, the 24-step draft sequence as a spine
beneath, and the hero grid in the four attribute columns.

The palette, type and voice follow the client: cool blue-charcoal panels,
Radiant olive / Dire brick, no gold and no serif. The tool's own intel — win
probability, hero ratings, scouting hints — stays subordinate to the drill,
demoted to the panel row under the board.

Self-contained page served by herodraft.py; polls /draft/state and posts
actions back. Hero portraits come from the Steam CDN (graceful text fallback
when offline).
"""

import html
import json

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Captains Mode — LD2L</title>
<style>
:root{
  /* surfaces — cool blue-charcoal, the client's greys (no purple cast) */
  --void:#0B0E12; --panel:#171C23; --panel-lit:#1F262F;
  --rule:#2C353F; --rule-hi:#3C4854;
  /* text — cool, not warm */
  --ink:#C7CDD4; --ink-hi:#E8EDF2; --ink-dim:#7C8794;
  /* factions — Valve's actual values */
  --radiant:#92A525; --dire:#C23C2A;
  /* affordances */
  --go:#6B9A22; --go-hi:#84B92C; --good:#9BBF4A; --bad:#D65B45;
  --ui:"Segoe UI","Noto Sans",-apple-system,system-ui,Arial,sans-serif;
  --tile:clamp(34px, 2.9vw, 52px);
}
*{box-sizing:border-box; margin:0; padding:0}
body{background:var(--void); color:var(--ink);
  font:400 13px/1.45 var(--ui); font-variant-numeric:tabular-nums;
  min-height:100vh; padding:10px 14px}
h1{font-size:15px; font-weight:600; letter-spacing:.22em; text-transform:uppercase;
  color:var(--ink-hi); text-align:center}
.sub{text-align:center; color:var(--ink-dim); font-size:11px; letter-spacing:.12em;
  text-transform:uppercase; margin:3px 0 10px}
/* client-style button: flat, uppercase, letterspaced, faint top-lit gradient */
button{background:linear-gradient(180deg,var(--panel-lit),#141920); color:var(--ink);
  border:1px solid var(--rule-hi); padding:7px 18px;
  font:600 11.5px var(--ui); letter-spacing:.14em; text-transform:uppercase;
  cursor:pointer; border-radius:2px}
button:hover:not(:disabled){border-color:var(--ink-dim); color:var(--ink-hi)}
button:disabled{opacity:.3; cursor:default}
button.primary{background:linear-gradient(180deg,var(--go-hi),var(--go));
  border-color:#3F6614; color:#0E1408}
button.primary:hover:not(:disabled){filter:brightness(1.12); color:#0E1408}
:focus-visible{outline:2px solid var(--ink-hi); outline-offset:2px}
input[type=text]{background:#0E1218; border:1px solid var(--rule); color:var(--ink);
  padding:6px 9px; font:400 12.5px var(--ui); width:100%; border-radius:2px}
input[type=text]::placeholder{color:#5D6874}
.wrap{max-width:1720px; margin:0 auto}

/* ================= setup ================= */
.setup{display:none; max-width:1060px; margin:0 auto}
.setup.on{display:block}
.teamcols{display:flex; gap:20px; margin-top:8px}
.tcol{flex:1; background:var(--panel); border:1px solid var(--rule); padding:14px;
  border-radius:2px}
.tcol h2{font-size:11.5px; font-weight:600; letter-spacing:.16em;
  text-transform:uppercase; margin-bottom:9px; color:var(--ink)}
.tcol.mine{border-top:2px solid var(--radiant)}
.tcol.enemy{border-top:2px solid var(--dire)}
.chips{min-height:32px; margin:8px 0; display:flex; flex-wrap:wrap; gap:5px}
.chip{background:var(--panel-lit); border:1px solid var(--rule-hi); padding:3px 9px;
  border-radius:2px; font-size:11.5px; cursor:pointer; white-space:nowrap}
.chip:hover{border-color:var(--dire); color:var(--ink-dim); text-decoration:line-through}
.chip b{color:var(--ink-hi); font-weight:600}
.plist{max-height:214px; overflow-y:auto; border:1px solid var(--rule); margin-top:6px;
  background:#0E1218}
.prow{padding:4px 9px; font-size:12px; cursor:pointer; display:flex;
  justify-content:space-between; gap:10px}
.prow:hover{background:var(--panel-lit); color:var(--ink-hi)}
.prow .meta{color:var(--ink-dim)}
.opts{display:flex; gap:44px; justify-content:center; margin:18px 0; flex-wrap:wrap}
.opt h3{font-size:10.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-dim); text-align:center; margin-bottom:6px; font-weight:600}
.seg{display:flex; border:1px solid var(--rule-hi); border-radius:2px; overflow:hidden}
.seg button{border:0; border-right:1px solid var(--rule-hi); background:transparent;
  color:var(--ink-dim); padding:7px 15px}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--panel-lit); color:var(--ink-hi)}
.startrow{text-align:center; margin-top:4px}
.startrow button{font-size:13px; padding:11px 46px; letter-spacing:.18em}
.warn{text-align:center; color:var(--bad); font-size:11.5px; min-height:16px; margin-top:9px}

/* ================= board ================= */
.board{display:none}
.board.on{display:block}
/* --- top bar: team banner + own ban strip, clock centred --- */
.topbar{display:grid; grid-template-columns:1fr 320px 1fr; gap:10px; align-items:stretch}
.tbox{background:var(--panel); border:1px solid var(--rule); border-radius:2px;
  padding:8px 13px; display:flex; flex-direction:column; justify-content:space-between;
  gap:8px}
.tline{display:flex; justify-content:space-between; align-items:center; gap:12px}
.tbox.right .tline{flex-direction:row-reverse}
.tbox .nm{display:inline-flex; align-items:center; gap:8px; font-size:14px;
  font-weight:600; letter-spacing:.1em; text-transform:uppercase}
.tbox.right .nm{flex-direction:row-reverse}
.tbox .nm::before{content:''; width:9px; height:9px; transform:rotate(45deg); flex:0 0 auto}
.tbox.radiant{border-bottom:2px solid var(--radiant)}
.tbox.radiant .nm{color:var(--radiant)} .tbox.radiant .nm::before{background:var(--radiant)}
.tbox.dire{border-bottom:2px solid var(--dire)}
.tbox.dire .nm{color:var(--dire)} .tbox.dire .nm::before{background:var(--dire)}
.tmeta{display:flex; align-items:center; gap:14px}
.tbox.right .tmeta{flex-direction:row-reverse}
.tbox .fp{font-size:9.5px; color:var(--ink-dim); letter-spacing:.14em; text-transform:uppercase}
.reserve{font-size:10.5px; color:var(--ink-dim); letter-spacing:.08em; text-transform:uppercase}
.reserve b{color:var(--ink); font-weight:600}
.reserve.low b{color:var(--bad)}
/* ban strip lives under its own team, like the client */
.banstrip{display:flex; gap:3px}
.tbox.right .banstrip{justify-content:flex-end}
.banstrip .b{width:42px; height:24px; border:1px solid var(--rule); border-radius:1px;
  overflow:hidden; position:relative; background:#0E1218}
.banstrip .b img{width:100%; height:100%; object-fit:cover; filter:grayscale(1) brightness(.5)}
.banstrip .b.used{border-color:#4A2620}
.banstrip .b.used::after{content:''; position:absolute; inset:0; background:
  linear-gradient(45deg,transparent 46%,rgba(194,60,42,.92) 48%,rgba(194,60,42,.92) 52%,transparent 54%)}
/* --- clock --- */
.tcenter{text-align:center; display:flex; flex-direction:column; justify-content:center}
.turnlabel{font-size:10px; letter-spacing:.18em; text-transform:uppercase; color:var(--ink-dim)}
.clock{font:300 40px/1 var(--ui); font-variant-numeric:tabular-nums; color:var(--ink-hi);
  letter-spacing:.02em}
.clock.reserve{color:var(--bad)}
.clockbar{width:82%; height:3px; background:#0E1218; overflow:hidden; margin:5px auto 3px}
.clockbar i{display:block; height:100%; background:var(--ink-dim); transition:width .25s linear}
.clockbar i.reserve{background:var(--dire)}
.turnwho{font-size:12.5px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-hi)}
.turnwho.enemyturn{color:var(--ink-dim)}

/* --- draft spine: the 24 steps, cut at real phase boundaries --- */
.spine{display:flex; justify-content:center; gap:16px; margin:8px 0 9px;
  padding:7px 0; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule);
  flex-wrap:wrap}
.phase{display:flex; flex-direction:column; align-items:center; gap:4px}
.phcap{font-size:8.5px; letter-spacing:.16em; color:#39424C; text-transform:uppercase;
  transition:color .3s}
.phase.curphase .phcap{color:var(--ink-hi)}
.phrow{display:flex; gap:3px}
.sq{width:21px; height:21px; border:1px solid var(--rule); background:#0E1218;
  position:relative; overflow:hidden; border-radius:1px}
.sq.pick{width:27px; height:27px}
.sq.radiant{border-bottom:2px solid var(--radiant)}
.sq.dire{border-bottom:2px solid var(--dire)}
.sq.cur{border-color:var(--ink-hi); box-shadow:0 0 0 1px var(--ink-hi)}
.sq img{width:100%; height:100%; object-fit:cover}
.sq.banned img{filter:grayscale(1) brightness(.45)}
.sq.banned::after{content:''; position:absolute; inset:0; background:
  linear-gradient(45deg,transparent 44%,rgba(194,60,42,.88) 47%,rgba(194,60,42,.88) 53%,transparent 56%)}
.sq.skipped::after{content:'—'; position:absolute; inset:0; color:var(--ink-dim);
  display:flex; align-items:center; justify-content:center; font-size:11px}

/* --- arena: pick columns flanking the hero grid --- */
.arena{display:flex; gap:12px; align-items:flex-start}
.pickcol{flex:0 0 180px; background:var(--panel); border:1px solid var(--rule);
  border-radius:2px; padding:10px}
.pickcol.radiant{border-left:2px solid var(--radiant)}
.pickcol.dire{border-right:2px solid var(--dire)}
.pickcol.active{border-color:var(--rule-hi)}
.slots{display:flex; flex-direction:column; gap:7px}
.pcard{position:relative; border:1px solid var(--rule); border-radius:1px;
  overflow:hidden; background:#0E1218}
.pcard .imwrap{width:100%; aspect-ratio:16/9; display:flex; align-items:center;
  justify-content:center; overflow:hidden}
.pcard img{width:100%; height:100%; object-fit:cover}
.pcard .ph{color:#2A323B; font-size:22px}
.pcard .cap{padding:3px 6px; font-size:10.5px; display:flex; justify-content:space-between;
  gap:5px; background:var(--panel-lit)}
.pcard .cap .h{color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.pcard .cap .pl{color:var(--ink-dim); white-space:nowrap}
.pcard .rt{position:absolute; top:2px; right:2px; font:600 9.5px var(--ui);
  background:rgba(6,9,13,.82); padding:1px 4px; border-radius:1px; letter-spacing:.02em}
.rt.pos{color:var(--good)} .rt.neg{color:var(--bad)} .rt.mid{color:var(--ink-dim)}
.pickcol .roster{font-size:10.5px; color:var(--ink-dim); line-height:1.6; margin-top:9px;
  padding-top:8px; border-top:1px solid var(--rule)}
.pickcol .roster b{color:var(--ink); font-weight:600}

/* --- hero grid: four attribute groups, in-game column widths --- */
.gridwrap{flex:1; background:var(--panel); border:1px solid var(--rule); border-radius:2px;
  padding:8px 10px; min-width:0; overflow-x:auto}
.gridtop{display:flex; justify-content:center; margin-bottom:8px}
.gridtop input{max-width:260px}
.herogrid{display:flex; gap:12px; align-items:flex-start; justify-content:center;
  min-width:max-content}
.attrgroup{display:flex; flex-direction:column}
.attrhead{display:flex; align-items:center; gap:6px; margin-bottom:6px; padding-bottom:4px;
  border-bottom:1px solid var(--rule)}
.attrhead .dot{width:8px; height:8px; transform:rotate(45deg)}
.attrhead span{font-size:9.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-dim); font-weight:600}
.grid{display:grid; gap:3px}   /* grid-template-columns set inline per attribute */
.tile{width:var(--tile); cursor:pointer; position:relative}
.tile .im{width:var(--tile); height:calc(var(--tile)*0.56); background:#0E1218;
  border:1px solid var(--rule); border-radius:1px; overflow:hidden; display:flex;
  align-items:center; justify-content:center}
.tile .im img{width:100%; height:100%; object-fit:cover; display:block}
.tile:hover .im{border-color:var(--ink-hi)}
.tile.taken{pointer-events:none}
.tile.taken .im img{filter:grayscale(1) brightness(.35)}
.tile.taken .im{border-color:#1A2028}
.tile.sel .im{border-color:var(--ink-hi); box-shadow:0 0 0 1px var(--ink-hi)}
.tile.sugg .im{border-color:var(--rule-hi)}
.tile.dim{opacity:.22}
.tile .txtfall{color:#3E4854; font-size:8.5px; padding:2px; text-align:center}
.tile .rb{position:absolute; top:1px; right:1px; font:600 8.5px var(--ui);
  background:rgba(6,9,13,.8); padding:0 3px; border-radius:1px; pointer-events:none}
.rb.pos{color:var(--good)} .rb.neg{color:var(--bad)} .rb.mid{color:#5D6874}
.lockrow{position:sticky; bottom:8px; text-align:center; margin-top:9px}
.lockrow button{font-size:12px; padding:9px 38px}
.lockrow .picking{color:var(--ink-dim); font-size:10.5px; letter-spacing:.14em;
  text-transform:uppercase; margin-bottom:5px; min-height:14px}

/* --- panel row: the tool's own intel, subordinate to the drill --- */
.panels{display:flex; gap:12px; margin-top:12px; align-items:flex-start}
.panelbox{flex:1; background:var(--panel); border:1px solid var(--rule); border-radius:2px;
  padding:10px 12px}
.panelbox.narrow{flex:0 0 300px}
.panelbox h3{font-size:9.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-dim); margin-bottom:8px; border-bottom:1px solid var(--rule);
  padding-bottom:5px; font-weight:600}
.meterrow{display:flex; align-items:center; gap:9px}
.mlab{font:600 13px var(--ui); font-variant-numeric:tabular-nums; width:42px}
.mlab.l{text-align:right} .mlab.r{text-align:left}
.mlab.radiant{color:var(--radiant)} .mlab.dire{color:var(--dire)}
.meter{flex:1; height:10px; background:#0E1218; border:1px solid var(--rule);
  overflow:hidden; display:flex; position:relative}
.meter .mfl{height:100%; background:var(--radiant); transition:width .5s}
.meter .mfr{height:100%; flex:1; background:var(--dire)}
.meter .mmark{position:absolute; top:0; bottom:0; width:1px; background:var(--void);
  left:50%; opacity:.8}
.mhint{font-size:10.5px; color:var(--ink-dim); letter-spacing:.06em; min-height:15px;
  margin-top:7px; text-align:center}
.mhint b{color:var(--ink-hi); font-weight:600}
.sg{display:flex; gap:10px; align-items:center; padding:5px 3px; cursor:pointer}
.sg:hover{background:var(--panel-lit)}
.sg img{width:54px; height:31px; object-fit:cover; border:1px solid var(--rule)}
.sg .srt{font:600 13px var(--ui); font-variant-numeric:tabular-nums; width:46px; text-align:right}
.srt.pos{color:var(--good)} .srt.neg{color:var(--bad)} .srt.mid{color:var(--ink-dim)}
.sg .snm{font-size:12.5px; color:var(--ink)}
.sg .swhy{font-size:10px; color:var(--ink-dim); line-height:1.4}
.hintlite{color:var(--ink-dim); font-size:11.5px}
.feed{max-height:290px; overflow-y:auto; font-size:11.5px; line-height:1.55}
.feed div{padding:2px 0; border-bottom:1px solid #12171D}
.feed .me{color:var(--radiant)} .feed .en{color:#D08074} .feed .sys{color:var(--ink-dim)}

/* --- summary --- */
.overlay{display:none; position:fixed; inset:0; background:rgba(6,9,13,.9); z-index:50;
  align-items:center; justify-content:center}
.overlay.on{display:flex}
.obox{background:var(--panel); border:1px solid var(--rule-hi); border-radius:2px;
  padding:26px 32px; max-width:880px; width:92%}
.obox h2{color:var(--ink-hi); text-align:center; letter-spacing:.2em; text-transform:uppercase;
  font-size:16px; font-weight:600; margin-bottom:6px}
.overdict{text-align:center; font-size:13px; color:var(--ink-dim); margin:8px 0}
.overdict b{font-weight:600}
.oteams{display:flex; gap:26px; margin-top:16px}
.oteam{flex:1}
.oteam h4{letter-spacing:.14em; text-transform:uppercase; font-size:11.5px; margin-bottom:7px;
  display:inline-flex; align-items:center; gap:8px; font-weight:600}
.oteam h4::before{content:''; width:8px; height:8px; transform:rotate(45deg)}
.oteam.mine h4{color:var(--radiant)} .oteam.mine h4::before{background:var(--radiant)}
.oteam.enemy h4{color:var(--dire)} .oteam.enemy h4::before{background:var(--dire)}
.oline{display:flex; align-items:center; gap:8px; padding:3px 0; font-size:12.5px}
.oline img{width:50px; height:28px; object-fit:cover; border:1px solid var(--rule)}
.oline .op{color:var(--ink-dim); font-size:11px; margin-left:auto}
.obans{font-size:10.5px; color:var(--ink-dim); margin-top:10px; padding-top:8px;
  border-top:1px solid var(--rule)}
.obtns{text-align:center; margin-top:20px; display:flex; gap:14px; justify-content:center}

/* --- signature: the board reacts when YOUR reserve time is burning --- */
.burn{position:fixed; inset:0; pointer-events:none; z-index:40; opacity:0;
  transition:opacity .45s ease; box-shadow:inset 0 0 180px 34px rgba(194,60,42,.5)}
body.burning .burn{opacity:1; animation:burnpulse 1.7s ease-in-out infinite}
body.burning .clock.reserve{animation:ticktock 1s steps(1) infinite}
@keyframes burnpulse{0%,100%{opacity:.5} 50%{opacity:1}}
@keyframes ticktock{0%,49%{opacity:1} 50%,100%{opacity:.5}}

::-webkit-scrollbar{width:8px; height:8px}
::-webkit-scrollbar-thumb{background:var(--rule); border-radius:0}
::-webkit-scrollbar-track{background:transparent}

@media (max-width:1180px){
  .arena{flex-wrap:wrap}
  .pickcol{flex:1 1 100%}
  .slots{flex-direction:row}
  .pcard{flex:1}
  .pickcol .roster{display:none}
  .gridwrap{flex:1 1 100%; order:-1}
}
@media (max-width:820px){
  .topbar{grid-template-columns:1fr}
  .tbox.right .tline,.tbox.right .nm,.tbox.right .tmeta{flex-direction:row}
  .tbox.right .banstrip{justify-content:flex-start}
  .teamcols,.panels,.oteams{flex-direction:column}
  .panelbox.narrow{flex:1 1 auto}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.001ms !important; animation-iteration-count:1 !important;
    transition-duration:.001ms !important}
  body.burning .burn{opacity:.85}
}
</style>
</head>
<body>
<div class="burn" aria-hidden="true"></div>
<div class="wrap">
  <h1>Captains Mode</h1>
  <div class="sub">Patch 7.40 draft order · __LABEL__</div>

  <!-- ================= SETUP ================= -->
  <div class="setup on" id="setup">
    <div class="teamcols">
      <div class="tcol mine">
        <h2>Your team</h2>
        <div class="chips" id="mineChips"></div>
        <input type="text" id="mineSearch" placeholder="Search players" aria-label="Search players for your team">
        <div class="plist" id="mineList"></div>
      </div>
      <div class="tcol enemy">
        <h2>Opposition</h2>
        <input type="text" id="enemyName" placeholder="Opposition team name" style="margin-bottom:6px" aria-label="Opposition team name">
        <div class="chips" id="enemyChips"></div>
        <input type="text" id="enemySearch" placeholder="Search players" aria-label="Search players for the opposition">
        <div class="plist" id="enemyList"></div>
      </div>
    </div>
    <div class="opts">
      <div class="opt"><h3>First pick</h3>
        <div class="seg" id="firstSeg">
          <button data-v="me">You</button><button data-v="enemy">Opposition</button>
          <button data-v="random" class="on">Random</button>
        </div>
      </div>
      <div class="opt"><h3>Your side</h3>
        <div class="seg" id="sideSeg">
          <button data-v="radiant">Radiant</button><button data-v="dire">Dire</button>
          <button data-v="random" class="on">Random</button>
        </div>
      </div>
    </div>
    <div class="startrow"><button id="startBtn" class="primary">Start draft</button></div>
    <div class="warn" id="setupWarn"></div>
  </div>

  <!-- ================= BOARD ================= -->
  <div class="board" id="board">
    <div class="topbar">
      <div class="tbox" id="tboxL">
        <div class="tline">
          <span class="nm" id="tnL"></span>
          <span class="tmeta"><span class="fp" id="fpL"></span><span class="reserve" id="rvL"></span></span>
        </div>
        <div class="banstrip" id="bansL"></div>
      </div>
      <div class="tcenter">
        <div class="turnlabel" id="phaseName">&nbsp;</div>
        <div class="clock" id="clock">--</div>
        <div class="clockbar"><i id="clockFill" style="width:100%"></i></div>
        <div class="turnwho" id="turnWho">&nbsp;</div>
      </div>
      <div class="tbox right" id="tboxR">
        <div class="tline">
          <span class="nm" id="tnR"></span>
          <span class="tmeta"><span class="fp" id="fpR"></span><span class="reserve" id="rvR"></span></span>
        </div>
        <div class="banstrip" id="bansR"></div>
      </div>
    </div>

    <div class="spine" id="seqstrip"></div>

    <div class="arena">
      <div class="pickcol" id="colL">
        <div class="slots" id="slotsL"></div>
        <div class="roster" id="rosL"></div>
      </div>
      <div class="gridwrap">
        <div class="gridtop">
          <input type="text" id="heroSearch" placeholder="Search heroes" aria-label="Search heroes">
        </div>
        <div id="heroGrid"></div>
        <div class="lockrow">
          <div class="picking" id="pickingLbl"></div>
          <button id="lockBtn" class="primary" disabled>Select hero</button>
          <button id="resetBtn" style="font-size:10px; padding:6px 14px; margin-left:12px">Leave draft</button>
        </div>
      </div>
      <div class="pickcol" id="colR">
        <div class="slots" id="slotsR"></div>
        <div class="roster" id="rosR"></div>
      </div>
    </div>

    <div class="panels">
      <div class="panelbox narrow"><h3>Win read</h3>
        <div class="meterrow">
          <div class="mlab l" id="mlabL">50%</div>
          <div class="meter"><div class="mfl" id="meterFill" style="width:50%"></div>
            <div class="mfr"></div><div class="mmark"></div></div>
          <div class="mlab r" id="mlabR">50%</div>
        </div>
        <div class="mhint" id="mhint"></div>
      </div>
      <div class="panelbox"><h3>Scouting report</h3><div id="suggBox">
        <div class="hintlite">Hints appear on your turn.</div>
      </div></div>
      <div class="panelbox"><h3>Draft log</h3><div class="feed" id="feed"></div></div>
    </div>
  </div>

  <!-- ================= SUMMARY ================= -->
  <div class="overlay" id="overlay"><div class="obox">
    <h2>Draft complete</h2>
    <div class="overdict" id="sumVerdict"></div>
    <div class="oteams" id="sumTeams"></div>
    <div class="obtns">
      <button id="againBtn" class="primary">Draft again</button>
      <button id="newBtn">Change teams</button>
    </div>
  </div></div>
</div>

<script>
const HEROES = __HEROES__;   // hid -> {n, key, attr}
const POOL   = __POOL__;     // [{steam32, name, mmr, role}]
const CDN = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/";
/* attribute colours as the client shows them */
const ATTRS = [["str","Strength","#EE3B21"],["agi","Agility","#26E030"],
               ["int","Intelligence","#00A5E0"],["all","Universal","#B47CE8"]];

let ST = null;
let mineSel = [], enemySel = [];
let firstChoice = "random", sideChoice = "random";
let selectedHid = null;
let heroQuery = "";
let lastEventCount = -1;

function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

function img(hid){
  const h = HEROES[hid];
  if (!h || !h.key) return '<div class="txtfall">' + esc(h ? h.n : "?") + '</div>';
  return '<img loading="lazy" src="' + CDN + esc(h.key) + '.png" alt="' + esc(h.n) +
         '" onerror="this.onerror=null;this.replaceWith(document.createTextNode(this.alt))">';
}
function hname(hid){ const h = HEROES[hid]; return h ? h.n : ("#"+hid); }
function post(url, body){ return fetch(url, {method:"POST",
  headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})})
  .then(r=>r.json()).catch(()=>({ok:false,msg:"server unreachable"})); }
function fmtClock(s){ s = Math.max(0, Math.ceil(s));
  return Math.floor(s/60) + ":" + String(s%60).padStart(2,"0"); }
function rtClass(v){ return v >= 1 ? "pos" : (v <= -1 ? "neg" : "mid"); }
function rtText(v){ return (v >= 0 ? "+" : "") + v.toFixed(1); }

/* ================= setup screen ================= */
function renderChips(){
  const mk = (sel, elId) => {
    const el = document.getElementById(elId); el.innerHTML = "";
    sel.forEach(s32 => {
      const p = POOL.find(p => p.steam32 === s32); if (!p) return;
      const c = document.createElement("div"); c.className = "chip";
      c.innerHTML = "<b>" + esc(p.name) + "</b> " + p.mmr + " · P" + esc(p.role);
      c.title = "Remove"; c.onclick = () => {
        const i = sel.indexOf(s32); if (i >= 0) sel.splice(i, 1);
        renderChips(); renderLists(); };
      el.appendChild(c);
    });
  };
  mk(mineSel, "mineChips"); mk(enemySel, "enemyChips");
}
function renderLists(){
  const mk = (sel, other, q, elId) => {
    const el = document.getElementById(elId); el.innerHTML = "";
    const needle = q.trim().toLowerCase();
    POOL.filter(p => !sel.includes(p.steam32) && !other.includes(p.steam32) &&
                     (!needle || p.name.toLowerCase().includes(needle)))
        .slice(0, needle ? 40 : 25)
        .forEach(p => {
          const r = document.createElement("div"); r.className = "prow";
          r.innerHTML = "<span>" + esc(p.name) + "</span><span class=meta>" +
                        p.mmr + " · P" + esc(p.role) + "</span>";
          r.onclick = () => { if (sel.length >= 5) return;
            sel.push(p.steam32); renderChips(); renderLists(); };
          el.appendChild(r);
        });
  };
  mk(mineSel, enemySel, document.getElementById("mineSearch").value, "mineList");
  mk(enemySel, mineSel, document.getElementById("enemySearch").value, "enemyList");
}
document.getElementById("mineSearch").oninput = renderLists;
document.getElementById("enemySearch").oninput = renderLists;
function seg(id, set){
  const el = document.getElementById(id);
  el.querySelectorAll("button").forEach(b => b.onclick = () => {
    el.querySelectorAll("button").forEach(x => x.classList.remove("on"));
    b.classList.add("on"); set(b.dataset.v);
  });
}
seg("firstSeg", v => firstChoice = v);
seg("sideSeg", v => sideChoice = v);

document.getElementById("startBtn").onclick = async () => {
  const warn = document.getElementById("setupWarn");
  if (!mineSel.length || !enemySel.length){
    warn.textContent = "Both teams need at least one player."; return; }
  warn.textContent = "";
  let r = await post("/draft/teams", { mine: mineSel, enemy: enemySel,
    enemy_name: document.getElementById("enemyName").value || "The Dire" });
  if (!r.ok){ warn.textContent = r.msg || "Couldn't save teams."; return; }
  r = await post("/draft/start", { first: firstChoice, side: sideChoice });
  if (!r.ok) warn.textContent = r.msg || "Couldn't start the draft.";
};
document.getElementById("resetBtn").onclick = () => {
  if (confirm("Leave this draft?")) post("/draft/reset"); };
document.getElementById("againBtn").onclick = async () => {
  document.getElementById("overlay").classList.remove("on");
  await post("/draft/start", { first: firstChoice, side: sideChoice });
};
document.getElementById("newBtn").onclick = async () => {
  document.getElementById("overlay").classList.remove("on");
  await post("/draft/reset");
};

/* ================= hero grid (built once) =================
   The in-game hero grid: four attribute groups side by side, each alphabetical,
   at the client's column widths (STR/AGI/INT = 6, Universal = 4). Portraits
   only, name on hover. Search dims non-matches rather than collapsing the
   grid — positions stay put, so the spatial memory the drill is building
   survives a search. */
const GRID_COLS = { str: 6, agi: 6, int: 6, all: 4 };
function buildGrid(){
  const root = document.getElementById("heroGrid");
  root.className = "herogrid"; root.innerHTML = "";
  const mkTile = hid => {
    const t = document.createElement("div");
    t.className = "tile"; t.id = "tile" + hid;
    t.innerHTML = '<div class="im">' + img(hid) + '</div>' +
                  '<div class="rb" id="rb' + hid + '" style="display:none"></div>';
    t.onclick = () => selectHero(hid);
    return t;
  };
  ATTRS.forEach(([attr, label, color]) => {
    const sub = Object.keys(HEROES).map(Number)
      .filter(h => (HEROES[h].attr || "all") === attr)
      .sort((a,b) => HEROES[a].n.localeCompare(HEROES[b].n));
    if (!sub.length) return;
    const group = document.createElement("div"); group.className = "attrgroup";
    const head = document.createElement("div"); head.className = "attrhead";
    head.innerHTML = '<div class="dot" style="background:' + color + '"></div><span>' +
                     label + '</span>';
    group.appendChild(head);
    const g = document.createElement("div"); g.className = "grid";
    g.style.gridTemplateColumns = "repeat(" + (GRID_COLS[attr] || 6) + ", var(--tile))";
    sub.forEach(hid => g.appendChild(mkTile(hid)));
    group.appendChild(g);
    root.appendChild(group);
  });
}
function selectHero(hid){
  if (!ST || !ST.turn || !ST.turn.is_me) return;
  if (ST.taken.includes(hid)) return;
  selectedHid = (selectedHid === hid) ? null : hid;
  syncGrid();
}
async function lockIn(){
  if (selectedHid == null) return;
  const r = await post("/draft/act", { hid: selectedHid });
  if (r.ok) { selectedHid = null; poll(); }
}
document.getElementById("lockBtn").onclick = lockIn;
document.getElementById("heroSearch").oninput = e => {
  heroQuery = e.target.value.trim().toLowerCase(); syncGrid(); };
/* Enter locks the selection in — the clock doesn't wait for the mouse. */
document.addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  if (!ST || !ST.turn || !ST.turn.is_me || selectedHid == null) return;
  e.preventDefault(); lockIn();
});

function syncGrid(){
  const taken = new Set(ST ? ST.taken : []);
  const suggs = new Set((ST && ST.suggestions || []).map(s => s.hid));
  const ratings = ST && ST.ratings;
  Object.keys(HEROES).forEach(hid => {
    hid = Number(hid);
    const t = document.getElementById("tile" + hid); if (!t) return;
    t.classList.toggle("taken", taken.has(hid));
    t.classList.toggle("sel", selectedHid === hid);
    t.classList.toggle("sugg", suggs.has(hid) && !taken.has(hid));
    t.classList.toggle("dim", !!heroQuery && !hname(hid).toLowerCase().includes(heroQuery));
    const rb = document.getElementById("rb" + hid);
    if (ratings && ratings[hid] !== undefined && !taken.has(hid)){
      const v = ratings[hid];
      rb.style.display = "block";
      rb.textContent = rtText(v);
      rb.className = "rb " + rtClass(v);
      t.title = hname(hid) + " " + rtText(v);
    } else {
      rb.style.display = "none"; t.title = hname(hid);
    }
  });
  const myTurn = ST && ST.turn && ST.turn.is_me;
  const btn = document.getElementById("lockBtn");
  btn.disabled = !(myTurn && selectedHid != null);
  const lbl = document.getElementById("pickingLbl");
  if (myTurn){
    const verb = ST.turn.type === "ban" ? "Ban" : "Pick";
    let extra = "";
    if (selectedHid != null && ratings && ratings[selectedHid] !== undefined)
      extra = " (" + rtText(ratings[selectedHid]) + ")";
    lbl.textContent = selectedHid != null
      ? verb + ": " + hname(selectedHid) + extra
      : "Select a hero to " + verb.toLowerCase();
    btn.textContent = selectedHid != null ? verb + " hero" : "Select hero";
  } else {
    lbl.textContent = ""; btn.textContent = "Select hero";
  }
}

/* ================= board rendering ================= */
function sideTeams(){
  // left column = Radiant, right = Dire — like the in-game client
  const rad = ST.teams.find(t => t.side === "radiant") || ST.teams[0];
  const dire = ST.teams.find(t => t.side === "dire") || ST.teams[1];
  return [rad, dire];
}
function firstTag(tm){
  const fp = (ST.me_first && tm.is_me) || (ST.me_first === false && !tm.is_me);
  return fp ? "First pick" : "Second pick";
}

function renderTop(){
  const [L, R] = sideTeams();
  [[L,"L"],[R,"R"]].forEach(([tm, s]) => {
    if (!tm) return;
    document.getElementById("tbox" + s).className =
      "tbox " + (s === "R" ? "right " : "") + tm.side;
    document.getElementById("tn" + s).textContent =
      tm.label + (tm.is_me ? " (you)" : "");
    document.getElementById("fp" + s).textContent = firstTag(tm);
    const rv = document.getElementById("rv" + s);
    const sec = tm.reserve_ms / 1000;
    rv.innerHTML = "Reserve <b>" + fmtClock(sec) + "</b>";
    rv.classList.toggle("low", sec < 30);
  });
}

function renderMeter(){
  const [L] = sideTeams();
  if (ST.winprob == null || !L){
    document.getElementById("mhint").textContent = ST.has_meta ? "" :
      "No patch meta cached — ratings run on roster comfort only";
    return;
  }
  const myPct = ST.winprob;
  const leftPct = L.is_me ? myPct : 100 - myPct;
  document.getElementById("meterFill").style.width = leftPct + "%";
  const ml = document.getElementById("mlabL"), mr = document.getElementById("mlabR");
  ml.textContent = leftPct.toFixed(0) + "%";
  mr.textContent = (100 - leftPct).toFixed(0) + "%";
  ml.className = "mlab l " + sideTeams()[0].side;
  mr.className = "mlab r " + sideTeams()[1].side;
  const hint = document.getElementById("mhint");
  const diff = Math.abs(myPct - 50);
  if (diff < 3) hint.innerHTML = "Dead even so far";
  else hint.innerHTML = (myPct > 50 ? "<b>You are " + myPct.toFixed(0) + "% favoured</b>"
                                    : esc(ST.enemy_name) + " is " + (100-myPct).toFixed(0) + "% favoured");
}

function renderBans(){
  const [L, R] = sideTeams();
  [[L,"bansL"],[R,"bansR"]].forEach(([tm, elId]) => {
    const el = document.getElementById(elId); el.innerHTML = "";
    const nbans = 7;
    for (let i = 0; i < nbans; i++){
      const hid = tm && tm.bans[i];
      const b = document.createElement("div");
      b.className = "b" + (hid ? " used" : "");
      if (hid){ b.innerHTML = img(hid); b.title = "Banned: " + hname(hid); }
      el.appendChild(b);
    }
  });
}

function renderCols(){
  const [L, R] = sideTeams();
  [[L,"L"],[R,"R"]].forEach(([tm, s]) => {
    if (!tm) return;
    const col = document.getElementById("col" + s);
    col.className = "pickcol " + tm.side;
    if (ST.turn && ((ST.turn.is_me && tm.is_me) || (!ST.turn.is_me && !tm.is_me)))
      col.classList.add("active");
    const wrap = document.getElementById("slots" + s); wrap.innerHTML = "";
    const hist = {}; (ST.history || []).forEach(h => { if (h.hid != null) hist[h.hid] = h; });
    for (let k = 0; k < 5; k++){
      const p = tm.picks[k];
      const d = document.createElement("div"); d.className = "pcard";
      if (p){
        const h = hist[p.hid];
        const rt = h && h.rating != null
          ? '<div class="rt ' + rtClass(h.rating) + '">' + rtText(h.rating) + '</div>' : "";
        d.innerHTML = '<div class="imwrap">' + img(p.hid) + '</div>' + rt +
          '<div class="cap"><span class="h">' + esc(hname(p.hid)) + '</span>' +
          (p.player ? '<span class="pl">' + esc(p.player) + '</span>' : "") + '</div>';
      } else {
        d.innerHTML = '<div class="imwrap"><div class="ph">?</div></div>' +
                      '<div class="cap"><span class="h">&nbsp;</span></div>';
      }
      wrap.appendChild(d);
    }
    document.getElementById("ros" + s).innerHTML = tm.players
      .map(p => "<b>" + esc(p.name) + "</b> <span style='opacity:.7'>" + p.mmr +
                " · P" + esc(p.role) + "</span>").join("<br>");
  });
}

/* The 24-step spine, cut into the real CM phases. The sequence alternates
   ban/pick blocks, so a change of step type is exactly a phase boundary. */
function renderSeq(){
  const el = document.getElementById("seqstrip"); el.innerHTML = "";
  const hist = {}; (ST.history || []).forEach(h => hist[h.idx] = h);
  const [L] = sideTeams();
  const leftTeamIdx = (L && L.is_me) ? (ST.me_first ? 0 : 1) : (ST.me_first ? 1 : 0);
  let group = null, row = null, lastType = null;
  ST.seq.forEach((s, i) => {
    if (s.type !== lastType){
      lastType = s.type;
      group = document.createElement("div"); group.className = "phase " + s.type;
      const cap = document.createElement("div"); cap.className = "phcap";
      cap.textContent = s.type === "ban" ? "Ban" : "Pick";
      row = document.createElement("div"); row.className = "phrow";
      group.appendChild(cap); group.appendChild(row);
      el.appendChild(group);
    }
    const d = document.createElement("div");
    const side = (s.team === leftTeamIdx) ? "radiant" : "dire";
    d.className = "sq " + s.type + " " + side;
    if (i === ST.idx && ST.phase === "drafting"){
      d.classList.add("cur"); group.classList.add("curphase");
    }
    const h = hist[i];
    if (h){
      if (h.hid != null){ d.innerHTML = img(h.hid);
        if (h.type === "ban") d.classList.add("banned");
        d.title = (h.type === "ban" ? "Ban: " : "Pick: ") + hname(h.hid) +
                  (h.rating != null ? " " + rtText(h.rating) : "");
      } else d.classList.add("skipped");
    } else d.title = (s.type === "ban" ? "Ban" : "Pick");
    row.appendChild(d);
  });
}

function renderTurn(){
  const t = ST.turn;
  const who = document.getElementById("turnWho");
  const phase = document.getElementById("phaseName");
  const clock = document.getElementById("clock");
  const fill = document.getElementById("clockFill");
  if (!t){ who.textContent = "—"; clock.textContent = "--";
    document.body.classList.remove("burning"); return; }
  phase.textContent = t.phase_name;
  const verb = t.type === "ban" ? "banning" : "picking";
  who.textContent = (t.is_me ? "You are " : ST.enemy_name + " is ") + verb;
  who.classList.toggle("enemyturn", !t.is_me);
  const elapsed = (Date.now() - ST._recvAt + t.elapsed_ms) / 1000;
  const remain = t.step_secs - elapsed;
  const tm = ST.teams.find(x => x.is_me === t.is_me);
  const reserve = tm ? tm.reserve_ms / 1000 : 0;
  if (remain > 0){
    clock.textContent = fmtClock(remain);
    clock.className = "clock";
    fill.className = ""; fill.style.width = (remain / t.step_secs * 100) + "%";
    document.body.classList.remove("burning");
  } else {
    const rleft = Math.max(0, reserve + remain);
    clock.textContent = fmtClock(rleft);
    clock.className = "clock reserve";
    fill.className = "reserve";
    fill.style.width = (reserve > 0 ? rleft / reserve * 100 : 0) + "%";
    // the one dramatic moment: your own reserve time draining away
    document.body.classList.toggle("burning", t.is_me && rleft > 0);
  }
}

function partsLine(p){
  if (!p) return "";
  const bits = [];
  bits.push("comfort " + rtText(p.c));
  if (p.base != null) bits.push("patch " + rtText(p.p) + " (" + p.base.toFixed(1) + "%)");
  if (p.v) bits.push("vs " + rtText(p.v));
  if (p.w) bits.push("with " + rtText(p.w));
  return bits.join(" · ");
}

function renderSuggs(){
  const box = document.getElementById("suggBox");
  const s = ST.suggestions || [];
  if (!ST.turn || !ST.turn.is_me || !s.length){
    box.innerHTML = '<div class="hintlite">' +
      (ST.turn && ST.turn.is_me ? "No scouted lines here — trust your read."
                                : "Hints appear on your turn.") + '</div>';
    return;
  }
  box.innerHTML = "";
  s.forEach(x => {
    const d = document.createElement("div"); d.className = "sg";
    d.innerHTML = '<div class="srt ' + rtClass(x.rating) + '">' + rtText(x.rating) +
      '</div>' + img(x.hid) + '<div><div class="snm">' + esc(hname(x.hid)) +
      '</div><div class="swhy">' + partsLine(x.parts) +
      (x.why ? '<br>' + esc(x.why) : '') + '</div></div>';
    d.onclick = () => { selectHero(x.hid); window.scrollTo({top:0}); };
    box.appendChild(d);
  });
}

function renderFeed(){
  if (ST.events.length === lastEventCount) return;
  lastEventCount = ST.events.length;
  const el = document.getElementById("feed");
  const myTeam = ST.me_first ? 0 : 1;
  el.innerHTML = ST.events.slice().reverse().map(e => {
    let cls = "sys";
    if (e.team !== undefined) cls = (e.team === myTeam) ? "me" : "en";
    return '<div class="' + cls + '">' + esc(e.text) + '</div>';
  }).join("");
}

function renderSummary(){
  const ov = document.getElementById("overlay");
  if (ST.phase !== "done" || !ST.summary){ ov.classList.remove("on"); return; }
  if (ov.classList.contains("on")) return;
  const v = document.getElementById("sumVerdict");
  if (ST.winprob != null){
    const fav = ST.winprob >= 50;
    v.innerHTML = "Final read: <b style='color:var(--" + (fav ? "radiant" : "dire") +
      ")'>" + (fav ? "you are " + ST.winprob.toFixed(0) + "% favoured"
                   : esc(ST.enemy_name) + " is " + (100 - ST.winprob).toFixed(0) + "% favoured") +
      "</b>";
  } else v.textContent = "Study the board — would you win this game?";
  const el = document.getElementById("sumTeams"); el.innerHTML = "";
  const hist = {}; (ST.history || []).forEach(h => { if (h.hid != null) hist[h.hid] = h; });
  ST.summary.forEach(tm => {
    const d = document.createElement("div");
    d.className = "oteam " + (tm.is_me ? "mine" : "enemy");
    d.innerHTML = "<h4>" + esc(tm.team) + "</h4>" +
      tm.lineup.map(l => {
        const h = hist[l.hid];
        const rt = h && h.rating != null ? " <span class='srt " +
          rtClass(h.rating) + "' style='font-size:11px'>" + rtText(h.rating) + "</span>" : "";
        return '<div class="oline">' + img(l.hid) + "<span>" + esc(l.hero) + rt + "</span>" +
          (l.player ? '<span class="op">' + esc(l.player) + "</span>" : "") + "</div>";
      }).join("") +
      '<div class="obans">Bans: ' + (tm.bans.map(esc).join(", ") || "—") + "</div>";
    el.appendChild(d);
  });
  ov.classList.add("on");
}

/* ================= poll loop ================= */
async function poll(){
  try {
    const r = await fetch("/draft/state");
    ST = await r.json();
    ST._recvAt = Date.now();
  } catch (e) { return; }
  const drafting = ST.phase === "drafting" || ST.phase === "done";
  document.getElementById("setup").classList.toggle("on", !drafting);
  document.getElementById("board").classList.toggle("on", drafting);
  if (!drafting) document.body.classList.remove("burning");
  if (ST.phase === "setup"){
    if (!mineSel.length && ST.my_roster.length) { mineSel = ST.my_roster.slice();
      renderChips(); renderLists(); }
    if (!enemySel.length && ST.enemy_roster.length) { enemySel = ST.enemy_roster.slice();
      renderChips(); renderLists(); }
    const en = document.getElementById("enemyName");
    if (!en.value && ST.enemy_name && ST.enemy_name !== "The Dire")
      en.value = ST.enemy_name;
  }
  if (drafting){
    if (ST.turn && !ST.turn.is_me) selectedHid = null;
    renderTop(); renderMeter(); renderBans(); renderCols(); renderSeq();
    renderTurn(); renderSuggs(); renderFeed();
    syncGrid(); renderSummary();
  }
}
setInterval(() => { if (ST && ST.turn) renderTurn(); }, 250);  // smooth clock
setInterval(poll, 500);

buildGrid(); renderLists(); poll();
</script>
</body>
</html>
"""


def render_page(pool, heroes, label):
    heroes_json = json.dumps({str(k): v for k, v in heroes.items()}).replace(
        "</", "<\\/"
    )
    pool_json = json.dumps(pool).replace("</", "<\\/")
    return (PAGE
            .replace("__HEROES__", heroes_json)
            .replace("__POOL__", pool_json)
            .replace("__LABEL__", html.escape(str(label or "LD2L"))))
