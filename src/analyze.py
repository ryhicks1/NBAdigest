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

            # Skip if all last 3 games are zero (not interesting)
            if all(v == 0 for v in last_3):
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
    """Merge anomaly data with current betting lines and tag with game info.

    Adds the relevant betting line and game/event info to each anomaly.
    """
    # Build lookups: player->event mapping and odds
    player_odds_lookup = {}
    player_game_lookup = {}  # player_name -> {event_name, home_team, away_team}
    team_totals_lookup = {}

    for event in odds_data.get("events", []):
        event_name = event["event_name"]
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        game_label = f"{away_team} @ {home_team}" if home_team and away_team else event_name

        for player_name, props in event.get("player_props", {}).items():
            if player_name not in player_odds_lookup:
                player_odds_lookup[player_name] = {}
            player_odds_lookup[player_name].update(props)
            player_game_lookup[player_name] = {
                "game": game_label,
                "home_team": home_team,
                "away_team": away_team,
            }

        team_totals = event.get("team_totals", {})
        if team_totals:
            team_totals_lookup[event_name] = {
                "totals": team_totals,
                "game": game_label,
                "home_team": home_team,
                "away_team": away_team,
            }

    # Attach odds and game info to player anomalies
    for anomaly in player_anomalies:
        player_name = anomaly["player_name"]
        stat = anomaly["stat"]
        odds = player_odds_lookup.get(player_name, {}).get(stat)
        anomaly["betting_line"] = odds if odds else None

        game_info = player_game_lookup.get(player_name)
        if game_info:
            anomaly["game"] = game_info["game"]
        else:
            anomaly["game"] = None

    # Attach odds and game info to team anomalies
    for anomaly in team_anomalies:
        team_name = anomaly["team_name"]
        matched = False
        for event_name, info in team_totals_lookup.items():
            if team_name.split()[-1] in event_name or any(
                word in event_name for word in team_name.split()
            ):
                anomaly["betting_line"] = info["totals"].get("game_total")
                anomaly["game"] = info["game"]
                matched = True
                break
        if not matched:
            anomaly["betting_line"] = None
            anomaly["game"] = None

    # Filter out anomalies without a betting line for that specific stat
    player_anomalies = [a for a in player_anomalies if a["betting_line"] is not None]
    team_anomalies = [a for a in team_anomalies if a["betting_line"] is not None]

    return player_anomalies, team_anomalies
