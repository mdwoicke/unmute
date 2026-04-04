"""LiveKit Voice Agent with IVA (Interactive Voice Agent) pipeline.

Uses a custom LLM wrapper (IVALLM) that routes user messages through the
IVA LangGraph FSM instead of calling an LLM API. This lets the LiveKit
session pipeline handle transcript accumulation, turn detection, and TTS
routing naturally — the same way the MCP agent works with OpenAI.
"""

import json
import logging
import os

from livekit.agents import Agent, AgentSession, AutoSubscribe, JobContext, WorkerOptions, cli

from kyutai_stt import KyutaiSTT
from kyutai_tts import KyutaiTTS
from iva_bridge import IVABridge
from iva_llm import IVALLM

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration from environment
KYUTAI_STT_URL = os.environ.get("KYUTAI_STT_URL", "ws://localhost:8090")
KYUTAI_TTS_URL = os.environ.get("KYUTAI_TTS_URL", "ws://localhost:8089")
DEFAULT_VOICE = "unmute-prod-website/p329_022.wav"

SYSTEM_PROMPT = """/no_think
You are a transportation booking assistant.
"""


async def entrypoint(ctx: JobContext):
    logger.info("IVA Agent entrypoint called")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Connected to room: {ctx.room.name}")

    # Read voice selection from room metadata
    voice = DEFAULT_VOICE
    room_metadata = ctx.room.metadata
    if room_metadata:
        try:
            meta = json.loads(room_metadata)
            voice = meta.get("voice", DEFAULT_VOICE)
            logger.info(f"Voice selected: {voice}")
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Could not parse room metadata: {room_metadata}")

    # Initialize components
    stt_plugin = KyutaiSTT(url=KYUTAI_STT_URL)
    tts_plugin = KyutaiTTS(url=KYUTAI_TTS_URL, voice=voice)

    # Initialize IVA bridge and custom LLM wrapper
    iva = IVABridge()
    greeting = iva.init_session()
    logger.info(f"IVA session started: {iva.session_id}")

    llm_plugin = IVALLM(iva_bridge=iva)

    # Create session — same pattern as the MCP agent
    # Increase endpointing delays so the pipeline waits for the full
    # utterance before sending to IVA (prevents fragmented turns)
    session = AgentSession(
        stt=stt_plugin,
        tts=tts_plugin,
        llm=llm_plugin,
        min_endpointing_delay=0.8,
        max_endpointing_delay=3.0,
    )

    await session.start(
        room=ctx.room,
        agent=Agent(instructions=SYSTEM_PROMPT),
    )

    # Speak the IVA greeting
    await session.say(greeting)
    logger.info("IVA greeting spoken")

    logger.info("IVA Agent session started, listening for speech")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="unmute-livekit-agent-builder",
        )
    )
