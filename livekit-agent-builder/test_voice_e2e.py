"""E2E test harness for the voice IVA bridge.

Tests the IVA bridge with voice-realistic utterances — number words,
questions, fragments, conversational language — to verify the voice
preprocessing and IVA integration work end-to-end.

Usage:
    docker exec unmute-livekit-agent-builder-1 python test_voice_e2e.py
"""

import asyncio
import json
import os
import sys
import time

# Ensure IVA source is on path
IVA_SOURCE_PATH = os.environ.get("IVA_SOURCE_PATH", "/app/iva-source")
if IVA_SOURCE_PATH not in sys.path:
    sys.path.insert(0, IVA_SOURCE_PATH)

from iva_bridge import IVABridge

# ── Test Scenarios ──────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "Happy path (text-clean)",
        "description": "Standard booking with clean text — baseline",
        "utterances": [
            "I need to book a ride",
            "My member ID is 44556677",
            "789 Oak Boulevard",
            "321 Hospital Lane",
            "April 5th at 2 PM",
            "No wheelchair needed",
            "Just me",
            "No return ride",
            "No special instructions",
            "Yes that's correct",
        ],
        "expect_complete": True,
    },
    {
        "name": "Voice number words",
        "description": "Member ID and numbers spoken as words",
        "utterances": [
            "I'd like to schedule a ride",
            "four, four, five, five, six, six, seven, seven",
            "789 Oak Boulevard",
            "321 Hospital Lane",
            "Tomorrow at two PM",
            "No I walk fine",
            "No just me",
            "No return ride",
            "Nothing special",
            "Yes confirmed",
        ],
        "expect_complete": True,
    },
    {
        "name": "Voice edge case questions",
        "description": "Caller asks questions mid-flow",
        "utterances": [
            "I need a ride please",
            "Where can I find my member ID?",
            "44556677",
            "123 Main Street",
            "What kind of places can I go to?",
            "456 Hospital Drive",
            "Next Tuesday at 9 a.m.",
            "No mobility needs",
            "One companion",
            "No return ride",
            "Nothing else",
            "Yes that's right",
        ],
        "expect_complete": True,
        "max_turns": 15,  # Extra turns for questions
    },
    {
        "name": "Terse voice responses",
        "description": "Very short answers typical of voice",
        "utterances": [
            "Book a ride",
            "88776655",
            "100 Main",
            "200 Medical Center",
            "Tomorrow ten AM",
            "No",
            "Alone",
            "No",
            "No",
            "Yes",
        ],
        "expect_complete": True,
    },
    {
        "name": "Companion edge case",
        "description": "Tests companion slot with voice-natural responses",
        "utterances": [
            "I need to book a ride",
            "44556677",
            "789 Oak Boulevard",
            "321 Hospital Lane",
            "April 5th at 2 PM",
            "No wheelchair needed",
            "My son is coming with me",
            "No return ride",
            "No special instructions",
            "Yes that's correct",
        ],
        "expect_complete": True,
    },
    {
        "name": "Questions at every stage",
        "description": "Caller asks a question before answering at each stage",
        "utterances": [
            "I need to book a ride",
            "Where can I find my member ID?",
            "44556677",
            "Where can I be picked up from?",
            "789 Oak Boulevard",
            "What kind of places can I go to?",
            "321 Hospital Lane",
            "When is the earliest I can go?",
            "April 5th at 2 PM",
            "What mobility options do you have?",
            "No wheelchair needed",
            "Can I bring someone?",
            "Just me",
            "Do I need a return ride?",
            "No return ride",
            "Is there anything else I should know?",
            "No special instructions",
            "Yes that's correct",
        ],
        "expect_complete": True,
        "max_turns": 25,
    },
    {
        "name": "Question as pickup address (regression)",
        "description": "Ensures 'Where can I be picked up from?' is NOT stored as address",
        "utterances": [
            "I need a ride",
            "44556677",
            "Where can I be picked up from?",
            "123 Main Street",
            "456 Hospital Drive",
            "Tomorrow at 9 a.m.",
            "No",
            "Just me",
            "No",
            "Nothing",
            "Yes",
        ],
        "expect_complete": True,
        "max_turns": 15,
    },
]


# ── Test Runner ─────────────────────────────────────────────────────────

async def run_scenario(scenario: dict) -> dict:
    """Run a single scenario through the IVA bridge."""
    name = scenario["name"]
    utterances = scenario["utterances"]
    expect_complete = scenario.get("expect_complete", True)
    max_turns = scenario.get("max_turns", len(utterances) + 3)

    bridge = IVABridge()
    greeting = bridge.init_session()

    turns = []
    turns.append({
        "turn": 0,
        "utterance": "(greeting)",
        "response": greeting,
        "stage": "greeting",
    })

    escalated = False
    completed = False

    for i, utterance in enumerate(utterances):
        if escalated or completed:
            break
        if i >= max_turns:
            break

        try:
            result = await bridge.process(utterance)
        except Exception as e:
            turns.append({
                "turn": i + 1,
                "utterance": utterance,
                "error": str(e),
            })
            break

        stage = result.get("stage", "?")
        response = result.get("response", "")
        escalated = result.get("escalated", False)
        completed = result.get("call_complete", False)

        turns.append({
            "turn": i + 1,
            "utterance": utterance,
            "stage": stage,
            "response": response[:100],
            "slots_extracted": result.get("slots_extracted", {}),
            "escalated": escalated,
            "call_complete": completed,
            "response_source": result.get("response_source", "?"),
        })

    # Evaluate
    issues = []
    if expect_complete and not completed and not escalated:
        issues.append("INCOMPLETE: Call did not complete")
    if expect_complete and escalated:
        last_turn = turns[-1] if turns else {}
        issues.append(f"ESCALATED at stage={last_turn.get('stage')} turn={last_turn.get('turn')}")
    if not greeting:
        issues.append("NO GREETING")

    # Check for repeated re-prompts (same response 3+ times)
    responses = [t.get("response", "") for t in turns[1:]]
    for resp in set(responses):
        if resp and responses.count(resp) >= 3:
            issues.append(f"REPEATED 3x: '{resp[:60]}...'")

    return {
        "name": name,
        "turns": len(turns) - 1,
        "completed": completed,
        "escalated": escalated,
        "issues": issues,
        "pass": len(issues) == 0,
        "turn_details": turns,
    }


async def run_all():
    """Run all scenarios and print results."""
    print("=" * 70)
    print("VOICE IVA E2E TEST HARNESS")
    print("=" * 70)
    print()

    results = []
    for scenario in SCENARIOS:
        print(f"Running: {scenario['name']}...")
        start = time.time()
        result = await run_scenario(scenario)
        elapsed = round(time.time() - start, 1)
        results.append(result)

        status = "PASS" if result["pass"] else "FAIL"
        print(f"  [{status}] {result['turns']} turns, {elapsed}s", end="")
        if result["completed"]:
            print(" (completed)", end="")
        if result["escalated"]:
            print(" (ESCALATED)", end="")
        print()
        if result["issues"]:
            for issue in result["issues"]:
                print(f"    - {issue}")
        print()

    # Summary
    print("=" * 70)
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print(f"RESULTS: {passed}/{total} passed")
    print("=" * 70)

    # Print detailed turn log for failures
    for result in results:
        if not result["pass"]:
            print(f"\n--- FAILED: {result['name']} ---")
            for turn in result["turn_details"]:
                utt = turn.get("utterance", "")
                stage = turn.get("stage", "")
                resp = turn.get("response", "")
                slots = turn.get("slots_extracted", {})
                src = turn.get("response_source", "")
                err = turn.get("error", "")
                print(f"  Turn {turn['turn']}: [{stage}] '{utt}'")
                if slots:
                    print(f"    slots: {slots}")
                if resp:
                    print(f"    -> {resp}")
                if src:
                    print(f"    (source: {src})")
                if err:
                    print(f"    ERROR: {err}")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_all())
    sys.exit(0 if all(r["pass"] for r in results) else 1)
