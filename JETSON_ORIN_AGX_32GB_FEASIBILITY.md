# Unmute on NVIDIA Jetson Orin AGX 32GB - Feasibility Study

## Executive Summary

Running the Unmute voice-chat application as-is on the Jetson Orin AGX 32GB is **not possible** due to hard x86_64 architecture requirements in the Rust-based moshi-server (STT/TTS) and vLLM (LLM). However, research uncovered **two viable paths forward**:

1. **Path A (Native Moshi via PyTorch):** Kyutai publishes a pure-Python `moshi` package (`pip install moshi`) with a built-in server (`python -m moshi.server`) that is platform-independent. The critical `rustymimi` audio codec dependency **ships prebuilt aarch64 Linux wheels**. This path preserves the original Moshi models but requires ~24 GB for the full 7B Moshi model in bf16 -- extremely tight on 32 GB shared memory.

2. **Path B (Alternative STT/TTS/LLM stack):** Replace moshi with Jetson-native alternatives (whisper.cpp + Piper/Riva TTS + Ollama). Uses only ~8 GB, leaving ample headroom. Requires writing WebSocket adapter services but uses battle-tested Jetson components.

This document covers both paths, the blockers, memory budgets, expected latency, and implementation roadmaps.

---

## 1. Jetson Orin AGX 32GB Hardware Specs

| Spec | Value |
|------|-------|
| GPU | NVIDIA Ampere, 1792 CUDA cores, 56 Tensor Cores (3rd gen) |
| GPU Compute | SM 8.7 (sm_87) |
| AI Performance | Up to 200 TOPS (INT8, with DLA) |
| Memory | 32 GB LPDDR5, **shared** CPU/GPU (unified DRAM) |
| Memory Bandwidth | 204.8 GB/s |
| CPU | 8-core Arm Cortex-A78AE @ 2.2 GHz |
| DLA | 2x NVDLA v2.0 engines |
| Power | Configurable: 15W / 30W / 60W (MAXN) |
| Software | JetPack 6.2, CUDA 12.6, cuDNN 9.x, TensorRT 10.x |

**Key constraint:** The 32 GB is shared between the OS, CPU workloads, and GPU workloads. Expect ~28 GB usable after OS/runtime overhead (~3-4 GB).

---

## 2. Blockers for Running Unmute As-Is

### 2.1 Architecture: x86_64 Only

The moshi-server (Rust binary handling STT and TTS) is built exclusively for x86_64. From the README:

> *"Architecture must be x86_64, no aarch64 support is planned."*

- Docker images use `nvidia/cuda:12.8.1-devel-ubuntu22.04` (x86_64)
- The Candle ML framework (used by moshi) supports aarch64 in principle, but moshi-server has no ARM build targets, no CI for ARM, and CUDA kernel architectures are untested on sm_87
- Recompiling moshi-server for Jetson would require patching Candle's CUDA kernels for sm_87, resolving `cudarc` version mismatches with JetPack's CUDA 12.6, and fixing any aarch64-specific compilation issues. Estimate: **weeks of work** with uncertain outcome

### 2.2 vLLM Does Not Support Jetson

The LLM service uses `vllm/vllm-openai:v0.11.0`, which is x86_64-only and does not build on aarch64/Jetson. A replacement LLM runtime is required.

### 2.3 Shared Memory Pressure

Unmute's default configuration uses ~14 GB of VRAM across three models:

| Service | VRAM (x86) | Notes |
|---------|-----------|-------|
| STT (kyutai/stt-1b) | 2.5 GB | 1B parameter model, fp32 |
| TTS (kyutai/tts-1.6b) | 5.3 GB | 1.6B parameter model, fp32 |
| LLM (Gemma 3 1B) | 6.1 GB | bfloat16 via vLLM |
| **Total** | **13.9 GB** | |

On Jetson's shared 32 GB, this leaves only ~14 GB for the OS, Python runtime, Node.js frontend, and any buffering. It would be marginal even without the architecture blocker.

### 2.4 Inference Speed Gap

The Jetson Orin AGX 32GB GPU (1792 CUDA cores @ 930 MHz) is roughly **5-10x slower** than a desktop RTX 4090 (16,384 cores @ 2.52 GHz). Unmute's real-time latency targets (450-750ms TTS) would be difficult to meet with the original models.

---

## 3. Path A: Running Native Moshi on Jetson via PyTorch

### 3.1 Discovery: Pure Python Moshi Server Exists

Kyutai publishes a **separate Python/PyTorch implementation** of Moshi that does NOT require the Rust moshi-server binary:

```bash
pip install moshi          # Pure Python wheel (py3-none-any) -- works on ANY platform
python -m moshi.server     # Runs a standalone PyTorch-based Moshi server
```

**Key facts:**
- Package: `moshi` v0.2.13 on PyPI
- Wheel type: `py3-none-any` (pure Python, platform-independent)
- Python requirement: 3.10-3.14
- PyTorch requirement: 2.2-2.10
- The unmute codebase already has this package cached in `volumes/uv-cache/` and references it in `dockerless/start_tts.sh`

### 3.2 The rustymimi Audio Codec: aarch64 Ready

The critical dependency `rustymimi` (Kyutai's Mimi audio codec, written in Rust) **ships prebuilt aarch64 Linux wheels on PyPI**:

```
rustymimi-0.4.1-cp3XX-cp3XX-manylinux_2_17_aarch64.manylinux2014_aarch64.whl  (28.3 MB)
rustymimi-0.4.1-cp3XX-cp3XX-musllinux_1_2_aarch64.whl  (27.8 MB)
```

This means `pip install moshi` on a Jetson aarch64 device should resolve all dependencies including the native Mimi codec **without needing to compile any Rust code**.

### 3.3 Memory Problem: 32 GB Is Extremely Tight

The PyTorch Moshi server runs the **full 7B parameter Moshi model** (not the separate STT-1B + TTS-1.6B that unmute uses). Memory requirements:

| Component | Memory |
|-----------|--------|
| Moshi 7B model (bf16) | ~14 GB (weights only) |
| KV cache + activations | ~6-10 GB |
| PyTorch CUDA runtime | ~2 GB |
| OS + system overhead | ~3-4 GB |
| **Total** | **~25-30 GB** |
| **Available** | **32 GB** |

This is **borderline**. The 64 GB Orin AGX would be comfortable. On 32 GB:
- No headroom for a separate LLM (Moshi IS the LLM in this mode -- it's multimodal speech+text)
- No room for additional services (monitoring, etc.)
- Risk of OOM under sustained load
- **No quantization support** in PyTorch mode (int8 is "experimental" per Kyutai)

### 3.4 Moshi PyTorch vs. Unmute Architecture: Different Models

**Important distinction:** The Python `moshi.server` runs Moshi as a **unified multimodal model** (speech-in, speech-out, with text reasoning built in). This is fundamentally different from Unmute's architecture:

| Aspect | Unmute (current) | Moshi PyTorch Server |
|--------|-----------------|---------------------|
| Architecture | STT + LLM + TTS (3 separate models) | Single multimodal model |
| STT model | kyutai/stt-1b (1B params) | Built into Moshi 7B |
| LLM | Gemma 3 / any OpenAI-compatible | Built into Moshi 7B |
| TTS model | kyutai/tts-1.6b (1.6B params) | Built into Moshi 7B |
| Total params | ~3.6B + LLM | 7B (all-in-one) |
| Customizable LLM | Yes (swap any model) | No (fixed to Moshi) |
| Voice cloning | Yes (70+ voices) | Limited |
| Streaming | Word-by-word STT, chunked TTS | Full-duplex real-time |

Running `python -m moshi.server` would give you a **different product** than Unmute -- it's Moshi's native full-duplex voice assistant, not Unmute's "wrap any text LLM with voice" architecture.

### 3.5 Path A Verdict

| Criterion | Assessment |
|-----------|-----------|
| Will `pip install moshi` work on Jetson? | **Very likely yes** (pure Python + aarch64 rustymimi wheel) |
| Will `python -m moshi.server` run? | **Uncertain** -- needs PyTorch+CUDA on Jetson (officially supported) but nobody has confirmed this end-to-end |
| Will it fit in 32 GB? | **Extremely tight** -- may OOM under load |
| Does it replicate Unmute? | **No** -- it's a different architecture (unified model vs. STT+LLM+TTS pipeline) |
| Can Unmute's backend use it? | **No** -- different WebSocket protocol, different capabilities |
| Is it worth trying? | **Yes, as a quick experiment** -- could work in ~1 day of setup |

### 3.6 Path A: Quick-Start Experiment

If you want to try this before committing to a full port:

```bash
# On Jetson Orin AGX 32GB with JetPack 6.2

# 1. Install PyTorch for Jetson (NVIDIA's official wheel)
pip install torch torchvision torchaudio --index-url https://developer.download.nvidia.com/compute/redist/jp/v61

# 2. Install Moshi
pip install moshi

# 3. Run the server (will download ~14GB model on first run)
python -m moshi.server --host 0.0.0.0 --port 8998

# 4. Open browser to http://<jetson-ip>:8998
# Moshi's built-in web client should load
```

**Expected outcome:** Either it runs (proving Jetson viability) or it OOMs during model loading (confirming 32 GB is insufficient for the full Moshi 7B). This test takes minimal effort and gives a definitive answer.

### 3.7 Community Status

- **One unanswered NVIDIA forum thread** (April 28, 2025): A user asked about running Moshi on Jetson AGX Orin. NVIDIA staff had no direct experience. Thread closed with no resolution.
- **No confirmed success reports** of Moshi (PyTorch or Rust) running on any Jetson device.
- **No ONNX or TensorRT exports** of Moshi exist. No community ports to edge-optimized formats.
- The Moshi GitHub repo (`kyutai-labs/moshi`) has **zero issues** related to ARM or Jetson.

---

## 4. Path B: Why Swapping Services Is Feasible

The good news: Unmute's backend is **loosely coupled** to its ML services.

### 3.1 Service Architecture

```
Browser <--WebSocket--> Backend (FastAPI) <--WebSocket--> STT Server
                                          <--WebSocket--> TTS Server
                                          <--HTTP/REST--> LLM Server
```

- STT and TTS communicate via **MessagePack over WebSocket**
- LLM uses **OpenAI-compatible HTTP API** (`/v1/chat/completions`)
- Service URLs are configurable via environment variables:
  - `KYUTAI_STT_URL` (default: `ws://localhost:8090`)
  - `KYUTAI_TTS_URL` (default: `ws://localhost:8089`)
  - `KYUTAI_LLM_URL` (default: `http://localhost:8091`)

### 3.2 WebSocket Protocol (STT)

Endpoint: `/api/asr-streaming`

| Direction | Message Type | Payload |
|-----------|-------------|---------|
| Client -> Server | `Audio` | `{"type": "Audio", "pcm": [float32_array]}` (1920 samples, 80ms) |
| Client -> Server | `Marker` | `{"type": "Marker", "id": int}` |
| Server -> Client | `Ready` | `{"type": "Ready"}` |
| Server -> Client | `Word` | `{"type": "Word", "text": str}` |
| Server -> Client | `EndWord` | `{"type": "EndWord", "stop_time": float}` |
| Server -> Client | `Step` | `{"type": "Step", "step_idx": int, "prs": [float, float, float]}` |

**VAD (Voice Activity Detection):** Uses `prs[2]` (pause probability) from `Step` messages with an EMA filter. A replacement STT would need to provide equivalent end-of-speech signaling.

### 3.3 WebSocket Protocol (TTS)

Endpoint: `/api/tts_streaming?format=PcmMessagePack&voice=<id>&cfg_alpha=<value>`

| Direction | Message Type | Payload |
|-----------|-------------|---------|
| Client -> Server | `Text` | `{"type": "Text", "text": str}` |
| Client -> Server | `Voice` | `{"type": "Voice", "embeddings": [float], "shape": [int]}` |
| Client -> Server | `Eos` | `{"type": "Eos"}` |
| Server -> Client | `Ready` | `{"type": "Ready"}` |
| Server -> Client | `Audio` | `{"type": "Audio", "pcm": [float32_array]}` |

### 3.4 Swap Strategy

A Jetson-compatible STT/TTS engine needs only to:
1. Expose the same WebSocket endpoints
2. Use MessagePack serialization
3. Implement the same message types
4. Send a `Ready` message on connection

Alternatively, modify the Python client classes (`unmute/stt/speech_to_text.py`, `unmute/tts/text_to_speech.py`) to speak a different protocol. These are ~200-300 lines each and well-structured.

---

## 5. Path B: Jetson-Compatible Alternatives

### 4.1 STT Options

| Engine | Type | Memory | Latency (10s audio) | Quality | Jetson Support |
|--------|------|--------|---------------------|---------|----------------|
| **NVIDIA Riva ASR** | Conformer/TensorRT | ~2-3 GB | 100-300ms (streaming) | Excellent | Native (NGC containers) |
| **whisper.cpp (small)** | Whisper via GGML | ~1 GB | 500ms-1.5s | Very good | Yes (CUDA sm_87) |
| **whisper.cpp (base)** | Whisper via GGML | ~500 MB | 200-500ms | Good | Yes (CUDA sm_87) |
| **Faster-Whisper (small)** | CTranslate2 | ~1-2 GB | 500ms-1s | Very good | Build from source |

**Recommendation: NVIDIA Riva ASR** for lowest latency and native Jetson support. Falls back to **whisper.cpp (small)** if Riva licensing is not available.

Riva provides streaming ASR with chunked processing, closely matching Unmute's frame-by-frame audio pipeline. Time-to-first-word is 100-300ms, which is faster than Unmute's current 500ms `STT_DELAY_SEC`.

### 4.2 TTS Options

| Engine | Type | Memory | Time-to-First-Audio | Quality | Jetson Support |
|--------|------|--------|---------------------|---------|----------------|
| **NVIDIA Riva TTS** | FastPitch + HiFi-GAN / TensorRT | ~1-2 GB | 100-200ms | Very good | Native (NGC containers) |
| **Piper TTS** | VITS / ONNX | ~15-80 MB | 50-100ms | Good | Yes (CPU-only, no GPU needed) |
| **Kokoro TTS** | Transformer | ~300 MB-1 GB | 100-400ms | Good | Yes (PyTorch/ONNX) |
| **XTTS v2** | Transformer / PyTorch | ~4-6 GB | 500ms-1.5s | Excellent (voice cloning) | Yes (CUDA) |

**Recommendation: Piper TTS** for the best latency-to-memory ratio. At 50-100ms time-to-first-audio on CPU alone, it frees the GPU entirely for STT and LLM. If voice cloning (a key Unmute feature) is required, use **Kokoro** or accept higher latency with **XTTS v2**.

**Alternative: NVIDIA Riva TTS** if using the Riva stack for both STT and TTS (simplifies deployment, single NGC pull).

### 4.3 LLM Options

| Runtime | Model | Quantization | Memory | Tokens/sec | Jetson Support |
|---------|-------|-------------|--------|------------|----------------|
| **llama.cpp** | Llama 3.2 3B | Q4_K_M | ~2.5 GB | 20-35 tok/s | Yes (CUDA sm_87) |
| **llama.cpp** | Gemma 2 2B | Q4_K_M | ~1.5 GB | 30-45 tok/s | Yes |
| **llama.cpp** | Phi-3.5 Mini 3.8B | Q4_K_M | ~2.5 GB | 18-30 tok/s | Yes |
| **Ollama** | Llama 3.2 3B | Q4_K_M | ~2.5 GB | 15-25 tok/s | Yes (aarch64 builds) |
| **TensorRT-LLM** | Llama 3.2 3B | INT4 AWQ | ~2-3 GB | 25-40 tok/s | Yes (JetPack 6.x) |

**Recommendation: Ollama** with **Llama 3.2 3B Q4** for easiest setup (drop-in OpenAI-compatible API at `http://localhost:11434/v1/chat/completions`). The backend's OpenAI SDK client works without modification - just change the URL and model name.

For maximum performance, **TensorRT-LLM** provides the highest throughput but requires a model compilation step.

---

## 6. Path B: Recommended Jetson Architecture

### 5.1 Optimal Stack

```
┌──────────────────────────────────────────────┐
│           Frontend (Next.js)                  │
│          Port 3000 (unchanged)                │
└─────────────────┬────────────────────────────┘
                  │ WebSocket
                  v
┌──────────────────────────────────────────────┐
│        Backend (FastAPI + uvicorn)            │
│         Port 8000 (unchanged)                 │
│   Modified STT/TTS clients for new protocols  │
└────┬──────────────┬──────────────┬───────────┘
     │              │              │
     v              v              v
┌─────────┐  ┌───────────┐  ┌──────────────┐
│ Whisper  │  │ Piper TTS │  │   Ollama     │
│ .cpp     │  │  (CPU)    │  │ Llama 3.2 3B │
│ (GPU)    │  │           │  │   (GPU)      │
│ ~1 GB    │  │ ~50 MB    │  │  ~2.5 GB     │
└─────────┘  └───────────┘  └──────────────┘
```

### 5.2 Memory Budget

| Component | Memory (GPU) | Memory (CPU) |
|-----------|-------------|-------------|
| JetPack OS + CUDA runtime | - | 3-4 GB |
| whisper.cpp (small, CUDA) | ~1 GB | ~200 MB |
| Piper TTS (CPU-only) | 0 | ~100 MB |
| Ollama + Llama 3.2 3B Q4 | ~2.5 GB | ~500 MB |
| Backend (Python/FastAPI) | - | ~500 MB |
| Frontend (Next.js) | - | ~200 MB |
| **Total** | **~3.5 GB** | **~4.5 GB** |
| **Combined** | | **~8 GB** |
| **Remaining (of 32 GB)** | | **~24 GB headroom** |

This leaves substantial headroom for:
- Upgrading to a 7B LLM (~4 GB Q4) if quality demands it
- Adding XTTS v2 (~4-6 GB) for voice cloning
- Running monitoring/metrics services
- Handling memory spikes during inference

### 5.3 Alternative: Full Riva Stack

If NVIDIA Riva licensing is acceptable:

| Component | Memory |
|-----------|--------|
| Riva ASR (Conformer) | ~2-3 GB |
| Riva TTS (FastPitch + HiFi-GAN) | ~1-2 GB |
| Ollama + Llama 3.2 3B Q4 | ~2.5 GB |
| System overhead | ~4 GB |
| **Total** | **~10-12 GB** |

Riva provides the lowest latency STT/TTS and is purpose-built for Jetson. Downside: fewer voice options than Piper and no voice cloning out-of-the-box.

---

## 7. Expected End-to-End Latency

### 6.1 Latency Breakdown (Recommended Stack)

| Stage | Estimated Latency | Notes |
|-------|------------------|-------|
| Audio capture + WebSocket | ~20-50ms | Browser to backend |
| STT (whisper.cpp small) | ~500ms-1s | For a 2-3 second utterance |
| End-of-speech detection | ~300-500ms | Pause detection EMA |
| LLM generation (first token) | ~100-200ms | Llama 3.2 3B prompt processing |
| LLM generation (full response) | ~500ms-1.5s | 20-35 tok/s, ~30 token response |
| TTS (Piper, first audio) | ~50-100ms | CPU inference, very fast |
| TTS (streaming) | real-time | Streams as generated |
| **Total voice-in to voice-out** | **~1.5-3.5 seconds** | |

### 6.2 Comparison to Original Unmute

| Metric | Unmute (x86, single GPU) | Jetson (recommended) | Jetson (Riva) |
|--------|-------------------------|---------------------|---------------|
| STT latency | ~500ms (streaming) | ~500ms-1s (batch) | ~100-300ms (streaming) |
| TTS time-to-first-audio | ~750ms | ~50-100ms | ~100-200ms |
| LLM tokens/sec | ~50-100+ | ~20-35 | ~20-35 |
| End-to-end | ~1.5-2.5s | ~1.5-3.5s | ~1-2.5s |
| Concurrent users | 4+ | **1 only** | **1 only** |

The Riva stack on Jetson could actually match or beat the original single-GPU setup's latency, despite the weaker hardware, thanks to TensorRT optimization.

---

## 8. Implementation Roadmap

### Phase 1: Core Port (1-2 weeks)

1. **Set up JetPack 6.2** on Orin AGX 32GB (CUDA 12.6, TensorRT 10.x)
2. **Install Ollama** (aarch64 build) and pull `llama3.2:3b`
3. **Build whisper.cpp** with CUDA for sm_87
4. **Install Piper TTS** (pre-built aarch64 wheel or build from source)
5. **Write adapter services** - thin WebSocket wrappers around whisper.cpp and Piper that speak the moshi protocol (or modify the Python clients)
6. **Deploy the Python backend** (FastAPI) - this is architecture-agnostic and should work with minimal changes

### Phase 2: Integration (1 week)

7. Modify `KYUTAI_STT_URL`, `KYUTAI_TTS_URL`, `KYUTAI_LLM_URL` to point to new services
8. Adapt STT client to handle Whisper's batch (non-streaming) output vs. moshi's word-by-word streaming
9. Adapt TTS client for Piper's output format
10. Test end-to-end voice pipeline

### Phase 3: Optimization (1-2 weeks)

11. Profile memory usage across the full pipeline
12. Tune whisper.cpp parameters (beam size, model size) for latency vs accuracy
13. Consider TensorRT-LLM if Ollama throughput is insufficient
14. Evaluate Riva as a drop-in for STT/TTS if latency targets aren't met
15. Implement power management (30W vs 60W profiles for thermal management)

### Phase 4: Voice Cloning (optional, 1-2 weeks)

16. If voice cloning is needed, integrate XTTS v2 or Kokoro with voice embedding support
17. Budget additional ~4-6 GB GPU memory (may require dropping LLM to 1B or further quantizing)

---

## 9. Using a 1TB NVMe SSD to Extend Memory

A 1TB NVMe SSD can significantly improve the viability of both paths by acting as extended memory via swap, mmap, and model offloading.

### 9.1 Jetson Orin AGX NVMe Hardware

| Spec | Value |
|------|-------|
| M.2 Slot | Key M, 2280 form factor, NVMe only (no SATA) |
| PCIe Interface | **Gen 4 x4** (theoretical 8 GB/s) |
| Measured sequential read | **~1.9-3.7 GB/s** (Samsung 980 Pro) |
| Measured sequential write | **~300-414 MB/s** (varies by power mode) |
| Random 4K read | ~50-80 MB/s estimated |

**Recommended drives:** Samsung 980 Pro 1TB, WD Black SN770 1TB, or Samsung 990 Pro 1TB. Choose high TBW (endurance) ratings for sustained AI workloads.

### 9.2 NVMe Swap Configuration

Disable the default ZRAM (poor compression on model weights) and create a large NVMe swap:

```bash
# Disable default ZRAM (compresses poorly on float weights)
sudo systemctl disable nvzramconfig
sudo swapoff -a

# Create 128GB swap on NVMe (mounted at /ssd)
# With a 1TB SSD, no reason to be conservative -- use 128GB+
sudo fallocate -l 128G /ssd/128GB.swap
sudo mkswap /ssd/128GB.swap
sudo swapon /ssd/128GB.swap

# Make persistent
echo '/ssd/128GB.swap none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune swappiness for AI workloads (lower = prefer keeping data in RAM)
sudo sysctl vm.swappiness=10
```

This gives you **32 GB RAM + 128 GB NVMe swap = 160 GB virtual memory**. The OS transparently pages cold memory to the SSD. With a 1TB drive, you can go even higher (256 GB, 512 GB) -- the limit is speed, not capacity.

**Critical caveat: swap size vs. swap speed.** Only 32 GB of data can be "hot" in physical RAM at any time. Anything paged out to NVMe costs ~0.5-2ms per page fault to bring back (vs. nanoseconds for RAM). For real-time voice, the goal is to keep all model weights in RAM and use swap only for OS/background overflow:

| Swap Config | Virtual Total | Best For | Inference Impact |
|-------------|--------------|----------|------------------|
| 128 GB | 160 GB | 7B-13B models (fit in RAM, swap catches OS overflow) | None -- models stay in RAM |
| 256 GB | 288 GB | 30B Q4 models (~18 GB weights, partially in RAM) | Moderate -- some layers page |
| 512 GB | 544 GB | 70B Q4 models (~40 GB weights, mostly on SSD) | Severe -- ~1-5 tok/s |

### 9.3 Impact on Path A (PyTorch Moshi 7B)

With 32 GB NVMe swap, Path A becomes **much more viable**:

| Without swap | With 32 GB NVMe swap |
|-------------|---------------------|
| ~25-30 GB needed, 32 GB available | ~25-30 GB needed, 64 GB virtual available |
| OOM risk under load | OOM eliminated |
| No headroom | ~34 GB headroom for spikes |

**Caveat:** If model weights get paged to SSD, inference slows dramatically. The goal is to keep hot weights in RAM and only page out cold/OS data. With 32 GB swap, the OS can page out non-essential processes, filesystem cache, and inactive memory pages, freeing more of the 32 GB physical RAM for the Moshi model.

**Expected behavior:** Moshi 7B (bf16) loads ~14 GB of weights. With KV cache and PyTorch runtime, total reaches ~25 GB. Swap absorbs the remaining OS/system pressure. Inference should work at reduced but usable speed.

### 9.4 Impact on Path B (Alternative Stack)

Path B already fits in ~8 GB, but NVMe swap opens up **larger LLM options**:

| Configuration | Model Memory | Total w/ STT+TTS | Fits in 32 GB? |
|--------------|-------------|-------------------|-----------------|
| Llama 3.2 3B Q4 | ~2.5 GB | ~8 GB | Yes (no swap needed) |
| Mistral 7B Q4 | ~4.5 GB | ~10 GB | Yes (no swap needed) |
| **Llama 3.1 13B Q4** | ~8 GB | ~14 GB | Yes (no swap needed) |
| **Llama 3.1 70B Q4** | ~40 GB | ~46 GB | **Yes with swap** (very slow) |

The sweet spot is **7B-13B Q4 models** which fit entirely in RAM with room to spare. 70B+ models technically load via mmap + swap but are too slow for real-time voice (~1-3 tok/s).

### 9.5 llama.cpp mmap: SSD as Transparent Model Store

llama.cpp uses `mmap()` by default, which makes the NVMe SSD act as transparent extended memory:

```bash
# Model file lives on NVMe at /ssd/models/
# llama.cpp mmaps it -- OS pages in only what's needed
./llama-server -m /ssd/models/mistral-7b-q4.gguf --n-gpu-layers 99

# For models larger than RAM, use --no-mmap for faster initial load:
./llama-server -m /ssd/models/large-model.gguf --no-mmap --n-gpu-layers 99
```

**Performance notes:**
- Models that fit in RAM: mmap loads pages on first access, then runs at full RAM speed. **No performance penalty** once warmed up.
- Models larger than RAM: OS pages cold layers to/from NVMe. Each page fault costs ~0.5-2ms. Inference drops to **~1-5 tok/s** for oversized models.
- Community tip: `--no-mmap` (eager loading) is often faster on Jetson — one user reported **1.5 min vs 8.7 min** load time.

### 9.6 HuggingFace Accelerate Disk Offload (for Path A)

If running Moshi via PyTorch and memory is tight, use Accelerate to offload transformer layers to NVMe:

```python
from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained(
    "kyutai/moshi-7b",
    device_map="auto",           # Auto-distribute across GPU/CPU/disk
    offload_folder="/ssd/offload" # NVMe path for overflow layers
)
```

**How it works:** Weights that don't fit in RAM are saved as memory-mapped numpy arrays on the SSD. During forward pass, each layer's weights are loaded from NVMe before execution.

**Performance cost per layer offloaded to disk:**
- Each Moshi transformer layer: ~440 MB
- NVMe read at 1.9 GB/s: **~230 ms per layer load**
- If 50% of 32 layers are on disk (16 layers): **~3.7 seconds added per token**
- If only 4 layers overflow to disk: **~920 ms added per token**

**Verdict:** Disk offload is a safety net, not a performance solution. Keep as many layers in RAM as possible. The NVMe swap approach (Section 9.2) is generally better because the OS makes smarter paging decisions than explicit layer offloading.

### 9.7 CUDA Unified Memory Oversubscription

On Jetson, CUDA unified memory can oversubscribe physical RAM by paging to NVMe swap:

1. Allocate more than 32 GB via `cudaMallocManaged()`
2. Linux kernel pages cold GPU memory to NVMe swap
3. Page faults bring data back when accessed

This happens **automatically** with NVMe swap enabled — no code changes needed. PyTorch on Jetson uses unified memory by default.

**Caution:** Random access patterns on oversubscribed memory are extremely slow (~100-1000x slower than in-RAM). Sequential patterns (like loading transformer layers in order) are tolerable.

### 9.8 Revised Memory Architecture with 1TB NVMe

```
┌──────────────────────────────────────────────────────────────┐
│                    32 GB LPDDR5 (shared)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐  │
│  │ OS/System│ │ STT Model│ │ TTS Model│ │   LLM Model    │  │
│  │  ~4 GB   │ │  ~1 GB   │ │ ~0.1 GB  │ │  ~2.5-8 GB     │  │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘  │
│                    ~20 GB free headroom                       │
└──────────────────────────┬───────────────────────────────────┘
                           │ overflow (swap)
                           v
┌──────────────────────────────────────────────────────────────┐
│                1 TB NVMe SSD (Gen4 x4)                        │
│  ┌───────────┐ ┌──────────┐ ┌─────────────────────────────┐ │
│  │ 128GB Swap│ │  Model   │ │   Remaining ~500+ GB        │ │
│  │           │ │  Files   │ │   Docker, logs, data         │ │
│  └───────────┘ └──────────┘ └─────────────────────────────┘ │
│              ~1.9-3.7 GB/s read                               │
└──────────────────────────────────────────────────────────────┘
```

### 9.9 Recommended SSD Layout for 1TB Drive

| Partition/Path | Size | Purpose |
|---------------|------|---------|
| `/ssd/swap` | 128 GB | Swap file for memory overflow (can go higher) |
| `/ssd/models` | 200 GB | GGUF/safetensors model storage |
| `/ssd/offload` | 50 GB | HuggingFace Accelerate disk offload cache |
| `/ssd/docker` | 200 GB | Docker data root (move from eMMC) |
| `/ssd/hf-cache` | 100 GB | HuggingFace Hub download cache |
| Remaining | ~322 GB | Logs, recordings, data, future models |

### 9.10 What the SSD Changes for Each Path

**Path A (PyTorch Moshi 7B) — previously "extremely tight":**
- With 32 GB swap: **Now viable**. Model loads into RAM, OS overflow goes to NVMe.
- Expected inference: Slower than desktop but functional for real-time voice.
- Confidence: **Medium** — nobody has tested this exact config yet.

**Path B (whisper.cpp + Piper + Ollama) — previously "comfortable":**
- With NVMe: Can now run **13B LLMs** without any swap pressure, or even **experiment with 30B Q4** (~18 GB) models.
- Model loading: Store all GGUF models on NVMe, llama.cpp mmaps them into RAM.
- Confidence: **High** — well-proven community pattern.

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Whisper batch mode breaks real-time feel | STT feels sluggish compared to streaming moshi | Use chunked processing (process every 2-3 seconds), or switch to Riva for true streaming |
| Thermal throttling at 60W sustained | Inference speed drops under sustained load | Use active cooling, or run at 30W with slightly lower performance |
| Shared memory contention | OOM kills during peak concurrent inference | Limit to single user, use memory-mapped models, monitor with `tegrastats` |
| Piper voice quality insufficient | Voices sound robotic vs. moshi's neural TTS | Upgrade to Kokoro TTS or XTTS v2 (costs more memory) |
| LLM quality too low at 3B | Responses are shallow or incoherent | Try Phi-3.5 Mini 3.8B or Mistral 7B Q4 (fits in memory budget) |
| WebSocket adapter complexity | Protocol mismatch causes audio glitches | Implement thorough integration tests, buffer audio properly |

---

## 11. Feature Comparison: What You Keep vs. What You Lose

| Feature | Original Unmute | Jetson Port |
|---------|----------------|-------------|
| Real-time voice chat | Yes | Yes (slightly higher latency) |
| Streaming STT | Yes (word-by-word) | Partial (chunked) or Yes (with Riva) |
| Streaming TTS | Yes | Yes |
| Voice cloning | Yes (kyutai voices) | Not initially (Phase 4 adds it) |
| Multiple characters/personas | Yes (voices.yaml) | Yes (LLM personas work, TTS voices differ) |
| Multi-user concurrent | 4+ users | 1 user only |
| Voice library (70+ voices) | Yes (kyutai/tts-voices) | Limited (Piper has ~30+ voices, different set) |
| LiveKit WebRTC integration | Yes | Possible (Python agent code is portable) |
| Monitoring (Prometheus/Grafana) | Yes | Yes (Python code is portable) |
| Docker deployment | Yes | Partial (no moshi-server container) |
| Offline/edge operation | No (needs GPU server) | **Yes (fully self-contained)** |
| Power consumption | 300-500W (desktop GPU) | **15-60W** |
| Physical size | Desktop/rack | **Compact module** |

---

## 12. Conclusion and Recommendation

### Step 0: Set Up NVMe SSD (30 minutes)

Before anything else, configure the 1TB NVMe as your memory safety net:

```bash
# Disable ZRAM, create 128GB NVMe swap, set swappiness low
sudo systemctl disable nvzramconfig
sudo fallocate -l 128G /ssd/128GB.swap && sudo mkswap /ssd/128GB.swap && sudo swapon /ssd/128GB.swap
sudo sysctl vm.swappiness=10
```

This turns your 32 GB physical RAM into **160 GB virtual memory** (and you can go up to 512 GB+ swap on a 1TB drive). OOM is eliminated as a showstopper.

### Step 1: Try Path A (1 day)

With NVMe swap in place, Path A is now worth attempting:

```bash
pip install torch --index-url https://developer.download.nvidia.com/compute/redist/jp/v61
pip install moshi
python -m moshi.server --host 0.0.0.0 --port 8998
```

The 32 GB swap means the Moshi 7B model (~25-30 GB working set) can load even if it slightly exceeds physical RAM. Monitor with `tegrastats` to see how much is paging to NVMe.

**If it runs at acceptable speed** -- you're done. Full Moshi voice AI on a 60W edge device.

**If it's too slow due to swap thrashing** -- proceed to Path B.

### Step 2: Path B Is the Reliable Option (3-6 weeks)

The recommended stack (whisper.cpp + Piper TTS + Ollama) fits in ~8 GB. With the NVMe SSD, you can now also:
- Run **13B LLMs** (Llama 3.1 13B Q4, ~8 GB) with zero swap pressure
- Store multiple model variants on the 1TB SSD and swap between them
- Use llama.cpp mmap to load models directly from NVMe without doubling memory usage

### Summary

| Path | Effort | Memory (RAM) | With NVMe SSD | Risk |
|------|--------|-------------|---------------|------|
| **A: PyTorch Moshi** | 1 day | ~25-30 GB | Viable (swap absorbs overflow) | Medium |
| **B: Alt stack (3B LLM)** | 3-6 weeks | ~8 GB | Comfortable (24 GB headroom) | Low |
| **B: Alt stack (13B LLM)** | 3-6 weeks | ~14 GB | Comfortable (18 GB headroom) | Low |
| **B: Alt stack (7B LLM)** | 3-6 weeks | ~10 GB | Comfortable (22 GB headroom) | Low |

The 1TB NVMe SSD changes the picture significantly:
- **Path A goes from "probably OOM" to "worth trying"**
- **Path B goes from "3B LLM max" to "13B LLM comfortably, 30B experimentally"**
- **Latency:** ~1.5-3.5s voice-to-voice (Path B), improvable to ~1-2.5s with NVIDIA Riva
- **Concurrency:** Single user only
- **Biggest win:** Fully offline, edge-deployable voice AI at 15-60W with a 1TB local model/data store

---

## Appendix A: Key Links and References

| Resource | URL |
|----------|-----|
| Moshi PyPI package | https://pypi.org/project/moshi/ |
| rustymimi (aarch64 wheels) | https://pypi.org/project/rustymimi/ |
| Kyutai Moshi GitHub | https://github.com/kyutai-labs/moshi |
| Kyutai Unmute GitHub | https://github.com/kyutai-labs/unmute |
| NVIDIA Jetson PyTorch install | https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/ |
| NVIDIA Riva on Jetson | https://developer.nvidia.com/riva |
| Jetson AI Lab (containers) | https://github.com/dusty-nv/jetson-containers |
| Ollama on Jetson | https://ollama.com (aarch64 Linux builds) |
| whisper.cpp | https://github.com/ggerganov/whisper.cpp |
| Piper TTS | https://github.com/rhasspy/piper |
| Moshi on Jetson forum thread (unanswered) | https://forums.developer.nvidia.com/t/kyutai-moshi-install/331658 |
| Jetson AI Lab RAM Optimization | https://www.jetson-ai-lab.com/tutorials/ram-optimization/ |
| HuggingFace Accelerate Big Models | https://huggingface.co/docs/accelerate/en/concept_guides/big_model_inference |
| CUDA Unified Memory Guide | https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/unified-memory.html |
| Jetson NVMe SSD Compatibility | https://forums.developer.nvidia.com/t/nvme-ssd-compatibility-for-agx-orin-devkit/228143 |
| Jetson NVMe Benchmark Thread | https://forums.developer.nvidia.com/t/nvme-gen4-x4-ssd-read-speed/251302 |

## Appendix B: Unmute WebSocket Protocol Reference

For anyone implementing Path B adapter services, the full moshi WebSocket protocol is documented in Sections 4.2 and 4.3 above. Key implementation notes:

- Serialization: MessagePack with `use_bin_type=True, use_single_float=True`
- Audio: PCM float32 at 24 kHz, 1920 samples per frame (80ms)
- Handshake: Server must send `{"type": "Ready"}` before client sends data
- STT VAD: `Step.prs[2]` is pause probability (0.0-1.0), used with EMA filter for end-of-speech detection
- TTS voice selection: Passed as query parameter on WebSocket URL
- Auth: Header `{"kyutai-api-key": "public_token"}` (hardcoded token)
