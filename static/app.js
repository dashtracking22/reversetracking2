// --------- DOM helpers ----------
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

// --------- Elements -------------
const sportSelect     = $("#sportSelect");
const bookmakerSelect = $("#bookmakerSelect");
const daysSelect      = $("#daysSelect");
const refreshBtn      = $("#refreshBtn");
const content         = $("#content");
const asOfEl          = $("#asOf");
const gameCardTpl     = $("#gameCardTpl");

// --------- State / prefs --------
const LS = {
  SPORT: "bk.sport",
  BOOK: "bk.book",
  DAYS: "bk.days"
};

const DEFAULTS = {
  sport: "baseball_mlb",
  book: "betonlineag",
  days: "all",
};

function savePrefs() {
  try {
    localStorage.setItem(LS.SPORT, sportSelect.value || "");
    localStorage.setItem(LS.BOOK, bookmakerSelect.value || "");
    localStorage.setItem(LS.DAYS, daysSelect.value || "all");
  } catch {}
}
function loadPrefs() {
  try {
    return {
      sport: localStorage.getItem(LS.SPORT) || null,
      book: localStorage.getItem(LS.BOOK) || null,
      days: localStorage.getItem(LS.DAYS) || null,
    };
  } catch { return { sport: null, book: null, days: null }; }
}

// --------- Fetch util -----------
async function fetchJSON(url) {
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${t}`);
  }
  return res.json();
}

// --------- Skeleton UI ----------
function skeletonCards(n = 4) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    const sec = document.createElement("section");
    sec.className = "game-card skeleton";
    sec.innerHTML = `
      <div class="game-head">
        <div class="matchup sk-bar"></div>
        <div class="kickoff sk-pill"></div>
      </div>
      <div class="markets">
        <div class="market">
          <h3>Moneyline</h3>
          <div class="rows">
            <div class="row"><div class="cell team sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div></div>
            <div class="row"><div class="cell team sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div></div>
          </div>
        </div>
        <div class="market"><h3>Spread</h3><div class="rows"><div class="row"><div class="cell team sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div></div></div></div>
        <div class="market"><h3>Total</h3><div class="rows"><div class="row"><div class="cell team sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div><div class="cell sk-pill"></div><div class="cell sk-bar"></div></div></div></div>
      </div>`;
    frag.appendChild(sec);
  }
  return frag;
}
function setLoading(on) {
  if (on) {
    content.innerHTML = "";
    content.appendChild(skeletonCards(4));
    asOfEl.textContent = "Loading…";
    refreshBtn.disabled = sportSelect.disabled = bookmakerSelect.disabled = daysSelect.disabled = true;
  } else {
    refreshBtn.disabled = sportSelect.disabled = bookmakerSelect.disabled = daysSelect.disabled = false;
  }
}

// --------- Render helpers -------
function esc(s) { return (s ?? "").toString()
  .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
  .replaceAll('"',"&quot;").replaceAll("'","&#39;"); }

function sign(v) {
  if (v === null || v === undefined) return "-";
  const n = Number(v); if (Number.isNaN(n)) return "-";
  return n > 0 ? `+${n}` : `${n}`;
}
function diffCls(v){
  if (typeof v !== "number" || Number.isNaN(v)) return "";
  return v > 0 ? "diff-pos" : v < 0 ? "diff-neg" : "";
}
function joinPointPrice(point, price) {
  const hasPoint = point !== null && point !== undefined;
  const hasPrice = price !== null && price !== undefined && `${price}` !== "";
  if (!hasPoint && !hasPrice) return "-";
  return hasPrice ? `${point ?? "-"} (${price})` : `${point ?? "-"}`;
}

// --------- Days filter ----------
function dayOffsetFromNow(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr);            // ISO → Date (UTC)
    const now = new Date();                // local
    // Normalize both to local midnight
    const localD = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const localNow = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diffMs = localD - localNow;
    return Math.round(diffMs / 86400000);
  } catch { return null; }
}

function filterByDays(games, mode) {
  if (mode === "all") return games;
  const want = Number(mode);
  return games.filter(g => {
    const off = dayOffsetFromNow(g.commence_time_iso);
    return off === want;
  });
}

// --------- Rendering ------------
function renderGames(payload) {
  content.innerHTML = "";
  asOfEl.textContent = `As of ${payload.as_of_est} — ${String(payload.bookmaker || "").toUpperCase()}`;

  let games = payload.games || [];
  games = filterByDays(games, daysSelect.value || "all");

  if (!games.length) {
    content.innerHTML = `<div class="error">No games for this selection.</div>`;
    return;
  }

  const frag = document.createDocumentFragment();
  for (const g of games) {
    const node = gameCardTpl.content.cloneNode(true);
    $(".matchup", node).textContent = `${g.away_team} @ ${g.home_team}`;
    $(".kickoff", node).textContent = g.commence_time_est || "";

    const containers = $$(".market .rows", node);
    const ml = containers[0], sp = containers[1], tot = containers[2];

    (g.moneyline || []).forEach(r => {
      ml.insertAdjacentHTML("beforeend", `
        <div class="row">
          <div class="cell team">${esc(r.team)}</div>
          <div class="cell">Open</div><div class="cell">${r.open_price ?? "-"}</div>
          <div class="cell">Live</div><div class="cell">${r.live_price ?? "-"}</div>
          <div class="cell">Diff</div><div class="cell ${diffCls(r.diff_price)}">${sign(r.diff_price)}</div>
        </div>`);
    });

    (g.spreads || []).forEach(r => {
      sp.insertAdjacentHTML("beforeend", `
        <div class="row">
          <div class="cell team">${esc(r.team)}</div>
          <div class="cell">Open</div><div class="cell">${joinPointPrice(r.open_point, r.open_price)}</div>
          <div class="cell">Live</div><div class="cell">${joinPointPrice(r.live_point, r.live_price)}</div>
          <div class="cell">Diff</div><div class="cell ${diffCls(r.diff_point)}">${sign(r.diff_point)}</div>
        </div>`);
    });

    (g.totals || []).forEach(r => {
      tot.insertAdjacentHTML("beforeend", `
        <div class="row">
          <div class="cell team">${esc(r.team)}</div>
          <div class="cell">Open</div><div class="cell">${joinPointPrice(r.open_point, r.open_price)}</div>
          <div class="cell">Live</div><div class="cell">${joinPointPrice(r.live_point, r.live_price)}</div>
          <div class="cell">Diff</div><div class="cell ${diffCls(r.diff_point)}">${sign(r.diff_point)}</div>
        </div>`);
    });

    frag.appendChild(node);
  }
  content.appendChild(frag);
}

// --------- Loaders --------------
async function loadSports() {
  const data = await fetchJSON("/sports");
  const sports = data.sports || [];
  sportSelect.innerHTML = sports.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join("");
  const prefs = loadPrefs();
  const pick = (prefs.sport && sports.some(s => s.key === prefs.sport) && prefs.sport) || (sports[0]?.key) || DEFAULTS.sport;
  sportSelect.value = pick;
}

async function loadBooks() {
  const data = await fetchJSON("/bookmakers");
  const books = data.bookmakers || [];
  bookmakerSelect.innerHTML = books.map(b => `<option value="${b}">${esc(b)}</option>`).join("");
  const prefs = loadPrefs();
  const pick = (prefs.book && books.includes(prefs.book) && prefs.book) || (books[0]) || DEFAULTS.book;
  bookmakerSelect.value = pick;
  daysSelect.value = loadPrefs().days || DEFAULTS.days;
}

async function loadOdds({ refresh = false } = {}) {
  const sport = sportSelect.value || DEFAULTS.sport;
  const book  = bookmakerSelect.value || DEFAULTS.book;
  const url = `/odds/${encodeURIComponent(sport)}?bookmaker=${encodeURIComponent(book)}${refresh ? "&refresh=1" : ""}`;

  setLoading(true);
  try {
    const payload = await fetchJSON(url);
    renderGames(payload);
  } catch (e) {
    console.error(e);
    content.innerHTML = `<div class="error">Error loading odds: ${String(e.message || e)}</div>`;
  } finally {
    setLoading(false);
  }
}

// --------- Events ---------------
refreshBtn.addEventListener("click", () => { savePrefs(); loadOdds({ refresh: true }); });
sportSelect.addEventListener("change", () => { savePrefs(); loadOdds({ refresh: true }); });
bookmakerSelect.addEventListener("change", () => { savePrefs(); loadOdds({ refresh: true }); });
daysSelect.addEventListener("change", () => { savePrefs(); loadOdds({ refresh: false }); });

document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() === "r" && !e.metaKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault(); refreshBtn.click();
  }
});

// --------- Init -----------------
(async function init(){
  try {
    await Promise.all([loadSports(), loadBooks()]);
    await loadOdds({ refresh: true });
  } catch (e) {
    console.error(e);
    content.innerHTML = `<div class="error">Startup failed: ${String(e.message || e)}</div>`;
  }
})();
