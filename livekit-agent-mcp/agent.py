"""LiveKit Voice Agent with MCP-based weather tool.

Instead of @function_tool, this agent discovers tools via MCP protocol
from an internal FastMCP server running alongside it.
"""

import json
import logging
import os

from livekit.agents import Agent, AgentSession, AutoSubscribe, JobContext, WorkerOptions, cli
from livekit.agents.llm import mcp
from livekit.plugins import openai

from kyutai_stt import KyutaiSTT
from kyutai_tts import KyutaiTTS

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration from environment
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "qwen/qwen3-4b")
KYUTAI_STT_URL = os.environ.get("KYUTAI_STT_URL", "ws://localhost:8090")
KYUTAI_TTS_URL = os.environ.get("KYUTAI_TTS_URL", "ws://localhost:8089")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")
MCP_SPORTS_SERVER_URL = os.environ.get("MCP_SPORTS_SERVER_URL", "http://localhost:8001/sse")
DEFAULT_VOICE = "unmute-prod-website/p329_022.wav"

SYSTEM_PROMPT = """/no_think
You are a helpful voice assistant. You speak in short, natural sentences.
Your responses will be spoken aloud, so keep them concise and conversational.
Do not use markdown, bullet points, or special characters.

When the user asks about weather, temperature, or conditions for a location,
use the get_weather tool to look it up. Always use the tool rather than guessing.
Pass the city name or zipcode the user mentions.

When the user asks about sports scores, standings, or schedules for NFL, NBA, MLB,
or NHL, use the appropriate sports tool. Use get_scores for current or recent game
results, get_standings for league standings, and get_schedule to find upcoming games
for a team. Always pass the league name and team name when mentioned.

When reporting sports results, follow these rules:
Read the tool response naturally as it is already formatted for speech.
Do not add extra games or details beyond what the tool provided.
Keep your response to 2 to 4 sentences maximum.
Say numbers naturally, like 112 to 105 instead of 112 comma 105.
"""


async def entrypoint(ctx: JobContext):
    logger.info("MCP Agent entrypoint called")

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

    # Initialize components — same models as function-call demo
    stt_plugin = KyutaiSTT(url=KYUTAI_STT_URL)
    tts_plugin = KyutaiTTS(url=KYUTAI_TTS_URL, voice=voice)

    llm_plugin = openai.LLM(
        model=LM_STUDIO_MODEL,
        base_url=LM_STUDIO_URL,
        api_key="EMPTY",
        temperature=0.7,
    )

    # Connect to internal MCP server for weather tool
    mcp_weather = mcp.MCPServerHTTP(url=MCP_SERVER_URL)
    logger.info(f"Connecting to MCP server at {MCP_SERVER_URL}")
    mcp_sports = mcp.MCPServerHTTP(url=MCP_SPORTS_SERVER_URL)
    logger.info(f"Connecting to Sports MCP server at {MCP_SPORTS_SERVER_URL}")

    session = AgentSession(
        stt=stt_plugin,
        llm=llm_plugin,
        tts=tts_plugin,
        tools=[
            mcp.MCPToolset(id="weather_mcp", mcp_server=mcp_weather),
            mcp.MCPToolset(id="sports_mcp", mcp_server=mcp_sports),
        ],
    )

    await session.start(
        room=ctx.room,
        agent=Agent(instructions=SYSTEM_PROMPT),
    )

    await session.say(
        "Hello! I'm your voice assistant powered by MCP tools. "
        "Ask me about the weather or sports scores, standings, and schedules."
    )

    logger.info("MCP Agent session started")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="unmute-livekit-agent-mcp",
        )
    )
