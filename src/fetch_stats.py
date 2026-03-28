"""Fetch NBA player and team game logs via nba_api."""

import time
import pandas as pd
from nba_api.stats.endpoints import (
    leaguegamelog,
    playergamelog,
    boxscoretraditionalv2,
    commonallplayers,
)
from nba_api.stats.static import teams as nba_teams

SEASON = "2025-26"
STAT_COLS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]
NBA_API_TIMEOUT = 120  # seconds - NBA.com can be slow from CI
MAX_RETRIES = 5

# Custom headers to avoid NBA.com blocking CI/cloud IPs
CUSTOM_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def _fetch_with_retry(fetch_fn, description="data"):
    """Retry nba_api calls with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = fetch_fn()
            time.sleep(1)
            return result
        except Exception as e:
            print(f"  Attempt {attempt}/{MAX_RETRIES} for {description} failed: {e}")
            if attempt < MAX_RETRIES:
                wait = 10 * attempt  # 10s, 20s, 30s, 40s
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def get_all_player_game_logs():
    """Fetch game logs for all players who played this season via LeagueGameLog."""
    print("Fetching league-wide player game logs...")
    logs = _fetch_with_retry(
        lambda: leaguegamelog.LeagueGameLog(
            season=SEASON,
            season_type_all_star="Regular Season",
            player_or_team_abbreviation="P",
            timeout=NBA_API_TIMEOUT,
            headers=CUSTOM_HEADERS,
        ),
        "player game logs",
    )
    df = logs.get_data_frames()[0]
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    # Filter out DNP / garbage time entries (less than 3 minutes played)
    df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce")
    df = df[df["MIN"] >= 3].copy()
    df = df.sort_values(["PLAYER_ID", "GAME_DATE"], ascending=[True, False])
    return df


def get_team_game_logs():
    """Fetch game logs for all teams this season."""
    print("Fetching league-wide team game logs...")
    logs = _fetch_with_retry(
        lambda: leaguegamelog.LeagueGameLog(
            season=SEASON,
            season_type_all_star="Regular Season",
            player_or_team_abbreviation="T",
            timeout=NBA_API_TIMEOUT,
            headers=CUSTOM_HEADERS,
        ),
        "team game logs",
    )
    df = logs.get_data_frames()[0]
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    df = df.sort_values(["TEAM_ID", "GAME_DATE"], ascending=[True, False])
    return df


def compute_player_stats(df):
    """For each player, compute season avg, L10 avg, and last 3 game values."""
    results = {}
    for player_id, group in df.groupby("PLAYER_ID"):
        group = group.sort_values("GAME_DATE", ascending=False)
        if len(group) < 3:
            continue

        player_name = group.iloc[0]["PLAYER_NAME"]
        team_abbr = group.iloc[0]["TEAM_ABBREVIATION"]

        last_3 = group.head(3)
        last_10 = group.head(10)

        player_data = {
            "player_id": int(player_id),
            "player_name": player_name,
            "team": team_abbr,
            "games_played": len(group),
            "stats": {},
        }

        for stat in STAT_COLS:
            season_avg = round(group[stat].mean(), 1)
            l10_avg = round(last_10[stat].mean(), 1)
            last_3_values = last_3[stat].tolist()
            last_3_avg = round(sum(last_3_values) / 3, 1)

            player_data["stats"][stat] = {
                "season_avg": season_avg,
                "l10_avg": l10_avg,
                "last_3": last_3_values,
                "last_3_avg": last_3_avg,
            }

        results[player_name] = player_data

    return results


def compute_team_stats(df):
    """For each team, compute season avg, L10 avg, and last 3 game total points."""
    results = {}
    team_list = nba_teams.get_teams()
    team_id_to_name = {t["id"]: t["full_name"] for t in team_list}
    team_id_to_abbr = {t["id"]: t["abbreviation"] for t in team_list}

    for team_id, group in df.groupby("TEAM_ID"):
        group = group.sort_values("GAME_DATE", ascending=False)
        if len(group) < 3:
            continue

        team_name = team_id_to_name.get(team_id, group.iloc[0]["TEAM_ABBREVIATION"])
        team_abbr = team_id_to_abbr.get(team_id, group.iloc[0]["TEAM_ABBREVIATION"])

        last_3 = group.head(3)
        last_10 = group.head(10)

        season_avg = round(group["PTS"].mean(), 1)
        l10_avg = round(last_10["PTS"].mean(), 1)
        last_3_values = last_3["PTS"].tolist()

        results[team_name] = {
            "team_name": team_name,
            "team_abbr": team_abbr,
            "team_id": int(team_id),
            "games_played": len(group),
            "total_points": {
                "season_avg": season_avg,
                "l10_avg": l10_avg,
                "last_3": last_3_values,
                "last_3_avg": round(sum(last_3_values) / 3, 1),
            },
        }

    return results


def fetch_quarter_half_scores(game_ids):
    """Fetch 1Q and 1H scores for given game IDs using box scores.

    Returns dict: {game_id: {team_abbr: {"q1": pts, "first_half": pts}}}
    """
    results = {}
    for game_id in game_ids:
        try:
            box = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
            time.sleep(0.6)
            frames = box.get_data_frames()
            # frames[1] is team stats - but doesn't have quarter breakdown
            # We need to use the player stats and sum by team per period
            # Actually BoxScoreTraditionalV2 doesn't give quarter breakdowns
            # We need a different approach
        except Exception as e:
            print(f"Error fetching box score for {game_id}: {e}")
            continue
    return results


def get_team_quarter_data():
    """Get team 1Q and 1H scoring data from game logs.

    nba_api's LeagueGameLog doesn't include quarter breakdowns.
    We'll use the boxscoresummaryv2 endpoint for recent games.
    """
    from nba_api.stats.endpoints import leaguedashteamstats

    # For now, we'll track total points only.
    # Quarter/half data requires per-game box score fetching which is expensive.
    # We can add this later if needed by fetching BoxScoreSummaryV2 for each game.
    print("Note: 1Q/1H team scoring requires per-game fetching. Using total points for now.")
    return {}


def fetch_all_stats():
    """Main entry point: fetch all stats and return processed data."""
    player_logs = get_all_player_game_logs()
    team_logs = get_team_game_logs()

    player_stats = compute_player_stats(player_logs)
    team_stats = compute_team_stats(team_logs)

    print(f"Processed stats for {len(player_stats)} players and {len(team_stats)} teams")
    return {
        "players": player_stats,
        "teams": team_stats,
    }


if __name__ == "__main__":
    data = fetch_all_stats()
    print(f"\nSample player: {list(data['players'].keys())[:3]}")
    print(f"Sample team: {list(data['teams'].keys())[:3]}")
