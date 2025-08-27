import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

API_KEY = os.getenv("API_KEY")  # Set this on Render
BASE_URL = "https://api.the-odds-api.com/v4"

# ===== Known-good keys you confirmed work =====
ALLOWED_SPORTS = [
    "baseball_mlb",
    "mma_mixed_martial_arts",
    "basketball_wnba",
    "americanfootball_nfl",
    "americanfootball_ncaaf",
]
DEFAULT_SPORT = "baseball_mlb"

# Keep the bookmaker list simple; you can expand later
ALLOWED_BOOKMAKERS = [
    "draftkings",
    "betonlineag",
    "fanduel",
    "caesars",
]
DEFAULT_BOOKMAKER = "draftkings"


@app.route("/")
def home():
    # Serve the SPA front page
    return send_from_directory(app.static_folder, "index.html")


@app.route("/sports")
def sports():
    # Frontend dropdown population
    return jsonify({"sports": ALLOWED_SPORTS, "default": DEFAULT_SPORT})


@app.route("/bookmakers")
def bookmakers():
    # Frontend dropdown population
    return jsonify({"bookmakers": ALLOWED_BOOKMAKERS, "default": DEFAULT_BOOKMAKER})


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

    # Day chips: 0=today (ET), 1=tomorrow, etc.
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

    # Filter by selected calendar day in ET (matches your chips)
    et = ZoneInfo("America/New_York")
    start_day = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_day = start_day + timedelta(days=1)

    def is_in_day(iso_str: str) -> bool:
        try:
            dt_et = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone(et)
            return start_day <= dt_et < end_day
        except Exception:
            return False

    games = []
    for ev in events:
        if not is_in_day(ev.get("commence_time", "")):
            continue

        # Get only the selected bookmaker’s markets for purity
        bm = next((b for b in ev.get("bookmakers", []) if b.get("key") == bookmaker), None)
        if not bm:
            continue
        markets = bm.get("markets", [])

        # Extractors (stable versions)
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
            # Keep Over first if both exist
            if len(arr) == 2:
                arr.sort(key=lambda x: 0 if (x["team"] or "").lower().startswith("over") else 1)
            return arr

        h2h = get_h2h(markets)
        spreads = get_spreads(markets)
        totals = get_totals(markets)

        # ET kickoff for header
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
            # Open/diff are dashes in this baseline; we’ll restore after stability
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


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=True)
