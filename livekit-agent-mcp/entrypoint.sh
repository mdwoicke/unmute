#!/bin/bash
set -e

# Maximum number of restarts allowed per MCP server before giving up
MAX_RESTARTS=3
WEATHER_RESTARTS=0
SPORTS_RESTARTS=0

# ---------------------------------------------------------------------------
# Cleanup: kill all child processes on SIGTERM / SIGINT
# ---------------------------------------------------------------------------
cleanup() {
    echo "Received shutdown signal — stopping all processes..."
    kill "$WEATHER_PID" "$SPORTS_PID" "$AGENT_PID" 2>/dev/null || true
    wait "$WEATHER_PID" "$SPORTS_PID" "$AGENT_PID" 2>/dev/null || true
    echo "All processes stopped."
    exit 0
}
trap cleanup SIGTERM SIGINT

# ---------------------------------------------------------------------------
# Helper: non-blocking TCP reachability check (mirrors startup probe)
# ---------------------------------------------------------------------------
check_port() {
    python -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('localhost',$1)); s.close()" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Start MCP servers
# ---------------------------------------------------------------------------
echo "Starting MCP Weather Server..."
python mcp_weather_server.py &
WEATHER_PID=$!

echo "Starting MCP Sports Server..."
python mcp_sports_server.py &
SPORTS_PID=$!

# ---------------------------------------------------------------------------
# Wait for Weather MCP server on port 8000
# ---------------------------------------------------------------------------
echo "Waiting for Weather MCP server on port 8000..."
for i in $(seq 1 30); do
    if check_port 8000; then
        echo "Weather MCP server ready!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "Weather MCP server failed to start"
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# Wait for Sports MCP server on port 8001
# ---------------------------------------------------------------------------
echo "Waiting for Sports MCP server on port 8001..."
for i in $(seq 1 30); do
    if check_port 8001; then
        echo "Sports MCP server ready!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "Sports MCP server failed to start"
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# Start the LiveKit agent in the background (not exec, so we keep control)
# ---------------------------------------------------------------------------
echo "Starting LiveKit Agent..."
python agent.py start &
AGENT_PID=$!

# ---------------------------------------------------------------------------
# Monitoring loop
# ---------------------------------------------------------------------------
echo "Entering monitoring loop (10 s interval)..."
while true; do
    sleep 10

    # -- Agent liveness check ------------------------------------------------
    if ! kill -0 "$AGENT_PID" 2>/dev/null; then
        echo "ERROR: LiveKit agent (PID $AGENT_PID) has died — exiting so Docker can restart the container."
        kill "$WEATHER_PID" "$SPORTS_PID" 2>/dev/null || true
        exit 1
    fi

    # -- Weather MCP health check (port 8000) --------------------------------
    if ! check_port 8000; then
        if [ "$WEATHER_RESTARTS" -ge "$MAX_RESTARTS" ]; then
            echo "ERROR: Weather MCP server is down and has already been restarted $MAX_RESTARTS times — giving up. Continuing with remaining tools."
        else
            WEATHER_RESTARTS=$((WEATHER_RESTARTS + 1))
            echo "WARNING: Weather MCP server down, restarting... (attempt $WEATHER_RESTARTS/$MAX_RESTARTS)"
            kill "$WEATHER_PID" 2>/dev/null || true
            python mcp_weather_server.py &
            WEATHER_PID=$!
        fi
    fi

    # -- Sports MCP health check (port 8001) ---------------------------------
    if ! check_port 8001; then
        if [ "$SPORTS_RESTARTS" -ge "$MAX_RESTARTS" ]; then
            echo "ERROR: Sports MCP server is down and has already been restarted $MAX_RESTARTS times — giving up. Continuing with remaining tools."
        else
            SPORTS_RESTARTS=$((SPORTS_RESTARTS + 1))
            echo "WARNING: Sports MCP server down, restarting... (attempt $SPORTS_RESTARTS/$MAX_RESTARTS)"
            kill "$SPORTS_PID" 2>/dev/null || true
            python mcp_sports_server.py &
            SPORTS_PID=$!
        fi
    fi
done
