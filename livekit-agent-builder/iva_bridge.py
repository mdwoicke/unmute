"""Bridge between LiveKit voice agent and the IVA (Interactive Voice Agent) graph.

Manages per-room IVA sessions, mirroring the plugin-mode session management
from dynamic-skills-agent/web_app.py (lines 1818-2018).

Includes voice-specific preprocessing: STT outputs number words
("one, six, three, two") which must be converted to digits ("1632")
for the IVA's slot extraction regexes.
"""

import asyncio
import logging
import os
import re
import sys
import time
import uuid

logger = logging.getLogger(__name__)

# ── Voice-aware IVA integration ────────────────────────────────────────
#
# The IVA's nemt_intake skill already calls an LLM for intent/slot extraction.
# Instead of adding a separate LLM call for voice normalization (which adds
# latency), we inject voice-awareness into the EXISTING LLM call by
# monkey-patching nemt_intake.execute to add voice context to the prompt hint.
#
# This means:
# - Zero extra LLM calls (reuses the existing nemt_intake classification)
# - Fully dynamic (the LLM handles numbers, times, addresses, dates, etc.)
# - No hardcoded rules or lists
# - No additional latency
#
# We also apply minimal fast preprocessing (smart regex for trailing
# punctuation) since the IVA's regex fallbacks run on the raw utterance.

_VOICE_HINT = (
    "VOICE INPUT: This utterance comes from speech-to-text and may contain "
    "spoken numbers as words or STT artifacts. CRITICAL RULES: "
    "1) ALL numeric slot values MUST be digits, never words "
    "(member_id: '1632' not 'one six three two', "
    "number_of_companions: 1 not 'one', appointment_time: '9:00 AM' not 'nine'). "
    "2) 'My son' or 'just my son' when asked about companions means "
    "number_of_companions=1 and companion_relationship='son'. "
    "3) Interpret the caller's meaning, not literal words — "
    "'just one' = 1, 'a couple' = 2, 'no one' = 0."
)

_voice_patched = False


def _patch_nemt_for_voice():
    """Monkey-patch nemt_intake.execute to inject voice context into the prompt.

    This adds voice-awareness to the EXISTING LLM call — zero extra latency.
    """
    global _voice_patched
    if _voice_patched:
        return
    try:
        import iva_graph
        original_execute = iva_graph._nemt_mod.execute

        def _voice_aware_execute(utterance=None, **kwargs):
            # Prepend voice hint to the next_prompt_hint parameter
            hint = kwargs.get("next_prompt_hint", "") or ""
            kwargs["next_prompt_hint"] = _VOICE_HINT + "\n" + hint if hint else _VOICE_HINT
            return original_execute(utterance=utterance, **kwargs)

        iva_graph._nemt_mod.execute = _voice_aware_execute
        _voice_patched = True
        logger.info("Patched nemt_intake with voice-awareness hint")
    except Exception as e:
        logger.warning(f"Failed to patch nemt_intake for voice: {e}")


_WORD_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10",
}


def _validate_extracted_slots(extracted: dict, utterance: str) -> dict:
    """Validate extracted slot values — reject questions/nonsense stored as data.

    Uses fast heuristics (no LLM call) to detect obviously invalid values.
    Returns a cleaned copy of extracted with invalid values set to None.
    """
    cleaned = dict(extracted)

    # Patterns that indicate a question, not a data value
    _QUESTION_WORDS = re.compile(
        r'^(where|what|how|why|when|who|can|could|do|does|is|are|should|would)\b',
        re.IGNORECASE,
    )
    _HAS_QUESTION = re.compile(r'\?')

    # Slots that should contain addresses
    _ADDRESS_SLOTS = {"pickup_address", "dropoff_address"}
    # Slots that should contain numbers
    _NUMERIC_SLOTS = {"member_id", "number_of_companions", "gate_code"}
    # Slots that should contain dates/times
    _TIME_SLOTS = {"appointment_date", "appointment_time", "appointment_datetime_local",
                   "return_pickup_time"}

    for slot, value in extracted.items():
        if value is None:
            continue
        val_str = str(value).strip()
        if not val_str:
            continue

        # Universal check: if the value looks like a question, it's invalid
        if _QUESTION_WORDS.match(val_str) or _HAS_QUESTION.search(val_str):
            logger.info(f"Slot validation: '{slot}' = '{val_str}' looks like a question")
            cleaned[slot] = None
            continue

        # Address slots: should contain a number or known address word
        if slot in _ADDRESS_SLOTS:
            has_number = bool(re.search(r'\d', val_str))
            has_address_word = bool(re.search(
                r'\b(street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd|lane|ln|'
                r'way|court|ct|circle|place|pl|highway|hwy|center|hospital|clinic)\b',
                val_str, re.IGNORECASE,
            ))
            if not has_number and not has_address_word and len(val_str) < 10:
                logger.info(f"Slot validation: '{slot}' = '{val_str}' doesn't look like an address")
                cleaned[slot] = None
                continue

        # Numeric slots: should be numeric
        if slot in _NUMERIC_SLOTS:
            if not re.search(r'\d', val_str):
                logger.info(f"Slot validation: '{slot}' = '{val_str}' has no digits")
                cleaned[slot] = None
                continue

    return cleaned


def _generate_conversational_response(
    utterance: str, session_state: dict, template_response: str
) -> str | None:
    """Use LLM to answer a caller's question when the IVA has no natural response.

    Only called for edge cases — questions, clarifications, or conversational
    turns that the IVA's template system can't handle. Returns None if the
    utterance doesn't need an LLM response (e.g., it's just noise/fragments).
    """
    import httpx

    # Don't waste an LLM call on very short fragments
    if len(utterance.split()) < 3:
        return None

    stage = session_state.get("current_stage", "greeting")
    collected = {k: v for k, v in session_state.get("slots", {}).items() if v is not None}

    # Map stage to what info is being asked for
    _STAGE_INFO = {
        "verification": "their member ID, which is on their insurance card or member welcome letter",
        "collect_pickup": "their pickup address",
        "collect_dropoff": "their destination address",
        "collect_time": "their appointment date and time",
        "mobility": "whether they need mobility assistance like a wheelchair",
        "companion": "how many companions are traveling with them",
        "return_ride": "whether they need a return ride",
        "special_instructions": "any special instructions for the driver",
        "confirmation": "confirmation of their booking details",
    }
    stage_info = _STAGE_INFO.get(stage, "the requested information")

    prompt = (
        f"You are a friendly NEMT (medical transportation) phone agent. "
        f"You just asked the caller for {stage_info}. "
        f"The caller responded: \"{utterance}\"\n\n"
        f"They are asking a question or need clarification. "
        f"Give a direct, helpful answer to their question in 1 sentence. "
        f"For example if they ask 'where can I find my member ID' say "
        f"'Your member ID can be found on your insurance card or the welcome letter you received.' "
        f"Be warm and conversational. Do NOT ask them for information — just answer their question. "
        f"Do NOT use markdown. Keep it under 25 words. Return ONLY the answer, nothing else."
    )

    try:
        lm_url = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
        # Use LLM_MODEL (same as nemt_intake) — this is the model actually loaded
        model = os.environ.get("LLM_MODEL", "qwen3-4b")
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                f"{lm_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "/no_think"},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 80,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean up — remove quotes, markdown
            answer = answer.strip('"\'')
            for char in "*_`":
                answer = answer.replace(char, "")
            if answer and len(answer) > 5:
                return answer
    except Exception as e:
        logger.warning(f"LLM fallback failed: {e}")
    return None


def _preprocess_utterance(utterance: str) -> str:
    """Fast preprocessing for voice utterances.

    1. Strip trailing sentence punctuation (not abbreviation dots)
    2. Convert short all-number-word utterances to digits
       ("One" -> "1", "Just one" -> "Just 1")

    The voice-aware LLM hint handles complex cases. This handles
    the simple cases where the IVA's regex/slot code needs digits.
    """
    text = utterance.strip()
    if not text:
        return text

    # Strip trailing sentence punctuation, but not abbreviation dots
    if text[-1:] in '.!?,;' and not re.search(r'\.[a-zA-Z]\.$', text):
        text = text[:-1]

    # Convert number words to digits in the utterance.
    # "one" -> "1", "My son and one companion" -> "My son and 1 companion"
    words = text.split()
    converted = []
    for w in words:
        key = w.lower().rstrip('.,!?;')
        if key in _WORD_DIGITS:
            suffix = w[len(key):]
            converted.append(_WORD_DIGITS[key] + suffix)
        else:
            converted.append(w)
    text = " ".join(converted)

    # Collapse separated digit sequences: "1, 4, 6, 2" -> "1462"
    # This handles STT outputting "One, four, six, two" for member IDs
    text = re.sub(
        r'\b(\d)(?:[,\s]+(\d))+\b',
        lambda m: re.sub(r'[,\s]+', '', m.group(0)),
        text,
    )

    return text

# Add IVA source to sys.path so imports work
IVA_SOURCE_PATH = os.environ.get("IVA_SOURCE_PATH", "/app/iva-source")
if IVA_SOURCE_PATH not in sys.path:
    sys.path.insert(0, IVA_SOURCE_PATH)

# IVA imports (deferred to allow path setup)
_iva_initialized = False


def _init_iva_imports():
    """Lazily import IVA modules after sys.path is configured."""
    global _iva_initialized
    if _iva_initialized:
        return
    # Importing these modules triggers graph compilation in iva_graph,
    # so we only do it once.
    try:
        import iva_graph  # noqa: F401
        _iva_initialized = True
        logger.info("IVA graph modules initialized successfully")
        # Inject voice-awareness into nemt_intake's existing LLM call
        _patch_nemt_for_voice()
    except Exception as e:
        logger.error(f"Failed to initialize IVA graph: {e}")
        raise


class IVABridge:
    """Manages a single IVA session for a LiveKit room."""

    def __init__(self):
        self.session_id: str | None = None
        self.session_state: dict | None = None
        self._last_turn_was_fragment: bool = False

    def init_session(self) -> str:
        """Create a fresh IVA session and return the greeting text.

        Returns:
            The greeting text to speak to the caller.
        """
        _init_iva_imports()

        from iva_state import empty_slots
        from iva_persistence import save_session_meta
        from iva_middleware import get_response_templates

        self.session_id = str(uuid.uuid4())
        self.session_state = {
            "current_stage": "greeting",
            "slots": empty_slots(),
            "turn_count": 0,
            "sentiment_history": [],
            "sentiment_mode": "normal",
            "conversation_stack": [],
            "primary_intent": None,
            "stage_attempts": {},
            "escalation": {"triggered": False, "reason": None},
            "rules_applied": [],
            "history": [],
            "created": time.time(),
        }

        save_session_meta(self.session_id, stage="greeting", turn_count=0)

        templates = get_response_templates()
        greeting = templates.get_response("greeting", "opening")

        # Seed history with the greeting so the first turn has agent context
        if greeting:
            self.session_state["history"].append({
                "turn": 0,
                "stage": "greeting",
                "utterance": "",
                "intent": None,
                "slots_extracted": {},
                "sentiment": "neutral",
                "agent_response": greeting,
            })

        logger.info(f"IVA session initialized: {self.session_id}")
        return greeting or ""

    async def process(self, utterance: str) -> dict:
        """Process a caller utterance through the IVA graph.

        Args:
            utterance: The transcribed text from STT.

        Returns:
            Result dict with stage, response, slots, sentiment, etc.
        """
        _init_iva_imports()

        from iva_graph import process_turn
        from iva_persistence import save_session_meta, recover_session_state

        if not self.session_id or not self.session_state:
            raise RuntimeError("No active IVA session. Call init_session() first.")

        session_state = self.session_state

        # Minimal voice preprocessing (trailing punctuation only —
        # the heavy lifting is done by the voice-aware nemt_intake LLM)
        original = utterance
        utterance = _preprocess_utterance(utterance)
        if utterance != original:
            logger.info(f"Preprocessed utterance: '{original}' -> '{utterance}'")

        # Voice interception: if the utterance is clearly a question (not a
        # slot answer), don't send it to the IVA at all — answer it with
        # the LLM and re-prompt with the current stage's template question.
        # This prevents the IVA from storing "Where can I be picked up from?"
        # as a pickup_address.
        _Q_PATTERN = re.compile(
            r'(\?$|^(where|what|how|why|when|who|can|could|do|does|is|are|should|would)\b)',
            re.IGNORECASE
        )
        if _Q_PATTERN.search(utterance):
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

            # Backfill into history for context
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

        # Voice compensation: if the previous turn was a wasted fragment
        # (no intent, no slots, stage unchanged), reset the stage_attempts
        # counter BEFORE this turn. This prevents STT fragments from
        # burning through max_stage_attempts (3) and causing premature
        # escalation. The reset must happen before process_turn because
        # the escalation check happens inside the graph.
        if self._last_turn_was_fragment:
            current_stage = session_state.get("current_stage", "greeting")
            attempts = session_state.get("stage_attempts", {})
            if current_stage in attempts and attempts[current_stage] > 0:
                attempts[current_stage] = max(0, attempts[current_stage] - 1)
                logger.info(f"Voice compensation: reset stage_attempts['{current_stage}'] "
                           f"to {attempts[current_stage]} (previous turn was fragment)")
            self._last_turn_was_fragment = False

        # Run the synchronous graph in a thread
        _pstart = time.time()
        graph_result = await asyncio.to_thread(
            process_turn, self.session_id, utterance, session_state
        )
        _pelapsed = round((time.time() - _pstart) * 1000, 1)
        logger.info(f"IVA process_turn completed in {_pelapsed}ms")

        # If the IVA returned a template re-prompt with no progress, and the
        # user's utterance looks like a question (contains "?", starts with
        # a question word, or is conversational), use the LLM to generate a
        # helpful answer before the template re-ask.
        # Only trigger for actual questions — NOT for slot-providing utterances
        # that the IVA just failed to parse (numbers, addresses, etc.)
        response_src = graph_result.get("response_source", "template")
        no_progress = (
            not graph_result.get("stage_changed", False)
            and not any(v is not None for v in graph_result.get("extracted_slots", {}).values())
            and graph_result.get("intent") is None
        )
        _QUESTION_PATTERN = re.compile(
            r'(\?|^(where|what|how|why|when|who|can|could|do|does|is|are|should|would)\b)',
            re.IGNORECASE
        )
        is_question = bool(_QUESTION_PATTERN.search(utterance)) if utterance else False
        if no_progress and response_src == "template" and is_question:
            llm_answer = _generate_conversational_response(
                utterance, session_state, graph_result.get("response", "")
            )
            if llm_answer:
                graph_result["response"] = llm_answer + " " + graph_result.get("response", "")
                logger.info(f"Voice LLM fallback: '{llm_answer[:80]}...'")

        # Voice slot validation: the nemt_intake LLM sometimes extracts
        # questions or nonsense as slot values (e.g., "Where can I be picked up?"
        # stored as pickup_address). Validate both extracted_slots and the
        # merged slots dict — remove invalid values so the IVA re-asks.
        for slots_key in ("extracted_slots", "slots"):
            slots_dict = graph_result.get(slots_key, {})
            if slots_dict and any(v is not None for v in slots_dict.values()):
                cleaned = _validate_extracted_slots(slots_dict, utterance)
                removed = {k: v for k, v in slots_dict.items()
                           if v is not None and cleaned.get(k) is None}
                if removed:
                    logger.info(f"Voice validation removed bad {slots_key}: {removed}")
                    graph_result[slots_key] = cleaned
                    if slots_key == "slots":
                        # Prevent stage advancement if we removed key slots
                        graph_result["stage_changed"] = False

        # Update session state from graph result (same key-by-key logic as web_app.py lines 1914-1924)
        for key in ("sentiment_history", "stage_attempts", "history", "primary_intent"):
            if key in graph_result:
                session_state[key] = graph_result[key]
        session_state["current_stage"] = graph_result.get("stage", session_state["current_stage"])
        session_state["turn_count"] = graph_result.get("turn_count", session_state["turn_count"])
        session_state["sentiment_mode"] = graph_result.get("behavioral_mode", session_state["sentiment_mode"])
        session_state["escalation"] = graph_result.get("escalation", session_state["escalation"])
        for k, v in graph_result.get("slots", {}).items():
            if v is not None:
                session_state["slots"][k] = v

        # Backfill agent_response into the last history entry so the NEXT
        # turn's classify_node has full conversation context. Without this,
        # the LLM only sees caller utterances and can't understand references
        # like "Where can I find that?" (it doesn't know what the agent asked).
        response_text = graph_result.get("response", "")
        if response_text and session_state.get("history"):
            session_state["history"][-1]["agent_response"] = response_text

        # Voice compensation: track whether this turn was a wasted fragment
        # so we can reset stage_attempts BEFORE the next process_turn call.
        no_intent = graph_result.get("intent") is None
        no_slots = not any(v is not None for v in graph_result.get("extracted_slots", {}).values())
        stage_unchanged = not graph_result.get("stage_changed", False)
        self._last_turn_was_fragment = no_intent and no_slots and stage_unchanged

        is_ended = graph_result.get("call_complete") or graph_result.get("escalation", {}).get("triggered")
        save_session_meta(
            self.session_id,
            stage=session_state["current_stage"],
            turn_count=session_state["turn_count"],
            is_ended=is_ended,
        )

        # Emit observability metrics
        try:
            from iva_observability import log_turn_metrics
            log_turn_metrics(self.session_id, graph_result, _pelapsed)
        except ImportError:
            pass  # observability module is optional

        # Load caller profile on first member_id detection
        member_id = session_state["slots"].get("member_id")
        if member_id and not session_state.get("_profile_loaded"):
            from iva_profiles import get_caller_profile
            profile = get_caller_profile(member_id)
            if profile:
                for field in ("mobility_type", "mobility_assistance_needed",
                              "language_preference", "service_animal",
                              "gate_code", "preferred_pickup_spot"):
                    prof_val = profile.get(field)
                    if prof_val is not None and session_state["slots"].get(field) is None:
                        session_state["slots"][field] = prof_val
                session_state["_profile_loaded"] = True
                logger.info(f"IVA profile loaded for member_id={member_id}, "
                            f"call_count={profile.get('call_count', 0)}")

        # Run parallel verification subagents
        from iva_subagents import run_verification_tasks
        verification_results = await run_verification_tasks(session_state)

        # Save caller profile on completed calls
        if is_ended and graph_result.get("call_complete"):
            from iva_profiles import save_caller_profile
            await asyncio.to_thread(save_caller_profile, session_state["slots"], session_state.get("history"))

        # Build result dict matching the REST API / plugin envelope format
        result = {
            "session_id": self.session_id,
            "turn": graph_result.get("turn_count", 0),
            "stage": graph_result.get("stage"),
            "previous_stage": graph_result.get("previous_stage"),
            "stage_changed": graph_result.get("stage_changed", False),
            "intent_detected": graph_result.get("intent"),
            "response": graph_result.get("response", ""),
            "response_source": graph_result.get("response_source", "template"),
            "sentiment": graph_result.get("sentiment_history", ["neutral"])[-1] if graph_result.get("sentiment_history") else "neutral",
            "behavioral_mode": graph_result.get("behavioral_mode", "normal"),
            "sentiment_mode": graph_result.get("behavioral_mode", "normal"),
            "slots_extracted": {k: v for k, v in graph_result.get("extracted_slots", {}).items() if v is not None},
            "slots_accumulated": {k: v for k, v in session_state["slots"].items() if v is not None},
            "call_complete": graph_result.get("call_complete", False),
            "escalated": graph_result.get("escalation", {}).get("triggered", False),
            "stages_skipped": graph_result.get("stages_skipped", []),
            "digression_handled": graph_result.get("digression_handled"),
            "verification": verification_results if verification_results else None,
            "elapsed_ms": _pelapsed,
        }

        logger.info(f"IVA turn {result['turn']}: stage={result['stage']}, "
                     f"intent={result['intent_detected']}, "
                     f"call_complete={result['call_complete']}, "
                     f"escalated={result['escalated']}")

        return result
