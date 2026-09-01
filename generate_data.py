#!/usr/bin/env python3
"""
Fetches current Yankees batting + pitching trends and season game log, and
writes it all to data.json for the dashboard (index.html) to read. Designed
to be run by a scheduled GitHub Action, but works fine run manually/locally too.
"""
import json
from datetime import date, datetime

import mlb_data

SEASON = 2026
TEAM_ID = 147

PLAYERS = [
    "Aaron Judge", "Ben Rice", "Paul Goldschmidt", "Jose Caballero", "Jazz Chisholm Jr.",
    "Cody Bellinger", "Jasson Dominguez", "Anthony Volpe", "Trent Grisham",
    "Ryan McMahon", "Amed Rosario", "Austin Wells",
    "Luis Garcia Jr.", "Heliot Ramos", "George Lombard Jr.", "Spencer Jones",
]

# Players acquired mid-season: their stats should ONLY reflect games played
# as a Yankee, not their prior team's numbers from earlier in the season.
# MLB's standard season/month/lastXGames stats don't separate this out, so
# for anyone in this dict, every stat window (month, season, and recent
# form) gets bounded to start no earlier than this date.
RECENT_ACQUISITIONS = {
    "Luis Garcia Jr.": date(2026, 8, 3),
    "Heliot Ramos": date(2026, 8, 4),
    "George Lombard Jr.": date(2026, 8, 4),
}

STARTING_PITCHERS = [
    "Max Fried", "Cam Schlittler", "Gerrit Cole", "Will Warren", "Carlos Rodón", "Ryan Weathers", "Elmer Rodriguez"
]

BULLPEN_PITCHERS = [
    "David Bednar", "Brent Headrick", "Angel Chivilli", "Paul Blackburn", "Fernando Cruz",
    "Tim Hill", "Ryan Yarbrough", "Luis Gil"
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


def build_recently_acquired_player_section(person_id, acquisition_date, today):
    """For a player who joined the Yankees mid-season: every window (month,
    season, recent form) is bounded to start no earlier than acquisition_date,
    so none of their prior team's stats leak in. Uses byDateRange throughout
    instead of the normal season/lastXGames endpoints, which can't be scoped
    to 'just this team' on their own."""
    month_splits = {}
    for year, month, start, end in mlb_data._recent_month_windows(today):
        clipped_start = max(start, acquisition_date)
        if clipped_start > end:
            continue  # this whole month was entirely before the trade
        stat = mlb_data.get_player_daterange_split(person_id, clipped_start, end)
        if stat["avg"] or stat["obp"] or stat["slg"]:
            month_splits[f"{month:02d}"] = stat
    month_splits = month_splits_to_named(month_splits, today)

    season = mlb_data.get_player_daterange_split(person_id, acquisition_date, today)

    return {
        "mlb_id": person_id,
        "month_splits": month_splits,
        "season": season,
        "last_30_games": mlb_data.get_player_recent_games_since(person_id, SEASON, acquisition_date, 30),
        "last_15_games": mlb_data.get_player_recent_games_since(person_id, SEASON, acquisition_date, 15),
        "last_7_games": mlb_data.get_player_recent_games_since(person_id, SEASON, acquisition_date, 7),
    }


def build_team_pitching_section(today):
    month_splits = month_splits_to_named(mlb_data.get_team_pitching_month_splits(TEAM_ID, SEASON), today)
    windows = mlb_data.current_month_windows(today)
    return {
        "month_splits": month_splits,
        "season": mlb_data.get_team_pitching_season_split(TEAM_ID, SEASON),
        "last_30_days": mlb_data.get_team_pitching_daterange_split(TEAM_ID, windows[30], today),
        "last_15_days": mlb_data.get_team_pitching_daterange_split(TEAM_ID, windows[15], today),
        "last_7_days": mlb_data.get_team_pitching_daterange_split(TEAM_ID, windows[7], today),
    }


def build_pitcher_section(name, person_id, today):
    month_splits = month_splits_to_named(mlb_data.get_pitcher_month_splits(person_id, SEASON), today)
    return {
        "mlb_id": person_id,
        "month_splits": month_splits,
        "season": mlb_data.get_pitcher_season_split(person_id, SEASON),
        "last_10_games": mlb_data.get_pitcher_last_n_games_split(person_id, SEASON, 10),
        "last_5_games": mlb_data.get_pitcher_last_n_games_split(person_id, SEASON, 5),
        "last_3_games": mlb_data.get_pitcher_last_n_games_split(person_id, SEASON, 3),
    }


def build_pitcher_group(names, roster, today):
    section = {}
    ids = []
    for name in names:
        pid = mlb_data.find_player_id(name, roster)
        if pid is None:
            print(f"  WARNING: couldn't find '{name}' on roster, skipping (check spelling/roster status)")
            continue
        print(f"Fetching {name} (pitching)...")
        section[name] = build_pitcher_section(name, pid, today)
        ids.append(pid)

    if ids:
        print(f"  Computing combined aggregate across {len(ids)} pitcher(s)...")
        aggregate = mlb_data.build_cohort_pitching_aggregate(ids, SEASON, today)
        aggregate["month_splits"] = month_splits_to_named(aggregate["month_splits"], today)
        # Put the team aggregate first in the dict so it's the default-selected option.
        section = {"New York Yankees (Selected)": aggregate, **section}
    return section


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
        if pid is None and name in RECENT_ACQUISITIONS:
            print(f"  '{name}' not in roster feed yet (common right after a trade) -- trying player search instead...")
            pid = mlb_data.find_player_id_by_search(name)
        if pid is None:
            print(f"  WARNING: couldn't find {name} on roster, skipping")
            continue
        if name in RECENT_ACQUISITIONS:
            print(f"Fetching {name} (Yankees stats only, since {RECENT_ACQUISITIONS[name].isoformat()})...")
            players_section[name] = build_recently_acquired_player_section(pid, RECENT_ACQUISITIONS[name], today)
        else:
            print(f"Fetching {name}...")
            players_section[name] = build_player_section(name, pid, today)

    print("Fetching team pitching trends...")
    team_pitching_section = build_team_pitching_section(today)

    print("Fetching starting pitchers...")
    starting_pitchers_section = build_pitcher_group(STARTING_PITCHERS, roster, today)

    print("Fetching bullpen pitchers...")
    bullpen_pitchers_section = build_pitcher_group(BULLPEN_PITCHERS, roster, today)

    print("Fetching full season game log (this takes a little while)...")
    game_log = mlb_data.get_full_season_game_log(TEAM_ID, SEASON)
    print(f"  {len(game_log)} completed games found")

    print("Computing rolling 10-game trends...")
    rolling10 = mlb_data.compute_rolling_10(game_log)

    print("Fetching per-game starter/bullpen pitching breakdown (this takes a while too)...")
    pitching_game_log = mlb_data.get_pitching_game_log(TEAM_ID, SEASON)
    print(f"  {len(pitching_game_log)} games with pitching data found")

    print("Computing rolling 10-game pitching trends (starters/bullpen/all)...")
    pitching_rolling10 = mlb_data.compute_rolling_10_pitching(pitching_game_log)

    as_of = mlb_data.get_most_recent_completed_game_date(TEAM_ID, SEASON, today)

    data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of_date": as_of.isoformat(),
        "team": team_section,
        "players": players_section,
        "team_pitching": team_pitching_section,
        "starting_pitchers": starting_pitchers_section,
        "bullpen_pitchers": bullpen_pitchers_section,
        "game_log": game_log,
        "rolling10": rolling10,
        "pitching_rolling10": pitching_rolling10,
    }

    with open("data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Wrote data.json")


if __name__ == "__main__":
    main()
