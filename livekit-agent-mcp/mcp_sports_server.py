"""MCP Sports Server using FastMCP.

Exposes sports scores, standings, and schedule tools via SSE transport.
The LiveKit agent discovers and calls these tools via MCP protocol.
Data sourced from ESPN public API (no API key required).
"""

import httpx
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Sports MCP Server", port=8001)

LEAGUES = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


def _validate_league(league: str) -> tuple[str, str | None]:
    """Validate and resolve league to ESPN sport path.

    Returns (sport_path, error_message). error_message is None on success.
    """
    key = league.strip().lower()
    path = LEAGUES.get(key)
    if path is None:
        return "", f"Unknown league: {league}. Supported: {', '.join(LEAGUES.keys())}"
    return path, None


@mcp.tool()
def get_scores(league: str) -> str:
    """Get live and recent game scores for a league.

    Args:
        league: The league to get scores for: nfl, nba, mlb, or nhl

    Returns:
        Human-readable summary of current/recent game scores
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    url = f"{ESPN_BASE}/{sport_path}/scoreboard"

    with httpx.Client(timeout=10) as client:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Failed to fetch {league.upper()} scores: {e}"

    events = data.get("events", [])
    if not events:
        return f"No {league.upper()} games found today."

    lines = []
    for event in events:
        name = event.get("name", "Unknown")
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "")
        detail = status_type.get("shortDetail", "")

        competitions = event.get("competitions", [])
        if not competitions:
            lines.append(f"{name} - {detail}")
            continue

        competitors = competitions[0].get("competitors", [])
        if len(competitors) == 2:
            home = competitors[0]
            away = competitors[1]
            home_name = home.get("team", {}).get("shortDisplayName", "Home")
            away_name = away.get("team", {}).get("shortDisplayName", "Away")
            home_score = home.get("score", "0")
            away_score = away.get("score", "0")

            if state == "pre":
                game_date = status_obj.get("type", {}).get("shortDetail", "Scheduled")
                lines.append(f"{away_name} at {home_name} - {game_date}")
            else:
                lines.append(f"{away_name} {away_score}, {home_name} {home_score} - {detail}")
        else:
            lines.append(f"{name} - {detail}")

    return "\n".join(lines)


@mcp.tool()
def get_standings(league: str) -> str:
    """Get current season standings for a league.

    Args:
        league: The league to get standings for: nfl, nba, mlb, or nhl

    Returns:
        Human-readable standings grouped by division or conference
    """
    sport_path, error = _validate_league(league)
    if error:
        return error

    url = f"{ESPN_BASE}/{sport_path}/standings"

    with httpx.Client(timeout=10) as client:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Failed to fetch {league.upper()} standings: {e}"

    children = data.get("children", [])
    if not children:
        return f"No {league.upper()} standings available."

    lines = []
    for group in children:
        group_name = group.get("name", "Unknown")

        # Some leagues have sub-groups (divisions within conferences)
        sub_groups = group.get("children", [])
        if sub_groups:
            for sub in sub_groups:
                sub_name = sub.get("name", "")
                header = f"{group_name} - {sub_name}" if sub_name else group_name
                lines.append(header + ":")
                standings = sub.get("standings", {}).get("entries", [])
                for i, entry in enumerate(standings, 1):
                    team_name = entry.get("team", {}).get("shortDisplayName", "Unknown")
                    stats = {s["name"]: s["displayValue"] for s in entry.get("stats", [])}
                    wins = stats.get("wins", "0")
                    losses = stats.get("losses", "0")
                    lines.append(f"  {i}. {team_name} ({wins}-{losses})")
        else:
            lines.append(f"{group_name}:")
            standings = group.get("standings", {}).get("entries", [])
            for i, entry in enumerate(standings, 1):
                team_name = entry.get("team", {}).get("shortDisplayName", "Unknown")
                stats = {s["name"]: s["displayValue"] for s in entry.get("stats", [])}
                wins = stats.get("wins", "0")
                losses = stats.get("losses", "0")
                lines.append(f"  {i}. {team_name} ({wins}-{losses})")

    return "\n".join(lines)


@mcp.tool()
def get_schedule(league: str, team: str = "") -> str:
    """Get upcoming game schedule for a league, optionally filtered by team name.

    Args:
        league: The league to check: nfl, nba, mlb, or nhl
        team: Optional team name to filter by (e.g. 'Lakers', 'Yankees'). If empty, shows all upcoming games.

    Returns:
        Human-readable list of upcoming games
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
    url = f"{ESPN_BASE}/{sport_path}/scoreboard?dates={date_range}"

    with httpx.Client(timeout=10) as client:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Failed to fetch {league.upper()} schedule: {e}"

    events = data.get("events", [])
    if not events:
        return f"No upcoming {league.upper()} games found in the next 7 days."

    team_lower = team.strip().lower()
    lines = []

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue

        competitors = competitions[0].get("competitors", [])
        if len(competitors) != 2:
            continue

        home = competitors[0]
        away = competitors[1]
        home_name = home.get("team", {}).get("shortDisplayName", "Home")
        away_name = away.get("team", {}).get("shortDisplayName", "Away")
        home_full = home.get("team", {}).get("displayName", home_name)
        away_full = away.get("team", {}).get("displayName", away_name)

        # Filter by team if specified
        if team_lower:
            names_to_check = [
                home_name.lower(), away_name.lower(),
                home_full.lower(), away_full.lower(),
            ]
            if not any(team_lower in n for n in names_to_check):
                continue

        status_obj = event.get("status", {})
        detail = status_obj.get("type", {}).get("shortDetail", "TBD")
        state = status_obj.get("type", {}).get("state", "")

        if state == "pre":
            lines.append(f"{away_name} at {home_name} - {detail}")
        else:
            home_score = home.get("score", "0")
            away_score = away.get("score", "0")
            lines.append(f"{away_name} {away_score}, {home_name} {home_score} - {detail}")

    if not lines:
        if team_lower:
            return f"No upcoming {league.upper()} games found for '{team}' in the next 7 days."
        return f"No upcoming {league.upper()} games found in the next 7 days."

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="sse")
