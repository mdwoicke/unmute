"""Unit tests for utterance_analyzer module."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from utterance_analyzer import UtteranceAnalysis, build_analysis_prompt, parse_llm_response


def test_utterance_analysis_model_valid():
    """Pydantic model accepts well-formed data."""
    a = UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance="April 8th at 2 PM",
        slot_values={"appointment_date": "April 8th"},
        is_question=False,
        conversational_response=None,
        tts_response=None,
        confidence=0.95,
        reasoning="date provided",
    )
    assert a.utterance_type == "slot_data"
    assert a.confidence == 0.95


def test_utterance_analysis_model_rejects_bad_type():
    with pytest.raises(Exception):
        UtteranceAnalysis(
            utterance_type="invalid",
            normalized_utterance="x",
            slot_values={},
            confidence=0.5,
            reasoning="x",
        )


def test_build_analysis_prompt_includes_date():
    p = build_analysis_prompt("next wednesday", "collect_time", {}, [])
    assert "2026" in p
    assert any(
        d in p
        for d in [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
    )


def test_build_analysis_prompt_includes_stage():
    p = build_analysis_prompt(
        "123 Main St", "collect_pickup", {"member_id": "1234"}, []
    )
    assert "collect_pickup" in p


def test_parse_llm_response_valid_json():
    raw = '{"utterance_type":"slot_data","normalized_utterance":"April 8th","slot_values":{},"is_question":false,"conversational_response":null,"tts_response":null,"confidence":0.9,"reasoning":"date"}'
    r = parse_llm_response(raw)
    assert isinstance(r, UtteranceAnalysis)


def test_parse_llm_response_strips_markdown():
    raw = '```json\n{"utterance_type":"question","normalized_utterance":"where is my ID","slot_values":{},"is_question":true,"conversational_response":"On your insurance card","tts_response":"On your insurance card","confidence":0.85,"reasoning":"question"}\n```'
    r = parse_llm_response(raw)
    assert r.is_question is True


def test_parse_llm_response_returns_none_on_garbage():
    assert parse_llm_response("sorry I can't help") is None


def test_tts_response_strips_period():
    a = UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance="test",
        tts_response="Your ride is booked.",
        confidence=0.9,
        reasoning="test",
    )
    assert not a.tts_response.endswith(".")


def test_tts_response_strips_markdown():
    a = UtteranceAnalysis(
        utterance_type="slot_data",
        normalized_utterance="test",
        tts_response="Your **ride** is booked",
        confidence=0.9,
        reasoning="test",
    )
    assert "**" not in a.tts_response


def test_prompt_resolves_next_wednesday():
    """Prompt gives LLM enough context to resolve 'next wednesday'."""
    prompt = build_analysis_prompt("next wednesday at 2 pm", "collect_time", {}, [])
    # Must contain day of week so LLM can calculate
    assert any(d in prompt for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
    # Must contain full year
    assert "2026" in prompt


def test_prompt_includes_tts_formatting_rules():
    """Prompt instructs LLM about TTS formatting."""
    prompt = build_analysis_prompt("test", "greeting", {}, [])
    assert ",,," in prompt  # breath pause instruction
    assert "period" in prompt.lower() or "dot" in prompt.lower()  # no-periods rule


def test_prompt_includes_conversation_history():
    """Prompt includes recent conversation turns using iva_bridge history format."""
    history = [
        {"utterance": "I need a ride", "agent_response": "Sure, when is your appointment?"},
        {"utterance": "next wednesday", "agent_response": None},
    ]
    prompt = build_analysis_prompt("next wednesday at 2", "collect_time", {}, history)
    assert "I need a ride" in prompt
    assert "when is your appointment" in prompt


def test_prompt_includes_collected_slots():
    """Prompt shows already-collected slot values."""
    slots = {"member_id": "1234", "pickup_address": "123 Main St"}
    prompt = build_analysis_prompt("2 pm tomorrow", "collect_time", slots, [])
    assert "1234" in prompt
    assert "123 Main St" in prompt
