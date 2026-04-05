# Sports MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sports MCP server to the LiveKit voice agent that provides live scores, standings, and schedules for NFL, NBA, MLB, and NHL via the ESPN public API.

**Architecture:** Standalone FastMCP server (`mcp_sports_server.py`) on port 8001, following the identical pattern of the existing weather MCP server on port 8000. The agent discovers sports tools via MCP protocol over SSE. ESPN public API is the sole data source.

**Tech Stack:** Python 3.12, FastMCP (`mcp` package), `httpx`, LiveKit Agents SDK with MCP support.

---

### Task 1: Create the sports MCP server with `get_scores`

**Files:**
- Create: `livekit-agent-mcp/mcp_sports_server.py`

- [ ] **Step 1: Create `mcp_sports_server.py` with league mapping and `get_scores` tool**

```python
"""MCP Sports Server using FastMCP.

Exposes sports scores, standings, and schedule tools via SSE transport.
The LiveKit agent discovers and calls these tools via MCP protocol.
Data sourced from ESPN public API (no API key required).
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Sports MCP Server")

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


if __name__ == "__main__":
    mcp.run(transport="sse", port=8001)
```

- [ ] **Step 2: Verify the server starts**

Run (from `livekit-agent-mcp/` directory):
```bash
cd livekit-agent-mcp && timeout 5 python mcp_sports_server.py || true
```
Expected: Server starts listening on port 8001 (will timeout after 5s, that's fine).

- [ ] **Step 3: Commit**

```bash
git add livekit-agent-mcp/mcp_sports_server.py
git commit -m "feat: add sports MCP server with get_scores tool"
```

---

### Task 2: Add `get_standings` tool

**Files:**
- Modify: `livekit-agent-mcp/mcp_sports_server.py`

- [ ] **Step 1: Add `get_standings` tool to `mcp_sports_server.py`**

Add the following function after the `get_scores` function:

```python
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
```

- [ ] **Step 2: Verify the server still starts**

```bash
cd livekit-agent-mcp && timeout 5 python mcp_sports_server.py || true
```
Expected: Server starts on port 8001 without import errors.

- [ ] **Step 3: Commit**

```bash
git add livekit-agent-mcp/mcp_sports_server.py
git commit -m "feat: add get_standings tool to sports MCP server"
```

---

### Task 3: Add `get_schedule` tool

**Files:**
- Modify: `livekit-agent-mcp/mcp_sports_server.py`

- [ ] **Step 1: Add `get_schedule` tool to `mcp_sports_server.py`**

Add the following import at the top of the file (after existing imports):

```python
from datetime import datetime, timedelta
```

Add the following function after `get_standings`:

```python
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
```

- [ ] **Step 2: Verify the server still starts**

```bash
cd livekit-agent-mcp && timeout 5 python mcp_sports_server.py || true
```
Expected: Server starts on port 8001 without errors.

- [ ] **Step 3: Commit**

```bash
git add livekit-agent-mcp/mcp_sports_server.py
git commit -m "feat: add get_schedule tool to sports MCP server"
```

---

### Task 4: Update entrypoint.sh to start both MCP servers

**Files:**
- Modify: `livekit-agent-mcp/entrypoint.sh`

- [ ] **Step 1: Replace `entrypoint.sh` contents**

Replace the entire file with:

```bash
#!/bin/bash
set -e

echo "Starting MCP Weather Server..."
python mcp_weather_server.py &
WEATHER_PID=$!

echo "Starting MCP Sports Server..."
python mcp_sports_server.py &
SPORTS_PID=$!

# Wait for Weather MCP server on port 8000
echo "Waiting for Weather MCP server on port 8000..."
for i in $(seq 1 30); do
    if python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',8000)); s.close()" 2>/dev/null; then
        echo "Weather MCP server ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Weather MCP server failed to start"
        exit 1
    fi
    sleep 1
done

# Wait for Sports MCP server on port 8001
echo "Waiting for Sports MCP server on port 8001..."
for i in $(seq 1 30); do
    if python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',8001)); s.close()" 2>/dev/null; then
        echo "Sports MCP server ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Sports MCP server failed to start"
        exit 1
    fi
    sleep 1
done

echo "Starting LiveKit Agent..."
exec python agent.py start
```

- [ ] **Step 2: Commit**

```bash
git add livekit-agent-mcp/entrypoint.sh
git commit -m "feat: start sports MCP server alongside weather in entrypoint"
```

---

### Task 5: Update agent.py to connect to sports MCP server

**Files:**
- Modify: `livekit-agent-mcp/agent.py`

- [ ] **Step 1: Add `MCP_SPORTS_SERVER_URL` env var**

After this line (line 26):
```python
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")
```

Add:
```python
MCP_SPORTS_SERVER_URL = os.environ.get("MCP_SPORTS_SERVER_URL", "http://localhost:8001/sse")
```

- [ ] **Step 2: Update `SYSTEM_PROMPT`**

Replace the existing `SYSTEM_PROMPT` (lines 29-37) with:

```python
SYSTEM_PROMPT = """/no_think
You are a helpful voice assistant. You speak in short, natural sentences.
Your responses will be spoken aloud, so keep them concise and conversational.
Do not use markdown, bullet points, or special characters.

When the user asks about weather, temperature, or conditions for a location,
use the get_weather tool to look it up. Always use the tool rather than guessing.
Pass the city name or zipcode the user mentions.

When the user asks about sports scores, standings, or schedules for NFL, NBA, MLB,
or NHL, use the appropriate sports tool. Use get_scores for current or recent game
results, get_standings for league standings, and get_schedule to find upcoming games
for a team. Always pass the league name and team name when mentioned.
"""
```

- [ ] **Step 3: Add sports MCP toolset in `entrypoint` function**

After this line (line 69):
```python
    mcp_weather = mcp.MCPServerHTTP(url=MCP_SERVER_URL)
```

Add:
```python
    mcp_sports = mcp.MCPServerHTTP(url=MCP_SPORTS_SERVER_URL)
    logger.info(f"Connecting to Sports MCP server at {MCP_SPORTS_SERVER_URL}")
```

- [ ] **Step 4: Update the tools list in AgentSession**

Replace the tools line (line 76):
```python
        tools=[mcp.MCPToolset(id="weather_mcp", mcp_server=mcp_weather)],
```

With:
```python
        tools=[
            mcp.MCPToolset(id="weather_mcp", mcp_server=mcp_weather),
            mcp.MCPToolset(id="sports_mcp", mcp_server=mcp_sports),
        ],
```

- [ ] **Step 5: Update the greeting message**

Replace the `session.say` call (lines 84-87):
```python
    await session.say(
        "Hello! I'm your voice assistant powered by MCP tools. "
        "Ask me about the weather in any city."
    )
```

With:
```python
    await session.say(
        "Hello! I'm your voice assistant powered by MCP tools. "
        "Ask me about the weather or sports scores, standings, and schedules."
    )
```

- [ ] **Step 6: Commit**

```bash
git add livekit-agent-mcp/agent.py
git commit -m "feat: integrate sports MCP toolset into LiveKit agent"
```

---

### Task 6: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `MCP_SPORTS_SERVER_URL` to `livekit-agent-mcp` service**

In the `livekit-agent-mcp` service environment section, after:
```yaml
      - MCP_SERVER_URL=http://localhost:8000/sse
```

Add:
```yaml
      - MCP_SPORTS_SERVER_URL=http://localhost:8001/sse
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add sports MCP server URL to docker-compose"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Rebuild the MCP agent container**

```bash
docker compose build livekit-agent-mcp
```
Expected: Build succeeds, `mcp_sports_server.py` is included in the image.

- [ ] **Step 2: Start the services**

```bash
docker compose up livekit-agent-mcp -d
```
Expected: Container starts, logs show both MCP servers ready and agent connected.

- [ ] **Step 3: Check container logs for both MCP servers**

```bash
docker compose logs livekit-agent-mcp --tail 30
```
Expected: Logs show "Weather MCP server ready!", "Sports MCP server ready!", and "Starting LiveKit Agent..."

- [ ] **Step 4: Commit any fixes if needed**

If any issues were found and fixed, commit them:
```bash
git add -A
git commit -m "fix: resolve sports MCP integration issues"
```
