# Sports MCP Server Design

## Overview

A standalone FastMCP server (`mcp_sports_server.py`) that exposes live scores, standings, and schedule data for NFL, NBA, MLB, and NHL via the ESPN public API. No API key required. Runs on port 8001 alongside the existing weather MCP server (port 8000) and integrates into the LiveKit voice agent via MCP protocol.

## Tools

| Tool | Signature | Purpose |
|---|---|---|
| `get_scores` | `get_scores(league: str) -> str` | Live/recent game scores for a league |
| `get_standings` | `get_standings(league: str) -> str` | Current season standings |
| `get_schedule` | `get_schedule(league: str, team: str) -> str` | Upcoming games, optionally filtered by team |

The `league` parameter accepts: `nfl`, `nba`, `mlb`, `nhl` (case-insensitive).

## Data Source

ESPN public API at `site.api.espn.com`. No authentication required.

### League-to-Sport Mapping

| League | Sport Path |
|---|---|
| `nfl` | `football/nfl` |
| `nba` | `basketball/nba` |
| `mlb` | `baseball/mlb` |
| `nhl` | `hockey/nhl` |

### Endpoints

| Tool | URL Pattern |
|---|---|
| Scores | `/apis/site/v2/sports/{sport}/{league}/scoreboard` |
| Standings | `/apis/site/v2/sports/{sport}/{league}/standings` |
| Schedule | `/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=YYYYMMDD` (upcoming days range) |

### Response Formatting

All tools return concise, voice-friendly plain text. No JSON dumps, no markdown. Examples:

- **Scores:** "Lakers 112, Celtics 105 - Final" or "Warriors 54, Suns 48 - 3rd Quarter, 4:32"
- **Standings:** "NFC West: 1. 49ers (11-4), 2. Seahawks (8-7), 3. Rams (7-8), 4. Cardinals (6-9)"
- **Schedule:** "Yankees vs Red Sox, Tuesday April 1st at 7:05 PM ET"

## Server Implementation

- Framework: `FastMCP` from `mcp` package (same as weather server)
- Transport: SSE on port 8001
- HTTP client: `httpx` with 10-second timeout
- Team filtering for `get_schedule`: client-side string matching against ESPN response data
- Error handling: return human-readable error strings (same pattern as weather server)

## Agent Integration

### New Files

- `livekit-agent-mcp/mcp_sports_server.py` — the FastMCP sports server

### Modified Files

- `livekit-agent-mcp/entrypoint.sh` — start sports server on port 8001, wait for both ports before launching agent
- `livekit-agent-mcp/agent.py` — add `MCP_SPORTS_SERVER_URL` env var, add second `MCPToolset` for sports, update system prompt
- `livekit-agent-mcp/docker-compose.yml` (or root `docker-compose.yml`) — add `MCP_SPORTS_SERVER_URL` env var

### No Changes Needed

- `requirements.txt` — already has `httpx` and `mcp` dependencies

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `MCP_SPORTS_SERVER_URL` | `http://localhost:8001/sse` | Sports MCP server SSE endpoint |

### System Prompt Addition

Add to the agent's system prompt:
> When the user asks about sports scores, standings, or schedules for NFL, NBA, MLB, or NHL, use the appropriate sports tool. Use get_scores for current/recent game results, get_standings for league standings, and get_schedule to find upcoming games for a team.

## Design Decisions

- **Separate server (port 8001):** Independent from weather server for clean separation and independent restarts.
- **ESPN API only:** Consistent URL pattern across all 4 leagues, stable despite being unofficial, no API key needed.
- **Voice-friendly output:** All responses are plain text sentences suitable for TTS, not structured data.
- **Client-side team filtering:** ESPN's scoreboard endpoint doesn't support team filtering, so we match team names in the response. Simple and sufficient.
