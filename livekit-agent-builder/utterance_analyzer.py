"""Pydantic-based utterance analyzer with A/B test modes.

Replaces regex preprocessing with structured LLM calls for better
handling of relative dates, spoken numbers, and edge cases.

Modes (controlled by UTTERANCE_ANALYZER env var):
  - legacy:  regex only (iva_bridge._preprocess_utterance)
  - hybrid:  trivial patterns handled locally, complex → LLM  (default)
  - pydantic: always LLM
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class UtteranceAnalysis(BaseModel):
    utterance_type: Literal["slot_data", "question", "confirmation", "noise", "fragment"]
    normalized_utterance: str  # dates/times/numbers resolved to absolute values
    slot_values: dict[str, Any] = {}  # extracted slots ready for IVA
    is_question: bool = False
    conversational_response: str | None = None  # answer if question
    tts_response: str | None = None  # voice-formatted (no periods, ,,, for pauses)
    confidence: float  # 0.0-1.0
    reasoning: str = ""  # for logging

    @field_validator("tts_response", mode="before")
    @classmethod
    def clean_tts_response(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Strip markdown bold/italic markers
        v = re.sub(r"\*+", "", v)
        v = re.sub(r"_+", "", v)
        v = re.sub(r"`+", "", v)
        # Strip trailing periods (TTS says "dot")
        v = v.rstrip(".")
        return v


# ---------------------------------------------------------------------------
# Stage context map
# ---------------------------------------------------------------------------

STAGE_CONTEXT: dict[str, str] = {
    "verification": "member ID",
    "collect_pickup": "pickup address",
    "collect_dropoff": "destination address",
    "collect_time": "appointment date and time",
    "mobility": "mobility needs",
    "companion": "companions",
    "return_ride": "return ride",
    "special_instructions": "special instructions",
    "confirmation": "booking confirmation",
}

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_analysis_prompt(
    utterance: str,
    stage: str,
    collected_slots: dict[str, Any],
    history: list[dict[str, str]],
) -> str:
    now = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
    stage_desc = STAGE_CONTEXT.get(stage, stage)

    recent_history = history[-3:] if history else []
    history_block = ""
    if recent_history:
        lines = []
        for turn in recent_history:
            role = turn.get("role", "unknown")
            text = turn.get("content", turn.get("text", ""))
            lines.append(f"  {role}: {text}")
        history_block = "\n".join(lines)

    slots_json = json.dumps(collected_slots, indent=2) if collected_slots else "{}"

    return f"""Analyze this voice utterance for an NEMT (medical transportation) booking system.

Current date/time: {now}
Current booking stage: {stage} (collecting: {stage_desc})
Slots already collected: {slots_json}
Recent conversation:
{history_block}

User said: "{utterance}"

CRITICAL INSTRUCTIONS:
- Resolve ALL relative dates to absolute dates using the current date above. For example "next wednesday" must become the actual date of the next Wednesday from today. Use ordinal dates like "April 8th".
- Convert spoken numbers to digits (e.g. "twenty three" → "23").
- For TTS responses: do NOT use periods (TTS engine says "dot"). Use ",,," between sentences for breath pauses. No markdown formatting. Spell out abbreviations.

Respond with ONLY a JSON object matching this exact schema:
{{
  "utterance_type": "slot_data" | "question" | "confirmation" | "noise" | "fragment",
  "normalized_utterance": "<dates/times/numbers resolved to absolute values>",
  "slot_values": {{}},
  "is_question": false,
  "conversational_response": null,
  "tts_response": null,
  "confidence": 0.9,
  "reasoning": "<brief explanation>"
}}"""


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

def parse_llm_response(raw: str) -> UtteranceAnalysis | None:
    """Parse raw LLM text into UtteranceAnalysis, tolerating markdown fences
    and <think> blocks."""
    if not raw:
        return None

    text = raw.strip()

    # Strip <think>...</think> blocks (qwen model produces these)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        return UtteranceAnalysis(**data)
    except Exception as exc:
        logger.warning("Failed to parse LLM response: %s — raw: %.200s", exc, raw)
        return None


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str) -> str | None:
    """POST to LM Studio chat completions endpoint."""
    lm_url = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
    model = os.environ.get("LM_STUDIO_MODEL", os.environ.get("LLM_MODEL", "qwen3-4b"))

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "/no_think\nYou are a voice utterance analyzer. Respond with ONLY valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{lm_url}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Trivial pattern matcher (hybrid mode fast-path)
# ---------------------------------------------------------------------------

_YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay"}
_NO_WORDS = {"no", "nope", "nah"}


def _is_trivial(utterance: str) -> UtteranceAnalysis | None:
    """Return an UtteranceAnalysis for trivially classifiable utterances,
    or None to fall through to LLM."""
    cleaned = utterance.strip().lower().rstrip(".,!?")

    if not cleaned:
        return UtteranceAnalysis(
            utterance_type="noise",
            normalized_utterance="",
            confidence=1.0,
            reasoning="empty utterance",
        )

    if cleaned in _YES_WORDS:
        return UtteranceAnalysis(
            utterance_type="confirmation",
            normalized_utterance=cleaned,
            slot_values={"confirmed": True},
            confidence=1.0,
            reasoning="affirmative keyword",
        )

    if cleaned in _NO_WORDS:
        return UtteranceAnalysis(
            utterance_type="confirmation",
            normalized_utterance=cleaned,
            slot_values={"confirmed": False},
            confidence=1.0,
            reasoning="negative keyword",
        )

    if re.fullmatch(r"\d+", cleaned):
        return UtteranceAnalysis(
            utterance_type="slot_data",
            normalized_utterance=cleaned,
            slot_values={"digits": cleaned},
            confidence=1.0,
            reasoning="pure digits",
        )

    return None


# ---------------------------------------------------------------------------
# Legacy fallback
# ---------------------------------------------------------------------------

def _analyze_legacy(utterance: str, stage: str) -> UtteranceAnalysis:
    """Wrap the old regex preprocessor in an UtteranceAnalysis."""
    from iva_bridge import _preprocess_utterance

    preprocessed = _preprocess_utterance(utterance, stage)
    return UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance=preprocessed,
        confidence=0.5,
        reasoning="legacy regex preprocessing",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def analyze_utterance(
    utterance: str,
    stage: str = "",
    collected_slots: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
) -> UtteranceAnalysis:
    """Analyze a voice utterance using the configured mode.

    Modes (UTTERANCE_ANALYZER env var):
      legacy  – regex only
      hybrid  – trivial patterns local, complex → LLM  (default)
      pydantic – always LLM
    """
    collected_slots = collected_slots or {}
    history = history or []
    mode = os.environ.get("UTTERANCE_ANALYZER", "hybrid").lower()

    # Legacy mode — skip LLM entirely
    if mode == "legacy":
        return _analyze_legacy(utterance, stage)

    # Hybrid mode — try trivial first
    if mode == "hybrid":
        trivial = _is_trivial(utterance)
        if trivial is not None:
            return trivial

    # Build prompt and call LLM (hybrid fallthrough + pydantic mode)
    prompt = build_analysis_prompt(utterance, stage, collected_slots, history)
    raw = await _call_llm(prompt)

    if raw:
        result = parse_llm_response(raw)
        if result is not None:
            return result

    # LLM failed — fall back to legacy
    logger.warning("LLM analysis failed, falling back to legacy for: %.100s", utterance)
    return _analyze_legacy(utterance, stage)
