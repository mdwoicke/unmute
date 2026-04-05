"""MCP Sports Server using FastMCP.

Exposes sports scores, standings, and schedule tools via SSE transport.
The LiveKit agent discovers and calls these tools via MCP protocol.
Data sourced from ESPN public API (no API key required).
"""

import httpx
from datetime import datetime, timedelta, timezone
from mcp.server.fastmcp import FastMCP

try:
    from zoneinfo import ZoneInfo
    _eastern = ZoneInfo("America/New_York")
except Exception:
    _eastern = None

mcp = FastMCP("Sports MCP Server", port=8001)

LEAGUES = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# Module-level HTTP client — reuses TCP connections across tool calls
_http = httpx.Client(timeout=10, base_url=ESPN_BASE)

# Sport-specific phrasing for upcoming ("pre") games
_UPCOMING_PHRASE = {
    "nba": "tip off at",
    "nfl": "kick off at",
    "mlb": "first pitch is at",
    "nhl": "puck drops at",
}


def _validate_league(league: str) -> tuple[str, str | None]:
    """Validate and resolve league to ESPN sport path.

    Returns (sport_path, error_message). error_message is None on success.
    """
    key = league.strip().lower()
    path = LEAGUES.get(key)
    if path is None:
        return "", f"Unknown league: {league}. Supported: {', '.join(LEAGUES.keys())}"
    return path, None


def _clean_detail(detail: str) -> str:
    """Clean ESPN shortDetail text for natural speech.

    Replaces ordinal abbreviations with spelled-out words, expands OT,
    lowercases period/quarter/half labels, and strips stray dashes.
    """
    replacements = [
        ("1st", "first"),
        ("2nd", "second"),
        ("3rd", "third"),
        ("4th", "fourth"),
        ("OT", "overtime"),
        ("Quarter", "quarter"),
        ("Period", "period"),
        ("Half", "half"),
    ]
    result = detail
    for old, new in replacements:
        result = result.replace(old, new)
    # Remove stray leading/trailing dashes and extra whitespace
    result = result.strip(" -")
    return result


def _to_eastern(dt_utc: datetime) -> datetime:
    """Convert a UTC datetime to US Eastern time."""
    if _eastern is not None:
        return dt_utc.astimezone(_eastern)

    year = dt_utc.year

    def nth_sunday(y: int, month: int, n: int) -> datetime:
        first = datetime(y, month, 1, tzinfo=timezone.utc)
        days_until_sunday = (6 - first.weekday()) % 7
        first_sunday = first + timedelta(days=days_until_sunday)
        return first_sunday + timedelta(weeks=n - 1)

    edt_start = nth_sunday(year, 3, 2)
    edt_end = nth_sunday(year, 11, 1)
    if edt_start <= dt_utc.replace(tzinfo=timezone.utc) < edt_end:
        offset = timezone(timedelta(hours=-4))
    else:
        offset = timezone(timedelta(hours=-5))
    return dt_utc.astimezone(offset)


def _spoken_time(dt: datetime) -> str:
    """Format a datetime as spoken time, e.g. '7 30 PM Eastern' or '1 PM Eastern'."""
    hour = dt.hour
    minute = dt.minute
    period = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    if minute == 0:
        return f"{hour12} {period} Eastern"
    return f"{hour12} {minute:02d} {period} Eastern"


def _spoken_date(dt: datetime) -> str:
    """Format a datetime as a spoken date, e.g. 'April 5th'."""
    month = dt.strftime("%B")
    day = dt.day
    if 11 <= day <= 13:
        suffix = "th"
    elif day % 10 == 1:
        suffix = "st"
    elif day % 10 == 2:
        suffix = "nd"
    elif day % 10 == 3:
        suffix = "rd"
    else:
        suffix = "th"
    return f"{month} {day}{suffix}"


def _relative_date_from_iso(date_str: str) -> str:
    """Convert an ESPN ISO 8601 event date to relative spoken phrasing.

    Parses strings like "2026-03-30T23:30Z" and converts to Eastern time.
    Returns phrases like "today at 7 30 PM Eastern", "tomorrow at 3 PM Eastern",
    "this Saturday at 1 PM Eastern", or "April 12th at 7 PM Eastern".
    Falls back to _clean_detail on the raw string if parsing fails.
    """
    if not date_str:
        return ""
    try:
        game_dt_utc = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        game_dt = _to_eastern(game_dt_utc)
        now_eastern = _to_eastern(datetime.now(timezone.utc))

        delta_days = (game_dt.date() - now_eastern.date()).days
        time_str = _spoken_time(game_dt)

        if delta_days == 0:
            return f"today at {time_str}"
        elif delta_days == 1:
            return f"tomorrow at {time_str}"
        elif 2 <= delta_days <= 6:
            weekday = game_dt.strftime("%A")
            return f"this {weekday} at {time_str}"
        else:
            return f"{_spoken_date(game_dt)} at {time_str}"
    except Exception:
        return _clean_detail(date_str)


def _parse_events(events: list[dict]) -> list[dict]:
    """Parse ESPN events into a standardized list of event dicts."""
    result = []
    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        competitors = competitions[0].get("competitors", [])
        if len(competitors) != 2:
            continue

        home = competitors[0]
        away = competitors[1]
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})

        result.append({
            "away_name": away.get("team", {}).get("shortDisplayName", "Away"),
            "home_name": home.get("team", {}).get("shortDisplayName", "Home"),
            "away_full": away.get("team", {}).get("displayName", ""),
            "home_full": home.get("team", {}).get("displayName", ""),
            "away_score": away.get("score", "0"),
            "home_score": home.get("score", "0"),
            "state": status_type.get("state", ""),
            "detail": status_type.get("shortDetail", ""),
            "date": event.get("date", ""),
        })
    return result


def _upcoming_phrase(league: str) -> str:
    """Return the sport-specific verb phrase for an upcoming game."""
    return _UPCOMING_PHRASE.get(league.strip().lower(), "tip off at")


def _format_scores_utterance(events_data: list[dict], league: str) -> str:
    """Format a list of parsed event dicts into a voice-ready spoken paragraph.

    Args:
        events_data: List of dicts with keys: away_name, home_name,
                     away_score, home_score, state, detail
        league: Lowercase league key (nba, nfl, mlb, nhl) used for
                sport-specific phrasing of upcoming games.

    Returns:
        A single paragraph of spoken sentences describing the scores.
    """
    # Sort: live first, then final, then upcoming
    order = {"in": 0, "post": 1, "pre": 2}
    sorted_events = sorted(events_data, key=lambda e: order.get(e["state"], 3))

    cap = 5
    truncated = max(0, len(sorted_events) - cap)
    display = sorted_events[:cap]

    phrase = _upcoming_phrase(league)

    sentences = []
    for ev in display:
        state = ev["state"]
        away = ev["away_name"]
        home = ev["home_name"]
        detail = _clean_detail(ev["detail"])

        if state == "in":
            try:
                away_sc = int(ev["away_score"])
                home_sc = int(ev["home_score"])
            except (ValueError, TypeError):
                away_sc = home_sc = 0

            if away_sc > home_sc:
                leader, trailer, high, low = away, home, away_sc, home_sc
            elif home_sc > away_sc:
                leader, trailer, high, low = home, away, home_sc, away_sc
            else:
                # Tied while live
                sentences.append(
                    f"The {away} and the {home} are tied at {away_sc} in the {detail}."
                )
                continue

            sentences.append(
                f"The {leader} lead the {trailer} {high} to {low} in the {detail}."
            )

        elif state == "post":
            try:
                away_sc = int(ev["away_score"])
                home_sc = int(ev["home_score"])
            except (ValueError, TypeError):
                away_sc = home_sc = 0

            if away_sc == home_sc:
                sentences.append(
                    f"The {away} and the {home} tied at {away_sc}."
                )
            elif away_sc > home_sc:
                sentences.append(
                    f"The {away} beat the {home} {away_sc} to {home_sc}."
                )
            else:
                sentences.append(
                    f"The {home} beat the {away} {home_sc} to {away_sc}."
                )

        else:  # "pre" or unknown — upcoming
            spoken_date = _relative_date_from_iso(ev.get("date", "")) or detail
            sentences.append(f"The {away} and the {home} {phrase} {spoken_date}.")

    if truncated > 0:
        sentences.append(f"There are also {truncated} other games scheduled.")

    return " ".join(sentences)


def _format_standings_utterance(children: list[dict]) -> str:
    """Format ESPN standings children into a voice-ready spoken paragraph.

    Args:
        children: The top-level list from the ESPN standings response's
                  'children' key.

    Returns:
        A single paragraph of spoken sentences summarising top standings.
    """
    sentences = []
    group_count = 0
    has_more = False

    for group in children:
        if group_count >= 2:
            has_more = True
            break

        group_name = group.get("name", "Unknown")
        sub_groups = group.get("children", [])

        if sub_groups:
            # Divisions within conferences — pick first 2 sub-groups
            for sub_idx, sub in enumerate(sub_groups):
                if sub_idx >= 2:
                    break
                sub_name = sub.get("name", "")
                label = f"{group_name} {sub_name}".strip()
                entries = sub.get("standings", {}).get("entries", [])[:3]
                sentence = _standings_sentence(label, entries)
                if sentence:
                    sentences.append(sentence)
        else:
            entries = group.get("standings", {}).get("entries", [])[:3]
            sentence = _standings_sentence(group_name, entries)
            if sentence:
                sentences.append(sentence)

        group_count += 1

    if has_more:
        sentences.append("There are more divisions in the standings.")

    return " ".join(sentences)


def _standings_sentence(group_name: str, entries: list[dict]) -> str:
    """Build one standings sentence for up to 3 teams in a group."""
    if not entries:
        return ""

    def record(entry: dict) -> tuple[str, str, str]:
        team_name = entry.get("team", {}).get("shortDisplayName", "Unknown")
        stats = {s["name"]: s["displayValue"] for s in entry.get("stats", [])}
        wins = stats.get("wins", "0")
        losses = stats.get("losses", "0")
        return team_name, wins, losses

    if len(entries) == 1:
        t1, w1, l1 = record(entries[0])
        return (
            f"In the {group_name}, the {t1} lead at {w1} and {l1}."
        )
    elif len(entries) == 2:
        t1, w1, l1 = record(entries[0])
        t2, w2, l2 = record(entries[1])
        return (
            f"In the {group_name}, the {t1} lead at {w1} and {l1}, "
            f"followed by the {t2} at {w2} and {l2}."
        )
    else:
        t1, w1, l1 = record(entries[0])
        t2, w2, l2 = record(entries[1])
        t3, w3, l3 = record(entries[2])
        return (
            f"In the {group_name}, the {t1} lead at {w1} and {l1}, "
            f"followed by the {t2} at {w2} and {l2} "
            f"and the {t3} at {w3} and {l3}."
        )


def _format_schedule_utterance(events_data: list[dict], team: str, league: str) -> str:
    """Format parsed schedule event dicts into a voice-ready spoken paragraph.

    Args:
        events_data: List of dicts with keys: away_name, home_name,
                     away_score, home_score, state, detail, date
        team: The team filter string (empty string means all teams).
        league: Lowercase league key (nba, nfl, mlb, nhl) used for
                sport-specific phrasing of upcoming games.

    Returns:
        A single paragraph of spoken sentences describing upcoming games.
    """
    cap = 3 if team else 5
    display = events_data[:cap]

    phrase = _upcoming_phrase(league)

    sentences = []
    for ev in display:
        away = ev["away_name"]
        home = ev["home_name"]
        state = ev["state"]

        if state == "pre":
            detail = _relative_date_from_iso(ev["date"]) if ev.get("date") else _clean_detail(ev["detail"])
            team_lower = team.strip().lower()
            if team_lower and team_lower in home.lower():
                sentences.append(f"The {home} host the {away}, {phrase} {detail}.")
            else:
                sentences.append(f"The {away} visit the {home}, {phrase} {detail}.")
        else:
            # Game in progress or final — include score
            detail = _clean_detail(ev["detail"])
            away_sc = ev.get("away_score", "0")
            home_sc = ev.get("home_score", "0")
            sentences.append(
                f"The {away} lead the {home} {away_sc} to {home_sc} in the {detail}."
            )

    return " ".join(sentences)


@mcp.tool()
def get_scores(league: str) -> str:
    """Get live and recent game scores for a league.

    Args:
        league: The league to get scores for: nfl, nba, mlb, or nhl

    Returns:
        A brief spoken summary of the most notable current scores
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    try:
        resp = _http.get(f"/{sport_path}/scoreboard")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Failed to fetch {league.upper()} scores: {e}"

    events = data.get("events", [])
    if not events:
        return f"No {league.upper()} games found today."

    events_data = _parse_events(events)

    if not events_data:
        return f"No {league.upper()} games found today."

    return _format_scores_utterance(events_data, league.strip().lower())


@mcp.tool()
def get_team_score(team: str, league: str) -> str:
    """Get the score for a specific team's current or most recent game.

    Args:
        team: Team name to look up (e.g. 'Lakers', 'Yankees', 'Chiefs')
        league: The league: nfl, nba, mlb, or nhl

    Returns:
        A spoken sentence describing the team's current game score or result
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    try:
        resp = _http.get(f"/{sport_path}/scoreboard")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Failed to fetch {league.upper()} scores: {e}"

    events = data.get("events", [])
    team_lower = team.strip().lower()
    league_key = league.strip().lower()

    for ev in _parse_events(events):
        names_to_check = [
            ev["away_name"].lower(),
            ev["home_name"].lower(),
            ev["away_full"].lower(),
            ev["home_full"].lower(),
        ]
        if not any(team_lower in n for n in names_to_check):
            continue

        away_name = ev["away_name"]
        home_name = ev["home_name"]
        state = ev["state"]
        detail_clean = _clean_detail(ev["detail"])

        if state == "in":
            try:
                away_sc = int(ev["away_score"])
                home_sc = int(ev["home_score"])
            except (ValueError, TypeError):
                away_sc = home_sc = 0

            if away_sc > home_sc:
                leader, trailer, high, low = away_name, home_name, away_sc, home_sc
            elif home_sc > away_sc:
                leader, trailer, high, low = home_name, away_name, home_sc, away_sc
            else:
                return f"The {away_name} and the {home_name} are tied at {away_sc} in the {detail_clean}."

            return f"The {leader} lead the {trailer} {high} to {low} in the {detail_clean}."

        elif state == "post":
            try:
                away_sc = int(ev["away_score"])
                home_sc = int(ev["home_score"])
            except (ValueError, TypeError):
                away_sc = home_sc = 0

            if away_sc == home_sc:
                return f"The {away_name} and the {home_name} tied at {away_sc}."
            elif away_sc > home_sc:
                return f"The {away_name} beat the {home_name} {away_sc} to {home_sc}."
            else:
                return f"The {home_name} beat the {away_name} {home_sc} to {away_sc}."

        else:  # "pre" or unknown — upcoming
            phrase = _upcoming_phrase(league_key)
            spoken_date = _relative_date_from_iso(ev.get("date", "")) or _clean_detail(ev["detail"])
            return f"The {away_name} and the {home_name} {phrase} {spoken_date}."

    return f"I couldn't find a game for {team} in the {league} today."


@mcp.tool()
def get_standings(league: str) -> str:
    """Get current season standings for a league.

    Args:
        league: The league to get standings for: nfl, nba, mlb, or nhl

    Returns:
        A brief spoken summary of top teams in each division
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    try:
        resp = _http.get(f"/{sport_path}/standings")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Failed to fetch {league.upper()} standings: {e}"

    children = data.get("children", [])
    if not children:
        return f"No {league.upper()} standings available."

    return _format_standings_utterance(children)


@mcp.tool()
def get_schedule(league: str, team: str = "") -> str:
    """Get upcoming game schedule for a league, optionally filtered by team name.

    Args:
        league: The league to check: nfl, nba, mlb, or nhl
        team: Optional team name to filter by (e.g. 'Lakers', 'Yankees'). If empty, shows all upcoming games.

    Returns:
        A brief spoken summary of upcoming games
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    # Build date range: today + 7 days
    today = datetime.now()
    dates = []
    for i in range(7):
        day = today + timedelta(days=i)
        dates.append(day.strftime("%Y%m%d"))

    date_range = f"{dates[0]}-{dates[-1]}"

    try:
        resp = _http.get(f"/{sport_path}/scoreboard", params={"dates": date_range})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Failed to fetch {league.upper()} schedule: {e}"

    events = data.get("events", [])
    if not events:
        return f"No upcoming {league.upper()} games found in the next 7 days."

    team_lower = team.strip().lower()
    all_events = _parse_events(events)

    # Filter by team if specified
    if team_lower:
        events_data = [
            ev for ev in all_events
            if any(
                team_lower in n
                for n in [
                    ev["away_name"].lower(),
                    ev["home_name"].lower(),
                    ev["away_full"].lower(),
                    ev["home_full"].lower(),
                ]
            )
        ]
    else:
        events_data = all_events

    if not events_data:
        if team_lower:
            return f"No upcoming {league.upper()} games found for '{team}' in the next 7 days."
        return f"No upcoming {league.upper()} games found in the next 7 days."

    return _format_schedule_utterance(events_data, team, league.strip().lower())


if __name__ == "__main__":
    mcp.run(transport="sse")
