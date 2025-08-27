import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, Any
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Project structure:
#   app.py
#   static/
#     index.html
#     app.js
#     styles.css

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# ===== Odds API config =====
API_KEY = os.getenv("API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

ALLOWED_SPORTS = [
    "baseball_mlb",
    "mma_mixed_martial_arts",
    "basketball_wnba",
    "americanfootball_nfl",
    "americanfootball_ncaaf",
]
DEFAULT_SPORT = "baseball_mlb"

ALLOWED_BOOKMAKERS = ["draftkings", "betonlineag", "fanduel", "caesars"]
DEFAULT_BOOKMAKER = "draftkings"

# ===== Upstash Redis REST config =====
UPSTASH_URL = (os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""

def _redis_headers():
    return {"Authorization": f"Bearer {UPSTASH_TOKEN}"} if UPSTASH_TOKEN else {}

def redis_ping() -> Tuple[Optional[str], Optional[str]]:
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None, "Missing Upstash env vars"
    try:
        r = requests.get(f"{UPSTASH_URL}/PING", headers=_redis_headers(), timeout=8)
        r.raise_for_status()
        return r.json().get("result"), None
    except Exception as e:
        return None, str(e)

def redis_get(key: str) -> Tuple[Optional[str], Optional[str]]:
    """GET with URL-encoded key."""
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None, "Missing Upstash env vars"
    try:
        k = quote(key, safe="")
        r = requests.get(f"{UPSTASH_URL}/GET/{k}", headers=_redis_headers(), timeout=8)
        r.raise_for_status()
        return r.json().get("result"), None
    except Exception as e:
        return None, str(e)

def redis_setnx(key: str, value: Any, ex_seconds: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """SET key value NX with URL-encoded key & value. Returns True if created."""
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return False, "Missing Upstash env vars"
    try:
        k = quote(key, safe="")
        v = quote(str(value), safe="")
        url = f"{UPSTASH_URL}/SET/{k}/{v}?NX=1"
        if ex_seconds is not None:
            url += f"&EX={int(ex_seconds)}"
        r = requests.get(url, headers=_redis_headers(), timeout=8)
        r.raise_for_status()
        return r.json().get("result") == "OK", None
    except Exception as e:
        return False, str(e)

# ===== Helpers for openings =====
OPEN_TTL = 7 * 24 * 3600  # 7 days

def key_ml(sport: str, event_id: str, team: str) -> str:
    return f"opening:{sport}:{event_id}:h2h:{team}"

def key_spread_point(sport: str, event_id: str, team: str) -> str:
    return f"opening:{sport}:{event_id}:spread_point:{team}"

def key_spread_price(sport: str, event_id: str, team: str) -> str:
    return f"opening:{sport}:{event_id}:spread_price:{team}"

def key_total_point(sport: str, event_id: str, ou_label: str) -> str:  # 'Over' or 'Under'
    return f"opening:{sport}:{event_id}:total_point:{ou_label}"

def key_total_price(sport: str, event_id: str, ou_label: str) -> str:
    return f"opening:{sport}:{event_id}:total_price:{ou_label}"

def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    # try numeric → allow "+110" form
    for candidate in (val, str(val).replace("+", "")):
        try:
            return float(candidate)
        except Exception:
            pass
    return None

def get_or_set_opening(key: str, current_value: Optional[Any]) -> Optional[float]:
    """
    Returns opening value (float) for a key.
    If none exists and current_value is provided, writes it NX and returns it.
    """
    existing, err = redis_get(key)
    if err is None and existing is not None:
        return _to_float(existing)

    if current_value is None:
        return None

    # Write-if-not-exists (NX)
    redis_setnx(key, current_value, ex_seconds=OPEN_TTL)
    stored, _ = redis_get(key)
    return _to_float(stored)

# ===== Static root =====
@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")

# ===== Dropdown data =====
@app.route("/sports")
def sports():
    return jsonify({"sports": ALLOWED_SPORTS, "default": DEFAULT_SPORT})

@app.route("/bookmakers")
def bookmakers():
    return jsonify({"bookmakers": ALLOWED_BOOKMAKERS, "default": DEFAULT_BOOKMAKER})

# ===== Odds endpoint (populates opening + diff) =====
@app.route("/odds")
def odds():
    if not API_KEY:
        return jsonify({"error": "Missing API_KEY environment variable"}), 500

    sport = request.args.get("sport", DEFAULT_SPORT)
    if sport not in ALLOWED_SPORTS:
        return jsonify({"error": f"Unsupported sport: {sport}"}), 400

    bookmaker = request.args.get("bookmaker", DEFAULT_BOOKMAKER)
    if bookmaker not in ALLOWED_BOOKMAKERS:
        return jsonify({"error": f"Unsupported bookmaker: {bookmaker}"}), 400

    try:
        day_offset = int(request.args.get("day_offset", "0"))
        day_offset = max(0, min(day_offset, 30))
    except ValueError:
        day_offset = 0

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "bookmakers": bookmaker,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }

    try:
        resp = requests.get(f"{BASE_URL}/sports/{sport}/odds", params=params, timeout=25)
        resp.raise_for_status()
        events = resp.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Error loading odds: {e}"}), 500

    et = ZoneInfo("America/New_York")
    start_day = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_day = start_day + timedelta(days=1)

    def in_window(iso_str: str) -> bool:
        try:
            dt_et = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(et)
            return start_day <= dt_et < end_day
        except Exception:
            return False

    games = []
    for ev in events:
        if not in_window(ev.get("commence_time", "")):
            continue

        bm = next((b for b in ev.get("bookmakers", []) if b.get("key") == bookmaker), None)
        if not bm:
            continue

        mkts = bm.get("markets", [])

        # Extractors
        def get_h2h(mkts_local):
            d = {}
            for m in mkts_local:
                if m.get("key") == "h2h":
                    for o in m.get("outcomes", []):
                        d[o.get("name")] = o.get("price")
            return d

        def get_spreads(mkts_local):
            d = {}
            for m in mkts_local:
                if m.get("key") == "spreads":
                    for o in m.get("outcomes", []):
                        d[o.get("name")] = {"point": o.get("point"), "price": o.get("price")}
            return d

        def get_totals(mkts_local):
            arr = []
            for m in mkts_local:
                if m.get("key") == "totals":
                    for o in m.get("outcomes", []):
                        arr.append({"team": o.get("name"), "point": o.get("point"), "price": o.get("price")})
            if len(arr) == 2:
                arr.sort(key=lambda x: 0 if (x["team"] or "").lower().startswith("over") else 1)
            return arr

        h2h = get_h2h(mkts)
        spreads = get_spreads(mkts)
        totals = get_totals(mkts)

        try:
            dt_et = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(et)
            kickoff_est = dt_et.strftime("%m/%d %I:%M %p")
        except Exception:
            kickoff_est = ""

        away = ev.get("away_team")
        home = ev.get("home_team")
        event_id = ev.get("id")

        # ---- Moneyline opening + diff (American odds delta) ----
        ml_rows = []
        for team in [away, home]:
            live_price = h2h.get(team)
            open_price = None
            diff_price = None
            if team is not None:
                k = key_ml(sport, event_id, team)
                open_price = get_or_set_opening(k, live_price)
                if open_price is not None and live_price is not None:
                    try:
                        diff_price = int(live_price) - int(open_price)
                    except Exception:
                        diff_price = None
            ml_rows.append({
                "team": team,
                "open_price": open_price,
                "live_price": live_price,
                "diff_price": diff_price
            })

        # ---- Spread opening + diff (points only) ----
        sp_rows = []
        for team in [away, home]:
            row = spreads.get(team) or {}
            lp = row.get("point")
            lprice = row.get("price")
            open_point = None
            if team is not None:
                kp = key_spread_point(sport, event_id, team)
                open_point = get_or_set_opening(kp, lp)
                # store price too for completeness
                kpp = key_spread_price(sport, event_id, team)
                _ = get_or_set_opening(kpp, lprice)

            diff_point = None
            if open_point is not None and lp is not None:
                try:
                    diff_point = float(lp) - float(open_point)
                except Exception:
                    diff_point = None

            sp_rows.append({
                "team": team,
                "open_point": open_point,
                "open_price": None,    # not used in diff now
                "live_point": lp,
                "live_price": lprice,
                "diff_point": diff_point
            })

        # ---- Totals opening + diff (points only) ----
        tot_rows = []
        for row in totals:
            ou_lab = row.get("team")  # "Over" or "Under"
            lp = row.get("point")
            lprice = row.get("price")
            open_point = None
            if ou_lab:
                ktp = key_total_point(sport, event_id, ou_lab)
                open_point = get_or_set_opening(ktp, lp)
                # also store price
                ktpr = key_total_price(sport, event_id, ou_lab)
                _ = get_or_set_opening(ktpr, lprice)

            diff_point = None
            if open_point is not None and lp is not None:
                try:
                    diff_point = float(lp) - float(open_point)
                except Exception:
                    diff_point = None

            tot_rows.append({
                "team": ou_lab,
                "open_point": open_point,
                "open_price": None,
                "live_point": lp,
                "live_price": lprice,
                "diff_point": diff_point
            })

        games.append({
            "event_id": event_id,
            "sport": sport,
            "away_team": away,
            "home_team": home,
            "commence_time_est": kickoff_est,
            "bookmaker": bookmaker,
            "moneyline": ml_rows,
            "spreads": sp_rows,
            "totals": tot_rows,
        })

    return jsonify({
        "as_of_est": datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d %I:%M %p"),
        "bookmaker": bookmaker,
        "sport": sport,
        "games": games,
    })

# ===== Seed openings now (force-write NX) =====
@app.route("/seed_openings", methods=["POST"])
def seed_openings():
    if not API_KEY:
        return jsonify({"error": "Missing API_KEY"}), 500

    sport = request.values.get("sport", DEFAULT_SPORT)
    bookmaker = request.values.get("bookmaker", DEFAULT_BOOKMAKER)
    try:
        day_offset = int(request.values.get("day_offset", "0"))
        day_offset = max(0, min(day_offset, 30))
    except ValueError:
        day_offset = 0

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "bookmakers": bookmaker,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }

    try:
        r = requests.get(f"{BASE_URL}/sports/{sport}/odds", params=params, timeout=12)
        r.raise_for_status()
        events = r.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Odds API error: {e}"}), 502

    et = ZoneInfo("America/New_York")
    start_day = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_day = start_day + timedelta(days=1)

    def in_window(iso_str: str) -> bool:
        try:
            dt_et = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(et)
            return start_day <= dt_et < end_day
        except Exception:
            return False

    def get_h2h(mkts_local):
        d = {}
        for m in mkts_local:
            if m.get("key") == "h2h":
                for o in m.get("outcomes", []):
                    d[o.get("name")] = o.get("price")
        return d

    def get_spreads(mkts_local):
        d = {}
        for m in mkts_local:
            if m.get("key") == "spreads":
                for o in m.get("outcomes", []):
                    d[o.get("name")] = {"point": o.get("point"), "price": o.get("price")}
        return d

    def get_totals(mkts_local):
        arr = []
        for m in mkts_local:
            if m.get("key") == "totals":
                for o in m.get("outcomes", []):
                    arr.append({"team": o.get("name"), "point": o.get("point"), "price": o.get("price")})
        return arr

    seeded = 0
    scanned = 0

    for ev in events:
        if not in_window(ev.get("commence_time", "")):
            continue
        bm = next((b for b in ev.get("bookmakers", []) if b.get("key") == bookmaker), None)
        if not bm:
            continue
        scanned += 1
        mkts = bm.get("markets", [])
        h2h = get_h2h(mkts)
        spreads = get_spreads(mkts)
        totals = get_totals(mkts)

        event_id = ev.get("id")
        away = ev.get("away_team")
        home = ev.get("home_team")

        # Moneyline openings
        for team in [away, home]:
            if team and h2h.get(team) is not None:
                created, _ = redis_setnx(key_ml(sport, event_id, team), str(h2h[team]), ex_seconds=OPEN_TTL)
                if created:
                    seeded += 1

        # Spreads (points)
        for team in [away, home]:
            if not team:
                continue
            row = spreads.get(team) or {}
            if row.get("point") is not None:
                created, _ = redis_setnx(key_spread_point(sport, event_id, team), str(row["point"]), ex_seconds=OPEN_TTL)
                if created:
                    seeded += 1

        # Totals (points)
        for row in totals:
            ou = row.get("team")
            p = row.get("point")
            if ou and p is not None:
                created, _ = redis_setnx(key_total_point(sport, event_id, ou), str(p), ex_seconds=OPEN_TTL)
                if created:
                    seeded += 1

    return jsonify({
        "ok": True,
        "sport": sport,
        "bookmaker": bookmaker,
        "day_offset": day_offset,
        "scanned_games": scanned,
        "seeded_fields": seeded
    }), 200

# ===== Debug =====
@app.route("/debug/redis/ping")
def debug_ping():
    res, err = redis_ping()
    if err:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "result": res})

@app.route("/debug/redis/get")
def debug_get():
    k = request.args.get("key")
    if not k:
        return jsonify({"error": "key is required"}), 400
    res, err = redis_get(k)
    if err:
        return jsonify({"error": err}), 500
    return jsonify({"key": k, "result": res})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=True)
