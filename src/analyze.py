"""Detect statistical anomaly streaks in NBA player and team stats."""

import statistics

STAT_LABELS = {
    "PTS": "Points",
    "REB": "Rebounds",
    "AST": "Assists",
    "STL": "Steals",
    "BLK": "Blocks",
    "FG3M": "Threes",
}

# Minimum season average to consider (filters out near-zero stats)
MIN_AVERAGES = {
    "PTS": 5.0,
    "REB": 2.0,
    "AST": 1.5,
    "STL": 0.5,
    "BLK": 0.3,
    "FG3M": 0.5,
}


def detect_player_anomalies(player_stats, players_with_markets):
    """Find players with 3-game anomaly streaks.

    An anomaly is when all 3 of the last 3 games are consistently
    above or below the season/L10 average.

    Args:
        player_stats: dict from fetch_stats.compute_player_stats()
        players_with_markets: set of player names that have Sportsbet markets

    Returns: list of anomaly dicts
    """
    anomalies = []

    for player_name, data in player_stats.items():
        # Only include players with active betting markets
        if player_name not in players_with_markets:
            continue

        for stat, values in data["stats"].items():
            season_avg = values["season_avg"]
            l10_avg = values["l10_avg"]
            last_3 = values["last_3"]
            last_3_avg = values["last_3_avg"]

            # Skip if season average is too low (noise)
            min_avg = MIN_AVERAGES.get(stat, 0.5)
            if season_avg < min_avg:
                continue

            # Check if all 3 games are consistently above or below
            all_above_season = all(v > season_avg for v in last_3)
            all_below_season = all(v < season_avg for v in last_3)
            all_above_l10 = all(v > l10_avg for v in last_3)
            all_below_l10 = all(v < l10_avg for v in last_3)

            if not (all_above_season or all_below_season or all_above_l10 or all_below_l10):
                continue

            # Calculate deviation percentage from season average
            if season_avg > 0:
                pct_diff_season = ((last_3_avg - season_avg) / season_avg) * 100
            else:
                pct_diff_season = 0

            if l10_avg > 0:
                pct_diff_l10 = ((last_3_avg - l10_avg) / l10_avg) * 100
            else:
                pct_diff_l10 = 0

            # Only flag if deviation is meaningful (>15% from season or L10)
            is_significant = abs(pct_diff_season) > 15 or abs(pct_diff_l10) > 15

            if not is_significant:
                continue

            # Determine direction
            if all_above_season or all_above_l10:
                direction = "hot"
                streak_desc = "above"
            else:
                direction = "cold"
                streak_desc = "below"

            # Determine which average it's deviating from most
            comparison = "season"
            pct_diff = pct_diff_season
            ref_avg = season_avg
            if abs(pct_diff_l10) > abs(pct_diff_season):
                comparison = "l10"
                pct_diff = pct_diff_l10
                ref_avg = l10_avg

            anomalies.append({
                "player_name": player_name,
                "team": data["team"],
                "stat": stat,
                "stat_label": STAT_LABELS.get(stat, stat),
                "direction": direction,
                "last_3": last_3,
                "last_3_avg": last_3_avg,
                "season_avg": season_avg,
                "l10_avg": l10_avg,
                "pct_diff_season": round(pct_diff_season, 1),
                "pct_diff_l10": round(pct_diff_l10, 1),
                "comparison": comparison,
                "games_played": data["games_played"],
            })

    # Sort by absolute deviation (most extreme first)
    anomalies.sort(key=lambda a: max(abs(a["pct_diff_season"]), abs(a["pct_diff_l10"])), reverse=True)
    return anomalies


def detect_team_anomalies(team_stats):
    """Find teams with 3-game total points anomaly streaks.

    Returns: list of anomaly dicts
    """
    anomalies = []

    for team_name, data in team_stats.items():
        totals = data["total_points"]
        season_avg = totals["season_avg"]
        l10_avg = totals["l10_avg"]
        last_3 = totals["last_3"]
        last_3_avg = totals["last_3_avg"]

        all_above = all(v > season_avg for v in last_3)
        all_below = all(v < season_avg for v in last_3)

        if not (all_above or all_below):
            continue

        pct_diff = ((last_3_avg - season_avg) / season_avg) * 100 if season_avg > 0 else 0

        if abs(pct_diff) < 10:  # Teams need >10% deviation
            continue

        anomalies.append({
            "team_name": team_name,
            "team_abbr": data["team_abbr"],
            "stat": "total_points",
            "stat_label": "Total Points",
            "direction": "hot" if all_above else "cold",
            "last_3": last_3,
            "last_3_avg": last_3_avg,
            "season_avg": season_avg,
            "l10_avg": l10_avg,
            "pct_diff": round(pct_diff, 1),
            "games_played": data["games_played"],
        })

    anomalies.sort(key=lambda a: abs(a["pct_diff"]), reverse=True)
    return anomalies


def merge_with_odds(player_anomalies, team_anomalies, odds_data):
    """Merge anomaly data with current Sportsbet betting lines.

    Adds the relevant betting line to each anomaly where available.
    """
    # Build a flat lookup: {player_name: {stat: line_data}} across all events
    player_odds_lookup = {}
    team_totals_lookup = {}

    for event in odds_data.get("events", []):
        event_name = event["event_name"]
        for player_name, props in event.get("player_props", {}).items():
            if player_name not in player_odds_lookup:
                player_odds_lookup[player_name] = {}
            player_odds_lookup[player_name].update(props)

        # Extract team names from event name ("Team A At Team B")
        team_totals = event.get("team_totals", {})
        if team_totals:
            team_totals_lookup[event_name] = team_totals

    # Attach odds to player anomalies
    for anomaly in player_anomalies:
        player_name = anomaly["player_name"]
        stat = anomaly["stat"]
        odds = player_odds_lookup.get(player_name, {}).get(stat)
        if odds:
            anomaly["betting_line"] = odds
        else:
            anomaly["betting_line"] = None

    # Attach odds to team anomalies
    for anomaly in team_anomalies:
        # Try to find matching team totals
        team_name = anomaly["team_name"]
        for event_name, totals in team_totals_lookup.items():
            if team_name.split()[-1] in event_name or any(
                word in event_name for word in team_name.split()
            ):
                anomaly["betting_line"] = totals.get("game_total")
                break
        else:
            anomaly["betting_line"] = None

    return player_anomalies, team_anomalies
