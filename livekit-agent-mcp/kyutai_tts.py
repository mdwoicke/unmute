"""Custom LiveKit TTS adapter for Kyutai moshi-server TTS.

Uses ChunkedStream (non-streaming) pattern — matching the OpenAI TTS plugin.
LiveKit's StreamAdapter automatically wraps this for streaming use.
"""

import asyncio
import logging
import os
import uuid

import msgpack
import numpy as np
import websockets
from livekit.agents import tts, APIConnectOptions

logger = logging.getLogger(__name__)

KYUTAI_SAMPLE_RATE = 24000
LIVEKIT_SAMPLE_RATE = 48000
HEADERS = {"kyutai-api-key": "public_token"}


class KyutaiTTS(tts.TTS):
    def __init__(
        self,
        url: str = "ws://localhost:8089",
        voice: str = "unmute-prod-website/p329_022.wav",
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )
        self._url = url
        self._api_path = "/api/tts_streaming"
        self._voice = voice

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> "KyutaiChunkedStream":
        return KyutaiChunkedStream(
            tts=self, input_text=text, conn_options=conn_options
        )


class KyutaiChunkedStream(tts.ChunkedStream):
    """Non-streaming TTS — matches the OpenAI TTS plugin pattern exactly."""

    def __init__(
        self,
        *,
        tts: KyutaiTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        text = _prepare_text(self.input_text)
        if not text:
            return

        query_params = (
            f"?format=PcmMessagePack"
            f"&voice={self._tts._voice}"
            f"&cfg_alpha=1.5"
        )
        url = self._tts._url + self._tts._api_path + query_params

        # Retry connection up to 3 times (TTS might still be starting)
        ws = None
        for attempt in range(3):
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(url, additional_headers=HEADERS),
                    timeout=10,
                )
                break
            except Exception as e:
                logger.warning(f"TTS connect attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    raise

        if ws is None:
            return

        try:
            # Wait for Ready
            for _ in range(10):
                ready_bytes = await asyncio.wait_for(ws.recv(), timeout=5)
                ready_msg = msgpack.unpackb(ready_bytes)
                if ready_msg.get("type") == "Ready":
                    break

            logger.info(f"Connected to Kyutai TTS, sending: {text[:50]}...")

            # Initialize the emitter (matching OpenAI plugin pattern)
            output_emitter.initialize(
                request_id=str(uuid.uuid4()),
                sample_rate=LIVEKIT_SAMPLE_RATE,
                num_channels=1,
                mime_type="audio/pcm",
            )

            # Send text + EOS
            await ws.send(msgpack.packb({"type": "Text", "text": text}))
            await ws.send(msgpack.packb({"type": "Eos"}))

            # Receive audio and push to emitter
            async for message_bytes in ws:
                data = msgpack.unpackb(message_bytes)
                if data.get("type") == "Audio":
                    pcm_f32 = np.array(data["pcm"], dtype=np.float32)
                    pcm_bytes = _to_pcm_bytes(pcm_f32)
                    output_emitter.push(pcm_bytes)

            output_emitter.flush()
            logger.info("TTS synthesis complete")

        except Exception as e:
            logger.error(f"KyutaiTTS error: {e}")
            raise
        finally:
            await ws.close()


def _prepare_text(text: str) -> str:
    text = text.strip()
    for char in "*_`":
        text = text.replace(char, "")
    return text


TTS_GAIN = float(os.environ.get("TTS_GAIN", "1.5"))


def _to_pcm_bytes(pcm_float32: np.ndarray, gain: float = TTS_GAIN) -> bytes:
    """Convert Kyutai 24kHz float32 to 48kHz int16 PCM bytes.

    Args:
        pcm_float32: Raw float32 PCM from Kyutai TTS.
        gain: Volume multiplier (1.0 = original, 1.5 = 50% louder, 2.0 = double).
    """
    resampled = np.repeat(pcm_float32, 2)  # 24k -> 48k
    audio_int16 = (resampled * gain * 32767).clip(-32768, 32767).astype(np.int16)
    return audio_int16.tobytes()
