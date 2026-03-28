"""Fetch NBA betting lines from Sportsbet.com.au internal API."""

import httpx
import time
import re

BASE_URL = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
NBA_COMPETITION_ID = 6927

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sportsbet.com.au/betting/basketball-us/nba",
}

# Market name patterns for player props
PLAYER_PROP_PATTERNS = {
    "PTS": re.compile(r"^(.+?) - Points$"),
    "REB": re.compile(r"^(.+?) - Rebounds$"),
    "AST": re.compile(r"^(.+?) - Assists$"),
    "FG3M": re.compile(r"^(.+?) - Made Threes$"),
    "STL": re.compile(r"^(.+?) - Steals$"),
    "BLK": re.compile(r"^(.+?) - Blocks$"),
}

# Threshold market patterns (for steals/blocks which don't have O/U lines)
THRESHOLD_PATTERNS = {
    "STL": re.compile(r"^To Record (\d+)\+ Steals$"),
    "BLK": re.compile(r"^To Record (\d+)\+ Blocks$"),
}


def get_nba_events():
    """Get all current NBA events from Sportsbet."""
    url = f"{BASE_URL}/Competitions/{NBA_COMPETITION_ID}"
    with httpx.Client(headers=HEADERS, timeout=30) as client:
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


def get_event_markets(event_id):
    """Get all markets for a specific event."""
    url = f"{BASE_URL}/Events/{event_id}"
    with httpx.Client(headers=HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    return data.get("marketList", [])


def parse_player_props(markets):
    """Parse player prop markets into structured data.

    Returns: {player_name: {stat: {"line": float, "over_price": float, "under_price": float}}}
    """
    player_props = {}

    for market in markets:
        name = market.get("name", "")
        selections = market.get("selections", [])

        # Check over/under player prop markets (Points, Rebounds, Assists, Made Threes)
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

    # Also parse threshold markets for steals/blocks
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
                    # Only store if we don't already have an O/U line, or this threshold is useful
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


def parse_team_totals(markets, event_name):
    """Parse team total points markets.

    Returns: {"total": {"line": float, "over_price": float, "under_price": float}}
    """
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

        # 1Q total
        elif name == "1st Quarter Total Points":
            over_sel = next((s for s in selections if "Over" in s.get("name", "")), None)
            under_sel = next((s for s in selections if "Under" in s.get("name", "")), None)
            if over_sel and over_sel.get("unformattedHandicap"):
                totals["q1_total"] = {
                    "line": float(over_sel["unformattedHandicap"]),
                    "over_price": over_sel.get("price", {}).get("winPrice"),
                    "under_price": under_sel.get("price", {}).get("winPrice") if under_sel else None,
                }

        # 1H total
        elif name == "1st Half Total Points":
            over_sel = next((s for s in selections if "Over" in s.get("name", "")), None)
            under_sel = next((s for s in selections if "Under" in s.get("name", "")), None)
            if over_sel and over_sel.get("unformattedHandicap"):
                totals["h1_total"] = {
                    "line": float(over_sel["unformattedHandicap"]),
                    "over_price": over_sel.get("price", {}).get("winPrice"),
                    "under_price": under_sel.get("price", {}).get("winPrice") if under_sel else None,
                }

    return totals


def fetch_all_odds():
    """Main entry point: fetch all NBA betting lines from Sportsbet.

    Returns:
    {
        "events": [
            {
                "event_id": int,
                "event_name": str,
                "player_props": {player_name: {stat: line_data}},
                "team_totals": {market_type: line_data},
            }
        ],
        "all_players_with_markets": set of player names that have any market
    }
    """
    events = get_nba_events()
    all_event_data = []
    all_players = set()

    for event in events:
        event_id = event["id"]
        event_name = event["name"]
        print(f"  Fetching markets for: {event_name} ({event_id})...")

        try:
            markets = get_event_markets(event_id)
        except Exception as e:
            print(f"    Error: {e}")
            continue

        player_props = parse_player_props(markets)
        team_totals = parse_team_totals(markets, event_name)

        all_event_data.append({
            "event_id": event_id,
            "event_name": event_name,
            "start_time": event["start_time"],
            "player_props": player_props,
            "team_totals": team_totals,
        })

        all_players.update(player_props.keys())
        time.sleep(0.5)  # Rate limiting

    print(f"Found markets for {len(all_players)} unique players across {len(all_event_data)} events")
    return {
        "events": all_event_data,
        "all_players_with_markets": all_players,
    }


if __name__ == "__main__":
    import json

    data = fetch_all_odds()
    # Convert set to list for JSON serialization
    data["all_players_with_markets"] = list(data["all_players_with_markets"])
    print(json.dumps(data, indent=2, default=str)[:3000])
