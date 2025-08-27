/* ============================================================================
   betkarma — Frontend Controller (pro-grade)
   - Robust state mgmt
   - Retry + backoff for fetch
   - URL param sync & localStorage persistence
   - Skeleton loading, empty states, accessible controls
   - Clean renderers for ML / Spread / Total with Diff coloring
   ========================================================================== */

(() => {
  // ---------------------------
  // DOM
  // ---------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const sportSelect = $("#sportSelect");
  const bookmakerSelect = $("#bookmakerSelect");
  const refreshBtn = $("#refreshBtn");
  const content = $("#content");
  const asOfEl = $("#asOf");
  const gameCardTpl = $("#gameCardTpl");

  // ---------------------------
  // Constants / Config
  // ---------------------------
  const LS_KEYS = {
    SPORT: "bk.selectedSport",
    BOOK: "bk.selectedBook",
  };

  const BACKOFF_MS = [0, 500, 1200]; // retry delays
  const DEFAULT_SPORT = "baseball_mlb";
  const DEFAULT_BOOK = "betonlineag";

  // ---------------------------
  // App State
  // ---------------------------
  const AppState = {
    sports: [],
    books: [],
    selectedSport: null,
    selectedBook: null,
    lastPayload: null,
    loading: false,
  };

  // ---------------------------
  // Utils
  // ---------------------------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function fetchJSON(url, opts = {}, attempt = 0) {
    try {
      const res = await fetch(url, {
        ...opts,
        headers: {
          "Accept": "application/json",
          ...(opts.headers || {}),
        },
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} ${text}`);
      }
      return res.json();
    } catch (err) {
      if (attempt < BACKOFF_MS.length - 1) {
        await sleep(BACKOFF_MS[attempt + 1]);
        return fetchJSON(url, opts, attempt + 1);
      }
      throw err;
    }
  }

  function setText(el, txt) {
    if (!el) return;
    el.textContent = txt == null ? "" : String(txt);
  }

  function savePrefs() {
    try {
      localStorage.setItem(LS_KEYS.SPORT, AppState.selectedSport || "");
      localStorage.setItem(LS_KEYS.BOOK, AppState.selectedBook || "");
    } catch {}
  }

  function loadPrefs() {
    try {
      const s = localStorage.getItem(LS_KEYS.SPORT);
      const b = localStorage.getItem(LS_KEYS.BOOK);
      return {
        sport: s || null,
        book: b || null,
      };
    } catch {
      return { sport: null, book: null };
    }
  }

  function updateURLParams() {
    const u = new URL(window.location.href);
    if (AppState.selectedSport) u.searchParams.set("sport", AppState.selectedSport);
    if (AppState.selectedBook) u.searchParams.set("bookmaker", AppState.selectedBook);
    history.replaceState(null, "", u.toString());
  }

  function readURLParams() {
    const u = new URL(window.location.href);
    return {
      sport: u.searchParams.get("sport"),
      book: u.searchParams.get("bookmaker"),
    };
  }

  function fmtSign(num) {
    if (num === null || num === undefined || Number.isNaN(num)) return "-";
    if (typeof num !== "number") num = Number(num);
    if (Number.isNaN(num)) return "-";
    return num > 0 ? `+${num}` : `${num}`;
  }

  function clsDiff(val) {
    if (typeof val !== "number" || Number.isNaN(val)) return "";
    if (val > 0) return "diff-pos";
    if (val < 0) return "diff-neg";
    return "";
  }

  function safeJoinPointAndPrice(point, price) {
    // For Spread/Total: show "point (price)" where price may be undefined
    const hasPoint = point !== null && point !== undefined;
    const hasPrice = price !== null && price !== undefined && `${price}` !== "";
    if (!hasPoint && !hasPrice) return "-";
    return hasPrice ? `${point ?? "-"} (${price})` : `${point ?? "-"}`;
  }

  function skeletonCards(count = 6) {
    const frag = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
      const section = document.createElement("section");
      section.className = "game-card skeleton";
      section.innerHTML = `
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
        </div>
      `;
      frag.appendChild(section);
    }
    return frag;
  }

  function showSkeleton() {
    AppState.loading = true;
    content.innerHTML = "";
    content.appendChild(skeletonCards(4));
    setText(asOfEl, "Loading…");
    refreshBtn.disabled = true;
    sportSelect.disabled = true;
    bookmakerSelect.disabled = true;
  }

  function clearSkeleton() {
    AppState.loading = false;
    refreshBtn.disabled = false;
    sportSelect.disabled = false;
    bookmakerSelect.disabled = false;
  }

  function showError(err) {
    content.innerHTML = `<div class="error">Error loading odds: ${escapeHTML(String(err))}</div>`;
  }

  function showEmpty() {
    content.innerHTML = `<div class="error">No games found for your selection.</div>`;
  }

  function escapeHTML(str) {
    return str
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  // ---------------------------
  // Renderers
  // ---------------------------
  function renderMoneylineRows(container, rows) {
    rows.forEach((r) => {
      const diffTxt = fmtSign(r.diff_price);
      const diffClass = clsDiff(r.diff_price);
      const html = `
        <div class="row" role="row">
          <div class="cell team" role="cell">${escapeHTML(r.team ?? "-")}</div>
          <div class="cell" role="cell">Open</div><div class="cell" role="cell">${r.open_price ?? "-"}</div>
          <div class="cell" role="cell">Live</div><div class="cell" role="cell">${r.live_price ?? "-"}</div>
          <div class="cell" role="cell">Diff</div><div class="cell ${diffClass}" role="cell">${diffTxt}</div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", html);
    });
  }

  function renderSpreadRows(container, rows) {
    rows.forEach((r) => {
      const openStr = safeJoinPointAndPrice(r.open_point, r.open_price);
      const liveStr = safeJoinPointAndPrice(r.live_point, r.live_price);
      const diffTxt = fmtSign(r.diff_point);
      const diffClass = clsDiff(r.diff_point);
      const html = `
        <div class="row" role="row">
          <div class="cell team" role="cell">${escapeHTML(r.team ?? "-")}</div>
          <div class="cell" role="cell">Open</div><div class="cell" role="cell">${openStr}</div>
          <div class="cell" role="cell">Live</div><div class="cell" role="cell">${liveStr}</div>
          <div class="cell" role="cell">Diff</div><div class="cell ${diffClass}" role="cell">${diffTxt}</div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", html);
    });
  }

  function renderTotalRows(container, rows) {
    rows.forEach((r) => {
      const openStr = safeJoinPointAndPrice(r.open_point, r.open_price);
      const liveStr = safeJoinPointAndPrice(r.live_point, r.live_price);
      const diffTxt = fmtSign(r.diff_point);
      const diffClass = clsDiff(r.diff_point);
      const html = `
        <div class="row" role="row">
          <div class="cell team" role="cell">${escapeHTML(r.team ?? "-")}</div>
          <div class="cell" role="cell">Open</div><div class="cell" role="cell">${openStr}</div>
          <div class="cell" role="cell">Live</div><div class="cell" role="cell">${liveStr}</div>
          <div class="cell" role="cell">Diff</div><div class="cell ${diffClass}" role="cell">${diffTxt}</div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", html);
    });
  }

  function renderGames(payload) {
    content.innerHTML = "";
    setText(asOfEl, `As of ${payload.as_of_est} — ${String(payload.bookmaker || "").toUpperCase()}`);

    const games = payload.games || [];
    if (games.length === 0) {
      showEmpty();
      return;
    }

    const frag = document.createDocumentFragment();

    for (const g of games) {
      const node = gameCardTpl.content.cloneNode(true);
      $(".matchup", node).textContent = `${g.away_team} @ ${g.home_team}`;
      $(".kickoff", node).textContent = g.commence_time_est || "";

      const marketContainers = $$(".market .rows", node);
      const mlContainer = marketContainers[0];
      const spContainer = marketContainers[1];
      const totContainer = marketContainers[2];

      renderMoneylineRows(mlContainer, g.moneyline || []);
      renderSpreadRows(spContainer, g.spreads || []);
      renderTotalRows(totContainer, g.totals || []);

      frag.appendChild(node);
    }

    content.appendChild(frag);
  }

  // ---------------------------
  // Loaders
  // ---------------------------
  async function loadSports() {
    const data = await fetchJSON("/sports");
    AppState.sports = data.sports || [];
    sportSelect.innerHTML = AppState.sports
      .map((s) => `<option value="${s.key}">${escapeHTML(s.label)}</option>`)
      .join("");

    // pick from URL param > localStorage > default
    const { sport: qsSport } = readURLParams();
    const { sport: lsSport } = loadPrefs();
    const pick =
      (qsSport && AppState.sports.some((s) => s.key === qsSport) && qsSport) ||
      (lsSport && AppState.sports.some((s) => s.key === lsSport) && lsSport) ||
      (AppState.sports[0] && AppState.sports[0].key) ||
      DEFAULT_SPORT;

    AppState.selectedSport = pick;
    sportSelect.value = pick;
  }

  async function loadBookmakers() {
    const data = await fetchJSON("/bookmakers");
    AppState.books = data.bookmakers || [];
    bookmakerSelect.innerHTML = AppState.books
      .map((b) => `<option value="${b}">${escapeHTML(b)}</option>`)
      .join("");

    const { book: qsBook } = readURLParams();
    const { book: lsBook } = loadPrefs();
    const pick =
      (qsBook && AppState.books.includes(qsBook) && qsBook) ||
      (lsBook && AppState.books.includes(lsBook) && lsBook) ||
      (AppState.books[0] || DEFAULT_BOOK);

    AppState.selectedBook = pick;
    bookmakerSelect.value = pick;
  }

  async function loadOdds({ refresh = false } = {}) {
    const sport = AppState.selectedSport || DEFAULT_SPORT;
    const bk = AppState.selectedBook || DEFAULT_BOOK;

    showSkeleton();
    try {
      const url = `/odds/${encodeURIComponent(sport)}?bookmaker=${encodeURIComponent(bk)}${
        refresh ? "&refresh=1" : ""
      }`;
      const payload = await fetchJSON(url);
      AppState.lastPayload = payload;
      renderGames(payload);
    } catch (err) {
      showError(err);
      console.error("[Odds] load error:", err);
    } finally {
      clearSkeleton();
    }
  }

  // ---------------------------
  // Events
  // ---------------------------
  refreshBtn.addEventListener("click", () => {
    loadOdds({ refresh: true });
  });

  sportSelect.addEventListener("change", () => {
    AppState.selectedSport = sportSelect.value;
    savePrefs();
    updateURLParams();
    loadOdds({ refresh: true });
  });

  bookmakerSelect.addEventListener("change", () => {
    AppState.selectedBook = bookmakerSelect.value;
    savePrefs();
    updateURLParams();
    loadOdds({ refresh: true });
  });

  // Keyboard shortcut: r to refresh
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() === "r" && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      refreshBtn.click();
    }
  });

  // ---------------------------
  // Init
  // ---------------------------
  (async function init() {
    try {
      // load meta first
      await Promise.all([loadSports(), loadBookmakers()]);
      // ensure URL matches state
      updateURLParams();
      // initial fetch
      await loadOdds({ refresh: true });
    } catch (err) {
      showError(err);
      console.error("[Init] error:", err);
    }
  })();
})();
