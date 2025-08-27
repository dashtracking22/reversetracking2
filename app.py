import os
import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytz
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# -----------------------------
# Flask (serves ./static at / )
# -----------------------------
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

@app.route("/")
def root():
    return app.send_static_file("index.html")

@app.route("/styles.css")
def styles():
    return send_from_directory(app.static_folder, "styles.css", mimetype="text/css")

@app.route("/app.js")
def app_js():
    return send_from_directory(app.static_folder, "app.js", mimetype="application/javascript")

@app.get("/healthz")
def healthz():
    return "ok", 200

# -----------------------------
# Config
# -----------------------------
API_KEY = (os.getenv("API_KEY") or os.getenv("ODDS_API_KEY") or "").strip()

CACHE_SECONDS = 30
_cache: Dict[str, Dict[str, Any]] = {}

NY_TZ = pytz.timezone("America/New_York")

SPORTS = [
    {"key": "baseball_mlb", "label": "MLB"},
    {"key": "mma_mixed_martial_arts", "label": "MMA"},
    {"key": "basketball_wnba", "label": "WNBA"},
    {"key": "americanfootball_nfl", "label": "NFL"},
    {"key": "americanfootball_ncaaf", "label": "NCAAF"},
]

BOOKMAKERS = ["betonlineag", "draftkings", "fanduel", "caesars", "betmgm"]

DEFAULT_MARKETS = ["h2h", "spreads", "totals"]

UPSTASH_URL = (os.getenv("UPSTASH_REDIS_REST_URL", "") or "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "") or ""

REDIS_DEBUG = os.getenv("REDIS_DEBUG", "") in ("1", "true", "TRUE", "yes", "YES")
ODDS_DEBUG  = os.getenv("ODDS_DEBUG", "")  in ("1", "true", "TRUE", "yes", "YES")

_http = requests.Session()

def has_upstash() -> bool:
    ok = bool(UPSTASH_URL and UPSTASH_TOKEN)
    if REDIS_DEBUG and not ok:
        print("[REDIS] Missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN")
    return ok

def _redis_call(cmd: str, *args, params: Optional[dict] = None, method: str = "GET"):
    """
    Upstash REST helper. For simple commands (SET/GET/PING), use GET with path args.
    Returns the 'result' field or None on error.
    """
    if not has_upstash():
        return None
    try:
        cmd_path = cmd.upper()  # 'SET', 'GET', 'PING'
        url_parts = [UPSTASH_URL, cmd_path] + [requests.utils.quote(str(a), safe="") for a in args]
        url = "/".join(url_parts)
        headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
        if REDIS_DEBUG:
            print(f"[REDIS] {method} {url} params={params}")
        resp = _http.get(url, headers=headers, params=params, timeout=10)
        if REDIS_DEBUG:
            print(f"[REDIS] status={resp.status_code} body={resp.text[:300]}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("result")
    except Exception as e:
        if REDIS_DEBUG:
            print(f"[REDIS] ERROR: {e}")
        return None

def _opening_key(sport, book, event_id, market, side):
    # market: moneyline | spread | total
    # side: team_slug | over | under
    return f"opening:{sport}:{book}:{event_id}:{market}:{side}"

def save_opening_once(sport, book, event_id, side, market, price=None, point=None, ttl_days=60):
    """
    Save opening once with NX; avoid locking in blanks.
    Returns stored opening dict or None.
    """
    if not has_upstash():
        return None

    # Guard against nulls (prevents locking in bad openings)
    if market == "moneyline" and price is None:
        return None
    if market in ("spread", "total") and point is None:
        return None

    key = _opening_key(sport, book, event_id, market, side)
    payload = {"price": price, "point": point, "ts": int(time.time())}
    value = json.dumps(payload, separators=(",", ":"))  # compact JSON

    try:
        _redis_call("SET", key, value, params={"NX": "true", "EX": str(ttl_days * 24 * 3600)})
    except Exception as e:
        if REDIS_DEBUG:
            print(f"[REDIS] save_opening_once SET error: {e}")

    try:
        raw = _redis_call("GET", key)
        if isinstance(raw, str):
            return json.loads(raw)
        return raw if raw else None
    except Exception as e:
        if REDIS_DEBUG:
            print(f"[REDIS] save_opening_once GET error: {e}")
        return None

def compute_diff(current_price=None, current_point=None, opening=None):
    if not opening:
        return {"price_diff": None, "point_diff": None}
    price_diff = None
    point_diff = None
    try:
        if current_price is not None and opening.get("price") is not None:
            price_diff = float(current_price) - float(opening["price"])
    except Exception:
        pass
    try:
        if current_point is not None and opening.get("point") is not None:
            point_diff = float(current_point) - float(opening["point"])
    except Exception:
        pass
    return {"price_diff": price_diff, "point_diff": point_diff}

# -----------------------------
# Odds API
# -----------------------------
def _cache_key(*parts): return "|".join(str(p) for p in parts)

def get_cached(key):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] <= CACHE_SECONDS:
        return entry["data"]
    _cache.pop(key, None)
    return None

def set_cached(key, data): _cache[key] = {"ts": time.time(), "data": data}

def iso_to_est_str(iso_str):
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt_utc.astimezone(NY_TZ).strftime("%m/%d %I:%M %p")
    except Exception:
        return iso_str

def slug_team(name):
    return (name or "").lower().replace(" ", "_").replace(".", "").replace("'", "")

def fetch_odds(sport, bookmaker, markets):
    if not API_KEY:
        raise RuntimeError("Missing API_KEY/ODDS_API_KEY for The Odds API.")
    params = {
        "regions": "us",
        "markets": ",".join(markets),
        "bookmakers": bookmaker,
        "oddsFormat": "american",
        "dateFormat": "iso",
        "apiKey": API_KEY,
    }
    last_err_text = None
    for attempt, delay in [(1, 0.0), (2, 0.7), (3, 1.5)]:
        try:
            resp = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params=params, timeout=30,
            )
            if ODDS_DEBUG:
                remain = resp.headers.get("x-requests-remaining")
                used   = resp.headers.get("x-requests-used")
                print(f"[ODDS] attempt={attempt} status={resp.status_code} used={used} remaining={remain}")
                if resp.status_code != 200:
                    print(f"[ODDS] body: {resp.text[:500]}")
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err_text = resp.text
                time.sleep(delay); continue
            raise RuntimeError(f"Odds API error {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            last_err_text = str(e)
            if ODDS_DEBUG: print(f"[ODDS] network error attempt={attempt}: {e}")
            time.sleep(delay)
    raise RuntimeError(f"Odds API request failed after retries: {last_err_text or 'unknown error'}")

def pick_bookmaker_lines(bookmakers, want):
    return next((bm for bm in (bookmakers or []) if bm.get("key") == want), None)

def extract_market_outcomes(bm_data, market_key):
    for mk in bm_data.get("markets", []):
        if mk.get("key") == market_key:
            return mk
    return None

# -----------------------------
# API routes
# -----------------------------
@app.get("/sports")
def get_sports():
    return jsonify({"sports": SPORTS})

@app.get("/bookmakers")
def get_bookmakers():
    return jsonify({"bookmakers": BOOKMAKERS})

@app.get("/redis-ping")
def redis_ping():
    if not has_upstash():
        return jsonify({"ok": False, "pong": None, "error": "UPSTASH_REDIS_REST_URL/TOKEN not set"}), 503
    try:
        pong = _redis_call("PING")
        return jsonify({"ok": pong == "PONG", "pong": pong})
    except Exception as e:
        return jsonify({"ok": False, "pong": None, "error": str(e)}), 500

# Debug helpers (safe to keep; remove later if you want)
@app.get("/redis-selftest")
def redis_selftest():
    if not has_upstash():
        return jsonify({"ok": False, "error": "no_upstash"}), 503
    key = "selftest:hello"
    try:
        _redis_call("SET", key, json.dumps({"v":"world"}, separators=(",", ":")), params={"NX": "true", "EX": "120"})
        got = _redis_call("GET", key)
        return jsonify({"ok": True, "key": key, "value": got})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/redis-get/<path:key>")
def redis_get(key):
    val = _redis_call("GET", key)
    return jsonify({"key": key, "value": val})

@app.get("/odds/<sport>")
def odds_for_sport(sport):
    bookmaker = request.args.get("bookmaker", "betonlineag")
    if bookmaker not in BOOKMAKERS:
        bookmaker = "betonlineag"
    if sport not in {s["key"] for s in SPORTS}:
        return jsonify({"error": f"Unsupported sport '{sport}'"}), 400

    refresh = request.args.get("refresh") in ("1","true","TRUE","yes","YES")
    markets = ["h2h", "totals"] if sport == "mma_mixed_martial_arts" else DEFAULT_MARKETS

    ck = _cache_key("odds", sport, bookmaker, ",".join(markets))
    if not refresh:
        cached = get_cached(ck)
        if cached:
            return jsonify(cached)

    try:
        games = fetch_odds(sport, bookmaker, markets)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    results = []
    for game in games:
        event_id = game.get("id")
        bm_blob = pick_bookmaker_lines(game.get("bookmakers", []), bookmaker)
        if not bm_blob:
            continue

        item = {
            "event_id": event_id,
            "sport": sport,
            "bookmaker": bookmaker,
            "commence_time_est": iso_to_est_str(game.get("commence_time")),
            "commence_time_iso": game.get("commence_time"),  # <-- for front-end day filter
            "home_team": game.get("home_team"),
            "away_team": game.get("away_team"),
            "moneyline": [],
            "spreads": [],
            "totals": [],
        }

        # MONEYLINE
        h2h = extract_market_outcomes(bm_blob, "h2h")
        if h2h:
            for oc in h2h.get("outcomes", []):
                name, price = oc.get("name"), oc.get("price")
                side = slug_team(name or "")
                opening = save_opening_once(sport, bookmaker, event_id, side, "moneyline", price, None)
                diffs = compute_diff(price, None, opening)
                item["moneyline"].append({
                    "team": name,
                    "open_price": (opening or {}).get("price"),
                    "live_price": price,
                    "diff_price": diffs["price_diff"],
                })

        # SPREADS
        spreads = extract_market_outcomes(bm_blob, "spreads")
        if spreads:
            for oc in spreads.get("outcomes", []):
                name, price, point = oc.get("name"), oc.get("price"), oc.get("point")
                side = slug_team(name or "")
                opening = save_opening_once(sport, bookmaker, event_id, side, "spread", price, point)
                diffs = compute_diff(price, point, opening)
                item["spreads"].append({
                    "team": name,
                    "open_point": (opening or {}).get("point"),
                    "open_price": (opening or {}).get("price"),
                    "live_point": point,
                    "live_price": price,
                    "diff_point": diffs["point_diff"],
                })

        # TOTALS
        totals = extract_market_outcomes(bm_blob, "totals")
        if totals:
            for oc in totals.get("outcomes", []):
                nm = (oc.get("name") or "").lower()
                price, point = oc.get("price"), oc.get("point")
                side = "over" if "over" in nm else "under"
                opening = save_opening_once(sport, bookmaker, event_id, side, "total", price, point)
                diffs = compute_diff(price, point, opening)
                item["totals"].append({
                    "team": "Over" if side == "over" else "Under",
                    "open_point": (opening or {}).get("point"),
                    "open_price": (opening or {}).get("price"),
                    "live_point": point,
                    "live_price": price,
                    "diff_point": diffs["point_diff"],
                })

        results.append(item)

    payload = {
        "sport": sport,
        "bookmaker": bookmaker,
        "as_of_est": datetime.now(NY_TZ).strftime("%m/%d %I:%M %p"),
        "games": results,
    }
    set_cached(ck, payload)
    return jsonify(payload)

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=True)
