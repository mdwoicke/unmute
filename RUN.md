---
name: unmute-runner
description: Start and manage all Unmute LiveKit Builder voice agent services — STT/TTS Docker containers, LiveKit server, Python agent, Next.js frontend, and Node.js proxy. Use when asked to start, stop, restart, or check status of the unmute app.
type: skill
---

# Unmute LiveKit Builder — How to Run

Quick-start guide and skill reference for launching all services. All commands run from project root `D:\Applications\examples\unmute`.

## Skill Instructions

When invoked as a skill to start the app:

1. Run the **Pre-flight Checks** to verify dependencies
2. For any failed check, fix it before proceeding (start Docker, check LM Studio, etc.)
3. Start services **in order** (Steps 1-5) — each step depends on the previous
4. After starting each service, verify it before moving to the next
5. Run the **Health Check** at the end to confirm everything is up
6. Kill any process on a conflicting port BEFORE starting — never let Next.js auto-increment ports
7. Always use the exact ports specified — they are hardcoded in Cloudflare Tunnel and router configs

## Pre-flight Checks

| Dependency | Required Port | How to check |
|-----------|--------------|-------------|
| Docker Desktop | — | `docker ps` (engine must be started) |
| LM Studio | 1234 | `curl -s http://localhost:1234/v1/models` |
| `.env` file | — | Must contain `HUGGING_FACE_HUB_TOKEN`, `CF_TURN_TOKEN_ID`, `CF_TURN_API_TOKEN` |
| Cloudflared | — | `tasklist \| grep cloudflared` (auto-starts as Windows service) |

```bash
# Quick pre-flight
curl -s http://localhost:1234/v1/models | python -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['data']]"
docker ps > /dev/null 2>&1 && echo "Docker: OK" || echo "Docker: NOT RUNNING"
tasklist 2>/dev/null | grep -q cloudflared && echo "Cloudflared: OK" || echo "Cloudflared: NOT RUNNING"
cat .env | head -1 > /dev/null 2>&1 && echo ".env: OK" || echo ".env: MISSING"
```

## Start Services (in order)

### Step 1: STT/TTS Containers (Kyutai Moshi — GPU)

```bash
cd D:/Applications/examples/unmute
docker compose up -d stt tts
```

**Wait for healthy** (~5-10 min first run, ~30s subsequent):

```bash
docker ps --filter "name=unmute" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected:
```
unmute-stt-1   Up (healthy)   0.0.0.0:8090->8080/tcp
unmute-tts-1   Up (healthy)   0.0.0.0:8089->8080/tcp
```

Do NOT proceed until both show `(healthy)`.

### Step 2: LiveKit Server

First kill any existing LiveKit process:
```bash
netstat -ano | grep ":7880.*LISTENING" | awk '{print $5}' | xargs -I{} taskkill //F //PID {}
```

Start:
```bash
cd D:/Applications/examples/unmute
./livekit-server.exe --dev --config livekit-server-config.yaml --bind 0.0.0.0
```

**Verify** — must see all of:
- `nodeIP: 99.66.11.228`
- `rtc.portTCP: 7881`
- `rtc.portICERange: [7882, 7882]`
- `Starting TURN server {"turn.portUDP": 3478}`

**Critical UDP check** — must be bound to `192.168.1.221`, NOT `172.27.96.1`:
```bash
netstat -ano | grep "UDP.*7882"
```

If bound to wrong interface, verify `interfaces.excludes: vEthernet` in `livekit-server-config.yaml`.

### Step 3: Builder Agent

```bash
cd D:/Applications/examples/unmute/livekit-agent-builder

LIVEKIT_URL=ws://localhost:7880 \
LIVEKIT_API_KEY=devkey \
LIVEKIT_API_SECRET=secret \
LM_STUDIO_URL=http://localhost:1234/v1 \
LM_STUDIO_MODEL=qwen3-4b \
LLM_MODEL=qwen3-4b \
KYUTAI_STT_URL=ws://localhost:8090 \
KYUTAI_TTS_URL=ws://localhost:8089 \
IVA_SOURCE_PATH=D:/Applications/dynamic-skills-agent \
PYTHONPATH=D:/Applications/dynamic-skills-agent \
TTS_GAIN=1.5 \
python agent.py dev
```

**Verify**: `registered worker {"agent_name": "unmute-livekit-agent-builder"}` in output.

If missing dependencies: `pip install -r requirements.txt`

### Step 4: Builder Frontend (Next.js — port 5334)

Kill any existing process on port 5334 first:
```bash
netstat -ano | grep ":5334.*LISTENING" | awk '{print $5}' | xargs -I{} taskkill //F //PID {}
```

Start:
```bash
cd D:/Applications/examples/unmute/livekit-frontend-builder

CF_TURN_TOKEN_ID=308cf0007e8811f12e27c6cffbb28e5a \
CF_TURN_API_TOKEN=c020e2f5174c93197ff64993f120652ca359af56364174159c6bc6f050f02df2 \
npx next dev -p 5334
```

If missing dependencies: `npm install`

**Verify**: `Ready in Xms` at `http://localhost:5334`.

### Step 5: Proxy (port 5333 — Cloudflare tunnel target)

Kill any existing process on port 5333 first:
```bash
netstat -ano | grep ":5333.*LISTENING" | awk '{print $5}' | xargs -I{} taskkill //F //PID {}
```

Start:
```bash
cd D:/Applications/examples/unmute/livekit-frontend-builder
node proxy.js
```

**Verify**: `Proxy listening on :5333 -> Next.js :5334 + LiveKit :7880`

### Step 6: MCP Frontend (optional — port 3000)

```bash
cd D:/Applications/examples/unmute/livekit-frontend-mcp
npx next dev -p 3000
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ External: https://moshi.digitalresponsetech.com                 │
│   └─ Cloudflare Tunnel → proxy:5333                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ proxy.js     │    │ Next.js      │    │ LiveKit      │      │
│  │ :5333        │───→│ :5334        │    │ :7880 HTTP   │      │
│  │ HTTP + WS    │    │ Frontend     │    │ :7881 ICE/TCP│      │
│  │              │    │ + TURN creds │    │ :7882 ICE/UDP│      │
│  │ /livekit-ws/ │───────────────────────→│ :3478 TURN   │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                  │              │
│                                           ┌──────┴──────┐      │
│                                           │ Agent (Py)  │      │
│                                           │ IVA Bridge  │      │
│                                           └──────┬──────┘      │
│                            ┌─────────────────────┼──────────┐  │
│                      ┌─────┴─────┐    ┌─────────┴┐  ┌──────┴┐ │
│                      │ STT :8090 │    │ TTS :8089│  │LM 1234│ │
│                      │ Docker GPU│    │ Docker   │  │Studio │ │
│                      └───────────┘    └──────────┘  └───────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Port Reference

| Port | Proto | Service | Process | Must Be |
|------|-------|---------|---------|---------|
| 1234 | TCP | LM Studio (Qwen 3 4B) | LM Studio | Running before agent |
| 3000 | TCP | MCP Frontend | node (next) | Optional |
| 3478 | UDP | TURN Server | livekit-server | Port forwarded on router |
| 5333 | TCP | Proxy (HTTP+WS) | node (proxy.js) | Cloudflare tunnel target |
| 5334 | TCP | Builder Frontend | node (next) | Internal only |
| 7880 | TCP | LiveKit Signaling | livekit-server | Proxied via 5333 |
| 7881 | TCP | ICE TCP | livekit-server | Port forwarded on router |
| 7882 | UDP | ICE UDP | livekit-server | Bound to 192.168.1.221 |
| 8089 | TCP | Kyutai TTS | Docker moshi | Container port 8080 |
| 8090 | TCP | Kyutai STT | Docker moshi | Container port 8080 |
| 30000-30002 | UDP | TURN Relay | livekit-server | Auto-managed |

**NEVER change these ports — Cloudflare Tunnel and router port forwards depend on them.**

## LiveKit Server Config

`livekit-server-config.yaml`:
```yaml
rtc:
  port_range_start: 7882
  port_range_end: 7882
  tcp_port: 7881
  node_ip: 99.66.11.228          # External IP — update if ISP changes it
  use_ice_lite: false             # Must be false for external access
  stun_servers:
    - stun.cloudflare.com:3478
  interfaces:
    excludes:
      - vEthernet                 # Exclude WSL/Docker virtual adapters

turn:
  enabled: true
  domain: moshi.digitalresponsetech.com
  udp_port: 3478
```

## Network Requirements (already configured)

### AT&T Router (192.168.1.254)

**NAT/Gaming port forwards** (Firewall > NAT/Gaming):

| Service | Ports | Protocol | Device |
|---------|-------|----------|--------|
| LiveKit-WebRTC | 7881-7882 | TCP/UDP | Home_Server |
| LiveKit-TURN | 3478 | UDP | Home_Server |

**Firewall Advanced** (Firewall > Firewall Advanced):

| Setting | Value |
|---------|-------|
| **Reflexive ACL** | **OFF** (CRITICAL for external WebRTC) |

### Windows Firewall

Already added via elevated PowerShell:
```powershell
netsh advfirewall firewall add rule name="LiveKit HTTP" dir=in action=allow protocol=TCP localport=7880
netsh advfirewall firewall add rule name="LiveKit ICE-TCP" dir=in action=allow protocol=TCP localport=7881
netsh advfirewall firewall add rule name="LiveKit ICE-UDP" dir=in action=allow protocol=UDP localport=7882
netsh advfirewall firewall add rule name="LiveKit TURN-UDP" dir=in action=allow protocol=UDP localport=3478
netsh advfirewall firewall add rule name="LiveKit TURN-Relay" dir=in action=allow protocol=UDP localport=30000-30002
netsh advfirewall firewall add rule name="LiveKit-Frontend" dir=in action=allow protocol=TCP localport=5333
netsh advfirewall firewall add rule name="LiveKit-Frontend-MCP" dir=in action=allow protocol=TCP localport=3000
```

### Cloudflare Tunnel Route

| Hostname | Service |
|----------|---------|
| `moshi.digitalresponsetech.com` | `http://192.168.1.221:5333` |

### Cloudflare TURN Server

Dashboard > Media > Realtime > TURN Server > `unmute-livekit`:
- Token ID: stored in `.env` as `CF_TURN_TOKEN_ID`
- API Token: stored in `.env` as `CF_TURN_API_TOKEN`
- Credentials generated per-session by `/api/token` endpoint

## Health Check

```bash
echo "=== Docker ===" && \
docker ps --filter "name=unmute" --format "{{.Names}}: {{.Status}}" && \
echo "=== LiveKit ===" && \
curl -s http://localhost:7880 > /dev/null && echo "LiveKit: OK" || echo "LiveKit: DOWN" && \
echo "=== LM Studio ===" && \
curl -s http://localhost:1234/v1/models | python -c "import sys,json;d=json.load(sys.stdin);print(f'Models: {len(d[\"data\"])}')" 2>/dev/null || echo "LM Studio: DOWN" && \
echo "=== Frontend ===" && \
curl -s http://localhost:5333 > /dev/null && echo "Frontend: OK" || echo "Frontend: DOWN" && \
echo "=== Ports ===" && \
netstat -ano | grep -E "LISTENING.*(7880|7881|5333|5334)" | awk '{print $2, "OPEN"}' && \
netstat -ano | grep "UDP.*7882" | awk '{print $2, "OPEN (UDP)"}' && \
echo "=== External IP ===" && \
curl -s https://api.ipify.org && echo ""
```

## Test

| Test | URL | From |
|------|-----|------|
| Local | `http://localhost:5333` | This machine |
| LAN | `http://192.168.1.221:5333` | Same network |
| External | `https://moshi.digitalresponsetech.com` | Phone on mobile data |

## Stop Services

```bash
# Docker STT/TTS
docker compose stop stt tts

# LiveKit server
netstat -ano | grep ":7880.*LISTENING" | awk '{print $5}' | head -1 | xargs -I{} taskkill //F //PID {}

# All Node.js (proxy + frontend) — kills ALL node processes
taskkill //F //IM node.exe

# Agent — kills ALL python processes
taskkill //F //IM python.exe
```

## Quick Restart (after reboot)

```bash
cd D:/Applications/examples/unmute

# 1. Docker STT/TTS
docker compose up -d stt tts
echo "Waiting for STT/TTS healthy..." && sleep 60

# 2. LiveKit server
./livekit-server.exe --dev --config livekit-server-config.yaml --bind 0.0.0.0 &
sleep 3

# 3. Agent
cd livekit-agent-builder && \
LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret \
LM_STUDIO_URL=http://localhost:1234/v1 LM_STUDIO_MODEL=qwen3-4b LLM_MODEL=qwen3-4b \
KYUTAI_STT_URL=ws://localhost:8090 KYUTAI_TTS_URL=ws://localhost:8089 \
IVA_SOURCE_PATH=D:/Applications/dynamic-skills-agent PYTHONPATH=D:/Applications/dynamic-skills-agent \
TTS_GAIN=1.5 python agent.py dev &
cd ..

# 4. Frontend + proxy
cd livekit-frontend-builder && \
CF_TURN_TOKEN_ID=308cf0007e8811f12e27c6cffbb28e5a \
CF_TURN_API_TOKEN=c020e2f5174c93197ff64993f120652ca359af56364174159c6bc6f050f02df2 \
npx next dev -p 5334 &
sleep 5 && node proxy.js &
cd ..

echo "All services started. Test: http://localhost:5333"
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Port already in use | `netstat -ano \| grep :<port>` then `taskkill //F //PID <pid>` |
| Next.js picks wrong port | Always use `-p <port>` — kill conflicting process first |
| Agent: "no module named livekit" | `pip install -r livekit-agent-builder/requirements.txt` |
| Agent: "no worker available" | LiveKit server must start before agent |
| STT/TTS: "invalid bearer token" | Check `HUGGING_FACE_HUB_TOKEN` in `.env` |
| STT/TTS still starting | Wait — first run compiles Rust + downloads models (~10 min) |
| UDP 7882 on wrong interface | `interfaces.excludes: vEthernet` in livekit config |
| External can't connect | AT&T router: **Reflexive ACL must be OFF** |
| External IP changed | `curl https://api.ipify.org` — update `node_ip` in config |
| Docker not running | Start Docker Desktop, wait for engine, then `docker compose up -d stt tts` |
| LM Studio not loaded | Open LM Studio, load `qwen3-4b`, start server on port 1234 |
