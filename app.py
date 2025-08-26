import requests
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ===== Local hardcoded API key (no env) =====
API_KEY = "e9cb3bfd5865b71161c903d24911b88d"  # <-- your key here
DEFAULT_BOOKMAKER = "betonlineag"

# Sports we’ll show in the dropdown
ALLOWED_SPORTS = [
    "baseball_mlb",
    "mma_mixed_martial_arts",
    "basketball_wnba",
    "americanfootball_nfl",
    "americanfootball_ncaaf",
]

# In-memory “opening” baselines (reset whenever you restart app.py)
moneyline_open = {}       # moneyline_open[game_id][team] = opening american price (int)
spread_open_points = {}   # spread_open_points[game_id][team] = opening spread point (float)
total_open_points = {}    # total_open_points[game_id]["Over"/"Under"] = opening total point (float)

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/sports")
def sports():
    return jsonify({"sports": ALLOWED_SPORTS})

@app.route("/odds/<sport>")
def odds(sport):
    if sport not in ALLOWED_SPORTS:
        return jsonify({"error": f"Unsupported sport '{sport}'.", "allowed": ALLOWED_SPORTS}), 400

    bookmaker = request.args.get("bookmaker", DEFAULT_BOOKMAKER)
    url = build_odds_url(sport, bookmaker, markets="h2h,spreads,totals")
    print(f"[FETCH] {url}")  # ← prints exact URL in your terminal

    try:
        resp = requests.get(url, timeout=12)
        status = resp.status_code
        text_preview = resp.text[:240]
        print(f"[FETCH][{status}] preview: {text_preview!r}")
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        return jsonify({"error": "The Odds API HTTP error", "details": str(e), "url": url, "preview": text_preview}), 502
    except Exception as e:
        return jsonify({"error": "Failed to fetch odds", "details": str(e), "url": url}), 502

    games = []
    for event in data:
        game_id = event.get("id")
        home = event.get("home_team")
        away = event.get("away_team")

        commence = event.get("commence_time")
        try:
            ct = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(timezone.utc)
            commence_iso = ct.isoformat()
        except Exception:
            commence_iso = commence

        book = first_bookmaker(event.get("bookmakers", []))
        if not book:
            continue

        ml = parse_moneyline(game_id, book)
        sp = parse_spreads(game_id, book)
        tl = parse_totals(game_id, book)

        if ml or sp or tl:
            games.append({
                "game_id": game_id,
                "commence_time": commence_iso,
                "home": home,
                "away": away,
                "moneyline": ml,
                "spread": sp,
                "total": tl
            })

    return jsonify({"sport": sport, "bookmaker": bookmaker, "count": len(games), "results": games})

# ---------- helpers ----------

def build_odds_url(sport: str, bookmaker: str, markets: str) -> str:
    base = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": markets,
        "bookmakers": bookmaker,
        "oddsFormat": "american",
    }
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{base}/?{query}"

def first_bookmaker(bookmakers):
    if not bookmakers:
        return None
    return bookmakers[0]

def parse_moneyline(game_id, book):
    h2h = next((m for m in (book.get("markets") or []) if m.get("key") == "h2h"), None)
    if not h2h:
        return {}
    outcomes = h2h.get("outcomes") or []

    if game_id not in moneyline_open:
        moneyline_open[game_id] = {}

    result = {}
    for oc in outcomes:
        team = oc.get("name")
        price = oc.get("price")
        if team is None or price is None:
            continue
        if team not in moneyline_open[game_id]:
            moneyline_open[game_id][team] = price
        open_price = moneyline_open[game_id].get(team)
        diff = price - open_price if isinstance(open_price, int) else None
        result[team] = {"open": open_price if isinstance(open_price, int) else None, "live": price, "diff": diff}
    return result

def parse_spreads(game_id, book):
    spreads = next((m for m in (book.get("markets") or []) if m.get("key") == "spreads"), None)
    if not spreads:
        return {}
    outcomes = spreads.get("outcomes") or []

    if game_id not in spread_open_points:
        spread_open_points[game_id] = {}

    result = {}
    for oc in outcomes:
        team = oc.get("name")
        live_point = oc.get("point")
        live_price = oc.get("price")
        if team is None or live_point is None:
            continue
        try:
            lp = float(live_point)
        except Exception:
            continue
        if team not in spread_open_points[game_id]:
            spread_open_points[game_id][team] = lp
        open_point = spread_open_points[game_id].get(team)
        diff_points = (lp - open_point) if isinstance(open_point, float) else None
        result[team] = {
            "open_point": open_point if isinstance(open_point, float) else None,
            "live_point": lp,
            "diff_points": diff_points,
            "open_price": None,
            "live_price": live_price
        }
    return result

def parse_totals(game_id, book):
    totals = next((m for m in (book.get("markets") or []) if m.get("key") == "totals"), None)
    if not totals:
        return {}
    outcomes = totals.get("outcomes") or []

    if game_id not in total_open_points:
        total_open_points[game_id] = {}

    result = {}
    for oc in outcomes:
        side = oc.get("name")  # "Over" or "Under"
        live_point = oc.get("point")
        live_price = oc.get("price")
        if side not in ("Over", "Under") or live_point is None:
            continue
        try:
            lp = float(live_point)
        except Exception:
            continue
        if side not in total_open_points[game_id]:
            total_open_points[game_id][side] = lp
        open_point = total_open_points[game_id].get(side)
        diff_points = (lp - open_point) if isinstance(open_point, float) else None
        result[side] = {
            "open_point": open_point if isinstance(open_point, float) else None,
            "live_point": lp,
            "diff_points": diff_points,
            "open_price": None,
            "live_price": live_price
        }
    return result

if __name__ == "__main__":
    # debug=False keeps one process; simpler + fewer surprises
    app.run(host="127.0.0.1", port=5050, debug=False)
