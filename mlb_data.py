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


# ---------------------------------------------------------------------------
# Pitching trends (team + individual starters/relievers) -- ERA and WHIP
# ---------------------------------------------------------------------------

def _pitching_stat(split):
    s = split["stat"]
    return {
        "era": float(s.get("era", 0) or 0),
        "whip": float(s.get("whip", 0) or 0),
    }


def get_team_pitching_daterange_split(team_id, start_date, end_date):
    data = _get(
        f"/teams/{team_id}/stats", stats="byDateRange", group="pitching",
        startDate=start_date.isoformat(), endDate=end_date.isoformat(),
    )
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _pitching_stat(split)
    return {"era": 0.0, "whip": 0.0}


def get_team_pitching_season_split(team_id, season):
    data = _get(f"/teams/{team_id}/stats", stats="season", group="pitching", season=season)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _pitching_stat(split)
    return {"era": 0.0, "whip": 0.0}


def get_team_pitching_month_splits(team_id, season):
    out = {}
    for year, month, start, end in _recent_month_windows():
        stat = get_team_pitching_daterange_split(team_id, start, end)
        if stat["era"] or stat["whip"]:
            out[f"{month:02d}"] = stat
    return out


def get_pitcher_season_split(person_id, season):
    data = _get(f"/people/{person_id}/stats", stats="season", group="pitching", season=season)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _pitching_stat(split)
    return {"era": 0.0, "whip": 0.0}


def get_pitcher_month_splits(person_id, season):
    out = {}
    for year, month, start, end in _recent_month_windows():
        data = _get(
            f"/people/{person_id}/stats", stats="byDateRange", group="pitching",
            startDate=start.isoformat(), endDate=end.isoformat(),
        )
        stat = {"era": 0.0, "whip": 0.0}
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                stat = _pitching_stat(split)
        if stat["era"] or stat["whip"]:
            out[f"{month:02d}"] = stat
    return out


def get_pitcher_last_n_games_split(person_id, season, n):
    """Same 'lastXGames' approach validated for hitters -- should be equally
    authoritative for pitchers, but PLEASE double check the first real
    numbers against mlb.com once this is deployed (untested against live
    pitching data as of writing)."""
    data = _get(f"/people/{person_id}/stats", stats="lastXGames", group="pitching", season=season, limit=n)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            s = split["stat"]
            return {"era": float(s.get("era", 0) or 0), "whip": float(s.get("whip", 0) or 0)}
    return {"era": 0.0, "whip": 0.0}


# ---------------------------------------------------------------------------
# Cohort pitching aggregates (e.g. "your 6 tracked starters combined") --
# built from raw counting stats since ERA/WHIP can't just be averaged
# across pitchers, they have to be recomputed from summed innings/earned
# runs/hits/walks.
# ---------------------------------------------------------------------------

def _innings_str_to_outs(ip):
    """MLB formats innings pitched as e.g. '6.2' meaning 6 and 2/3 innings
    (the decimal digit is thirds of an inning, NOT a decimal fraction) --
    this converts to total outs recorded (6.2 -> 6*3 + 2 = 20)."""
    ip = str(ip or "0.0")
    whole, _, frac = ip.partition(".")
    whole = int(whole or 0)
    frac = int(frac or 0)  # 0, 1, or 2 (thirds of an inning)
    return whole * 3 + frac


def _pitching_counts(split):
    s = split["stat"]
    return {
        "earned_runs": int(s.get("earnedRuns", 0) or 0),
        "outs": _innings_str_to_outs(s.get("inningsPitched", "0.0")),
        "hits": int(s.get("hits", 0) or 0),
        "walks": int(s.get("baseOnBalls", 0) or 0),
    }


def get_pitcher_counts_daterange(person_id, start_date, end_date):
    data = _get(
        f"/people/{person_id}/stats", stats="byDateRange", group="pitching",
        startDate=start_date.isoformat(), endDate=end_date.isoformat(),
    )
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _pitching_counts(split)
    return {"earned_runs": 0, "outs": 0, "hits": 0, "walks": 0}


def get_pitcher_counts_season(person_id, season):
    data = _get(f"/people/{person_id}/stats", stats="season", group="pitching", season=season)
    for group in data.get("stats", []):
        for split in group.get("splits", []):
            return _pitching_counts(split)
    return {"earned_runs": 0, "outs": 0, "hits": 0, "walks": 0}


def get_pitcher_counts_month_splits(person_id, season):
    """Same 4-month window logic as get_pitcher_month_splits, but returns
    raw counts instead of ERA/WHIP, keyed the same way."""
    out = {}
    for year, month, start, end in _recent_month_windows():
        counts = get_pitcher_counts_daterange(person_id, start, end)
        if counts["outs"]:
            out[f"{month:02d}"] = counts
    return out


def _sum_counts(counts_list):
    total = {"earned_runs": 0, "outs": 0, "hits": 0, "walks": 0}
    for c in counts_list:
        for k in total:
            total[k] += c.get(k, 0)
    return total


def _counts_to_era_whip(counts):
    outs = counts["outs"]
    if not outs:
        return {"era": 0.0, "whip": 0.0}
    innings = outs / 3
    era = 9 * counts["earned_runs"] / innings
    whip = (counts["hits"] + counts["walks"]) / innings
    return {"era": round(era, 3), "whip": round(whip, 3)}


def build_cohort_pitching_aggregate(person_ids, season, today):
    """Aggregates ERA/WHIP across a specific group of pitchers (e.g. your
    tracked starters or tracked bullpen arms) for month-by-month splits, the
    season total, and last 30/15/7 CALENDAR DAYS (not games -- there's no
    shared 'last N games' across multiple pitchers who don't all pitch in
    the same games, so this cohort view uses date ranges throughout, same
    as the team-wide view)."""
    windows = current_month_windows(today)

    month_splits = {}
    for year, month, start, end in _recent_month_windows(today):
        per_pitcher = [get_pitcher_counts_daterange(pid, start, end) for pid in person_ids]
        total = _sum_counts(per_pitcher)
        if total["outs"]:
            month_splits[f"{month:02d}"] = _counts_to_era_whip(total)

    season_counts = _sum_counts([get_pitcher_counts_season(pid, season) for pid in person_ids])
    d30_counts = _sum_counts([get_pitcher_counts_daterange(pid, windows[30], today) for pid in person_ids])
    d15_counts = _sum_counts([get_pitcher_counts_daterange(pid, windows[15], today) for pid in person_ids])
    d7_counts = _sum_counts([get_pitcher_counts_daterange(pid, windows[7], today) for pid in person_ids])

    return {
        "month_splits": month_splits,
        "season": _counts_to_era_whip(season_counts),
        "last_30_days": _counts_to_era_whip(d30_counts),
        "last_15_days": _counts_to_era_whip(d15_counts),
        "last_7_days": _counts_to_era_whip(d7_counts),
    }
