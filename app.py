import os
import logging
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
app.logger.setLevel(logging.INFO)

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

def _json_get(url: str, timeout: int = 8) -> dict:
    r = requests.get(url, headers=_redis_headers(), timeout=timeout)
    r.raise_for_status()
    return r.json()

def redis_ping() -> Tuple[Optional[str], Optional[str]]:
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None, "Missing Upstash env vars"
    try:
        return _json_get(f"{UPSTASH_URL}/PING").get("result"), None
    except Exception as e:
        return None, str(e)

# ----- Dual-read + migrate helpers -----
def redis_get_dual(key: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Try encoded GET first; if not found, try legacy raw GET.
    Returns (value, where, err) where where ∈ {"encoded","legacy",None}.
    """
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return None, None, "Missing Upstash env vars"
    try:
        k_enc = quote(key, safe="")
        d1 = _json_get(f"{UPSTASH_URL}/GET/{k_enc}")
        if d1.get("result") is not None:
            return d1["result"], "encoded", None
        d2 = _json_get(f"{UPSTASH_URL}/GET/{key}")
        if d2.get("result") is not None:
            return d2["result"], "legacy", None
        return None, None, None
    except Exception as e:
        app.logger.error("Redis GET failed key=%s err=%s", key, e)
        return None, None, str(e)

def redis_setnx_encoded(key: str, value: Any, ex_seconds: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return False, "Missing Upstash env vars"
    try:
        k = quote(key, safe=""); v = quote(str(value), safe="")
        url = f"{UPSTASH_URL}/SET/{k}/{v}?NX=1"
        if ex_seconds is not None:
            url += f"&EX={int(ex_seconds)}"
        return _json_get(url).get("result") == "OK", None
    except Exception as e:
        app.logger.error("Redis SETNX failed key=%s val=%s err=%s", key, value, e)
        return False, str(e)

def redis_set_encoded(key: str, value: Any, ex_seconds: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    if not (UPSTASH_URL and UPSTASH_TOKEN):
        return False, "Missing Upstash env vars"
    try:
        k = quote(key, safe=""); v = quote(str(value), safe="")
        url = f"{UPSTASH_URL}/SET/{k}/{v}"
        if ex_seconds is not None:
            url += f"?EX={int(ex_seconds)}"
        return _json_get(url).get("result") == "OK", None
    except Exception as e:
        app.logger.error("Redis SET failed key=%s err=%s", key, e)
        return False, str(e)

def redis_del_both(key: str) -> None:
    try:
        _json_get(f"{UPSTASH_URL}/DEL/{quote(key, safe='')}")
    except Exception:
        pass
    try:
        _json_get(f"{UPSTASH_URL}/DEL/{key}")
    except Exception:
        pass

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
    for candidate in (val, str(val).replace("+", "")):
        try:
            return float(candidate)
        except Exception:
            pass
    return None

def get_or_set_opening(key: str, current_value: Optional[Any]) -> Optional[float]:
    """
    Read opening (try encoded, then legacy). If legacy found, migrate -> encoded.
    If missing and current_value is provided, write encoded NX and return it.
    """
    existing, where, err = redis_get_dual(key)
    if err is None and existing is not None:
        if where == "legacy":
            # migrate legacy -> encoded once
            redis_set_encoded(key, existing, ex_seconds=OPEN_TTL)
            redis_del_both(key)
        return _to_float(existing)

    if current_value is None:
        return None

    redis_setnx_encoded(key, current_value, ex_seconds=OPEN_TTL)
    stored, _, _ = redis_get_dual(key)
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

        # Moneyline opening + diff (American odds delta)
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

        # Spreads opening + diff (points only)
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
                "open_price": None,
                "live_point": lp,
                "live_price": lprice,
                "diff_point": diff_point
            })

        # Totals opening + diff (points only)
        tot_rows = []
        for row in totals:
            ou_lab = row.get("team")  # "Over" / "Under"
            lp = row.get("point")
            lprice = row.get("price")
            open_point = None
            if ou_lab:
                ktp = key_total_point(sport, event_id, ou_lab)
                open_point = get_or_set_opening(ktp, lp)
                # store price too
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

# ===== Seed openings (GET + POST so you can test in browser) =====
@app.route("/seed_openings", methods=["GET", "POST"])
def seed_openings():
    if not API_KEY:
        return jsonify({"error": "Missing API_KEY"}), 500

    if request.method == "GET":
        sport = request.args.get("sport", DEFAULT_SPORT)
        bookmaker = request.args.get("bookmaker", DEFAULT_BOOKMAKER)
        try:
            day_offset = int(request.args.get("day_offset", "0"))
        except ValueError:
            day_offset = 0
    else:
        sport = request.values.get("sport", DEFAULT_SPORT)
        bookmaker = request.values.get("bookmaker", DEFAULT_BOOKMAKER)
        try:
            day_offset = int(request.values.get("day_offset", "0"))
        except ValueError:
            day_offset = 0
    day_offset = max(0, min(day_offset, 30))

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
                created, _ = redis_setnx_encoded(key_ml(sport, event_id, team), str(h2h[team]), ex_seconds=OPEN_TTL)
                if created:
                    seeded += 1

        # Spreads (points)
        for team in [away, home]:
            if not team:
                continue
            row = spreads.get(team) or {}
            if row.get("point") is not None:
                created, _ = redis_setnx_encoded(key_spread_point(sport, event_id, team), str(row["point"]), ex_seconds=OPEN_TTL)
                if created:
                    seeded += 1

        # Totals (points)
        for row in totals:
            ou = row.get("team")
            p = row.get("point")
            if ou and p is not None:
                created, _ = redis_setnx_encoded(key_total_point(sport, event_id, ou), str(p), ex_seconds=OPEN_TTL)
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
@app.route("/debug/boot")
def debug_boot():
    return jsonify({"booted_at_est": datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")})

@app.route("/debug/redis/ping")
def debug_ping_route():
    res, err = redis_ping()
    if err:
        return jsonify({"ok": False, "error": err}), 500
    return jsonify({"ok": True, "result": res})

@app.route("/debug/redis/get")
def debug_get():
    k = request.args.get("key")
    if not k:
        return jsonify({"error": "key is required"}), 400
    val, where, err = redis_get_dual(k)
    if err:
        return jsonify({"error": err}), 500
    return jsonify({"key": k, "result": val, "where": where})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=True)
