"""LiveKit Voice Agent with Kyutai STT/TTS and LM Studio LLM (v1.5 API)."""

import json
import logging
import os

from livekit.agents import Agent, AgentSession, AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.plugins import openai

from kyutai_stt import KyutaiSTT
from kyutai_tts import KyutaiTTS
from weather_tools import get_weather

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration from environment
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "qwen/qwen3-4b")
KYUTAI_STT_URL = os.environ.get("KYUTAI_STT_URL", "ws://localhost:8090")
KYUTAI_TTS_URL = os.environ.get("KYUTAI_TTS_URL", "ws://localhost:8089")
DEFAULT_VOICE = "unmute-prod-website/p329_022.wav"

SYSTEM_PROMPT = """/no_think
You are a helpful voice assistant. You speak in short, natural sentences.
Your responses will be spoken aloud, so keep them concise and conversational.
Do not use markdown, bullet points, or special characters.

When the user asks about weather, temperature, or conditions for a location or zipcode,
use the get_weather function to look it up. Always use the function rather than guessing.

If the user says a zipcode like "90210" or "what is the weather in 10001",
call get_weather with that zipcode.
"""


async def entrypoint(ctx: JobContext):
    logger.info("Agent entrypoint called")

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

    llm_plugin = openai.LLM(
        model=LM_STUDIO_MODEL,
        base_url=LM_STUDIO_URL,
        api_key="EMPTY",
        temperature=0.7,
    )

    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        tools=[get_weather],
    )

    await session.start(
        room=ctx.room,
        agent=Agent(instructions=SYSTEM_PROMPT),
    )

    await session.say(
        "Hello! I'm your voice assistant. "
        "Ask me anything, or try asking about the weather."
    )

    logger.info("Agent session started")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="unmute-livekit-agent",
        )
    )
