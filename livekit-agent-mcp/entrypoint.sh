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
