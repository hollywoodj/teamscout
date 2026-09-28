// Role observations remain estimates. Only usable observations from an exact
// five-player roster can establish regular-team flex; substitutions are separate.
function bumpRole(map,pos,win){
  const r=map.get(pos)||{position:pos,games:0,wins:0};
  r.games++;if(win)r.wins++;map.set(pos,r);
}
function roleList(map){return [...map.values()].sort((a,b)=>b.games-a.games||a.position-b.position)}
function isSupportPos(n){return n===4||n===5}
function roleLabel(pos){return `P${pos} ${POS[pos]}`}
function roleGameCount(n){return `${n} game${n===1?"":"s"}`}
function teamRoleBreakdown(inputGames,postedIds,replacedIds,roleAt=officialRoleAt){
  const idKey=id=>id!=null&&String(id)!=="0"&&String(id)!==""?String(id):null;
  const replaced=new Set([...replacedIds||[]].map(idKey).filter(Boolean));
  const posted=new Set([...postedIds||[]].map(idKey).filter(id=>id&&!replaced.has(id)));
  const rosterKnown=posted.size===5;
  // Repeated feed rows must not turn one occurrence into a pattern.
  const seenGames=new Set(),games=[];
  for(const g of inputGames||[]){
    if(g.match_id==null||seenGames.has(String(g.match_id)))continue;
    seenGames.add(String(g.match_id));
    const seenPlayers=new Set(),players=[];
    for(const p of g.players||[]){
      const id=idKey(p.id);
      if(id&&seenPlayers.has(id))continue;
      if(id)seenPlayers.add(id);
      players.push({...p,id});
    }
    games.push({...g,players});
  }
  const hasFormer=g=>g.players.some(p=>replaced.has(p.id));
  const currentGames=games.filter(g=>!hasFormer(g));
  const eraFallback=!!(replaced.size&&!currentGames.length);
  const roleGames=eraFallback?games:currentGames;
  const byPlayer=new Map(),heroes=new Map(),lineups=[];
  function player(p){
    const key=p.id||`unknown:${p.name||"Unknown"}`;
    if(!byPlayer.has(key))byPlayer.set(key,{id:p.id,name:p.name||"Unknown",games:0,classified:0,usable:0,uncertain:0,unclassified:0,full:0,standin:0,unknown:0,roles:new Map(),rolesFull:new Map(),rolesStandin:new Map(),usableRoles:new Map(),usableFull:new Map(),usableStandin:new Map()});
    const e=byPlayer.get(key);if(p.name)e.name=p.name;return e;
  }
  for(const g of roleGames){
    const complete=g.lineupKnown!==false&&g.players.length===5&&g.players.every(p=>p.id);
    const standins=g.players.filter(p=>p.id&&!posted.has(p.id)&&!replaced.has(p.id));
    const missing=[...posted].filter(id=>!g.players.some(p=>p.id===id));
    const context=hasFormer(g)?"historical":!rosterKnown||!complete?"unknown":missing.length?"standin":"full";
    const slots=g.players.map(p=>{
      const r=p.id?roleAt(Number(p.id),g.match_id)||{}:{};
      const position=Number(r.position),valid=[1,2,3,4,5].includes(position);
      const evidence=r.evidence||[];
      const usable=valid&&["high","medium"].includes(r.confidence)&&!(evidence.length===1&&evidence[0]==="hero profile");
      return {...p,position:valid?position:null,confidence:r.confidence||"none",usable,reason:!valid?"no position data":!usable?"weak role evidence":""};
    });
    // A collision is not a swap. Do not invent a second role to fill a vacancy.
    const positionCounts=new Map();
    for(const s of slots)if(s.usable)positionCounts.set(s.position,(positionCounts.get(s.position)||0)+1);
    for(const s of slots){
      if(s.usable&&positionCounts.get(s.position)>1){s.usable=false;s.reason="conflicting team positions"}
      const e=player(s);e.games++;if(context==="full")e.full++;else if(context==="standin")e.standin++;else e.unknown++;
      if(!s.position){e.unclassified++;continue}
      e.classified++;bumpRole(e.roles,s.position,g.win);
      if(context==="full")bumpRole(e.rolesFull,s.position,g.win);
      if(context==="standin")bumpRole(e.rolesStandin,s.position,g.win);
      if(s.usable){
        e.usable++;bumpRole(e.usableRoles,s.position,g.win);
        if(context==="full")bumpRole(e.usableFull,s.position,g.win);
        if(context==="standin")bumpRole(e.usableStandin,s.position,g.win);
      }else e.uncertain++;
    }
    lineups.push({match_id:g.match_id,slots,context,standins,missing});
  }
  // Show absent regulars too, so missing data cannot silently look like stability.
  for(const id of posted)if(!byPlayer.has(id))player({id,name:(byId.get(Number(id))||{}).name||`Player ${id}`});
  // Former players retain their history, but never establish current flex.
  for(const g of games)for(const p of g.players){
    if(!eraFallback&&replaced.has(p.id)){
      const e=player(p),r=roleAt(Number(p.id),g.match_id)||{};e.games++;
      if([1,2,3,4,5].includes(r.position)){e.classified++;bumpRole(e.roles,r.position,g.win)}else e.unclassified++;
    }
    if(!p.hero_id)continue;
    const h=heroes.get(p.hero_id)||{id:p.hero_id,games:0,players:new Map(),roles:new Set()};
    h.games++;
    const key=p.id||`unknown:${p.name}`,who=h.players.get(key)||{id:p.id,name:p.name||"Unknown",games:0};
    who.games++;h.players.set(key,who);heroes.set(p.hero_id,h);
  }
  for(const g of lineups)if(g.context!=="historical")for(const s of g.slots)if(s.usable&&posted.has(s.id)&&heroes.has(s.hero_id))heroes.get(s.hero_id).roles.add(s.position);
  const players=[...byPlayer.values()].map(e=>{
    for(const field of ["roles","rolesFull","rolesStandin","usableRoles","usableFull","usableStandin"])e[field]=roleList(e[field]);
    const fullN=e.usableFull.reduce((n,r)=>n+r.games,0);
    const base=fullN>=2?e.usableFull:e.usableRoles.length?e.usableRoles:e.roles;
    const primary=base[0]||null;
    const baselineEstablished=!!(fullN>=2&&primary.games>=2&&(!base[1]||primary.games>base[1].games));
    const repeated=e.usableFull.filter(r=>r.games>=2);
    const flexFull=repeated.length>=2;
    const supportFlex=flexFull&&repeated.every(r=>isSupportPos(r.position));
    const offFull=primary?e.usableFull.filter(r=>r.position!==primary.position):[];
    const offStandin=baselineEstablished?e.usableStandin.filter(r=>r.position!==primary.position):[];
    return {...e,primary,baselineEstablished,fullN,repeated,flexFull,supportFlex,offFull,offStandin,flexStandin:offStandin.length>0,posted:posted.has(e.id),replaced:replaced.has(e.id)};
  }).sort((a,b)=>(a.primary?.position||99)-(b.primary?.position||99)||b.games-a.games||a.name.localeCompare(b.name));
  const roster=players.filter(p=>p.posted),lookup=new Map(players.map(p=>[p.id,p]));
  const eventMap=new Map(),uncertainMap=new Map();
  for(const g of lineups){
    if(g.context==="historical")continue;
    for(const s of g.slots){
      const p=lookup.get(s.id);
      if(!p?.posted||!p.primary||s.position==null||s.position===p.primary.position)continue;
      // Stand-in differences need a main role established without stand-ins.
      const comparable=p.baselineEstablished||g.context==="full"&&p.flexFull;
      const uncertain=!s.usable||!comparable||g.context==="unknown";
      const context=uncertain?"uncertain":g.context;
      const map=uncertain?uncertainMap:eventMap,key=[s.id,p.primary.position,s.position,context].join(":");
      const e=map.get(key)||{id:s.id,name:p.name,from:p.primary.position,to:s.position,context,matches:[],occurrences:[],standins:new Set(),missing:new Set(),reasons:new Set(),partners:new Set()};
      e.matches.push(g.match_id);
      e.occurrences.push({match_id:g.match_id,standins:g.standins.map(x=>x.name||`Player ${x.id}`),missing:g.missing.map(id=>lookup.get(id)?.name||`Player ${id}`)});
      g.standins.forEach(x=>e.standins.add(x.name||`Player ${x.id}`));
      g.missing.forEach(id=>e.missing.add(lookup.get(id)?.name||`Player ${id}`));
      if(uncertain)e.reasons.add(s.reason||(!comparable?"main role not established":"incomplete or unknown lineup"));
      for(const other of g.slots){
        const op=lookup.get(other.id);
        if(other.id!==s.id&&other.usable&&op?.posted&&op.baselineEstablished&&other.position===p.primary.position&&op.primary.position===s.position)e.partners.add(op.name);
      }
      map.set(key,e);
    }
  }
  const serialize=e=>({...e,standins:[...e.standins],missing:[...e.missing],reasons:[...e.reasons],partners:[...e.partners],games:e.matches.length});
  const changes=[...eventMap.values()].map(serialize).sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name));
  const uncertainChanges=[...uncertainMap.values()].map(serialize).sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name));
  const countContext=context=>lineups.filter(g=>g.context===context).length;
  const fullGames=countContext("full"),standinGames=countContext("standin"),unknownGames=countContext("unknown");
  const changedCount=context=>new Set(changes.filter(e=>e.context===context).flatMap(e=>e.matches)).size;
  const fullChangeGames=changedCount("full"),standinChangeGames=changedCount("standin");
  const repeated=roster.filter(p=>p.flexFull);
  const stableSample=rosterKnown&&roster.every(p=>p.baselineEstablished&&p.fullN>=3&&p.fullN>=fullGames*.8);
  let verdict;
  if(eraFallback)verdict="No games without former players yet. These historical roles do not establish the current team's flex.";
  else if(!rosterKnown)verdict="A known five-player roster is needed to distinguish regular role changes from stand-ins.";
  else if(!fullGames)verdict="No complete full-roster games in this sample; regular-team flex is unproven.";
  else if(repeated.length){
    const kind=repeated.every(p=>p.supportFlex)?"Repeated support-role changes":"Repeated full-roster role changes";
    verdict=`${kind}: ${repeated.map(p=>`${p.name} (${p.repeated.map(r=>`${roleLabel(r.position)}: ${roleGameCount(r.games)}`).join(" / ")})`).join("; ")}.`;
  }else if(fullChangeGames)verdict=`Usable evidence shows role changes in ${roleGameCount(fullChangeGames)} with the full roster; no repeated flex pattern.`;
  else if(standinChangeGames)verdict=`Usable evidence shows role changes only in ${roleGameCount(standinChangeGames)} with stand-ins; no repeated full-roster flex shown.`;
  else if(stableSample)verdict=`Mostly settled roles across ${roleGameCount(fullGames)} with the full roster; no repeated flex shown.`;
  else verdict="No repeated flex established. The usable full-roster role sample is limited.";
  if(!eraFallback&&fullGames>0&&fullGames<4)verdict+=` Only ${roleGameCount(fullGames)} with all five regulars ${fullGames===1?"is":"are"} available.`;
  if(!eraFallback&&fullChangeGames&&standinChangeGames)verdict+=` Role changes also appear in ${roleGameCount(standinChangeGames)} with stand-ins.`;
  const flexHeroes=[...heroes.values()].filter(h=>h.players.size>1||h.roles.size>1).map(h=>{
    const who=[...h.players.values()].sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name));
    const currentWho=who.filter(p=>posted.has(p.id));
    const gone=currentWho.length<2&&who.some(p=>replaced.has(p.id));
    const label=h.roles.size>1?`Current players seen at ${[...h.roles].sort().map(p=>`P${p}`).join(" / ")}`:currentWho.length>=2?"Shared by regulars; no distinct roles established":gone?"Includes former players":"Sharing involves stand-ins or unknown players";
    return {...h,who,gone,label};
  }).sort((a,b)=>b.games-a.games||heroName(a.id).localeCompare(heroName(b.id)));
  const usable=roster.reduce((n,p)=>n+p.usable,0),observations=roster.reduce((n,p)=>n+p.games,0);
  return {players,posted,verdict,changes,uncertainChanges,flexHeroes,games:games.length,fullGames,standinGames,unknownGames,fullChangeGames,standinChangeGames,currentGames:currentGames.length,eraFallback,replacedCount:replaced.size,usable,observations};
}
function roleMix(p){return p.roles.map(r=>`${roleLabel(r.position)} ${r.games}`).join(" · ")||"unclassified"}
function teamRolesPanel(games,postedIds,replacedIds){
  const d=teamRoleBreakdown(games,postedIds,replacedIds),regulars=d.players.filter(p=>p.posted),gone=d.players.filter(p=>p.replaced),extras=d.players.filter(p=>!p.posted&&!p.replaced);
  function mix(roles){return roles.map(r=>`${roleLabel(r.position)}: ${roleGameCount(r.games)}`).join(" · ")||"No usable positions"}
  function playerBlock(p){
    const badge=p.primary?`<span class="posBadge">${p.flexFull&&!p.baselineEstablished?p.repeated.map(r=>r.position).join("/"):`P${p.primary.position}`}</span>`:`<span class="posBadge">—</span>`;
    const tag=p.replaced?"Former player":p.flexFull?"Repeated full-roster flex":p.flexStandin?"Role change with stand-ins":p.baselineEstablished?"Usual role established":"Main role tentative";
    const role=p.flexFull&&!p.baselineEstablished?`Repeated roles: ${p.repeated.map(r=>roleLabel(r.position)).join(" / ")}`:p.primary?`${p.baselineEstablished?"Usual":"Most seen"}: ${roleLabel(p.primary.position)}`:"No inferred role";
    const coverage=`${p.usable}/${p.games} usable role readings`;
    const detail=p.posted?`<div class="roleMix">Full roster (${p.full}g): ${E(mix(p.usableFull))}</div><div class="roleMix">With stand-ins (${p.standin}g): ${E(mix(p.usableStandin))}</div>`:"";
    const counts=p.replaced?`${p.games} historical games`:`${coverage}${p.uncertain?` · ${p.uncertain} uncertain`:""}${p.unclassified?` · ${p.unclassified} unclassified`:""}`;
    return `<div class="rolePlayer">${badge}<div><b>${E(p.name)}</b><div class="roleMix">${E(role)} · ${E(tag)}</div><div class="roleMix">${E(counts)}</div>${detail}<details class="roleMix"><summary>All inferred positions</summary>${E(roleMix(p))}</details></div></div>`;
  }
  function evidence(e){
    const kind=e.context==="standin"?"With stand-ins":e.context==="uncertain"?"Uncertain":e.games>=2?"Repeated with full roster":"Isolated with full roster";
    const context=[e.standins.length?`Stand-ins: ${e.standins.join(", ")}`:"",e.missing.length?`Absent regulars: ${e.missing.join(", ")}`:"",e.partners.length?`Reciprocal change seen with ${e.partners.join(", ")}`:"",e.reasons.join("; ")].filter(Boolean).join(" · ");
    const links=e.occurrences.map(o=>{
      const lineup=o.standins.length?` · with ${o.standins.join(", ")}${o.missing.length?`; absent: ${o.missing.join(", ")}`:""}`:"";
      return `<span><a target="_blank" rel="noopener" href="${E(dbMatchUrl(o.match_id))}">${E(o.match_id)}</a>${E(lineup)}</span>`;
    }).join("<br>");
    return `<div class="keyItem"><b>${E(e.name)}: ${E(roleLabel(e.from))} → ${E(roleLabel(e.to))}</b><p>${E(kind)} · ${roleGameCount(e.games)}${context?` · ${E(context)}`:""}</p><p>Matches: ${links}</p></div>`;
  }
  const roster=regulars.map(playerBlock).join("")||extras.map(playerBlock).join("");
  const goneBody=gone.length?`<div class="contentBlock"><h3>Replaced</h3><div class="roleRoster">${gone.map(playerBlock).join("")}</div></div>`:"";
  const extraBody=regulars.length&&extras.length?`<div class="contentBlock"><h3>Standins</h3><div class="roleRoster">${extras.map(playerBlock).join("")}</div></div>`:"";
  const wayBody=d.changes.length?`<div class="keysList">${d.changes.map(evidence).join("")}</div>`:`<div class="emptyAnalysis">No role changes established from usable positions and a full-roster baseline.</div>`;
  const uncertainBody=d.uncertainChanges.length?`<details class="contentBlock"><summary>Uncertain role differences (${d.uncertainChanges.length})</summary><p class="matchupCap">These do not count as flex. Check the linked games before treating them as role changes.</p><div class="keysList">${d.uncertainChanges.map(evidence).join("")}</div></details>`:"";
  const heroBody=d.flexHeroes.length?`<div class="flexHeroList">${d.flexHeroes.map(h=>`<div class="flexHero${h.gone?' gone':''}">${heroIcon(h.id,32)}<div><b>${E(heroName(h.id))}</b><small>${E(h.who.map(p=>`${p.name} ${p.games}g`).join(" · "))}</small><small>${E(h.label)}</small></div></div>`).join("")}</div>`:`<div class="emptyAnalysis">No shared heroes or heroes with multiple usable roles in this sample.</div>`;
  const era=d.replacedCount?(d.eraFallback?"historical sample only":`${d.currentGames} games without former players`):"";
  const cap=[`${d.games} official games`,era,`${d.fullGames} with all five regulars`,`${d.standinGames} with stand-ins`,d.unknownGames?`${d.unknownGames} with incomplete or unknown lineups`:"",`${d.usable}/${d.observations} usable regular-player role readings`].filter(Boolean).join(" · ");
  const method=`<details class="method"><summary>How to read roles and flex</summary><p>Positions are inferred from lane, hero, farm and wards. Low-confidence, hero-only and conflicting team positions remain visible but cannot establish flex. A regular player must have at least two usable games in each of two roles with all five regulars present to show repeated flex. One-off changes and games with stand-ins are listed separately. Stand-in changes compare against a role established in at least two full-roster games; they show an association, not why the player changed roles. Missing data cannot establish stability. Support lane changes may not reflect a true P4/P5 change.</p></details>`;
  return `<div class="card section"><p class="read">${E(d.verdict)}</p><p class="matchupCap">${E(cap)}</p>${method}<div class="roleRoster">${roster||'<div class="emptyAnalysis">No players in the official sample.</div>'}</div></div><div class="contentBlock"><h3>Role changes and evidence</h3>${wayBody}</div>${uncertainBody}${goneBody}${extraBody}<div class="contentBlock"><h3>Flex heroes</h3><p class="matchupCap">Sharing a hero does not by itself establish positional flex. Hero sharing includes the full official history.</p>${heroBody}</div>`;
}
