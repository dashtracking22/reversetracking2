const sportSelect = document.getElementById("sportSelect");
const bookmakerSelect = document.getElementById("bookmakerSelect");
const loadBtn = document.getElementById("loadBtn");
const cards = document.getElementById("cards");
const asOfText = document.getElementById("asOfText");
const dateChips = document.getElementById("dateChips");

let currentDayOffset = 0;

init();

async function init(){
  buildDateChips();
  await hydrateSports();
  await hydrateBookmakers();
  loadBtn.addEventListener("click", loadOdds);
  await loadOdds();
}

function buildDateChips(){
  dateChips.innerHTML = "";
  const now = new Date();
  for(let i=0;i<6;i++){
    const d = new Date(now.getTime() + i*24*3600*1000);
    const chip = document.createElement("button");
    chip.className = "chip" + (i===0 ? " active" : "");
    chip.textContent = d.toLocaleDateString(undefined, {weekday:"short", month:"short", day:"numeric"});
    chip.addEventListener("click", ()=>{
      currentDayOffset = i;
      [...dateChips.children].forEach(c=>c.classList.remove("active"));
      chip.classList.add("active");
      loadOdds();
    });
    dateChips.appendChild(chip);
  }
}

async function hydrateSports(){
  const r = await fetch("/sports");
  const data = await r.json();
  sportSelect.innerHTML = "";
  (data.sports || []).forEach(s=>{
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = labelSport(s);
    sportSelect.appendChild(opt);
  });
  if (data.default) sportSelect.value = data.default;
}

async function hydrateBookmakers(){
  const r = await fetch("/bookmakers");
  const data = await r.json();
  bookmakerSelect.innerHTML = "";
  (data.bookmakers || []).forEach(b=>{
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = titleCase(b);
    bookmakerSelect.appendChild(opt);
  });
  if (data.default) bookmakerSelect.value = data.default;
}

async function loadOdds(){
  cards.innerHTML = `<div class="badge">Loading…</div>`;
  try{
    const qs = new URLSearchParams({
      sport: sportSelect.value,
      bookmaker: bookmakerSelect.value,
      day_offset: String(currentDayOffset),
    });
    const r = await fetch(`/odds?${qs.toString()}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Failed to load odds");
    render(data);
  }catch(err){
    cards.innerHTML = `<div class="badge">Error: ${err.message}</div>`;
  }
}

function render(payload){
  asOfText.textContent = `As of ${payload.as_of_est}, book: ${titleCase(payload.bookmaker)}`;
  const games = payload.games || [];
  if (!games.length){
    cards.innerHTML = `<div class="badge">No games found for selected day.</div>`;
    return;
  }
  cards.innerHTML = games.map(renderCard).join("");
}

function renderCard(g){
  const away = safe(g.away_team);
  const home = safe(g.home_team);

  const mlRows = (g.moneyline || []).map(row=>{
    const team = safe(row.team);
    const open = "—";
    const live = fmt(row.live_price);
    const diff = "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${live}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  const spreadRows = (g.spreads || []).map(row=>{
    const team = safe(row.team);
    const lp = row.live_point, lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${signed(lp)} (${fmt(lprice)})` : "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">—</td>
      <td class="num">${live}</td>
      <td class="num">—</td>
    </tr>`;
  }).join("");

  const totalRows = (g.totals || []).map(row=>{
    const team = safe(row.team); // Over/Under
    const lp = row.live_point, lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${lp} (${fmt(lprice)})` : "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">—</td>
      <td class="num">${live}</td>
      <td class="num">—</td>
    </tr>`;
  }).join("");

  return `
  <section class="card">
    <div class="card-header">
      <div class="card-title">${away} @ ${home}</div>
      <div class="badge">${g.commence_time_est}</div>
    </div>

    <div class="section">
      <h4>MONEYLINE</h4>
      <table class="table">
        <thead><tr><th>Team</th><th>Open</th><th>Live</th><th>Diff</th></tr></thead>
        <tbody>${mlRows}</tbody>
      </table>
    </div>

    <div class="section">
      <h4>SPREAD</h4>
      <table class="table">
        <thead><tr><th>Team</th><th>Open</th><th>Live</th><th>Diff</th></tr></thead>
        <tbody>${spreadRows}</tbody>
      </table>
    </div>

    <div class="section">
      <h4>TOTAL</h4>
      <table class="table">
        <thead><tr><th>Team</th><th>Open</th><th>Live</th><th>Diff</th></tr></thead>
        <tbody>${totalRows}</tbody>
      </table>
    </div>
  </section>`;
}

/* utils */
function labelSport(key){
  const map = { americanfootball_ncaaf:"NCAAF", americanfootball_nfl:"NFL", baseball_mlb:"MLB", basketball_wnba:"WNBA", mma_mixed_martial_arts:"MMA" };
  return map[key] || key;
}
function titleCase(s){ return (s||"").replace(/[_-]/g," ").replace(/\b\w/g,c=>c.toUpperCase()); }
function fmt(v){ return (v === null || v === undefined || v === "") ? "—" : String(v); }
function signed(v){ if (v === null || v === undefined || v === "") return "—"; const n=Number(v); return Number.isNaN(n)?String(v): (n>0?`+${n}`:String(n)); }
function safe(s){ return (s ?? "").toString(); }
