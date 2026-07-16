#!/usr/bin/env python3
"""
Fetches current Yankees batting trends + season game log, and writes it all
to data.json for the dashboard (index.html) to read. Designed to be run by
a scheduled GitHub Action, but works fine run manually/locally too.
"""
import json
from datetime import date, datetime

import mlb_data

SEASON = 2026
TEAM_ID = 147

PLAYERS = [
    "Ben Rice", "Paul Goldschmidt", "Jose Caballero", "Jazz Chisholm Jr.",
    "Cody Bellinger", "Jasson Dominguez", "Anthony Volpe", "Trent Grisham",
    "Ryan McMahon", "Amed Rosario", "Austin Wells",
]

MONTH_NAMES = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
               7: "July", 8: "August", 9: "September", 10: "October"}


def month_splits_to_named(month_splits, today):
    current = today.month
    out = {}
    for mm, stat in month_splits.items():
        name = MONTH_NAMES[int(mm)]
        if int(mm) == current:
            name += " (to date)"
        out[name] = stat
    return out


def build_team_section(today):
    month_splits = month_splits_to_named(mlb_data.get_team_month_splits(TEAM_ID, SEASON), today)
    windows = mlb_data.current_month_windows(today)
    return {
        "month_splits": month_splits,
        "season": mlb_data.get_team_season_split(TEAM_ID, SEASON),
        "last_30_days": mlb_data.get_team_daterange_split(TEAM_ID, windows[30], today),
        "last_15_days": mlb_data.get_team_daterange_split(TEAM_ID, windows[15], today),
        "last_7_days": mlb_data.get_team_daterange_split(TEAM_ID, windows[7], today),
    }


def build_player_section(name, person_id, today):
    month_splits = month_splits_to_named(mlb_data.get_player_month_splits(person_id, SEASON), today)
    return {
        "mlb_id": person_id,
        "month_splits": month_splits,
        "season": mlb_data.get_player_season_split(person_id, SEASON),
        "last_30_games": mlb_data.get_player_last_n_games_split(person_id, SEASON, 30),
        "last_15_games": mlb_data.get_player_last_n_games_split(person_id, SEASON, 15),
        "last_7_games": mlb_data.get_player_last_n_games_split(person_id, SEASON, 7),
    }


def main():
    today = date.today()
    print(f"Building dashboard data for {today.isoformat()}...")

    print("Fetching roster...")
    roster = mlb_data.get_roster(TEAM_ID, SEASON)

    print("Fetching team batting trends...")
    team_section = build_team_section(today)

    players_section = {}
    for name in PLAYERS:
        pid = mlb_data.find_player_id(name, roster)
        if pid is None:
            print(f"  WARNING: couldn't find {name} on roster, skipping")
            continue
        print(f"Fetching {name}...")
        players_section[name] = build_player_section(name, pid, today)

    print("Fetching full season game log (this takes a little while)...")
    game_log = mlb_data.get_full_season_game_log(TEAM_ID, SEASON)
    print(f"  {len(game_log)} completed games found")

    print("Computing rolling 10-game trends...")
    rolling10 = mlb_data.compute_rolling_10(game_log)

    as_of = mlb_data.get_most_recent_completed_game_date(TEAM_ID, SEASON, today)

    data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": as_of.isoformat(),
        "team": team_section,
        "players": players_section,
        "game_log": game_log,
        "rolling10": rolling10,
    }

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Wrote data.json")


if __name__ == "__main__":
    main()
