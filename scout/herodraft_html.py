"""The --herodraft board page: a faithful Dota 2 Captains Mode draft UI.

Laid out and skinned like the real in-client CM screen: a top bar with both
rosters' player-slot cards flanking a large clock and reserve boxes, a turn
heading, the hero grid in the four attribute columns on the left, and on the
right a vertical draft panel showing the real 24-step Captains Mode sequence
with an action box underneath it for the current ban/pick.

The palette follows the client: blue-grey slate panels (not near-black),
Radiant olive / Dire brick, no gold and no serif except a small captain
crown. The tool's own intel - win probability, hero ratings, scouting hints
- stays subordinate to the drill, tucked into an opt-in hints drawer.

Self-contained page served by herodraft.py; polls /draft/state and posts
actions back. Hero portraits come from the Steam CDN (graceful text fallback
when offline). Sound is synthesized with the Web Audio API by default, with
an optional override: drop the user's own exported Dota 2 sounds into
scout/assets/sounds/ (see the README there) and the page will use them.
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
  /* background — the client's blue-grey slate, not near-black */
  --bg-top:#3A4754; --bg-edge:#1C242C;
  --void:#12171D; --panel:#1B222B; --panel-lit:#242F3A;
  --slab: rgba(22,27,33,.85);
  --rule:#33404C; --rule-hi:#4A5B6B;
  /* text — cool, not warm */
  --ink:#D6DDE3; --ink-hi:#F1F5F8; --ink-dim:#8C99A6;
  /* factions — Valve's actual values */
  --radiant:#92A525; --dire:#C23C2A;
  /* affordances */
  --go:#6B9A22; --go-hi:#84B92C; --good:#9BBF4A; --bad:#D65B45;
  --reserve-fill:#3B5068;
  --ui:"Segoe UI","Noto Sans",-apple-system,system-ui,Arial,sans-serif;
  /* tile scales with whichever dimension is tighter, so the four attribute
     groups (six rows each) always fit the leftover height without a page
     scroll, but never outgrow the available width either. Sized off the
     grid panel's own (container-query) width, not the viewport's, so it
     shrinks correctly when the hints drawer or draft panel take width. */
  --tile:clamp(26px, min(calc(4.5cqw - 4px), 9vh), 84px);
  /* Dota's real player-slot colours, roster order */
  --slotr1:#3375FF; --slotr2:#66FFBF; --slotr3:#BF00BF; --slotr4:#F3F00B; --slotr5:#FF6B00;
  --slotd1:#FE86C2; --slotd2:#A1B447; --slotd3:#65D9F7; --slotd4:#008321; --slotd5:#A46900;
}
*{box-sizing:border-box; margin:0; padding:0}
body{
  background:
    radial-gradient(ellipse 1300px 820px at 50% -6%, var(--bg-top) 0%, transparent 62%),
    linear-gradient(180deg, var(--bg-top) 0%, var(--bg-edge) 68%);
  color:var(--ink);
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
input[type=text],select{background:#0E1218; border:1px solid var(--rule); color:var(--ink);
  padding:6px 9px; font:400 12.5px var(--ui); width:100%; border-radius:2px}
input[type=text]::placeholder{color:#5D6874}
select{margin-bottom:6px}
.wrap{max-width:1720px; margin:0 auto; position:relative}
.vignette{position:fixed; inset:0; pointer-events:none; z-index:1;
  box-shadow:inset 0 0 220px 70px rgba(0,0,0,.55)}

/* ================= setup ================= */
.setup{display:none; max-width:1060px; margin:0 auto; position:relative; z-index:2}
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
.board{display:none; position:relative; z-index:2}
.board.on{display:flex; flex-direction:column; gap:6px; height:calc(100vh - 20px);
  min-height:0; overflow:hidden}
body.drafting h1, body.drafting .sub{display:none}

/* --- top bar: icons, rosters, clock, reserve, turn heading --- */
.topbar{flex:0 0 auto; position:relative; padding-top:2px}
.topicons{position:absolute; top:0; left:0; display:flex; align-items:center; gap:4px;
  z-index:3}
.iconbtn{background:transparent; border:1px solid transparent; color:var(--ink-dim);
  font-size:15px; line-height:1; padding:6px 8px; border-radius:2px; letter-spacing:0;
  text-transform:none; font-weight:400}
.iconbtn:hover{color:var(--ink-hi); border-color:var(--rule)}
.iconbtn.leave{font-size:10px; letter-spacing:.1em; text-transform:uppercase;
  font-weight:600; margin-left:4px}
.volslider{width:64px; accent-color:var(--ink-dim); vertical-align:middle}
.rosterrow{display:flex; align-items:flex-end; justify-content:center; gap:4vw;
  padding-top:2px}
.teamcards{display:flex; gap:.6vw}
.pcard{width:clamp(46px, 5.4vw, 78px); display:flex; flex-direction:column;
  align-items:center; gap:3px; position:relative}
.cardbody{width:100%; height:clamp(26px,3.4vw,40px);
  background:linear-gradient(180deg,#28323C,#151B22);
  clip-path:polygon(14% 0,100% 0,86% 100%,0% 100%);
  border-bottom:4px solid var(--slot-color, var(--ink-dim))}
.pname{font-size:clamp(8px,.72vw,10.5px); color:var(--ink-dim); text-align:center;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%}
.crown{position:absolute; top:-10px; left:50%; transform:translateX(-50%);
  font-size:12px; color:#E8C24A; text-shadow:0 1px 2px rgba(0,0,0,.6)}
.clockblock{display:flex; align-items:center; gap:clamp(8px,1.4vw,20px); padding:0 6px}
.reservebox{display:flex; flex-direction:column; align-items:center; gap:3px}
.rlabel{background:var(--reserve-fill); color:#CFE0F0; font:700 8px var(--ui);
  letter-spacing:.14em; text-transform:uppercase; padding:2px 9px; border-radius:1px}
.rtime{font:600 13px var(--ui); font-variant-numeric:tabular-nums; color:var(--ink)}
.rtime.hot{color:var(--bad)}
.clockcol{display:flex; flex-direction:column; align-items:center; min-width:92px}
.clock{font:300 clamp(34px,4.6vw,72px)/1 var(--ui); color:var(--ink-hi);
  font-variant-numeric:tabular-nums}
.clock.reserve{color:var(--bad)}
.cmlabel{font:700 10.5px var(--ui); letter-spacing:.22em; text-transform:uppercase;
  color:var(--ink-dim); margin-top:2px}
.turnheading{text-align:center; font:300 clamp(15px,2vw,29px)/1.3 var(--ui);
  letter-spacing:.1em; text-transform:uppercase; color:var(--ink-hi); margin-top:4px}
.turnheading.enemyturn{color:var(--ink-dim)}

/* --- main row: hero grid + optional hints drawer + draft column --- */
.mainrow{display:flex; gap:8px; flex:1; min-height:0}
.gridwrap{flex:1; min-width:0; display:flex; flex-direction:column; min-height:0;
  background:var(--panel); border:1px solid var(--rule); border-radius:2px;
  padding:7px 9px; overflow-x:auto; container-type:inline-size}
.gridtop{display:flex; align-items:center; justify-content:space-between; gap:10px;
  margin-bottom:6px; flex:0 0 auto}
.gridtop input{max-width:260px}
.hintsbtn{font-size:10px; padding:6px 14px; flex:0 0 auto}
.hintsbtn.on{background:linear-gradient(180deg,var(--panel-lit),var(--rule-hi));
  color:var(--ink-hi); border-color:var(--ink-dim)}
/* herogrid is sized to its content (sizeHeroGrid() sets an explicit pixel
   height on it, computed from real measurements), NOT stretched with flex:1
   — a stretched flex:1 row lets each attribute group's grid grow taller than
   its tiles can (capped at 1.6x tile width), which leaves a visible gap
   under every row. Sizing to content instead means any leftover vertical
   room in .gridwrap collapses into a single gap below the whole grid. */
.herogrid{flex:0 0 auto; display:flex; gap:12px; align-items:stretch;
  justify-content:center}
.attrgroup{display:flex; flex-direction:column; flex:0 0 auto; min-height:0}
.attrhead{display:flex; align-items:center; gap:6px; margin-bottom:6px; padding-bottom:4px;
  border-bottom:1px solid var(--rule); flex:0 0 auto}
.attrhead .dot{width:8px; height:8px; transform:rotate(45deg)}
.attrhead span{font-size:9.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--ink-dim); font-weight:600}
/* grid-template-columns/rows set inline per attribute (buildGrid): columns at
   the client's widths, rows shared uniformly at the tallest group's row count
   so every tile in every group gets the same height. minmax(0,1fr) rows
   divide up #heroGrid's own JS-measured height (sizeHeroGrid()) exactly, so
   there's no per-row slack for the image to fall short of. */
.grid{display:grid; gap:3px; flex:1; min-height:0}
.tile{width:var(--tile); height:100%; cursor:pointer; position:relative}
.tile .im{width:100%; height:100%; background:#0E1218;
  border:1px solid var(--rule); border-radius:1px; overflow:hidden; display:flex;
  align-items:center; justify-content:center;
  /* safety bounds only — sizeHeroGrid() already keeps rows within this range */
  min-height:calc(var(--tile)*0.56); max-height:calc(var(--tile)*2.3)}
.tile .im img{width:100%; height:100%; object-fit:cover; object-position:50% 30%;
  display:block}
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

/* --- hints drawer: the tool's own intel, off by default, toggled on demand --- */
.drawer{flex:0 0 300px; width:300px; min-width:0; background:var(--panel);
  border:1px solid var(--rule); border-radius:2px; padding:10px 12px; display:none;
  flex-direction:column; gap:0; min-height:0; overflow-y:auto}
.drawer.on{display:flex}
.panelbox{padding-bottom:10px; margin-bottom:10px; border-bottom:1px solid var(--rule)}
.panelbox:last-child{border-bottom:0; margin-bottom:0; padding-bottom:0}
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

/* --- right column: the 24-step draft panel + the action box under it --- */
.rightcol{flex:0 0 clamp(300px, 23vw, 400px); display:flex; flex-direction:column;
  gap:6px; min-height:0}
.draftpanel{flex:1; min-height:0; background:var(--slab); border:1px solid var(--rule);
  border-radius:2px; display:flex; flex-direction:column; overflow:hidden}
.dpheader{display:flex; flex:0 0 auto; border-bottom:1px solid var(--rule)}
.dpcol{flex:1; text-align:center; padding:6px 0; font:700 10.5px var(--ui);
  letter-spacing:.16em; text-transform:uppercase; color:var(--ink-dim);
  transition:color .3s}
.dpcol.radiant.active{color:var(--radiant)}
.dpcol.dire.active{color:var(--dire)}
.dpbody{flex:1; min-height:0; display:flex; flex-direction:column; position:relative;
  transition:background .3s ease}
.dpbody::before{content:''; position:absolute; left:50%; top:0; bottom:0; width:1px;
  background:var(--rule); z-index:0}
.dpbody.actradiant{background:linear-gradient(90deg, rgba(146,165,37,.22), transparent 58%)}
.dpbody.actdire{background:linear-gradient(270deg, rgba(194,60,42,.22), transparent 58%)}
/* Rows are packed two-steps-per-row where the sequence allows (see
   buildVisualRows), so there are ~14 rows for 24 steps, not 24. Pick rows
   get double the flex-grow of ban rows, so pick boxes end up roughly twice
   the height of ban boxes — matching the reference — instead of every row
   (and thus every box) being forced to the same size. */
.dprow{display:grid; grid-template-columns:1fr 26px 1fr; align-items:stretch;
  flex:1 1 0; min-height:0; position:relative; z-index:1}
.dprow.pick{flex-grow:2}
.dpslot{display:flex; align-items:center; min-height:0}
.dpslot.left{justify-content:flex-end; padding-right:3px}
.dpslot.right{justify-content:flex-start; padding-left:3px}
.dpnumcol{display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px}
.dpnum{font:600 9.5px var(--ui); color:var(--ink-dim); font-variant-numeric:tabular-nums;
  line-height:1}
.dpnum.cur{color:var(--ink-hi)}
.slotbox{height:75%; aspect-ratio:2.15; background:#05070A; border:1px solid var(--rule);
  border-radius:1px; position:relative; overflow:hidden}
.slotbox.pick{height:80%; aspect-ratio:2.0}
.slotbox.empty{border-style:dashed; opacity:.5}
.slotbox.skipped{opacity:.35}
.slotbox img{width:100%; height:100%; object-fit:cover; display:block}
.slotbox.banned img{filter:grayscale(1) brightness(.5)}
/* thick diagonal strike across the whole portrait, like the reference,
   plus a small ✕ at the outer edge if there's room for it */
.slotbox.banned::after{content:''; position:absolute; inset:0; z-index:0; background:
  linear-gradient(45deg,transparent 42%,rgba(194,60,42,.92) 46%,
  rgba(194,60,42,.92) 54%,transparent 58%)}
.slotbox .banx{position:absolute; top:50%; transform:translateY(-50%);
  color:#fff; font-weight:700; font-size:10px; background:rgba(5,7,10,.72);
  border-radius:50%; width:14px; height:14px; display:flex; align-items:center;
  justify-content:center; z-index:1}
.dpslot.left .banx{left:1px} .dpslot.right .banx{right:1px}
.slotbox.cur{background:transparent; border:1px solid #8CA2B5; display:flex;
  align-items:center; justify-content:center; color:var(--ink-hi);
  font:700 9.5px var(--ui); letter-spacing:.1em; text-transform:uppercase;
  animation:nextpulse 1.4s ease-in-out infinite}
@keyframes nextpulse{0%,100%{box-shadow:0 0 0 0 rgba(232,237,242,.5)}
  50%{box-shadow:0 0 0 4px rgba(232,237,242,0)}}

/* --- action box: selection + the one lock button, client-style --- */
/* Two lines: portrait + name (+ reason under the name) on top, the big
   BAN/PICK button full-width underneath — a name next to a button had too
   little room and truncated awkwardly ("No hero ..."). */
.actionbox{display:flex; flex-direction:column; gap:8px; padding:9px 12px;
  background:var(--panel); border:1px solid var(--rule); border-radius:2px; flex:0 0 auto}
.selinfo{display:flex; align-items:center; gap:10px; min-width:0}
.selim{width:56px; height:32px; background:#0E1218; border:1px solid var(--rule);
  border-radius:1px; overflow:hidden; display:flex; align-items:center; justify-content:center;
  flex:0 0 auto}
.selim img{width:100%; height:100%; object-fit:cover}
.selim .ph{color:#2A323B; font-size:16px}
.seltext{min-width:0; flex:1}
.selname{font-size:13.5px; color:var(--ink-hi); font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis}
.selreason{font-size:10px; color:var(--ink-dim); letter-spacing:.08em; text-transform:uppercase;
  min-height:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.lockbtn{width:100%; font-size:12.5px; padding:10px 16px; letter-spacing:.14em}
.lockbtn.ban{background:linear-gradient(180deg,#D6604A,#B0311F); border-color:#7A2015;
  color:#1B0705}
.lockbtn.ban:hover:not(:disabled){filter:brightness(1.12); color:#1B0705}
.lockbtn.pick{background:linear-gradient(180deg,var(--go-hi),var(--go)); border-color:#3F6614;
  color:#0E1408}
.lockbtn.pick:hover:not(:disabled){filter:brightness(1.12); color:#0E1408}

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

@media (max-width:900px){
  /* below here the board may stack and scroll: only the three target
     desktop sizes are required to fit with no page scroll */
  .board.on{height:auto; min-height:0; overflow:visible}
  body{overflow-x:hidden; overflow-y:auto}
  .topicons{position:static; margin-bottom:6px; justify-content:center}
  .rosterrow{flex-wrap:wrap; row-gap:8px}
  .mainrow{flex-direction:column; flex:0 0 auto}
  .gridwrap{min-height:340px}
  .herogrid{flex-wrap:wrap; overflow:visible}
  .drawer{width:100%; flex:0 0 auto}
  .rightcol{width:100%; flex:0 0 auto}
  .draftpanel{min-height:420px}
  .teamcols,.oteams{flex-direction:column}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.001ms !important; animation-iteration-count:1 !important;
    transition-duration:.001ms !important}
  body.burning .burn{opacity:.85}
  .slotbox.cur{animation:none; box-shadow:0 0 0 3px var(--ink-hi)}
}
</style>
</head>
<body>
<div class="vignette" aria-hidden="true"></div>
<div class="burn" aria-hidden="true"></div>
<div class="wrap">
  <h1>Captains Mode</h1>
  <div class="sub">Patch 7.40 draft order · __LABEL__</div>

  <!-- ================= SETUP ================= -->
  <div class="setup on" id="setup">
    <div class="teamcols">
      <div class="tcol mine">
        <h2>Your team</h2>
        <select id="mineLeague" aria-label="Your Team Scout team"></select>
        <div class="chips" id="mineChips"></div>
        <input type="text" id="mineSearch" placeholder="Search players" aria-label="Search players for your team">
        <div class="plist" id="mineList"></div>
      </div>
      <div class="tcol enemy">
        <h2>Opposition</h2>
        <select id="enemyLeague" aria-label="Opposition Team Scout team"></select>
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
      <div class="topicons">
        <button id="settingsBtn" class="iconbtn" type="button" aria-label="Settings">&#9881;</button>
        <button id="soundBtn" class="iconbtn" type="button" aria-label="Toggle sound" aria-pressed="true">&#128266;</button>
        <input type="range" id="volumeSlider" class="volslider" min="0" max="100" value="50" aria-label="Sound volume">
        <button id="resetBtn" class="iconbtn leave" type="button" aria-label="Leave draft">Leave draft</button>
      </div>
      <div class="rosterrow">
        <div class="teamcards" id="cardsL"></div>
        <div class="clockblock">
          <div class="reservebox"><div class="rlabel">Reserve</div><div class="rtime" id="rvL">--</div></div>
          <div class="clockcol">
            <div class="clock" id="clock">--:--</div>
            <div class="cmlabel">Captains Mode</div>
          </div>
          <div class="reservebox"><div class="rlabel">Reserve</div><div class="rtime" id="rvR">--</div></div>
        </div>
        <div class="teamcards" id="cardsR"></div>
      </div>
      <div class="turnheading" id="turnHeading" aria-live="polite">&nbsp;</div>
    </div>

    <div class="mainrow">
      <div class="gridwrap">
        <div class="gridtop">
          <input type="text" id="heroSearch" placeholder="Search heroes" aria-label="Search heroes">
          <button id="hintsToggle" class="hintsbtn" type="button" aria-pressed="false">Hints</button>
        </div>
        <div id="heroGrid"></div>
      </div>
      <div class="drawer" id="hintsDrawer">
        <div class="panelbox"><h3>Win read</h3>
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
      </div>
      <div class="rightcol">
        <div class="draftpanel" id="draftPanel">
          <div class="dpheader">
            <div class="dpcol radiant" id="dpHeadL">Radiant</div>
            <div class="dpcol dire" id="dpHeadR">Dire</div>
          </div>
          <div class="dpbody" id="dpBody"></div>
        </div>
        <div class="actionbox">
          <div class="selinfo">
            <div class="selim" id="selIm"><div class="ph">?</div></div>
            <div class="seltext">
              <div class="selname" id="selName">No hero selected</div>
              <div class="selreason" id="selReason"></div>
            </div>
          </div>
          <button id="lockBtn" class="lockbtn" disabled>Select a hero</button>
        </div>
      </div>
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
const LEAGUE = __LEAGUE__;   // [{key, name, short, roster}]
const CDN = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/";
/* attribute colours as the client shows them */
const ATTRS = [["str","Strength","#EE3B21"],["agi","Agility","#26E030"],
               ["int","Intelligence","#00A5E0"],["all","Universal","#B47CE8"]];
/* real Dota player-slot colours, in roster order */
const SLOT_COLORS = {
  radiant: ["#3375FF","#66FFBF","#BF00BF","#F3F00B","#FF6B00"],
  dire:    ["#FE86C2","#A1B447","#65D9F7","#008321","#A46900"],
};

let ST = null;
let mineSel = [], enemySel = [];
let mineKey = "", enemyKey = "";
let firstChoice = "random", sideChoice = "random";
let selectedHid = null;
let heroQuery = "";

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

/* ================= sound =================
   Wired to the user's own exported Dota 2 draft sounds in
   scout/assets/sounds/ (event names + relative volumes taken from the
   client's own soundevents/game_sounds_ui_imported.vsndevts) — see the
   README there. Any name missing on disk falls back to a small synthesized
   Web Audio equivalent, so the board always makes SOME sound. Audio never
   starts before the user's first interaction (autoplay rules); Start draft
   counts, and so does touching the sound controls themselves. */
const SOUND_VOL = {                 // relative volume, straight from the client
  music:0.35, draft_start:0.16, advance:0.2, ban:0.16, pick:0.16,
  pick_made:0.66, countdown:0.3, announcer_10s:0.66, announcer_5s:0.66,
  your_ban:0.66, your_pick:0.66, enemy_ban:0.66, enemy_pick:0.66,
};
const SOUND_NAMES = Object.keys(SOUND_VOL);
const SOUND_EXTS = ["mp3","ogg","wav","webm"];
const realSounds = {};
let soundEventLog = [];             // for Playwright verification: which events fired
let audioCtx = null;
let userInteracted = false;
let soundOn = true;
let volume = 0.5;
try { const s = localStorage.getItem("hd_sound"); if (s !== null) soundOn = s === "1"; } catch (e) {}
try { const v = localStorage.getItem("hd_volume"); if (v !== null && !isNaN(+v)) volume = Math.min(1, Math.max(0, +v)); } catch (e) {}
let musicEl = null, musicFading = false;

function markInteracted(){
  userInteracted = true;
  ensureAudioCtx();
}
function ensureAudioCtx(){
  if (audioCtx) return audioCtx;
  try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {}
  return audioCtx;
}
async function probeRealSounds(){
  for (const name of SOUND_NAMES){
    for (const ext of SOUND_EXTS){
      const url = "/sounds/" + name + "." + ext;
      try {
        const r = await fetch(url, {method:"HEAD", cache:"no-store"});
        if (r.ok){ realSounds[name] = url; break; }
      } catch (e) {}
    }
  }
  if (realSounds.music){
    musicEl = new Audio(realSounds.music);
    musicEl.loop = true;
    musicEl.volume = soundOn ? volume * SOUND_VOL.music : 0;
  }
}
function scheduleTone(delay, freq, dur, gain, type){
  const ctx = ensureAudioCtx(); if (!ctx || gain <= 0) return;
  const t0 = ctx.currentTime + delay;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type || "sine";
  o.frequency.setValueAtTime(freq, t0);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.linearRampToValueAtTime(gain, t0 + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g); g.connect(ctx.destination);
  o.start(t0); o.stop(t0 + dur + 0.03);
}
function synthThudGain(gain){
  const ctx = ensureAudioCtx(); if (!ctx) return;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = "sine";
  o.frequency.setValueAtTime(160, ctx.currentTime);
  o.frequency.exponentialRampToValueAtTime(55, ctx.currentTime + 0.28);
  g.gain.setValueAtTime(gain, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.32);
  o.connect(g); g.connect(ctx.destination);
  o.start(); o.stop(ctx.currentTime + 0.34);
}
/* Fallback synthesis for each real-file event, used only when that file is
   missing from scout/assets/sounds/. `gain` is already volume-scaled. */
const SYNTH_FALLBACK = {
  draft_start:   g => { scheduleTone(0, 587.33, 0.16, g, "triangle"); scheduleTone(0.11, 880, 0.22, g, "triangle"); },
  advance:       g => scheduleTone(0, 1200, 0.045, g * 0.6, "sine"),
  ban:           g => synthThudGain(g),
  pick:          g => { scheduleTone(0, 523.25, 0.28, g, "triangle"); scheduleTone(0.09, 783.99, 0.28, g, "triangle"); },
  pick_made:     g => scheduleTone(0, 1318.5, 0.24, g, "triangle"),
  countdown:     g => scheduleTone(0, 1000, 0.08, g, "sine"),
  announcer_10s: g => { scheduleTone(0, 700, 0.15, g, "square"); scheduleTone(0.17, 700, 0.15, g, "square"); },
  announcer_5s:  g => { scheduleTone(0, 920, 0.14, g, "square"); scheduleTone(0.15, 920, 0.14, g, "square"); },
  your_ban:      g => { scheduleTone(0, 740, 0.14, g, "square"); scheduleTone(0.16, 980, 0.16, g, "square"); },
  your_pick:     g => { scheduleTone(0, 740, 0.14, g, "square"); scheduleTone(0.16, 980, 0.16, g, "square"); },
  enemy_ban:     g => scheduleTone(0, 420, 0.22, g, "sawtooth"),
  enemy_pick:    g => scheduleTone(0, 420, 0.22, g, "sawtooth"),
};
function synthDraftComplete(){
  // Only reached when NO real sound files exist at all (see poll()) — the
  // client itself plays no dedicated "draft complete" line.
  const ctx = ensureAudioCtx(); if (!ctx) return;
  [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
    scheduleTone(i * 0.12, f, 0.4, 0.28 * volume, "triangle"));
}
function playSound(name){
  if (!soundOn || !userInteracted) return;
  soundEventLog.push(name);
  if (soundEventLog.length > 200) soundEventLog.splice(0, soundEventLog.length - 200);
  const base = SOUND_VOL[name] != null ? SOUND_VOL[name] : 0.3;
  const url = realSounds[name];
  if (url){
    try {
      const a = new Audio(url);
      a.volume = Math.max(0, Math.min(1, volume * base));
      a.play().catch(() => {});
      return;
    } catch (e) {}
  }
  const fn = SYNTH_FALLBACK[name];
  if (fn) fn(Math.max(0.0001, base * 0.45 * volume));
}
function anyRealSounds(){ return Object.keys(realSounds).length > 0; }
function startMusic(){
  if (!musicEl || !userInteracted || !soundOn) return;
  musicFading = false;
  musicEl.volume = volume * SOUND_VOL.music;
  musicEl.currentTime = 0;
  musicEl.play().catch(() => {});
}
function stopMusicFade(durationMs){
  durationMs = durationMs || 2000;
  if (!musicEl || musicEl.paused || musicFading) return;
  musicFading = true;
  const startVol = musicEl.volume;
  const t0 = performance.now();
  const step = () => {
    if (!musicEl) return;
    const frac = Math.min(1, (performance.now() - t0) / durationMs);
    musicEl.volume = startVol * (1 - frac);
    if (frac < 1) requestAnimationFrame(step);
    else { musicEl.pause(); musicFading = false; }
  };
  requestAnimationFrame(step);
}
function applySoundUI(){
  const btn = document.getElementById("soundBtn");
  btn.innerHTML = soundOn ? "&#128266;" : "&#128263;";
  btn.setAttribute("aria-pressed", soundOn ? "true" : "false");
  document.getElementById("volumeSlider").value = Math.round(volume * 100);
  if (musicEl && !musicFading) musicEl.volume = soundOn ? volume * SOUND_VOL.music : 0;
}
document.getElementById("soundBtn").onclick = () => {
  markInteracted();
  soundOn = !soundOn;
  try { localStorage.setItem("hd_sound", soundOn ? "1" : "0"); } catch (e) {}
  applySoundUI();
};
document.getElementById("volumeSlider").oninput = e => {
  markInteracted();
  volume = Math.max(0, Math.min(1, e.target.value / 100));
  try { localStorage.setItem("hd_volume", String(volume)); } catch (e) {}
  applySoundUI();
};
applySoundUI();

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
function leagueByKey(key){ return (LEAGUE || []).find(t => t.key === key); }
function fillLeagueSelects(){
  [["mineLeague","Your Team Scout team"],
   ["enemyLeague","Opposition from Team Scout"]].forEach(([id, blank]) => {
    const el = document.getElementById(id);
    el.innerHTML = '<option value="">' + esc(blank) + '</option>';
    (LEAGUE || []).forEach(t => {
      const o = document.createElement("option");
      o.value = t.key;
      o.textContent = t.short === t.name ? t.name : (t.short + " — " + t.name);
      el.appendChild(o);
    });
  });
}
function applyLeague(side, key){
  const t = leagueByKey(key);
  if (side === "mine"){
    mineKey = t ? t.key : "";
    if (t) mineSel = t.roster.filter(id => !enemySel.includes(id)).slice(0, 5);
  } else {
    enemyKey = t ? t.key : "";
    if (t){
      enemySel = t.roster.filter(id => !mineSel.includes(id)).slice(0, 5);
      document.getElementById("enemyName").value = t.name;
    }
  }
  document.getElementById(side === "mine" ? "mineLeague" : "enemyLeague").value = key || "";
  renderChips(); renderLists();
}
document.getElementById("mineLeague").onchange = e => applyLeague("mine", e.target.value);
document.getElementById("enemyLeague").onchange = e => applyLeague("enemy", e.target.value);
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
  markInteracted();
  const warn = document.getElementById("setupWarn");
  if (!mineSel.length || !enemySel.length){
    warn.textContent = "Both teams need at least one player."; return; }
  warn.textContent = "";
  let r = await post("/draft/teams", { mine: mineSel, enemy: enemySel,
    enemy_name: document.getElementById("enemyName").value || "The Dire",
    mine_key: mineKey || null, enemy_key: enemyKey || null });
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
/* hints: off by default, remembered per browser (never required to draft) */
let hintsOn = false;
try { hintsOn = localStorage.getItem("hd_hints") === "1"; } catch (e) {}
function applyHintsUI(){
  document.getElementById("hintsDrawer").classList.toggle("on", hintsOn);
  const btn = document.getElementById("hintsToggle");
  btn.classList.toggle("on", hintsOn);
  btn.setAttribute("aria-pressed", hintsOn ? "true" : "false");
  syncGrid();
  sizeHeroGrid();   // the drawer changes gridwrap's width, which changes nothing
                     // for tile size (height-driven) but the grid may need to
                     // re-wrap/re-centre — cheap, so just always re-measure
}
document.getElementById("hintsToggle").onclick = () => {
  hintsOn = !hintsOn;
  try { localStorage.setItem("hd_hints", hintsOn ? "1" : "0"); } catch (e) {}
  applyHintsUI();
};
function buildGrid(){
  const root = document.getElementById("heroGrid");
  root.className = "herogrid"; root.innerHTML = "";
  const mkTile = hid => {
    const t = document.createElement("div");
    t.className = "tile"; t.id = "tile" + hid;
    t.tabIndex = 0; t.setAttribute("role", "button"); t.setAttribute("aria-label", hname(hid));
    t.innerHTML = '<div class="im">' + img(hid) + '</div>' +
                  '<div class="rb" id="rb' + hid + '" style="display:none"></div>';
    t.onclick = () => selectHero(hid);
    /* Space always toggles the selection; Enter selects on first press but,
       once already selected, falls through to the document-level handler
       below that locks it in - so Enter both selects and confirms, in two
       presses, the same as click-then-lock. */
    t.addEventListener("keydown", e => {
      if (e.key === " "){ e.preventDefault(); selectHero(hid); return; }
      if (e.key === "Enter" && selectedHid !== hid){
        e.preventDefault(); e.stopPropagation(); selectHero(hid);
      }
    });
    return t;
  };
  const groups = ATTRS.map(([attr, label, color]) => {
    const sub = Object.keys(HEROES).map(Number)
      .filter(h => (HEROES[h].attr || "all") === attr)
      .sort((a,b) => HEROES[a].n.localeCompare(HEROES[b].n));
    const cols = GRID_COLS[attr] || 6;
    return {attr, label, color, sub, cols, rows: Math.ceil(sub.length / cols)};
  }).filter(g => g.sub.length);
  /* every group shares the tallest group's row count, so a tile is the same
     height everywhere regardless of which attribute has fewer heroes */
  const maxRows = Math.max(1, ...groups.map(g => g.rows));
  heroMaxRows = maxRows;
  heroGroupCols = groups.map(g => g.cols);
  groups.forEach(({label, color, sub, cols}) => {
    const group = document.createElement("div"); group.className = "attrgroup";
    const head = document.createElement("div"); head.className = "attrhead";
    head.innerHTML = '<div class="dot" style="background:' + color + '"></div><span>' +
                     label + '</span>';
    group.appendChild(head);
    const g = document.createElement("div"); g.className = "grid";
    g.style.gridTemplateColumns = "repeat(" + cols + ", var(--tile))";
    g.style.gridTemplateRows = "repeat(" + maxRows + ", minmax(0,1fr))";
    sub.forEach(hid => g.appendChild(mkTile(hid)));
    group.appendChild(g);
    root.appendChild(group);
  });
  sizeHeroGrid();
}

/* Measures the real, current layout (not a viewport-relative guess) to pick
   a tile size that fills #heroGrid's available height with no per-row gap,
   WITHOUT ever making a group wider than the panel (that would scroll the
   Strength group off-screen, failing "all four attribute groups visible"):
     rowBudget = (available height - attribute header - inter-row gaps) / rows
     colBudget = (available width - inter-group/intra-group gaps) / total cols
     tile      = min(colBudget, rowBudget / TILE_RATIO), clamped to [26, 84]
   TILE_RATIO (2.3, matching .tile .im's max-height) is taller than a literal
   Dota portrait's ~1.6 aspect: at this panel's actual width (a fixed-width
   draft column takes ~23% of it), the hero grid is normally width-bound, so
   raising the ratio lets the image use more of the height that a stricter
   1.6 would otherwise leave as gap, at the cost of a slightly taller crop.
   #heroGrid then gets that exact computed height (flex:0 0 auto, not
   flex:1), so any leftover space collapses into ONE gap below the whole
   grid instead of one gap under every row. Only when height is the binding
   term does the fill-the-height goal fully land (zero leftover); when width
   binds instead, a bigger bottom gap is the correct trade-off — it beats
   hiding a whole attribute group behind a horizontal scrollbar. Re-run on
   hints toggle and window resize since both change gridwrap's box. */
let heroMaxRows = 6;
let heroGroupCols = [6, 6, 6, 4];
let sizeHeroGridQueued = false;
function sizeHeroGrid(){
  const wrap = document.querySelector(".gridwrap");
  const gridtop = document.querySelector(".gridtop");
  const heroGridEl = document.getElementById("heroGrid");
  const head = heroGridEl && heroGridEl.querySelector(".attrhead");
  if (!wrap || !gridtop || !heroGridEl || !head) return;
  const wrapRect = wrap.getBoundingClientRect();
  const wrapCS = getComputedStyle(wrap);
  const padBottom = parseFloat(wrapCS.paddingBottom) || 0;
  const padLeft = parseFloat(wrapCS.paddingLeft) || 0;
  const padRight = parseFloat(wrapCS.paddingRight) || 0;
  const topRect = gridtop.getBoundingClientRect();
  const topMarginBottom = parseFloat(getComputedStyle(gridtop).marginBottom) || 0;
  const headRect = head.getBoundingClientRect();
  const headMarginBottom = parseFloat(getComputedStyle(head).marginBottom) || 0;
  const availH = (wrapRect.bottom - padBottom) -
                 (topRect.bottom + topMarginBottom) - (headRect.height + headMarginBottom);
  const availW = wrapRect.width - padLeft - padRight;
  if (availH <= 0 || availW <= 0) return;

  const rows = heroMaxRows;
  const rowGapTotal = (rows - 1) * 3;
  const rowBudget = (availH - rowGapTotal) / rows;

  const totalCols = heroGroupCols.reduce((a, b) => a + b, 0);
  const totalColGapsWithin = heroGroupCols.reduce((a, c) => a + (c - 1) * 3, 0);
  const totalInterGroupGaps = (heroGroupCols.length - 1) * 12;
  const colBudget = (availW - totalInterGroupGaps - totalColGapsWithin) / totalCols;

  const TILE_RATIO = 2.3;
  const tile = Math.max(26, Math.min(84, Math.min(colBudget, rowBudget / TILE_RATIO)));
  document.documentElement.style.setProperty("--tile", tile.toFixed(2) + "px");
  const gridHeight = Math.min(rows * (tile * TILE_RATIO) + rowGapTotal, availH);
  heroGridEl.style.height = gridHeight.toFixed(2) + "px";
}
window.addEventListener("resize", () => {
  if (sizeHeroGridQueued) return;
  sizeHeroGridQueued = true;
  requestAnimationFrame(() => { sizeHeroGridQueued = false; sizeHeroGrid(); });
});
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
    t.classList.toggle("sugg", hintsOn && suggs.has(hid) && !taken.has(hid));
    t.classList.toggle("dim", !!heroQuery && !hname(hid).toLowerCase().includes(heroQuery));
    const rb = document.getElementById("rb" + hid);
    if (hintsOn && ratings && ratings[hid] !== undefined && !taken.has(hid)){
      const v = ratings[hid];
      rb.style.display = "block";
      rb.textContent = rtText(v);
      rb.className = "rb " + rtClass(v);
      t.title = hname(hid) + " " + rtText(v);
    } else {
      rb.style.display = "none"; t.title = hname(hid);
    }
  });
  renderActionBox();
}

/* ================= action box ================= */
function renderActionBox(){
  const selIm = document.getElementById("selIm");
  const selName = document.getElementById("selName");
  const selReason = document.getElementById("selReason");
  const btn = document.getElementById("lockBtn");
  const t = ST && ST.turn;
  if (!t){
    selIm.innerHTML = '<div class="ph">?</div>';
    selName.textContent = "No hero selected";
    selReason.textContent = "";
    btn.className = "lockbtn"; btn.disabled = true; btn.textContent = "Select a hero";
    return;
  }
  const verb = t.type === "ban" ? "Ban" : "Pick";
  btn.className = "lockbtn " + t.type;
  if (t.is_me){
    if (selectedHid != null){
      selIm.innerHTML = img(selectedHid);
      selName.textContent = hname(selectedHid);
      selReason.textContent = "";
      btn.disabled = false;
      btn.textContent = verb + " " + hname(selectedHid);
    } else {
      selIm.innerHTML = '<div class="ph">?</div>';
      selName.textContent = "No hero selected";
      selReason.textContent = "Your turn to " + verb.toLowerCase();
      btn.disabled = true;
      btn.textContent = "Select a hero";
    }
  } else {
    selIm.innerHTML = '<div class="ph">?</div>';
    selName.textContent = "No hero selected";
    selReason.textContent = (ST.enemy_name || "Opponent") + " is " +
      (t.type === "ban" ? "banning" : "picking");
    btn.disabled = true;
    btn.textContent = verb + " hero";
  }
}

/* ================= board rendering ================= */
function sideTeams(){
  // left = Radiant, right = Dire — like the in-game client. ST.teams is
  // always indexed [0]=first-pick,[1]=second-pick, and each seq step's
  // "team" field is that same index, so ST.teams[step.team] gives the
  // acting team directly without re-deriving F/S from "is_me".
  const rad = ST.teams.find(t => t.side === "radiant") || ST.teams[0];
  const dire = ST.teams.find(t => t.side === "dire") || ST.teams[1];
  return [rad, dire];
}

function renderTeamCards(){
  const [L, R] = sideTeams();
  [[L, "cardsL"], [R, "cardsR"]].forEach(([tm, elId]) => {
    const el = document.getElementById(elId);
    el.innerHTML = "";
    if (!tm) return;
    const colors = SLOT_COLORS[tm.side] || SLOT_COLORS.radiant;
    for (let i = 0; i < 5; i++){
      const p = tm.players[i];
      const card = document.createElement("div"); card.className = "pcard";
      // Team Scout's roster data carries no captain flag, so no crown is
      // shown here — see herodraft_html.py's docstring / the delivery report.
      card.innerHTML =
        '<div class="cardbody" style="--slot-color:' + colors[i] + '"></div>' +
        '<div class="pname">' + esc(p ? p.name : "") + '</div>';
      el.appendChild(card);
    }
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

/* The 24-step Captains Mode sequence, drawn as a vertical panel: bans as
   small wide boxes, picks as larger ones, each on its acting team's side of
   a centre line carrying the step number. The current step shows an
   outlined BAN/PICK button in place of a hero. */
/* Packs the 24 fixed steps into visual rows the way the client does: two
   CONSECUTIVE steps of the same type but opposite teams share one row
   (Radiant left / Dire right, both step numbers stacked in the centre
   column); a step whose neighbour is the same team, or a different type
   (a ban next to a pick), starts its own row. This is why one bare CM
   phase boundary (a same-team pair, e.g. the F,F opener) still gets two
   rows while the rest pair up — for the current 7/2/3/6/4/2 sequence that
   packs 24 steps into 14 rows, matching the reference board. Computed once
   since CM_SEQUENCE (ST.seq) never changes shape during a draft. */
let draftVisualRows = null;
function buildVisualRows(seq){
  const rows = [];
  let i = 0;
  while (i < seq.length){
    if (i + 1 < seq.length && seq[i + 1].type === seq[i].type &&
        seq[i + 1].team !== seq[i].team){
      rows.push([i, i + 1]);
      i += 2;
    } else {
      rows.push([i]);
      i += 1;
    }
  }
  return rows;
}

function renderDraftPanel(){
  const headL = document.getElementById("dpHeadL"), headR = document.getElementById("dpHeadR");
  const body = document.getElementById("dpBody");
  const t = ST.turn;
  const activeTeam = t ? ST.teams[t.team] : null;
  const activeSide = activeTeam ? activeTeam.side : null;
  headL.classList.toggle("active", activeSide === "radiant");
  headR.classList.toggle("active", activeSide === "dire");
  body.className = "dpbody" + (activeSide ? " act" + activeSide : "");
  const hist = {}; (ST.history || []).forEach(h => { hist[h.idx] = h; });
  if (!draftVisualRows) draftVisualRows = buildVisualRows(ST.seq);
  body.innerHTML = "";
  draftVisualRows.forEach(stepIdxs => {
    const row = document.createElement("div"); row.className = "dprow";
    const rowType = ST.seq[stepIdxs[0]].type;   // both steps share it when paired
    row.classList.add(rowType);
    const slotL = document.createElement("div"); slotL.className = "dpslot left";
    const slotR = document.createElement("div"); slotR.className = "dpslot right";
    const numCol = document.createElement("div"); numCol.className = "dpnumcol";
    stepIdxs.forEach(i => {
      const s = ST.seq[i];
      const team = ST.teams[s.team];
      const side = team ? team.side : "radiant";
      const isCur = i === ST.idx && ST.phase === "drafting";
      const num = document.createElement("div");
      num.className = "dpnum" + (isCur ? " cur" : "");
      num.textContent = String(i + 1);
      numCol.appendChild(num);
      const box = document.createElement("div");
      box.className = "slotbox " + (s.type === "pick" ? "pick" : "ban");
      const h = hist[i];
      if (isCur){
        box.classList.add("cur");
        box.textContent = s.type === "ban" ? "Ban" : "Pick";
      } else if (h && h.hid != null){
        box.innerHTML = img(h.hid);
        box.title = (s.type === "ban" ? "Banned: " : "Picked: ") + hname(h.hid);
        if (s.type === "ban"){
          box.classList.add("banned");
          const x = document.createElement("div"); x.className = "banx"; x.textContent = "✕";
          box.appendChild(x);
        }
      } else if (h){
        box.classList.add("skipped");
        box.title = "Skipped";
      } else {
        box.classList.add("empty");
      }
      (side === "radiant" ? slotL : slotR).appendChild(box);
    });
    row.appendChild(slotL); row.appendChild(numCol); row.appendChild(slotR);
    body.appendChild(row);
  });
}

/* ================= clock / reserve / turn heading + tick sounds ================= */
let lastTickWhole = null;
let lastAnnouncedIdx = null;        // per-turn: your_ban/your_pick/enemy_ban/enemy_pick
let turnFlags = {a10: false, a5: false};   // per-turn: each announcer fires once
let burningIsMe = null;

function updateReserveDisplays(){
  const [L, R] = sideTeams();
  [[L,"rvL"],[R,"rvR"]].forEach(([tm, id]) => {
    const el = document.getElementById(id); if (!tm) return;
    el.textContent = fmtClock(tm.reserve_ms / 1000);
    el.classList.toggle("hot", burningIsMe !== null && tm.is_me === burningIsMe);
  });
}

function renderTurn(){
  const t = ST.turn;
  const clock = document.getElementById("clock");
  const heading = document.getElementById("turnHeading");
  if (!t){
    clock.textContent = "--:--"; clock.className = "clock";
    heading.textContent = " "; heading.className = "turnheading";
    document.body.classList.remove("burning");
    burningIsMe = null; lastTickWhole = null; lastAnnouncedIdx = null;
    updateReserveDisplays();
    return;
  }
  // a new turn: announce it once (your_ban/your_pick/enemy_ban/enemy_pick),
  // and reset the per-turn 10s/5s announcer flags + tick tracking
  if (ST.idx !== lastAnnouncedIdx){
    if (lastAnnouncedIdx !== null) playSound("advance");   // order moved on
    playSound((t.is_me ? "your_" : "enemy_") + t.type);
    lastAnnouncedIdx = ST.idx;
    turnFlags = {a10: false, a5: false};
    lastTickWhole = null;
  }
  const elapsed = (Date.now() - ST._recvAt + t.elapsed_ms) / 1000;
  const remain = t.step_secs - elapsed;
  const tm = ST.teams.find(x => x.is_me === t.is_me);
  const reserve = tm ? tm.reserve_ms / 1000 : 0;
  let secLeft, inReserve;
  if (remain > 0){
    clock.textContent = fmtClock(remain);
    clock.className = "clock";
    document.body.classList.remove("burning");
    burningIsMe = null;
    secLeft = remain; inReserve = false;
  } else {
    const rleft = Math.max(0, reserve + remain);
    clock.textContent = fmtClock(rleft);
    clock.className = "clock reserve";
    document.body.classList.toggle("burning", t.is_me && rleft > 0);
    burningIsMe = rleft > 0 ? t.is_me : null;
    secLeft = rleft; inReserve = true;
  }
  updateReserveDisplays();
  tickClock(secLeft, inReserve);
  const verb = t.type === "ban" ? "ban" : "pick";
  heading.textContent = (t.is_me ? "Your team's turn to " : "Enemy team's turn to ") + verb;
  heading.className = "turnheading" + (t.is_me ? "" : " enemyturn");
}

/* Countdown ticks: once per second in the main timer's last 5s, and once per
   second of reserve burn. The 10s/5s announcer marks pre-empt the countdown
   tick on that exact second (real client behaviour: the line, not the tick). */
function tickClock(secLeft, inReserve){
  const whole = Math.ceil(secLeft);
  if (whole === lastTickWhole) return;
  lastTickWhole = whole;
  if (!inReserve){
    if (whole === 10 && !turnFlags.a10){ playSound("announcer_10s"); turnFlags.a10 = true; return; }
    if (whole === 5 && !turnFlags.a5){ playSound("announcer_5s"); turnFlags.a5 = true; return; }
    if (whole > 0 && whole <= 5) playSound("countdown");
  } else if (whole > 0) {
    playSound("countdown");
  }
}

function partsLine(p){
  if (!p) return "";
  const bits = [];
  bits.push("comfort " + rtText(p.c));
  if (p.s) bits.push("scout " + rtText(p.s));
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
let lastHistoryLen = null;
let lastPhase = null;
let boardWasVisible = false;

async function poll(){
  try {
    const r = await fetch("/draft/state");
    ST = await r.json();
    ST._recvAt = Date.now();
  } catch (e) { return; }
  const drafting = ST.phase === "drafting" || ST.phase === "done";
  document.getElementById("setup").classList.toggle("on", !drafting);
  document.getElementById("board").classList.toggle("on", drafting);
  document.body.classList.toggle("drafting", drafting);
  if (!drafting){ document.body.classList.remove("burning"); boardWasVisible = false; }
  if (drafting && !boardWasVisible){
    // .board is display:none until this first poll, so buildGrid()'s initial
    // sizeHeroGrid() measured a zero-height box and bailed out — measure for
    // real now that the board has actually been painted.
    boardWasVisible = true;
    requestAnimationFrame(sizeHeroGrid);
  }
  if (ST.phase === "setup"){
    if (!mineSel.length && ST.my_roster.length) { mineSel = ST.my_roster.slice();
      renderChips(); renderLists(); }
    if (!enemySel.length && ST.enemy_roster.length) { enemySel = ST.enemy_roster.slice();
      renderChips(); renderLists(); }
    if (!mineKey && ST.mine_key){
      mineKey = ST.mine_key;
      document.getElementById("mineLeague").value = mineKey;
    }
    if (!enemyKey && ST.enemy_key){
      enemyKey = ST.enemy_key;
      document.getElementById("enemyLeague").value = enemyKey;
    }
    const en = document.getElementById("enemyName");
    if (!en.value && ST.enemy_name && ST.enemy_name !== "The Dire")
      en.value = ST.enemy_name;
  }
  // sound: a ban/pick lock on new history entries, music + phase transitions
  if (drafting){
    if (lastHistoryLen !== null && ST.history.length > lastHistoryLen){
      const last = ST.history[ST.history.length - 1];
      playSound(last.type === "ban" ? "ban" : "pick");
      if (last.type === "pick" && last.hid != null && ST.teams[last.team] &&
          ST.teams[last.team].is_me){
        playSound("pick_made");   // only for the user's own picks
      }
    }
    lastHistoryLen = ST.history.length;
  } else {
    lastHistoryLen = null;
  }
  if (ST.phase === "drafting" && lastPhase !== "drafting"){
    playSound("draft_start");
    startMusic();
  }
  if (ST.phase === "done" && lastPhase !== "done"){
    stopMusicFade();
    if (!anyRealSounds()) synthDraftComplete();  // client itself has no such line
  }
  if (ST.phase === "setup" && lastPhase && lastPhase !== "setup") stopMusicFade();
  lastPhase = ST.phase;
  if (drafting){
    if (ST.turn && !ST.turn.is_me) selectedHid = null;
    renderTeamCards(); renderMeter(); renderDraftPanel();
    renderTurn(); renderSuggs();
    syncGrid(); renderSummary();
  }
}
setInterval(() => { if (ST && ST.turn) renderTurn(); }, 250);  // smooth clock + tick sounds
setInterval(poll, 500);

buildGrid(); applyHintsUI(); fillLeagueSelects(); renderLists(); probeRealSounds(); poll();
</script>
</body>
</html>
"""


def render_page(pool, heroes, label, league_teams=None):
    heroes_json = json.dumps({str(k): v for k, v in heroes.items()}).replace(
        "</", "<\\/"
    )
    pool_json = json.dumps(pool).replace("</", "<\\/")
    league_json = json.dumps(league_teams or []).replace("</", "<\\/")
    return (PAGE
            .replace("__HEROES__", heroes_json)
            .replace("__POOL__", pool_json)
            .replace("__LEAGUE__", league_json)
            .replace("__LABEL__", html.escape(str(label or "LD2L"))))
