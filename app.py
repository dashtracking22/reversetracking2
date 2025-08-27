import os
import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytz
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# =========================
# Flask setup
# =========================
app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("API_KEY", "").strip()

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

# =========================
# Upstash REST (Redis) setup
# =========================
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
_http = requests.Session()

def has_upstash() -> bool:
    return bool(UPSTASH_URL and UPSTASH_TOKEN)

def _redis_call(cmd: str, *args, params: Optional[dict] = None, method: str = "POST"):
    if not has_upstash():
        return None
    url_parts = [UPSTASH_URL, cmd] + [requests.utils.quote(str(a), safe="") for a in args]
    url = "/".join(url_parts)
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    resp = (_http.get if method.upper() == "GET" else _http.post)(
        url, headers=headers, params=params, timeout=10
    )
    resp.raise_for_status()
    return resp.json().get("result")

def _opening_key(sport, book, event_id, market, side):
    return f"opening:{sport}:{book}:{event_id}:{market}:{side}"

def save_opening_once(sport, book, event_id, side, market, price=None, point=None, ttl_days=60):
    if not has_upstash():
        return None
    key = _opening_key(sport, book, event_id, market, side)
    payload = {"price": price, "point": point, "ts": int(time.time())}
    try:
        params = {"NX": "true", "EX": str(ttl_days * 24 * 3600)}
        _redis_call("set", key, json.dumps(payload), params=params)
    except Exception:
        pass
    try:
        raw = _redis_call("get", key, method="GET")
        return json.loads(raw) if raw else None
    except Exception:
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

# =========================
# Odds API helpers
# =========================
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

def slug_team(name): return name.lower().replace(" ", "_").replace(".", "").replace("'", "")

def fetch_odds(sport, bookmaker, markets):
    if not API_KEY:
        raise RuntimeError("Missing API_KEY")
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
        params={
            "regions": "us", "markets": ",".join(markets),
            "bookmakers": bookmaker, "oddsFormat": "american",
            "dateFormat": "iso", "apiKey": API_KEY,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Odds API error {resp.status_code}: {resp.text}")
    return resp.json()

def pick_bookmaker_lines(bookmakers, want):
    return next((bm for bm in bookmakers or [] if bm.get("key") == want), None)

def extract_market_outcomes(bm_data, market_key):
    for mk in bm_data.get("markets", []):
        if mk.get("key") == market_key:
            return mk
    return None

# =========================
# Routes
# =========================
@app.get("/sports")
def get_sports(): return jsonify({"sports": SPORTS})

@app.get("/bookmakers")
def get_bookmakers(): return jsonify({"bookmakers": BOOKMAKERS})

@app.get("/redis-ping")
def redis_ping():
    try:
        return jsonify({"ok": True, "pong": _redis_call("ping", method="GET")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/odds/<sport>")
def odds_for_sport(sport):
    bookmaker = request.args.get("bookmaker", "betonlineag")
    if bookmaker not in BOOKMAKERS: bookmaker = "betonlineag"
    if sport not in {s["key"] for s in SPORTS}: return jsonify({"error": "Unsupported sport"}), 400
    markets = ["h2h", "totals"] if sport == "mma_mixed_martial_arts" else DEFAULT_MARKETS
    ck = _cache_key("odds", sport, bookmaker, ",".join(markets))
    cached = get_cached(ck)
    if cached: return jsonify(cached)
    try: games = fetch_odds(sport, bookmaker, markets)
    except Exception as e: return jsonify({"error": str(e)}), 502
    results = []
    for game in games:
        event_id = game.get("id")
        bm_blob = pick_bookmaker_lines(game.get("bookmakers", []), bookmaker)
        if not bm_blob: continue
        item = {
            "event_id": event_id, "sport": sport, "bookmaker": bookmaker,
            "commence_time_est": iso_to_est_str(game.get("commence_time")),
            "home_team": game.get("home_team"), "away_team": game.get("away_team"),
            "moneyline": [], "spreads": [], "totals": [],
        }
        # MONEYLINE
        h2h = extract_market_outcomes(bm_blob, "h2h")
        if h2h:
            for oc in h2h["outcomes"]:
                name, price = oc.get("name"), oc.get("price")
                side = slug_team(name or "")
                opening = save_opening_once(sport, bookmaker, event_id, side, "moneyline", price, None)
                diffs = compute_diff(price, None, opening)
                item["moneyline"].append({
                    "team": name, "open_price": opening.get("price") if opening else None,
                    "live_price": price, "diff_price": diffs["price_diff"]
                })
        # SPREADS
        spreads = extract_market_outcomes(bm_blob, "spreads")
        if spreads:
            for oc in spreads["outcomes"]:
                name, price, point = oc.get("name"), oc.get("price"), oc.get("point")
                side = slug_team(name or "")
                opening = save_opening_once(sport, bookmaker, event_id, side, "spread", price, point)
                diffs = compute_diff(price, point, opening)
                item["spreads"].append({
                    "team": name, "open_point": opening.get("point") if opening else None,
                    "open_price": opening.get("price") if opening else None,
                    "live_point": point, "live_price": price,
                    "diff_point": diffs["point_diff"]
                })
        # TOTALS
        totals = extract_market_outcomes(bm_blob, "totals")
        if totals:
            for oc in totals["outcomes"]:
                name, price, point = oc.get("name","").lower(), oc.get("price"), oc.get("point")
                side = "over" if "over" in name else "under"
                opening = save_opening_once(sport, bookmaker, event_id, side, "total", price, point)
                diffs = compute_diff(price, point, opening)
                item["totals"].append({
                    "team": "Over" if side=="over" else "Under",
                    "open_point": opening.get("point") if opening else None,
                    "open_price": opening.get("price") if opening else None,
                    "live_point": point, "live_price": price,
                    "diff_point": diffs["point_diff"]
                })
        results.append(item)
    payload = {"sport": sport, "bookmaker": bookmaker,
               "as_of_est": datetime.now(NY_TZ).strftime("%m/%d %I:%M %p"),
               "games": results}
    set_cached(ck, payload)
    return jsonify(payload)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=True)
