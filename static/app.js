const sportSelect = document.getElementById("sportSelect");
const bookmakerSelect = document.getElementById("bookmakerSelect");
const loadBtn = document.getElementById("loadBtn");
const cards = document.getElementById("cards");
const asOfText = document.getElementById("asOfText");
const dateChips = document.getElementById("dateChips");

let currentDayOffset = 0;

init();

async function init(){
  makeDateChips();
  await populateSports();
  await populateBookmakers();
  loadBtn.addEventListener("click", loadOdds);
  await loadOdds();
}

function makeDateChips(){
  // 6 chips: today + next 5 days
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

async function populateSports(){
  const r = await fetch("/sports");
  const data = await r.json();
  sportSelect.innerHTML = "";
  (data.sports || []).forEach(s=>{
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = labelizeSport(s);
    sportSelect.appendChild(opt);
  });
}

async function populateBookmakers(){
  const r = await fetch("/bookmakers");
  const data = await r.json();
  bookmakerSelect.innerHTML = "";
  (data.bookmakers || []).forEach(b=>{
    const opt = document.createElement("option");
    opt.value = b; opt.textContent = titleCase(b);
    bookmakerSelect.appendChild(opt);
  });
  if(data.default){
    bookmakerSelect.value = data.default;
  }
}

async function loadOdds(){
  cards.innerHTML = `<div class="badge">Loading…</div>`;
  try{
    const params = new URLSearchParams({
      sport: sportSelect.value,
      bookmaker: bookmakerSelect.value,
      day_offset: String(currentDayOffset)
    });
    const r = await fetch(`/odds?${params.toString()}`);
    const data = await r.json();
    if(!r.ok){
      throw new Error(data.error || "Failed to load odds");
    }
    renderOdds(data);
  }catch(err){
    cards.innerHTML = `<div class="badge">Error: ${err.message}</div>`;
  }
}

function renderOdds(payload){
  asOfText.textContent = `As of ${payload.as_of_est}, book: ${titleCase(payload.bookmaker)}`;
  const games = payload.games || [];
  if(games.length === 0){
    cards.innerHTML = `<div class="badge">No games found for selected day.</div>`;
    return;
  }

  cards.innerHTML = games.map(g => renderCard(g)).join("");
}

function renderCard(g){
  const home = safe(g.home_team);
  const away = safe(g.away_team);

  const mlRows = (g.moneyline || []).map(row => {
    const team = safe(row.team);
    const open = "—";
    const live = row.live_price ?? "—";
    const diff = "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${fmtNum(live)}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  const spreadRows = (g.spreads || []).map(row => {
    const team = safe(row.team);
    const open = "—";
    const lp = row.live_point;
    const lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${signed(lp)} (${fmtNum(lprice)})` : "—";
    const diff = "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${live}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  const totalRows = (g.totals || []).map(row => {
    const team = safe(row.team); // Over / Under
    const open = "—";
    const lp = row.live_point;
    const lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${lp} (${fmtNum(lprice)})` : "—";
    const diff = "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${live}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  return `
  <section class="card">
    <div class="card-header">
      <div class="card-title">${away}  @  ${home}</div>
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

function labelizeSport(key){
  const map = {
    americanfootball_ncaaf: "NCAAF",
    americanfootball_nfl: "NFL",
    baseball_mlb: "MLB",
    basketball_wnba: "WNBA",
    mma_mixed_martial_arts: "MMA",
  };
  return map[key] || key;
}

function titleCase(s){
  return s.replace(/[_-]/g," ").replace(/\b\w/g, c => c.toUpperCase());
}

function fmtNum(v){
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}
function signed(v){
  if (v === null || v === undefined) return "";
  const n = Number(v);
  return n > 0 ? `+${n}` : String(n);
}
function safe(s){ return (s ?? "").toString(); }
