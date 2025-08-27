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
  const data = await fetchJSON("/sports");
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
  const data = await fetchJSON("/bookmakers");
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
    const data = await fetchJSON(`/odds?${qs.toString()}`);
    render(data);
  }catch(err){
    cards.innerHTML = `<div class="badge">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ---- robust fetch / parse ----
async function fetchJSON(url, options){
  const r = await fetch(url, options);
  const text = await r.text();               // read raw body first
  let json;
  try { json = text ? JSON.parse(text) : null; } catch { json = null; }

  if (!r.ok) {
    const snippet = text ? text.slice(0, 400) : "(empty body)";
    const status = `${r.status} ${r.statusText}`;
    const serverErr = (json && json.error) ? json.error : snippet;
    throw new Error(`${status} — ${serverErr}`);
  }
  if (!json) throw new Error("Server returned an empty or non-JSON response.");
  return json;
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
    const open = fmt(row.open_price);
    const live = fmt(row.live_price);
    const diff = fmtSigned(row.diff_price);
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${live}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  const spreadRows = (g.spreads || []).map(row=>{
    const team = safe(row.team);
    const oPoint = row.open_point;
    const oPrice = row.open_price;
    const open = (oPoint != null)
      ? `${signed(oPoint)}${oPrice!=null?` (${fmt(oPrice)})`:``}`
      : "—";
    const lp = row.live_point, lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${signed(lp)} (${fmt(lprice)})` : "—";
    const diff = (row.diff_point != null) ? signed(row.diff_point) : "—";
    return `<tr>
      <td>${team}</td>
      <td class="num">${open}</td>
      <td class="num">${live}</td>
      <td class="num">${diff}</td>
    </tr>`;
  }).join("");

  const totalRows = (g.totals || []).map(row=>{
    const team = safe(row.team); // Over / Under
    const oPoint = row.open_point;
    const oPrice = row.open_price;
    const open = (oPoint != null)
      ? `${oPoint}${oPrice!=null?` (${fmt(oPrice)})`:``}`
      : "—";
    const lp = row.live_point, lprice = row.live_price;
    const live = (lp != null && lprice != null) ? `${lp} (${fmt(lprice)})` : "—";
    const diff = (row.diff_point != null) ? signed(row.diff_point) : "—";
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

/* ===== utils ===== */
function labelSport(key){
  const map = { baseball_mlb:"MLB", mma_mixed_martial_arts:"MMA", basketball_wnba:"WNBA", americanfootball_nfl:"NFL", americanfootball_ncaaf:"NCAAF" };
  return map[key] || key;
}
function titleCase(s){ return (s||"").replace(/[_-]/g," ").replace(/\b\w/g,c=>c.toUpperCase()); }
function fmt(v){ return (v === null || v === undefined || v === "") ? "—" : String(v); }
function fmtSigned(v){
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n > 0 ? `+${n}` : String(n);
}
function signed(v){
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n > 0 ? `+${stripTrailingZeros(n)}` : `${stripTrailingZeros(n)}`;
}
function stripTrailingZeros(n){
  return (Math.round(n) === n) ? n : Number(n.toFixed(1));
}
function safe(s){ return (s ?? "").toString(); }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
