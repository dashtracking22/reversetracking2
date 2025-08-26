const sportSelect = document.getElementById("sportSelect");
const bookmakerSelect = document.getElementById("bookmakerSelect");
const customBookWrap = document.getElementById("customBookWrap");
const customBookInput = document.getElementById("customBookInput");
const refreshBtn = document.getElementById("refreshBtn");
const statusBox = document.getElementById("status");
const metaBox = document.getElementById("meta");
const gamesEl = document.getElementById("games");
const dayScroller = document.getElementById("dayScroller");

// Pretty labels for sport keys
const SPORT_LABELS = {
  baseball_mlb: "MLB",
  mma_mixed_martial_arts: "MMA",
  basketball_wnba: "WNBA",
  americanfootball_nfl: "NFL",
  americanfootball_ncaaf: "NCAAF",
};

// Allow opening index.html from disk while still calling the API
const API_BASE = location.origin.startsWith("file:") ? "http://127.0.0.1:5050" : "";

// --- state
let selectedDateKey = null;   // 'YYYY-MM-DD' local date key for filtering
let lastLoadedGames = [];     // cache latest fetch so changing day is instant

// --- helpers
const setStatus = (msg) => { statusBox.textContent = msg; };
const setMeta = (msg) => { metaBox.textContent = msg || ""; };
const fmtAmerican = (v) => v == null ? "-" : (v > 0 ? `+${v}` : `${v}`);
const fmtPoint = (v) => (v == null ? "-" : (Number(v) > 0 ? `+${Number(v)}` : `${Number(v)}`));
const fmtDiffPts = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}`);
const fmtISOToLocal = (iso) => {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
};
function localDateKeyFromISO(iso) {
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function localKeyFromDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

async function fetchJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch {
    throw new Error(`Non-JSON from ${url}: ${text.slice(0, 180)}`);
  }
  if (!res.ok) {
    const detail = json.error || JSON.stringify(json).slice(0, 180);
    throw new Error(`HTTP ${res.status} for ${url}: ${detail}`);
  }
  return json;
}

// --- init sports
async function initSports() {
  setStatus("Loading sports…");
  try {
    const data = await fetchJSON(`${API_BASE}/sports`);
    const sports = data.sports || [];
    sportSelect.innerHTML = "";
    for (const s of sports) {
      const opt = document.createElement("option");
      opt.value = s;                         // keep API key as value
      opt.textContent = SPORT_LABELS[s] || s; // show pretty label
      sportSelect.appendChild(opt);
    }
    setStatus("Pick a sport and click Load Odds");
  } catch (err) {
    sportSelect.innerHTML = `<option value="">(failed)</option>`;
    setStatus(`Failed to load sports → ${err.message}`);
  }
}

// --- day scroller
function buildDayScroller(days = 12) {
  dayScroller.innerHTML = "";
  const now = new Date();
  for (let i = 0; i < days; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() + i);
    const key = localKeyFromDate(d);
    const label = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

    const btn = document.createElement("button");
    btn.className = "day-pill";
    btn.setAttribute("role", "tab");
    btn.dataset.key = key;
    btn.textContent = label;
    btn.addEventListener("click", () => {
      setSelectedDay(key);
      renderGamesForSelectedDay();
    });
    dayScroller.appendChild(btn);
  }
  setSelectedDay(localKeyFromDate(now)); // today
}

function setSelectedDay(key) {
  selectedDateKey = key;
  Array.from(dayScroller.querySelectorAll(".day-pill")).forEach(btn => {
    btn.classList.toggle("active", btn.dataset.key === key);
  });
}

// --- rendering
function renderGameHTML(g) {
  const mlRows = g.moneyline ? Object.entries(g.moneyline).map(([team, v]) => {
    const diff = v.diff;
    const cls = typeof diff === "number" ? (diff < 0 ? "neg" : diff > 0 ? "pos" : "zero") : "";
    return `
      <div class="col">${team}</div>
      <div class="col">${fmtAmerican(v.open)}</div>
      <div class="col">${fmtAmerican(v.live)}</div>
      <div class="col ${cls}">${diff == null ? "-" : `${diff > 0 ? "+" : ""}${diff}`}</div>
    `;
  }).join("") : `<div class="col">—</div><div class="col">—</div><div class="col">—</div><div class="col">—</div>`;

  const spRows = g.spread ? Object.entries(g.spread).map(([team, v]) => {
    const d = v.diff_points;
    const cls = typeof d === "number" ? (d < 0 ? "neg" : d > 0 ? "pos" : "zero") : "";
    return `
      <div class="col">${team}</div>
      <div class="col">${fmtPoint(v.open_point)} (${fmtAmerican(v.open_price)})</div>
      <div class="col">${fmtPoint(v.live_point)} (${fmtAmerican(v.live_price)})</div>
      <div class="col ${cls}">${d == null ? "-" : fmtDiffPts(d)}</div>
    `;
  }).join("") : `<div class="col">—</div><div class="col">—</div><div class="col">—</div><div class="col">—</div>`;

  const tlRows = ["Over","Under"].map(side => {
    const v = g.total?.[side];
    if (!v) return "";
    const d = v.diff_points;
    const cls = typeof d === "number" ? (d < 0 ? "neg" : d > 0 ? "pos" : "zero") : "";
    return `
      <div class="col">${side}</div>
      <div class="col">${fmtPoint(v.open_point)} (${fmtAmerican(v.open_price)})</div>
      <div class="col">${fmtPoint(v.live_point)} (${fmtAmerican(v.live_price)})</div>
      <div class="col ${cls}">${d == null ? "-" : fmtDiffPts(d)}</div>
    `;
  }).join("") || `<div class="col">—</div><div class="col">—</div><div class="col">—</div><div class="col">—</div>`;

  return `
  <div class="game-card">
    <div class="game-header">
      <div class="matchup">
        <span class="away">${g.away || "TBD"}</span>
        <span class="at">@</span>
        <span class="home">${g.home || "TBD"}</span>
      </div>
      <div class="kick">Start: ${fmtISOToLocal(g.commence_time)}</div>
    </div>

    <div class="section">
      <div class="section-title">Moneyline</div>
      <div class="grid">
        <div class="col col-head">Side</div>
        <div class="col col-head">Open</div>
        <div class="col col-head">Live</div>
        <div class="col col-head">Diff</div>
        ${mlRows}
      </div>
    </div>

    <div class="section">
      <div class="section-title">Spread</div>
      <div class="grid">
        <div class="col col-head">Side</div>
        <div class="col col-head">Open</div>
        <div class="col col-head">Live</div>
        <div class="col col-head">Diff</div>
        ${spRows}
      </div>
    </div>

    <div class="section">
      <div class="section-title">Total</div>
      <div class="grid">
        <div class="col col-head">Side</div>
        <div class="col col-head">Open</div>
        <div class="col col-head">Live</div>
        <div class="col col-head">Diff</div>
        ${tlRows}
      </div>
    </div>
  </div>`;
}

function renderGamesForSelectedDay() {
  if (!lastLoadedGames.length) {
    gamesEl.innerHTML = "";
    setStatus("No games loaded yet.");
    return;
  }
  const filtered = selectedDateKey
    ? lastLoadedGames.filter(g => localDateKeyFromISO(g.commence_time) === selectedDateKey)
    : lastLoadedGames;

  if (!filtered.length) {
    gamesEl.innerHTML = "";
    setStatus("No games for that day (try another day or bookmaker).");
    setMeta("");
    return;
  }

  setStatus(`Showing ${filtered.length} game${filtered.length === 1 ? "" : "s"} for ${selectedDateKey}`);
  gamesEl.innerHTML = filtered.map(renderGameHTML).join("");
}

// --- loading odds
async function loadOdds() {
  let bookmaker = bookmakerSelect.value;
  if (bookmaker === "custom") {
    const custom = (customBookInput.value || "").trim();
    if (!custom) { setStatus("Enter a custom bookmaker or choose a preset."); return; }
    bookmaker = custom;
  }
  const sport = sportSelect.value;
  if (!sport) return setStatus("Pick a sport first.");

  gamesEl.innerHTML = "";
  setStatus(`Loading ${sport} from ${bookmaker}…`);
  setMeta("");

  const t0 = Date.now();
  try {
    const json = await fetchJSON(`${API_BASE}/odds/${encodeURIComponent(sport)}?bookmaker=${encodeURIComponent(bookmaker)}`);
    lastLoadedGames = json.results || [];
    const took = ((Date.now() - t0) / 1000).toFixed(1);
    setMeta(`Book: ${json.bookmaker} • Games: ${lastLoadedGames.length} • Loaded in ${took}s • ${new Date().toLocaleTimeString()}`);

    if (!lastLoadedGames.length) {
      setStatus(`No games/lines returned. Try a different bookmaker or sport.`);
      return;
    }
    renderGamesForSelectedDay();
  } catch (err) {
    setStatus(`Failed to load odds → ${err.message}`);
  }
}

// Toggle custom bookmaker input
bookmakerSelect.addEventListener("change", () => {
  const showCustom = bookmakerSelect.value === "custom";
  customBookWrap.classList.toggle("hidden", !showCustom);
  if (showCustom) customBookInput.focus();
});

// Events
refreshBtn.addEventListener("click", loadOdds);
window.addEventListener("DOMContentLoaded", () => {
  initSports();
  buildDayScroller(12); // today + 11 more days
});
