// app.js — Reverse Odds Tracker
const API_BASE = ""; // same origin on Render

const els = {
  sport: document.getElementById("sportSelect"),
  book: document.getElementById("bookmakerSelect"),
  customBookWrap: document.getElementById("customBookWrap"),
  customBookInput: document.getElementById("customBookInput"),
  refresh: document.getElementById("refreshBtn"),
  status: document.getElementById("status"),
  meta: document.getElementById("meta"),
  games: document.getElementById("games"),
  dayScroller: document.getElementById("dayScroller"),
};

function fmtOdd(n){if(n==null)return"—";const x=+n;if(isNaN(x))return"—";return x>0?`+${x}`:`${x}`;}
function fmtPoint(n){if(n==null)return"—";const x=+n;if(isNaN(x))return"—";return x>0?`+${x}`:`${x}`;}
function diffClass(n){if(n==null)return"zero";const x=+n;if(isNaN(x)||x===0)return"zero";return x>0?"pos":"neg";}
function fmtDiff(n){if(n==null)return"—";const x=+n;if(isNaN(x))return"—";return x>0?`+${x}`:`${x}`;}

async function fetchJSON(u){const r=await fetch(u);if(!r.ok)throw Error(`HTTP ${r.status}`);return r.json();}

async function loadSports(){const d=await fetchJSON(`${API_BASE}/sports`);els.sport.innerHTML="";for(const s of d.sports||[]){const o=document.createElement("option");o.value=s.key;o.textContent=s.label;els.sport.appendChild(o);}}

function setStatus(t){els.status.textContent=t;} function setMeta(t){els.meta.textContent=t;}
function setCustomBookVisibility(){const v=els.book.value;if(v==="custom"){els.customBookWrap.classList.remove("hidden");}else{els.customBookWrap.classList.add("hidden");els.customBookInput.value="";}}

function renderDayScroller(){els.dayScroller.innerHTML="";const now=new Date();for(let i=0;i<7;i++){const d=new Date(now);d.setDate(now.getDate()+i);const label=d.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"});const b=document.createElement("button");b.className=`day-pill${i===0?" active":""}`;b.textContent=label;b.type="button";b.onclick=()=>{document.querySelectorAll(".day-pill").forEach(el=>el.classList.remove("active"));b.classList.add("active");};els.dayScroller.appendChild(b);}}

function sectionHeaderRow(){return `<div class="grid"><div class="col-head">Team</div><div class="col-head">Open</div><div class="col-head">Live</div><div class="col-head">Diff</div></div>`;}

function renderGameCard(g){
  const ml=(g.moneyline||[]).map(r=>`<div class="grid"><div class="col">${r.team}</div><div class="col">${fmtOdd(r.open_price)}</div><div class="col">${fmtOdd(r.live_price)}</div><div class="col ${diffClass(r.diff_price)}">${fmtDiff(r.diff_price)}</div></div>`).join("");
  const sp=(g.spreads||[]).map(r=>{const o=r.open_point!=null?`${fmtPoint(r.open_point)} (${fmtOdd(r.open_price)})`:"—";const l=r.live_point!=null?`${fmtPoint(r.live_point)} (${fmtOdd(r.live_price)})`:"—";return `<div class="grid"><div class="col">${r.team}</div><div class="col">${o}</div><div class="col">${l}</div><div class="col ${diffClass(r.diff_point)}">${fmtDiff(r.diff_point)}</div></div>`;}).join("");
  const tot=(g.totals||[]).map(r=>{const o=r.open_point!=null?`${fmtPoint(r.open_point)} (${fmtOdd(r.open_price)})`:"—";const l=r.live_point!=null?`${fmtPoint(r.live_point)} (${fmtOdd(r.live_price)})`:"—";return `<div class="grid"><div class="col">${r.team}</div><div class="col">${o}</div><div class="col">${l}</div><div class="col ${diffClass(r.diff_point)}">${fmtDiff(r.diff_point)}</div></div>`;}).join("");
  return `<div class="game-card"><div class="game-header"><div class="matchup">${g.away_team} <span class="at">@</span> ${g.home_team}</div><div class="kick">${g.commence_time_est||""}</div></div><div class="section"><div class="section-title">Moneyline</div>${sectionHeaderRow()}${ml}</div><div class="section"><div class="section-title">Spread</div>${sectionHeaderRow()}${sp}</div><div class="section"><div class="section-title">Total</div>${sectionHeaderRow()}${tot}</div></div>`;}

async function loadOdds(){const sport=els.sport.value;let bm=els.book.value;if(bm==="custom")bm=els.customBookInput.value.trim()||"betonlineag";setStatus(`Loading ${sport} odds...`);els.games.innerHTML="";try{const d=await fetchJSON(`${API_BASE}/odds/${sport}?bookmaker=${bm}`);setMeta(`As of ${d.as_of_est}, book: ${d.bookmaker}`);setStatus("");els.games.innerHTML=d.games.map(renderGameCard).join("");}catch(e){console.error(e);setStatus("Error loading odds.");}}

function init(){loadSports();renderDayScroller();els.book.onchange=setCustomBookVisibility;els.refresh.onclick=loadOdds;}
document.addEventListener("DOMContentLoaded",init);
