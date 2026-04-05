"""Custom LiveKit STT adapter for Kyutai moshi-server ASR.

Implements streaming STT by connecting to moshi-server WebSocket.
"""

import asyncio
import logging

import msgpack
import numpy as np
import websockets
from livekit import rtc
from livekit.agents import stt, APIConnectOptions

logger = logging.getLogger(__name__)

KYUTAI_SAMPLE_RATE = 24000
KYUTAI_FRAME_SAMPLES = 1920  # 80ms at 24kHz
HEADERS = {"kyutai-api-key": "public_token"}


class KyutaiSTT(stt.STT):
    def __init__(self, url: str = "ws://localhost:8090"):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._url = url
        self._api_path = "/api/asr-streaming"

    async def _recognize_impl(
        self,
        buffer,
        *,
        language=None,
        conn_options: APIConnectOptions = APIConnectOptions(),
    ) -> stt.SpeechEvent:
        raise NotImplementedError("Use streaming mode")

    def stream(
        self,
        *,
        language=None,
        conn_options: APIConnectOptions = APIConnectOptions(),
        **kwargs,
    ) -> "KyutaiSpeechStream":
        return KyutaiSpeechStream(
            stt=self,
            conn_options=conn_options,
        )


class KyutaiSpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt: KyutaiSTT,
        conn_options: APIConnectOptions,
    ):
        super().__init__(
            stt=stt,
            conn_options=conn_options,
            sample_rate=KYUTAI_SAMPLE_RATE,
        )
        self._stt_instance = stt
        self._current_text = ""
        self._speaking = False

    async def _run(self) -> None:
        url = self._stt_instance._url + self._stt_instance._api_path

        # Retry connection
        ws = None
        for attempt in range(3):
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(url, additional_headers=HEADERS),
                    timeout=10,
                )
                break
            except Exception as e:
                logger.warning(f"STT connect attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    raise

        if ws is None:
            return

        try:
            # Wait for Ready
            ready_bytes = await asyncio.wait_for(ws.recv(), timeout=5)
            ready_msg = msgpack.unpackb(ready_bytes)
            if ready_msg.get("type") != "Ready":
                raise RuntimeError(f"Expected Ready, got {ready_msg}")
            logger.info("Connected to Kyutai STT")

            send_task = asyncio.create_task(self._send_audio(ws))
            recv_task = asyncio.create_task(self._recv_results(ws))

            # Both tasks must run concurrently for the full session
            await asyncio.gather(send_task, recv_task, return_exceptions=True)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"KyutaiSTT error: {e}")
        finally:
            if ws:
                await ws.close()

    async def _send_audio(self, ws: websockets.ClientConnection) -> None:
        """Read frames from LiveKit input channel, resample, send to moshi-server."""
        buffer = np.array([], dtype=np.float32)

        frames_sent = 0
        try:
            async for frame in self._input_ch:
                if not isinstance(frame, rtc.AudioFrame):
                    continue

                audio_int16 = np.frombuffer(frame.data, dtype=np.int16)

                if frames_sent == 0:
                    logger.info(f"First audio frame: sr={frame.sample_rate} samples={len(audio_int16)} dtype={audio_int16.dtype}")
                if frames_sent < 5 or frames_sent % 200 == 0:
                    rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2))
                    logger.info(f"Audio frame {frames_sent}: rms={rms:.1f} max={np.max(np.abs(audio_int16))}")

                # Already resampled to 24kHz by the framework (we set sample_rate in __init__)
                audio_f32 = audio_int16.astype(np.float32) / 32768.0
                buffer = np.concatenate([buffer, audio_f32])

                while len(buffer) >= KYUTAI_FRAME_SAMPLES:
                    chunk = buffer[:KYUTAI_FRAME_SAMPLES]
                    buffer = buffer[KYUTAI_FRAME_SAMPLES:]
                    msg = msgpack.packb(
                        {"type": "Audio", "pcm": chunk.tolist()},
                        use_bin_type=True,
                        use_single_float=True,
                    )
                    await ws.send(msg)
                    frames_sent += 1
                    if frames_sent % 100 == 0:
                        logger.info(f"STT: sent {frames_sent} frames to moshi-server")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT send error: {e}")

    async def _recv_results(self, ws: websockets.ClientConnection) -> None:
        """Receive transcription from moshi-server, emit SpeechEvents."""
        n_steps_to_wait = 12
        step_count = 0

        try:
            async for message_bytes in ws:
                data = msgpack.unpackb(message_bytes)
                msg_type = data.get("type")

                if msg_type == "Step":
                    step_count += 1
                    if step_count % 50 == 0:
                        prs = data.get("prs", [])
                        logger.info(f"STT recv: {step_count} steps, prs={[round(p,2) for p in prs]}")

                if msg_type == "Word":
                    text = data.get("text", "")
                    logger.info(f"STT Word: '{text}'")
                    if not self._speaking:
                        self._speaking = True
                        self._current_text = ""
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.START_OF_SPEECH,
                            )
                        )

                    self._current_text += (" " if self._current_text else "") + text
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(
                            type=stt.SpeechEventType.INTERIM_TRANSCRIPT,
                            alternatives=[
                                stt.SpeechData(
                                    text=self._current_text,
                                    language="en",
                                    confidence=0.9,
                                )
                            ],
                        )
                    )

                elif msg_type == "Step":
                    prs = data.get("prs", [0, 0, 0])
                    pause_prob = prs[2] if len(prs) > 2 else 0

                    if n_steps_to_wait > 0:
                        n_steps_to_wait -= 1
                        continue

                    if self._speaking and pause_prob > 0.7 and self._current_text:
                        self._speaking = False
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                                alternatives=[
                                    stt.SpeechData(
                                        text=self._current_text,
                                        language="en",
                                        confidence=0.95,
                                    )
                                ],
                            )
                        )
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=stt.SpeechEventType.END_OF_SPEECH,
                            )
                        )
                        self._current_text = ""

        except websockets.ConnectionClosedOK:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT recv error: {e}")
