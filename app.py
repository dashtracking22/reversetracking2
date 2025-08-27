import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Structure:
# app.py
# static/
#   index.html
#   app.js
#   styles.css

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

# ===== Odds API config =====
API_KEY = os.getenv("API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

ALLOWED_SPORTS = [
    "americanfootball_ncaaf",
    "americanfootball_nfl",
    "baseball_mlb",
    "basketball_wnba",
    "mma_mixed_martial_arts",
]
DEFAULT_SPORT = "americanfootball_ncaaf"

ALLOWED_BOOKMAKERS = ["draftkings", "betonlineag", "fanduel", "caesars"]
DEFAULT_BOOKMAKER = "draftkings"

# ===== Upstash Redis REST config (single-line test) =====
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")  # e.g. https://xxxxx.upstash.io
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

def _redis_headers():
    return {"Authorization": f"Bearer {UPSTASH_TOKEN}"} if UPSTASH_TOKEN else {}

def redis_get(key: str):
    """GET key from Upstash REST."""
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None, "Missing Upstash env vars"
    try:
        r = requests.get(f"{UPSTASH_URL}/GET/{key}", headers=_redis_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()  # {"result":"..."} or {"result": None}
        return data.get("result"), None
    except Exception as e:
        return None, str(e)

def redis_setnx(key: str, value: str, ex: int | None = None):
    """
    SET key value with NX via Upstash REST.
    ex = seconds to expire (optional). Returns (created: bool, err: str|None)
    """
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return False, "Missing Upstash env vars"
    try:
        # Build URL with NX and optional EX
        url = f"{UPSTASH_URL}/SET/{key}/{value}?NX=1"
        if ex is not None:
            url += f"&EX={int(ex)}"
        r = requests.get(url, headers=_redis_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()  # {"result":"OK"} if set, or {"result": None} if NX prevented write
        created = (data.get("result") == "OK")
        return created, None
    except Exception as e:
        return False, str(e)

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

# ===== Odds endpoint (unchanged display baseline) =====
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

        def get_h2h(mkts):
            d = {}
            for m in mkts:
                if m.get("key") == "h2h":
                    for o in m.get("outcomes", []):
                        d[o.get("name")] = o.get("price")
            return d

        def get_spreads(mkts):
            d = {}
            for m in mkts:
                if m.get("key") == "spreads":
                    for o in m.get("outcomes", []):
                        d[o.get("name")] = {"point": o.get("point"), "price": o.get("price")}
            return d

        def get_totals(mkts):
            arr = []
            for m in mkts:
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

        games.append({
            "event_id": ev.get("id"),
            "sport": sport,
            "away_team": away,
            "home_team": home,
            "commence_time_est": kickoff_est,
            "bookmaker": bookmaker,
            "moneyline": [
                {"team": away, "open_price": None, "live_price": h2h.get(away), "diff_price": None},
                {"team": home, "open_price": None, "live_price": h2h.get(home), "diff_price": None},
            ],
            "spreads": [
                {"team": away, "open_point": None, "open_price": None,
                 "live_point": (spreads.get(away) or {}).get("point"),
                 "live_price": (spreads.get(away) or {}).get("price"),
                 "diff_point": None},
                {"team": home, "open_point": None, "open_price": None,
                 "live_point": (spreads.get(home) or {}).get("point"),
                 "live_price": (spreads.get(home) or {}).get("price"),
                 "diff_point": None},
            ],
            "totals": [
                {"team": row.get("team"),
                 "open_point": None, "open_price": None,
                 "live_point": row.get("point"), "live_price": row.get("price"),
                 "diff_point": None}
                for row in totals
            ],
        })

    return jsonify({
        "as_of_est": datetime.now(et).strftime("%m/%d %I:%M %p"),
        "bookmaker": bookmaker,
        "sport": sport,
        "games": games,
    })

# ===== SINGLE-LINE OPENING CAPTURE =====
@app.route("/opening_sample", methods=["POST"])
def opening_sample():
    """
    Capture ONE opening line to Redis using SET NX:
      - Picks first event for sport/bookmaker/day_offset
      - Stores away team's h2h price (opening) if not already set
    Body/Query: sport, bookmaker, day_offset (optional)
    """
    if not API_KEY:
        return jsonify({"error": "Missing API_KEY"}), 500
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return jsonify({"error": "Missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN"}), 500

    sport = request.values.get("sport", DEFAULT_SPORT)
    bookmaker = request.values.get("bookmaker", DEFAULT_BOOKMAKER)
    try:
        day_offset = int(request.values.get("day_offset", "0"))
        day_offset = max(0, min(day_offset, 30))
    except ValueError:
        day_offset = 0

    # Pull odds (same as /odds but we only need one line)
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h",
        "bookmakers": bookmaker,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    try:
        resp = requests.get(f"{BASE_URL}/sports/{sport}/odds", params=params, timeout=20)
        resp.raise_for_status()
        events = resp.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Odds fetch failed: {e}"}), 500

    # Window filter (today+offset in ET)
    et = ZoneInfo("America/New_York")
    start_day = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_day = start_day + timedelta(days=1)

    def in_window(iso_str: str) -> bool:
        try:
            dt_et = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(et)
            return start_day <= dt_et < end_day
        except Exception:
            return False

    # Find first suitable event + away team h2h price
    event = None
    h2h_price = None
    team = None

    for ev in events:
        if not in_window(ev.get("commence_time", "")):
            continue
        bm = next((b for b in ev.get("bookmakers", []) if b.get("key") == bookmaker), None)
        if not bm:
            continue
        for m in bm.get("markets", []):
            if m.get("key") == "h2h":
                outcomes = m.get("outcomes", [])
                if not outcomes:
                    continue
                # choose away team outcome when possible
                away = ev.get("away_team")
                chosen = next((o for o in outcomes if o.get("name") == away), outcomes[0])
                h2h_price = chosen.get("price")
                team = chosen.get("name")
                event = ev
                break
        if event:
            break

    if not event or h2h_price is None or team is None:
        return jsonify({"error": "No suitable line found to capture"}), 404

    event_id = event.get("id")
    key = f"opening:{sport}:{event_id}:h2h:{team}"
    value = str(h2h_price)  # store just the american price as the simplest opening datum

    created, err = redis_setnx(key, value, ex=7*24*3600)  # 7 days TTL
    if err:
        return jsonify({"error": f"Redis error: {err}"}), 500

    # Read back to confirm
    stored, err2 = redis_get(key)
    if err2:
        return jsonify({"error": f"Redis readback error: {err2}"}), 500

    return jsonify({
        "sport": sport,
        "bookmaker": bookmaker,
        "event_id": event_id,
        "team": team,
        "opening_attempted": True,
        "created": created,  # False means it already existed (NX prevented overwrite)
        "stored_value": stored,
        "redis_key": key,
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=True)
