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


def _format_scores_utterance(events_data: list[dict]) -> str:
    """Format a list of parsed event dicts into a voice-ready spoken paragraph.

    Args:
        events_data: List of dicts with keys: away_name, home_name,
                     away_score, home_score, state, detail

    Returns:
        A single paragraph of spoken sentences describing the scores.
    """
    # Sort: live first, then final, then upcoming
    order = {"in": 0, "post": 1, "pre": 2}
    sorted_events = sorted(events_data, key=lambda e: order.get(e["state"], 3))

    cap = 5
    truncated = max(0, len(sorted_events) - cap)
    display = sorted_events[:cap]

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
            sentences.append(f"The {away} and the {home} tip off at {detail}.")

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


def _format_schedule_utterance(events_data: list[dict], team: str) -> str:
    """Format parsed schedule event dicts into a voice-ready spoken paragraph.

    Args:
        events_data: List of dicts with keys: away_name, home_name,
                     away_score, home_score, state, detail
        team: The team filter string (empty string means all teams).

    Returns:
        A single paragraph of spoken sentences describing upcoming games.
    """
    cap = 3 if team else 5
    display = events_data[:cap]

    sentences = []
    for ev in display:
        away = ev["away_name"]
        home = ev["home_name"]
        detail = _clean_detail(ev["detail"])
        state = ev["state"]

        if state == "pre":
            team_lower = team.strip().lower()
            if team_lower and team_lower in home.lower():
                sentences.append(f"The {home} host the {away} on {detail}.")
            else:
                sentences.append(f"The {away} play at the {home} on {detail}.")
        else:
            # Game in progress or final — include score
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

    events_data = []
    for event in events:
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "")
        detail = status_type.get("shortDetail", "")

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
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")

        events_data.append({
            "away_name": away_name,
            "home_name": home_name,
            "away_score": away_score,
            "home_score": home_score,
            "state": state,
            "detail": detail,
        })

    if not events_data:
        return f"No {league.upper()} games found today."

    return _format_scores_utterance(events_data)


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

    url = f"{ESPN_BASE}/{sport_path}/scoreboard"

    with httpx.Client(timeout=10) as client:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"Failed to fetch {league.upper()} scores: {e}"

    events = data.get("events", [])
    team_lower = team.strip().lower()

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

        names_to_check = [
            home_name.lower(), away_name.lower(),
            home_full.lower(), away_full.lower(),
        ]
        if not any(team_lower in n for n in names_to_check):
            continue

        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "")
        detail = status_type.get("shortDetail", "")
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")

        ev = {
            "away_name": away_name,
            "home_name": home_name,
            "away_score": away_score,
            "home_score": home_score,
            "state": state,
            "detail": detail,
        }

        # Format a single-game utterance using the same style as _format_scores_utterance
        detail_clean = _clean_detail(detail)

        if state == "in":
            try:
                away_sc = int(away_score)
                home_sc = int(home_score)
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
                away_sc = int(away_score)
                home_sc = int(home_score)
            except (ValueError, TypeError):
                away_sc = home_sc = 0

            if away_sc == home_sc:
                return f"The {away_name} and the {home_name} tied at {away_sc}."
            elif away_sc > home_sc:
                return f"The {away_name} beat the {home_name} {away_sc} to {home_sc}."
            else:
                return f"The {home_name} beat the {away_name} {home_sc} to {away_sc}."

        else:  # "pre" or unknown — upcoming
            return f"The {away_name} and the {home_name} tip off at {detail_clean}."

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
    events_data = []

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
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")

        events_data.append({
            "away_name": away_name,
            "home_name": home_name,
            "away_score": away_score,
            "home_score": home_score,
            "state": state,
            "detail": detail,
        })

    if not events_data:
        if team_lower:
            return f"No upcoming {league.upper()} games found for '{team}' in the next 7 days."
        return f"No upcoming {league.upper()} games found in the next 7 days."

    return _format_schedule_utterance(events_data, team)


if __name__ == "__main__":
    mcp.run(transport="sse")
