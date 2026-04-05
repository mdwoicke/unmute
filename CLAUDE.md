# CLAUDE.md — Unmute

## Deployment

- This app is served behind **Cloudflare Tunnel**. Port numbers are fixed in the Cloudflare config and **must not be changed**.
- `livekit-frontend-mcp` must run on **port 3000**.
- `livekit-frontend-builder` must run on **port 5333**.
- Never let Next.js auto-increment to another port — kill conflicting processes first.
- When starting dev servers, always specify the port explicitly (e.g. `-p 3000`, `-p 5333`) and ensure the port is free before starting.

## Dockerless Startup (without Docker Desktop)

When Docker is not running, start services manually in this order:

1. **LiveKit server** (port 7880): `./livekit-server.exe --dev --config livekit-server-config.yaml --bind 0.0.0.0`
2. **STT/TTS** (Docker): `docker compose up -d stt tts` (requires Docker Desktop + `HUGGING_FACE_HUB_TOKEN` in `.env`)
3. **Builder agent**: `LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret LM_STUDIO_URL=http://localhost:1234/v1 LM_STUDIO_MODEL=qwen3-4b LLM_MODEL=qwen3-4b KYUTAI_STT_URL=ws://localhost:8090 KYUTAI_TTS_URL=ws://localhost:8089 IVA_SOURCE_PATH=D:/Applications/dynamic-skills-agent PYTHONPATH=D:/Applications/dynamic-skills-agent TTS_GAIN=1.5 python agent.py dev` (from `livekit-agent-builder/`)
3. **Builder frontend** (port 5333): `npx next dev -p 5333` (from `livekit-frontend-builder/`)
4. **MCP frontend** (port 3000): `npx next dev -p 3000` (from `livekit-frontend-mcp/`)

## Utterance Analyzer A/B Test

The `UTTERANCE_ANALYZER` env var controls how caller utterances are preprocessed before reaching the IVA graph:

- `hybrid` (default): Fast regex for trivials (yes/no, pure numbers), Pydantic-structured LLM call for complex utterances (dates, questions, addresses)
- `pydantic`: Full LLM analysis for every utterance — best accuracy, ~200-400ms added per turn
- `legacy`: Original regex preprocessing — zero added latency, but misses edge cases like "next wednesday", "this coming Friday"

Add to the builder agent startup command:
```
UTTERANCE_ANALYZER=hybrid python agent.py dev
```
