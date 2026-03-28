"""Fetch NBA player and team game logs via ESPN public API.

ESPN's API is free, requires no API key, and works from any IP
(unlike stats.nba.com which blocks cloud/CI IPs).
"""

import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SEASON = 2026  # ESPN uses the end-year (2025-26 season = 2026)
STAT_COLS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog?season={season}"

# ESPN gamelog stat indices (from the 'labels' array):
# MIN=0, FG=1, FG%=2, 3PT=3, 3P%=4, FT=5, FT%=6, REB=7, AST=8, BLK=9, STL=10, PF=11, TO=12, PTS=13
STAT_INDEX = {
    "MIN": 0,
    "FG3M": 3,   # "3-5" format, we parse the made part
    "REB": 7,
    "AST": 8,
    "BLK": 9,
    "STL": 10,
    "PTS": 13,
}


def _session_with_retries(retries=3, backoff=0.5):
    """Create a requests Session with automatic retries on transient errors."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session = _session_with_retries()


def get_all_teams():
    """Get all NBA team IDs and names from ESPN."""
    resp = _session.get(f"{ESPN_BASE}/teams", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    teams = data["sports"][0]["leagues"][0]["teams"]
    return [
        {
            "id": t["team"]["id"],
            "name": t["team"]["displayName"],
            "abbreviation": t["team"]["abbreviation"],
        }
        for t in teams
    ]


def get_team_roster(team_id):
    """Get player IDs for a team.

    ESPN roster API returns athletes as a flat list:
    data["athletes"] = [{"id": "...", "fullName": "...", ...}, ...]
    """
    resp = _session.get(f"{ESPN_BASE}/teams/{team_id}/roster", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "id": athlete["id"],
            "name": athlete["fullName"],
        }
        for athlete in data.get("athletes", [])
    ]


def _safe_int(val, default=0):
    """Safely parse a stat value to int, handling '--', empty strings, etc."""
    try:
        return int(val)
    except (ValueError, TypeError, IndexError):
        return default


def get_player_gamelog(athlete_id):
    """Get per-game stats for a player this season.

    Returns games in chronological order (oldest first).
    """
    url = ESPN_GAMELOG.format(athlete_id=athlete_id, season=SEASON)
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    games = []

    # Get regular season games
    for season_type in data.get("seasonTypes", []):
        if "Regular" not in season_type.get("displayName", ""):
            continue
        for category in season_type.get("categories", []):
            for event in category.get("events", []):
                stats = event.get("stats", [])
                if not stats or len(stats) < 14:
                    continue

                # Parse minutes
                minutes = _safe_int(stats[STAT_INDEX["MIN"]])

                # Skip DNP / garbage time
                if minutes < 3:
                    continue

                # Parse 3PT made from "made-attempted" format
                fg3_str = stats[STAT_INDEX["FG3M"]]
                try:
                    fg3m = int(fg3_str.split("-")[0])
                except (ValueError, AttributeError, IndexError):
                    fg3m = 0

                game = {
                    "event_id": event.get("eventId", ""),
                    "MIN": minutes,
                    "PTS": _safe_int(stats[STAT_INDEX["PTS"]]),
                    "REB": _safe_int(stats[STAT_INDEX["REB"]]),
                    "AST": _safe_int(stats[STAT_INDEX["AST"]]),
                    "STL": _safe_int(stats[STAT_INDEX["STL"]]),
                    "BLK": _safe_int(stats[STAT_INDEX["BLK"]]),
                    "FG3M": fg3m,
                }
                games.append(game)

    return games


def get_team_game_logs():
    """Get team game results from ESPN schedule endpoints."""
    print("Fetching team game logs...")
    teams = get_all_teams()
    team_stats = {}

    for team in teams:
        team_id = team["id"]
        team_name = team["name"]
        team_abbr = team["abbreviation"]

        try:
            # ESPN team schedule/results endpoint
            sched_url = f"{ESPN_BASE}/teams/{team_id}/schedule?season={SEASON}"
            resp = _session.get(sched_url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            games = []
            for event in data.get("events", []):
                # Only completed games
                competitions = event.get("competitions", [])
                if not competitions:
                    continue
                status = competitions[0].get("status", {}).get("type", {}).get("name", "")
                if status != "STATUS_FINAL":
                    continue

                # Find this team's score
                for competitor in competitions[0].get("competitors", []):
                    if competitor.get("team", {}).get("id") == str(team_id):
                        raw_score = competitor.get("score", 0)
                        # Score can be a dict {"value": 118.0}, a string "118", or an int
                        if isinstance(raw_score, dict):
                            score = _safe_int(raw_score.get("value", 0))
                        else:
                            score = _safe_int(raw_score)
                        if score > 0:
                            games.append(score)
                        break

            if len(games) >= 3:
                # Games are chronological (oldest first); take from the end
                last_3 = list(reversed(games[-3:]))   # Most recent first
                last_10 = list(reversed(games[-10:]))  # Most recent first

                team_stats[team_name] = {
                    "team_name": team_name,
                    "team_abbr": team_abbr,
                    "team_id": _safe_int(team_id),
                    "games_played": len(games),
                    "total_points": {
                        "season_avg": round(sum(games) / len(games), 1),
                        "l10_avg": round(sum(last_10) / len(last_10), 1),
                        "last_3": last_3,
                        "last_3_avg": round(sum(last_3) / 3, 1),
                    },
                }

            time.sleep(0.3)
        except Exception as e:
            print(f"  Error fetching {team_name}: {e}")
            continue

    return team_stats


def compute_player_stats(all_player_games):
    """Compute season avg, L10 avg, and last 3 game values per player."""
    results = {}

    for player_name, info in all_player_games.items():
        games = info["games"]
        team = info["team"]

        if len(games) < 3:
            continue

        # ESPN gamelog returns games chronologically (oldest first).
        # Reverse so index 0 = most recent game.
        games = list(reversed(games))
        last_3 = games[:3]
        last_10 = games[:10]

        player_data = {
            "player_id": info["id"],
            "player_name": player_name,
            "team": team,
            "games_played": len(games),
            "stats": {},
        }

        for stat in STAT_COLS:
            all_vals = [g[stat] for g in games]
            l3_vals = [g[stat] for g in last_3]
            l10_vals = [g[stat] for g in last_10]

            season_avg = round(sum(all_vals) / len(all_vals), 1)
            l10_avg = round(sum(l10_vals) / len(l10_vals), 1)
            last_3_avg = round(sum(l3_vals) / 3, 1)

            player_data["stats"][stat] = {
                "season_avg": season_avg,
                "l10_avg": l10_avg,
                "last_3": l3_vals,
                "last_3_avg": last_3_avg,
            }

        results[player_name] = player_data

    return results


def fetch_all_stats():
    """Main entry point: fetch all stats and return processed data."""
    print("Fetching NBA stats via ESPN API...")
    teams = get_all_teams()
    print(f"Found {len(teams)} teams")

    # Fetch all player game logs
    all_player_games = {}
    for i, team in enumerate(teams):
        team_name = team["name"]
        team_abbr = team["abbreviation"]
        print(f"  [{i+1}/{len(teams)}] {team_name}...")

        try:
            roster = get_team_roster(team["id"])
        except Exception as e:
            print(f"    Error getting roster: {e}")
            continue

        for player in roster:
            try:
                games = get_player_gamelog(player["id"])
                if games:
                    all_player_games[player["name"]] = {
                        "id": player["id"],
                        "team": team_abbr,
                        "games": games,
                    }
                time.sleep(0.15)  # Rate limit
            except requests.exceptions.RequestException as e:
                # Player may not have stats this season, or transient error
                continue

        time.sleep(0.3)

    print(f"Fetched game logs for {len(all_player_games)} players")

    # Compute stats
    player_stats = compute_player_stats(all_player_games)

    # Fetch team stats
    team_stats = get_team_game_logs()

    print(f"Processed stats for {len(player_stats)} players and {len(team_stats)} teams")
    return {
        "players": player_stats,
        "teams": team_stats,
    }


if __name__ == "__main__":
    data = fetch_all_stats()
    print(f"\nSample player: {list(data['players'].keys())[:3]}")
    print(f"Sample team: {list(data['teams'].keys())[:3]}")
