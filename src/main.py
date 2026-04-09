"""NBA Betting Anomalies Digest - Main orchestrator."""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_stats import fetch_all_stats
from fetch_odds import fetch_all_odds
from analyze import detect_player_anomalies, detect_team_anomalies, merge_with_odds, pick_featured_bets
from config import apply_affiliate_tag
from track_results import load_or_init_history, record_bets, resolve_pending, save_history, build_summary


STATS_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "stats_cache.json",
)


def _load_cached_stats():
    """Load cached ESPN stats from disk if available."""
    if os.path.exists(STATS_CACHE_PATH):
        with open(STATS_CACHE_PATH) as f:
            return json.load(f)
    return None


def _save_stats_cache(stats_data):
    """Save ESPN stats to disk for hourly odds-only refreshes."""
    os.makedirs(os.path.dirname(STATS_CACHE_PATH), exist_ok=True)
    with open(STATS_CACHE_PATH, "w") as f:
        json.dump(stats_data, f, default=str)


def run_pipeline(odds_only=False):
    """Run the data pipeline and generate anomalies.json.

    Args:
        odds_only: If True, reuse cached ESPN stats and only refresh odds.
                   If False (default), fetch fresh stats from ESPN too.
    """
    sydney_tz = timezone(timedelta(hours=11))  # AEDT
    now = datetime.now(sydney_tz)
    mode = "odds-only refresh" if odds_only else "full run"
    print(f"=== NBA Betting Anomalies Digest ({mode}) ===")
    print(f"Run time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print()

    # Step 1: Fetch or load NBA stats
    if odds_only:
        print("--- Step 1: Loading cached ESPN stats ---")
        stats_data = _load_cached_stats()
        if not stats_data:
            print("No cached stats found — falling back to full ESPN fetch")
            stats_data = fetch_all_stats()
            _save_stats_cache(stats_data)
        else:
            print(f"Loaded cached stats ({len(stats_data.get('players', {}))} players)")
    else:
        print("--- Step 1: Fetching NBA stats ---")
        stats_data = fetch_all_stats()
        _save_stats_cache(stats_data)
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

    # Step 5: Pick featured bets
    print("--- Step 5: Picking featured bets ---")
    featured = pick_featured_bets(player_anomalies, team_anomalies, count=10)
    print(f"Selected {len(featured)} featured bets")
    for i, f in enumerate(featured, 1):
        print(f"  {i}. {f['bet_description']} (score: {f['score']})")

    # Step 6: Track bet outcomes
    print("--- Step 6: Tracking bet outcomes ---")
    today_str = now.strftime("%Y-%m-%d")
    bet_history = load_or_init_history()
    added = record_bets(bet_history, featured, today_str)
    print(f"Recorded {added} new bets for {today_str}")
    settled = resolve_pending(bet_history, stats_data)
    print(f"Settled {settled} pending bets")
    save_history(bet_history)
    tracking_summary = build_summary(bet_history)
    total_s = tracking_summary["settled"]
    wins = tracking_summary["wins"]
    win_rate = tracking_summary["win_rate"]
    print(f"All-time: {wins}W/{tracking_summary['losses']}L out of {total_s} ({win_rate}% win rate)")

    # Step 7: Build output
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
        "featured_bets": featured,
        "tracking": tracking_summary,
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

    # Apply affiliate tags to all sportsbet_url fields
    for item in output["featured_bets"]:
        if "sportsbet_url" in item:
            item["sportsbet_url"] = apply_affiliate_tag(item["sportsbet_url"])
    for direction in ("hot", "cold"):
        for item in output["player_anomalies"][direction]:
            if "sportsbet_url" in item:
                item["sportsbet_url"] = apply_affiliate_tag(item["sportsbet_url"])
        for item in output["team_anomalies"][direction]:
            if "sportsbet_url" in item:
                item["sportsbet_url"] = apply_affiliate_tag(item["sportsbet_url"])

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
    odds_only = "--odds-only" in sys.argv
    run_pipeline(odds_only=odds_only)
