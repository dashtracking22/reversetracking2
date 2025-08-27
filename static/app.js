// app.js — Reverse Odds Tracker (Redis-enabled backend)
// Renders Moneyline, Spreads, Totals with Open / Live / Diff
// Diff rules: Moneyline -> price delta; Spread/Total -> point delta only.

const API_BASE = ""; // same origin as your Flask service on Render

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

function fmtOdd(n) {
  if (n === null || n === undefined) return "—";
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return x > 0 ? `+${x}` : `${x}`;
}
function fmtPoint(n) {
  if (n === null || n === undefined) return "—";
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return x > 0 ? `+${x}` : `${x}`;
}
function diffClass(n) {
  if (n === null || n === undefined) return "zero";
  const x = Number(n);
  if (Number.isNaN(x) || x === 0) return "zero";
  return x > 0 ? "pos" : "neg";
}
function fmtDiff(n) {
  if (n === null || n === undefined) return "—";
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return x > 0 ? `+${x}` : `${x}`;
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function loadSports() {
  const data = await fetchJSON(`${API_BASE}/sports`);
  els.sport.innerHTML = "";
  for (const s of data.sports || []) {
    const opt = document.createElement("option");
    opt.value = s.key;
    opt.textContent = s.label;
    els.sport.appendChild(opt);
  }
}

function setStatus(text) {
  els.status.textContent = text;
}
function setMeta(text) {
  els.meta.textContent = text;
}

function setCustomBookVisibility() {
  const val = els.book.value;
  if (val === "custom") {
    els.customBookWrap.classList.remove("hidden");
  } else {
    els.customBookWrap.classList.add("hidden");
    els.customBookInput.value = "";
  }
}

function renderDayScroller() {
  els.dayScroller.innerHTML = "";
  const now = new Date();
  for (let i = 0; i < 7; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() + i);
    const label = d.toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric"
    });
    const btn = document.createElement("button");
    btn.className = `day-pill${i === 0 ? " active" : ""}`;
    btn.textContent = label;
    btn.type = "button";
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-pill").forEach(el => el.classList.remove("active"));
      btn.classList.add("active");
      // (Optional) Hook date filtering here later
    });
    els.dayScroller.appendChild(btn);
  }
}

function sectionHeaderRow() {
  return `
    <div class="grid">
      <div class="col-head">Team</div>
      <div class="col-head">Open</div>
      <div class="col-head">Live</div>
      <div class="col-head">Diff</div>
    </div>
  `;
}

function renderGameCard(g) {
  // Moneyline rows
  const mlRows = (g.moneyline || []).map(row => {
    const diff = row.diff_price;
    return `
      <div class="grid">
        <div class="col">${row.team ?? "—"}</div>
        <div class="col">${fmtOdd(row.open_price)}</div>
        <div class="col">${fmtOdd(row.live_price)}</div>
        <div class="col ${diffClass(diff)}">${fmtDiff(diff)}</div>
      </div>
    `;
  }).join("");

  // Spreads rows
  const spRows = (g.spreads || []).map(row => {
    const diff = row.diff_point;
    const open = row.open_point != null ? `${fmtPoint(row.open_point)} (${fmtOdd(row.open_price)})` : "—";
    const live = row.live_point != null ? `${fmtPoint(row.live_point)} (${fmtOdd(row.live_price)})` : "—";
    return `
      <div class="grid">
        <div class="col">${row.team ?? "—"}</div>
        <div class="col">${open}</div>
        <div class="col">${live}</div>
        <div class="col ${diffClass(diff)}">${fmtDiff(diff)}</div>
      </div>
    `;
  }).join("");

  // Totals rows
  const totRows = (g.totals || []).map(row => {
    const diff = row.diff_point;
    const open = row.open_point != null ? `${fmtPoint(row.open_point)} (${fmtOdd(row.open_price)})` : "—";
    const live = row.live_point != null ? `${fmtPoint(row.live_point)} (${fmtOdd(row.live_price)})` : "—";
    return `
      <div class="grid">
        <div class="col">${row.team ?? "—"}</div>
        <div class="col">${open}</div>
        <div class="col">${live}</div>
        <div class="col ${diffClass(diff)}">${fmtDiff(diff)}</div>
      </div>
    `;
  }).join("");

  return `
    <div class="game-card">
      <div class="game-header">
        <div class="matchup">${g.away_team} <span class="at">@</span> ${g.home_team}</div>
        <div class="kick">${g.commence_time_est || ""}</div>
      </div>

      <div class="section">
        <div class="section-title">Moneyline</div>
        ${sectionHeaderRow()}
        ${mlRows}
      </div>

      <div class="section">
        <div class="section-title">Spread</div>
        ${sectionHeaderRow()}
        ${spRows}
      </div>

      <div class="section">
        <div class="section-title">Total</div>
        ${sectionHeaderRow()}
        ${totRows}
      </div>
    </div>
  `;
}

async function loadOdds() {
  const sport = els.sport.value;
  let bookmaker = els.book.value;
  if (bookmaker === "custom") {
    bookmaker = els.customBookInput.value.trim() || "betonlineag";
  }
  setStatus(`Loading ${sport} odds from ${bookmaker}...`);
  els.games.innerHTML = "";

  try {
    const data = await fetchJSON(`${API_BASE}/odds/${sport}?bookmaker=${bookmaker}`);
    els.meta.textContent = `As of ${data.as_of_est}, book: ${data.bookmaker}`;
    els.status.textContent = "";
    els.games.innerHTML = data.games.map(renderGameCard).join("");
  } catch (err) {
    console.error(err);
    setStatus("Error loading odds.");
  }
}

function init() {
  loadSports();
  renderDayScroller();
  els.book.addEventListener("change", setCustomBookVisibility);
  els.refresh.addEventListener("click", loadOdds);
}

document.addEventListener("DOMContentLoaded", init);
