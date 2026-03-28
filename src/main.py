"""NBA Betting Anomalies Digest - Main orchestrator."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_stats import fetch_all_stats
from fetch_odds import fetch_all_odds
from analyze import detect_player_anomalies, detect_team_anomalies, merge_with_odds


def run_pipeline():
    """Run the full data pipeline and generate anomalies.json."""
    sydney_tz = timezone(timedelta(hours=11))  # AEDT
    now = datetime.now(sydney_tz)
    print(f"=== NBA Betting Anomalies Digest ===")
    print(f"Run time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()

    # Step 1: Fetch NBA stats
    print("--- Step 1: Fetching NBA stats ---")
    stats_data = fetch_all_stats()
    print()

    # Step 2: Fetch Sportsbet odds
    print("--- Step 2: Fetching Sportsbet.com.au odds ---")
    try:
        odds_data = fetch_all_odds()
    except Exception as e:
        print(f"Warning: Failed to fetch odds: {e}")
        print("Continuing without betting lines...")
        odds_data = {"events": [], "all_players_with_markets": set()}
    print()

    # Step 3: Detect anomalies
    print("--- Step 3: Detecting anomalies ---")
    players_with_markets = odds_data.get("all_players_with_markets", set())

    # If no odds data, use all players (for testing/fallback)
    if not players_with_markets:
        print("No Sportsbet markets found - showing all player anomalies")
        players_with_markets = set(stats_data["players"].keys())

    player_anomalies = detect_player_anomalies(stats_data["players"], players_with_markets)
    team_anomalies = detect_team_anomalies(stats_data["teams"])

    print(f"Found {len(player_anomalies)} player anomalies")
    print(f"Found {len(team_anomalies)} team anomalies")

    # Step 4: Merge with odds
    print("--- Step 4: Merging with betting lines ---")
    player_anomalies, team_anomalies = merge_with_odds(
        player_anomalies, team_anomalies, odds_data
    )

    # Step 5: Build output
    # Build games list for the filter dropdown
    games = []
    for event in odds_data.get("events", []):
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home and away:
            games.append(f"{away} @ {home}")
        else:
            games.append(event.get("event_name", ""))

    output = {
        "generated_at": now.isoformat(),
        "season": "2025-26",
        "games": sorted(set(games)),
        "player_anomalies": {
            "hot": [a for a in player_anomalies if a["direction"] == "hot"],
            "cold": [a for a in player_anomalies if a["direction"] == "cold"],
        },
        "team_anomalies": {
            "hot": [a for a in team_anomalies if a["direction"] == "hot"],
            "cold": [a for a in team_anomalies if a["direction"] == "cold"],
        },
        "meta": {
            "total_players_analyzed": len(stats_data["players"]),
            "total_teams_analyzed": len(stats_data["teams"]),
            "players_with_sportsbet_markets": len(players_with_markets),
            "events_count": len(odds_data.get("events", [])),
        },
    }

    # Write to data/anomalies.json
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)
    output_path = os.path.join(data_dir, "anomalies.json")

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nOutput written to {output_path}")
    print(f"Hot player streaks: {len(output['player_anomalies']['hot'])}")
    print(f"Cold player streaks: {len(output['player_anomalies']['cold'])}")
    print(f"Hot team streaks: {len(output['team_anomalies']['hot'])}")
    print(f"Cold team streaks: {len(output['team_anomalies']['cold'])}")

    return output


if __name__ == "__main__":
    run_pipeline()
