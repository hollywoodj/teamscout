"""Single-file interface for the mirrored team scouting workspace."""

import base64
import functools
import json
import os


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#151b23">
<script>var THEME_COLORS={sports:"#151b23",military:"#191c16",lotus:"#060a14"};(function(){var t="sports";try{var s=localStorage.getItem("team-scout:theme");if(THEME_COLORS[s])t=s;var l=localStorage.getItem("team-scout:theme-league");if(t==="lotus"&&l&&l!=="ld2l")t="sports"}catch(e){}document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');if(m)m.content=THEME_COLORS[t]})();</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@600;700;800&family=Hanken+Grotesk:wght@400;600;700&family=Saira:wght@400;600;700&family=Saira+Stencil+One&family=Orbitron:wght@600;700;800&family=Exo+2:wght@400;600;700&display=swap" rel="stylesheet">
<title>Team Scout</title>
<style>
:root{--bg:#070b10;--panel:#0d141d;--panel2:#111b26;--line:#263341;--ink:#edf3f7;--muted:#93a3b3;--mine:#45c7cf;--mine2:#13373d;--enemy:#f06468;--enemy2:#3a1d25;--gold:#dfb65d;--good:#70d49b;--bad:#f07979;--radius:12px;--shadow:0 18px 45px #0008}
*{box-sizing:border-box}html{background:var(--bg);color:var(--ink);font-family:"Segoe UI",Inter,system-ui,sans-serif}body{margin:0;min-height:100vh;background:radial-gradient(circle at 18% 0,#102932 0,transparent 34rem),radial-gradient(circle at 83% 0,#321820 0,transparent 34rem),var(--bg)}button,input,select{font:inherit;color:inherit}button,select,input{border:1px solid var(--line);background:#0b121a;border-radius:8px}button{cursor:pointer}.shell{max-width:1540px;margin:auto;padding:0 22px 48px}.top{min-height:74px;display:flex;align-items:center;gap:18px;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20;background:#070b10ee;backdrop-filter:blur(14px)}.brand{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;min-width:210px;padding:8px 0}.brand h1{font:650 18px/1;margin:0;letter-spacing:.06em}.who{display:block;margin-top:4px;color:var(--muted);font-size:11px;letter-spacing:.04em}.who a{color:var(--muted)}.nav{display:flex;gap:5px;flex:none;overflow:auto;padding:12px 0}.nav button{border-color:transparent;background:transparent;padding:9px 11px;color:var(--muted);white-space:nowrap;font-size:14px}.nav button.on{color:var(--ink);background:var(--panel2);border-color:var(--line)}.navEnemy{flex:1;margin-left:10px;padding-left:14px;border-left:1px solid var(--line)}.navSide{margin-left:auto;padding-left:14px;border-left:1px solid var(--line)}.window{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px}.window select{padding:8px 30px 8px 10px;min-width:150px}.rosterbar{display:grid;grid-template-columns:1fr 54px 1fr;gap:14px;align-items:stretch;margin-bottom:16px}.teamsetup{border:1px solid var(--line);background:#0b1118d9;border-radius:var(--radius);padding:13px 14px;box-shadow:var(--shadow)}.teamsetup.mine{border-top:2px solid var(--mine)}.teamsetup.enemy{border-top:2px solid var(--enemy)}.teamhead{display:flex;gap:9px;align-items:center;margin-bottom:10px;flex-wrap:wrap}.teamhead input{font-weight:650;font-size:16px;padding:7px 9px;flex:1 1 240px;min-width:160px;background:transparent}.teamhead .count{color:var(--muted);font-size:13px}.add{padding:7px 9px;max-width:230px;color:var(--muted)}.chips{display:flex;gap:7px;flex-wrap:wrap;min-height:31px}.chip{display:flex;align-items:center;gap:7px;background:#151f29;border:1px solid #2b3a48;border-radius:999px;padding:6px 8px 6px 11px;font-size:13px}.chip button{border:0;background:transparent;color:var(--muted);padding:0 2px;font-size:16px}.emptychip{color:var(--muted);font-size:13px;padding:7px 0}.vs{display:grid;place-items:center;color:#637384;font:700 13px Georgia;letter-spacing:.12em}.mirror{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:15px}.side{min-width:0}.sideTitle{display:flex;align-items:center;justify-content:space-between;margin:0 0 9px;padding:0 3px}.sideTitle h2{font:650 18px/1.2;margin:0}.side.mine .sideTitle h2{color:var(--mine)}.side.enemy .sideTitle h2{color:var(--enemy)}.sample{font-size:12px;color:var(--muted)}.card{background:linear-gradient(180deg,#111a24,#0c131b);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 12px 32px #0005}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;overflow:hidden;margin-bottom:10px}.metric{padding:15px 13px;background:#0e1720;min-height:83px}.metric span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.metric b{display:block;font:650 23px/1.1 Georgia,serif;margin-top:8px}.metric small{display:block;color:var(--muted);font-size:12px;margin-top:3px}.section{padding:16px}.section+.section{border-top:1px solid var(--line)}.section h3{font-size:13px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);margin:0 0 11px}.read{font:18px/1.45 Georgia,serif;margin:0}.read strong{color:var(--gold)}.bars{display:grid;gap:9px}.bars{grid-template-columns:minmax(110px,1fr) 2fr auto}.barrow{display:grid;grid-column:1/-1;grid-template-columns:subgrid;gap:10px;align-items:center;font-size:14px}.track{height:7px;border-radius:10px;background:#202b36;overflow:hidden}.fill{height:100%;background:var(--mine)}.enemy .fill{background:var(--enemy)}.value{font-variant-numeric:tabular-nums;color:var(--muted)}.playerList{display:grid;gap:8px}.player{display:grid;grid-template-columns:minmax(130px,1.4fr) repeat(4,minmax(54px,.65fr));gap:8px;align-items:center;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:#0d151e;text-align:left;width:100%}.player:hover,.player.on{border-color:#536779;background:#14202b}.player .who b{display:block;font-size:15px}.player .who small{color:var(--muted)}.stat{text-align:right}.stat b{display:block;font-size:14px}.stat small{color:var(--muted);font-size:11px;text-transform:uppercase}.official{color:var(--gold)}.good{color:var(--good)}.bad{color:var(--bad)}.detail{margin-top:10px}.detailHead{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.detailHead h3{font-size:20px;letter-spacing:0;text-transform:none;color:var(--ink);margin:0}.detailHead p{margin:5px 0 0;color:var(--muted);font-size:13px}.detailHead a{color:#a8d9e2;text-decoration:none}.detailHead a:hover{text-decoration:underline}.pill{display:inline-flex;padding:4px 7px;border-radius:999px;border:1px solid #5c4d2f;color:var(--gold);font-size:12px}.pillRow{display:flex;gap:7px;flex-wrap:wrap;align-items:flex-start}
.tbl th[data-hero-sort]{cursor:pointer}.tbl th[data-hero-sort].on{color:var(--ink)}.heroGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.hero{display:grid;grid-template-columns:1fr auto;gap:8px;padding:9px 10px;background:#0a1118;border:1px solid #202d39;border-radius:8px;font-size:13px}.hero span:last-child{color:var(--muted);font-variant-numeric:tabular-nums}.tableWrap{overflow:auto;border:1px solid var(--line);border-radius:10px}.tbl{border-collapse:collapse;width:100%;font-size:13px;min-width:590px}.tbl th{position:sticky;top:0;background:#131d27;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;text-align:right;padding:9px 10px;border-bottom:1px solid var(--line)}.tbl th:first-child,.tbl td:first-child,.tbl th.heroCol,.tbl td.heroCol{text-align:left}.tbl td{text-align:right;padding:9px 10px;border-bottom:1px solid #1b2732;font-variant-numeric:tabular-nums}.tbl td.matchupNote{text-align:left;color:var(--muted);font-size:12px;font-variant-numeric:normal}.matchupWho{display:block;color:var(--muted);font-size:11px;text-transform:none;letter-spacing:0;margin-top:2px}.matchupCap{margin:0 3px 10px;color:var(--muted);font-size:12px;line-height:1.4}.tbl.matchupTbl,.tbl.leagueTbl{min-width:0;font-size:12px}.tbl.matchupTbl th,.tbl.matchupTbl td{padding:8px 7px}.tbl tr:last-child td{border-bottom:0}.tbl a{color:#a8d9e2;text-decoration:none}.tbl a:hover{text-decoration:underline}.heroTable{display:grid;gap:7px}.heroRow{display:grid;grid-template-columns:minmax(120px,1fr) 50px 55px 2fr;gap:10px;align-items:center;padding:10px 11px;border:1px solid var(--line);border-radius:9px;background:#0d151e;font-size:13px}.heroRow b{font-size:14px}.coverage{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.patchRows{display:grid;gap:8px}.patchRow{display:grid;grid-template-columns:70px repeat(3,1fr);gap:10px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:9px;background:#0d151e}.patchRow b{font-family:Georgia,serif}.patchRow span{text-align:right}.patchRow small{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.selector{display:flex;gap:8px;margin-bottom:9px}.selector select{padding:8px 10px;max-width:100%}.notice{padding:28px;border:1px dashed #344454;border-radius:var(--radius);text-align:center;color:var(--muted);background:#0b1219}.foot{margin-top:18px;color:var(--muted);font-size:12px;text-align:center}.hidden{display:none!important}
@media(max-width:980px){.shell{padding:0 12px 35px}.top{flex-wrap:wrap;gap:4px;padding-top:8px}.brand{min-width:160px}.nav{order:3;padding:3px 0 9px}.navEnemy{flex:1;margin-left:6px;padding-left:10px}.navSide{margin-left:auto;border-left:0;padding-left:0}.window{margin-left:auto}.rosterbar{grid-template-columns:1fr}.vs{display:none}.mirror{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.teamhead{flex-wrap:wrap}.teamhead .count{order:2}.add{order:3;flex-basis:100%;max-width:none}.player{grid-template-columns:minmax(120px,1.5fr) repeat(2,minmax(52px,.7fr))}.player .stat:nth-last-child(-n+2){display:none}}
@media(max-width:540px){body{overflow-x:hidden}.shell{overflow:hidden}.brand{min-width:174px}.brand h1{font-size:17px}.window span{display:none}.metrics{grid-template-columns:1fr 1fr}.metric{min-height:75px}.heroGrid{grid-template-columns:1fr}.patchRow{grid-template-columns:60px repeat(3,1fr);font-size:12px}.teamhead input{max-width:58%}.nav{scrollbar-width:none}.nav::-webkit-scrollbar{display:none}.heroRow.best{grid-template-columns:minmax(115px,1fr) 48px 54px}.heroRow.best>:nth-child(4),.heroRow.best>:nth-child(5){display:none}.positionRow{grid-template-columns:88px 1fr 70px;font-size:12px}.analysisTitle{align-items:flex-start;flex-direction:column;gap:3px}}
select.preset{padding:7px 9px;flex:1 1 260px;min-width:180px;max-width:100%;color:var(--muted);border-color:#3a4d5d}.loadTeam{padding:7px 11px;border-color:#56717e;background:#162631;color:#dceaf0;font-weight:650}.loadTeam:disabled{cursor:not-allowed;opacity:.42}
.teamIdentity{display:flex;align-items:baseline;gap:10px;min-width:160px;margin-right:auto}.teamIdentity input{flex:0 1 240px;width:240px;max-width:100%;min-width:160px}.teamName{font-weight:650;font-size:24px;line-height:1.15}.teamRecord{font-weight:650;font-size:24px;line-height:1.15;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}.rosterLine{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.rosterLine>.chips{flex:1 1 220px;min-width:0}.rosterRight{display:flex;align-items:center;gap:12px;margin-left:auto;flex-wrap:wrap;justify-content:flex-end}.gearBtn{padding:6px 8px;line-height:0;flex:none}.gearBtn svg{display:block}
.teamRoster{margin:0 0 12px}.subnav{display:flex;gap:5px;margin:16px 0 10px}.subnav button{border-color:transparent;background:transparent;padding:8px 12px;color:var(--muted)}.subnav button.on{color:var(--ink);background:var(--panel2);border-color:var(--line)}.chip[data-focus]{cursor:pointer}.chip.on{border-color:#536779;background:#14202b}
.workspace{min-width:0}.singlePage{max-width:1180px;margin:0 auto}.singlePage>.teamsetup{margin:14px 0 8px;border:0;background:transparent;box-shadow:none;padding:0;border-radius:0}.singlePage>.teamsetup.mine,.singlePage>.teamsetup.enemy{border-top:0}.singlePage>.teamsetup .teamhead{margin-bottom:0}.pageHeading{display:flex;align-items:end;justify-content:space-between;gap:16px;margin:4px 2px 14px}.pageHeading .window{margin:0;flex:none}.pageHeading h2{font:650 24px/1.1 Georgia,serif;margin:0}.pageHeading p{margin:0;color:var(--muted);font-size:13px}.contentBlock{margin-top:16px}.contentBlock>h3{font-size:13px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);margin:0 0 9px 3px}.reconTop .metrics{grid-template-columns:repeat(4,minmax(0,1fr)) minmax(150px,1.25fr);margin-bottom:0}.metric.privateBlock.on{background:var(--enemy2)}.metric.privateBlock.on>span,.metric.privateBlock.on>b,.metric.privateBlock.on>small{color:var(--bad)}.metric.privateBlock.on>b{font-size:15px;line-height:1.25}.pageGrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}.breakdownPicker{display:flex;align-items:center;gap:10px;margin-bottom:12px}.breakdownPicker label{color:var(--muted);font-size:13px}.breakdownPicker select{min-width:280px;padding:9px 11px}
.detailMetrics{grid-template-columns:repeat(auto-fit,minmax(145px,1fr))}.analysisGrid{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(260px,.75fr);gap:14px}.compareTable{width:100%;border-collapse:collapse;font-size:13px}.compareTable th,.compareTable td{padding:8px 9px;border-bottom:1px solid #1e2b37;text-align:right;font-variant-numeric:tabular-nums}.compareTable th:first-child,.compareTable td:first-child{text-align:left}.compareTable th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}.deltaUp{color:var(--good)}.deltaDown{color:var(--bad)}.inference{display:grid;gap:8px}.insight{padding:10px 11px;border-left:2px solid var(--gold);background:#0a1118;color:#cbd5dc;font-size:13px;line-height:1.4}.caveat{color:var(--muted);font-size:12px;line-height:1.45;margin:9px 0 0}.positionBars{display:grid;gap:8px}.positionRow{display:grid;grid-template-columns:95px 1fr 78px;gap:9px;align-items:center;font-size:13px}.positionRow .track{height:8px}.posBadge{display:inline-flex;align-items:center;justify-content:center;min-width:30px;padding:3px 6px;border:1px solid #415466;border-radius:999px;color:#c8d7e1;font-size:11px;font-weight:700}.heroRow.best{grid-template-columns:minmax(135px,1.35fr) 64px 62px 72px minmax(130px,1.4fr)}.sub,.heroRow .sub{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:3px}.conf{color:var(--muted);font-size:11px}.analysisTitle{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.analysisTitle small{color:var(--muted);font-size:11px;text-transform:none;letter-spacing:0}.roleLine{display:flex;gap:7px;flex-wrap:wrap;align-items:center}.emptyAnalysis{color:var(--muted);font-size:13px;padding:5px 0}.keysList{display:grid;gap:10px;margin-top:8px}.keyItem{padding:13px 15px;border-left:3px solid var(--gold);background:#0a1118}.keyItem>b{display:block;font:650 17px/1.3 Georgia,serif;margin:0 0 6px}.keyItem p{margin:0;color:#b7c5d0;font-size:13px;line-height:1.45}
@media(max-width:980px){.pageGrid,.analysisGrid{grid-template-columns:1fr}.heroRow.best{grid-template-columns:minmax(125px,1.2fr) 55px 55px minmax(120px,1fr)}.heroRow.best>:nth-child(4){display:none}.reconTop .metrics{grid-template-columns:repeat(2,1fr)}}
@media(max-width:540px){.heroRow.best{grid-template-columns:minmax(115px,1fr) 48px 54px}.heroRow.best>:nth-child(4),.heroRow.best>:nth-child(5){display:none}.positionRow{grid-template-columns:88px 1fr 70px;font-size:12px}.analysisTitle{align-items:flex-start;flex-direction:column;gap:3px}}
.heroIcon{border-radius:4px;object-fit:cover;background:#0a1118;display:inline-block;vertical-align:middle}.heroFallback{display:inline-flex;align-items:center;justify-content:center;background:#1b2733;color:var(--muted);font:700 10px/1 Georgia,serif;border-radius:4px}.heroIconGray{filter:grayscale(1) brightness(.75)}
.rowMine{background:var(--mine2)}.rowMine td:first-child,.rowMine b{color:var(--mine)}.rowEnemy{background:var(--enemy2)}.rowEnemy td:first-child,.rowEnemy b{color:var(--enemy)}.rankGold{color:var(--gold);margin-right:4px}.standingsTbl{min-width:0}.standingsWho b{display:block}.standingsWho .sub{margin-top:2px}.standingsActions{display:flex;gap:6px;justify-content:flex-end;white-space:nowrap}.standingsActions button{padding:5px 8px;font-size:12px}.matchupSlate{display:grid;gap:8px;margin:0 0 16px}.slateRow{display:flex;align-items:center;justify-content:center;gap:12px;width:100%;padding:12px 14px;text-align:center;background:#0d151e}.slateRow:hover{border-color:#536779;background:#14202b}.slateVs{color:var(--muted);font:700 11px Georgia;letter-spacing:.12em}.slateRow .onSide{color:var(--gold)}
.pullbox{position:relative;margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.pullInput{flex:1;min-width:220px;padding:8px 10px}.pullbox button{padding:8px 12px}.pullDropdown{position:absolute;top:100%;left:0;right:0;margin-top:4px;background:#101923;border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);z-index:30;max-height:280px;overflow:auto}
.pullResult{display:flex;align-items:center;gap:9px;width:100%;padding:8px 10px;border:0;border-radius:0;background:transparent;text-align:left}.pullResult:hover{background:#182531}.pullAvatar{width:26px;height:26px;border-radius:50%;object-fit:cover;background:#1b2733;flex:none}.pullResultInfo small{color:var(--muted);display:block;font-size:11px}
.pullMsg{padding:9px 10px;color:var(--muted);font-size:13px}.pullErr{color:var(--bad)}.pullStatus{width:100%;font-size:12px;color:var(--muted)}.pullStatus.bad{color:var(--bad)}.hint{color:var(--muted);font-size:12px;margin-top:4px}
.standinCol{display:flex;flex-direction:column;align-items:flex-end;gap:6px;min-width:0}.replacementsRow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;margin:0;padding:0;border:0}.replacementsRow>b{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;white-space:nowrap}.replacementsRow .chips{flex:0 1 auto;min-height:0}.repActions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.repActions button{padding:6px 9px;font-size:12px}
.subChip,.subChipTag{border-color:#5c4d2f;cursor:pointer}.sub{color:var(--gold);text-transform:uppercase;font-size:9px;margin-left:3px}.chip.swapReady{cursor:pointer;border-color:var(--gold)}.chip.pending{border-color:var(--gold);color:var(--gold)}.chip.goneChip{text-decoration:line-through;opacity:.75;cursor:default;border-color:#3a4a58}.markGone{border:0;background:transparent;color:var(--muted);font-size:10px;padding:0 3px;text-transform:uppercase;letter-spacing:.04em}.markGone:hover{color:var(--ink)}td.goneHeroName,td.goneHeroName .matchupWho,.flexHero.gone b,.flexHero.gone small{text-decoration:line-through;color:var(--muted)}
.resultsHeader .resultsHeadTop{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px;flex-wrap:wrap}.resultsHeadTop h3{margin:0;font-size:20px}.heroChipRow{display:flex;flex-wrap:wrap;gap:8px}.heroChip{display:flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid var(--line);border-radius:9px;background:#0d151e;font-size:12px}.heroChip small{color:var(--muted)}
.roleRoster{display:grid;gap:12px;margin-top:14px}.rolePlayer{display:grid;grid-template-columns:42px minmax(0,1fr);gap:10px;align-items:start}.rolePlayer .posBadge{margin-top:3px}.rolePlayer b{display:block;font-size:15px}.roleMix{color:var(--muted);font-size:12px;margin-top:3px}.rolePlayer .positionBars{margin-top:7px}.flexHeroList{display:grid;gap:8px}.flexHero{display:flex;align-items:flex-start;gap:9px;padding:10px 11px;border:1px solid var(--line);border-radius:9px;background:#0d151e}.flexHero>div{min-width:0}.flexHero b{display:block;font-size:14px}.flexHero small{display:block;color:var(--muted);font-size:12px;margin-top:3px}
.seriesList{display:grid;gap:14px}.seriesCard{padding:14px}.seriesCard .tableWrap{margin-top:10px}.seriesHead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:10px}.seriesDate{color:var(--ink);font:650 22px/1.15 Georgia,serif}.seriesOpp small{color:var(--muted)}.seriesScore{font:700 16px/1 Georgia,serif;font-variant-numeric:tabular-nums}.seriesScore.good{color:var(--good)}.seriesScore.bad{color:var(--bad)}
.gameList{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-items:start}.gameList .gameRow:only-child{grid-column:1/-1}.gameRow{border:1px solid var(--line);border-radius:9px;padding:10px 11px;background:#0d151e;min-width:0}.gameMeta{display:flex;gap:10px;align-items:center;font-size:12px;color:var(--muted);margin-bottom:8px;flex-wrap:wrap}.gameMeta a{color:#a8d9e2}
.resultsFilter{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin:0 3px 12px}.resultsFilter>b{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-right:2px}.resultsFilter .chip{cursor:pointer}.resultsFilter .chip.on{border-color:var(--mine);background:#16323a;color:var(--ink);font-weight:650;box-shadow:0 0 0 1px var(--mine)}.resultsFilter.enemy .chip.on{border-color:var(--enemy);background:#3a1d25;box-shadow:0 0 0 1px var(--enemy)}.heroCell.on{background:#16323a;box-shadow:0 0 0 2px var(--mine);border-radius:6px}.seriesList.enemy .heroCell.on{box-shadow:0 0 0 2px var(--enemy);background:#3a1d25}.seriesList.filtering .sideBlock.mine .heroCell:not(.on){opacity:.32}.seriesList.filtering .sideBlock.enemy{opacity:.45}.gameRow.sitout{opacity:.42}
.gameSides{display:flex;gap:10px;align-items:flex-start;justify-content:center}.sideBlock{display:flex;gap:0;justify-content:flex-start;min-width:0;padding:8px 6px 7px}.gameSides .sideBlock:first-child{justify-content:flex-end}.sideBlock.mine{border:1.5px solid rgba(255,255,255,.35);border-radius:28px}.vsTiny{color:var(--muted);font-size:11px;padding-top:40px;flex:none}.heroCell{display:flex;flex-direction:column;align-items:center;gap:3px;flex:none;width:48px;font-size:11px;text-align:center}.heroPickN{font-size:9px;line-height:1;color:var(--muted);font-variant-numeric:tabular-nums;min-height:9px}.heroCell .heroIcon,.heroCell .heroFallback{display:block;border-radius:0}.heroCellName{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;font-size:9px;font-weight:600;width:48px;line-height:1.2;max-height:2.4em;overflow-wrap:normal;word-break:normal}
.draftLine{display:flex;align-items:flex-end;gap:0;flex-wrap:wrap;margin-top:9px;padding-top:8px;border-top:1px solid #182531;font-size:11px;color:var(--muted)}.gameList .draftLine{flex-wrap:nowrap;min-width:0}.gameList .draftLabel{flex:none}.gameList .draftAct{flex:1 1 0;min-width:0;max-width:28px}.gameList .draftAct .heroIcon,.gameList .draftAct .heroFallback{width:100%!important;height:auto!important;aspect-ratio:1}.draftLabel{color:var(--muted);margin-right:8px;padding-bottom:4px}.draftSep{color:#3a4a58;margin:0 4px}.draftAct{display:inline-flex;flex-direction:column;align-items:center;gap:2px;line-height:0}.draftAct:before{content:"";width:100%;height:2px;background:transparent;margin-top:1px;flex:none;order:1}.draftAct.ours:before{background:var(--mine)}.draftAct.theirs:before{background:var(--enemy)}.draftAct:after{content:"";width:5px;height:5px;border-radius:50%;background:transparent;margin-top:3px;flex:none;order:2;box-sizing:border-box}.draftAct.ours:after{background:#fff}.draftAct.ours.ban:after{background:transparent;border:1px solid #fff}.draftAct .heroIcon,.draftAct .heroFallback{display:block;border-radius:0}.draftN{font-size:9px;line-height:1;color:var(--muted);font-variant-numeric:tabular-nums}
.wardGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:12px}.wardCard{background:#0d151e;border:1px solid var(--line);border-radius:10px;padding:8px 8px 10px;text-align:center}.wardCard b{display:block;font-size:13px}.wardCard small{display:block;color:var(--muted);font-size:11px;margin:3px 0 7px}.wardMap{position:relative;overflow:hidden;border-radius:6px;background:#081018;margin:0 auto}.wardMap img{display:block;width:100%;height:100%;object-fit:cover;filter:saturate(.8) brightness(.92)}.wardDot{position:absolute;border-radius:50%;transform:translate(-50%,-50%);pointer-events:none}.wardDot.obs{width:11px;height:11px;background:var(--gold);box-shadow:0 0 8px #dfb65dcc;border:1px solid #1a1408}.wardDot.sen{width:8px;height:8px;background:var(--mine);box-shadow:0 0 7px #45c7cf99;border:1px solid #041416}.wardEmpty{position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:11px;background:#0005}.wardLegend{display:flex;gap:12px;justify-content:flex-end;align-items:center;color:var(--muted);font-size:11px;margin:0 3px 8px}.wardFreqHint{margin-right:auto}.wardLegend .wardToggle{margin-right:auto}.wardToggle{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;flex:none}.wardToggle button{border:0;border-radius:0;background:transparent;color:var(--muted);padding:2px 8px;font-size:11px;line-height:1.5}.wardToggle button.on{background:#16323a;color:var(--ink)}.wardHeatPair{display:flex;gap:6px;justify-content:center;position:relative}.wardKind{color:var(--muted);font-size:10px;text-align:center;margin-bottom:3px}.wardHeat{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.heatScale{display:inline-flex;align-items:center;gap:5px}.heatScale i{width:48px;height:8px;border-radius:99px;margin:0;background:linear-gradient(90deg,#00f,#0f0 45%,#ff0 72%,#f00)}.wardLegend i{display:inline-block;position:static;transform:none;margin-right:5px;vertical-align:middle}.wardSplit,.gameWards{display:flex;flex-direction:column;align-items:center;gap:14px;margin-top:10px}.wardSplit{margin-top:0}.wardSlot{min-width:0}.wardSlot.off{opacity:.32}.wardSlot.off:has(.wardHeatPair){display:none}.wardSplit .wardSideLabel,.gameWards .wardSideLabel{color:var(--muted);font-size:11px;margin-bottom:4px;text-align:center}.playerProfile .subnav{margin-top:4px}.steamLink{display:inline-flex;align-items:center;color:#a8d9e2;vertical-align:-3px}.steamLink:hover{color:var(--ink)}.steamIcon{display:block}.playerWardAll{margin:0 0 16px}.playerWardAll .wardCard{max-width:none;text-align:center}.playerGameWard a{display:inline-block;margin-top:6px;color:#a8d9e2;font-size:11px;text-decoration:none}.wardFold{margin-top:9px;padding-top:8px;border-top:1px solid #182531}.wardFold>summary{cursor:pointer;display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;color:var(--muted);list-style:none}.wardFold>summary::-webkit-details-marker,.wardFold>summary::marker{display:none;content:""}.wardFold>summary::before{content:"";width:0;height:0;border-left:5px solid currentColor;border-top:4px solid transparent;border-bottom:4px solid transparent;flex:none;opacity:.75}.wardFold[open]>summary::before{transform:rotate(90deg)}.wardFold[open]>summary{margin-bottom:4px}.wardFold>summary:focus-visible{outline:2px solid var(--mine);outline-offset:2px}.wardFold .gameWards{margin-top:8px}.seriesWards{margin-top:4px}.seriesWards .resultHeads,.seriesWards .resultKindMaps{display:grid;grid-template-columns:76px minmax(0,1fr) minmax(0,1fr);gap:8px 14px;align-items:start}.seriesWards .resultHeads{color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}.seriesWards .resultHeads span:nth-child(2){text-align:left}.seriesWards .resultHeads span:nth-child(3){text-align:right}.seriesWards .resultKind+.resultKind{margin-top:12px}.seriesWards .resultKindLabel{color:var(--muted);font-size:11px;padding-top:6px}.seriesWards .resultSide{display:flex;flex-wrap:wrap;gap:8px;min-width:0}.seriesWards .resultSide.radiant{justify-content:flex-start}.seriesWards .resultSide.dire{justify-content:flex-end;text-align:right}.seriesWards .resultMap{margin:0}.seriesWards .resultMap figcaption{color:var(--muted);font-size:11px;margin:0 0 4px}.tbl tr.wardRow td{text-align:left;padding:2px 10px 12px}.tbl tr.wardRow .wardFold{margin-top:0;padding-top:4px;border-top:0}.playerWardAll .wardFold,.playerGameWard .wardFold{margin-top:8px;padding-top:8px;text-align:left}
@media(max-width:980px){.gameList{grid-template-columns:1fr}}
@media(max-width:640px){.wardMap{width:min(var(--ward,240px),calc(50vw - 36px))!important;height:auto!important;aspect-ratio:1}}
@media(max-width:540px){.gameSides{flex-direction:column}.vsTiny{align-self:center;padding-top:0}.sideBlock{flex-wrap:nowrap;gap:0}.resultsHeadTop{flex-direction:column;align-items:flex-start}}
.extLink{color:var(--mine);font-size:13px;text-decoration:none}.extLink:hover{text-decoration:underline}.gemList{display:grid;gap:8px}.gemRow{display:grid;grid-template-columns:minmax(150px,230px) 52px minmax(0,1fr);gap:12px;align-items:center;padding:9px 11px;background:#0a1118;border:1px solid #202d39;border-radius:8px}.gemRow b{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.gemScore{color:var(--good);font-weight:650}.gemReason{color:var(--muted);font-size:13px;line-height:1.45}
@media(max-width:640px){.gemRow{grid-template-columns:minmax(0,1fr) auto}.gemReason{grid-column:1/-1}}
.leagueSwitch{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;flex:none}
.leagueSwitch button{border:0;border-radius:0;background:transparent;color:var(--muted);padding:7px 14px;font-size:12px;letter-spacing:.08em}
.leagueSwitch button.on{background:#143044;color:var(--ink)}
/* Theme layer: Sports and Military. Overrides the base rules above; the header toggle sets html[data-theme]. */

/* Sports (default): broadcast scorebug, blue vs red */
:root,:root[data-theme="sports"]{
  --bg:#151b23;--topbg:#151b23f2;--panel:#1c2430;--panel2:#232d3b;--line:#2e3a4a;--hair:#263140;
  --ink:#e8edf2;--muted:#95a2b2;
  --mine:#6fa8dc;--mine2:#1e3144;--enemy:#e0524f;--enemy2:#3b1c1f;
  --gold:#d9b566;--good:#a3d386;--bad:#e8a15c;
  --river:#9cc3d6;
  --display:"Big Shoulders Display","Bahnschrift","Arial Narrow",sans-serif;--displayW:800;
  --text:"Hanken Grotesk","Segoe UI",sans-serif;
  --radius:6px;--shadow:none;
}
/* Military: ops briefing on a map grid. Friendly blue, hostile red, as on tactical symbols. */
:root[data-theme="military"]{
  --bg:#191c16;--topbg:#191c16f2;--panel:#21251d;--panel2:#2a2f25;--line:#3a4132;--hair:#2e3428;
  --ink:#e6e3d1;--muted:#a2a38c;
  --mine:#7fb6d6;--mine2:#1d2b30;--enemy:#d4524a;--enemy2:#35201b;
  --gold:#c9a74e;--good:#b5cf7a;--bad:#e0a04f;
  --river:#c9a74e;
  --display:"Saira Stencil One","Bahnschrift","Arial Narrow",sans-serif;--displayW:400;
  --text:"Saira","Segoe UI",sans-serif;
  --radius:0px;
}
/* Lotus: fleet command over a starfield. Allied blue, enemy red, crawl-yellow accents. */
:root[data-theme="lotus"]{
  --bg:#060a14;--topbg:#060a14d9;--panel:#0a1222e6;--panel2:#13213a;--line:#233a5c;--hair:#1a2b45;
  --ink:#e8f0ff;--muted:#8ea3c7;
  --mine:#5cc8ff;--mine2:#0e2a45;--enemy:#ff4d5e;--enemy2:#3b1222;
  --gold:#ffe81f;--good:#7fe3b4;--bad:#ffab5c;
  --river:#9fd8ff;
  --display:"Orbitron","Bahnschrift","Arial Narrow",sans-serif;--displayW:700;
  --text:"Exo 2","Segoe UI",sans-serif;
  --radius:3px;
}
html{background:var(--bg);font-family:var(--text);font-size:15px;font-variant-numeric:tabular-nums}
body{background:var(--bg)}
button,select,input{background:var(--panel);border-color:var(--line);border-radius:4px}
:focus-visible{outline:2px solid var(--river);outline-offset:2px}

/* Header */
.top{background:var(--topbg);border-bottom:1px solid var(--line);min-height:64px;gap:22px}
.brand h1{font:var(--displayW) 26px/1 var(--display);letter-spacing:.01em;text-transform:none}
.leagueSwitch{border-radius:4px}
.leagueSwitch button{font:700 14px/1 var(--text);letter-spacing:.02em;padding:8px 12px}
.leagueSwitch button.on{background:var(--panel2)}
.nav button{border:0;border-radius:0;background:transparent;font:600 15px/1 var(--text);padding:10px 4px;margin:0 7px;border-bottom:2px solid transparent}
.nav button.on{background:transparent;border-bottom-color:var(--ink)}
.navMine button.on{color:var(--mine);border-bottom-color:var(--mine)}
.navEnemy button.on{color:var(--enemy);border-bottom-color:var(--enemy)}
.navEnemy,.navSide{border-left-color:var(--line)}
.themeSwitch{display:flex;border:1px solid var(--line);border-radius:4px;overflow:hidden;flex:none}
.themeSwitch button{border:0;border-radius:0;background:transparent;color:var(--muted);padding:7px 11px;font:600 13px/1 var(--text)}
.themeSwitch button[aria-pressed="true"]{background:var(--panel2);color:var(--ink)}
.settings{position:relative;flex:none}
.settingsBtn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:4px;background:transparent;color:var(--muted);padding:7px 11px;font:600 13px/1 var(--text);cursor:pointer}
.settingsBtn:hover,.settingsBtn[aria-expanded="true"]{background:var(--panel2);color:var(--ink)}
.settingsPanel{position:absolute;right:0;top:calc(100% + 8px);z-index:30;display:grid;gap:14px;width:max-content;min-width:230px;max-width:calc(100vw - 24px);padding:14px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 12px 30px #0008}
.settingsPanel[hidden],.settingsRow[hidden]{display:none}
.settingsRow{display:grid;gap:7px;justify-items:start}
.settingsRow>b{font:600 12px/1.2 var(--text);color:var(--muted)}

/* Scorebug: the one loud element */
.scorebug{position:relative;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin:22px 0 18px;
  border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;
  background:linear-gradient(104deg,var(--mine2) 0 calc(50% - 1px),var(--river) calc(50% - 1px) calc(50% + 1px),var(--enemy2) calc(50% + 1px) 100%)}
.scorebug::before{content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(104deg,transparent 0 calc(50% - 7px),color-mix(in srgb,var(--river) 14%,transparent) calc(50% - 7px) calc(50% + 7px),transparent calc(50% + 7px))}
.sbSide{display:flex;align-items:baseline;gap:18px;padding:22px 28px;min-width:0}
.sbSide.enemy{flex-direction:row-reverse;text-align:right}
.sbName{font:var(--displayW) 44px/1 var(--display);letter-spacing:.005em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.sbSide.mine .sbName{color:var(--mine)}.sbSide.enemy .sbName{color:var(--enemy)}
.sbRec{font:var(--displayW) 44px/1 var(--display);color:var(--ink);white-space:nowrap}
.sbMeta{display:block;font:400 13px/1.3 var(--text);color:var(--muted);margin-top:6px}
.sbMid{width:48px}
.scorebug~.mirror .sideTitle{display:none}

/* Section rhythm */
.sideTitle h2{font:var(--displayW) 30px/1.1 var(--display)}
.side.mine .sideTitle h2{color:var(--mine)}.side.enemy .sideTitle h2{color:var(--enemy)}
.sample{font-size:13px}
.contentBlock{margin-top:40px}
.contentBlock>h3{font:var(--displayW) 30px/1.1 var(--display);text-transform:none;letter-spacing:0;color:var(--ink);margin:0 0 14px 0}
.section h3,.analysisTitle h3{font:var(--displayW) 21px/1.15 var(--display);text-transform:none;letter-spacing:.005em;color:var(--ink);margin:0 0 12px}
.read{font:var(--displayW) 24px/1.2 var(--display);letter-spacing:.005em}
.matchupCap{max-width:78ch;font-size:13px;line-height:1.5;margin:0 0 14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:none}
.section{padding:18px 20px}
.section+.section{border-top-color:var(--hair)}
.side.mine .card{border-top:2px solid var(--mine)}.side.enemy .card{border-top:2px solid var(--enemy)}

/* Tables */
.tableWrap{border:0;border-radius:0}
.tbl,.compareTable{font-size:14px}
.tbl th,.compareTable th{background:transparent;text-transform:none;letter-spacing:0;font:600 12px/1.2 var(--text);color:var(--muted);border-bottom:1px solid var(--line)}
.tbl td,.compareTable td{border-bottom-color:var(--hair)}
.tbl td small,.matchupWho{color:var(--muted)}
.deltaUp{color:var(--good)}.deltaDown{color:var(--bad)}

/* Bars */
.barrow{font-size:14px}
.track,.positionRow .track{height:4px;border-radius:0;background:var(--hair)}
.fill{background:var(--mine)}.enemy .fill{background:var(--enemy)}
.positionRow{grid-template-columns:120px 1fr 78px}

/* Hero list: rows on a rule, not cards in a card */
.heroTable{gap:0}
.heroRow,.heroRow.best{border:0;border-bottom:1px solid var(--hair);border-radius:0;background:transparent;padding:10px 2px}
.heroRow:last-child{border-bottom:0}
.heroRow b{font:var(--displayW) 18px/1.1 var(--display);letter-spacing:.005em}
.heroRow .sub,.sub{color:var(--muted);text-transform:none;font:400 12px/1.3 var(--text)}
.posBadge{border-radius:3px;border-color:var(--line);background:var(--panel2);color:var(--ink);font:700 12px/1 var(--text);letter-spacing:0}

/* Keys, roles, misc */
.keyItem,.insight{background:transparent;border-left-color:var(--gold);padding:4px 0 4px 16px}
.keyItem>b{font:var(--displayW) 21px/1.2 var(--display)}
.emptyAnalysis{font-size:14px}
.rolePlayer b{font:var(--displayW) 19px/1.1 var(--display)}
.flexHero,.gameRow,.heroChip{background:var(--panel);border-color:var(--line);border-radius:var(--radius)}
.chip{background:var(--panel);border-color:var(--line);border-radius:4px}
.subnav button{border:0;border-radius:0;border-bottom:2px solid transparent;background:transparent;font-weight:600}
.subnav button.on{background:transparent;border-bottom-color:var(--ink)}
.notice{border-radius:var(--radius);background:var(--panel);border-color:var(--line)}
.slateRow{background:var(--panel);border-radius:var(--radius)}
.slateVs{font:600 13px var(--text);letter-spacing:.04em;color:var(--river)}
.teamName,.teamRecord,.pageHeading h2{font-family:var(--display);font-weight:var(--displayW);font-size:34px}
.metric b,.seriesDate,.seriesScore,.heroFallback,.vs,.patchRow b{font-family:var(--display)}

/* Military specifics */
:root[data-theme="military"] body{background:
  linear-gradient(var(--hair) 1px,transparent 1px) 0 0/96px 96px,
  linear-gradient(90deg,var(--hair) 1px,transparent 1px) 0 0/96px 96px,var(--bg)}
:root[data-theme="military"] .scorebug{background:linear-gradient(90deg,var(--mine2) 0 50%,var(--enemy2) 50% 100%)}
:root[data-theme="military"] .scorebug::before{background:repeating-linear-gradient(180deg,var(--river) 0 10px,transparent 10px 18px) center/2px 100% no-repeat}
:root[data-theme="military"] .sbName,:root[data-theme="military"] .contentBlock>h3,:root[data-theme="military"] .section h3,:root[data-theme="military"] .analysisTitle h3,:root[data-theme="military"] .read{letter-spacing:.02em}
:root[data-theme="military"] .heroRow b,:root[data-theme="military"] .rolePlayer b,:root[data-theme="military"] .keyItem>b{font-family:var(--text);font-weight:700;font-size:16px}
:root[data-theme="military"] .posBadge,:root[data-theme="military"] .chip,:root[data-theme="military"] .themeSwitch,:root[data-theme="military"] .leagueSwitch,:root[data-theme="military"] .settingsBtn,:root[data-theme="military"] .settingsPanel{border-radius:0}
:root[data-theme="military"] .track{background:repeating-linear-gradient(90deg,var(--line) 0 3px,transparent 3px 5px)}

/* Lotus specifics: starfield behind everything, Orbitron is wide so display sizes step down */
:root[data-theme="lotus"] body{background:transparent}
:root[data-theme="lotus"] body::before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:linear-gradient(180deg,#060a1410 0,#060a1440 70%,#060a1499 100%),url("__LOTUS_BG__") center/cover no-repeat,var(--bg)}
/* Spinnable Lotus heads: a fixed layer sized and cropped exactly like the cover background, so marks
   placed in its percentages stay lined up with the baked-in rifles. Double-click spins one (see JS). */
.lotusField{display:none}
:root[data-theme="lotus"] .lotusField{display:block;position:fixed;left:50%;top:50%;width:max(100vw,133.334vh);height:max(75vw,100vh);transform:translate(-50%,-50%);z-index:-1;pointer-events:none}
.lotusMark{position:absolute;aspect-ratio:356/334;background:url("__LOTUS_MARK__") center/contain no-repeat;transform:translate(-50%,-50%) rotate(calc(var(--r) + var(--spin,0deg)));transition:transform 1.4s cubic-bezier(.45,0,.2,1)}
:root[data-theme="lotus"] .top{backdrop-filter:blur(10px);border-bottom-color:color-mix(in srgb,var(--mine) 35%,var(--line));box-shadow:0 1px 0 #5cc8ff14,0 8px 30px #0008}
:root[data-theme="lotus"] .brand h1{font-size:19px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold);text-shadow:0 0 14px #ffe81f40}
:root[data-theme="lotus"] .nav button,:root[data-theme="lotus"] .themeSwitch button,:root[data-theme="lotus"] .leagueSwitch button,:root[data-theme="lotus"] .settingsBtn{letter-spacing:.06em;text-transform:uppercase;font-size:13px}
:root[data-theme="lotus"] .navMine button.on{text-shadow:0 0 10px #5cc8ff80;box-shadow:0 6px 12px -8px var(--mine)}
:root[data-theme="lotus"] .navEnemy button.on{text-shadow:0 0 10px #ff4d5e80;box-shadow:0 6px 12px -8px var(--enemy)}
:root[data-theme="lotus"] .scorebug{background:linear-gradient(90deg,#0e2a45e6 0 50%,#3b1222e6 50% 100%);border-color:var(--line);box-shadow:0 0 0 1px #0006,0 12px 40px #000a}
:root[data-theme="lotus"] .scorebug::before{background:linear-gradient(90deg,transparent calc(50% - 1px),var(--river) calc(50% - 1px) calc(50% + 1px),transparent calc(50% + 1px));filter:drop-shadow(0 0 6px var(--river))}
:root[data-theme="lotus"] .sbName,:root[data-theme="lotus"] .sbRec{font-size:26px;letter-spacing:.03em;text-transform:uppercase}
:root[data-theme="lotus"] .sbSide.mine .sbName{text-shadow:0 0 18px #5cc8ff66}
:root[data-theme="lotus"] .sbSide.enemy .sbName{text-shadow:0 0 18px #ff4d5e66}
:root[data-theme="lotus"] .sbMeta{letter-spacing:.04em}
:root[data-theme="lotus"] .contentBlock>h3,:root[data-theme="lotus"] .sideTitle h2{font-size:21px;letter-spacing:.1em;text-transform:uppercase}
:root[data-theme="lotus"] .section h3,:root[data-theme="lotus"] .analysisTitle h3{font-size:14px;letter-spacing:.12em;text-transform:uppercase;color:var(--river)}
:root[data-theme="lotus"] .read{font:600 20px/1.35 var(--text);letter-spacing:0}
:root[data-theme="lotus"] .teamName,:root[data-theme="lotus"] .teamRecord,:root[data-theme="lotus"] .pageHeading h2{font-size:25px;letter-spacing:.05em;text-transform:uppercase}
:root[data-theme="lotus"] .metric b{font-size:20px;letter-spacing:.02em}
:root[data-theme="lotus"] .heroRow b,:root[data-theme="lotus"] .rolePlayer b,:root[data-theme="lotus"] .keyItem>b{font-family:var(--text);font-weight:700;font-size:16px}
:root[data-theme="lotus"] .seriesDate{font-size:18px;letter-spacing:.04em}
:root[data-theme="lotus"] .card{box-shadow:0 10px 30px #0007}
:root[data-theme="lotus"] .side.mine .card{box-shadow:0 -1px 12px -4px var(--mine),0 10px 30px #0007}
:root[data-theme="lotus"] .side.enemy .card{box-shadow:0 -1px 12px -4px var(--enemy),0 10px 30px #0007}
:root[data-theme="lotus"] .fill{background:linear-gradient(90deg,color-mix(in srgb,var(--mine) 45%,transparent),var(--mine));box-shadow:0 0 8px #5cc8ff66}
:root[data-theme="lotus"] .enemy .fill,:root[data-theme="lotus"] .enemyView .fill{background:linear-gradient(90deg,color-mix(in srgb,var(--enemy) 45%,transparent),var(--enemy));box-shadow:0 0 8px #ff4d5e66}
:root[data-theme="lotus"] .track{overflow:visible;border-radius:2px}
:root[data-theme="lotus"] .keyItem,:root[data-theme="lotus"] .insight{border-left-color:var(--gold);box-shadow:-6px 0 12px -10px var(--gold)}
:root[data-theme="lotus"] .tableWrap{background:var(--panel)}
:root[data-theme="lotus"] .posBadge{font-family:var(--display);font-size:11px;letter-spacing:.04em}
@media(max-width:540px){
  .themeSwitch button{padding:7px 8px}
  :root[data-theme="lotus"] .brand h1{font-size:16px;white-space:nowrap}
  :root[data-theme="lotus"] .nav button,:root[data-theme="lotus"] .themeSwitch button,:root[data-theme="lotus"] .leagueSwitch button,:root[data-theme="lotus"] .settingsBtn{font-size:11px;letter-spacing:.02em}
  :root[data-theme="lotus"] .nav button{margin-right:9px}
}

@media(max-width:980px){
  .scorebug,:root[data-theme="military"] .scorebug{grid-template-columns:1fr;background:var(--panel)}
  .scorebug::before{display:none}
  .sbSide.mine{border-bottom:2px solid var(--river);background:var(--mine2)}
  :root[data-theme="military"] .sbSide.mine{border-bottom-style:dashed}
  :root[data-theme="lotus"] .scorebug{background:var(--panel)}
  :root[data-theme="lotus"] .sbName,:root[data-theme="lotus"] .sbRec{font-size:19px}
  .sbSide.enemy{flex-direction:row;text-align:left;background:var(--enemy2)}
  .sbMid{display:none}
  .sbName,.sbRec{font-size:32px}
  .sbSide{padding:16px}
}
@media(max-width:540px){.positionRow{grid-template-columns:104px 1fr 64px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
/* The Lotus spin only runs when someone double-clicks for it, so it survives reduced motion. */
@media (prefers-reduced-motion:reduce){.lotusMark{transition:transform 1.4s cubic-bezier(.45,0,.2,1)!important}}

/* Teams table: the actions cell must stay a table cell so row rules and highlights span the full row */
.standingsActions{display:table-cell;text-align:right;white-space:nowrap}
.standingsActions button+button{margin-left:6px}

/* Deltas that move the unhelpful way in wins carry a word, not just a color */
.deltaTag{display:inline-block;margin-right:6px;padding:1px 5px;border:1px solid currentColor;border-radius:3px;font:600 10px/1.3 var(--text);letter-spacing:.02em;vertical-align:1px}
:root[data-theme="military"] .deltaTag{border-radius:0}

/* Phone header: brand and settings on top, your/opponent tabs together, then league tabs */
@media(max-width:980px){
  .top{display:grid;grid-template-columns:auto minmax(0,1fr) auto;grid-template-areas:"brand brand settings" "mine enemy enemy" "side side side";align-items:center;gap:0 10px;padding-top:10px}
  .brand{grid-area:brand;min-width:0}
  .settings{grid-area:settings}
  .navMine{grid-area:mine}
  .navEnemy{grid-area:enemy;margin-left:0;padding-left:10px;border-left:1px solid var(--line)}
  .navSide{grid-area:side;margin-left:0;padding-left:0;border-left:0}
  .nav{overflow:visible;padding:4px 0;min-width:0}
  .nav button{margin:0 12px 0 0;padding:10px 0}
}
:root[data-theme="military"] .tableWrap{background:var(--panel)}

/* Base surfaces and labels mapped onto theme tokens */
.metrics{background:var(--line)}.metric{background:var(--panel)}
.metric span,.stat small,.patchRow small,.replacementsRow>b,.resultsFilter>b,.seriesWards .resultHeads,.markGone{text-transform:none;letter-spacing:0}
.metric span{font:600 12px/1.2 var(--text)}
.player,.patchRow,.wardCard,.hero,.gemRow,.teamsetup{background:var(--panel);border-color:var(--line)}
.player:hover,.player.on,.chip.on,.slateRow:hover,.pullResult:hover{background:var(--panel2);border-color:var(--muted)}
.pullDropdown{background:var(--panel);border-color:var(--line)}
.heroFallback,.pullAvatar{background:var(--panel2)}
.draftLine,.wardFold{border-top-color:var(--hair)}
.insight{color:var(--ink)}.keyItem p{color:var(--muted)}
.wardToggle button.on{background:var(--panel2)}
.resultsFilter .chip.on,.heroCell.on{background:var(--mine2)}
.resultsFilter.enemy .chip.on,.seriesList.enemy .heroCell.on{background:var(--enemy2)}
.tbl a,.gameMeta a,.detailHead a,.steamLink,.playerGameWard a,.who a{color:var(--river)}
.enemyView .fill{background:var(--enemy)}

.method{margin:0 0 14px}
.method>summary{cursor:pointer;display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;list-style:none}
.method>summary::-webkit-details-marker,.method>summary::marker{display:none;content:""}
.method>summary::before{content:"";border-left:5px solid currentColor;border-top:4px solid transparent;border-bottom:4px solid transparent}
.method[open]>summary::before{transform:rotate(90deg)}
.method>summary:hover{color:var(--ink)}
.method[open]>summary{margin-bottom:8px}
.method .matchupCap{margin:0}
.sbContext{grid-column:1/-1;position:relative;z-index:1;display:flex;justify-content:center;gap:16px;padding:9px 16px;background:var(--panel);border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
.sbContext b{color:var(--ink);font-weight:600}
</style>
</head>
<body>
<main class="shell">
  <header class="top">
    <div class="brand"><h1>Team Scout</h1><span class="who" id="signedIn"></span></div>
    <nav class="nav navMine" aria-label="Your team">
      <button data-view="team" class="on">Your Team</button>
    </nav>
    <nav class="nav navEnemy" aria-label="Opponent">
      <button data-view="opponent">Opponent</button>
      <button data-view="recon">Recon</button>
      <button data-view="matchup">Matchup</button>
    </nav>
    <nav class="nav navSide" aria-label="League">
      <button data-view="admin">Admin</button>
      <button data-view="standings">Teams</button>
      <button data-view="league">League Stats</button>
    </nav>
    <div class="settings">
      <button type="button" class="settingsBtn" aria-expanded="false" aria-controls="settingsPanel"><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.03 7.03 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.9 2h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.59.24-1.13.56-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.48a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.39.3.6.22l2.39-.96c.5.38 1.04.7 1.63.94l.36 2.54c.05.24.25.42.49.42h3.8c.24 0 .45-.18.49-.42l.36-2.54c.59-.24 1.13-.56 1.63-.94l2.39.96c.22.08.47 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.6a3.6 3.6 0 1 1 0-7.2 3.6 3.6 0 0 1 0 7.2z"/></svg>Settings</button>
      <div class="settingsPanel" id="settingsPanel" hidden>
        <div class="settingsRow" id="leagueRow" hidden><b>League</b><div class="leagueSwitch" id="leagueSwitch" role="group" aria-label="League"></div></div>
        <div class="settingsRow"><b>Theme</b><div class="themeSwitch" role="group" aria-label="Theme"><button type="button" data-theme="sports">Sports</button><button type="button" data-theme="military">Military</button><button type="button" data-theme="lotus">Lotus</button></div></div>
      </div>
    </div>
  </header>
  <section class="workspace" id="workspace"></section>
</main>
<div class="lotusField" aria-hidden="true">__LOTUS_MARKS__</div>
<script>
const DATA=__DATA__;
const ACCOUNT=DATA.account||{locked:false,user:""};
const SOURCE={teams:[...(DATA.teams||[])],standings:[...(DATA.standings||[])],matchups:[...(DATA.matchups||[])],teamMatches:[...(DATA.teamMatches||[])],players:[...(DATA.players||[])]};
function leagueId(name){const s=String(name||"").toUpperCase();if(s.includes("RD2L"))return "rd2l";if(s.includes("LD2L"))return "ld2l";return ""}
function leagueLabel(id){return id==="rd2l"?"RD2L":id==="ld2l"?"LD2L":(id||"League")}
function teamLeagueId(team){return leagueId((team&&team.league)||(DATA.officialSource&&DATA.officialSource.league)||"")}
const leagueIds=[...new Set(SOURCE.teams.map(teamLeagueId))].filter(Boolean).sort((a,b)=>Number(a!=="ld2l")-Number(b!=="ld2l")||a.localeCompare(b));
const primaryLeague=leagueId(DATA.officialSource&&DATA.officialSource.league)||leagueIds[0]||"";
const BASE_KEY=ACCOUNT.user?`team-scout:${DATA.seasonId}:${ACCOUNT.user}`:`team-scout:${DATA.seasonId}`;
const LEAGUE_PREF=`${BASE_KEY}:league`;
let activeLeague=leagueIds.length>1?(localStorage.getItem(LEAGUE_PREF)||primaryLeague||leagueIds[0]):(leagueIds[0]||"");
if(leagueIds.length&&!leagueIds.includes(activeLeague))activeLeague=leagueIds[0];
function storageKey(league){const which=league||activeLeague;return leagueIds.length>1?`${BASE_KEY}:${which}`:BASE_KEY}
function rosterIdSet(teams){const ids=new Set();for(const t of teams||[]){for(const id of [...(t.roster||[]),...(t.postedRoster||[]),...(t.replaced||[])])ids.add(Number(id));for(const r of [...(t.replacements||[]),...(t.replacedPlayers||[])])if(r&&r.id!=null)ids.add(Number(r.id))}return ids}
const idsByLeague={};for(const id of leagueIds)idsByLeague[id]=rosterIdSet(SOURCE.teams.filter(t=>teamLeagueId(t)===id));
function playerInLeague(p,league){if((idsByLeague[league]||new Set()).has(p.id))return true;return !leagueIds.some(id=>(idsByLeague[id]||new Set()).has(p.id))&&league===primaryLeague}
function keptIds(league,ids){
  const mine=idsByLeague[league]||new Set();
  const foreign=new Set();
  for(const id of leagueIds){if(id===league)continue;for(const pid of idsByLeague[id]||[])if(!mine.has(pid))foreign.add(pid)}
  return new Set([...ids].map(Number).filter(id=>!foreign.has(id)));
}
function applyLeague(league,extraIds){
  const teams=SOURCE.teams.filter(t=>teamLeagueId(t)===league);
  const keys=new Set(teams.map(t=>t.key));
  DATA.teams=teams;
  DATA.standings=SOURCE.standings.filter(r=>leagueId(r.league)===league||keys.has(r.key));
  DATA.matchups=SOURCE.matchups.filter(m=>keys.has(m.aKey)&&keys.has(m.bKey));
  DATA.teamMatches=(SOURCE.teamMatches||[]).filter(m=>m&&m.radiant&&m.dire&&keys.has(m.radiant.team_key)&&keys.has(m.dire.team_key));
  const extra=extraIds||new Set();
  DATA.players=SOURCE.players.filter(p=>playerInLeague(p,league)||extra.has(p.id)).map(p=>{
    const official=p.official;
    if(!official||!official.matches)return p;
    const matches=official.matches.filter(row=>!row.team_key||keys.has(row.team_key));
    if(matches.length===official.matches.length)return p;
    const wins=matches.filter(row=>row.result==="W").length;
    return {...p,official:{...official,matches,games:matches.length,wins,winrate:matches.length?Math.round(wins/matches.length*1000)/10:null}};
  });
  byId.clear();
  for(const p of DATA.players)byId.set(p.id,p);
}
function readSaved(league){
  let raw=null;
  try{raw=localStorage.getItem(storageKey(league))}catch(e){raw=null}
  if(raw==null&&leagueIds.length>1&&league===primaryLeague){try{raw=localStorage.getItem(BASE_KEY)}catch(e){raw=null}}
  let saved={};
  try{saved=raw?JSON.parse(raw)||{}:{}}catch(e){saved={}}
  const keys=new Set(SOURCE.teams.filter(t=>teamLeagueId(t)===league).map(t=>t.key));
  if(saved.mineTeamKey&&!keys.has(saved.mineTeamKey)){saved={...saved,mine:[],mineName:"My Team",mineTeamKey:null,focusMine:null}}
  if(saved.enemyTeamKey&&!keys.has(saved.enemyTeamKey)){saved={...saved,enemy:[],enemyName:"Opponent",enemyTeamKey:null,focusEnemy:null}}
  return saved;
}
const byId=new Map();
const _bootSaved=readSaved(activeLeague);
if(activeLeague)applyLeague(activeLeague,keptIds(activeLeague,[...(_bootSaved.mine||[]),...(_bootSaved.enemy||[])]));
else for(const p of SOURCE.players)byId.set(p.id,p);
const latestPatch=DATA.patches.length?DATA.patches[DATA.patches.length-1]:null;
const saved=_bootSaved;
const allowedViews=["team","opponent","recon","matchup","standings","league"];
if(ACCOUNT.admin)allowedViews.push("admin");else{const adminBtn=document.querySelector("[data-view=admin]");if(adminBtn)adminBtn.remove()}
const boot=(()=>{const subPane=v=>v==="draft"||v==="results"||v==="roles"?v:"players";let view=saved.view,sub={mine:subPane(saved.sub&&saved.sub.mine),enemy:subPane(saved.sub&&saved.sub.enemy)};if(view==="results"){const onEnemy=!!(saved.resultsTeam&&saved.resultsTeam===saved.enemyTeamKey);view=onEnemy?"opponent":"team";sub[onEnemy?"enemy":"mine"]="results"}else if(view==="player"){const id=saved.focusPlayer||saved.focusEnemy||saved.focusMine;view=(saved.enemy||[]).includes(id)?"opponent":"team"}if(!view)view="team";else if(!allowedViews.includes(view))view="team";return {view,sub}})();
const playerPane=v=>v==="wards"||v==="pubs"||v==="officials"||v==="standins"||v==="heroes"||v==="esports"?v:"overview";
const state={view:boot.view,window:saved.window||"current",mine:(saved.mine||[]).filter(id=>byId.has(id)).slice(0,5),enemy:(saved.enemy||[]).filter(id=>byId.has(id)).slice(0,5),mineName:saved.mineName||"My Team",enemyName:saved.enemyName||"Opponent",minePreset:"",enemyPreset:"",focusMine:saved.focusMine||null,focusEnemy:saved.focusEnemy||null,focusPlayer:saved.focusPlayer||saved.focusMine||saved.focusEnemy||null,mineTeamKey:saved.mineTeamKey||null,enemyTeamKey:saved.enemyTeamKey||null,resultsTeam:saved.resultsTeam||null,resultsPlayer:{mine:(saved.resultsPlayer&&saved.resultsPlayer.mine)||null,enemy:(saved.resultsPlayer&&saved.resultsPlayer.enemy)||null},sub:boot.sub,playerSub:{mine:playerPane(saved.playerSub&&saved.playerSub.mine),enemy:playerPane(saved.playerSub&&saved.playerSub.enemy)},wardStyle:saved.wardStyle==="heat"?"heat":"dots",editing:{mine:!!(saved.editing&&saved.editing.mine),enemy:!!(saved.editing&&saved.editing.enemy)},pendingStandin:null};
if(ACCOUNT.locked&&ACCOUNT.teamKey){const lockedTeam=(DATA.teams||[]).find(t=>t.key===ACCOUNT.teamKey);if(lockedTeam){state.mine=activeRoster(lockedTeam,state.enemy);state.mineName=lockedTeam.name||lockedTeam.short||ACCOUNT.team||"My Team";state.mineTeamKey=lockedTeam.key}}
else ensureDefaultMine();
const E=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function cellName(s){let t=String(s??"").replace(/_/g," ").replace(/[^\p{L}\p{N} ]+/gu,"").replace(/\s+/g," ").trim();if(!t)return t;if(t===t.toUpperCase())return t;return t.replace(/([\p{Ll}\p{N}])(\p{Lu})/gu,"$1 $2")}
function teamKey(name){let s=String(name||"").trim().toLowerCase();s=s.replace(/^the\s+/,"");return s.replace(/[^a-z0-9]+/g,"")}
function heroInitials(name){return String(name||"?").trim().split(/\s+/).map(w=>w[0]||"").join("").slice(0,3).toUpperCase()||"?"}
function heroImgFallback(img){const span=document.createElement("span");span.className=(img.className||"heroIcon")+" heroFallback";span.style.width=(img.getAttribute("width")||32)+"px";span.style.height=(img.getAttribute("height")||32)+"px";span.title=img.title||"";span.textContent=img.dataset.fallback||"?";img.replaceWith(span)}
function heroIcon(id,size,gray){size=size||32;const h=(DATA.heroes||{})[id]||{},name=h.n||(id?`Hero ${id}`:"Unknown"),initials=heroInitials(name),cls=`heroIcon${gray?' heroIconGray':''}`;if(!h.key)return `<span class="${cls} heroFallback" style="width:${size}px;height:${size}px" title="${E(name)}">${E(initials)}</span>`;const src=`https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${h.key}.png`;return `<img class="${cls}" loading="lazy" width="${size}" height="${size}" src="${src}" alt="${E(name)}" title="${E(name)}" data-fallback="${E(initials)}" onerror="heroImgFallback(this)">`}
function heroName(id){return ((DATA.heroes||{})[id]||{}).n||`Hero ${id}`}
const pct=(w,g)=>g?`${Math.round(w/g*100)}%`:"—";
const avg=(rows,key)=>{const a=rows.map(x=>x[key]).filter(Number.isFinite);return a.length?a.reduce((s,x)=>s+x,0)/a.length:null};
const fmt=n=>n==null?"—":Number(n).toLocaleString();
const date=t=>t?new Date(t*1000).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"—";
const patchName=id=>DATA.patches.find(p=>p.id===id)?.name||`#${id}`;
const POS={1:"Carry",2:"Mid",3:"Offlane",4:"Soft support",5:"Hard support"};
const signed=(n,digits=0)=>n==null?"—":`${n>0?"+":""}${Number(n).toFixed(digits)}`;
function wilson(w,n,z=1.96){if(!n)return null;const p=w/n,z2=z*z,den=1+z2/n,mid=(p+z2/(2*n))/den,half=z*Math.sqrt((p*(1-p)+z2/(4*n))/n)/den;return [Math.max(0,mid-half)*100,Math.min(1,mid+half)*100]}
function sampleLabel(n){return n>=20?"strong sample":n>=10?"useful sample":n>=5?"developing sample":"thin sample"}
function positionSummary(rows){const slots=new Map(),confidence={high:0,medium:0,low:0};for(const m of rows){if(!m.position)continue;const level=["high","medium","low"].includes(m.positionConfidence)?m.positionConfidence:"low",weight=level==="high"?1:level==="medium"?.7:.35,x=slots.get(m.position)||{position:m.position,games:0,wins:0,weight:0,high:0};x.games++;x.wins+=m.win?1:0;x.weight+=weight;x.high+=level==="high"?1:0;confidence[level]++;slots.set(m.position,x)}const list=[...slots.values()].sort((a,b)=>b.weight-a.weight||b.games-a.games);return {list,primary:list[0]||null,total:list.reduce((s,x)=>s+x.games,0),confidence}}
function officialRows(p){return p.official.matches.map(m=>({win:m.result==="W",duration:m.duration,kills:m.kills,deaths:m.deaths,assists:m.assists,gpm:m.gpm,xpm:m.xpm,lh:m.last_hits,heroDamage:m.hero_damage,towerDamage:m.tower_damage,laneEff:m.lane_eff,position:m.position,positionConfidence:m.position_confidence,obs:m.observer_wards,sen:m.sentry_wards,teamfight:m.teamfight}))}
function persist(){localStorage.setItem(storageKey(),JSON.stringify(state))}
function ensureDefaultMine(){
  if(state.mine&&state.mine.length)return;
  const signin=(ACCOUNT.signins||[]).find(s=>leagueId(s.league)===activeLeague&&s.teamKey);
  const team=signin&&(DATA.teams||[]).find(t=>t.key===signin.teamKey);
  if(!team)return;
  state.mine=activeRoster(team,state.enemy||[]);
  state.mineName=team.name||team.short||signin.team||"My Team";
  state.mineTeamKey=team.key;
}
function paintLeagueSwitch(){
  const el=document.querySelector("#leagueSwitch");
  if(!el)return;
  const row=document.querySelector("#leagueRow");
  if(leagueIds.length<2){if(row)row.hidden=true;el.innerHTML="";return}
  if(row)row.hidden=false;
  el.innerHTML=leagueIds.map(id=>`<button type="button" data-league="${id}" class="${id===activeLeague?"on":""}">${leagueLabel(id)}</button>`).join("");
  el.querySelectorAll("[data-league]").forEach(b=>b.onclick=()=>switchLeague(b.dataset.league));
}
function paintSignedIn(){
  const el=document.querySelector("#signedIn");
  if(!el)return;
  const out=`<a href="/logout">Sign out</a>`;
  if(ACCOUNT.admin)el.innerHTML=`${leagueIds.length>1?`${leagueLabel(activeLeague)} · `:""}Admin · ${out}`;
  else if(ACCOUNT.locked)el.innerHTML=`${E(ACCOUNT.team||ACCOUNT.user)} · ${out}`;
}
function applySaved(saved){
  const subPane=v=>v==="draft"||v==="results"||v==="roles"?v:"players";
  let view=saved.view,sub={mine:subPane(saved.sub&&saved.sub.mine),enemy:subPane(saved.sub&&saved.sub.enemy)};
  if(view==="results"){const onEnemy=!!(saved.resultsTeam&&saved.resultsTeam===saved.enemyTeamKey);view=onEnemy?"opponent":"team";sub[onEnemy?"enemy":"mine"]="results"}
  else if(view==="player"){const id=saved.focusPlayer||saved.focusEnemy||saved.focusMine;view=(saved.enemy||[]).includes(id)?"opponent":"team"}
  if(!view)view="team";else if(!allowedViews.includes(view))view="team";
  state.view=view;state.window=saved.window||"current";
  state.mine=(saved.mine||[]).filter(id=>byId.has(id)).slice(0,5);
  state.enemy=(saved.enemy||[]).filter(id=>byId.has(id)).slice(0,5);
  state.mineName=saved.mineName||"My Team";state.enemyName=saved.enemyName||"Opponent";
  state.minePreset="";state.enemyPreset="";
  state.focusMine=saved.focusMine||null;state.focusEnemy=saved.focusEnemy||null;
  state.focusPlayer=saved.focusPlayer||saved.focusMine||saved.focusEnemy||null;
  state.mineTeamKey=saved.mineTeamKey||null;state.enemyTeamKey=saved.enemyTeamKey||null;
  state.resultsTeam=saved.resultsTeam||null;
  state.resultsPlayer={mine:(saved.resultsPlayer&&saved.resultsPlayer.mine)||null,enemy:(saved.resultsPlayer&&saved.resultsPlayer.enemy)||null};
  state.sub=sub;
  state.playerSub={mine:playerPane(saved.playerSub&&saved.playerSub.mine),enemy:playerPane(saved.playerSub&&saved.playerSub.enemy)};
  state.wardStyle=saved.wardStyle==="heat"?"heat":"dots";
  state.editing={mine:!!(saved.editing&&saved.editing.mine),enemy:!!(saved.editing&&saved.editing.enemy)};
  state.pendingStandin=null;
  if(ACCOUNT.locked&&ACCOUNT.teamKey){const lockedTeam=(DATA.teams||[]).find(t=>t.key===ACCOUNT.teamKey);if(lockedTeam){state.mine=activeRoster(lockedTeam,state.enemy);state.mineName=lockedTeam.name||lockedTeam.short||ACCOUNT.team||"My Team";state.mineTeamKey=lockedTeam.key}}
  else ensureDefaultMine();
}
function switchLeague(league){
  if(!leagueIds.includes(league)||league===activeLeague)return;
  persist();
  activeLeague=league;
  try{localStorage.setItem(LEAGUE_PREF,activeLeague)}catch(e){}
  const next=readSaved(activeLeague);
  applyLeague(activeLeague,keptIds(activeLeague,[...(next.mine||[]),...(next.enemy||[])]));
  applySaved(next);
  applyTheme();paintLeagueSwitch();paintSignedIn();render();
}
function members(side){return state[side].map(id=>byId.get(id)).filter(Boolean)}
function windowMatches(p,window=state.window){
  if(window==="all")return p.matches;
  if(window==="week"){const floor=DATA.generatedAt-7*86400;return p.matches.filter(m=>m.at>=floor)}
  const id=window==="current"?latestPatch?.id:Number(window.split(":")[1]);
  return p.matches.filter(m=>m.patch===id);
}
function record(p){if(state.window==="all")return p.lifetime;const m=windowMatches(p);return {games:m.length,wins:m.filter(x=>x.win).length}}
function isPub(m){return (m.lobby===0||m.lobby===7)&&m.mode!==23}
function matchSummary(rows){
  const games=rows.length,wins=rows.filter(x=>x.win).length,k=rows.reduce((s,x)=>s+(x.kills||0),0),d=rows.reduce((s,x)=>s+(x.deaths||0),0),a=rows.reduce((s,x)=>s+(x.assists||0),0),mins=rows.reduce((s,x)=>s+(x.duration||0),0)/60;
  const wardRows=rows.filter(x=>(x.duration||0)>0&&(Number.isFinite(x.obs)||Number.isFinite(x.sen))),wardMins=wardRows.reduce((s,x)=>s+x.duration,0)/1800,tf=avg(rows,"teamfight"),damageRows=rows.filter(x=>(x.duration||0)>0&&Number.isFinite(x.heroDamage)),towerRows=rows.filter(x=>(x.duration||0)>0&&Number.isFinite(x.towerDamage)),damageMins=damageRows.reduce((s,x)=>s+x.duration,0)/60,towerMins=towerRows.reduce((s,x)=>s+x.duration,0)/60;
  return {games,wins,wr:games?wins/games*100:null,kda:games?((k+a)/Math.max(d,1)):null,kills:games?k/games:null,deaths:games?d/games:null,assists:games?a/games:null,gpm:avg(rows,"gpm"),xpm:avg(rows,"xpm"),hdpm:damageMins?Math.round(damageRows.reduce((s,x)=>s+x.heroDamage,0)/damageMins):null,tdpm:towerMins?Math.round(towerRows.reduce((s,x)=>s+x.towerDamage,0)/towerMins):null,lane:avg(rows,"laneEff"),obs30:wardMins?wardRows.reduce((s,x)=>s+(x.obs||0),0)/wardMins:null,sen30:wardMins?wardRows.reduce((s,x)=>s+(x.sen||0),0)/wardMins:null,wards30:wardMins?wardRows.reduce((s,x)=>s+(x.obs||0)+(x.sen||0),0)/wardMins:null,teamfight:tf==null?null:(tf<=1?tf*100:tf),duration:games?rows.reduce((s,x)=>s+(x.duration||0),0)/games/60:null};
}
function winLoss(rows){return {win:matchSummary(rows.filter(x=>x.win)),loss:matchSummary(rows.filter(x=>!x.win))}}
const COMPARE=[
  {key:"kda",label:"KDA",digits:2,scale:1,good:1},
  {key:"deaths",label:"Deaths / game",digits:1,scale:1,good:-1},
  {key:"gpm",label:"Gold / min",digits:0,scale:55,good:1},
  {key:"xpm",label:"XP / min",digits:0,scale:65,good:1},
  {key:"hdpm",label:"Hero damage / min",digits:0,scale:80,good:1},
  {key:"tdpm",label:"Tower damage / min",digits:0,scale:35,good:1},
  {key:"lane",label:"Lane efficiency",digits:1,scale:6,good:1,suffix:"%"},
  {key:"obs30",label:"Observers / 30",digits:1,scale:1.5,good:1},
  {key:"sen30",label:"Sentries / 30",digits:1,scale:2,good:1},
  {key:"teamfight",label:"Teamfight participation",digits:1,scale:8,good:1,suffix:"%"},
];
function compareRows(rows){const c=winLoss(rows);return COMPARE.map(m=>{const w=c.win[m.key],l=c.loss[m.key];return {...m,w,l,delta:w!=null&&l!=null?w-l:null,strength:w!=null&&l!=null?Math.abs(w-l)/m.scale:0}}).filter(x=>x.w!=null||x.l!=null)}
function evidenceRead(rows){const c=winLoss(rows),ranked=compareRows(rows).filter(x=>x.delta!=null).sort((a,b)=>b.strength-a.strength);if(!c.win.games||!c.loss.games)return [`A win/loss fingerprint needs at least one result on each side; this window is ${c.win.games}–${c.loss.games}.`];const out=[];if(Math.min(c.win.games,c.loss.games)<5)out.push(`Only ${c.win.games} wins and ${c.loss.games} losses are available; treat every difference below as directional, not established.`);for(const x of ranked.slice(0,3)){const direction=x.delta>=0?"higher":"lower",amount=Math.abs(x.delta);if(x.strength<.2)continue;out.push(`Wins come with ${direction} ${x.label.toLowerCase()} (${amount.toFixed(x.digits)}${x.suffix||""} difference).`)}return out.length?out:["Wins and losses have no large separation in the available performance fields."]}
function heroStats(p){
  if(state.window==="all")return p.heroes.map(h=>({...h,players:[p.name]}));
  const map=new Map();for(const m of windowMatches(p)){const h=map.get(m.hero)||{id:m.hero,name:m.heroName,games:0,wins:0,players:[p.name],positions:{}};h.games++;if(m.win)h.wins++;if(m.position)h.positions[m.position]=(h.positions[m.position]||0)+1;map.set(m.hero,h)}return [...map.values()].map(h=>({...h,primaryPosition:Object.entries(h.positions||{}).sort((a,b)=>b[1]-a[1])[0]?.[0]||null})).sort((a,b)=>b.games-a.games||b.wins-a.wins);
}
function teamHeroStats(ps){const map=new Map();for(const p of ps)for(const h of heroStats(p)){const x=map.get(h.id)||{...h,games:0,wins:0,players:[],positions:{}};x.games+=h.games;x.wins+=h.wins;if(!x.players.includes(p.name))x.players.push(p.name);if(h.primaryPosition)x.positions[h.primaryPosition]=(x.positions[h.primaryPosition]||0)+h.games;map.set(h.id,x)}return [...map.values()].map(h=>({...h,primaryPosition:Object.entries(h.positions||{}).sort((a,b)=>b[1]-a[1])[0]?.[0]||h.primaryPosition||null})).sort((a,b)=>b.games-a.games||b.players.length-a.players.length||b.wins-a.wins)}
function heroScore(h){const posterior=(h.wins+2)/(h.games+4),reliability=h.games/(h.games+8);return .5+(posterior-.5)*reliability}
function bestHeroes(ps,limit=12){const all=teamHeroStats(ps),qualified=all.filter(h=>h.games>=3);return (qualified.length?qualified:all).sort((a,b)=>heroScore(b)-heroScore(a)||b.games-a.games||a.name.localeCompare(b.name)).slice(0,limit)}
function teamStats(ps){const recs=ps.map(record),games=recs.reduce((s,x)=>s+x.games,0),wins=recs.reduce((s,x)=>s+x.wins,0),officialGames=ps.reduce((s,p)=>s+p.official.games,0),officialWins=ps.reduce((s,p)=>s+p.official.wins,0),rows=ps.flatMap(p=>windowMatches(p));return {games,wins,officialGames,officialWins,mmr:avg(ps.filter(p=>p.mmr>0),"mmr"),active:ps.filter(p=>p.lastMatch>=DATA.generatedAt-30*86400).length,deep:matchSummary(rows),rows,positions:positionSummary(rows)} }
function windowChoices(){
  const rows=[["current",`Current patch${latestPatch?` · ${latestPatch.name}`:""}`],["week","Last 7 days"],["all","All time"]];
  for(const p of [...DATA.patches].reverse().slice(0,10))rows.push([`patch:${p.id}`,`Patch ${p.name}`]);
  if(!rows.some(r=>r[0]===state.window))state.window="current";
  return rows;
}
function windowSelect(){
  return `<label class="window"><span>Public games</span><select data-window aria-label="Public games window">${windowChoices().map(([v,l])=>`<option value="${E(v)}" ${v===state.window?"selected":""}>${E(l)}</option>`).join("")}</select></label>`;
}
function leaguesOf(rows, fallback){
  const names=[];
  for(const row of rows||[]){
    const name=row.league||fallback||"";
    if(name&&!names.includes(name))names.push(name);
  }
  return names;
}
function teamChoiceOptions(presetKey){
  const teams=DATA.teams||[];
  const fallback=DATA.officialSource&&DATA.officialSource.league;
  const leagues=leaguesOf(teams, fallback);
  const option=(t,i)=>`<option value="${i}" ${String(i)===state[presetKey]?'selected':''}>${E(t.short||t.name)}${t.record?` · ${E(t.record)}`:''}</option>`;
  if(leagues.length<2)return teams.map(option).join("");
  return leagues.map(league=>`<optgroup label="${E(league)}">${teams.map((t,i)=>({t,i})).filter(x=>(x.t.league||fallback)===league).map(x=>option(x.t,x.i)).join("")}</optgroup>`).join("");
}
function setupHead(side){
  const presetKey=side+"Preset",nameKey=side+"Name",editing=!!(state.editing&&state.editing[side]);
  const teamObj=(DATA.teams||[]).find(t=>t.key===sideLoadedKey(side));
  const nameField=editing?`<input value="${E(state[nameKey])}" title="${E(state[nameKey])}" data-name="${side}" aria-label="${side==='mine'?'My team':'Opponent'} name">`:`<span class="teamName">${E(state[nameKey])}</span>`;
  const record=teamObj&&teamObj.record?`<span class="teamRecord">${E(teamObj.record)}</span>`:'';
  const gear=`<button class="loadTeam gearBtn" data-edit-roster="${side}" aria-label="${editing?'Done':'Settings'}" title="${editing?'Done':'Settings'}"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.03 7.03 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.9 2h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.6.24-1.14.55-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.81 8.48a.5.5 0 0 0 .12.64L4.96 10.7c-.04.31-.06.63-.06.94s.02.63.06.94L2.93 14.16a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.4.31.64.22l2.39-.96c.49.39 1.03.7 1.63.94l.36 2.54c.05.24.25.42.49.42h3.8c.24 0 .44-.18.49-.42l.36-2.54c.6-.24 1.14-.55 1.63-.94l2.39.96c.24.09.51 0 .64-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.6A3.6 3.6 0 1 1 12 8.4a3.6 3.6 0 0 1 0 7.2z"/></svg></button>`;
  const picker=editing&&!(side==="mine"&&ACCOUNT.locked)&&DATA.teams?.length?`<select class="preset" data-team-choice="${side}" aria-label="Choose ${side==='mine'?'my':'opponent'} team"><option value="">Choose team</option>${teamChoiceOptions(presetKey)}</select><button class="loadTeam" data-load-team="${side}" ${state[presetKey]===''?'disabled':''}>Add team</button>`:'';
  return `<div class="teamhead"><div class="teamIdentity">${nameField}${record}</div>${picker}${gear}</div>`;
}
function setupRoster(side){
  const ps=members(side),full=ps.length>=5,editing=!!(state.editing&&state.editing[side]);
  const teamObj=(DATA.teams||[]).find(t=>t.key===sideLoadedKey(side));
  const postedSet=new Set(teamObj?teamObj.postedRoster||[]:[]);
  const pending=state.pendingStandin&&state.pendingStandin.side===side?state.pendingStandin.id:null;
  const focusId=state[side==='mine'?'focusMine':'focusEnemy'];
  const chips=`<div class="rosterLine"><div class="chips">${ps.length?ps.map(p=>{const sub=teamObj&&!postedSet.has(p.id),selected=!pending&&focusId===p.id,cls=`chip${sub?' subChipTag':''}${pending?' swapReady':''}${selected?' on':''}`,action=pending?` data-swap-for="${side}:${p.id}" title="Swap out ${E(p.name)}"`:` data-focus="${side}:${p.id}"`,goneMark=editing&&teamObj?`<button class="markGone" data-mark-replaced="${side}:${p.id}" title="Mark as replaced (left the team)">replaced</button>`:'',x=editing?`<button data-remove="${side}:${p.id}" aria-label="Remove ${E(p.name)}">×</button>`:'';return `<span class="${cls}"${action}>${E(p.name)}${sub?' <small class="sub">sub</small>':''}${goneMark}${x}</span>`}).join(""):`<span class="emptychip">Add a team or pull a player</span>`}</div><div class="rosterRight">${replacementsRow(side,teamObj)}</div></div>`;
  const pull=editing?`<div class="pullbox" data-pull="${side}"><input type="text" class="pullInput" data-pull-input="${side}" placeholder="Name, Steam ID, or Dotabuff/OpenDota link" autocomplete="off" ${full?'disabled':''}><button data-pull-btn="${side}" ${full?'disabled':''}>Pull player</button><div class="pullDropdown hidden" data-pull-dropdown="${side}"></div><div class="pullStatus" data-pull-status="${side}"></div>${full?'<div class="hint">Roster is full — remove a player to pull a standin.</div>':''}</div>`:'';
  return chips+pull;
}
function setup(side,showRoster=true){return setupHead(side)+(showRoster?setupRoster(side):"")}
function replacementsRow(side,teamObj){
  if(!teamObj)return "";
  const editing=!!(state.editing&&state.editing[side]);
  const pending=state.pendingStandin&&state.pendingStandin.side===side?state.pendingStandin.id:null;
  const gone=(teamObj.replaced||[]).map(id=>{const from=(teamObj.replacedPlayers||[]).find(r=>r.id===id),p=byId.get(id);return {id,name:(p&&p.name)||(from&&from.name)||String(id),games:from&&from.games!=null?from.games:null}});
  const goneChips=gone.length?gone.map(r=>{const un=editing?`<button class="markGone" data-unmark-replaced="${side}:${r.id}" title="Count this player again">undo</button>`:'';return `<span class="chip goneChip">${E(r.name)}${r.games?` <small>${r.games}g</small>`:''}${un}</span>`}).join(""):`<span class="emptychip">None</span>`;
  const goneRow=(gone.length||editing)?`<div class="replacementsRow"><b>Replaced</b><div class="chips">${goneChips}</div></div>`:'';
  const actions=editing?`<div class="repActions"><button data-save-roster="${side}">Save as team roster</button>${teamObj.edited?`<button data-reset-roster="${side}">Reset to posted roster</button>`:''}</div>`:'';
  const hint=pending?`<div class="hint">Click a roster player to swap in ${E((byId.get(pending)||{}).name||'standin')}.</div>`:(editing?`<div class="hint">Mark a player replaced if they left the team. Current roles use games without them. Heroes only they won on stay listed, struck through.</div>`:'');
  if(!goneRow&&!actions&&!hint)return "";
  return `<div class="standinCol">${goneRow}${actions}${hint}</div>`;
}
function standinItems(side,teamObj){
  if(!teamObj)return [];
  const on=new Set(state[side]),replacedSet=new Set(teamObj.replaced||[]);
  const posted=teamObj.postedRoster||[],reps=teamObj.replacements||[];
  const benchPosted=posted.filter(id=>!on.has(id)&&!replacedSet.has(id)).map(id=>{const p=byId.get(id);return {id,name:p?p.name:String(id),games:null}});
  return [...benchPosted,...(reps.filter(r=>!on.has(r.id)&&!replacedSet.has(r.id)))];
}
function standinsTab(side){
  const teamObj=(DATA.teams||[]).find(t=>t.key===sideLoadedKey(side));
  if(!teamObj)return `<div class="notice">Add a team to see standins.</div>`;
  const editing=!!(state.editing&&state.editing[side]);
  const pending=state.pendingStandin&&state.pendingStandin.side===side?state.pendingStandin.id:null;
  const items=standinItems(side,teamObj);
  const markBtn=id=>editing?`<button class="markGone" data-mark-replaced="${side}:${id}" title="Mark as replaced (left the team)">replaced</button>`:'';
  const chips=items.length?items.map(r=>`<span class="chip subChip${pending===r.id?' pending':''}" data-sub-chip="${side}:${r.id}" title="${r.games!=null?`${r.games} official game${r.games===1?'':'s'} for this team`:'Posted roster'}">${E(r.name)}${r.games!=null?` <small>${r.games}g</small>`:''}${markBtn(r.id)}</span>`).join(""):`<span class="emptychip">None</span>`;
  const hint=pending?`<div class="hint">Click a roster player to swap in ${E((byId.get(pending)||{}).name||'standin')}.</div>`:(editing?`<div class="hint">Click a standin, then a roster player, to swap them in.</div>`:'');
  return `<div class="contentBlock"><h3>Standins</h3><div class="chips">${chips}</div>${hint}</div>`;
}
function sideHeader(side,extra=""){return `<div class="sideTitle"><h2>${E(state[side+"Name"])}</h2><span class="sample">${extra}</span></div>`}
function metric(label,value,note=""){return `<div class="metric"><span>${label}</span><b>${value}</b>${note?`<small>${note}</small>`:""}</div>`}
function intervalNote(w,g){const ci=wilson(w,g);return ci?`95% range ${Math.round(ci[0])}–${Math.round(ci[1])}% · ${sampleLabel(g)}`:"no sample"}
function winLossPanel(rows,title="Wins / losses"){
  const c=winLoss(rows),metrics=compareRows(rows);
  return `<div class="card section"><div class="analysisTitle"><h3>${E(title)}</h3><small>${c.win.games} wins · ${c.loss.games} losses</small></div>${metrics.length&&c.win.games&&c.loss.games?`<table class="compareTable"><thead><tr><th>Signal</th><th>Wins</th><th>Losses</th><th>Difference</th></tr></thead><tbody>${metrics.map(x=>{const favorable=x.delta!=null&&x.delta*x.good>0;return `<tr><td>${E(x.label)}</td><td>${x.w==null?'—':x.w.toFixed(x.digits)}${x.w==null?'':x.suffix||''}</td><td>${x.l==null?'—':x.l.toFixed(x.digits)}${x.l==null?'':x.suffix||''}</td><td class="${favorable?'deltaUp':x.delta==null?'':'deltaDown'}">${!favorable&&x.delta!=null?'<span class="deltaTag" title="In their wins this stat moves the unhelpful way">reversed</span>':''}${signed(x.delta,x.digits)}${x.delta==null?'':x.suffix||''}</td></tr>`}).join("")}</tbody></table>`:`<div class="emptyAnalysis">Need a win and a loss.</div>`}</div>`
}
function positionPanel(rows,title="Positions"){
  const s=positionSummary(rows),max=Math.max(...s.list.map(x=>x.games),1);
  return `<div class="card section"><div class="analysisTitle"><h3>${E(title)}</h3></div>${s.list.length?`<div class="roleLine" style="margin-bottom:11px"><span class="posBadge">P${s.primary.position}</span><strong>${E(POS[s.primary.position])}</strong><span class="conf">primary in ${s.primary.games}/${s.total} classified games · confidence ${s.confidence.high} high / ${s.confidence.medium} medium / ${s.confidence.low} low</span></div><div class="positionBars">${s.list.map(x=>`<div class="positionRow"><span>P${x.position} ${E(POS[x.position])}</span><div class="track"><div class="fill" style="width:${x.games/max*100}%"></div></div><span class="value">${x.games}g · ${pct(x.wins,x.games)}</span></div>`).join("")}</div>`:`<div class="emptyAnalysis">No position could be classified in this window.</div>`}</div>`
}
function bestHeroPanel(ps,title="Best heroes"){
  const hs=bestHeroes(ps);return `<div class="card section"><div class="analysisTitle"><h3>${E(title)}</h3></div><div class="heroTable">${hs.map((h,i)=>`<div class="heroRow best"><b>${i+1}. ${heroIcon(h.id,22)} ${E(h.name)}<span class="sub">${E(h.players.join(', '))}</span></b><span>${h.wins}–${h.games-h.wins}</span><span class="${h.games>=5&&h.wins/h.games>=.55?'good':h.games>=5&&h.wins/h.games<.45?'bad':''}">${pct(h.wins,h.games)}</span><span><span class="posBadge">${h.primaryPosition?'P'+h.primaryPosition:'—'}</span></span></div>`).join("")||"<span class='sample'>No hero data in this window.</span>"}</div></div>`
}
function empty(side){return sideHeader(side)+`<div class="notice">Add players to this roster to begin scouting.</div>`}
function sourceTeam(ps){const ids=new Set(ps.map(p=>p.id));return (DATA.teams||[]).find(t=>t.roster.length===ids.size&&t.roster.every(id=>ids.has(id)))}
function sideLoadedKey(side){const src=sourceTeam(members(side));if(src)return src.key;const byName=teamKey(state[side+"Name"]);const direct=(DATA.teams||[]).find(t=>t.key===byName);if(direct)return direct.key;return state[side+"TeamKey"]||null}
function teamByKey(key){return (DATA.teams||[]).find(t=>t.key===key)}
function standingByKey(key){return (DATA.standings||[]).find(s=>s.key===key)}
function captainLabel(name,key){const hit=(key&&(teamByKey(key)||standingByKey(key)))||(name&&(teamByKey(teamKey(name))||standingByKey(teamKey(name))));return (hit&&hit.captain)||name||"—"}
function dbMatchUrl(id){return `https://www.dotabuff.com/matches/${id}`}
function opponentLink(name,key,matchId){const label=captainLabel(name,key);return matchId?`<a target="_blank" rel="noopener" href="${dbMatchUrl(matchId)}" title="${E(name||label)}">${E(label)}</a>`:E(label)}
function officialTeamHeroStats(ps){const map=new Map();for(const p of ps){for(const m of p.official.matches||[]){const id=m.hero_id;if(!id)continue;const x=map.get(id)||{id,name:heroName(id),games:0,wins:0,players:[],positions:{}};x.games++;if(m.result==="W")x.wins++;if(!x.players.includes(p.name))x.players.push(p.name);if(m.position)x.positions[m.position]=(x.positions[m.position]||0)+1;map.set(id,x)}}return [...map.values()].map(h=>({...h,primaryPosition:Object.entries(h.positions||{}).sort((a,b)=>b[1]-a[1])[0]?.[0]||null})).sort((a,b)=>b.games-a.games||b.players.length-a.players.length||b.wins-a.wins)}
function impactPlayers(ps,limit=3){const rows=ps.map(p=>{const off=officialRows(p),s=matchSummary(off);return {p,s,pos:positionSummary(off).primary}}).filter(x=>x.s.games);const qualified=rows.filter(x=>x.s.games>=5);return (qualified.length?qualified:rows).sort((a,b)=>(b.s.kda||0)-(a.s.kda||0)||b.s.games-a.s.games||(b.s.gpm||0)-(a.s.gpm||0)).slice(0,limit)}
function impactPanel(ps){const top=impactPlayers(ps);return `<div class="section"><h3>Highest impact</h3><p class="matchupCap">Ranked by KDA in LD2L officials.</p><div class="tableWrap"><table class="tbl matchupTbl"><thead><tr><th>Player</th><th>KDA</th><th>GPM</th><th>XPM</th><th>WR</th><th>G</th></tr></thead><tbody>${top.map(({p,s,pos})=>{const role=pos?`P${pos.position} ${POS[pos.position]}`:"—";return `<tr><td>${E(p.name)}<span class="matchupWho">${E(role)}</span></td><td>${s.kda==null?'—':s.kda.toFixed(2)}</td><td>${s.gpm==null?'—':Math.round(s.gpm)}</td><td>${s.xpm==null?'—':Math.round(s.xpm)}</td><td>${pct(s.wins,s.games)}</td><td>${s.games}</td></tr>`}).join("")||"<tr><td colspan='6'>No official player data.</td></tr>"}</tbody></table></div></div>`}
function overview(side){const ps=members(side);if(!ps.length)return empty(side);const posted=sourceTeam(ps),officialGames=ps.reduce((s,p)=>s+p.official.games,0),officialWins=ps.reduce((s,p)=>s+p.official.wins,0),heroes=officialTeamHeroStats(ps),max=Math.max(...heroes.slice(0,6).map(h=>h.games),1),rec=posted?.record||(officialGames?`${officialWins}–${officialGames-officialWins}`:null),extra=rec?`${rec} official`:"";return sideHeader(side,extra)+`<div class="card">${impactPanel(ps)}<div class="section"><h3>Most exposed heroes</h3><div class="bars">${heroes.slice(0,6).map(h=>`<div class="barrow"><span>${heroIcon(h.id,18)} ${E(h.name)}</span><div class="track"><div class="fill" style="width:${h.games/max*100}%"></div></div><span class="value">${h.games}g · ${pct(h.wins,h.games)}</span></div>`).join("")||"<span class='sample'>No official hero data.</span>"}</div></div></div>`}
function playerRow(p,side){const r=record(p),m=matchSummary(windowMatches(p)),pos=positionSummary(windowMatches(p)).primary;return `<button class="player ${state[side==='mine'?'focusMine':'focusEnemy']===p.id?'on':''}" data-focus="${side}:${p.id}"><span class="who"><b>${E(p.name)}</b><small>${E(p.rank)}${pos?` · P${pos.position} ${E(POS[pos.position])} inferred`:''}</small></span><span class="stat"><b>${p.mmr||'—'}</b><small>MMR</small></span><span class="stat"><b>${pct(r.wins,r.games)}</b><small>${r.games} games</small></span><span class="stat"><b class="official">${p.official.winrate==null?'—':p.official.winrate+'%'}</b><small>${p.official.games} official</small></span><span class="stat"><b>${m.kda==null?'—':m.kda.toFixed(2)}</b><small>KDA</small></span></button>`}
function steam64(id){return (BigInt(id)+76561197960265728n).toString()}
function steamUrl(id){return `https://steamcommunity.com/profiles/${steam64(id)}`}
function steamIcon(){return `<svg class="steamIcon" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" focusable="false"><path fill="currentColor" d="M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.628c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012zM16.063 12.3c-1.796 0-3.256-1.459-3.256-3.258 0-1.797 1.46-3.256 3.256-3.256 1.798 0 3.257 1.459 3.257 3.256 0 1.799-1.459 3.258-3.257 3.258zm0-5.303c-1.128 0-2.044.916-2.044 2.044 0 1.128.916 2.044 2.044 2.044 1.129 0 2.045-.916 2.045-2.044 0-1.128-.916-2.044-2.045-2.044z"/></svg>`}
function steamLink(id){return `<a class="steamLink" target="_blank" rel="noopener" href="${steamUrl(id)}" title="Steam" aria-label="Steam">${steamIcon()}</a>`}
function esportsPillText(esports){if(!esports||esports.status==="unavailable")return "Esports: not fetched";if(!esports.games)return "Esports: no ticketed games";return `Esports ${esports.wins}-${esports.games-esports.wins} · ${esports.winrate==null?'—':esports.winrate+'%'}`}
function esportsPillTitle(esports){const unresolved=(esports&&esports.unresolved)||0;return `Ticketed league matches found via OpenDota (the same basis as Dotabuff's esports profile). ${unresolved} lobby game${unresolved===1?'':'s'} not yet classified.`}
function playerHead(p){const links=p.links||{};return `<div class="card"><div class="section detailHead"><div><h3>${E(p.name)}</h3><p>${E(p.rank)} · ${p.mmr?p.mmr+' MMR':'MMR unavailable'}${p.private?' · Private profile':''} · ${steamLink(p.id)}${links.dotabuff?` · <a target="_blank" rel="noopener" href="${links.dotabuff}">Dotabuff</a>`:''}${links.dotabuffEsports?` · <a target="_blank" rel="noopener" href="${links.dotabuffEsports}">Esports profile</a>`:''}</p></div><span class="pillRow"><span class="pill">Officials ${p.official.wins}–${p.official.games-p.official.wins} · ${p.official.winrate==null?'—':p.official.winrate+'%'}</span><span class="pill" title="${E(esportsPillTitle(p.esports))}">${E(esportsPillText(p.esports))}</span></span></div></div>`}
function playerOverview(p){
  const officials=officialRows(p);
  if(!officials.length)return `<div class="notice">No cached LD2L official matches for this player.</div>`;
  return `<div class="detail"><div class="contentBlock">${winLossPanel(officials,"Officials")}</div><div class="contentBlock">${positionPanel(officials,"Official positions")}</div></div>`;
}
function playerOfficialsTab(p){
  return `<div class="detail"><div class="contentBlock">${officialSeriesList(p)}</div></div>`;
}
function playerPubsTab(p){
  const rows=windowMatches(p).filter(isPub),wins=rows.filter(x=>x.win).length,m=matchSummary(rows),pos=positionSummary(rows).primary,ci=wilson(wins,rows.length);
  return `<div class="detail"><div class="pageHeading">${windowSelect()}</div><div class="card"><div class="metrics detailMetrics">${metric("Window",`${wins}–${rows.length-wins}`,pct(wins,rows.length))}${metric("95% WR range",ci?`${Math.round(ci[0])}–${Math.round(ci[1])}%`:"—")}${metric("Observed role",pos?`P${pos.position} ${POS[pos.position]}`:"Unclear",pos?`${pos.games}/${positionSummary(rows).total} classified games`:"no classified games")}${metric("KDA",m.kda==null?'—':m.kda.toFixed(2))}${metric("GPM / XPM",`${fmt(m.gpm==null?null:Math.round(m.gpm))} / ${fmt(m.xpm==null?null:Math.round(m.xpm))}`)}${metric("Exact lanes",`${p.deep.laneW}–${p.deep.laneD}–${p.deep.laneL}`,`${p.deep.lanes} parsed`)}</div></div><div class="contentBlock">${winLossPanel(rows)}</div><div class="contentBlock"><div class="analysisGrid">${positionPanel(rows)}${bestHeroPanel([p])}</div></div><div class="contentBlock">${matchTable(p)}</div></div>`;
}
let heroSort={key:"score",dir:-1};
function heroSortValue(h,key){
  if(key==="games")return h.lifetime.games+h.recent.games;
  if(key==="pubsWr")return h.recent.games?h.recent.wins/h.recent.games:-1;
  if(key==="esportsGames")return h.esports.games;
  return h.score;
}
function heroTagChips(tags){return (tags||[]).map(t=>`<span class="chip">${E(t)}</span>`).join(" ")}
function heroGemsCard(pool){
  const gems=pool.gems||[];
  if(!gems.length)return `<div class="card section"><h3>Hidden gems</h3><p class="sample">No hidden gems: nothing outside their comfort picks clears the bar yet.</p></div>`;
  return `<div class="card section"><h3>Hidden gems</h3><div class="gemList">${gems.map(h=>`<div class="gemRow"><b>${heroIcon(h.id,26)} ${E(heroName(h.id))}<span class="sub">${h.position?`P${h.position} ${E(POS[h.position]||'')}`:''}</span></b><span class="gemScore" title="Shrunk win rate">${Math.round(h.score*100)}%</span><span class="gemReason">${E(h.reason)}</span></div>`).join("")}</div></div>`;
}
function heroTableHead(){
  const th=(key,label)=>`<th data-hero-sort="${key}" class="${heroSort.key===key?'on':''}">${label}${heroSort.key===key?' ▾':''}</th>`;
  return `<tr>${th("score","Hero")}<th>Pos</th>${th("pubsWr","Pubs 6mo")}${th("games","Lifetime")}<th>Officials</th>${th("esportsGames","Esports")}<th>Meta WR</th><th>Tags</th></tr>`;
}
function heroPoolRow(h){
  const pubsWr=h.recent.games?pct(h.recent.wins,h.recent.games):"—",lifeWr=h.lifetime.games?pct(h.lifetime.wins,h.lifetime.games):"—";
  const delta=h.recent.kdaDelta,deltaCls=delta==null?"":delta>=0?"good":"bad";
  return `<tr><td class="heroCol">${heroIcon(h.id,20)} ${E(heroName(h.id))}</td><td>${h.position?'P'+h.position:'—'}</td><td>${h.recent.games?`${h.recent.wins}–${h.recent.games-h.recent.wins}`:'—'} <span class="sub">${pubsWr}</span> <span class="${deltaCls}">${delta==null?'':signed(delta,1)}</span></td><td>${h.lifetime.games?`${h.lifetime.wins}–${h.lifetime.games-h.lifetime.wins}`:'—'} <span class="sub">${lifeWr} · ${date(h.lifetime.last)}</span></td><td>${h.official.games?`${h.official.wins}–${h.official.games-h.official.wins}`:'—'}</td><td>${h.esports.games?`${h.esports.wins}–${h.esports.games-h.esports.wins}`:'—'}</td><td>${h.metaWr==null?'—':h.metaWr+'%'}</td><td class="matchupNote">${heroTagChips(h.tags)}</td></tr>`;
}
function heroPoolTable(pool){
  const heroes=[...(pool.heroes||[])].sort((a,b)=>heroSortValue(b,heroSort.key)-heroSortValue(a,heroSort.key));
  return `<div class="tableWrap"><table class="tbl"><thead>${heroTableHead()}</thead><tbody>${heroes.map(heroPoolRow).join("")||'<tr><td colspan="8">No hero data yet.</td></tr>'}</tbody></table></div>`;
}
function playerHeroesTab(p){
  const pool=p.heroPool||{heroes:[],gems:[],baseline:{},pubWindowDays:180};
  return `<div class="detail">${heroGemsCard(pool)}<div class="contentBlock">${heroPoolTable(pool)}</div><p class="foot">Pubs = ranked and unranked matches from the last ${pool.pubWindowDays||180} days (Turbo and lobbies excluded). Score shrinks small samples toward 50%; recent games count double.</p></div>`;
}
function leagueNameById(es,id){const row=(es.leagues||[]).find(l=>l.id===id);return row?row.name:(id?`League ${id}`:"—")}
function esportsPoolCompare(p){
  const esHeroes=(p.esports&&p.esports.heroes)||[],pool=(p.heroPool&&p.heroPool.heroes)||[];
  const pubs=new Map(pool.filter(h=>h.recent.games).map(h=>[h.id,h.recent.games])),es=new Map(esHeroes.map(h=>[h.id,h.games]));
  const totalEsports=esHeroes.reduce((s,h)=>s+h.games,0),totalPubs=(p.heroPool&&p.heroPool.baseline&&p.heroPool.baseline.games)||[...pubs.values()].reduce((s,g)=>s+g,0);
  if(!totalEsports||!totalPubs)return `<h3>League pool vs pub pool</h3><p class="sample">Not enough data in both pools yet to compare.</p>`;
  const rows=[...new Set([...es.keys(),...pubs.keys()])].map(id=>({id,diff:((es.get(id)||0)/totalEsports*100)-((pubs.get(id)||0)/totalPubs*100)}));
  const esportsHeavy=rows.filter(x=>x.diff>=4).sort((a,b)=>b.diff-a.diff).slice(0,8);
  const pubHeavy=rows.filter(x=>x.diff<=-4).sort((a,b)=>a.diff-b.diff).slice(0,8);
  const list=items=>items.length?`<div class="heroChipRow">${items.map(x=>`<span class="heroChip">${heroIcon(x.id,18)} ${E(heroName(x.id))} <small>${signed(x.diff,0)}pt</small></span>`).join("")}</div>`:`<p class="sample">No hero differs by 4+ points.</p>`;
  return `<h3>League pool vs pub pool</h3><details class="method"><summary>How this is calculated</summary><p class="matchupCap">Share of ticketed league games minus share of recent pub games (${totalEsports} league, ${totalPubs} pub). Heroes they save for league lobbies, and the reverse.</p></details><div class="pageGrid resultsSummary"><div class="card section"><h3>More in league games</h3>${list(esportsHeavy)}</div><div class="card section"><h3>More in pubs</h3>${list(pubHeavy)}</div></div>`;
}
function playerEsportsTab(p){
  const es=p.esports,links=p.links||{};
  if(!es||es.status==="unavailable")return `<div class="notice">Esports history hasn't been fetched for this player yet. Team Scout's background refresh fills it in within 12 hours.</div>`;
  const classified=es.lobbyGames-es.unresolved;
  const metrics=`<div class="metrics detailMetrics">${metric("All-time",`${es.wins}–${es.games-es.wins}`,pct(es.wins,es.games))}${metric("Last 6 months",`${es.sixMonth.wins}–${es.sixMonth.games-es.sixMonth.wins}`,pct(es.sixMonth.wins,es.sixMonth.games))}${metric("Leagues played",es.leagues.length)}${metric("Lobby games classified",`${classified}/${es.lobbyGames}`,es.unresolved?`${es.unresolved} unresolved`:"all resolved")}</div>`;
  const leaguesTbl=`<div class="tableWrap"><table class="tbl"><thead><tr><th>League</th><th>Tier</th><th>W-L</th><th>WR</th><th>First</th><th>Latest</th></tr></thead><tbody>${es.leagues.map(l=>`<tr><td>${E(l.name)}</td><td>${E(l.tier||'—')}</td><td>${l.wins}–${l.games-l.wins}</td><td>${pct(l.wins,l.games)}</td><td>${date(l.first)}</td><td>${date(l.latest)}</td></tr>`).join("")||'<tr><td colspan="6">No ticketed leagues found yet.</td></tr>'}</tbody></table></div>`;
  const matchesTbl=`<div class="tableWrap"><table class="tbl"><thead><tr><th>Match</th><th>Date</th><th class="heroCol">Hero</th><th>League</th><th>Result</th><th>K/D/A</th><th>GPM</th><th>XPM</th></tr></thead><tbody>${es.matches.map(m=>`<tr><td><a target="_blank" rel="noopener" href="https://www.dotabuff.com/matches/${m.id}">${m.id}</a></td><td>${date(m.at)}</td><td class="heroCol">${heroIcon(m.hero,20)} ${E(heroName(m.hero))}</td><td>${E(leagueNameById(es,m.league))}</td><td class="${m.win?'good':'bad'}">${m.win?'W':'L'}</td><td>${m.kills??'—'}/${m.deaths??'—'}/${m.assists??'—'}</td><td>${m.gpm??'—'}</td><td>${m.xpm??'—'}</td></tr>`).join("")||'<tr><td colspan="8">No cached ticketed matches.</td></tr>'}</tbody></table></div>`;
  return `<div class="detail"><div class="card"><div class="section"><div class="analysisTitle"><h3>Ticketed league record</h3>${links.dotabuffEsports?`<a class="extLink" target="_blank" rel="noopener" href="${links.dotabuffEsports}">Open Dotabuff esports profile ↗</a>`:''}</div>${metrics}</div></div><div class="contentBlock"><h3>Leagues</h3>${leaguesTbl}</div><div class="contentBlock">${esportsPoolCompare(p)}</div><div class="contentBlock"><h3>Recent ticketed matches</h3>${matchesTbl}</div></div>`;
}
function playerDetail(p){return `<div class="detail">${playerHead(p)}${playerOverview(p)}</div>`}
function playersView(side){const ps=members(side);if(!ps.length)return empty(side);const fk=side==='mine'?'focusMine':'focusEnemy';let focus=byId.get(state[fk]);if(!focus||!state[side].includes(focus.id))focus=ps[0];return sideHeader(side,`${ps.length} players`)+`<div class="playerList">${ps.map(p=>playerRow(p,side)).join("")}</div>${playerDetail(focus)}`}
function heroesView(side){const ps=members(side);if(!ps.length)return empty(side);const hs=teamHeroStats(ps);return sideHeader(side,`${hs.length} heroes seen`)+`<div class="card section"><div class="heroTable">${hs.slice(0,30).map((h,i)=>`<div class="heroRow"><b>${i+1}. ${E(h.name)}</b><span>${h.games}g</span><span class="${h.games>=3&&h.wins/h.games>=.55?'good':''}">${pct(h.wins,h.games)}</span><span class="coverage">${h.players.length} player${h.players.length===1?'':'s'} · ${E(h.players.join(', '))}</span></div>`).join("")||"<span class='sample'>No hero data in this window.</span>"}</div></div>`}
function deepView(side){const ps=members(side);if(!ps.length)return empty(side);const rows=ps.map(p=>({p,s:matchSummary(windowMatches(p))}));return sideHeader(side,"performance and parsed evidence")+`<div class="tableWrap"><table class="tbl"><thead><tr><th>Player</th><th>Games</th><th>KDA</th><th>GPM</th><th>XPM</th><th>HD/min</th><th>TD/min</th><th>Lane</th><th>Dewards/30</th></tr></thead><tbody>${rows.map(({p,s})=>`<tr><td>${E(p.name)}</td><td>${s.games}</td><td>${s.kda==null?'—':s.kda.toFixed(2)}</td><td>${fmt(s.gpm)}</td><td>${fmt(s.xpm)}</td><td>${fmt(s.hdpm)}</td><td>${fmt(s.tdpm)}</td><td>${s.lane==null?'—':s.lane+'%'}</td><td>${p.deep.dewards30??'—'}</td></tr>`).join("")}</tbody></table></div>`}
function matchTable(p,official=false){if(official)return officialSeriesList(p);const rows=windowMatches(p).filter(isPub);return `<div class="tableWrap"><table class="tbl"><thead><tr><th>Match</th><th>Date</th><th class="heroCol">Hero</th><th>Position</th><th>Result</th><th>K/D/A</th><th>GPM</th><th>XPM</th><th>Hero dmg</th><th>Tower dmg</th><th>Lane eff</th><th>Obs</th><th>Sen</th></tr></thead><tbody>${rows.map(m=>`<tr><td><a target="_blank" rel="noopener" href="https://www.opendota.com/matches/${m.id}">${m.id}</a><span class="sub">${E(patchName(m.patch))}</span></td><td>${date(m.at)}</td><td class="heroCol">${heroIcon(m.hero,20)} ${E(m.heroName)}</td><td title="${E((m.positionEvidence||[]).join(', '))}">${m.position?`P${m.position} ${E(POS[m.position])}`:'—'}<span class="sub">${E(m.positionConfidence||'')}</span></td><td class="${m.win?'good':'bad'}">${m.win?'W':'L'}</td><td>${m.kills??'—'}/${m.deaths??'—'}/${m.assists??'—'}</td><td>${m.gpm??'—'}</td><td>${m.xpm??'—'}</td><td>${fmt(m.heroDamage)}</td><td>${fmt(m.towerDamage)}</td><td>${laneWithResult(m.laneEff, m.win)}</td><td>${m.obs??'—'}</td><td>${m.sen??'—'}</td></tr>`).join("")||`<tr><td colspan="13">No matches in this window.</td></tr>`}</tbody></table></div>`}
function matchesView(side){const ps=members(side);if(!ps.length)return empty(side);const fk=side==='mine'?'focusMine':'focusEnemy';let p=byId.get(state[fk]);if(!p||!state[side].includes(p.id))p=ps[0];return sideHeader(side,"match-by-match evidence")+`<div class="selector"><select data-log-player="${side}" aria-label="Player match log">${ps.map(x=>`<option value="${x.id}" ${x.id===p.id?'selected':''}>${E(x.name)}</option>`).join("")}</select></div><div class="card"><div class="section"><h3>Public</h3>${matchTable(p)}</div><div class="section"><h3>Officials</h3>${matchTable(p,true)}</div></div>`}
function patchesView(side){const ps=members(side);if(!ps.length)return empty(side);const relevant=[...DATA.patches].reverse().filter(pa=>ps.some(p=>p.matches.some(m=>m.patch===pa.id))).slice(0,12);return sideHeader(side,"form across major patches")+`<div class="card section patchRows">${relevant.map(pa=>{const rows=ps.flatMap(p=>p.matches.filter(m=>m.patch===pa.id)),s=matchSummary(rows);return `<div class="patchRow"><b>${E(pa.name)}</b><span>${s.games}<small>games</small></span><span class="${s.wr>=55?'good':s.wr<45?'bad':''}">${s.wr==null?'—':Math.round(s.wr)+'%'}<small>win rate</small></span><span>${s.kda==null?'—':s.kda.toFixed(2)}<small>KDA</small></span></div>`}).join("")||"<span class='sample'>No patch-tagged matches in the cached sample.</span>"}</div>`}
function heroPanel(ps){const all=officialTeamHeroStats(ps),qualified=all.filter(h=>h.games>=3),hs=(qualified.length?qualified:all).sort((a,b)=>heroScore(b)-heroScore(a)||b.games-a.games||a.name.localeCompare(b.name)).slice(0,12);return `<div class="card section"><div class="analysisTitle"><h3>Best heroes</h3></div><div class="heroTable">${hs.map((h,i)=>`<div class="heroRow best"><b>${i+1}. ${heroIcon(h.id,22)} ${E(h.name)}<span class="sub">${E(h.players.join(', '))}</span></b><span>${h.wins}–${h.games-h.wins}</span><span class="${h.games>=5&&h.wins/h.games>=.55?'good':h.games>=5&&h.wins/h.games<.45?'bad':''}">${pct(h.wins,h.games)}</span><span><span class="posBadge">${h.primaryPosition?'P'+h.primaryPosition:'—'}</span></span></div>`).join("")||"<span class='sample'>No official hero data.</span>"}</div></div>`}
function deepPanel(ps){const rows=ps.map(p=>{const matches=windowMatches(p);return {p,s:matchSummary(matches),pos:positionSummary(matches).primary}});return `<div class="tableWrap"><table class="tbl"><thead><tr><th>Player</th><th>Role</th><th>Games</th><th>KDA</th><th>GPM</th><th>XPM</th><th>HD/min</th><th>TD/min</th><th>Lane</th><th>Obs/30</th><th>Sen/30</th><th>Dewards/30</th></tr></thead><tbody>${rows.map(({p,s,pos})=>`<tr><td>${E(p.name)}</td><td>${pos?`P${pos.position} ${E(POS[pos.position])}`:'—'}</td><td>${s.games}</td><td>${s.kda==null?'—':s.kda.toFixed(2)}</td><td>${fmt(s.gpm==null?null:Math.round(s.gpm))}</td><td>${fmt(s.xpm==null?null:Math.round(s.xpm))}</td><td>${fmt(s.hdpm)}</td><td>${fmt(s.tdpm)}</td><td>${s.lane==null?'—':s.lane.toFixed(1)+'%'}</td><td>${s.obs30==null?'—':s.obs30.toFixed(1)}</td><td>${s.sen30==null?'—':s.sen30.toFixed(1)}</td><td>${p.deep.dewards30??'—'}</td></tr>`).join("")}</tbody></table></div>`}
function patchPanel(ps){const relevant=[...DATA.patches].reverse().filter(pa=>ps.some(p=>p.matches.some(m=>m.patch===pa.id))).slice(0,12);return `<div class="card section patchRows">${relevant.map(pa=>{const rows=ps.flatMap(p=>p.matches.filter(m=>m.patch===pa.id)),s=matchSummary(rows);return `<div class="patchRow"><b>${E(pa.name)}</b><span>${s.games}<small>games</small></span><span class="${s.wr>=55?'good':s.wr<45?'bad':''}">${s.wr==null?'—':Math.round(s.wr)+'%'}<small>win rate</small></span><span>${s.kda==null?'—':s.kda.toFixed(2)}<small>KDA</small></span></div>`}).join("")||"<span class='sample'>No patch-tagged matches in the cached sample.</span>"}</div>`}
function teamPage(side){
  const label=side==='mine'?'Your Team':'Opponent',pane=state.sub&&(state.sub[side]==="draft"||state.sub[side]==="results"||state.sub[side]==="roles")?state.sub[side]:"players";
  const body=pane==="roles"?teamRoles(side):pane==="draft"?teamDraft(side):pane==="results"?teamResults(side):teamPlayers(side);
  const roster=pane==="players"?`<div class="teamRoster">${setupRoster(side)}</div>`:"";
  return `<div class="singlePage"><div class="teamsetup ${side}" id="setup-${side}">${setupHead(side)}</div><nav class="subnav" aria-label="${label} sections"><button data-team-sub="${side}:players" class="${pane==='players'?'on':''}">Players</button><button data-team-sub="${side}:roles" class="${pane==='roles'?'on':''}">Roles</button><button data-team-sub="${side}:draft" class="${pane==='draft'?'on':''}">Draft</button><button data-team-sub="${side}:results" class="${pane==='results'?'on':''}">Results</button></nav>${roster}${body}</div>`;
}
function focusedPlayer(side){const id=state[side==="mine"?"focusMine":"focusEnemy"],p=byId.get(id);return p&&state[side].includes(p.id)?p:null}
function playerPanel(p,side){const pane=playerPane(state.playerSub&&state.playerSub[side]),body=pane==="standins"?standinsTab(side):pane==="wards"?playerWardsTab(p):pane==="heroes"?playerHeroesTab(p):pane==="esports"?playerEsportsTab(p):pane==="pubs"?playerPubsTab(p):pane==="officials"?playerOfficialsTab(p):playerOverview(p);return `<div class="contentBlock playerProfile">${playerHead(p)}<nav class="subnav" aria-label="${E(p.name)} profile"><button data-player-sub="${side}:overview" class="${pane==='overview'?'on':''}">Overview</button><button data-player-sub="${side}:officials" class="${pane==='officials'?'on':''}">Officials</button><button data-player-sub="${side}:esports" class="${pane==='esports'?'on':''}">Esports</button><button data-player-sub="${side}:pubs" class="${pane==='pubs'?'on':''}">Pubs</button><button data-player-sub="${side}:heroes" class="${pane==='heroes'?'on':''}">Heroes</button><button data-player-sub="${side}:wards" class="${pane==='wards'?'on':''}">Ward maps</button><button data-player-sub="${side}:standins" class="${pane==='standins'?'on':''}">Standins</button></nav>${body}</div>`}
function teamDraftPanel(games){if(!games.length)return "";const bansBy=banSummary(games,true),bansAgainst=banSummary(games,false);return `<div class="contentBlock"><h3>Bans</h3><div class="pageGrid resultsSummary"><div class="card section"><h3>Most banned</h3><div class="heroChipRow">${bansBy.map(h=>heroBanChip(h)).join("")||'<span class="sample">No bans recorded.</span>'}</div></div><div class="card section"><h3>Most banned against them</h3><div class="heroChipRow">${bansAgainst.map(h=>heroBanChip(h)).join("")||'<span class="sample">No bans recorded.</span>'}</div></div></div></div>`}
function teamPlayers(side){const ps=members(side);if(!ps.length)return `<div class="notice">Add a team or pull a player to see the roster breakdown.</div>`;let p=focusedPlayer(side);if(!p){p=ps[0];state[side==="mine"?"focusMine":"focusEnemy"]=p.id}return playerPanel(p,side)}
function teamDraft(side){const key=sideLoadedKey(side),games=key?teamGames(key):[];if(!key)return `<div class="notice">Add a team to see draft analysis.</div>`;if(!games.length)return `<div class="notice">No cached official matches for this team yet.</div>`;return teamSplitPanel(games)+heroMatchupPanel(games,replacedIdsFor(side))+teamDraftPanel(games)}
function officialPosAt(id,matchId){
  const p=byId.get(id);
  const m=p&&p.official&&p.official.matches&&p.official.matches.find(x=>x.match_id===matchId);
  return m&&m.position?m.position:null;
}
function playerOfficialLineups(ps){
  const byMatch=new Map();
  for(const p of ps){
    for(const m of (p.official&&p.official.matches)||[]){
      const e=byMatch.get(m.match_id)||{match_id:m.match_id,win:m.result==="W",players:[]};
      e.players.push({id:p.id,name:p.name,hero_id:m.hero_id});
      byMatch.set(m.match_id,e);
    }
  }
  return [...byMatch.values()].filter(g=>g.players.length>=2);
}
function officialRoleGames(side){
  const key=sideLoadedKey(side);
  if(key){
    const games=teamGames(key);
    if(games.length)return games.map(g=>({match_id:g.m.match_id,win:g.win,players:g.mine.players||[]}));
    return [];
  }
  const ps=members(side);
  return ps.length?playerOfficialLineups(ps):null;
}
function postedIdsFor(side){
  const t=teamByKey(sideLoadedKey(side));
  return new Set((t&&(t.postedRoster||t.roster))||[]);
}
function replacedIdsFor(side){
  const t=teamByKey(sideLoadedKey(side));
  return new Set((t&&t.replaced)||[]);
}
function currentIdsFor(side){
  const t=teamByKey(sideLoadedKey(side));
  if(!t)return new Set();
  const replaced=replacedIdsFor(side);
  const base=(t.roster&&t.roster.length)?t.roster:(t.postedRoster||[]);
  return new Set(base.filter(id=>!replaced.has(id)));
}
function activeRoster(t,otherIds){
  const replaced=new Set((t&&t.replaced)||[]),other=new Set(otherIds||[]);
  return ((t&&t.roster)||[]).filter(id=>!replaced.has(id)&&!other.has(id)).slice(0,5);
}
function bumpRole(map,pos,win){
  const r=map.get(pos)||{position:pos,games:0,wins:0};
  r.games++;if(win)r.wins++;map.set(pos,r);
}
function roleList(map){return [...map.values()].sort((a,b)=>b.games-a.games||a.position-b.position)}
function roleShare(roles,classified){return classified&&roles[0]?roles[0].games/classified:0}
function isCorePos(n){return n===1||n===2||n===3}
function isSupportPos(n){return n===4||n===5}
function teamRoleBreakdown(games,postedIds,replacedIds){
  const counts=new Map();
  for(const g of games)for(const p of g.players||[])if(p.id!=null)counts.set(p.id,(counts.get(p.id)||0)+1);
  const replaced=new Set(replacedIds||[]);
  const posted=postedIds&&postedIds.size?new Set([...postedIds].filter(id=>!replaced.has(id))):new Set([...counts.entries()].filter(x=>!replaced.has(x[0])).sort((a,b)=>b[1]-a[1]).slice(0,5).map(x=>x[0]));
  function hasReplaced(g){return (g.players||[]).some(p=>p.id!=null&&replaced.has(p.id))}
  function hasStandin(g){return (g.players||[]).some(p=>p.id!=null&&!posted.has(p.id)&&!replaced.has(p.id))}
  const currentGames=replaced.size?games.filter(g=>!hasReplaced(g)):games;
  const roleGames=currentGames.length?currentGames:games;
  const eraFallback=!!(replaced.size&&!currentGames.length);
  const byPlayer=new Map();
  function bump(p,pos,win,standin){
    const key=p.id!=null?p.id:p.name;
    if(key==null||key==="")return;
    const e=byPlayer.get(key)||{id:p.id,name:p.name,games:0,classified:0,full:0,standin:0,roles:new Map(),rolesFull:new Map(),rolesStandin:new Map()};
    e.games++;
    if(p.name)e.name=p.name;
    if(standin)e.standin++;else e.full++;
    if(pos){
      e.classified++;
      bumpRole(e.roles,pos,win);
      if(standin)bumpRole(e.rolesStandin,pos,win);else bumpRole(e.rolesFull,pos,win);
    }
    byPlayer.set(key,e);
  }
  const lineups=[],heroes=new Map();
  let standinGames=0;
  for(const g of roleGames){
    const standin=hasStandin(g);
    if(standin)standinGames++;
    const slots=[];
    for(const p of g.players||[]){
      const pos=p.id!=null?officialPosAt(p.id,g.match_id):null;
      if(p.id!=null&&replaced.has(p.id)){
        slots.push({id:p.id,name:p.name,position:pos,hero_id:p.hero_id,standin:false});
        continue;
      }
      bump(p,pos,g.win,standin);
      slots.push({id:p.id,name:p.name,position:pos,hero_id:p.hero_id,standin});
    }
    lineups.push({slots,standin});
  }
  for(const g of games){
    for(const p of g.players||[]){
      if(p.hero_id){
        const h=heroes.get(p.hero_id)||{id:p.hero_id,games:0,wins:0,players:new Map()};
        h.games++;if(g.win)h.wins++;
        const pk=p.id!=null?p.id:p.name,pe=h.players.get(pk)||{id:p.id,name:p.name,games:0};
        pe.games++;if(p.name)pe.name=p.name;h.players.set(pk,pe);
        heroes.set(p.hero_id,h);
      }
      if(p.id!=null&&replaced.has(p.id))bump(p,officialPosAt(p.id,g.match_id),g.win,false);
    }
  }
  const players=[...byPlayer.values()].map(e=>{
    const roles=roleList(e.roles),rolesFull=roleList(e.rolesFull),rolesStandin=roleList(e.rolesStandin);
    const primary=(rolesFull[0]&&e.full>=2?rolesFull[0]:roles[0])||null;
    const classifiedFull=rolesFull.reduce((s,r)=>s+r.games,0),classifiedStandin=rolesStandin.reduce((s,r)=>s+r.games,0);
    const offFull=primary?rolesFull.filter(r=>r.position!==primary.position):[],offStandin=primary?rolesStandin.filter(r=>r.position!==primary.position):[];
    const share=roleShare(primary&&rolesFull[0]&&e.full>=2?rolesFull:roles,primary&&rolesFull[0]&&e.full>=2?classifiedFull:e.classified);
    const flexFull=classifiedFull>=2&&offFull.length>0&&(offFull.reduce((s,r)=>s+r.games,0)>=2||classifiedFull>=3&&share<.8);
    const flexStandin=offStandin.length>0&&offStandin.reduce((s,r)=>s+r.games,0)>=1;
    const supportFlex=primary&&isSupportPos(primary.position)&&roles.some(r=>isSupportPos(r.position)&&r.position!==primary.position&&r.games>=2);
    const core=primary?isCorePos(primary.position):false;
    return {...e,roles,rolesFull,rolesStandin,primary,share,offFull,offStandin,flexFull,flexStandin,supportFlex,core,posted:e.id!=null&&posted.has(e.id),replaced:e.id!=null&&replaced.has(e.id)};
  }).sort((a,b)=>{
    const pa=a.primary?a.primary.position:99,pb=b.primary?b.primary.position:99;
    return pa-pb||b.classified-a.classified||b.games-a.games||String(a.name||"").localeCompare(String(b.name||""));
  });
  const roster=players.filter(p=>p.posted),cores=roster.filter(p=>p.core),supports=roster.filter(p=>p.primary&&isSupportPos(p.primary.position));
  const coreFull=cores.filter(p=>p.flexFull),coreSub=cores.filter(p=>p.flexStandin&&!p.flexFull),supFlex=roster.filter(p=>p.supportFlex);
  let verdict="No classified official positions yet.";
  if(players.some(p=>p.classified&&!p.replaced)){
    if(!roster.some(p=>p.classified>=3)&&!players.filter(p=>!p.replaced).some(p=>p.classified>=3))verdict="Too few official games to know if they flex.";
    else if(coreFull.length)verdict="They flex.";
    else if(supFlex.length&&coreSub.length)verdict="Cores stay on the same roles. They only flex support, and they shuffle when a standin is in.";
    else if(supFlex.length)verdict="Cores stay on the same roles. They only flex support.";
    else if(coreSub.length)verdict="Cores stay on the same roles with the full team. They move around to fit standins.";
    else if(roster.some(p=>p.flexStandin)&&!roster.some(p=>p.flexFull||p.supportFlex))verdict="They stick to set roles with the full team. They shuffle when a standin is in.";
    else verdict="They stick to set roles.";
  }
  const names=new Map(players.filter(p=>p.id!=null).map(p=>[p.id,p.name]));
  const primary=new Map(players.filter(p=>p.id!=null&&p.primary&&!p.replaced).map(p=>[p.id,p.primary.position]));
  const swapMap=new Map(),moveMap=new Map();
  for(const game of lineups){
    const rows=game.slots.filter(s=>s.id!=null&&s.position&&!replaced.has(s.id));
    if(!game.standin){
      for(let i=0;i<rows.length;i++){
        for(let j=i+1;j<rows.length;j++){
          const a=rows[i],b=rows[j],pa=primary.get(a.id),pb=primary.get(b.id);
          if(!pa||!pb||pa===pb)continue;
          if(a.position!==pb||b.position!==pa)continue;
          const id1=a.id<b.id?a.id:b.id,id2=a.id<b.id?b.id:a.id,lo=Math.min(pa,pb),hi=Math.max(pa,pb),key=id1+":"+id2+":"+lo+":"+hi;
          const e=swapMap.get(key)||{id1,id2,lo,hi,games:0};
          e.games++;swapMap.set(key,e);
        }
      }
    }else{
      const standins=rows.filter(s=>!posted.has(s.id));
      const standinNames=[...new Set(standins.map(s=>s.name).filter(Boolean))].sort();
      for(const s of rows){
        if(!posted.has(s.id))continue;
        const pa=primary.get(s.id);
        if(!pa||s.position===pa)continue;
        const key=s.id+":"+s.position+":"+standinNames.join(",");
        const e=moveMap.get(key)||{id:s.id,pos:s.position,standins:standinNames,games:0};
        e.games++;moveMap.set(key,e);
      }
    }
  }
  const swapLines=[...swapMap.values()].sort((a,b)=>b.games-a.games).map(e=>{
    const n1=names.get(e.id1)||"Unknown",n2=names.get(e.id2)||"Unknown";
    return `${n1} and ${n2} swap ${POS[e.lo]} / ${POS[e.hi]} (${e.games} game${e.games===1?"":"s"})`;
  });
  const moveLines=[...moveMap.values()].sort((a,b)=>b.games-a.games).map(e=>{
    const who=names.get(e.id)||"Unknown",role=POS[e.pos]||("P"+e.pos);
    const when=e.standins.length===1?`when ${e.standins[0]} stands in`:"when a standin is in";
    return `${who} plays ${role} ${when} (${e.games} game${e.games===1?"":"s"})`;
  });
  const leftover=supFlex.map(p=>`${p.name}: ${roleMix(p)}`);
  const seen=new Set(),deduped=[];
  for(const line of [...swapLines,...leftover,...moveLines]){
    if(seen.has(line))continue;seen.add(line);deduped.push(line);
  }
  const flexHeroes=[...heroes.values()].filter(h=>h.players.size>1).map(h=>{
    const who=[...h.players.values()].sort((a,b)=>b.games-a.games||String(a.name||"").localeCompare(String(b.name||"")));
    const currentWho=who.filter(p=>p.id!=null&&posted.has(p.id));
    const gone=currentWho.length<2&&who.some(p=>p.id!=null&&replaced.has(p.id));
    return {...h,who,gone};
  }).sort((a,b)=>b.who.length-a.who.length||b.games-a.games||heroName(a.id).localeCompare(heroName(b.id)));
  return {players,posted,verdict,ways:deduped,flexHeroes,games:games.length,standinGames,currentGames:currentGames.length,eraFallback,replacedCount:replaced.size};
}
function roleMix(p){return p.roles.map(r=>`P${r.position} ${POS[r.position]} ${r.games}`).join(" · ")||"unclassified"}
function teamRolesPanel(games,postedIds,replacedIds){
  const d=teamRoleBreakdown(games,postedIds,replacedIds),regulars=d.players.filter(p=>p.posted),gone=d.players.filter(p=>p.replaced),extras=d.players.filter(p=>!p.posted&&!p.replaced);
  const max=Math.max(...regulars.flatMap(p=>p.roles.map(r=>r.games)),1);
  function playerBlock(p,withBars){
    const badge=p.primary?`<span class="posBadge">P${p.primary.position}</span>`:`<span class="posBadge">—</span>`;
    const tag=p.replaced?" · replaced":p.flexFull||p.supportFlex?" · flex":p.flexStandin?" · standin shuffle":"";
    const bars=withBars&&p.roles.length?`<div class="positionBars">${p.roles.map(r=>`<div class="positionRow"><span>P${r.position} ${E(POS[r.position])}</span><div class="track"><div class="fill" style="width:${r.games/max*100}%"></div></div><span class="value">${r.games}g · ${pct(r.wins,r.games)}</span></div>`).join("")}</div>`:"";
    return `<div class="rolePlayer">${badge}<div><b>${E(p.name||"Unknown")}</b><div class="roleMix">${E(roleMix(p))}${tag}</div>${bars}</div></div>`;
  }
  const roster=regulars.map(p=>playerBlock(p,true)).join("")||extras.map(p=>playerBlock(p,true)).join("");
  const goneBody=gone.length?`<div class="contentBlock"><h3>Replaced</h3><div class="roleRoster">${gone.map(p=>playerBlock(p,false)).join("")}</div></div>`:"";
  const extraBody=regulars.length&&extras.length?`<div class="contentBlock"><h3>Standins</h3><div class="roleRoster">${extras.map(p=>playerBlock(p,false)).join("")}</div></div>`:"";
  const ways=d.ways;
  const wayBody=ways.length?`<div class="keysList">${ways.map(x=>`<div class="keyItem"><b>${E(x)}</b></div>`).join("")}</div>`:`<div class="emptyAnalysis">${regulars.length?"Everyone stays on their main role.":"Need more official games to see flex patterns."}</div>`;
  const heroBody=d.flexHeroes.length?`<div class="flexHeroList">${d.flexHeroes.map(h=>`<div class="flexHero${h.gone?' gone':''}">${heroIcon(h.id,32)}<div><b>${E(heroName(h.id))}</b><small>${E(h.who.map(p=>`${p.name} ${p.games}`).join(" · "))}</small></div></div>`).join("")}</div>`:`<div class="emptyAnalysis">No hero has been played by more than one player.</div>`;
  const era=d.replacedCount?(d.eraFallback?"no games since replacement, roles include former players":`${d.currentGames} since replacement`):"";
  const cap=[`${d.games} official game${d.games===1?"":"s"}`,era,d.standinGames?`${d.standinGames} with a standin`:"","positions inferred from lane, hero, and farm"].filter(Boolean).join(" · ");
  return `<div class="card section"><p class="read">${E(d.verdict)}</p><p class="matchupCap">${E(cap)}</p><div class="roleRoster">${roster||'<div class="emptyAnalysis">No players in the official sample.</div>'}</div></div>${goneBody}${extraBody}<div class="contentBlock"><h3>How they flex</h3>${wayBody}</div><div class="contentBlock"><h3>Flex heroes</h3>${heroBody}</div>`;
}
function teamRoles(side){
  const games=officialRoleGames(side);
  if(games==null)return `<div class="notice">Add a team to see official roles.</div>`;
  if(!games.length)return `<div class="notice">No cached official matches for this team yet.</div>`;
  return teamRolesPanel(games,currentIdsFor(side),replacedIdsFor(side));
}
function dayKey(ts){return new Date(ts*1000).toLocaleDateString("en-CA")}
function leagueWeekMap(){
  const days=[...new Set((DATA.teamMatches||[]).map(m=>m.start_time?dayKey(m.start_time):null).filter(Boolean))].sort();
  const map=new Map();let week=0,prev=null;
  for(const day of days){
    const [y,mo,d]=day.split("-").map(Number),n=Date.UTC(y,mo-1,d)/86400000;
    if(prev==null||n-prev>3)week++;
    map.set(day,week);prev=n;
  }
  return map;
}
function seriesWeekLabel(games,weeks){const week=(weeks||leagueWeekMap()).get(dayKey(games[0].m.start_time));return week?`Week ${week}`:"Week —"}
function resultsPlayerId(side){const id=state.resultsPlayer&&state.resultsPlayer[side];return id&&members(side).some(p=>p.id===id)?id:null}
function resultsPlayerList(side){return members(side).map(p=>({id:p.id,name:p.name}))}
function teamResults(side){
  const key=sideLoadedKey(side);if(!key)return `<div class="notice">Add a team to see official games.</div>`;
  const games=teamGames(key),groups=seriesGroups(games),weeks=leagueWeekMap();
  if(!games.length)return `<div class="notice">No cached official matches for this team yet.</div>`;
  const focus=resultsPlayerId(side),players=resultsPlayerList(side);
  const chips=`<div class="resultsFilter ${side}" role="toolbar" aria-label="Filter by player"><b>Player</b>${players.map(p=>`<button type="button" class="chip${focus===p.id?' on':''}" data-results-player="${side}:${p.id}">${E(p.name)}</button>`).join("")}</div>`;
  return `<div class="contentBlock">${chips}<div class="seriesList ${side}${focus?' filtering':''}">${groups.map(g=>seriesCard(g,weeks,focus)).join("")}</div></div>`;
}
const KEY_MIN_GROUP=5,KEY_MIN_GAP=.3,KEY_MAX_BAD_WR=.4,KEY_MIN_GOOD_WR=.55,KEY_MIN_GPM_GAP=60,KEY_LANE_WIN=55,KEY_LANE_LOSS=45,KEY_ALPHA=.05;
const KEY_LANE_ACTION={1:"Win the safelane",2:"Win mid",3:"Win the offlane",4:"Win the offlane",5:"Win the safelane"};
function logFact(n){let s=0;for(let i=2;i<=n;i++)s+=Math.log(i);return s}
function logBinom(n,k){if(k<0||k>n)return -Infinity;return logFact(n)-logFact(k)-logFact(n-k)}
function fisherExact(a,b,c,d){
  if(![a,b,c,d].every(x=>Number.isInteger(x)&&x>=0))return null;
  const n=a+b+c+d;if(!n)return null;
  const row1=a+b,col1=a+c;
  const logp=aa=>logBinom(row1,aa)+logBinom(n-row1,col1-aa)-logBinom(n,col1);
  const logObs=logp(a),lo=Math.max(0,row1+col1-n),hi=Math.min(row1,col1);
  let total=0;
  for(let aa=lo;aa<=hi;aa++){const lp=logp(aa);if(lp<=logObs+1e-9)total+=Math.exp(lp)}
  return Math.min(1,total);
}
function matchLaneResult(m){
  if(m.laneResult==="win"||m.laneResult==="loss"||m.laneResult==="draw")return m.laneResult;
  const e=m.laneEff;if(!Number.isFinite(e))return null;
  if(e>=KEY_LANE_WIN)return "win";if(e<=KEY_LANE_LOSS)return "loss";return "draw";
}
function keyPrimaryPos(rows){
  const counts={};for(const m of rows){if(KEY_LANE_ACTION[m.position])counts[m.position]=(counts[m.position]||0)+1}
  let best=null,n=-1;for(const [pos,c] of Object.entries(counts)){const p=Number(pos);if(c>n||(c===n&&(best==null||p<best))){best=p;n=c}}
  return best;
}
function keyWl(rows){return {w:rows.filter(m=>m.win).length,n:rows.length}}
function keyRecord(w,n){return `${w}–${n-w}`}
function keyPct(w,n){return `${Math.round(w/n*100)}%`}
function keyFmtP(p){return p<0.001?"p < 0.001":`p = ${p.toFixed(3)}`}
function keyRound50(v){return Math.round(v/50)*50}
function keyQualifies(good,bad){
  const g=keyWl(good),b=keyWl(bad);if(g.n<KEY_MIN_GROUP||b.n<KEY_MIN_GROUP)return false;
  const gwr=g.w/g.n,bwr=b.w/b.n;return gwr-bwr>=KEY_MIN_GAP&&bwr<=KEY_MAX_BAD_WR&&gwr>=KEY_MIN_GOOD_WR;
}
function keySplitP(good,bad){const g=keyWl(good),b=keyWl(bad);return fisherExact(g.w,g.n-g.w,b.w,b.n-b.w)}
function keyMedian(a){const s=[...a].sort((x,y)=>x-y),m=Math.floor(s.length/2);return s.length%2?s[m]:(s[m-1]+s[m])/2}
function makeKey(action,reason,p,good,bad,kind,playerId,source){
  const g=keyWl(good),b=keyWl(bad);
  return {action,reason,p,gap:g.w/g.n-b.w/b.n,kind,playerId,source,dedupe:`${playerId}:${kind}`};
}
function laneKey(p,rows,source){
  const won=[],lost=[];for(const m of rows){const o=matchLaneResult(m);if(o==="win")won.push(m);else if(o==="loss")lost.push(m)}
  if(!keyQualifies(won,lost))return null;
  const pv=keySplitP(won,lost);if(pv==null||pv>=KEY_ALPHA)return null;
  const pos=keyPrimaryPos(rows),action=KEY_LANE_ACTION[pos]||`Win ${p.name}'s lane`;
  const w=keyWl(won),l=keyWl(lost);
  const reason=`In ${source}, ${p.name} is ${keyRecord(l.w,l.n)} (${keyPct(l.w,l.n)}) when losing the lane, versus ${keyRecord(w.w,w.n)} (${keyPct(w.w,w.n)}) when winning it (${keyFmtP(pv)}).`;
  return makeKey(action,reason,pv,won,lost,"lane",p.id,source);
}
function gpmKey(p,rows,side,source){
  if([4,5].includes(keyPrimaryPos(rows)))return null;
  const withG=rows.filter(m=>Number.isFinite(m.gpm)),winG=withG.filter(m=>m.win).map(m=>m.gpm),lossG=withG.filter(m=>!m.win).map(m=>m.gpm);
  if(winG.length<KEY_MIN_GROUP||lossG.length<KEY_MIN_GROUP)return null;
  const winMed=keyMedian(winG),lossMed=keyMedian(lossG);if(winMed-lossMed<KEY_MIN_GPM_GAP)return null;
  const cut=keyRound50((winMed+lossMed)/2);if(cut<500||cut>800)return null;
  const high=withG.filter(m=>m.gpm>=cut),low=withG.filter(m=>m.gpm<cut);
  if(!keyQualifies(high,low))return null;
  const pv=keySplitP(high,low);if(pv==null||pv>=KEY_ALPHA)return null;
  const h=keyWl(high),l=keyWl(low);
  const action=side==="enemy"?`Keep ${p.name} under ${cut} GPM`:`Get ${p.name} over ${cut} GPM`;
  const reason=`In ${source}, ${p.name} is ${keyRecord(l.w,l.n)} (${keyPct(l.w,l.n)}) below ${cut} GPM, versus ${keyRecord(h.w,h.n)} (${keyPct(h.w,h.n)}) at ${cut}+ (${keyFmtP(pv)}).`;
  return makeKey(action,reason,pv,high,low,"gpm",p.id,source);
}
function playerKeys(p,rows,side,source){
  const out=[];
  const lane=laneKey(p,rows,source);if(lane)out.push(lane);
  const g=gpmKey(p,rows,side,source);if(g)out.push(g);
  return out;
}
function collectKeys(ps,side){
  const out=[],replaced=replacedIdsFor(side);
  for(const p of ps){
    if(replaced.has(p.id))continue;
    const off=officialRows(p);if(off.length)out.push(...playerKeys(p,off,side,"LD2L officials"));
  }
  return out;
}
function mergeKeys(keys){
  const gpm=keys.filter(k=>k.kind==="gpm").sort((a,b)=>a.p-b.p||b.gap-a.gap).slice(0,2);
  const rest=keys.filter(k=>k.kind!=="gpm").concat(gpm);
  const map=new Map();
  for(const k of rest){
    const cur=map.get(k.action);
    if(!cur){map.set(k.action,{action:k.action,reasons:[k.reason],p:k.p,gap:k.gap});continue}
    cur.reasons.push(k.reason);cur.p=Math.min(cur.p,k.p);cur.gap=Math.max(cur.gap,k.gap);
  }
  return [...map.values()].sort((a,b)=>a.p-b.p||b.gap-a.gap);
}
function keysPanel(mine,enemy){
  const keys=mergeKeys([...collectKeys(mine,"mine"),...collectKeys(enemy,"enemy")]).slice(0,8);
  const list=keys.length?`<div class="keysList">${keys.map(k=>`<article class="keyItem"><b>${E(k.action)}</b><p>${E(k.reasons.join(" "))}</p></article>`).join("")}`:`<div class="emptyAnalysis">No statistically significant keys in this official sample.</div>`;
  return `<div class="contentBlock"><h3>Keys to victory</h3><details class="method"><summary>How this is calculated</summary><p class="matchupCap">Drawn from cached LD2L official matches. Only splits that survive a two-sided Fisher exact test at p under 0.05, with at least 5 games on each side, a 30-point win-rate gap, and a losing record on the bad side. Empty means nothing cleared the bar. GPM cuts are associations — gold also rises after winning.</p></details>${list}</div>`;
}
// Lotus is an LD2L-only theme. The saved choice is kept while another league is open, so switching
// back to LD2L restores it; elsewhere the page shows Sports and the Lotus button is hidden.
let themeChoice=(()=>{try{const s=localStorage.getItem("team-scout:theme");if(THEME_COLORS[s])return s}catch(e){}return THEME_COLORS[document.documentElement.dataset.theme]?document.documentElement.dataset.theme:"sports"})();
function lotusAllowed(){return activeLeague==="ld2l"}
function currentTheme(){const t=document.documentElement.dataset.theme;return THEME_COLORS[t]?t:"sports"}
function paintTheme(){const t=currentTheme(),m=document.querySelector('meta[name="theme-color"]');if(m)m.content=THEME_COLORS[t];document.querySelectorAll(".themeSwitch button").forEach(b=>{b.hidden=b.dataset.theme==="lotus"&&!lotusAllowed();b.setAttribute("aria-pressed",String(b.dataset.theme===t))})}
// The head script runs before DATA exists, so it reads the league from this fixed key to avoid a
// Lotus flash on RD2L loads.
function applyTheme(){try{localStorage.setItem("team-scout:theme-league",activeLeague)}catch(e){}document.documentElement.dataset.theme=themeChoice==="lotus"&&!lotusAllowed()?"sports":themeChoice;paintTheme()}
function setTheme(t){t=THEME_COLORS[t]?t:"sports";if(t==="lotus"&&!lotusAllowed())return;themeChoice=t;try{localStorage.setItem("team-scout:theme",t)}catch(e){}applyTheme();render()}
function scorebugSide(side){const ps=members(side),t=teamByKey(sideLoadedKey(side)),games=ps.reduce((s,p)=>s+p.official.games,0),wins=ps.reduce((s,p)=>s+p.official.wins,0),rec=t&&t.record?String(t.record).replace(/\s*-\s*/,"–"):(games?`${wins}–${games-wins}`:"");const cap=t&&t.captain;const theme=currentTheme(),meta=theme==="military"?`${side==="mine"?"Friendly":"Hostile"}${cap?`, commanded by ${E(cap)}`:""}`:theme==="lotus"?`${side==="mine"?"Allied fleet":"Enemy fleet"}${cap?`, Commander ${E(cap)}`:""}`:(cap?`Captain ${E(cap)}`:(side==="mine"?"Your team":"Opponent"));return `<div class="sbSide ${side}"><div style="min-width:0"><div class="sbName">${E(state[side+"Name"])}</div><span class="sbMeta">${meta}</span></div>${rec?`<div class="sbRec">${E(rec)}</div>`:""}</div>`}
function scorebugContext(){const a=sideLoadedKey("mine"),b=sideLoadedKey("enemy");if(!a||!b)return "";const fixture=(DATA.matchups||[]).find(m=>(m.aKey===a&&m.bKey===b)||(m.aKey===b&&m.bKey===a));const games=(DATA.teamMatches||[]).filter(m=>{const k=[m.radiant.team_key,m.dire.team_key];return k.includes(a)&&k.includes(b)});const won=games.filter(m=>(m.radiant.team_key===a)===!!m.radiant_win).length;const h2h=games.length?`This season: ${E(state.mineName)} ${won}–${games.length-won} in games`:"First meeting this season";return `<div class="sbContext">${fixture?`<b>Week ${E(fixture.week)}</b>`:""}<span>${h2h}</span></div>`}
function scorebug(){return `<section class="scorebug" aria-label="Matchup">${scorebugSide("mine")}<div class="sbMid" aria-hidden="true"></div>${scorebugSide("enemy")}${scorebugContext()}</section>`}
function matchupPage(){const mine=members('mine'),enemy=members('enemy');return `${mine.length&&enemy.length?scorebug():''}<div class="mirror"><div class="side mine">${overview('mine')}</div><div class="side enemy">${overview('enemy')}</div></div>${mine.length&&enemy.length?`${keysPanel(mine,enemy)}<div class="contentBlock"><h3>Wins / losses</h3><div class="mirror"><div class="side mine">${winLossPanel(mine.flatMap(p=>officialRows(p)),state.mineName)}</div><div class="side enemy">${winLossPanel(enemy.flatMap(p=>officialRows(p)),state.enemyName)}</div></div></div><div class="contentBlock"><h3>Heroes</h3><div class="mirror"><div class="side mine">${heroPanel(mine)}</div><div class="side enemy">${heroPanel(enemy)}</div></div></div><div class="contentBlock"><h3>Roles</h3><div class="mirror"><div class="side mine">${teamRoles('mine')}</div><div class="side enemy">${teamRoles('enemy')}</div></div></div>`:''}`}
function standingsTable(rows){
  const mineKey=sideLoadedKey("mine"),enemyKey=sideLoadedKey("enemy");
  return `<div class="tableWrap"><table class="tbl standingsTbl"><thead><tr><th>Team</th><th>#</th><th>W-L</th><th></th></tr></thead><tbody>${rows.map(r=>{
    const cls=r.key===mineKey?"rowMine":r.key===enemyKey?"rowEnemy":"",gold=r.rank<=4?'<span class="rankGold" title="Top 4">★</span>':'';
    return `<tr class="${cls}"><td class="standingsWho" title="${E(r.name)}"><b>${E(r.short)}</b><span class="sub">${E(r.captain||'—')}</span></td><td>${gold}${r.rank}</td><td>${r.wins}-${r.losses}</td><td class="standingsActions"><button data-standings-opponent="${E(r.key)}">Set as opponent</button><button data-standings-results="${E(r.key)}">Results</button></td></tr>`;
  }).join("")||`<tr><td colspan="4">No standings available.</td></tr>`}</tbody></table></div>`;
}
function matchupSlate(slate, heading){
  if(!slate.length)return `<div class="notice">No upcoming matchups yet.</div>`;
  const all=DATA.matchups||[];
  const mineKey=sideLoadedKey("mine"),enemyKey=sideLoadedKey("enemy");
  return `<div class="contentBlock"><h3>${E(heading)}</h3><div class="matchupSlate">${slate.map(m=>{
    const i=all.indexOf(m);
    return `<button class="slateRow" data-open-matchup="${i}"><span class="${m.aKey===mineKey||m.aKey===enemyKey?'onSide':''}">${E(m.aShort)}</span><span class="slateVs">vs</span><span class="${m.bKey===mineKey||m.bKey===enemyKey?'onSide':''}">${E(m.bShort)}</span></button>`;
  }).join("")}</div></div>`;
}
function standingsPage(){
  const rows=DATA.standings||[];
  const fallback=DATA.officialSource&&DATA.officialSource.league;
  const leagues=leaguesOf(rows, fallback);
  const week=DATA.officialSource&&DATA.officialSource.week;
  const heading=week?`Week ${week} matchups`:"This week's matchups";
  if(leagues.length<2){
    return `<div class="singlePage">${matchupSlate(DATA.matchups||[], heading)}${standingsTable(rows)}</div>`;
  }
  const blocks=leagues.map(league=>{
    const group=rows.filter(r=>(r.league||fallback)===league);
    const slate=(DATA.matchups||[]).filter(m=>(m.league||fallback)===league);
    return `<div class="contentBlock"><h2>${E(league)}</h2>${matchupSlate(slate, "This week's matchups")}${standingsTable(group)}</div>`;
  }).join("");
  return `<div class="singlePage">${blocks}</div>`;
}
function teamGames(key){
  return (DATA.teamMatches||[]).filter(m=>m.radiant.team_key===key||m.dire.team_key===key).map(m=>{
    const isRadiant=m.radiant.team_key===key,mine=isRadiant?m.radiant:m.dire,opp=isRadiant?m.dire:m.radiant,win=isRadiant?m.radiant_win:!m.radiant_win;
    return {m,isRadiant,mine,opp,win};
  }).sort((a,b)=>b.m.start_time-a.m.start_time);
}
function firstPickSide(m){
  const picks=(m.picks_bans||[]).map((x,i)=>({team:x.team,order:x.order??i,is_pick:x.is_pick})).filter(x=>x.is_pick);
  picks.sort((a,b)=>a.order-b.order);
  return picks.length?picks[0].team:null;
}
function splitBucket(){return {games:0,wins:0}}
function teamSplitStats(games){
  const out={first:splitBucket(),second:splitBucket(),radiant:splitBucket(),dire:splitBucket()};
  for(const g of games){
    const side=g.isRadiant?out.radiant:out.dire;
    side.games++;if(g.win)side.wins++;
    const fp=firstPickSide(g.m);
    if(fp==null)continue;
    const pick=(g.isRadiant?0:1)===fp?out.first:out.second;
    pick.games++;if(g.win)pick.wins++;
  }
  return out;
}
function splitLabel(b){return b.games?`${b.wins}-${b.games-b.wins} · ${Math.round(b.wins/b.games*100)}%`:"—"}
function splitClass(b){if(!b.games)return "";const wr=b.wins/b.games*100;return wr>=55?"good":wr<45?"bad":""}
function splitCell(b){return `<td class="${splitClass(b)}">${splitLabel(b)}</td>`}
function splitMetric(label,b,emptyNote){return `<div class="metric"><span>${E(label)}</span><b class="${splitClass(b)}">${splitLabel(b)}</b><small>${b.games?`${b.games} games`:E(emptyNote)}</small></div>`}
function teamSplitPanel(games){
  const s=teamSplitStats(games);
  return `<div class="metrics detailMetrics">${splitMetric("First pick",s.first,"no draft data")}${splitMetric("Second pick",s.second,"no draft data")}${splitMetric("Radiant",s.radiant,"no sample")}${splitMetric("Dire",s.dire,"no sample")}</div>`;
}
function leagueSideSplits(){
  const matches=DATA.teamMatches||[],radiant={games:matches.length,wins:matches.filter(m=>m.radiant_win).length},first=splitBucket();
  for(const m of matches){
    const fp=firstPickSide(m);
    if(fp==null)continue;
    first.games++;
    if(fp===0?m.radiant_win:!m.radiant_win)first.wins++;
  }
  return {first,radiant};
}
function leagueTeamSplits(){
  const rows=DATA.standings&&DATA.standings.length?DATA.standings:DATA.teams||[];
  return rows.map(t=>{
    const games=teamGames(t.key);
    return {t,games:games.length,wins:games.filter(g=>g.win).length,s:teamSplitStats(games)};
  });
}
function seriesGroups(games){
  const groups=new Map();
  for(const g of games){
    // LD2L games get a fresh Dota series_id per lobby, so a Bo2 is the same opponent on the same local day.
    const day=new Date(g.m.start_time*1000).toLocaleDateString('en-CA'),key=`d:${g.opp.team_key||g.opp.name}:${day}`;
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(g);
  }
  return [...groups.values()].map(list=>list.sort((a,b)=>a.m.start_time-b.m.start_time))
    .sort((a,b)=>Math.max(...b.map(x=>x.m.start_time))-Math.max(...a.map(x=>x.m.start_time)));
}
function officialSeriesGroups(matches){
  const groups=new Map();
  for(const m of matches||[]){
    const day=m.start_time?dayKey(m.start_time):"?",key=`d:${m.opponent_key||m.opponent||"?"}:${day}`;
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(m);
  }
  return [...groups.values()].map(list=>list.sort((a,b)=>(a.start_time||0)-(b.start_time||0)))
    .sort((a,b)=>Math.max(...b.map(x=>x.start_time||0))-Math.max(...a.map(x=>x.start_time||0)));
}
function officialMatchNumber(p,m,fallback){
  const g=teamGameForPlayerMatch(p,m.match_id);
  if(g&&g.mine.team_key){
    const groups=seriesGroups(teamGames(g.mine.team_key));
    for(const list of groups){
      const i=list.findIndex(x=>x.m.match_id===m.match_id);
      if(i>=0)return i+1;
    }
  }
  return fallback;
}
function officialSeriesList(p){
  const rows=(p.official&&p.official.matches)||[];
  if(!rows.length)return `<div class="notice">No cached LD2L official matches found.</div>`;
  const weeks=leagueWeekMap();
  return `<div class="seriesList">${officialSeriesGroups(rows).map(list=>officialSeriesCard(p,list,weeks)).join("")}</div>`;
}
function officialSeriesCard(p,matches,weeks){
  const m0=matches[0],opp=captainLabel(m0.opponent,m0.opponent_key);
  const w=matches.filter(m=>m.result==="W").length,l=matches.length-w,cls=w>l?"good":l>w?"bad":"";
  const week=m0.start_time?(weeks||leagueWeekMap()).get(dayKey(m0.start_time)):null;
  const label=week?`Week ${week}`:"Week —";
  return `<div class="card section seriesCard"><div class="seriesHead"><span class="seriesDate">${E(label)}</span><span class="seriesOpp">vs <b title="${E(m0.opponent||opp)}">${E(opp)}</b></span><span class="seriesScore ${cls}">${w}-${l}</span></div><div class="tableWrap"><table class="tbl"><thead><tr><th>Match</th><th class="heroCol">Hero</th><th>Position</th><th>Result</th><th>K/D/A</th><th>GPM</th><th>XPM</th><th>LH/DN</th><th>Net worth</th><th>Hero dmg</th><th>Tower dmg</th><th>Lane eff</th><th>Obs</th><th>Sen</th><th>Dewards</th></tr></thead><tbody>${matches.map((m,i)=>officialMatchRows(p,m,officialMatchNumber(p,m,i+1))).join("")}</tbody></table></div></div>`;
}
function banSummary(games,byThisTeam,firstOnly=false){
  const map=new Map();
  for(const g of games){
    const myTeamNum=g.isRadiant?0:1;
    for(const pb of (g.m.picks_bans||[])){
      if(pb.is_pick)continue;
      if((pb.team===myTeamNum)!==byThisTeam)continue;
      if(firstOnly&&(pb.order??99)>=4)continue;
      const e=map.get(pb.hero_id)||{id:pb.hero_id,count:0};
      e.count++;map.set(pb.hero_id,e);
    }
  }
  return [...map.values()].sort((a,b)=>b.count-a.count).slice(0,8);
}
function bumpHero(map,id,g,p,ours){
  const e=map.get(id)||{id,games:0,wins:0,kills:0,deaths:0,assists:0,gpmSum:0,gpmN:0,laneSum:0,laneN:0,winLaneSum:0,winLaneN:0,winGpmSum:0,winGpmN:0,winKills:0,winDeaths:0,winAssists:0,winN:0,lossLaneSum:0,lossLaneN:0,lossGpmSum:0,lossGpmN:0,lossKills:0,lossDeaths:0,lossAssists:0,lossN:0,players:{},playerIds:{}};
  e.games++;if(g.win)e.wins++;
  e.kills+=p.kills||0;e.deaths+=p.deaths||0;e.assists+=p.assists||0;
  if(Number.isFinite(p.gpm)){e.gpmSum+=p.gpm;e.gpmN++}
  if(Number.isFinite(p.lane_eff)){e.laneSum+=p.lane_eff;e.laneN++}
  if(g.win&&!ours){
    e.winN++;
    e.winKills+=p.kills||0;e.winDeaths+=p.deaths||0;e.winAssists+=p.assists||0;
    if(Number.isFinite(p.lane_eff)){e.winLaneSum+=p.lane_eff;e.winLaneN++}
    if(Number.isFinite(p.gpm)){e.winGpmSum+=p.gpm;e.winGpmN++}
  }
  if(!g.win&&ours){
    e.lossN++;
    e.lossKills+=p.kills||0;e.lossDeaths+=p.deaths||0;e.lossAssists+=p.assists||0;
    if(Number.isFinite(p.lane_eff)){e.lossLaneSum+=p.lane_eff;e.lossLaneN++}
    if(Number.isFinite(p.gpm)){e.lossGpmSum+=p.gpm;e.lossGpmN++}
  }
  if(ours){
    if(p.name)e.players[p.name]=(e.players[p.name]||0)+1;
    if(p.id!=null)e.playerIds[p.id]=(e.playerIds[p.id]||0)+1;
  }
  map.set(id,e);
}
function finalizeHero(e,replacedIds){
  const ids=Object.keys(e.playerIds||{}).map(Number);
  const gone=!!(replacedIds&&replacedIds.size&&ids.length&&ids.every(id=>replacedIds.has(id)));
  const ci=wilson(e.wins,e.games);
  return {
    id:e.id,games:e.games,wins:e.wins,losses:e.games-e.wins,
    wr:e.games?e.wins/e.games*100:0,kda:e.games?((e.kills+e.assists)/Math.max(e.deaths,1)):null,
    gpm:e.gpmN?e.gpmSum/e.gpmN:null,lane:e.laneN?e.laneSum/e.laneN:null,
    winLane:e.winLaneN?e.winLaneSum/e.winLaneN:null,
    winGpm:e.winGpmN?e.winGpmSum/e.winGpmN:null,
    winKda:e.winN?((e.winKills+e.winAssists)/Math.max(e.winDeaths,1)):null,
    lossLane:e.lossLaneN?e.lossLaneSum/e.lossLaneN:null,
    lossGpm:e.lossGpmN?e.lossGpmSum/e.lossGpmN:null,
    lossKda:e.lossN?((e.lossKills+e.lossAssists)/Math.max(e.lossDeaths,1)):null,
    players:Object.entries(e.players||{}).sort((a,b)=>b[1]-a[1]).map(x=>x[0]),
    score:ci?ci[0]:0,gone
  };
}
function teamHeroMatchups(games,replacedIds){
  const ours=new Map(),faced=new Map(),teamN=games.length,teamW=games.filter(g=>g.win).length,teamWR=teamN?teamW/teamN*100:0;
  for(const g of games){
    for(const p of g.mine.players||[])if(p.hero_id)bumpHero(ours,p.hero_id,g,p,true);
    for(const p of g.opp.players||[])if(p.hero_id)bumpHero(faced,p.hero_id,g,p,false);
  }
  const forUs=[...ours.values()].map(e=>finalizeHero(e,replacedIds)).sort((a,b)=>b.score-a.score||b.games-a.games||b.wr-a.wr);
  const against=[...faced.values()].map(e=>finalizeHero(e,replacedIds)).sort((a,b)=>b.score-a.score||b.games-a.games||b.wr-a.wr);
  const struggle=against.map(h=>{
    const delta=h.wr-teamWR;
    const uglyLane=h.wins>0&&h.winLane!=null&&h.winLane>=58;
    const uglyGpm=h.wins>0&&h.winGpm!=null&&h.winGpm>=520;
    const uglyKda=h.wins>0&&h.winKda!=null&&h.winKda>=6;
    const ugly=uglyLane||uglyGpm||uglyKda;
    let note="";
    if(h.wins===0)note="Unbeaten vs you";
    else if(delta<=-8)note=`${Math.round(-delta)} pts below team WR`;
    else if(uglyLane)note=`Won, they still ${Math.round(h.winLane)}% lane`;
    else if(uglyGpm)note=`Won, they still ${Math.round(h.winGpm)} GPM`;
    else if(uglyKda)note=`Won, they still ${h.winKda.toFixed(1)} KDA`;
    const weight=(h.wins===0?30:0)+Math.max(0,-delta)+(ugly?12:0)+(h.games>=2?8:0);
    return {...h,delta,ugly,note,weight};
  }).filter(h=>h.games>=2&&(h.wins===0||h.delta<=-8||h.ugly)).sort((a,b)=>b.weight-a.weight||a.wr-b.wr||b.games-a.games);
  const good=forUs.map(h=>{
    const delta=h.wr-teamWR;
    const strongLane=h.losses>0&&h.lossLane!=null&&h.lossLane>=58;
    const strongGpm=h.losses>0&&h.lossGpm!=null&&h.lossGpm>=520;
    const strongKda=h.losses>0&&h.lossKda!=null&&h.lossKda>=6;
    const strong=strongLane||strongGpm||strongKda;
    let note="";
    if(h.losses===0)note="Unbeaten on this";
    else if(delta>=8)note=`${Math.round(delta)} pts above team WR`;
    else if(strongLane)note=`Lost, you still ${Math.round(h.lossLane)}% lane`;
    else if(strongGpm)note=`Lost, you still ${Math.round(h.lossGpm)} GPM`;
    else if(strongKda)note=`Lost, you still ${h.lossKda.toFixed(1)} KDA`;
    const weight=(h.losses===0?30:0)+Math.max(0,delta)+(strong?12:0)+(h.games>=2?8:0);
    return {...h,delta,strong,note,weight};
  }).filter(h=>h.games>=2&&(h.losses===0||h.delta>=8||h.strong)).sort((a,b)=>b.weight-a.weight||b.wr-a.wr||b.games-a.games);
  const take=(rows,minG)=>{
    const hit=rows.filter(h=>h.games>=minG);
    return (hit.length>=4?hit:rows).slice(0,8);
  };
  const forUsTake=take(forUs,2);
  const seen=new Set(forUsTake.map(h=>h.id));
  const goneExtra=forUs.filter(h=>h.gone&&!seen.has(h.id));
  return {teamWR,forUs:forUsTake.concat(goneExtra),against:take(against,2),good:good.slice(0,8),struggle:struggle.slice(0,8)};
}
function matchupHeroCell(h){const who=(h.players||[]).slice(0,2).join(", ");return `${heroIcon(h.id,20)} ${E(heroName(h.id))}${who?`<span class="matchupWho">${E((h.gone?"Former · ":"")+who)}</span>`:''}`}
function wrCell(wr){return `<td class="${wr>=60?'good':wr<45?'bad':''}">${Math.round(wr)}%</td>`}
function numCell(v,d,suf){return `<td>${v==null?'—':Number(v).toFixed(d)}${v==null?'':suf||''}</td>`}
function heroMatchupPanel(games,replacedIds){
  if(!games.length)return "";
  const m=teamHeroMatchups(games,replacedIds);
  const forRow=h=>`<tr><td class="${h.gone?'goneHeroName':''}" title="${h.gone?'Won with this; that player is no longer on the team':''}">${matchupHeroCell(h)}</td><td>${h.games}</td><td>${h.wins}-${h.losses}</td>${wrCell(h.wr)}${numCell(h.kda,1)}${numCell(h.lane,0,'%')}${numCell(h.gpm,0)}</tr>`;
  const vsRow=h=>`<tr><td>${matchupHeroCell(h)}</td><td>${h.games}</td><td>${h.wins}-${h.losses}</td>${wrCell(h.wr)}${numCell(h.kda,1)}${numCell(h.lane,0,'%')}${numCell(h.gpm,0)}</tr>`;
  const stRow=h=>{
    const inn=h.wins?[h.winLane!=null?`${Math.round(h.winLane)}% lane`:null,h.winGpm!=null?`${Math.round(h.winGpm)} GPM`:null,h.winKda!=null?`${h.winKda.toFixed(1)} KDA`:null].filter(Boolean).join(" · "):"—";
    return `<tr><td>${matchupHeroCell(h)}</td><td>${h.games}</td><td>${h.wins}-${h.losses}</td>${wrCell(h.wr)}<td>${inn||"—"}</td><td class="matchupNote">${E(h.note||'')}</td></tr>`;
  };
  const goodRow=h=>{
    const inn=h.losses?[h.lossLane!=null?`${Math.round(h.lossLane)}% lane`:null,h.lossGpm!=null?`${Math.round(h.lossGpm)} GPM`:null,h.lossKda!=null?`${h.lossKda.toFixed(1)} KDA`:null].filter(Boolean).join(" · "):"—";
    return `<tr><td>${matchupHeroCell(h)}</td><td>${h.games}</td><td>${h.wins}-${h.losses}</td>${wrCell(h.wr)}<td>${inn||"—"}</td><td class="matchupNote">${E(h.note||'')}</td></tr>`;
  };
  const goneNote=replacedIds&&replacedIds.size?" Heroes only a replaced player used stay listed, struck through. Good with still counts those games.":"";
  return `<div class="contentBlock"><h3>Official hero matchups</h3><details class="method"><summary>How this is calculated</summary><p class="matchupCap">Ranked by Wilson win rate, not raw WR. Good with / Struggle flag 2+ game samples: unbeaten, 8+ pts off team WR, or still stomping in the other result (lane ≥58%, 520+ GPM, or 6+ KDA).${goneNote}</p></details><div class="pageGrid"><div class="card section"><h3>Most successful for</h3><div class="tableWrap"><table class="tbl matchupTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th><th>KDA</th><th>Lane</th><th>GPM</th></tr></thead><tbody>${m.forUs.map(forRow).join("")||"<tr><td colspan='7'>No pick data.</td></tr>"}</tbody></table></div></div><div class="card section"><h3>Most successful against</h3><div class="tableWrap"><table class="tbl matchupTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th><th>KDA</th><th>Lane</th><th>GPM</th></tr></thead><tbody>${m.against.map(vsRow).join("")||"<tr><td colspan='7'>No matchup data.</td></tr>"}</tbody></table></div></div></div><div class="pageGrid" style="margin-top:16px"><div class="card section"><h3>Good with</h3><div class="tableWrap"><table class="tbl matchupTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th><th>In your losses</th><th>Why</th></tr></thead><tbody>${m.good.map(goodRow).join("")||"<tr><td colspan='6'>No repeating comfort heroes yet.</td></tr>"}</tbody></table></div></div><div class="card section"><h3>Struggle against</h3><div class="tableWrap"><table class="tbl matchupTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th><th>In your wins</th><th>Why</th></tr></thead><tbody>${m.struggle.map(stRow).join("")||"<tr><td colspan='6'>No repeating problem heroes yet.</td></tr>"}</tbody></table></div></div></div></div>`;
}
function heroBanChip(h){return `<span class="heroChip">${heroIcon(h.id,28,true)}<b>${E(heroName(h.id))}</b><small>${h.count}</small></span>`}
function seasonHeroRecords(){
  const map=new Map();
  for(const m of (DATA.teamMatches||[])){
    for(const side of [m.radiant,m.dire]){
      const won=side===m.radiant?m.radiant_win:!m.radiant_win;
      for(const p of (side.players||[])){
        if(!p.hero_id)continue;
        const e=map.get(p.hero_id)||{id:p.hero_id,games:0,wins:0};
        e.games++;if(won)e.wins++;map.set(p.hero_id,e);
      }
    }
  }
  return [...map.values()].map(h=>({...h,wr:h.games?h.wins/h.games*100:0}));
}
function seasonBanRecords(){
  const matches=DATA.teamMatches||[],matchCount=matches.length;
  const map=new Map();
  for(const m of matches){
    for(const pb of (m.picks_bans||[])){
      if(pb.is_pick)continue;
      const e=map.get(pb.hero_id)||{id:pb.hero_id,count:0,first:0};
      e.count++;if((pb.order??99)<4)e.first++;map.set(pb.hero_id,e);
    }
  }
  return [...map.values()].map(e=>({...e,rate:matchCount?e.count/matchCount:0})).sort((a,b)=>b.count-a.count);
}
function leaguePage(){
  const matches=DATA.teamMatches||[];
  if(!matches.length)return `<div class="singlePage"><div class="notice">No official games in cache.</div></div>`;
  const heroRecs=seasonHeroRecords(),banRecs=seasonBanRecords(),matchCount=matches.length;
  const qualified=heroRecs.filter(h=>h.games>=3);
  const topWR=[...qualified].sort((a,b)=>b.wr-a.wr||b.games-a.games).slice(0,12);
  const botWR=[...qualified].sort((a,b)=>a.wr-b.wr||b.games-a.games).slice(0,12);
  const topBans=banRecs.slice(0,12);
  const firstBans=[...banRecs].filter(h=>h.first>0).sort((a,b)=>b.first-a.first||b.count-a.count).slice(0,12);
  const uniqueHeroes=heroRecs.length,uniqueBans=new Set(banRecs.map(b=>b.id)).size;
  const leagueSplits=leagueSideSplits(),teamSplits=leagueTeamSplits();
  const mineKey=sideLoadedKey("mine"),enemyKey=sideLoadedKey("enemy");
  function heroWRRow(h){return `<tr><td>${heroIcon(h.id,20)} ${E(heroName(h.id))}</td><td>${h.games}</td><td>${h.wins}-${h.games-h.wins}</td><td class="${h.wr>=55?'good':h.wr<45?'bad':''}">${Math.round(h.wr)}%</td></tr>`}
  function banRow(h){return `<tr><td>${heroIcon(h.id,20,true)} ${E(heroName(h.id))}</td><td>${h.count}</td><td>${h.first}</td><td>${(h.rate*100).toFixed(0)}%</td></tr>`}
  function teamSplitRow(r){
    const cls=r.t.key===mineKey?"rowMine":r.t.key===enemyKey?"rowEnemy":"";
    return `<tr class="${cls}"><td title="${E(r.t.name)}"><b>${E(r.t.short||r.t.name)}</b></td><td>${r.games}</td><td>${r.wins}-${r.games-r.wins}</td>${splitCell(r.s.first)}${splitCell(r.s.second)}${splitCell(r.s.radiant)}${splitCell(r.s.dire)}</tr>`;
  }
  return `<div class="singlePage"><div class="metrics detailMetrics"><div class="metric"><span>Official games</span><b>${matchCount}</b></div><div class="metric"><span>Unique heroes</span><b>${uniqueHeroes}</b></div><div class="metric"><span>Unique bans</span><b>${uniqueBans}</b></div>${splitMetric("First pick",leagueSplits.first,"no draft data")}${splitMetric("Radiant",leagueSplits.radiant,"no sample")}</div><div class="contentBlock"><h3>All teams</h3><div class="tableWrap"><table class="tbl leagueTbl"><thead><tr><th>Team</th><th>G</th><th>W-L</th><th>First pick</th><th>Second pick</th><th>Radiant</th><th>Dire</th></tr></thead><tbody>${teamSplits.map(teamSplitRow).join("")||"<tr><td colspan='7'>No teams.</td></tr>"}</tbody></table></div></div><div class="contentBlock pageGrid"><div><div class="contentBlock"><h3>Highest win rate</h3><div class="tableWrap"><table class="tbl leagueTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th></tr></thead><tbody>${topWR.map(heroWRRow).join("")||"<tr><td colspan='4'>No hero data.</td></tr>"}</tbody></table></div></div></div><div><div class="contentBlock"><h3>Lowest win rate</h3><div class="tableWrap"><table class="tbl leagueTbl"><thead><tr><th>Hero</th><th>G</th><th>W-L</th><th>WR</th></tr></thead><tbody>${botWR.map(heroWRRow).join("")||"<tr><td colspan='4'>No hero data.</td></tr>"}</tbody></table></div></div></div></div><div class="contentBlock pageGrid"><div><div class="contentBlock"><h3>Most banned</h3><div class="tableWrap"><table class="tbl leagueTbl"><thead><tr><th>Hero</th><th>Bans</th><th>First</th><th>% games</th></tr></thead><tbody>${topBans.map(banRow).join("")||"<tr><td colspan='4'>No ban data.</td></tr>"}</tbody></table></div></div></div><div><div class="contentBlock"><h3>First bans</h3><div class="tableWrap"><table class="tbl leagueTbl"><thead><tr><th>Hero</th><th>Bans</th><th>First</th><th>% games</th></tr></thead><tbody>${firstBans.map(banRow).join("")||"<tr><td colspan='4'>No ban data.</td></tr>"}</tbody></table></div></div></div></div></div>`
}
function laneWithResult(eff,won){const lane=eff==null||eff===""?"—":`${Number(eff).toFixed(1)}%`;const cls=won?"good":"bad";const mark=won?"W":"L";return `${lane} <b class="${cls}">${mark}</b>`}
function wardPair(p){const o=p.obs,s=p.sen;if(o==null&&s==null)return null;return {name:p.name,o:o||0,s:s||0,total:(o||0)+(s||0)}}
function visionItems(players){const rows=players.map(wardPair).filter(x=>x&&x.total>0).sort((a,b)=>b.s-a.s||b.o-a.o||a.name.localeCompare(b.name));return rows.map(x=>`<span>${E(cellName(x.name)||x.name)} <b>${x.o}/${x.s}</b></span>`).join("")}
function visionLine(players){const items=visionItems(players);return items?`<div class="draftLine"><span class="draftLabel">Ward maps</span>${items}</div>`:""}
const WARD_MAP_SRC="https://www.opendota.com/assets/images/dota2/map/detailed_740.jpg";
function wardPatchId(){const p=(DATA.patches||[]).find(x=>String(x.name)==="7.41");return p?p.id:60}
function isWardPatch(patch){return Number(patch)===Number(wardPatchId())}
function wardPct(x,y){return {l:((x-64)/128)*100,t:(1-(y-64)/128)*100}}
function clusterWards(pts){
  const bin=5,map=new Map();
  for(const pt of pts||[]){
    const x=+pt[0],y=+pt[1];
    if(!Number.isFinite(x)||!Number.isFinite(y))continue;
    const k=`${Math.round(x/bin)*bin},${Math.round(y/bin)*bin}`;
    const e=map.get(k)||{sx:0,sy:0,n:0};
    e.sx+=x;e.sy+=y;e.n++;map.set(k,e);
  }
  return [...map.values()].map(e=>({x:e.sx/e.n,y:e.sy/e.n,n:e.n})).sort((a,b)=>a.n-b.n);
}
function wardDotPx(kind,n){
  const base=kind==="obs"?11:8;
  return Math.max(base,Math.min(kind==="obs"?30:24,Math.round(base*Math.sqrt(n))));
}
function wardDot(kind,c){
  const p=wardPct(c.x,c.y),px=wardDotPx(kind,c.n);
  return `<span class="wardDot ${kind}" style="left:${p.l}%;top:${p.t}%;width:${px}px;height:${px}px;z-index:${c.n}" title="${c.n} ${kind==="obs"?"obs":"sen"}"></span>`;
}
let wardHeatJobs=[];
function wardStyleToggle(){
  const heat=state.wardStyle==="heat";
  return `<span class="wardToggle" role="group" aria-label="Ward map style"><button type="button" data-ward-style="dots" class="${heat?"":"on"}">Dots</button><button type="button" data-ward-style="heat" class="${heat?"on":""}">Heatmap</button></span>`;
}
function wardHeatCanvas(pts,size){
  const id=wardHeatJobs.length;
  wardHeatJobs.push(pts||[]);
  return `<canvas class="wardHeat" data-ward-heat="${id}" width="${size}" height="${size}"></canvas>`;
}
function wardHeatMap(label,pts,size){
  return `<div class="wardHeatOne"><div class="wardKind">${label}</div><div class="wardMap" style="--ward:${size}px;width:${size}px;height:${size}px"><img alt="" src="${WARD_MAP_SRC}" width="${size}" height="${size}">${wardHeatCanvas(pts,size)}</div></div>`;
}
function wardMap(obs,sen,size,showEmpty){
  size=size||168;
  if(state.wardStyle==="heat"){
    const empty=showEmpty!==false&&!(obs&&obs.length)&&!(sen&&sen.length);
    return `<div class="wardHeatPair">${wardHeatMap("Observer",obs,size)}${wardHeatMap("Sentry",sen,size)}${empty?'<span class="wardEmpty">No ward maps</span>':''}</div>`;
  }
  const o=clusterWards(obs),s=clusterWards(sen);
  return `<div class="wardMap" style="--ward:${size}px;width:${size}px;height:${size}px"><img alt="" src="${WARD_MAP_SRC}" width="${size}" height="${size}">${s.map(c=>wardDot("sen",c)).join("")}${o.map(c=>wardDot("obs",c)).join("")}${showEmpty!==false&&!o.length&&!s.length?'<span class="wardEmpty">No ward maps</span>':''}</div>`;
}
function wardSingle(kind,pts,size){
  size=size||220;
  if(state.wardStyle==="heat"){
    const empty=!(pts&&pts.length);
    return `<div class="wardMap" style="--ward:${size}px;width:${size}px;height:${size}px"><img alt="" src="${WARD_MAP_SRC}" width="${size}" height="${size}">${wardHeatCanvas(pts,size)}${empty?'<span class="wardEmpty">No ward maps</span>':''}</div>`;
  }
  const dots=clusterWards(pts);
  return `<div class="wardMap" style="--ward:${size}px;width:${size}px;height:${size}px"><img alt="" src="${WARD_MAP_SRC}" width="${size}" height="${size}">${dots.map(c=>wardDot(kind,c)).join("")}${dots.length?'':'<span class="wardEmpty">No ward maps</span>'}</div>`;
}
let heatLut=null;
function heatLutBytes(){
  if(heatLut)return heatLut;
  const c=document.createElement("canvas");
  c.width=256;c.height=1;
  const g=c.getContext("2d"),grd=g.createLinearGradient(0,0,256,0);
  grd.addColorStop(0,"rgba(0,0,255,0)");
  grd.addColorStop(.2,"rgb(0,0,255)");
  grd.addColorStop(.45,"rgb(0,255,0)");
  grd.addColorStop(.7,"rgb(255,255,0)");
  grd.addColorStop(.85,"rgb(255,90,0)");
  grd.addColorStop(1,"rgb(255,0,0)");
  g.fillStyle=grd;g.fillRect(0,0,256,1);
  heatLut=g.getImageData(0,0,256,1).data;
  return heatLut;
}
function paintWardHeats(){
  if(state.wardStyle!=="heat")return;
  const lut=heatLutBytes();
  document.querySelectorAll("canvas[data-ward-heat]").forEach(canvas=>{
    const pts=wardHeatJobs[+canvas.dataset.wardHeat]||[];
    const w=canvas.width,h=canvas.height,ctx=canvas.getContext("2d");
    ctx.clearRect(0,0,w,h);
    if(!pts.length||!w||!h)return;
    const buckets=new Map();
    for(const pt of pts){
      const x=+pt[0],y=+pt[1];
      if(!Number.isFinite(x)||!Number.isFinite(y))continue;
      const p=wardPct(x,y);
      const px=Math.max(0,Math.min(w-1,Math.round(p.l/100*(w-1))));
      const py=Math.max(0,Math.min(h-1,Math.round(p.t/100*(h-1))));
      const k=px+py*w;
      buckets.set(k,(buckets.get(k)||0)+1);
    }
    if(!buckets.size)return;
    let max=1;
    const cells=[];
    for(const [k,n] of buckets){const v=Math.sqrt(n);if(v>max)max=v;cells.push([k%w,(k-k%w)/w,v])}
    const radius=Math.max(12,Math.round(Math.min(w,h)*.16)),r2=radius*radius,field=new Float32Array(w*h);
    for(const [cx,cy,v] of cells){
      const weight=v/max,x0=Math.max(0,cx-radius),x1=Math.min(w-1,cx+radius),y0=Math.max(0,cy-radius),y1=Math.min(h-1,cy+radius);
      for(let y=y0;y<=y1;y++){
        const dy=y-cy;
        for(let x=x0;x<=x1;x++){
          const dx=x-cx,d=dx*dx+dy*dy;
          if(d>r2)continue;
          const t=1-Math.sqrt(d)/radius;
          field[y*w+x]+=weight*t*t;
        }
      }
    }
    let peak=0;
    for(let i=0;i<field.length;i++)if(field[i]>peak)peak=field[i];
    if(peak<=0)return;
    const img=ctx.createImageData(w,h),data=img.data;
    for(let i=0;i<field.length;i++){
      const n=field[i]/peak;
      if(n<.05)continue;
      const gi=Math.min(255,Math.round(n*255))*4,o=i*4;
      data[o]=lut[gi];data[o+1]=lut[gi+1];data[o+2]=lut[gi+2];
      data[o+3]=Math.round(Math.min(1,.2+n*.75)*255);
    }
    ctx.putImageData(img,0,0);
  });
}
function flattenWards(players){const obs=[],sen=[];for(const p of players||[]){obs.push(...(p.obs_map||[]));sen.push(...(p.sen_map||[]))}return {obs,sen}}
function focusPlayers(players,focusId){return focusId==null?players||[]:(players||[]).filter(p=>p.id===focusId)}
function emptyWards(){return {obs:[],sen:[],games:0}}
function splitWards(){return {radiant:emptyWards(),dire:emptyWards()}}
function addWards(dst,obs,sen){dst.obs.push(...(obs||[]));dst.sen.push(...(sen||[]))}
function hasWards(w){return !!(w.obs.length||w.sen.length)}
function splitTotals(w){return {obs:w.radiant.obs.length+w.dire.obs.length,sen:w.radiant.sen.length+w.dire.sen.length,games:(w.radiant.games||0)+(w.dire.games||0)}}
function wardSlot(label,side,size){const on=!!side.games;return `<div class="wardSlot${on?'':' off'}"><div class="wardSideLabel">${label}</div>${wardMap(side.obs,side.sen,size,on)}</div>`}
function wardSplit(w,size){size=size||140;return `<div class="wardSplit">${wardSlot("Radiant",w.radiant,size)}${wardSlot("Dire",w.dire,size)}</div>`}
function scoutedWardMap(label,obs,sen,size){return `<div class="gameWards"><div><div class="wardSideLabel">${label}</div>${wardMap(obs,sen,size)}</div></div>`}
function gameWardSplit(g,size){if(g.isRadiant!==true&&g.isRadiant!==false)return wardMap(g.obs,g.sen,size);return scoutedWardMap(g.isRadiant?"Radiant":"Dire",g.obs,g.sen,size)}
function collectPlayerWards(id){
  const out=splitWards();
  for(const m of DATA.teamMatches||[]){
    if(!isWardPatch(m.patch))continue;
    const r=(m.radiant.players||[]).find(x=>x.id===id);
    const d=(m.dire.players||[]).find(x=>x.id===id);
    if(r){addWards(out.radiant,r.obs_map,r.sen_map);out.radiant.games++}
    if(d){addWards(out.dire,d.obs_map,d.sen_map);out.dire.games++}
  }
  return out;
}
function collectOfficialWards(p){
  const out=splitWards();
  for(const m of (p.official&&p.official.matches)||[]){
    if(!isWardPatch(m.patch))continue;
    const side=m.is_radiant===true?"radiant":m.is_radiant===false?"dire":null;
    if(!side)continue;
    addWards(out[side],m.obs_map,m.sen_map);out[side].games++;
  }
  return out;
}
function collectPubWards(p){
  const out=splitWards();
  for(const m of p.pubWards||[]){
    if(!isWardPatch(m.patch))continue;
    const side=m.is_radiant===true?"radiant":m.is_radiant===false?"dire":null;
    if(!side)continue;
    addWards(out[side],m.obs_map,m.sen_map);out[side].games++;
  }
  return out;
}
function bestWardSplit(p){
  const league=collectPlayerWards(p.id);
  if(hasWards(league.radiant)||hasWards(league.dire))return {split:league,title:"All officials"};
  const official=collectOfficialWards(p);
  if(hasWards(official.radiant)||hasWards(official.dire))return {split:official,title:"All officials"};
  const pubs=collectPubWards(p);
  if(hasWards(pubs.radiant)||hasWards(pubs.dire))return {split:pubs,title:"Pubs"};
  if(official.radiant.games||official.dire.games)return {split:official,title:"All officials"};
  if(league.radiant.games||league.dire.games)return {split:league,title:"All officials"};
  return {split:pubs,title:"Pubs"};
}
function playerWardPoints(p){return bestWardSplit(p).split}
function wardMapTitle(p){return bestWardSplit(p).title}
function playerWardCard(p){const w=playerWardPoints(p),t=splitTotals(w);return `<div class="wardCard"><b>${E(p.name)}</b><small>${t.obs} obs · ${t.sen} sen · ${t.games}g</small>${wardSplit(w,240)}</div>`}
function wardLegend(){const heat=state.wardStyle==="heat",key=heat?`<span class="heatScale"><i></i>rare → often</span>`:`<span class="wardFreqHint">Larger = more often</span><span><i class="wardDot obs"></i>Observer</span><span><i class="wardDot sen"></i>Sentry</span>`;return `<div class="wardLegend">${wardStyleToggle()}${key}</div>`}
function wardMapsPanel(ps){return `<div class="contentBlock"><h3>Ward maps · 7.41</h3>${wardLegend()}<div class="wardGrid">${ps.map(playerWardCard).join("")}</div></div>`}
function playerWardGames(p){
  const seen=new Set(),out=[];
  for(const m of DATA.teamMatches||[]){
    if(!isWardPatch(m.patch))continue;
    for(const side of [m.radiant,m.dire]){
      const row=(side.players||[]).find(x=>x.id===p.id);
      if(!row)continue;
      const isRadiant=side===m.radiant,opp=isRadiant?m.dire:m.radiant,win=isRadiant?m.radiant_win:!m.radiant_win;
      seen.add(m.match_id);
      out.push({match_id:m.match_id,start_time:m.start_time,opponent:opp.name,opponent_key:opp.team_key,hero_id:row.hero_id,win,isRadiant,obs:row.obs_map||[],sen:row.sen_map||[]});
    }
  }
  for(const m of (p.official&&p.official.matches)||[]){
    if(!isWardPatch(m.patch)||seen.has(m.match_id))continue;
    const isRadiant=m.is_radiant===true?true:m.is_radiant===false?false:null;
    out.push({match_id:m.match_id,start_time:m.start_time,opponent:m.opponent,opponent_key:m.opponent_key,hero_id:m.hero_id,win:m.result==="W",isRadiant,obs:m.obs_map||[],sen:m.sen_map||[]});
  }
  for(const m of p.pubWards||[]){
    if(!isWardPatch(m.patch)||seen.has(m.match_id))continue;
    const isRadiant=m.is_radiant===true?true:m.is_radiant===false?false:null;
    seen.add(m.match_id);
    out.push({match_id:m.match_id,start_time:m.start_time,opponent:"Pub",hero_id:m.hero_id,win:!!m.win,isRadiant,obs:m.obs_map||[],sen:m.sen_map||[],pub:true});
  }
  return out.sort((a,b)=>(b.start_time||0)-(a.start_time||0));
}
function playerGameWardCard(g){const who=g.pub?"Pub":captainLabel(g.opponent,g.opponent_key);return `<div class="wardCard playerGameWard"><b>${heroIcon(g.hero_id,22)} vs ${E(who)}</b><small><span class="${g.win?"good":"bad"}">${g.win?"W":"L"}</span> · ${date(g.start_time)} · ${g.obs.length} obs · ${g.sen.length} sen</small>${gameWardSplit(g,240)}<a target="_blank" rel="noopener" href="https://www.opendota.com/matches/${g.match_id}">Match ${g.match_id}</a></div>`}
function playerWardsTab(p){
  const all=playerWardPoints(p),games=playerWardGames(p),t=splitTotals(all);
  if(!t.games&&!games.length)return `<div class="notice">${p.pubWardsPending?"Recent 7.41 games are still waiting on an OpenDota parse.":"No 7.41 ward maps for this player yet."}</div>`;
  const waiting=p.pubWardsPending&&!t.obs&&!t.sen?`<p class="caveat">Recent 7.41 games are still waiting on an OpenDota parse.</p>`:"";
  return `<div class="contentBlock"><h3>Ward maps · 7.41</h3>${waiting}${wardLegend()}<div class="playerWardAll"><div class="wardCard"><b>${wardMapTitle(p)}</b><small>${t.obs} obs · ${t.sen} sen · ${t.games}g</small>${wardSplit(all,460)}</div></div>${games.length?`<h3>By game</h3><div class="wardGrid">${games.map(playerGameWardCard).join("")}</div>`:""}</div>`;
}
function seriesWardGrid(games,focusId){
  const shown=games.map((g,i)=>({g,n:i+1})).filter(({g})=>isWardPatch(g.m.patch));
  const cell=(side,kind)=>{
    const maps=shown.filter(({g})=>side==="radiant"?g.isRadiant===true:g.isRadiant===false).filter(({g})=>focusId==null||(g.mine.players||[]).some(p=>p.id===focusId)).map(({g,n})=>{
      const pts=flattenWards(focusPlayers(g.mine.players,focusId));
      return `<figure class="resultMap"><figcaption>Match ${n}</figcaption>${wardSingle(kind,kind==="obs"?pts.obs:pts.sen,220)}</figure>`;
    }).join("");
    return `<div class="resultSide ${side}">${maps}</div>`;
  };
  const row=(kind,label)=>`<div class="resultKind"><div class="resultKindLabel">${label}</div><div class="resultKindMaps">${cell("radiant",kind)}${cell("dire",kind)}</div></div>`;
  return `<div class="seriesWards"><div class="resultHeads"><span></span><span>Radiant</span><span>Dire</span></div>${row("obs","Observer")}${row("sen","Sentry")}</div>`;
}
function seriesWardFold(games,focusId){return games.some(g=>isWardPatch(g.m.patch))?mapsFold("",seriesWardGrid(games,focusId)):""}
function mapsFold(extra,body){return `<details class="wardFold"><summary><span class="draftLabel">Ward maps</span>${wardStyleToggle()}${extra||""}</summary>${body}</details>`}
function teamGameForPlayerMatch(p,matchId){
  const m=(DATA.teamMatches||[]).find(x=>x.match_id===matchId);
  if(!m)return null;
  const isRadiant=(m.radiant.players||[]).some(x=>x.id===p.id);
  if(!isRadiant&&!(m.dire.players||[]).some(x=>x.id===p.id))return null;
  const mine=isRadiant?m.radiant:m.dire,opp=isRadiant?m.dire:m.radiant,win=isRadiant?m.radiant_win:!m.radiant_win;
  return {m,isRadiant,mine,opp,win};
}
function officialMatchRows(p,m,n){
  return `<tr><td><a target="_blank" rel="noopener" href="${dbMatchUrl(m.match_id)}">Match ${n}</a></td><td class="heroCol">${heroIcon(m.hero_id,20)} ${E(m.hero)}</td><td title="${E((m.position_evidence||[]).join(', '))}">${m.position?`P${m.position} ${E(POS[m.position])}`:'—'}<span class="sub">${E(m.position_confidence||'')}</span></td><td class="${m.result==='W'?'good':'bad'}">${m.result}</td><td>${m.kills??'—'}/${m.deaths??'—'}/${m.assists??'—'}</td><td>${m.gpm??'—'}</td><td>${m.xpm??'—'}</td><td>${m.last_hits??'—'}/${m.denies??'—'}</td><td>${fmt(m.net_worth)}</td><td>${fmt(m.hero_damage)}</td><td>${fmt(m.tower_damage)}</td><td>${laneWithResult(m.lane_eff, m.result==="W")}</td><td>${m.observer_wards??'—'}</td><td>${m.sentry_wards??'—'}</td><td>${m.dewards??'—'}</td></tr>`;
}
function pickNums(m){const map=new Map();(m.picks_bans||[]).forEach((x,i)=>{if(!x.is_pick||!x.hero_id)return;const n=(Number.isFinite(x.order)?x.order:i)+1;if(!map.has(x.hero_id))map.set(x.hero_id,n)});return map}
function playersByDraft(players,nums){return [...(players||[])].sort((a,b)=>{const an=nums.get(a.hero_id),bn=nums.get(b.hero_id);if(an==null&&bn==null)return 0;if(an==null)return 1;if(bn==null)return -1;return an-bn})}
function playerHeroCell(p,focusId,pickN){const on=focusId!=null&&p.id===focusId,n=Number.isFinite(pickN)?`<span class="heroPickN">${pickN}</span>`:"";return `<div class="heroCell${on?' on':''}">${n}${heroIcon(p.hero_id,48)}<b class="heroCellName" title="${E(p.name)}">${E(cellName(p.name)||p.name)}</b><small>${p.kills??'—'}/${p.deaths??'—'}/${p.assists??'—'}</small></div>`}
function gameDraftLine(g){
  const myNum=g.isRadiant?0:1,pb=[...(g.m.picks_bans||[])].sort((a,b)=>(a.order??0)-(b.order??0));
  if(!pb.length)return "";
  const parts=pb.map((x,i)=>{
    const ours=x.team===myNum,ban=!x.is_pick,n=(Number.isFinite(x.order)?x.order:i)+1;
    return `<span class="draftAct ${ours?"ours":"theirs"}${ban?" ban":""}" title="${ban?"Ban":"Pick"} ${n} · ${ours?"us":"them"}"><span class="draftN">${n}</span>${heroIcon(x.hero_id,28,ban)}</span>`;
  });
  return `<div class="draftLine"><span class="draftLabel">Draft</span>${parts.join("")}</div>`;
}
function gameRow(g,n,focusId){
  const dur=`${Math.floor(g.m.duration/60)}:${String(g.m.duration%60).padStart(2,'0')}`,side=g.isRadiant?"Radiant":"Dire";
  const sit=focusId!=null&&!(g.mine.players||[]).some(p=>p.id===focusId);
  const nums=pickNums(g.m),mine=playersByDraft(g.mine.players,nums),opp=playersByDraft(g.opp.players,nums);
  const scouted=`<div class="sideBlock mine">${mine.map(p=>playerHeroCell(p,focusId,nums.get(p.hero_id))).join("")}</div>`;
  const other=`<div class="sideBlock enemy">${opp.map(p=>playerHeroCell(p,null,nums.get(p.hero_id))).join("")}</div>`;
  const sides=g.isRadiant?`${scouted}<div class="vsTiny">vs</div>${other}`:`${other}<div class="vsTiny">vs</div>${scouted}`;
  return `<div class="gameRow${sit?' sitout':''}"><div class="gameMeta"><b class="${g.win?'good':'bad'}">${g.win?'W':'L'}</b><a target="_blank" rel="noopener" href="${dbMatchUrl(g.m.match_id)}">Match ${n}</a><span>${dur}</span><span>${E(side)}</span></div><div class="gameSides">${sides}</div>${gameDraftLine(g)}${visionLine(focusPlayers(g.mine.players,focusId))}</div>`;
}
function seriesCard(games,weeks,focusId){
  const opp=games[0].opp;
  const w=games.filter(g=>g.win).length,l=games.length-w,cls=w>l?"good":l>w?"bad":"";
  return `<div class="card section seriesCard"><div class="seriesHead"><span class="seriesDate">${E(seriesWeekLabel(games,weeks))}</span><span class="seriesOpp">vs <b title="${E(opp.name)}">${E(captainLabel(opp.name,opp.team_key))}</b></span><span class="seriesScore ${cls}">${w}-${l}</span></div><div class="gameList">${games.map((g,i)=>gameRow(g,i+1,focusId)).join("")}</div>${seriesWardFold(games,focusId)}</div>`;
}
const pullState={mine:{results:[],loading:false,error:""},enemy:{results:[],loading:false,error:""}};
const pullTimers={mine:null,enemy:null};
function renderPullDropdown(side){
  const dd=document.querySelector(`[data-pull-dropdown="${side}"]`);
  if(!dd)return;
  const st=pullState[side];
  if(st.loading){dd.innerHTML='<div class="pullMsg">Searching…</div>';dd.classList.remove("hidden");return}
  if(st.error){dd.innerHTML=`<div class="pullMsg pullErr">${E(st.error)}</div>`;dd.classList.remove("hidden");return}
  if(!st.results.length){dd.classList.add("hidden");dd.innerHTML="";return}
  dd.innerHTML=st.results.map(r=>`<button type="button" class="pullResult" data-pull-pick="${side}:${r.id}">${r.avatar?`<img class="pullAvatar" src="${E(r.avatar)}" alt="">`:'<span class="pullAvatar"></span>'}<span class="pullResultInfo"><b>${E(r.name)}</b><small>${r.id}${r.inPool?' · in pool':''}</small></span></button>`).join("");
  dd.classList.remove("hidden");
  dd.querySelectorAll("[data-pull-pick]").forEach(b=>b.onclick=()=>{const [s,idStr]=b.dataset.pullPick.split(":");pickPullResult(s,Number(idStr))});
}
function setPullStatus(side,text,isError){
  const el=document.querySelector(`[data-pull-status="${side}"]`);
  if(el){el.textContent=text||"";el.classList.toggle("bad",!!isError)}
}
async function runPullSearch(side,query){
  const st=pullState[side];
  if(query.length<2){st.results=[];st.loading=false;st.error="";renderPullDropdown(side);return}
  st.loading=true;st.error="";renderPullDropdown(side);
  try{
    const res=await fetch(`/api/search?q=${encodeURIComponent(query)}`),body=await res.json().catch(()=>({}));
    if(!res.ok){st.error=body.error||"Search failed";st.results=[]}
    else{
      const mineIds=idsByLeague[activeLeague]||new Set();
      const foreign=new Set();
      for(const id of leagueIds){if(id===activeLeague)continue;for(const pid of idsByLeague[id]||[])if(!mineIds.has(pid))foreign.add(pid)}
      st.results=(body.results||[]).filter(r=>!foreign.has(r.id));
      st.error=st.results.length?"":"No matches found";
    }
  }catch(e){st.error="Search failed";st.results=[]}
  st.loading=false;renderPullDropdown(side);
}
function addPlayerToSide(side,id){
  const other=side==="mine"?"enemy":"mine";
  if(state[side].length>=5||state[side].includes(id))return;
  if(state[other].includes(id))state[other]=state[other].filter(x=>x!==id);
  state[side]=[...state[side],id];
  state.focusPlayer=id;
  persist();render();
}
function swapStandin(side,id){
  if(state.pendingStandin&&state.pendingStandin.side===side&&state.pendingStandin.id===id){state.pendingStandin=null;persist();render();return}
  if(state[side].includes(id))return;
  if(state[side].length<5){addPlayerToSide(side,id);return}
  state.pendingStandin={side,id};persist();render();
}
function completeSwap(side,outId){
  const pending=state.pendingStandin;
  if(!pending||pending.side!==side||!state[side].includes(outId)||state[side].includes(pending.id))return;
  const other=side==="mine"?"enemy":"mine";
  if(state[other].includes(pending.id))state[other]=state[other].filter(x=>x!==pending.id);
  state[side]=state[side].map(id=>id===outId?pending.id:id);
  const focusKey=side==="mine"?"focusMine":"focusEnemy";
  if(state[focusKey]===outId)state[focusKey]=pending.id;
  if(state.focusPlayer===outId)state.focusPlayer=pending.id;
  state.pendingStandin=null;persist();render();
}
function pickPullResult(side,id){
  const st=pullState[side],picked=st.results.find(r=>r.id===id);
  st.results=[];renderPullDropdown(side);
  if(!picked)return;
  if(picked.inPool||byId.has(id)){addPlayerToSide(side,id);return}
  pullFromOpenDota(side,id,picked.name);
}
async function pullFromOpenDota(side,id,fallbackName){
  setPullStatus(side,`Pulling ${fallbackName||id} from OpenDota…`);
  const btn=document.querySelector(`[data-pull-btn="${side}"]`);
  if(btn)btn.disabled=true;
  try{
    const res=await fetch("/api/player",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})}),body=await res.json().catch(()=>({}));
    if(!res.ok){setPullStatus(side,body.error||"Could not pull that player",true);if(btn)btn.disabled=false;return}
    const player=body.player;
    DATA.players.push(player);SOURCE.players.push(player);byId.set(player.id,player);
    setPullStatus(side,"");
    addPlayerToSide(side,player.id);
    return;
  }catch(e){setPullStatus(side,"Could not reach the server",true)}
  if(btn)btn.disabled=false;
}
function updateTeamInData(team){
  const idx=(DATA.teams||[]).findIndex(x=>x.key===team.key);
  if(idx>=0)DATA.teams[idx]=team;else (DATA.teams=DATA.teams||[]).push(team);
  const src=(SOURCE.teams||[]).findIndex(x=>x.key===team.key&&teamLeagueId(x)===teamLeagueId(team));
  if(src>=0)SOURCE.teams[src]=team;else SOURCE.teams.push(team);
  for(const id of leagueIds)idsByLeague[id]=rosterIdSet(SOURCE.teams.filter(t=>teamLeagueId(t)===id));
}
async function persistReplaced(side,ids){
  const t=(DATA.teams||[]).find(x=>x.key===sideLoadedKey(side));
  if(!t)return;
  try{
    const res=await fetch("/api/roster",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({team:t.key,replaced:ids})}),body=await res.json().catch(()=>({}));
    if(res.ok&&body.team){
      updateTeamInData(body.team);
      const other=side==="mine"?"enemy":"mine",gone=new Set(body.team.replaced||[]),focusKey=side==="mine"?"focusMine":"focusEnemy";
      if(gone.has(state[focusKey]))state[focusKey]=null;
      if(gone.has(state.focusPlayer))state.focusPlayer=null;
      if(state.pendingStandin&&state.pendingStandin.side===side&&gone.has(state.pendingStandin.id))state.pendingStandin=null;
      state[side]=activeRoster(body.team,state[other]);
      persist();render();return;
    }
    alert(body.error||"Could not save replaced players");
  }catch(e){alert("Could not reach the server")}
}
function reconMonday(){
  const now=new Date(),day=now.getDay();
  return Math.floor(new Date(now.getFullYear(),now.getMonth(),now.getDate()-(day===0?6:day-1)).getTime()/1000);
}
function reconMatches(p){const floor=reconMonday();return (p.matches||[]).filter(m=>m.at>=floor&&isPub(m))}
function reconHeroStats(rows,playerName){
  const map=new Map();
  for(const m of rows){
    const h=map.get(m.hero)||{id:m.hero,name:m.heroName||heroName(m.hero),games:0,wins:0,players:playerName?[playerName]:[],positions:{}};
    h.games++;if(m.win)h.wins++;
    if(m.position)h.positions[m.position]=(h.positions[m.position]||0)+1;
    map.set(m.hero,h);
  }
  return [...map.values()].map(h=>({...h,primaryPosition:Object.entries(h.positions||{}).sort((a,b)=>b[1]-a[1])[0]?.[0]||null})).sort((a,b)=>b.games-a.games||b.wins-a.wins);
}
function reconTeamHeroes(ps){
  const map=new Map();
  for(const p of ps){
    for(const h of reconHeroStats(reconMatches(p),p.name)){
      const x=map.get(h.id)||{id:h.id,name:h.name,games:0,wins:0,players:[],positions:{}};
      x.games+=h.games;x.wins+=h.wins;
      if(!x.players.includes(p.name))x.players.push(p.name);
      if(h.primaryPosition)x.positions[h.primaryPosition]=(x.positions[h.primaryPosition]||0)+h.games;
      map.set(h.id,x);
    }
  }
  return [...map.values()].sort((a,b)=>b.games-a.games||b.players.length-a.players.length||b.wins-a.wins);
}
function reconTogether(ps){
  const map=new Map();
  for(const p of ps){
    for(const m of reconMatches(p)){
      if(!m.id)continue;
      const g=map.get(m.id)||{id:m.id,at:m.at,players:[]};
      if(g.players.some(x=>x.p.id===p.id))continue;
      g.players.push({p,m});
      if(m.at&&(!g.at||m.at>g.at))g.at=m.at;
      map.set(m.id,g);
    }
  }
  return [...map.values()].filter(g=>g.players.length>=2).sort((a,b)=>(b.at||0)-(a.at||0)||b.players.length-a.players.length);
}
function reconTogetherRow(g){
  const who=g.players.map(({p,m})=>`${heroIcon(m.hero,20)} ${E(p.name)} <span class="${m.win?"good":"bad"}">${m.win?"W":"L"}</span>`).join(" · ");
  return `<tr><td><a target="_blank" rel="noopener" href="https://www.opendota.com/matches/${g.id}">${g.id}</a></td><td>${date(g.at)}</td><td class="heroCol">${who}</td></tr>`;
}
function reconTogetherSection(ps){
  const games=reconTogether(ps);
  if(!games.length)return "";
  return `<div class="contentBlock"><h3>Together this week</h3><p class="matchupCap">Same public match, two or more of them.</p><div class="tableWrap"><table class="tbl"><thead><tr><th>Match</th><th>Date</th><th class="heroCol">Who</th></tr></thead><tbody>${games.map(reconTogetherRow).join("")}</tbody></table></div></div>`;
}
function reconPrivateSection(ps){
  const priv=ps.filter(p=>p.private);
  if(!priv.length)return `<div class="metric privateBlock"><span>Private profiles</span><b>None</b><small>all public</small></div>`;
  const who=priv.map(p=>E(p.name)).join(", ");
  return `<div class="metric privateBlock on"><span>Private profiles</span><b>${who}</b><small>pub history hidden</small></div>`;
}
function reconPage(){
  const ps=members("enemy");
  const since=new Date(reconMonday()*1000).toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric"});
  const cap=`<p class="matchupCap">Public games since ${E(since)}. Ranked by volume so hero spam shows first.</p>`;
  const setupBar=`<div class="teamsetup enemy" id="setup-enemy">${setup("enemy")}</div>`;
  if(!ps.length)return `<div class="singlePage">${setupBar}${cap}<div class="notice">Add an opponent to see what they've been playing this week.</div></div>`;
  const byPlayer=ps.map(p=>{const rows=reconMatches(p);return {p,rows,heroes:reconHeroStats(rows,p.name),s:matchSummary(rows)}});
  const allRows=byPlayer.flatMap(x=>x.rows),heroes=reconTeamHeroes(ps),played=byPlayer.filter(x=>x.rows.length).length,top=heroes[0],max=Math.max(...heroes.slice(0,12).map(h=>h.games),1),wins=allRows.filter(m=>m.win).length;
  const priv=reconPrivateSection(ps);
  const metrics=`<div class="card reconTop"><div class="metrics">${metric("This week",`${wins}–${allRows.length-wins}`,`${allRows.length} player-games`)}${metric("Players active",`${played}/${ps.length}`,"with pubs since Monday")}${metric("Unique heroes",String(heroes.length))}${metric("Most played",top?E(top.name):"—",top?`${top.games}g · ${E(top.players.join(", "))}`:"no pubs this week")}${priv}</div></div>`;
  const teamHeroes=heroes.length?`<div class="contentBlock"><h3>Most played this week</h3><div class="card section"><div class="bars">${heroes.slice(0,12).map(h=>`<div class="barrow"><span>${heroIcon(h.id,18)} ${E(h.name)}</span><div class="track"><div class="fill" style="width:${h.games/max*100}%"></div></div><span class="value">${h.games}g · ${pct(h.wins,h.games)} · ${E(h.players.join(", "))}</span></div>`).join("")}</div></div></div>`:`<div class="notice">No cached public games since Monday.</div>`;
  const together=reconTogetherSection(ps);
  const players=`<div class="contentBlock"><h3>By player</h3><div class="flexHeroList">${byPlayer.map(({p,heroes,s})=>{const lead=heroes[0],chips=heroes.length?`<div class="heroChipRow">${heroes.map(h=>`<span class="heroChip">${heroIcon(h.id,28)}<b>${E(h.name)}</b><small>${h.games}g · ${h.wins}–${h.games-h.wins}</small></span>`).join("")}</div>`:`<small>No cached pubs since Monday.</small>`;return `<div class="flexHero">${lead?heroIcon(lead.id,36):""}<div><b>${E(p.name)}</b><small>${s.games?`${s.games} games · ${s.wins}–${s.games-s.wins}`:"quiet this week"}</small>${chips}</div></div>`}).join("")}</div></div>`;
  return `<div class="singlePage">${setupBar}${cap}<div class="side enemy">${metrics}${teamHeroes}${together}${players}</div></div>`;
}
function adminPage(){
  const signins=(ACCOUNT.signins||[]).filter(s=>leagueIds.length<2||leagueId(s.league)===activeLeague);
  const cards=signins.map(s=>{
    const t=teamByKey(s.teamKey);
    const names=((t&&t.roster)||[]).map(id=>((byId.get(id)||{}).name)||id).join(", ");
    const league=s.league?String(s.league).toUpperCase():"Team";
    return `<div class="card section"><h3>${E(league)}</h3><b>${E(s.team||s.user)}</b><p class="matchupCap">${names?E(names):"No roster saved yet."}</p><button data-open-signin="${E(s.teamKey)}">Open as my team</button></div>`;
  }).join("");
  return `<div class="singlePage"><div class="pageHeading"><h2>Admin</h2><p>One login for every team sign-in. Team passwords still cannot see each other. The league under Settings keeps this view in one league.</p></div><div class="pageGrid">${cards||"<div class='notice'>No team sign-in for this league.</div>"}</div></div>`;
}
const pages={team:()=>teamPage('mine'),opponent:()=>teamPage('enemy'),recon:reconPage,matchup:matchupPage,standings:standingsPage,league:leaguePage,admin:adminPage};
function bindSeriesWardFolds(){document.querySelectorAll(".seriesCard .wardFold").forEach(d=>d.ontoggle=()=>{const card=d.closest(".seriesCard");if(!card||d._sync)return;card.querySelectorAll(".wardFold").forEach(o=>{if(o===d||o.open===d.open)return;o._sync=1;o.open=d.open;o._sync=0})})}
function bindWardStyle(){document.querySelectorAll("[data-ward-style]").forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();const next=b.dataset.wardStyle==="heat"?"heat":"dots";if(state.wardStyle===next)return;state.wardStyle=next;persist();render()})}
function render(){wardHeatJobs=[];document.querySelectorAll(".nav button").forEach(b=>b.classList.toggle("on",b.dataset.view===state.view));const ws=document.querySelector("#workspace");ws.classList.toggle("enemyView",state.view==="opponent"||state.view==="recon");ws.innerHTML=pages[state.view]();bind()}
function bind(){bindSeriesWardFolds();bindWardStyle();paintWardHeats();document.querySelectorAll("[data-window]").forEach(s=>s.onchange=()=>{state.window=s.value;persist();render()});document.querySelectorAll("[data-team-choice]").forEach(s=>s.onchange=()=>{const side=s.dataset.teamChoice;state[side+'Preset']=s.value;const button=document.querySelector(`[data-load-team="${side}"]`);if(button)button.disabled=s.value===''});document.querySelectorAll("[data-load-team]").forEach(b=>b.onclick=()=>{const side=b.dataset.loadTeam;if(side==="mine"&&ACCOUNT.locked)return;const index=state[side+'Preset'],t=DATA.teams[Number(index)];if(index===''||!t)return;const other=side==='mine'?'enemy':'mine';state[side]=activeRoster(t,state[other]);state[side+'Name']=t.name||t.short;state[side+'TeamKey']=t.key;state[side==='mine'?'focusMine':'focusEnemy']=null;state[side+'Preset']='';state.pendingStandin=null;persist();render()});document.querySelectorAll("[data-remove]").forEach(b=>b.onclick=(e)=>{e.stopPropagation();const [side,id]=b.dataset.remove.split(":");state[side]=state[side].filter(x=>x!==Number(id));state.pendingStandin=null;persist();render()});document.querySelectorAll("[data-name]").forEach(i=>i.onchange=()=>{state[i.dataset.name+"Name"]=i.value.trim()||(i.dataset.name==='mine'?'My Team':'Opponent');persist();render()});document.querySelectorAll("[data-focus]").forEach(b=>b.onclick=()=>{const [side,id]=b.dataset.focus.split(":");state[side==='mine'?'focusMine':'focusEnemy']=Number(id);state.focusPlayer=Number(id);state.sub=state.sub||{mine:"players",enemy:"players"};state.sub[side]="players";persist();render()});
document.querySelectorAll("[data-team-sub]").forEach(b=>b.onclick=()=>{const [side,pane]=b.dataset.teamSub.split(":");state.sub=state.sub||{mine:"players",enemy:"players"};state.sub[side]=pane;persist();render()});
document.querySelectorAll("[data-results-player]").forEach(b=>b.onclick=()=>{const [side,idStr]=b.dataset.resultsPlayer.split(":");state.resultsPlayer=state.resultsPlayer||{mine:null,enemy:null};const id=idStr?Number(idStr):null;state.resultsPlayer[side]=id&&state.resultsPlayer[side]===id?null:id;persist();render()});
document.querySelectorAll("[data-player-sub]").forEach(b=>b.onclick=()=>{const [side,pane]=b.dataset.playerSub.split(":");state.playerSub=state.playerSub||{mine:"overview",enemy:"overview"};state.playerSub[side]=pane;persist();render()});
document.querySelectorAll("[data-open-matchup]").forEach(b=>b.onclick=()=>{const m=(DATA.matchups||[])[Number(b.dataset.openMatchup)];if(!m)return;const a=teamByKey(m.aKey),opp=teamByKey(m.bKey);if(!a||!opp)return;if(ACCOUNT.locked){const mineTeam=teamByKey(ACCOUNT.teamKey)||a;state.mine=activeRoster(mineTeam,[]);state.mineName=mineTeam.name||mineTeam.short;state.mineTeamKey=mineTeam.key;const foe=mineTeam.key===a.key?opp:a;if(foe.key!==mineTeam.key){state.enemy=activeRoster(foe,state.mine);state.enemyName=foe.name||foe.short;state.enemyTeamKey=foe.key}state.focusMine=null;state.focusEnemy=null;state.pendingStandin=null;state.view="matchup";persist();render();return}const mineKey=sideLoadedKey("mine");const left=mineKey===m.bKey?opp:a,right=left===a?opp:a;state.mine=activeRoster(left,[]);state.mineName=left.name||left.short;state.mineTeamKey=left.key;state.enemy=activeRoster(right,state.mine);state.enemyName=right.name||right.short;state.enemyTeamKey=right.key;state.focusMine=null;state.focusEnemy=null;state.pendingStandin=null;state.view="matchup";persist();render()});
document.querySelectorAll("[data-standings-opponent]").forEach(b=>b.onclick=()=>{const key=b.dataset.standingsOpponent,t=(DATA.teams||[]).find(x=>x.key===key);if(!t)return;state.enemy=activeRoster(t,state.mine);state.enemyName=t.name||t.short;state.enemyTeamKey=t.key;state.focusEnemy=null;state.pendingStandin=null;persist();render()});
document.querySelectorAll("[data-standings-results]").forEach(b=>b.onclick=()=>{const key=b.dataset.standingsResults,t=(DATA.teams||[]).find(x=>x.key===key);state.sub=state.sub||{mine:"players",enemy:"players"};if(sideLoadedKey("mine")===key){state.view="team";state.sub.mine="results"}else{if(t){state.enemy=activeRoster(t,state.mine);state.enemyName=t.name||t.short;state.enemyTeamKey=t.key;state.focusEnemy=null;state.pendingStandin=null}state.view="opponent";state.sub.enemy="results"}persist();render()});
document.querySelectorAll("[data-edit-roster]").forEach(b=>b.onclick=()=>{const side=b.dataset.editRoster;state.editing=state.editing||{mine:false,enemy:false};state.editing[side]=!state.editing[side];if(!state.editing[side])state.pendingStandin=null;persist();render()});
document.querySelectorAll("[data-sub-chip]").forEach(el=>el.onclick=()=>{const [side,idStr]=el.dataset.subChip.split(":");swapStandin(side,Number(idStr))});
document.querySelectorAll("[data-swap-for]").forEach(el=>el.onclick=()=>{const [side,idStr]=el.dataset.swapFor.split(":");completeSwap(side,Number(idStr))});
document.querySelectorAll("[data-save-roster]").forEach(b=>b.onclick=async()=>{const side=b.dataset.saveRoster,t=(DATA.teams||[]).find(x=>x.key===sideLoadedKey(side));if(!t)return;b.disabled=true;try{const res=await fetch("/api/roster",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({team:t.key,roster:state[side]})}),body=await res.json().catch(()=>({}));if(res.ok&&body.team){updateTeamInData(body.team);render();return}alert(body.error||"Could not save roster")}catch(e){alert("Could not reach the server")}b.disabled=false});
document.querySelectorAll("[data-reset-roster]").forEach(b=>b.onclick=async()=>{const side=b.dataset.resetRoster,t=(DATA.teams||[]).find(x=>x.key===sideLoadedKey(side));if(!t)return;b.disabled=true;try{const res=await fetch("/api/roster",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({team:t.key,reset:true})}),body=await res.json().catch(()=>({}));if(res.ok&&body.team){updateTeamInData(body.team);const other=side==="mine"?"enemy":"mine";state[side]=activeRoster(body.team,state[other]);persist();render();return}alert(body.error||"Could not reset roster")}catch(e){alert("Could not reach the server")}b.disabled=false});
document.querySelectorAll("[data-mark-replaced]").forEach(b=>b.onclick=async(e)=>{e.stopPropagation();e.preventDefault();const [side,idStr]=b.dataset.markReplaced.split(":"),t=(DATA.teams||[]).find(x=>x.key===sideLoadedKey(side));if(!t)return;const id=Number(idStr),ids=[...new Set([...(t.replaced||[]),id])];await persistReplaced(side,ids)});
document.querySelectorAll("[data-unmark-replaced]").forEach(b=>b.onclick=async(e)=>{e.stopPropagation();e.preventDefault();const [side,idStr]=b.dataset.unmarkReplaced.split(":"),t=(DATA.teams||[]).find(x=>x.key===sideLoadedKey(side));if(!t)return;const id=Number(idStr),ids=(t.replaced||[]).filter(x=>x!==id);await persistReplaced(side,ids)});
document.querySelectorAll("[data-pull-input]").forEach(inp=>{inp.oninput=()=>{const side=inp.dataset.pullInput;clearTimeout(pullTimers[side]);const q=inp.value.trim();pullTimers[side]=setTimeout(()=>runPullSearch(side,q),350)};inp.onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();const side=inp.dataset.pullInput;clearTimeout(pullTimers[side]);runPullSearch(side,inp.value.trim())}}});
document.querySelectorAll("[data-pull-btn]").forEach(b=>b.onclick=()=>{const side=b.dataset.pullBtn,inp=document.querySelector(`[data-pull-input="${side}"]`);if(inp){clearTimeout(pullTimers[side]);runPullSearch(side,inp.value.trim())}});
document.querySelectorAll("[data-hero-sort]").forEach(th=>th.onclick=()=>{heroSort.key=th.dataset.heroSort;render()});
document.querySelectorAll("[data-open-signin]").forEach(b=>b.onclick=()=>{const wanted=SOURCE.teams.find(x=>x.key===b.dataset.openSignin);if(wanted&&leagueIds.length>1){const league=teamLeagueId(wanted);if(league&&league!==activeLeague)switchLeague(league)}const t=teamByKey(b.dataset.openSignin);if(!t)return;state.mine=activeRoster(t,[]);state.mineName=t.name||t.short;state.mineTeamKey=t.key;state.focusMine=null;state.pendingStandin=null;state.view="team";persist();render()});
}
document.querySelectorAll(".nav button").forEach(b=>b.onclick=()=>{state.view=b.dataset.view;persist();render()});
document.querySelectorAll(".themeSwitch button").forEach(b=>b.onclick=()=>setTheme(b.dataset.theme));
const settingsBtn=document.querySelector(".settingsBtn"),settingsPanel=document.querySelector("#settingsPanel");
function setSettingsOpen(open){settingsPanel.hidden=!open;settingsBtn.setAttribute("aria-expanded",String(open))}
settingsBtn.onclick=()=>setSettingsOpen(settingsPanel.hidden);
document.addEventListener("click",e=>{if(!settingsPanel.hidden&&!e.target.closest(".settings"))setSettingsOpen(false)});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!settingsPanel.hidden){setSettingsOpen(false);settingsBtn.focus()}});
// Double-click a Lotus head in open space to spin it two full turns clockwise. Clicks on panels and
// controls are left alone, and the marks sit behind everything, so hit-test by position.
document.addEventListener("dblclick",e=>{if(currentTheme()!=="lotus"||e.target.closest("button,a,input,select,textarea,label,summary,.card,.tableWrap,.notice,.scorebug,.chip,.player,.heroRow,.gameRow,.teamsetup,.top,.settings"))return;const hit=[...document.querySelectorAll(".lotusMark")].find(m=>{const r=m.getBoundingClientRect();return e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom});if(!hit)return;hit.style.setProperty("--spin",((parseFloat(hit.style.getPropertyValue("--spin"))||0)+720)+"deg");const sel=window.getSelection();if(sel)sel.removeAllRanges()});
applyTheme();paintLeagueSwitch();paintSignedIn();
render();
</script>
</body></html>'''


ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOTUS_BG_PATH = os.path.join(ASSETS_DIR, "lotus_starfield.jpg")
LOTUS_MARK_PATH = os.path.join(ASSETS_DIR, "lotus_mark.png")

# Lotus heads as (center x, center y, width, rotation deg) on the same 1920x1280 grid the rifles in
# assets/build_lotus_background.py use, tucked into the gaps between them in the side margins.
# A 16:9 screen crops the grid's top and bottom ~140 rows, so heads stay inside y 300-1040.
LOTUS_MARKS = [
    (60, 420, 135, 20),
    (290, 600, 140, -8),
    (40, 760, 130, 15),
    (280, 1010, 140, -18),
    (1640, 330, 150, -10),
    (1880, 590, 130, 22),
    (1650, 800, 150, 12),
    (1850, 1020, 130, -15),
]


@functools.lru_cache(maxsize=None)
def _data_uri(path, mime):
    """Inline an asset so the page stays one file."""
    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
    except OSError:
        return ""
    return f"data:{mime};base64," + encoded


def _lotus_marks_html():
    return "".join(
        f'<i class="lotusMark" style="left:{x / 19.2:.2f}%;top:{y / 12.8:.2f}%;'
        f'width:{w / 19.2:.2f}%;--r:{r}deg"></i>'
        for x, y, w, r in LOTUS_MARKS
    )


def render_page(payload):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    page = (
        TEMPLATE.replace("__LOTUS_BG__", _data_uri(LOTUS_BG_PATH, "image/jpeg"))
        .replace("__LOTUS_MARK__", _data_uri(LOTUS_MARK_PATH, "image/png"))
        .replace("__LOTUS_MARKS__", _lotus_marks_html())
    )
    return page.replace("__DATA__", data)
