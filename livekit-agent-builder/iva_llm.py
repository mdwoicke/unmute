"""Custom LLM plugin that wraps the IVA graph as a LiveKit LLM.

This allows the LiveKit session pipeline to handle transcript accumulation,
turn detection, and TTS routing naturally — the same way it works with
the OpenAI LLM plugin in the MCP agent.

Instead of calling an LLM API, this "LLM" routes the user's message
through the IVA graph's process_turn() and emits the response as
ChatChunk events.
"""

import asyncio
import logging
import uuid

from livekit.agents import llm, APIConnectOptions
from livekit.agents.llm import ChatContext, ChatChunk, ChoiceDelta, Tool

from iva_bridge import IVABridge

logger = logging.getLogger(__name__)


class IVALLM(llm.LLM):
    """LLM wrapper that routes conversation through the IVA graph."""

    def __init__(self, iva_bridge: IVABridge):
        super().__init__()
        self._iva = iva_bridge

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = APIConnectOptions(),
        **kwargs,
    ) -> "IVALLMStream":
        return IVALLMStream(
            llm=self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            iva_bridge=self._iva,
        )


class IVALLMStream(llm.LLMStream):
    """LLM stream that processes the latest user message through IVA."""

    def __init__(
        self,
        *,
        llm: IVALLM,
        chat_ctx: ChatContext,
        tools: list[Tool],
        conn_options: APIConnectOptions,
        iva_bridge: IVABridge,
    ):
        super().__init__(llm=llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._iva = iva_bridge

    async def _run(self) -> None:
        # Extract the latest user message from chat context
        user_text = ""
        for item in reversed(self.chat_ctx.items):
            if hasattr(item, "role") and item.role == "user":
                user_text = item.text_content if hasattr(item, "text_content") else str(item)
                break

        if not user_text or not user_text.strip():
            # Emit empty response
            self._event_ch.send_nowait(
                ChatChunk(
                    id=str(uuid.uuid4()),
                    delta=ChoiceDelta(role="assistant", content=""),
                )
            )
            return

        logger.info(f"IVA LLM processing: {user_text}")

        try:
            result = await self._iva.process(user_text)
        except Exception as e:
            logger.error(f"IVA processing error: {e}", exc_info=True)
            response = "I'm sorry, I encountered an issue. Could you repeat that?"
            self._event_ch.send_nowait(
                ChatChunk(
                    id=str(uuid.uuid4()),
                    delta=ChoiceDelta(role="assistant", content=response),
                )
            )
            return

        response = result.get("response", "")
        logger.info(f"IVA response: {response[:100]}")

        # Clean and format response for TTS with natural pauses.
        # LiveKit accumulates all ChatChunks into one TTS request,
        # so pauses must be embedded in the text itself.
        import re
        # Ensure space after sentence-ending punctuation
        response = re.sub(r'([.!?])([A-Z])', r'\1 \2', response)
        # Replace sentence-ending periods with commas + pause ellipsis.
        # This creates a natural breath pause between confirmation and question.
        # Don't replace the final sentence's punctuation.
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', response) if s.strip()]
        if len(sentences) > 1:
            # Join with pause: comma + ellipsis creates ~0.5s pause in Kyutai TTS
            parts = []
            for i, s in enumerate(sentences):
                # Strip trailing period (TTS speaks it as "dot")
                if s.endswith('.'):
                    s = s[:-1]
                parts.append(s)
            # Join with pause markers — ",,," creates a natural breath pause
            response = ",,,  ".join(parts)
        else:
            # Single sentence — just strip trailing period
            if response.endswith('.'):
                response = response[:-1]

        self._event_ch.send_nowait(
            ChatChunk(
                id=str(uuid.uuid4()),
                delta=ChoiceDelta(role="assistant", content=response),
            )
        )
