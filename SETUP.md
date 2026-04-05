# Unmute - Local Setup Guide

Unmute makes text LLMs listen and speak by combining Speech-to-Text (STT), a text LLM, and Text-to-Speech (TTS). This guide covers running the full stack locally on Windows with Docker and LM Studio.

## Architecture

```
Browser --> nginx (ports 9090/9443) --> Frontend (Next.js :3000)
                                    --> Backend (FastAPI :80)
                                          |-> STT (moshi-server :8080) [GPU]
                                          |-> TTS (moshi-server :8080) [GPU]
                                          |-> LLM (LM Studio :1234)   [GPU]
```

Everything runs 100% locally. No data leaves your machine.

## Prerequisites

- **GPU**: NVIDIA with 16GB+ VRAM (tested on RTX 3090 24GB)
- **OS**: Windows 11 with WSL2
- **Docker Desktop**: Installed with WSL2 backend and NVIDIA Container Toolkit
- **LM Studio**: Installed (https://lmstudio.ai)
- **HuggingFace Account**: With a read-only access token (https://huggingface.co/settings/tokens)

## Models Used

| Component | Model | Params | VRAM | Source |
|-----------|-------|--------|------|--------|
| LLM | `qwen/qwen3-4b` | 4B | ~3GB | LM Studio (local GGUF) |
| STT | `kyutai/stt-1b-en_fr-candle` | 1B | ~2.5GB | HuggingFace (auto-downloaded) |
| TTS | `kyutai/tts-1.6b-en_fr` | 1.6B | ~5.3GB | HuggingFace (auto-downloaded) |
| TTS Voices | `kyutai/tts-voices` | 901 files | minimal | HuggingFace (auto-downloaded) |

Total VRAM: ~11GB

## Step 1: Clone the Repository

```bash
git clone https://github.com/kyutai-labs/unmute.git
cd unmute
```

## Step 2: Set HuggingFace Token

The STT and TTS models auto-download from HuggingFace and require authentication.

```bash
export HUGGING_FACE_HUB_TOKEN=hf_your_token_here
```

## Step 3: Set Up LM Studio

1. Open LM Studio
2. Go to **Discover** tab, search for `qwen3-4b`
3. Download a GGUF quantized version (Q4_K_M recommended)
4. Load the model
5. Go to **Developer** tab and **Start Server** (serves on `http://localhost:1234`)
6. Verify it's running:
   ```bash
   curl http://localhost:1234/v1/models
   ```

### LM Studio Optimal Settings

- **GPU Offload**: All layers on GPU for fastest inference
- **Context Length**: 2048-4096 (lower = faster, sufficient for voice conversations)
- **Flash Attention**: ON (if available)

### Important: Thinking Models

If using Qwen 3.x models, the system prompt includes `/no_think` to disable the reasoning/thinking phase. Without this, the model spends several seconds "thinking" before producing text, which causes the STT voice activity detection to interrupt the response.

This is configured in `unmute/llm/system_prompt.py` at the top of `_SYSTEM_PROMPT_TEMPLATE`.

Non-thinking models (Phi-4, Llama 3, Dolphin, etc.) do not need this.

## Step 4: Configure docker-compose.yml

The `docker-compose.yml` has been modified to:

1. **Replace Traefik with nginx** (Traefik's Docker socket doesn't work well on Docker Desktop for Windows)
2. **Replace the vLLM container with LM Studio** running on the host
3. **Use port 9090/9443** instead of 80 (which Docker Desktop uses)

Key environment variables in the `backend` service:

```yaml
environment:
  - KYUTAI_STT_URL=ws://stt:8080
  - KYUTAI_TTS_URL=ws://tts:8080
  - KYUTAI_LLM_URL=http://host.docker.internal:1234    # LM Studio on host
  - KYUTAI_LLM_MODEL=qwen/qwen3-4b                     # Must match LM Studio model ID
```

To change the LLM model, update `KYUTAI_LLM_MODEL` and **recreate** the backend container:

```bash
docker compose up -d --force-recreate backend
```

Note: A simple `restart` does NOT pick up environment variable changes.

## Step 5: Build and Start

```bash
export HUGGING_FACE_HUB_TOKEN=hf_your_token_here
docker compose up --build
```

Or run in detached mode:

```bash
docker compose up --build -d
```

### First Run Notes

- The **moshi-server** (STT/TTS) compiles Rust with CUDA support on first build. This takes 10-20 minutes.
- STT/TTS models are auto-downloaded from HuggingFace on first startup.
- Subsequent starts are fast since build artifacts and models are cached in Docker volumes.

### Monitoring Progress

```bash
# Check all container status
docker compose ps

# Watch STT/TTS compilation progress
docker compose logs -f stt
docker compose logs -f tts

# Check backend logs
docker compose logs -f backend
```

All services should show as `(healthy)` when ready.

## Step 6: Access the App

- **Local (this machine)**: https://localhost:9443
- **Local network**: https://192.168.1.221:9443 (replace with your IP)
- **HTTP fallback**: http://localhost:9090 (auto-redirects to HTTPS)

Your browser will warn about the self-signed certificate. Click **Advanced > Proceed** to accept it.

HTTPS is required for microphone access on non-localhost URLs.

## Step 7: Windows Firewall (for network access)

To allow other devices on your local network to access the app, add firewall rules (run in admin terminal):

```
netsh advfirewall firewall add rule name="Unmute Web UI" dir=in action=allow protocol=TCP localport=9090
netsh advfirewall firewall add rule name="Unmute HTTPS" dir=in action=allow protocol=TCP localport=9443
```

## Stopping the App

```bash
docker compose down
```

To also remove cached volumes (models will need to re-download):

```bash
docker compose down -v
```

## Troubleshooting

### "Couldn't connect" on the web page
- Check all containers are healthy: `docker compose ps`
- STT/TTS may still be compiling (check `docker compose logs stt`)

### No audio response (0 words from LLM)
- Verify the correct model is loaded in LM Studio: `curl http://localhost:1234/v1/models`
- Verify the container has the right env var: `docker compose exec backend env | grep KYUTAI_LLM`
- If they don't match, recreate: `docker compose up -d --force-recreate backend`
- If using a thinking model (Qwen 3.x/3.5), ensure `/no_think` is in the system prompt

### Microphone not working
- HTTPS is required for mic access on non-localhost URLs
- Use `https://localhost:9443` or accept the self-signed cert warning
- Check browser mic permissions (lock icon in URL bar)

### Port 80/8080 already in use
- Docker Desktop uses these ports. The app is configured to use 9090 (HTTP) and 9443 (HTTPS)

### Slow LLM response
- Use a non-thinking model or ensure `/no_think` is in the system prompt
- In LM Studio: maximize GPU offload layers, enable flash attention, reduce context length to 2048-4096
- The STT's voice activity detection will interrupt LLM responses that take too long to start

## File Structure (Key Files)

```
unmute/
  docker-compose.yml              # Main orchestration (modified for LM Studio + nginx)
  unmute/llm/system_prompt.py     # System prompt with /no_think for thinking models
  unmute/llm/llm_utils.py         # LLM streaming client
  unmute/kyutai_constants.py      # Environment variable configuration
  services/nginx/nginx.conf       # Reverse proxy config (replaces Traefik)
  services/nginx/certs/           # Self-signed SSL certificates
  services/moshi-server/          # STT/TTS Dockerfile and configs
  frontend/                       # Next.js frontend
  voices.yaml                     # Voice configurations
```
