"""
Pulls all the data the dashboard needs from MLB's official Stats API
(statsapi.mlb.com, free, no key required). Reuses the exact logic already
validated in the nyy_automation and nyy_score_trends projects earlier this
season -- this version is stateless (always rebuilds from scratch each run)
rather than incrementally patching a spreadsheet, since that's a better fit
for a scheduled cloud job with no persistent local state to build on.
"""
from datetime import date, timedelta

import requests

BASE = "https://statsapi.mlb.com/api/v1"


def _get(path, **params):
    r = requests.get(f"{BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Batting trends (team + individual players)
# ---------------------------------------------------------------------------

def get_roster(team_id, season):
    data = _get(f"/teams/{team_id}/roster", rosterType="fullSeason", season=season)
    return {p["person"]["fullName"]: p["person"]["id"] for p in data.get("roster", [])}


def find_player_id(name, roster):
    if name in roster:
        return roster[name]
    norm = lambda s: s.lower().replace(".", "").replace("é", "e").replace("í", "i")
    target = norm(name)
    for full_name, pid in roster.items():
        if norm(full_name) == target or target in norm(full_name):
            return pid
    return None


def _hitting_stat(split):
    s = split["stat"]
    return {
        "avg": float(s.get("avg", 0) or 0),
        "obp": float(s.get("obp", 0) or 0),
        "slg": float(s.get("slg", 0) or 0),
    }


def _recent_month_windows(today=None):
    import calendar
    today = today or date.today()
    y, m = today.year, today.month
    months = []
    for i in range(3, -1, -1):
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append((yy, mm))
    windows = []
    for yy, mm in months:
        start = date(yy, mm, 1)
        if start > today:
            continue
        last_day = calendar.monthrange(yy, mm)[1]
        end = date(yy, mm, last_day)
        if end > today:
            end = today
        windows.append((yy, mm, start, end))
    return windows


def get_team_daterange_split(team_id, start_date, end_date):
    data = _get(
        f"/teams/{team_id}/stats", stats="byDateRange", group="hitting",
        startDate=start_date.isoformat(), endDate=end_date.isoformat(),
    )
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _hitting_stat(split)
    return {"avg": 0.0, "obp": 0.0, "slg": 0.0}


def get_team_season_split(team_id, season):
    data = _get(f"/teams/{team_id}/stats", stats="season", group="hitting", season=season)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _hitting_stat(split)
    return {"avg": 0.0, "obp": 0.0, "slg": 0.0}


def get_player_season_split(person_id, season):
    data = _get(f"/people/{person_id}/stats", stats="season", group="hitting", season=season)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _hitting_stat(split)
    return {"avg": 0.0, "obp": 0.0, "slg": 0.0}


def get_team_month_splits(team_id, season):
    out = {}
    for year, month, start, end in _recent_month_windows():
        stat = get_team_daterange_split(team_id, start, end)
        if stat["avg"] or stat["obp"] or stat["slg"]:
            out[f"{month:02d}"] = stat
    return out


def get_player_month_splits(person_id, season):
    out = {}
    for year, month, start, end in _recent_month_windows():
        data = _get(
            f"/people/{person_id}/stats", stats="byDateRange", group="hitting",
            startDate=start.isoformat(), endDate=end.isoformat(),
        )
        stat = {"avg": 0.0, "obp": 0.0, "slg": 0.0}
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                stat = _hitting_stat(split)
        if stat["avg"] or stat["obp"] or stat["slg"]:
            out[f"{month:02d}"] = stat
    return out


def current_month_windows(today=None):
    today = today or date.today()
    return {30: today - timedelta(days=29), 15: today - timedelta(days=14), 7: today - timedelta(days=6)}


def get_player_last_n_games_split(person_id, season, n):
    """Uses MLB's own 'lastXGames' stat type -- guaranteed to match mlb.com
    exactly since it's the same source (validated earlier against Paul
    Goldschmidt, Jose Caballero, and Ryan McMahon)."""
    data = _get(f"/people/{person_id}/stats", stats="lastXGames", group="hitting", season=season, limit=n)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            s = split["stat"]
            return {"avg": float(s.get("avg", 0) or 0), "obp": float(s.get("obp", 0) or 0),
                     "slg": float(s.get("slg", 0) or 0)}
    return {"avg": 0.0, "obp": 0.0, "slg": 0.0}


def get_most_recent_completed_game_date(team_id, season, today=None):
    today = today or date.today()
    try:
        lookback_start = today - timedelta(days=10)
        data = _get("/schedule", teamId=team_id, sportId=1,
                     startDate=lookback_start.isoformat(), endDate=today.isoformat())
        completed_dates = []
        for d in data.get("dates", []):
            for game in d.get("games", []):
                if game.get("status", {}).get("abstractGameState") == "Final":
                    completed_dates.append(d["date"])
        if completed_dates:
            return date.fromisoformat(max(completed_dates))
    except Exception:
        pass
    return today - timedelta(days=1)


# ---------------------------------------------------------------------------
# Full-season game log + rolling 10-game trends (for the score/pitching chart)
# ---------------------------------------------------------------------------

def get_full_season_game_log(team_id, season):
    """Returns every completed game this season, chronologically, with final
    score/result plus the team's batting line and cumulative rate stats
    through that game (all from one box score call per game -- MLB's box
    score endpoint conveniently already computes cumulative avg/obp/slg for
    us, confirmed against real data earlier this season)."""
    season_start = date(season, 3, 1)  # safely before opening day
    today = date.today()
    sched = _get("/schedule", teamId=team_id, sportId=1, gameType="R",
                 startDate=season_start.isoformat(), endDate=today.isoformat(),
                 hydrate="linescore,team")

    games = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue
            home, away = g["teams"]["home"], g["teams"]["away"]
            is_home = home["team"]["id"] == team_id
            us, them = (home, away) if is_home else (away, home)
            if us.get("score") is None or them.get("score") is None:
                continue
            games.append({
                "gamePk": g["gamePk"],
                "date": d["date"],
                "opponent": them["team"].get("abbreviation", them["team"]["name"][:3].upper()),
                "home_away": "" if is_home else "@",
                "result": "W" if us["score"] > them["score"] else "L",
                "runs_scored": us["score"],
                "runs_allowed": them["score"],
            })
    games.sort(key=lambda x: (x["date"], x["gamePk"]))

    for i, g in enumerate(games, start=1):
        box = _get(f"/game/{g['gamePk']}/boxscore")
        for side in ("home", "away"):
            if box["teams"][side]["team"]["id"] == team_id:
                s = box["teams"][side]["teamStats"]["batting"]
                g["game_num"] = i
                g["AB"] = int(s.get("atBats", 0) or 0)
                g["H"] = int(s.get("hits", 0) or 0)
                g["cum_avg"] = float(s.get("avg", 0) or 0)
                g["cum_obp"] = float(s.get("obp", 0) or 0)
                g["cum_slg"] = float(s.get("slg", 0) or 0)
                break
    return games


def compute_rolling_10(game_log):
    """Trailing 10-game runs/game, runs allowed/game, run differential, and
    batting average -- same math as the 'data10' sheet in the score-trends
    spreadsheet."""
    rolling = []
    for i in range(9, len(game_log)):
        window = game_log[i - 9: i + 1]
        rs = sum(g["runs_scored"] for g in window)
        ra = sum(g["runs_allowed"] for g in window)
        ab = sum(g["AB"] for g in window)
        h = sum(g["H"] for g in window)
        rolling.append({
            "game_num": game_log[i]["game_num"],
            "date": game_log[i]["date"],
            "runs_per_game": rs / 10,
            "runs_allowed_per_game": ra / 10,
            "run_diff": (rs - ra) / 10,
            "avg": h / ab if ab else 0.0,
        })
    return rolling
