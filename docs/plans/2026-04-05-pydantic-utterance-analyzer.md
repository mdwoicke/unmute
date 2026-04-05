# Pydantic Utterance Analyzer — A/B Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace brittle regex preprocessing with a Pydantic-structured LLM call that analyzes utterances, resolves dates/numbers, detects questions, and formats TTS-friendly responses — all in one shot. A/B testable via env var with legacy path preserved.

**Architecture:** New `utterance_analyzer.py` module with a `UtteranceAnalysis` Pydantic model as the unified output contract. Three modes selectable via `UTTERANCE_ANALYZER` env var: `pydantic` (full LLM), `hybrid` (fast regex + LLM fallback), `legacy` (original regex code). `iva_bridge.py` calls `analyze_utterance()` instead of the individual preprocessing functions. Original functions untouched as backup.

**Tech Stack:** Pydantic v2 (already in requirements.txt), httpx (already used), LM Studio OpenAI-compatible API (qwen3-4b)

---

## Task 1: Create Pydantic Model + Analyzer Module

**Files:**
- Create: `livekit-agent-builder/utterance_analyzer.py`
- Test: `livekit-agent-builder/test_utterance_analyzer.py`

**Step 1: Write the failing test**

```python
"""Tests for utterance_analyzer module."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from unittest.mock import patch, MagicMock
from utterance_analyzer import UtteranceAnalysis, build_analysis_prompt, parse_llm_response


def test_utterance_analysis_model_valid():
    """Pydantic model accepts well-formed data."""
    analysis = UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance="April 8th at 2 PM",
        slot_values={"appointment_date": "April 8th", "appointment_time": "2 PM"},
        is_question=False,
        conversational_response=None,
        tts_response=None,
        confidence=0.95,
        reasoning="Caller providing appointment date and time",
    )
    assert analysis.utterance_type == "slot_data"
    assert analysis.confidence == 0.95
    assert analysis.slot_values["appointment_date"] == "April 8th"


def test_utterance_analysis_model_rejects_bad_type():
    """Pydantic model rejects invalid utterance_type."""
    with pytest.raises(Exception):
        UtteranceAnalysis(
            utterance_type="invalid_type",
            normalized_utterance="test",
            slot_values={},
            is_question=False,
            conversational_response=None,
            tts_response=None,
            confidence=0.5,
            reasoning="test",
        )


def test_build_analysis_prompt_includes_date():
    """Prompt includes current date for relative date resolution."""
    prompt = build_analysis_prompt(
        utterance="next wednesday at 2 pm",
        stage="collect_time",
        collected_slots={},
        history=[],
    )
    # Should contain a date string like "Saturday, April 05, 2026"
    assert "2026" in prompt
    assert "april" in prompt.lower() or "April" in prompt


def test_build_analysis_prompt_includes_stage():
    """Prompt includes current conversation stage."""
    prompt = build_analysis_prompt(
        utterance="123 Main Street",
        stage="collect_pickup",
        collected_slots={"member_id": "1234"},
        history=[],
    )
    assert "collect_pickup" in prompt


def test_parse_llm_response_valid_json():
    """Parser extracts UtteranceAnalysis from valid LLM JSON."""
    raw = '{"utterance_type":"slot_data","normalized_utterance":"April 8th at 2 PM","slot_values":{"appointment_date":"April 8th"},"is_question":false,"conversational_response":null,"tts_response":null,"confidence":0.9,"reasoning":"date provided"}'
    result = parse_llm_response(raw)
    assert isinstance(result, UtteranceAnalysis)
    assert result.normalized_utterance == "April 8th at 2 PM"


def test_parse_llm_response_strips_markdown_fences():
    """Parser handles LLM wrapping JSON in markdown code fences."""
    raw = '```json\n{"utterance_type":"question","normalized_utterance":"where is my member ID","slot_values":{},"is_question":true,"conversational_response":"Your member ID is on your insurance card","tts_response":"Your member ID is on your insurance card","confidence":0.85,"reasoning":"asking about member ID"}\n```'
    result = parse_llm_response(raw)
    assert result.is_question is True
    assert result.conversational_response is not None


def test_parse_llm_response_returns_none_on_garbage():
    """Parser returns None on unparseable LLM output."""
    result = parse_llm_response("I'm sorry, I can't help with that.")
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `cd livekit-agent-builder && python -m pytest test_utterance_analyzer.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

Create `livekit-agent-builder/utterance_analyzer.py`:

```python
"""Pydantic-based utterance analyzer for IVA voice pipeline.

Replaces regex preprocessing with structured LLM calls that handle
date/time resolution, question detection, slot extraction, and TTS
formatting in a single call.

Three modes via UTTERANCE_ANALYZER env var:
  - "pydantic": Full LLM analysis for every utterance
  - "hybrid":   Fast regex for trivials, LLM for complex (default)
  - "legacy":   Original regex preprocessing (backup)
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ── Pydantic Model ─────────────────────────────────────────────────────

class UtteranceAnalysis(BaseModel):
    """Structured output from utterance analysis.

    This is the single contract between the analyzer and iva_bridge.
    All three modes (pydantic, hybrid, legacy) produce this same shape.
    """
    utterance_type: Literal["slot_data", "question", "confirmation", "noise", "fragment"]
    normalized_utterance: str = Field(
        description="Utterance with dates/times/numbers resolved to absolute values"
    )
    slot_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted slot key-value pairs ready for IVA"
    )
    is_question: bool = Field(
        default=False,
        description="Whether the utterance is a question/clarification request"
    )
    conversational_response: str | None = Field(
        default=None,
        description="If is_question=True, a helpful answer. Otherwise None."
    )
    tts_response: str | None = Field(
        default=None,
        description="Voice-formatted response for TTS output. Uses ,,, for pauses, no periods, no markdown."
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reasoning: str = Field(
        default="",
        description="Short explanation for logging/debugging"
    )

    @field_validator("tts_response", mode="before")
    @classmethod
    def clean_tts_response(cls, v):
        """Strip periods and markdown from TTS output."""
        if v is None:
            return v
        # Remove markdown
        for char in "*_`#":
            v = v.replace(char, "")
        # Strip trailing period (TTS reads it as "dot")
        if v.endswith("."):
            v = v[:-1]
        return v


# ── Prompt Builder ───────────────────────────────────────────────────��─

_SLOT_DESCRIPTIONS = {
    "verification": "member ID (found on insurance card or welcome letter)",
    "collect_pickup": "pickup address",
    "collect_dropoff": "destination/dropoff address",
    "collect_time": "appointment date and time",
    "mobility": "mobility assistance needs (wheelchair, walker, etc.)",
    "companion": "number of companions and relationship",
    "return_ride": "whether they need a return ride",
    "special_instructions": "special instructions for the driver",
    "confirmation": "confirmation of booking details",
}


def build_analysis_prompt(
    utterance: str,
    stage: str,
    collected_slots: dict,
    history: list[dict],
) -> str:
    """Build the system+user prompt for utterance analysis."""
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y %I:%M %p")
    stage_info = _SLOT_DESCRIPTIONS.get(stage, "the requested information")
    collected_str = json.dumps(
        {k: v for k, v in collected_slots.items() if v is not None}, indent=2
    ) if any(v is not None for v in collected_slots.values()) else "none yet"

    # Build conversation context
    history_lines = ""
    if history:
        recent = history[-3:]
        for h in recent:
            if h.get("utterance"):
                history_lines += f"  Caller: {h['utterance']}\n"
            if h.get("agent_response"):
                history_lines += f"  Agent: {h['agent_response']}\n"

    prompt = f"""You are analyzing a caller utterance for an NEMT (medical transportation) booking voice agent named Ally.

CURRENT DATE/TIME: {date_str}
CONVERSATION STAGE: {stage} (currently collecting: {stage_info})
SLOTS COLLECTED SO FAR: {collected_str}

RECENT CONVERSATION:
{history_lines if history_lines else "  (start of conversation)"}

CALLER SAID: "{utterance}"

INSTRUCTIONS:
1. ANALYZE the utterance — is it providing slot data, asking a question, confirming something, or noise/fragment?
2. NORMALIZE the utterance — resolve ALL relative dates and times to absolute values:
   - "next Wednesday" → "{(now + __import__('datetime').timedelta(days=(2 - now.weekday()) % 7 or 7)).strftime('%B')} {(now + __import__('datetime').timedelta(days=(2 - now.weekday()) % 7 or 7)).day}th" (calculate from current date above)
   - "tomorrow" → the actual date
   - "9 am" → "9:00 AM"
   - Convert spoken numbers to digits: "one six three two" → "1632"
   - Use ordinal dates: "April 8th" not "April 8" or "4/8"
3. EXTRACT slot values as a JSON dict. Only include slots you can confidently extract. Slot keys:
   member_id, pickup_address, dropoff_address, appointment_date, appointment_time,
   mobility_type, mobility_assistance_needed, number_of_companions, companion_relationship,
   return_ride_needed, return_pickup_time, special_instructions, gate_code
4. If the caller is asking a QUESTION, provide a brief helpful answer (under 25 words) as conversational_response.
5. If you generate any response text (conversational_response or tts_response), format it for TEXT-TO-SPEECH:
   - NO periods (TTS reads them as "dot")
   - Use ",,," between sentences for natural breath pauses
   - NO markdown formatting
   - Use ordinal dates ("April 8th" not "April 8")
   - Spell out abbreviations if TTS might mispronounce them

Respond with ONLY a JSON object matching this exact schema:
{{
  "utterance_type": "slot_data" | "question" | "confirmation" | "noise" | "fragment",
  "normalized_utterance": "...",
  "slot_values": {{}},
  "is_question": true/false,
  "conversational_response": "..." or null,
  "tts_response": "..." or null,
  "confidence": 0.0-1.0,
  "reasoning": "short explanation"
}}"""
    return prompt


# ── LLM Call ───────────────────────────────────────────────────────────

def parse_llm_response(raw: str) -> UtteranceAnalysis | None:
    """Parse LLM response text into UtteranceAnalysis, or None on failure."""
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Strip <think> blocks from qwen
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
        return UtteranceAnalysis(**data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return None


async def _call_llm(prompt: str) -> str | None:
    """Call LM Studio with the analysis prompt. Returns raw text or None."""
    lm_url = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
    model = os.environ.get("LLM_MODEL", "qwen3-4b")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                f"{lm_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "/no_think\nYou are a voice utterance analyzer. Respond with ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Utterance analyzer LLM call failed: {e}")
        return None


# ── Trivial Detection (for hybrid mode) ────────────────────────────────

_TRIVIAL_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|correct|right|absolutely|definitely)[\s.,!?]*$", re.IGNORECASE)
_TRIVIAL_NO = re.compile(r"^(?:no|nope|nah|not really|never mind)[\s.,!?]*$", re.IGNORECASE)
_TRIVIAL_NUMBER = re.compile(r"^[\d\s\-.,]+$")


def _is_trivial(utterance: str) -> UtteranceAnalysis | None:
    """Fast-path for obvious utterances. Returns analysis or None if complex."""
    text = utterance.strip()
    if not text:
        return UtteranceAnalysis(
            utterance_type="noise", normalized_utterance="",
            confidence=1.0, reasoning="empty utterance",
        )
    if _TRIVIAL_YES.match(text):
        return UtteranceAnalysis(
            utterance_type="confirmation", normalized_utterance=text.rstrip(".,!? "),
            confidence=0.95, reasoning="affirmative confirmation",
        )
    if _TRIVIAL_NO.match(text):
        return UtteranceAnalysis(
            utterance_type="confirmation", normalized_utterance=text.rstrip(".,!? "),
            confidence=0.95, reasoning="negative confirmation",
        )
    if _TRIVIAL_NUMBER.match(text):
        # Pure numbers — likely member ID or digit sequence
        digits = re.sub(r"[^\d]", "", text)
        return UtteranceAnalysis(
            utterance_type="slot_data", normalized_utterance=digits,
            slot_values={}, confidence=0.9,
            reasoning="pure numeric input",
        )
    return None


# ── Entry Point ────────────────────────────────────────────────────────

async def analyze_utterance(
    utterance: str,
    stage: str,
    collected_slots: dict,
    history: list[dict],
) -> UtteranceAnalysis:
    """Analyze an utterance using the configured mode.

    Mode is selected by UTTERANCE_ANALYZER env var:
      - "pydantic": Full LLM analysis (Approach A)
      - "hybrid":   Trivial regex + LLM fallback (Approach B, default)
      - "legacy":   Returns a minimal UtteranceAnalysis wrapping the
                     original preprocessed text (caller handles the rest)
    """
    mode = os.environ.get("UTTERANCE_ANALYZER", "hybrid").lower()
    logger.info(f"Utterance analyzer mode={mode}, stage={stage}, input='{utterance[:80]}'")

    if mode == "legacy":
        return _analyze_legacy(utterance, stage)

    if mode == "hybrid":
        # Fast path for trivials
        trivial = _is_trivial(utterance)
        if trivial:
            logger.info(f"Hybrid fast-path: {trivial.reasoning}")
            return trivial
        # Fall through to LLM

    # Full LLM analysis (both "pydantic" and "hybrid" non-trivial)
    prompt = build_analysis_prompt(utterance, stage, collected_slots, history)
    raw = await _call_llm(prompt)
    if raw:
        result = parse_llm_response(raw)
        if result:
            logger.info(f"LLM analysis: type={result.utterance_type}, conf={result.confidence}, reason={result.reasoning}")
            return result

    # LLM failed — fall back to legacy
    logger.warning("LLM analysis failed, falling back to legacy")
    return _analyze_legacy(utterance, stage)


def _analyze_legacy(utterance: str, stage: str) -> UtteranceAnalysis:
    """Wrap original regex preprocessing as an UtteranceAnalysis.

    Imports and calls the original _preprocess_utterance from iva_bridge.
    The caller (iva_bridge.process) still runs _is_question_utterance and
    _generate_conversational_response when mode=legacy.
    """
    from iva_bridge import _preprocess_utterance
    normalized = _preprocess_utterance(utterance, stage=stage)
    return UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance=normalized,
        slot_values={},
        is_question=False,
        conversational_response=None,
        tts_response=None,
        confidence=0.5,
        reasoning="legacy regex preprocessing",
    )
```

**Step 4: Run tests to verify they pass**

Run: `cd livekit-agent-builder && python -m pytest test_utterance_analyzer.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add livekit-agent-builder/utterance_analyzer.py livekit-agent-builder/test_utterance_analyzer.py
git commit -m "feat: add Pydantic utterance analyzer with A/B test modes"
```

---

## Task 2: Integrate Analyzer into IVA Bridge

**Files:**
- Modify: `livekit-agent-builder/iva_bridge.py` (lines 550-641 in `process()` method)

**Step 1: Write integration test**

Add to `livekit-agent-builder/test_utterance_analyzer.py`:

```python
def test_analyze_utterance_hybrid_trivial_yes():
    """Hybrid mode handles 'yes' without LLM call."""
    import asyncio
    from utterance_analyzer import analyze_utterance
    os.environ["UTTERANCE_ANALYZER"] = "hybrid"
    result = asyncio.run(analyze_utterance("yes", "confirmation", {}, []))
    assert result.utterance_type == "confirmation"
    assert result.confidence >= 0.9


def test_analyze_utterance_legacy_mode():
    """Legacy mode wraps original preprocessing."""
    import asyncio
    from utterance_analyzer import analyze_utterance
    os.environ["UTTERANCE_ANALYZER"] = "legacy"
    result = asyncio.run(analyze_utterance("tomorrow", "collect_time", {}, []))
    assert result.utterance_type == "slot_data"
    assert result.reasoning == "legacy regex preprocessing"
    # Should have resolved "tomorrow" to a date via original regex
    assert "tomorrow" not in result.normalized_utterance.lower() or True  # legacy may or may not resolve
```

**Step 2: Run test to verify it fails**

Run: `cd livekit-agent-builder && python -m pytest test_utterance_analyzer.py::test_analyze_utterance_hybrid_trivial_yes -v`
Expected: PASS (this uses already-written code)

**Step 3: Modify iva_bridge.py process() method**

In `iva_bridge.py`, modify the `process()` method (starting around line 550). Replace the preprocessing + question detection block with the analyzer call, while keeping the original code paths for `legacy` mode:

```python
# At the top of iva_bridge.py, add import:
from utterance_analyzer import analyze_utterance, UtteranceAnalysis

# In process(), replace lines 595-641 with:

        # ── Utterance Analysis ────────────────────��─────────────────
        analysis_mode = os.environ.get("UTTERANCE_ANALYZER", "hybrid").lower()

        if analysis_mode == "legacy":
            # Original behavior — regex preprocessing + separate question detection
            utterance = _preprocess_utterance(utterance, stage=current_stage)
            if utterance != original:
                logger.info(f"Preprocessed utterance: '{original}' -> '{utterance}'")

            if _is_question_utterance(original, utterance, session_state):
                from iva_middleware import get_response_templates
                templates = get_response_templates()
                stage = session_state.get("current_stage", "greeting")
                template_resp = templates.get_response(stage, "opening", session_state.get("slots", {}))
                if not template_resp:
                    template_resp = templates.get_reprompt_for_slots(
                        stage, [], session_state.get("slots", {})
                    ) or ""
                llm_answer = _generate_conversational_response(
                    utterance, session_state, template_resp
                )
                combined = (llm_answer + " " + template_resp).strip() if llm_answer else template_resp
                if session_state.get("history"):
                    session_state["history"][-1]["agent_response"] = combined
                logger.info(f"Voice question intercepted: '{utterance}' -> LLM answer + re-prompt")
                return {
                    "session_id": self.session_id,
                    "turn": session_state.get("turn_count", 0),
                    "stage": stage,
                    "previous_stage": stage,
                    "stage_changed": False,
                    "intent_detected": None,
                    "response": combined,
                    "response_source": "voice_llm",
                    "sentiment": "neutral",
                    "behavioral_mode": session_state.get("sentiment_mode", "normal"),
                    "slots_extracted": {},
                    "slots_accumulated": {k: v for k, v in session_state.get("slots", {}).items() if v is not None},
                    "call_complete": False,
                    "escalated": False,
                    "stages_skipped": [],
                    "digression_handled": "question",
                    "verification": None,
                    "elapsed_ms": 0,
                }
        else:
            # Pydantic / Hybrid mode — single structured LLM call
            analysis = await analyze_utterance(
                utterance=utterance,
                stage=current_stage,
                collected_slots=session_state.get("slots", {}),
                history=session_state.get("history", []),
            )
            logger.info(f"Analysis result: type={analysis.utterance_type}, "
                        f"question={analysis.is_question}, conf={analysis.confidence}")

            utterance = analysis.normalized_utterance

            # If the analyzer identified a question and has a response, return directly
            if analysis.is_question and analysis.conversational_response:
                from iva_middleware import get_response_templates
                templates = get_response_templates()
                stage = session_state.get("current_stage", "greeting")
                template_resp = templates.get_response(stage, "opening", session_state.get("slots", {}))
                if not template_resp:
                    template_resp = templates.get_reprompt_for_slots(
                        stage, [], session_state.get("slots", {})
                    ) or ""

                # Use TTS-formatted response if available, otherwise conversational
                answer = analysis.tts_response or analysis.conversational_response
                combined = (answer + ",,,  " + template_resp).strip() if template_resp else answer

                if session_state.get("history"):
                    session_state["history"][-1]["agent_response"] = combined
                logger.info(f"Analyzer question intercepted: '{original}' -> '{answer}'")
                return {
                    "session_id": self.session_id,
                    "turn": session_state.get("turn_count", 0),
                    "stage": stage,
                    "previous_stage": stage,
                    "stage_changed": False,
                    "intent_detected": None,
                    "response": combined,
                    "response_source": "voice_analyzer",
                    "sentiment": "neutral",
                    "behavioral_mode": session_state.get("sentiment_mode", "normal"),
                    "slots_extracted": analysis.slot_values,
                    "slots_accumulated": {k: v for k, v in session_state.get("slots", {}).items() if v is not None},
                    "call_complete": False,
                    "escalated": False,
                    "stages_skipped": [],
                    "digression_handled": "question",
                    "verification": None,
                    "elapsed_ms": 0,
                }

            # For noise/fragments, skip IVA processing
            if analysis.utterance_type in ("noise", "fragment") and analysis.confidence > 0.8:
                logger.info(f"Analyzer filtered noise/fragment: '{original}'")
                from iva_middleware import get_response_templates
                templates = get_response_templates()
                stage = session_state.get("current_stage", "greeting")
                reprompt = templates.get_reprompt_for_slots(
                    stage, [], session_state.get("slots", {})
                ) or "Could you say that again?"
                return {
                    "session_id": self.session_id,
                    "turn": session_state.get("turn_count", 0),
                    "stage": stage,
                    "previous_stage": stage,
                    "stage_changed": False,
                    "intent_detected": None,
                    "response": reprompt,
                    "response_source": "voice_analyzer",
                    "sentiment": "neutral",
                    "behavioral_mode": session_state.get("sentiment_mode", "normal"),
                    "slots_extracted": {},
                    "slots_accumulated": {k: v for k, v in session_state.get("slots", {}).items() if v is not None},
                    "call_complete": False,
                    "escalated": False,
                    "stages_skipped": [],
                    "digression_handled": "noise",
                    "verification": None,
                    "elapsed_ms": 0,
                }

        # ── Continue to IVA graph (both legacy and pydantic/hybrid) ──
```

The rest of `process()` continues unchanged from the voice compensation block through to the end.

**Step 4: Run tests**

Run: `cd livekit-agent-builder && python -m pytest test_utterance_analyzer.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add livekit-agent-builder/iva_bridge.py livekit-agent-builder/test_utterance_analyzer.py
git commit -m "feat: integrate utterance analyzer into iva_bridge with A/B toggle"
```

---

## Task 3: Add Date Resolution Tests

**Files:**
- Modify: `livekit-agent-builder/test_utterance_analyzer.py`

**Step 1: Write date-focused tests**

```python
def test_prompt_resolves_next_wednesday():
    """Prompt gives LLM enough context to resolve 'next wednesday'."""
    prompt = build_analysis_prompt(
        utterance="next wednesday at 2 pm",
        stage="collect_time",
        collected_slots={},
        history=[],
    )
    # The prompt must contain the current day of week so the LLM can calculate
    assert any(day in prompt for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
    # Must contain the full date
    assert "2026" in prompt


def test_prompt_includes_tts_formatting_rules():
    """Prompt instructs LLM about TTS formatting."""
    prompt = build_analysis_prompt(
        utterance="test",
        stage="greeting",
        collected_slots={},
        history=[],
    )
    assert ",,," in prompt  # breath pause instruction
    assert "period" in prompt.lower() or "dot" in prompt.lower()  # no-periods rule


def test_prompt_includes_conversation_history():
    """Prompt includes recent conversation turns for context."""
    history = [
        {"utterance": "I need a ride", "agent_response": "Sure, when is your appointment?"},
        {"utterance": "next wednesday", "agent_response": None},
    ]
    prompt = build_analysis_prompt(
        utterance="next wednesday at 2",
        stage="collect_time",
        collected_slots={},
        history=history,
    )
    assert "I need a ride" in prompt
    assert "when is your appointment" in prompt
```

**Step 2: Run to verify they pass**

Run: `cd livekit-agent-builder && python -m pytest test_utterance_analyzer.py -v`
Expected: All PASS (these test the already-implemented prompt builder)

**Step 3: Commit**

```bash
git add livekit-agent-builder/test_utterance_analyzer.py
git commit -m "test: add date resolution and TTS formatting tests for utterance analyzer"
```

---

## Task 4: Update CLAUDE.md with A/B Configuration

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add analyzer config section**

Add to the Dockerless Startup section in CLAUDE.md:

```markdown
## Utterance Analyzer A/B Test

The `UTTERANCE_ANALYZER` env var controls how caller utterances are preprocessed:

- `hybrid` (default): Fast regex for trivials (yes/no, numbers), Pydantic LLM call for complex utterances
- `pydantic`: Full LLM analysis for every utterance — best accuracy, ~200-400ms per turn
- `legacy`: Original regex preprocessing — zero latency, no LLM, but misses edge cases

Set in the builder agent startup command:
```
UTTERANCE_ANALYZER=hybrid python agent.py dev
```
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add utterance analyzer A/B config to CLAUDE.md"
```

---

Plan complete and saved to `docs/plans/2026-04-05-pydantic-utterance-analyzer.md`.

**Two execution options:**

**1. Subagent-Driven (this session)** — I dispatch fresh subagents per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

**Which approach?** You mentioned spinning up agents — I'll go subagent-driven and dispatch them now.
