# LiveKit Builder — External Access Setup Guide

Complete end-to-end setup for running the Unmute LiveKit Builder voice agent accessible externally via `https://moshi.digitalresponsetech.com` using Cloudflare Tunnel + WebRTC through NAT.

## Architecture

```
External Client (mobile/browser)
    │
    ├── HTTPS ──→ Cloudflare Tunnel ──→ proxy:5333 ──→ Next.js:5334 (frontend)
    │                                        └──→ LiveKit:7880 (WebSocket signaling)
    │
    └── WebRTC ──→ Router NAT (99.66.11.228) ──→ Home_Server (192.168.1.221)
                   TCP 7881 (ICE TCP)
                   UDP 7882 (ICE UDP)
                   UDP 3478 (TURN)
                   UDP 30000-30002 (TURN relay)
```

## Prerequisites

- Windows 11 machine (Home_Server at 192.168.1.221)
- Docker Desktop (for Kyutai Moshi STT/TTS GPU containers)
- LM Studio running on port 1234 with `qwen3-4b` model loaded
- Node.js and npm installed
- Python 3.14+ with pip
- Cloudflare account with `digitalresponsetech.com` domain
- AT&T BGW210-700 gateway (router at 192.168.1.254)

## 1. Environment Variables

Create `.env` in project root (already gitignored):

```
HUGGING_FACE_HUB_TOKEN=<your_hf_token>
CF_TURN_TOKEN_ID=<cloudflare_turn_token_id>
CF_TURN_API_TOKEN=<cloudflare_turn_api_token>
```

## 2. Cloudflare Tunnel

The tunnel `drt` runs as a Windows service via `cloudflared.exe` with a token-based config.

### Published Application Routes

Zero Trust Dashboard > Networks > Connectors > `drt` > Published application routes:

| Hostname | Path | Service |
|----------|------|---------|
| `moshi.digitalresponsetech.com` | `*` | `http://192.168.1.221:5333` |

### Cloudflare TURN Server

Dashboard > Media > Realtime > TURN Server:

- App name: `unmute-livekit`
- Free tier: 1TB/month
- Provides: `stun:stun.cloudflare.com:3478`, `turn:turn.cloudflare.com:3478`
- The frontend token API generates short-lived TURN credentials via Cloudflare API

## 3. AT&T Router Configuration (192.168.1.254)

Access code is printed on the side/bottom of the BGW210-700 device.

### Firewall > NAT/Gaming — Port Forwards

| Service | Ports | Protocol | Device |
|---------|-------|----------|--------|
| LiveKit-WebRTC | 7881-7882 | TCP/UDP | Home_Server |
| LiveKit-TURN | 3478 | UDP | Home_Server |

### Firewall > Firewall Advanced — CRITICAL

| Setting | Value | Reason |
|---------|-------|--------|
| **Reflexive ACL** | **OFF** | **CRITICAL — this was the main blocker.** Blocks all unsolicited inbound IPv6 traffic, which kills WebRTC ICE negotiation from external clients. |
| Drop incoming ICMP Echo to LAN | Off | |
| ESP ALG | Off | |
| SIP ALG | On | |

### Firewall > IP Passthrough

- Allocation Mode: Passthrough
- Default Server Internal Address: `192.168.1.221`

## 4. Windows Firewall Rules

Run in elevated PowerShell:

```powershell
netsh advfirewall firewall add rule name="LiveKit HTTP" dir=in action=allow protocol=TCP localport=7880
netsh advfirewall firewall add rule name="LiveKit ICE-TCP" dir=in action=allow protocol=TCP localport=7881
netsh advfirewall firewall add rule name="LiveKit ICE-UDP" dir=in action=allow protocol=UDP localport=7882
netsh advfirewall firewall add rule name="LiveKit TURN-UDP" dir=in action=allow protocol=UDP localport=3478
netsh advfirewall firewall add rule name="LiveKit TURN-Relay" dir=in action=allow protocol=UDP localport=30000-30002
netsh advfirewall firewall add rule name="LiveKit-Frontend" dir=in action=allow protocol=TCP localport=5333
netsh advfirewall firewall add rule name="LiveKit-Frontend-MCP" dir=in action=allow protocol=TCP localport=3000
```

## 5. LiveKit Server Configuration

`livekit-server-config.yaml`:

```yaml
rtc:
  port_range_start: 7882
  port_range_end: 7882
  tcp_port: 7881
  node_ip: 99.66.11.228
  use_ice_lite: false
  stun_servers:
    - stun.cloudflare.com:3478
  interfaces:
    excludes:
      - vEthernet

turn:
  enabled: true
  domain: moshi.digitalresponsetech.com
  udp_port: 3478
```

### Key settings explained

| Setting | Value | Why |
|---------|-------|-----|
| `use_ice_lite` | `false` | Full ICE negotiation discovers external IP via STUN. ICE Lite only advertises local IPs. |
| `node_ip` | `99.66.11.228` | External IP in TURN credentials. Check with `curl https://api.ipify.org`. |
| `stun_servers` | `stun.cloudflare.com:3478` | Cloudflare global STUN for NAT traversal. |
| `interfaces.excludes` | `vEthernet` | Prevents UDP 7882 binding to WSL/Docker virtual adapter `172.27.96.1` instead of `192.168.1.221`. |
| `turn.enabled` | `true` | Built-in TURN relay for clients that can't do direct UDP. |

## 6. Docker Compose — STT/TTS Port Mappings

Added to `docker-compose.yml` (not in original):

```yaml
tts:
  ports:
    - "8089:8080"

stt:
  ports:
    - "8090:8080"
```

## 7. Proxy Server (replaces Docker nginx)

`livekit-frontend-builder/proxy.js`:

- Listens on port **5333** (Cloudflare tunnel target)
- Routes `/livekit-ws/*` → LiveKit at `localhost:7880` (with WebSocket upgrade)
- Routes everything else → Next.js at `localhost:5334`

## 8. Frontend TURN Credential Injection

`livekit-frontend-builder/src/app/api/token/route.ts` generates Cloudflare TURN credentials on each token request and returns them alongside the LiveKit JWT.

`livekit-frontend-builder/src/app/HomeClient.tsx` passes the ICE servers to `LiveKitRoom` via `options.rtcConfig.iceServers`.

## 9. Service Startup Order

### Step 1: Docker STT/TTS

```bash
docker compose up -d stt tts
# Wait for healthy (~5-10 min first run):
docker ps --filter "name=unmute" --format "{{.Names}}: {{.Status}}"
```

### Step 2: LiveKit Server

```bash
./livekit-server.exe --dev --config livekit-server-config.yaml --bind 0.0.0.0
```

Verify UDP binding: `netstat -ano | grep 7882` — must show `192.168.1.221`, NOT `172.27.96.1`.

### Step 3: Builder Agent

```bash
cd livekit-agent-builder
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

### Step 4: Builder Frontend + Proxy

```bash
# Terminal 1: Next.js
cd livekit-frontend-builder
CF_TURN_TOKEN_ID=<id> CF_TURN_API_TOKEN=<token> npx next dev -p 5334

# Terminal 2: Proxy
cd livekit-frontend-builder
node proxy.js
```

### Step 5: MCP Frontend (optional)

```bash
cd livekit-frontend-mcp && npx next dev -p 3000
```

## 10. Port Reference

| Port | Protocol | Service | Notes |
|------|----------|---------|-------|
| 1234 | TCP | LM Studio (Qwen 3 4B) | Must be running before agent |
| 3000 | TCP | MCP Frontend | Optional |
| 3478 | UDP | LiveKit TURN | Router port forwarded |
| 5333 | TCP | Builder Proxy | Cloudflare tunnel target |
| 5334 | TCP | Builder Frontend | Internal only |
| 7880 | TCP | LiveKit signaling | Proxied via 5333 |
| 7881 | TCP | LiveKit ICE TCP | Router port forwarded |
| 7882 | UDP | LiveKit ICE UDP | Router port forwarded |
| 8089 | TCP | Kyutai TTS (Docker) | Container port 8080 |
| 8090 | TCP | Kyutai STT (Docker) | Container port 8080 |
| 30000-30002 | UDP | TURN relay range | |

**Never change these ports — Cloudflare Tunnel and router forwards depend on them.**

## 11. Troubleshooting

### External clients can't connect (WebRTC ICE fails)

1. **Check Reflexive ACL is OFF** — `Firewall > Firewall Advanced`. This is the #1 cause.
2. Verify UDP 7882 bound to `192.168.1.221` not `172.27.96.1`: `netstat -ano | grep 7882`
3. Verify router port forwards: `Firewall > NAT/Gaming`
4. Verify Windows Firewall: `netsh advfirewall firewall show rule name=all dir=in | grep LiveKit`
5. Check external IP: `curl https://api.ipify.org` — update `node_ip` in config if changed

### STT/TTS containers fail

1. Docker Desktop running? `docker ps`
2. `HUGGING_FACE_HUB_TOKEN` set in `.env`?
3. First run: ~5-10 min (Rust compile + model download)
4. Check: `docker ps --filter "name=unmute"` — wait for `(healthy)`

### Agent says "no worker available"

1. LiveKit server must be running first
2. Check `worker registered` in LiveKit logs
3. STT/TTS healthy on 8090/8089?
4. LM Studio running on 1234?

### Works locally, not externally

- **Reflexive ACL** or **port forwarding** issue (see #1 above)
- Cloudflare Tunnel only handles HTTP/WebSocket signaling
- WebRTC audio requires direct UDP/TCP through the router

### What was tried and didn't work (for reference)

- **Cloudflare Tunnel TCP route** — tunnels only proxy HTTP/WS, not raw TCP/UDP for WebRTC
- **Cloudflare TURN as external ICE servers** — helps client side but LiveKit server still needs reachable ports
- **ICE Lite mode** — only advertises local IPs, external clients can't reach them
- **UPnP port forwarding** — disabled on AT&T gateway
- **IP Passthrough to Home_Server** — didn't help; Reflexive ACL was the actual blocker
