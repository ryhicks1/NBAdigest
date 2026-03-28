"""Fetch NBA player and team game logs.

Uses requests directly instead of nba_api's session management
to have full control over headers and connection handling,
which is critical for CI environments where NBA.com blocks cloud IPs.
"""

import time
import json
import requests
import pandas as pd
from nba_api.stats.static import teams as nba_teams

SEASON = "2025-26"
STAT_COLS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M"]
NBA_API_TIMEOUT = 60
MAX_RETRIES = 5

STATS_URL = "https://stats.nba.com/stats/leaguegamelog"

HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Connection": "keep-alive",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _fetch_nba_stats(params, description="data"):
    """Fetch from NBA stats API with retries and proper headers."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Use a fresh session each attempt to avoid stale connections
            session = requests.Session()
            session.headers.update(HEADERS)
            resp = session.get(STATS_URL, params=params, timeout=NBA_API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            session.close()
            time.sleep(1)
            return data
        except Exception as e:
            print(f"  Attempt {attempt}/{MAX_RETRIES} for {description} failed: {e}")
            if attempt < MAX_RETRIES:
                wait = 15 * attempt
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def _nba_json_to_df(data):
    """Convert NBA stats API JSON response to DataFrame."""
    result_set = data["resultSets"][0]
    headers = result_set["headers"]
    rows = result_set["rowSet"]
    return pd.DataFrame(rows, columns=headers)


def get_all_player_game_logs():
    """Fetch game logs for all players who played this season."""
    print("Fetching league-wide player game logs...")
    params = {
        "Counter": "0",
        "DateFrom": "",
        "DateTo": "",
        "Direction": "DESC",
        "LeagueID": "00",
        "PlayerOrTeam": "P",
        "Season": SEASON,
        "SeasonType": "Regular Season",
        "Sorter": "DATE",
    }
    data = _fetch_nba_stats(params, "player game logs")
    df = _nba_json_to_df(data)
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    # Filter out DNP / garbage time entries (less than 3 minutes played)
    df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce")
    df = df[df["MIN"] >= 3].copy()
    df = df.sort_values(["PLAYER_ID", "GAME_DATE"], ascending=[True, False])
    return df


def get_team_game_logs():
    """Fetch game logs for all teams this season."""
    print("Fetching league-wide team game logs...")
    params = {
        "Counter": "0",
        "DateFrom": "",
        "DateTo": "",
        "Direction": "DESC",
        "LeagueID": "00",
        "PlayerOrTeam": "T",
        "Season": SEASON,
        "SeasonType": "Regular Season",
        "Sorter": "DATE",
    }
    data = _fetch_nba_stats(params, "team game logs")
    df = _nba_json_to_df(data)
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
