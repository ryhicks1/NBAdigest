"""Track outcomes of previously suggested featured bets.

Workflow:
  1. load_or_init_history()         — load data/bet_history.json
  2. record_bets(history, bets, date) — append today's featured bets (deduped)
  3. resolve_pending(history, stats_cache) — fill in WIN/LOSS for unsettled bets
  4. save_history(history)           — write back to disk
  5. build_summary(history)          — return stats dict for anomalies.json
"""

import json
import os
from datetime import datetime, timedelta

HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "bet_history.json",
)

# Stat key in ESPN game log -> stat label used in featured bets
STAT_KEYS = {"PTS", "REB", "AST", "STL", "BLK", "FG3M"}


def load_or_init_history():
    """Load existing bet history or create a fresh structure."""
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {"bets": []}


def save_history(history):
    """Persist bet history to disk."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _bet_id(bet, date_str):
    """Stable dedup key for a bet so we don't double-record it."""
    return f"{date_str}|{bet['player_name']}|{bet['stat']}|{bet['betting_line']['line']}|{bet['bet_action']}"


def record_bets(history, featured_bets, date_str):
    """Append today's featured bets to history (idempotent — won't double-add)."""
    existing_ids = {b["id"] for b in history["bets"]}
    added = 0
    for bet in featured_bets:
        bid = _bet_id(bet, date_str)
        if bid in existing_ids:
            continue
        history["bets"].append({
            "id": bid,
            "suggested_date": date_str,
            "player_name": bet["player_name"],
            "team": bet.get("team", ""),
            "stat": bet["stat"],
            "stat_label": bet.get("stat_label", bet["stat"]),
            "direction": bet["bet_action"],
            "line": bet["betting_line"]["line"],
            "over_price": bet["betting_line"].get("over_price"),
            "under_price": bet["betting_line"].get("under_price"),
            "bet_description": bet["bet_description"],
            "game": bet.get("game", ""),
            "last_3_avg": bet.get("last_3_avg"),
            "season_avg": bet.get("season_avg"),
            "score": bet.get("score"),
            "status": "pending",
            "actual_value": None,
            "settled_at": None,
        })
        existing_ids.add(bid)
        added += 1
    return added


def _fetch_player_games(athlete_id, stats_cache_players):
    """Pull per-game stats from stats_cache if already loaded, else fetch live.

    Returns dict of {date_str: {stat: value, ...}}.
    We check both the suggested date and the day before to handle US/AEDT offset.
    """
    import requests

    SEASON = 2026
    ESPN_GAMELOG = (
        "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
        "/athletes/{athlete_id}/gamelog?season={season}"
    )
    STAT_INDEX = {"FG3M": 3, "REB": 7, "AST": 8, "BLK": 9, "STL": 10, "PTS": 13}

    url = ESPN_GAMELOG.format(athlete_id=athlete_id, season=SEASON)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    event_dates = {}
    for eid, ev in data.get("events", {}).items():
        event_dates[eid] = ev.get("gameDate", "")

    games = {}
    for season_type in data.get("seasonTypes", []):
        if "Regular" not in season_type.get("displayName", ""):
            continue
        for category in season_type.get("categories", []):
            for event in category.get("events", []):
                stats = event.get("stats", [])
                if not stats or len(stats) < 14:
                    continue
                minutes_raw = stats[0]
                try:
                    minutes = int(minutes_raw)
                except (ValueError, TypeError):
                    minutes = 0
                if minutes < 3:
                    continue
                try:
                    fg3m = int(str(stats[STAT_INDEX["FG3M"]]).split("-")[0])
                except Exception:
                    fg3m = 0
                event_id = event.get("eventId", "")
                game_date = event_dates.get(event_id, "")
                if not game_date:
                    continue
                date_key = game_date[:10]

                def _int(v):
                    try:
                        return int(v)
                    except Exception:
                        return 0

                games[date_key] = {
                    "PTS": _int(stats[STAT_INDEX["PTS"]]),
                    "REB": _int(stats[STAT_INDEX["REB"]]),
                    "AST": _int(stats[STAT_INDEX["AST"]]),
                    "STL": _int(stats[STAT_INDEX["STL"]]),
                    "BLK": _int(stats[STAT_INDEX["BLK"]]),
                    "FG3M": fg3m,
                }
    return games


def resolve_pending(history, stats_cache):
    """For each pending bet, try to find the game result and mark WIN/LOSS.

    We look for the game on `suggested_date` and `suggested_date - 1` (US date
    offset) and `suggested_date + 1` (games played late that evening AEDT).
    """
    import time

    players_cache = stats_cache.get("players", {})

    # Build player_name -> player_id map
    player_ids = {
        name: data["player_id"]
        for name, data in players_cache.items()
        if "player_id" in data
    }

    # Fetch game logs only for players with pending bets (cache per player)
    pending = [b for b in history["bets"] if b["status"] == "pending"]
    if not pending:
        return 0

    # Group pending bets by player so we fetch each player once
    players_needed = {b["player_name"] for b in pending}
    game_logs = {}  # player_name -> {date: stats}

    for name in players_needed:
        pid = player_ids.get(name)
        if not pid:
            continue
        try:
            game_logs[name] = _fetch_player_games(pid, players_cache)
        except Exception as e:
            print(f"  Warning: could not fetch game log for {name}: {e}")
        time.sleep(0.15)

    settled = 0
    today = datetime.utcnow().date()

    for bet in pending:
        name = bet["player_name"]
        stat = bet["stat"]
        line = bet["line"]
        direction = bet["direction"]
        suggested = datetime.strptime(bet["suggested_date"], "%Y-%m-%d").date()

        # Don't try to settle bets from today — results aren't in yet
        if suggested >= today:
            continue

        logs = game_logs.get(name)
        if not logs:
            continue

        # Check the suggested date, the day before, and the day after
        game_result = None
        for delta in (0, -1, 1):
            check_date = (suggested + timedelta(days=delta)).strftime("%Y-%m-%d")
            if check_date in logs:
                game_result = logs[check_date]
                break

        if game_result is None:
            # No game found for this player around that date — mark as no_game
            # Only do this if the date is old enough (3+ days) to be confident
            if (today - suggested).days >= 3:
                bet["status"] = "no_game"
                bet["settled_at"] = datetime.utcnow().isoformat()
                settled += 1
            continue

        actual = game_result.get(stat, 0)
        if direction == "OVER":
            hit = actual > line
        else:
            hit = actual < line

        bet["status"] = "win" if hit else "loss"
        bet["actual_value"] = actual
        bet["settled_at"] = datetime.utcnow().isoformat()
        settled += 1

    return settled


def build_summary(history):
    """Return a summary dict to embed in anomalies.json."""
    bets = history["bets"]
    settled = [b for b in bets if b["status"] in ("win", "loss")]
    wins = [b for b in settled if b["status"] == "win"]
    losses = [b for b in settled if b["status"] == "loss"]
    pending = [b for b in bets if b["status"] == "pending"]
    no_game = [b for b in bets if b["status"] == "no_game"]

    win_rate = round(len(wins) / len(settled) * 100, 1) if settled else None

    # Break down by stat
    from collections import defaultdict
    by_stat = defaultdict(lambda: {"wins": 0, "losses": 0})
    for b in settled:
        by_stat[b["stat_label"]]["wins" if b["status"] == "win" else "losses"] += 1

    stat_breakdown = {
        stat: {
            "wins": counts["wins"],
            "losses": counts["losses"],
            "win_pct": round(
                counts["wins"] / (counts["wins"] + counts["losses"]) * 100, 1
            ) if (counts["wins"] + counts["losses"]) > 0 else None,
        }
        for stat, counts in sorted(by_stat.items())
    }

    # Recent form: last 20 settled bets
    recent = sorted(settled, key=lambda b: b.get("settled_at", ""), reverse=True)[:20]
    recent_wins = sum(1 for b in recent if b["status"] == "win")
    recent_win_rate = round(recent_wins / len(recent) * 100, 1) if recent else None

    return {
        "total_bets": len(bets),
        "settled": len(settled),
        "wins": len(wins),
        "losses": len(losses),
        "pending": len(pending),
        "no_game": len(no_game),
        "win_rate": win_rate,
        "recent_win_rate": recent_win_rate,
        "recent_sample_size": len(recent),
        "by_stat": stat_breakdown,
        "last_20": [
            {
                "date": b["suggested_date"],
                "description": b["bet_description"],
                "actual": b.get("actual_value"),
                "status": b["status"],
            }
            for b in recent
        ],
    }
