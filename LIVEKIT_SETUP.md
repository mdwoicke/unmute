# Unmute LiveKit - Complete Setup Guide

This document covers the full end-to-end setup of the Unmute LiveKit voice agent with function calling (weather demo), running 100% locally on Windows 11 with Docker Desktop and LM Studio.

## Architecture

```
Browser (HTTPS :3443)
  |
  v
nginx (SSL termination + reverse proxy)
  |-- / --> livekit-frontend (Next.js :3000)
  |-- /livekit-ws/ --> LiveKit Server (:7880 on host)
  |-- /api/token --> livekit-frontend token API
  |
LiveKit Server (native on host, ports 7880/7881/7882)
  |
  v
LiveKit Python Agent (Docker)
  |-- STT: Custom KyutaiSTT --> moshi-server STT (Docker, ws://stt:8080)
  |-- LLM: OpenAI plugin --> LM Studio (host, http://localhost:1234/v1)
  |     |-- @function_tool get_weather(zipcode) --> Open-Meteo API
  |-- TTS: Custom KyutaiTTS --> moshi-server TTS (Docker, ws://tts:8080)
```

## Prerequisites

- **OS**: Windows 11 with WSL2
- **GPU**: NVIDIA with 16GB+ VRAM (tested on RTX 3090 24GB)
- **Docker Desktop**: With WSL2 backend and NVIDIA Container Toolkit
- **LM Studio**: Installed and running (https://lmstudio.ai)
- **HuggingFace Account**: With a read-only access token

## Models Used

| Component | Model | VRAM | Served By |
|-----------|-------|------|-----------|
| STT | `kyutai/stt-1b-en_fr-candle` | ~2.5GB | Docker moshi-server |
| TTS | `kyutai/tts-1.6b-en_fr` + voices | ~5.3GB | Docker moshi-server |
| LLM | `qwen/qwen3-4b` | ~3GB | LM Studio on host |

Total VRAM: ~11GB

## Network Ports

| Port | Protocol | Service | Access |
|------|----------|---------|--------|
| 3443 | TCP/HTTPS | LiveKit nginx (frontend + WS proxy) | Browser |
| 3333 | TCP/HTTP | LiveKit nginx (redirects to HTTPS) | Browser |
| 7880 | TCP | LiveKit Server (signaling) | Agent + nginx proxy |
| 7881 | TCP | LiveKit Server (RTC TCP fallback) | WebRTC |
| 7882 | UDP | LiveKit Server (RTC media) | WebRTC |
| 1234 | TCP | LM Studio (OpenAI-compatible API) | Agent container |
| 9090 | TCP/HTTP | Original Unmute demo nginx (optional) | Browser |
| 9443 | TCP/HTTPS | Original Unmute demo nginx (optional) | Browser |

## Step-by-Step Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/kyutai-labs/unmute.git
cd unmute
```

### Step 2: Set HuggingFace Token

```bash
export HUGGING_FACE_HUB_TOKEN=hf_your_token_here
```

### Step 3: Set Up LM Studio

1. Open LM Studio
2. Download `qwen/qwen3-4b` (GGUF, Q4_K_M quantization)
3. Load the model
4. Go to **Developer** tab > **Start Server** (serves on `http://localhost:1234`)
5. Verify: `curl http://localhost:1234/v1/models`

**Important settings for voice use:**
- Maximize GPU offload layers
- Set context length to 2048-4096 (lower = faster)
- Enable flash attention if available

### Step 4: Download LiveKit Server Binary

LiveKit server must run **natively on the host** (NOT in Docker) because Docker Desktop for Windows doesn't support host networking, which breaks WebRTC ICE candidate negotiation.

```bash
# Download LiveKit server for Windows
curl -sL -o livekit-server.zip "https://github.com/livekit/livekit/releases/download/v1.10.1/livekit_1.10.1_windows_amd64.zip"
unzip livekit-server.zip livekit-server.exe
```

### Step 5: Generate Self-Signed SSL Certificates

HTTPS is required for browser microphone access on non-localhost URLs.

**LiveKit frontend certs:**
```bash
mkdir -p livekit-frontend/certs
cd livekit-frontend/certs
MSYS_NO_PATHCONV=1 openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key -out selfsigned.crt \
  -subj "/CN=unmute-livekit.local" \
  -addext "subjectAltName=DNS:localhost,IP:YOUR_LOCAL_IP,IP:127.0.0.1"
cd ../..
```

**Original Unmute demo certs (optional):**
```bash
mkdir -p services/nginx/certs
cd services/nginx/certs
MSYS_NO_PATHCONV=1 openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout selfsigned.key -out selfsigned.crt \
  -subj "/CN=unmute.local" \
  -addext "subjectAltName=DNS:localhost,IP:YOUR_LOCAL_IP,IP:127.0.0.1"
cd ../../..
```

Replace `YOUR_LOCAL_IP` with your machine's LAN IP (e.g., `192.168.1.221`).

### Step 6: Windows Firewall Rules

Run these in an **admin terminal**:

```cmd
netsh advfirewall firewall add rule name="Unmute LiveKit HTTPS" dir=in action=allow protocol=TCP localport=3443
netsh advfirewall firewall add rule name="Unmute LiveKit HTTP" dir=in action=allow protocol=TCP localport=3333
netsh advfirewall firewall add rule name="Unmute LiveKit WebRTC TCP" dir=in action=allow protocol=TCP localport=7880-7881
netsh advfirewall firewall add rule name="Unmute LiveKit WebRTC UDP" dir=in action=allow protocol=UDP localport=7882
```

For the original Unmute demo (optional):
```cmd
netsh advfirewall firewall add rule name="Unmute Web UI" dir=in action=allow protocol=TCP localport=9090
netsh advfirewall firewall add rule name="Unmute HTTPS" dir=in action=allow protocol=TCP localport=9443
```

### Step 7: Start LiveKit Server (Native)

```bash
nohup ./livekit-server.exe --dev --bind 0.0.0.0 --node-ip YOUR_LOCAL_IP > /tmp/livekit-server.log 2>&1 &
```

Replace `YOUR_LOCAL_IP` with your LAN IP. Verify:
```bash
curl http://localhost:7880/
# Should return: OK
```

**Dev mode credentials:** API Key = `devkey`, API Secret = `secret`

### Step 8: Build and Start Docker Services

```bash
export HUGGING_FACE_HUB_TOKEN=hf_your_token_here

# Build and start STT/TTS first (slow first build - Rust compilation)
docker compose up --build -d stt tts

# Wait for STT/TTS to become healthy (check with docker compose ps)
# This takes 10-20 minutes on first run

# Then start LiveKit services
docker compose up --build -d livekit-agent livekit-frontend livekit-nginx
```

### Step 9: Verify All Services

```bash
# Check container status
docker compose ps

# Expected: stt (healthy), tts (healthy), livekit-agent (running),
#           livekit-frontend (healthy), livekit-nginx (running)

# Verify LiveKit agent registered
docker compose logs livekit-agent --tail 5
# Should show: "registered worker"

# Verify TTS from agent container
docker exec unmute-livekit-agent-1 python3 -c '
import asyncio, websockets, msgpack
async def test():
    ws = await websockets.connect("ws://tts:8080/api/tts_streaming?format=PcmMessagePack&voice=unmute-prod-website/p329_022.wav&cfg_alpha=1.5",
        additional_headers={"kyutai-api-key": "public_token"})
    print("TTS:", msgpack.unpackb(await ws.recv()).get("type"))
    await ws.close()
asyncio.run(test())
'

# Verify STT from agent container
docker exec unmute-livekit-agent-1 python3 -c '
import asyncio, websockets, msgpack
async def test():
    ws = await websockets.connect("ws://stt:8080/api/asr-streaming",
        additional_headers={"kyutai-api-key": "public_token"})
    print("STT:", msgpack.unpackb(await ws.recv()).get("type"))
    await ws.close()
asyncio.run(test())
'

# Verify LM Studio from agent container
docker exec unmute-livekit-agent-1 python3 -c '
import urllib.request
print(urllib.request.urlopen("http://host.docker.internal:1234/v1/models").read().decode()[:100])
'
```

### Step 10: Access the App

- **LiveKit demo**: https://localhost:3443 or https://YOUR_LOCAL_IP:3443
- **Original Unmute demo** (optional): https://localhost:9443

Accept the self-signed certificate warning in your browser (Advanced > Proceed).

## File Structure

```
unmute/
  docker-compose.yml                    # Main orchestration
  livekit-server.exe                    # Native LiveKit server binary
  livekit-server-config.yaml            # LiveKit config (unused with native)

  livekit-agent/                        # LiveKit Python agent
    agent.py                            # Main agent entry point
    kyutai_stt.py                       # Custom STT adapter for moshi-server
    kyutai_tts.py                       # Custom TTS adapter for moshi-server
    weather_tools.py                    # Weather function calling tool
    requirements.txt                    # Python dependencies
    Dockerfile

  livekit-frontend/                     # LiveKit React frontend
    src/app/page.tsx                    # Main UI component
    src/app/layout.tsx                  # Root layout
    src/app/globals.css                 # Styles
    src/app/api/token/route.ts          # Token generation API
    package.json
    next.config.ts
    tsconfig.json
    Dockerfile
    nginx/nginx.conf                    # HTTPS reverse proxy config
    certs/                              # Self-signed SSL certs
      selfsigned.crt
      selfsigned.key

  unmute/                               # Original Unmute backend (Python/FastAPI)
    llm/system_prompt.py                # Contains /no_think for Qwen models
    llm/llm_utils.py                    # LLM streaming client
    kyutai_constants.py                 # Environment variable config

  frontend/                             # Original Unmute frontend (Next.js)
  services/moshi-server/                # STT/TTS Dockerfile and configs
  services/nginx/                       # Original demo nginx + certs
  voices.yaml                           # Voice configurations
  volumes/                              # Docker volume data (auto-created)
```

## Configuration Details

### docker-compose.yml Key Settings

**Backend (original demo):**
```yaml
environment:
  - KYUTAI_LLM_URL=http://host.docker.internal:1234  # LM Studio (code appends /v1)
  - KYUTAI_LLM_MODEL=qwen/qwen3-4b                   # Must match LM Studio model ID
```

**LiveKit Agent:**
```yaml
environment:
  - LIVEKIT_URL=ws://host.docker.internal:7880        # Native LiveKit server
  - LIVEKIT_API_KEY=devkey
  - LIVEKIT_API_SECRET=secret
  - LM_STUDIO_URL=http://host.docker.internal:1234/v1
  - LM_STUDIO_MODEL=qwen/qwen3-4b
  - KYUTAI_STT_URL=ws://stt:8080                      # Docker internal DNS
  - KYUTAI_TTS_URL=ws://tts:8080
```

**Important:** The agent does NOT use `depends_on` for STT/TTS to avoid recreating those slow-starting containers on every agent rebuild.

### nginx Configuration (livekit-frontend/nginx/nginx.conf)

```nginx
resolver 127.0.0.11 valid=10s;

server {
    listen 80;
    return 301 https://$host:3443$request_uri;
}

server {
    listen 443 ssl;
    ssl_certificate /etc/nginx/certs/selfsigned.crt;
    ssl_certificate_key /etc/nginx/certs/selfsigned.key;

    location / {
        set $frontend http://livekit-frontend:3000;
        proxy_pass $frontend;
        # WebSocket support for Next.js hot reload
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location /livekit-ws/ {
        set $livekit http://host.docker.internal:7880;
        rewrite ^/livekit-ws/(.*) /$1 break;
        proxy_pass $livekit;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

### Token Generation (livekit-frontend/src/app/api/token/route.ts)

The token must include:
- `roomCreate: true` — allows creating the room
- `agent: true` — tells server to dispatch an agent
- `roomConfig.agents[].agentName` — specifies which agent to dispatch

### System Prompt (/no_think)

Qwen 3.x models use a "thinking" mode that puts tokens into `reasoning_content` instead of `content`. The system prompt starts with `/no_think` to disable this. Without it, the LLM response appears empty and the TTS has nothing to speak.

## Startup Sequence (Complete)

```bash
# 1. Set environment
export HUGGING_FACE_HUB_TOKEN=hf_your_token_here

# 2. Start LM Studio and load qwen/qwen3-4b, start server

# 3. Start LiveKit server natively
nohup ./livekit-server.exe --dev --bind 0.0.0.0 --node-ip YOUR_LOCAL_IP > /tmp/livekit-server.log 2>&1 &

# 4. Start STT/TTS (wait for healthy)
docker compose up --build -d stt tts
# Monitor: docker compose ps (wait for "healthy")

# 5. Start LiveKit services
docker compose up --build -d livekit-agent livekit-frontend livekit-nginx

# 6. Verify agent registered
docker compose logs livekit-agent --tail 5 | grep registered

# 7. Open browser: https://localhost:3443
```

## Shutdown

```bash
# Stop Docker services
docker compose down

# Stop LiveKit server
taskkill /F /IM livekit-server.exe

# Stop LM Studio server (via LM Studio UI)
```

## Rebuilding After Code Changes

```bash
# Rebuild ONLY the agent (does NOT recreate STT/TTS)
docker compose build livekit-agent
docker compose up -d --no-deps --force-recreate livekit-agent

# Rebuild frontend
docker compose up --build -d --force-recreate livekit-frontend

# If you changed docker-compose.yml env vars, you MUST recreate (not just restart)
docker compose up -d --force-recreate livekit-agent
```

## Known Issues and Fixes

### 1. LiveKit Server Must Run Natively (Not in Docker)

**Problem:** Docker Desktop for Windows doesn't support `network_mode: host`. LiveKit server in Docker uses internal Docker IPs for WebRTC ICE candidates, which browsers can't reach.

**Fix:** Run `livekit-server.exe` natively on the host with `--bind 0.0.0.0 --node-ip YOUR_LOCAL_IP`. The agent connects via `ws://host.docker.internal:7880`.

### 2. Traefik Docker Socket Fails on Docker Desktop Windows

**Problem:** Traefik's Docker provider can't access the Docker socket on Docker Desktop for Windows (`/var/run/docker.sock` is broken).

**Fix:** Replace Traefik with nginx using static routing configuration. Use Docker's internal DNS resolver (`resolver 127.0.0.11`) and variable-based `proxy_pass` for lazy DNS resolution.

### 3. Qwen 3.x "Thinking" Mode Produces Empty Responses

**Problem:** Qwen 3.x and 3.5 models put output into `reasoning_content` instead of `content` in streaming mode. The backend reads only `content`, getting 0 words.

**Fix:** Prepend `/no_think` as the first line of the system prompt. For the original Unmute demo, this is in `unmute/llm/system_prompt.py`. For LiveKit, it's in `livekit-agent/agent.py` `SYSTEM_PROMPT`.

### 4. STT/TTS Containers Recreated on Agent Rebuild

**Problem:** If the agent has `depends_on: [stt, tts]`, Docker recreates STT/TTS on every agent rebuild. These take 10+ minutes to start (Rust compilation + model download).

**Fix:** Remove `depends_on` from the agent service. Start STT/TTS separately and use `docker compose build livekit-agent && docker compose up -d --no-deps --force-recreate livekit-agent` to rebuild only the agent.

### 5. Port Conflicts with Docker Desktop

**Problem:** Docker Desktop occupies ports 80, 8080, 3001 on Windows.

**Fix:** Use alternative ports: 9090/9443 for original demo, 3333/3443 for LiveKit demo.

### 6. LiveKit Server Port 7882 Conflict

**Problem:** If a previous LiveKit server process didn't shut down cleanly, port 7882 (UDP) remains bound.

**Fix:** Kill the old process: `taskkill /F /IM livekit-server.exe`, wait a moment, then restart.

### 7. Browser Mic Access Requires HTTPS

**Problem:** Browsers block `getUserMedia()` on non-localhost HTTP pages.

**Fix:** Use self-signed HTTPS certs via nginx. Accept the cert warning in the browser.

### 8. Mixed Content (ws:// from https:// page)

**Problem:** Browsers block non-secure WebSocket (`ws://`) connections from HTTPS pages.

**Fix:** Proxy LiveKit WebSocket through nginx at `/livekit-ws/` path, converting `wss://` to `ws://` internally. Frontend auto-detects URL via `window.location.host`.

### 9. geocode.maps.co Now Requires API Key

**Problem:** The geocoding API at geocode.maps.co started requiring an API key.

**Fix:** Use Open-Meteo's own geocoding API (`geocoding-api.open-meteo.com/v1/search`) which is free and needs no key. Note: it searches by city name, not raw zipcode. For best results, say city names rather than zipcodes.

### 10. LiveKit Agents v1.5 API Changes

**Problem:** Many online examples use older LiveKit agents API (`FunctionContext`, `ai_callable`, `TypeInfo`). These don't exist in v1.5.

**Fix:** Use the v1.5 API:
- `@llm.function_tool` decorator (not `@llm.ai_callable`)
- `tools=[...]` parameter in `AgentSession()` (not `fnc_ctx=`)
- `Agent(instructions=...)` for session start (not `ctx.agent`)
- TTS `ChunkedStream` with `AudioEmitter.initialize(request_id, sample_rate, num_channels, mime_type)` + `push(bytes)` + `flush()`
- STT `SpeechStream._run()` with `self._input_ch` for audio frames and `self._event_ch.send_nowait()` for events

### 11. docker compose restart vs recreate for Env Var Changes

**Problem:** `docker compose restart` does NOT pick up environment variable changes in `docker-compose.yml`.

**Fix:** Use `docker compose up -d --force-recreate <service>` to apply new env vars.

### 12. GPU Processes Holding VRAM

**Problem:** Previous GPU processes (Ollama, moshi server) hold VRAM.

**Fix:** Check with `nvidia-smi`, kill processes by PID: `taskkill /PID <pid> /F`

## Weather Function Calling Flow

1. User says: "What's the weather in Beverly Hills?"
2. Kyutai STT transcribes speech to text
3. LLM (Qwen 3 4B via LM Studio) receives text with tool definitions
4. LLM calls `get_weather(zipcode="Beverly Hills")`
5. Agent geocodes via Open-Meteo: Beverly Hills -> lat 34.07, lon -118.40
6. Agent fetches weather from Open-Meteo API (free, no key)
7. Returns: "72 degrees, partly cloudy, humidity 45%, wind 8 mph"
8. LLM generates spoken response incorporating the data
9. Kyutai TTS converts response to speech
10. Audio streams to browser via LiveKit WebRTC

## Cloudflare Tunnel Setup (Remote Access)

To expose the LiveKit MCP demo externally via a Cloudflare tunnel (e.g., `moshi.digitalresponsetech.com`), follow these steps.

### The Problem

The nginx config has two listeners:
- **Port 80** (mapped to host port 4333) - plain HTTP, normally redirects to HTTPS
- **Port 443** (mapped to host port 4443) - HTTPS with self-signed cert

Cloudflare tunnels terminate SSL on Cloudflare's edge and forward **plain HTTP** to your origin. If you point the tunnel at port 4443 (HTTPS), Cloudflare sends plain HTTP to an HTTPS port, causing:

```
400 Bad Request - The plain HTTP request was sent to HTTPS port
```

If you point it at port 4443 with HTTPS type, Cloudflare tries to validate the self-signed cert and fails (unless `noTLSVerify` is set, which isn't available in the dashboard).

### Solution

#### Step 1: Update nginx to handle Cloudflare traffic on port 80

The port 80 server block normally just redirects to HTTPS. When behind Cloudflare, requests arrive on port 80 already SSL-terminated. The nginx config at `livekit-frontend-mcp/nginx/nginx.conf` was updated to detect Cloudflare via the `CF-Visitor` header and serve traffic directly instead of redirecting:

```nginx
server {
    listen 80;

    # When behind Cloudflare tunnel, requests arrive on port 80 already
    # SSL-terminated. Detect this via CF-Visitor header and serve directly.
    set $redirect_to_https 1;
    if ($http_cf_visitor ~* '"scheme":"https"') {
        set $redirect_to_https 0;
    }
    if ($redirect_to_https) {
        return 301 https://$host:4443$request_uri;
    }

    location / {
        set $frontend http://livekit-frontend-mcp:3000;
        proxy_pass $frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location /livekit-ws/ {
        set $livekit http://host.docker.internal:7880;
        rewrite ^/livekit-ws/(.*) /$1 break;
        proxy_pass $livekit;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

This way:
- **Direct LAN access** (`https://192.168.1.221:4443`) still works via the port 443 server block with self-signed cert
- **Cloudflare tunnel access** (`https://moshi.digitalresponsetech.com`) works via port 80 with Cloudflare handling SSL

#### Step 2: Configure the Cloudflare tunnel

In the Cloudflare Zero Trust dashboard (**Networks > Tunnels**):

| Setting | Value |
|---------|-------|
| **Subdomain** | `moshi` |
| **Domain** | `digitalresponsetech.com` |
| **Type** | `HTTP` (NOT HTTPS) |
| **URL** | `192.168.1.221:4333` |

**Critical details:**
- **Type must be `HTTP`** - Cloudflare handles SSL termination; your origin receives plain HTTP
- **Port must be `4333`** (maps to container port 80) - NOT `4443` (that's the HTTPS port)
- Do NOT use `https://192.168.1.221:4443` - this sends plain HTTP to an HTTPS port and causes a 400 error

#### Step 3: Restart nginx

```bash
docker compose restart livekit-nginx-mcp
```

#### How Audio Works Through the Tunnel

The audio pipeline has three layers:

1. **UI serving**: Browser -> Cloudflare -> nginx port 80 -> Next.js frontend (works normally)
2. **WebSocket signaling**: Browser -> Cloudflare -> nginx `/livekit-ws/` -> LiveKit server (Cloudflare supports WebSockets by default)
3. **WebRTC media**: Browser <-> LiveKit server directly via UDP (bypasses the tunnel entirely)

The frontend auto-detects the WebSocket URL from `window.location.host`:
```js
return `wss://${window.location.host}/livekit-ws/`;
```

When accessed via `moshi.digitalresponsetech.com`, this becomes `wss://moshi.digitalresponsetech.com/livekit-ws/`, which Cloudflare proxies through the tunnel to nginx.

The actual audio/video streams use WebRTC peer-to-peer connections that are negotiated during signaling but bypass the tunnel for media transport. This means:
- Audio latency is NOT affected by the tunnel
- The tunnel only carries the web UI and WebSocket signaling
- WebRTC may require a TURN server if the remote client is behind strict NAT

### Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `400 Bad Request - plain HTTP sent to HTTPS port` | Tunnel pointing to port 4443 (HTTPS) | Change tunnel URL to `192.168.1.221:4333` with type `HTTP` |
| `502 Bad Gateway` | nginx container not running or unreachable | Check `docker compose ps livekit-nginx-mcp` |
| Audio doesn't connect | WebRTC ICE candidates can't reach LiveKit server | Ensure LiveKit server runs with `--node-ip YOUR_PUBLIC_IP` or set up a TURN server |
| Favicon 404 in tunnel logs | Browser requests `/favicon.ico` which doesn't exist | Harmless; add a favicon to the frontend if desired |

## APIs Used (All Free, No Keys Required)

- **Open-Meteo Weather**: `api.open-meteo.com/v1/forecast`
- **Open-Meteo Geocoding**: `geocoding-api.open-meteo.com/v1/search`
