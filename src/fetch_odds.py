"""Fetch NBA betting lines from The Odds API (primary) and Sportsbet.com.au (fallback)."""

import httpx
import os
import time
import re

# === The Odds API (primary) ===
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")
SPORT_KEY = "basketball_nba"
REGIONS = "au"
BOOKMAKERS = "sportsbet"
PLAYER_PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_steals",
    "player_blocks",
]
TEAM_MARKETS = ["totals", "totals_q1", "totals_h1"]

# Map Odds API market names to our stat codes
ODDS_API_STAT_MAP = {
    "player_points": "PTS",
    "player_rebounds": "REB",
    "player_assists": "AST",
    "player_threes": "FG3M",
    "player_steals": "STL",
    "player_blocks": "BLK",
}

# === Sportsbet.com.au scraper (fallback) ===
SPORTSBET_BASE = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
NBA_COMPETITION_ID = 6927
SPORTSBET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sportsbet.com.au/betting/basketball-us/nba",
}
PLAYER_PROP_PATTERNS = {
    "PTS": re.compile(r"^(.+?) - Points$"),
    "REB": re.compile(r"^(.+?) - Rebounds$"),
    "AST": re.compile(r"^(.+?) - Assists$"),
    "FG3M": re.compile(r"^(.+?) - Made Threes$"),
    "STL": re.compile(r"^(.+?) - Steals$"),
    "BLK": re.compile(r"^(.+?) - Blocks$"),
}
THRESHOLD_PATTERNS = {
    "STL": re.compile(r"^To Record (\d+)\+ Steals$"),
    "BLK": re.compile(r"^To Record (\d+)\+ Blocks$"),
}


# =====================
# The Odds API (primary)
# =====================

def odds_api_get_events():
    """Get NBA events from The Odds API (free, no credits used)."""
    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/events"
    params = {"apiKey": ODDS_API_KEY}
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"  Odds API credits: {remaining} remaining, {used} used")
        return resp.json()


def odds_api_get_event_odds(event_id, markets):
    """Get odds for a specific event from The Odds API."""
    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "bookmakers": BOOKMAKERS,
        "markets": ",".join(markets),
        "oddsFormat": "decimal",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"    Credits remaining: {remaining}")
        return resp.json()


def parse_odds_api_player_props(event_data):
    """Parse The Odds API response into player props dict."""
    player_props = {}
    bookmakers = event_data.get("bookmakers", [])

    for bookmaker in bookmakers:
        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            stat = ODDS_API_STAT_MAP.get(market_key)
            if not stat:
                continue

            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description", "")
                if not player_name:
                    continue

                if player_name not in player_props:
                    player_props[player_name] = {}

                point = outcome.get("point")
                if point is None:
                    continue

                side = outcome.get("name", "")  # "Over" or "Under"
                price = outcome.get("price")

                if stat not in player_props[player_name]:
                    player_props[player_name][stat] = {
                        "line": point,
                        "market_type": "over_under",
                    }

                if side == "Over":
                    player_props[player_name][stat]["over_price"] = price
                    player_props[player_name][stat]["line"] = point
                elif side == "Under":
                    player_props[player_name][stat]["under_price"] = price

    return player_props


def parse_odds_api_team_totals(event_data):
    """Parse team total markets from The Odds API."""
    totals = {}
    market_key_map = {
        "totals": "game_total",
        "totals_q1": "q1_total",
        "totals_h1": "h1_total",
    }

    bookmakers = event_data.get("bookmakers", [])
    for bookmaker in bookmakers:
        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            total_key = market_key_map.get(market_key)
            if not total_key:
                continue

            over = next((o for o in market.get("outcomes", []) if o["name"] == "Over"), None)
            under = next((o for o in market.get("outcomes", []) if o["name"] == "Under"), None)

            if over and over.get("point"):
                totals[total_key] = {
                    "line": over["point"],
                    "over_price": over.get("price"),
                    "under_price": under.get("price") if under else None,
                }

    return totals


def fetch_odds_api():
    """Fetch all NBA odds via The Odds API."""
    print("Using The Odds API (paid plan)...")
    events = odds_api_get_events()
    print(f"Found {len(events)} NBA events")

    all_event_data = []
    all_players = set()

    for event in events:
        event_id = event["id"]
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        event_name = f"{away} At {home}"
        print(f"  Fetching odds for: {event_name}...")

        try:
            # Fetch player props and team totals in one call
            all_markets = PLAYER_PROP_MARKETS + TEAM_MARKETS
            event_odds = odds_api_get_event_odds(event_id, all_markets)

            player_props = parse_odds_api_player_props(event_odds)
            team_totals = parse_odds_api_team_totals(event_odds)

            all_event_data.append({
                "event_id": event_id,
                "event_name": event_name,
                "home_team": home,
                "away_team": away,
                "commence_time": event.get("commence_time", ""),
                "player_props": player_props,
                "team_totals": team_totals,
            })

            all_players.update(player_props.keys())
            time.sleep(0.3)

        except Exception as e:
            print(f"    Error: {e}")
            continue

    print(f"Found markets for {len(all_players)} unique players across {len(all_event_data)} events")
    return {
        "events": all_event_data,
        "all_players_with_markets": all_players,
    }


# =====================
# Sportsbet.com.au (fallback)
# =====================

def sportsbet_get_events():
    """Get NBA events from Sportsbet."""
    url = f"{SPORTSBET_BASE}/Competitions/{NBA_COMPETITION_ID}"
    with httpx.Client(headers=SPORTSBET_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    events = data.get("events", [])
    print(f"Found {len(events)} NBA events on Sportsbet")
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "start_time": e["startTime"],
            "num_markets": e.get("numMarkets", 0),
        }
        for e in events
    ]


def sportsbet_get_event_markets(event_id):
    """Get all markets for a specific Sportsbet event."""
    url = f"{SPORTSBET_BASE}/Events/{event_id}"
    with httpx.Client(headers=SPORTSBET_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data.get("marketList", [])


def sportsbet_parse_player_props(markets):
    """Parse Sportsbet player prop markets."""
    player_props = {}

    for market in markets:
        name = market.get("name", "")
        selections = market.get("selections", [])

        for stat, pattern in PLAYER_PROP_PATTERNS.items():
            match = pattern.match(name)
            if match:
                player_name = match.group(1)
                if player_name not in player_props:
                    player_props[player_name] = {}

                over_sel = next((s for s in selections if "Over" in s.get("name", "")), None)
                under_sel = next((s for s in selections if "Under" in s.get("name", "")), None)

                if over_sel and over_sel.get("unformattedHandicap"):
                    player_props[player_name][stat] = {
                        "line": float(over_sel["unformattedHandicap"]),
                        "over_price": over_sel.get("price", {}).get("winPrice"),
                        "under_price": under_sel.get("price", {}).get("winPrice") if under_sel else None,
                        "market_type": "over_under",
                    }
                break

    for market in markets:
        name = market.get("name", "")
        selections = market.get("selections", [])

        for stat, pattern in THRESHOLD_PATTERNS.items():
            match = pattern.match(name)
            if match:
                threshold = int(match.group(1))
                for sel in selections:
                    player_name = sel.get("name", "")
                    if not player_name:
                        continue
                    if player_name not in player_props:
                        player_props[player_name] = {}
                    if stat not in player_props[player_name]:
                        player_props[player_name][stat] = {
                            "thresholds": {},
                            "market_type": "threshold",
                        }
                    if player_props[player_name][stat].get("market_type") == "threshold":
                        player_props[player_name][stat]["thresholds"][threshold] = {
                            "price": sel.get("price", {}).get("winPrice"),
                        }
                break

    return player_props


def sportsbet_parse_team_totals(markets):
    """Parse Sportsbet team total markets."""
    totals = {}
    for market in markets:
        name = market.get("name", "")
        selections = market.get("selections", [])

        if name == "Total Points":
            over_sel = next((s for s in selections if s.get("name") == "Over"), None)
            under_sel = next((s for s in selections if s.get("name") == "Under"), None)
            if over_sel and over_sel.get("unformattedHandicap"):
                totals["game_total"] = {
                    "line": float(over_sel["unformattedHandicap"]),
                    "over_price": over_sel.get("price", {}).get("winPrice"),
                    "under_price": under_sel.get("price", {}).get("winPrice") if under_sel else None,
                }
    return totals


def fetch_sportsbet():
    """Fetch all NBA odds via Sportsbet scraping."""
    print("Using Sportsbet.com.au scraper (fallback)...")
    events = sportsbet_get_events()
    all_event_data = []
    all_players = set()

    for event in events:
        event_id = event["id"]
        event_name = event["name"]
        print(f"  Fetching markets for: {event_name} ({event_id})...")

        try:
            markets = sportsbet_get_event_markets(event_id)
        except Exception as e:
            print(f"    Error: {e}")
            continue

        player_props = sportsbet_parse_player_props(markets)
        team_totals = sportsbet_parse_team_totals(markets)

        # Parse team names from "Away At Home" format
        parts = event_name.split(" At ")
        away_team = parts[0] if len(parts) == 2 else ""
        home_team = parts[1] if len(parts) == 2 else ""

        all_event_data.append({
            "event_id": event_id,
            "event_name": event_name,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": event.get("start_time", ""),
            "player_props": player_props,
            "team_totals": team_totals,
        })

        all_players.update(player_props.keys())
        time.sleep(0.5)

    print(f"Found markets for {len(all_players)} unique players across {len(all_event_data)} events")
    return {
        "events": all_event_data,
        "all_players_with_markets": all_players,
    }


# =====================
# Public entry point
# =====================

def fetch_all_odds():
    """Fetch NBA odds. Uses The Odds API if key is set, otherwise Sportsbet scraper."""
    if ODDS_API_KEY:
        try:
            return fetch_odds_api()
        except Exception as e:
            print(f"The Odds API failed: {e}")
            print("Falling back to Sportsbet scraper...")
            return fetch_sportsbet()
    else:
        print("No THE_ODDS_API_KEY set.")
        return fetch_sportsbet()


if __name__ == "__main__":
    import json

    data = fetch_all_odds()
    data["all_players_with_markets"] = list(data["all_players_with_markets"])
    print(json.dumps(data, indent=2, default=str)[:3000])
