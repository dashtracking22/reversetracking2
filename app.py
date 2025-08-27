import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

# ====== Config ======
API_KEY = os.getenv("API_KEY")  # Set on Render
BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_SPORT = "americanfootball_ncaaf"
DEFAULT_BOOKMAKER = "draftkings"

# Allowed sports (feel free to add/remove once stable)
ALLOWED_SPORTS = [
    "americanfootball_ncaaf",
    "americanfootball_nfl",
    "baseball_mlb",
    "basketball_wnba",
    "mma_mixed_martial_arts",
]

# We’ll expose a conservative list of bookmakers
ALLOWED_BOOKMAKERS = [
    "draftkings",
    "betonlineag",
    "fanduel",
    "caesars",
]

# ====== Static file routes (index.html, app.js, styles.css at project root) ======

@app.route("/")
def root():
    return send_from_directory(".", "index.html")

@app.route("/<path:filename>")
def serve_static_file(filename):
    # Serve app.js / styles.css / images if any
    return send_from_directory(".", filename)

# ====== API: sports, bookmakers ======

@app.route("/sports")
def get_sports():
    return jsonify({"sports": ALLOWED_SPORTS})

@app.route("/bookmakers")
def get_bookmakers():
    # (We could fetch live list, but keeping static for stability)
    return jsonify({"bookmakers": ALLOWED_BOOKMAKERS, "default": DEFAULT_BOOKMAKER})

# ====== API: odds ======
# Params:
#   sport=<key> (required)
#   bookmaker=<key> (required)
#   day_offset=<int> (0=today, 1=tomorrow, etc.; default 0)
@app.route("/odds")
def get_odds():
    api_key = API_KEY
    if not api_key:
        return jsonify({"error": "Missing API_KEY env var"}), 500

    sport = request.args.get("sport", DEFAULT_SPORT)
    if sport not in ALLOWED_SPORTS:
        return jsonify({"error": f"Unsupported sport: {sport}"}), 400

    bookmaker = request.args.get("bookmaker", DEFAULT_BOOKMAKER)
    if bookmaker not in ALLOWED_BOOKMAKERS:
        return jsonify({"error": f"Unsupported bookmaker: {bookmaker}"}), 400

    try:
        day_offset = int(request.args.get("day_offset", "0"))
        if day_offset < 0:
            day_offset = 0
        if day_offset > 30:
            day_offset = 30
    except ValueError:
        day_offset = 0

    # Fetch odds (american format) for selected bookmaker and markets
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "bookmakers": bookmaker,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }

    try:
        r = requests.get(f"{BASE_URL}/sports/{sport}/odds", params=params, timeout=20)
        r.raise_for_status()
        events = r.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Error loading odds: {e}"}), 500

    # Filter by the selected calendar day in ET
    et = ZoneInfo("America/New_York")
    today_et = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0)
    target_start = today_et + timedelta(days=day_offset)
    target_end = target_start + timedelta(days=1)

    def is_in_target_window(iso_str: str) -> bool:
        # commence_time is ISO in UTC per Odds API, e.g., "2025-08-28T23:00:00Z"
        try:
            dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            dt_et = dt_utc.astimezone(et)
            return target_start <= dt_et < target_end
        except Exception:
            return False

    # Parse per event
    parsed = []
    for ev in events:
        if not is_in_target_window(ev.get("commence_time", "")):
            continue

        bookmakers = ev.get("bookmakers", [])
        if not bookmakers:
            continue

        # find the selected bookmaker block
        bm_block = next((b for b in bookmakers if b.get("key") == bookmaker), None)
        if not bm_block:
            continue

        markets = bm_block.get("markets", [])

        # helper extractors
        def extract_h2h(mkts):
            # returns dict {team: price}
            result = {}
            for m in mkts:
                if m.get("key") == "h2h":
                    for o in m.get("outcomes", []):
                        team = o.get("name")
                        price = o.get("price")
                        if team is not None:
                            result[team] = price
            return result

        def extract_spreads(mkts):
            # returns dict {team: {"point": float, "price": int}}
            result = {}
            for m in mkts:
                if m.get("key") == "spreads":
                    for o in m.get("outcomes", []):
                        team = o.get("name")
                        point = o.get("point")
                        price = o.get("price")
                        if team is not None:
                            result[team] = {"point": point, "price": price}
            return result

        def extract_totals(mkts):
            # returns list like [{"team":"Over","point":x,"price":y},{"team":"Under",...}]
            result = []
            for m in mkts:
                if m.get("key") == "totals":
                    for o in m.get("outcomes", []):
                        result.append({
                            "team": o.get("name"),
                            "point": o.get("point"),
                            "price": o.get("price"),
                        })
            # Normalize to Over/Under ordering if both exist
            if len(result) == 2:
                result.sort(key=lambda x: 0 if x["team"].lower().startswith("over") else 1)
            return result

        h2h = extract_h2h(markets)
        spreads = extract_spreads(markets)
        totals = extract_totals(markets)

        # Commence time (ET, pretty)
        try:
            dt_utc = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(et)
            kickoff_est = dt_utc.strftime("%m/%d %I:%M %p")
        except Exception:
            kickoff_est = ""

        parsed.append({
            "event_id": ev.get("id"),
            "sport": sport,
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
            "commence_time_est": kickoff_est,
            "bookmaker": bookmaker,
            "moneyline": [{"team": t, "live_price": h2h.get(t, None), "open_price": None, "diff_price": None}
                          for t in [ev.get("away_team"), ev.get("home_team")] if t],
            "spreads": [{"team": t,
                         "live_point": spreads.get(t, {}).get("point"),
                         "live_price": spreads.get(t, {}).get("price"),
                         "open_point": None, "open_price": None,
                         "diff_point": None}
                        for t in [ev.get("away_team"), ev.get("home_team")] if t],
            "totals": [{"team": row.get("team"),
                        "live_point": row.get("point"),
                        "live_price": row.get("price"),
                        "open_point": None, "open_price": None,
                        "diff_point": None}
                       for row in totals]
        })

    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%m/%d %I:%M %p")
    return jsonify({
        "as_of_est": stamp,
        "bookmaker": bookmaker,
        "sport": sport,
        "games": parsed
    })


if __name__ == "__main__":
    # For local dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=True)
