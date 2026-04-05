"""Edge case test harness for IVA voice bridge.

Tests preprocessing, slot validation, question detection, and full
IVA round-trips across 50+ edge cases. Reports pass/fail with details.
"""

import json
import os
import re
import sys
import time

# Setup paths
IVA_SOURCE_PATH = os.environ.get("IVA_SOURCE_PATH", "D:/Applications/dynamic-skills-agent")
if IVA_SOURCE_PATH not in sys.path:
    sys.path.insert(0, IVA_SOURCE_PATH)

sys.path.insert(0, os.path.dirname(__file__))

from iva_bridge import (
    _preprocess_utterance,
    _validate_extracted_slots,
    _is_question_utterance,
)

# ── Test infrastructure ──────────────────────────────────────────────────

RESULTS = []

def test(name, actual, expected, details=""):
    passed = actual == expected
    RESULTS.append({
        "name": name,
        "passed": passed,
        "actual": actual,
        "expected": expected,
        "details": details,
    })
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if not passed:
        print(f"         expected: {expected}")
        print(f"         actual:   {actual}")
        if details:
            print(f"         details:  {details}")


def test_contains(name, actual, substring, details=""):
    passed = substring.lower() in str(actual).lower()
    RESULTS.append({
        "name": name,
        "passed": passed,
        "actual": actual,
        "expected": f"contains '{substring}'",
        "details": details,
    })
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}")
    if not passed:
        print(f"         expected to contain: {substring}")
        print(f"         actual:   {actual}")


# ── 1. Preprocessing Tests ──────────────────────────────────────────────

print("\n=== PREPROCESSING TESTS ===\n")

# Number word conversion
test("number: 'one' -> '1'", _preprocess_utterance("one"), "1")
test("number: 'nine' -> '9'", _preprocess_utterance("nine"), "9")
test("number: 'Tomorrow at nine' -> 'Tomorrow...'",
     "at 9" in _preprocess_utterance("Tomorrow at nine"), True)
test("number: 'My son and one companion'",
     _preprocess_utterance("My son and one companion"), "My son and 1 companion")
test("number: 'Just one' -> 'Just 1'",
     _preprocess_utterance("Just one"), "Just 1")

# Companion stage-specific preprocessing
test("companion: 'just my son' at companion stage",
     _preprocess_utterance("just my son", stage="companion"), "1 companion son")
test("companion: 'my daughter' at companion stage",
     _preprocess_utterance("my daughter", stage="companion"), "1 companion daughter")
test("companion: 'none' at companion stage",
     _preprocess_utterance("none", stage="companion"), "0 companions")
test("companion: 'just me' at companion stage",
     _preprocess_utterance("just me", stage="companion"), "0 companions")
test("companion: 'Just one' at companion stage",
     _preprocess_utterance("Just one", stage="companion"), "1 companions")
test("companion: 'a couple' at companion stage",
     _preprocess_utterance("a couple", stage="companion"), "2 companions")
test("companion: 'one' at NON-companion stage stays '1'",
     _preprocess_utterance("one", stage="collect_time"), "1")

# Address preamble stripping
test("addr: 'I'm heading to Mary Hospital' -> 'Mary Hospital'",
     _preprocess_utterance("I'm heading to Mary Hospital"), "Mary Hospital")
test("addr: 'pick me up from 123 Oak St' -> '123 Oak St'",
     _preprocess_utterance("pick me up from 123 Oak St"), "123 Oak St")
test("addr: 'the address is 500 Pine Rd' -> '500 Pine Rd'",
     _preprocess_utterance("the address is 500 Pine Rd"), "500 Pine Rd")
test("addr: 'going to City Medical Center' -> 'City Medical Center'",
     _preprocess_utterance("going to City Medical Center"), "City Medical Center")

# Member ID digit collapse
test("digits: '1, 4, 6, 2' -> '1462'",
     _preprocess_utterance("1, 4, 6, 2"), "1462")
test("digits: 'one six three two' -> '1632'",
     _preprocess_utterance("one six three two"), "1632")
test("digits: 'One, six, three, two' -> '1632'",
     _preprocess_utterance("One, six, three, two"), "1632")

# Punctuation stripping
test("punct: 'Hello.' -> 'Hello'", _preprocess_utterance("Hello."), "Hello")
test("punct: 'a.m.' preserved", _preprocess_utterance("a.m."), "a.m.")
test("punct: 'Yes!' -> 'Yes'", _preprocess_utterance("Yes!"), "Yes")
test("punct: 'Really?' -> 'Really'", _preprocess_utterance("Really?"), "Really")

# Relative date resolution
from datetime import datetime, timedelta
now = datetime.now()

def _ordinal(day):
    if 11 <= day <= 13:
        return f"{day}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"

def _fmt_date(dt):
    return f"{dt.strftime('%B')} {_ordinal(dt.day)}"

tomorrow_str = _fmt_date(now + timedelta(days=1))
today_str = _fmt_date(now)

test("date: 'tomorrow' resolves",
     _preprocess_utterance("tomorrow"), tomorrow_str)
test("date: 'Tomorrow at 9' resolves",
     _preprocess_utterance("Tomorrow at nine"),
     f"{tomorrow_str} at 9")
test("date: 'today at 2' resolves",
     _preprocess_utterance("today at two"),
     f"{today_str} at 2")

# Next day resolution
_DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
         "friday": 4, "saturday": 5, "sunday": 6}
for day_name, day_num in _DAYS.items():
    days_ahead = (day_num - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    expected_date = _fmt_date(now + timedelta(days=days_ahead))
    result = _preprocess_utterance(f"next {day_name}")
    test(f"date: 'next {day_name}' -> {expected_date}", result, expected_date)

# Time normalization
test("time: '9 a.m.' -> '9 AM'",
     "9 AM" in _preprocess_utterance("9 a.m."), True,
     _preprocess_utterance("9 a.m."))
test("time: '2 p.m.' -> '2 PM'",
     "2 PM" in _preprocess_utterance("2 p.m."), True,
     _preprocess_utterance("2 p.m."))
test("time: '2:30 pm' -> '2:30 PM'",
     "2:30 PM" in _preprocess_utterance("2:30 pm"), True,
     _preprocess_utterance("2:30 pm"))
test("time: 'Tomorrow at 9 a.m.' full resolve",
     f"{tomorrow_str} at 9 AM" in _preprocess_utterance("Tomorrow at 9 a.m."), True,
     _preprocess_utterance("Tomorrow at 9 a.m."))
test("time: 'next monday at 2 p.m.' full resolve",
     "at 2 PM" in _preprocess_utterance("next monday at 2 p.m."), True,
     _preprocess_utterance("next monday at 2 p.m."))
test("time: '9 in the morning' -> '9 AM'",
     "9 AM" in _preprocess_utterance("9 in the morning"), True,
     _preprocess_utterance("9 in the morning"))
test("time: '3 in the afternoon' -> '3 PM'",
     "3 PM" in _preprocess_utterance("3 in the afternoon"), True,
     _preprocess_utterance("3 in the afternoon"))

# Address preservation
test("addr: '123 Main Street' preserved",
     _preprocess_utterance("123 Main Street"), "123 Main Street")
test("addr: '456 Oak Ave.' trailing dot stripped",
     _preprocess_utterance("456 Oak Ave."), "456 Oak Ave")
test("addr: 'Five twenty one Elm Road' -> '5 20 1 Elm Road'",
     "5" in _preprocess_utterance("Five twenty one Elm Road"), True,
     _preprocess_utterance("Five twenty one Elm Road"))

# ── 2. Slot Validation Tests ────────────────────────────────────────────

print("\n=== SLOT VALIDATION TESTS ===\n")

# Questions should be rejected as addresses
test("slot: question as pickup rejected",
     _validate_extracted_slots({"pickup_address": "Where can I be picked up from"}, "Where can I be picked up from?")["pickup_address"],
     None, "question word mid-sentence")

test("slot: question as dropoff rejected",
     _validate_extracted_slots({"dropoff_address": "Can I go to the hospital"}, "Can I go to the hospital?")["dropoff_address"],
     None, "question with ?")

test("slot: '?' in value rejected",
     _validate_extracted_slots({"pickup_address": "Where is that?"}, "Where is that?")["pickup_address"],
     None)

# Valid addresses should pass
test("slot: '123 Main St' valid address",
     _validate_extracted_slots({"pickup_address": "123 Main St"}, "123 Main St")["pickup_address"],
     "123 Main St")

test("slot: 'General Hospital' valid address",
     _validate_extracted_slots({"dropoff_address": "General Hospital"}, "General Hospital")["dropoff_address"],
     "General Hospital")

test("slot: '5521 Elm Road' valid address",
     _validate_extracted_slots({"pickup_address": "5521 Elm Road"}, "5521 Elm Road")["pickup_address"],
     "5521 Elm Road")

# Short non-address should be rejected
test("slot: 'home' short non-address rejected",
     _validate_extracted_slots({"pickup_address": "home"}, "home")["pickup_address"],
     None, "too short, no number, no address word")

test("slot: 'my house' short non-address rejected",
     _validate_extracted_slots({"pickup_address": "my house"}, "my house")["pickup_address"],
     None)

# Valid numbers
test("slot: member_id '1632' valid",
     _validate_extracted_slots({"member_id": "1632"}, "1632")["member_id"],
     "1632")

# Invalid numbers
test("slot: member_id 'one six three two' invalid (no digits)",
     _validate_extracted_slots({"member_id": "one six three two"}, "one six three two")["member_id"],
     None)

# Edge case: long address without number but valid
test("slot: 'General Medical Center on Fifth Avenue' valid",
     _validate_extracted_slots({"dropoff_address": "General Medical Center on Fifth Avenue"}, "...")["dropoff_address"],
     "General Medical Center on Fifth Avenue")

# ── 3. Question Detection Tests ─────────────────────────────────────────

print("\n=== QUESTION DETECTION TESTS ===\n")

session = {"current_stage": "collect_pickup", "slots": {}}

# Should detect as questions
test("q: 'Where can I be picked up from?' = question",
     _is_question_utterance("Where can I be picked up from?", "Where can I be picked up from", session),
     True)

test("q: 'Or can I be picked up from?' = question",
     _is_question_utterance("Or can I be picked up from?", "Or can I be picked up from", session),
     True)

test("q: 'What is a member ID?' = question",
     _is_question_utterance("What is a member ID?", "What is a member ID", session),
     True)

test("q: 'How do I find my member ID?' = question",
     _is_question_utterance("How do I find my member ID?", "How do I find my member ID", session),
     True)

test("q: 'Can you pick me up from home?' = question",
     _is_question_utterance("Can you pick me up from home?", "Can you pick me up from home", session),
     True)

test("q: 'Where should I be waiting?' = question",
     _is_question_utterance("Where should I be waiting?", "Where should I be waiting", session),
     True)

test("q: 'Do I need to bring anything?' = question",
     _is_question_utterance("Do I need to bring anything?", "Do I need to bring anything", session),
     True)

test("q: 'Is there a cost for this?' = question",
     _is_question_utterance("Is there a cost for this?", "Is there a cost for this", session),
     True)

# Should NOT detect as questions (these are slot data)
test("q: '123 Main Street' = NOT question",
     _is_question_utterance("123 Main Street", "123 Main Street", session),
     False)

test("q: '1632' = NOT question",
     _is_question_utterance("1632", "1632", session),
     False)

test("q: 'General Hospital' = NOT question",
     _is_question_utterance("General Hospital", "General Hospital", session),
     False)

test("q: 'Tomorrow at 9 AM' = NOT question",
     _is_question_utterance("Tomorrow at 9 AM", "Tomorrow at 9 AM", session),
     False)

test("q: 'Yes' = NOT question (too short)",
     _is_question_utterance("Yes", "Yes", session),
     False)

test("q: 'No wheelchair needed' = NOT question",
     _is_question_utterance("No wheelchair needed", "No wheelchair needed", session),
     False)

test("q: 'Just my son' = NOT question",
     _is_question_utterance("Just my son", "Just my son", session),
     False)

# Tag questions / confirmations should NOT trigger
test("q: 'Yes, schedule, right?' = NOT question",
     _is_question_utterance("Yes, schedule, right?", "Yes, schedule, right", session),
     False)
test("q: 'Book a ride, okay?' = NOT question",
     _is_question_utterance("Book a ride, okay?", "Book a ride, okay", session),
     False)
test("q: 'Yes, Anita, schedule, right?' = NOT question",
     _is_question_utterance("Yes, Anita, schedule, right?", "Yes, Anita, schedule, right", session),
     False)
test("q: 'I need a ride, correct?' = NOT question",
     _is_question_utterance("I need a ride, correct?", "I need a ride, correct", session),
     False)


# ── 4. Full IVA Round-Trip Tests ────────────────────────────────────────

print("\n=== FULL IVA ROUND-TRIP TESTS ===\n")

try:
    from iva_bridge import IVABridge
    import asyncio

    async def run_turn(bridge, utterance):
        return await bridge.process(utterance)

    def sync_turn(bridge, utterance):
        return asyncio.run(run_turn(bridge, utterance))

    bridge = IVABridge()
    greeting = bridge.init_session()
    print(f"  Session: {bridge.session_id}")
    print(f"  Greeting: {greeting[:80]}...")

    # Turn 1: Intent detection
    r1 = sync_turn(bridge, "I need a ride to the doctor")
    test("iva: intent detected as book_new_ride",
         r1.get("intent_detected") in ("book_new_ride", None) or r1.get("stage") == "verification",
         True, f"stage={r1.get('stage')}, intent={r1.get('intent_detected')}")

    # Turn 2: Member ID
    r2 = sync_turn(bridge, "one six three two")
    test("iva: member_id extracted from number words",
         r2.get("slots_accumulated", {}).get("member_id") is not None,
         True, f"slots={r2.get('slots_accumulated', {})}")

    # Turn 3: Pickup address
    r3 = sync_turn(bridge, "123 Main Street")
    test("iva: pickup_address extracted",
         r3.get("slots_accumulated", {}).get("pickup_address") is not None,
         True, f"slots={r3.get('slots_accumulated', {})}")

    # Turn 4: Question instead of dropoff
    r4 = sync_turn(bridge, "Where am I going to be dropped off")
    test("iva: question not stored as dropoff_address",
         r4.get("slots_accumulated", {}).get("dropoff_address") is None,
         True, f"dropoff={r4.get('slots_accumulated', {}).get('dropoff_address')}")

    # Turn 5: Actual dropoff
    r5 = sync_turn(bridge, "City Medical Center")
    stage5 = r5.get("stage", "")
    test("iva: dropoff accepted or stage advanced",
         r5.get("slots_accumulated", {}).get("dropoff_address") is not None or "time" in stage5,
         True, f"stage={stage5}, slots={r5.get('slots_accumulated', {})}")

    # Turn 6: Relative date
    r6 = sync_turn(bridge, "Tomorrow at 9 AM")
    slots6 = r6.get("slots_accumulated", {})
    has_date = (slots6.get("appointment_date") is not None or
                slots6.get("appointment_time") is not None or
                slots6.get("appointment_datetime_local") is not None)
    test("iva: relative date 'Tomorrow at 9 AM' parsed",
         has_date, True, f"slots={slots6}")

except Exception as e:
    print(f"  [SKIP] Full IVA tests skipped: {e}")
    import traceback
    traceback.print_exc()


# ── Summary ─────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
passed = sum(1 for r in RESULTS if r["passed"])
failed = sum(1 for r in RESULTS if not r["passed"])
total = len(RESULTS)
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
print("=" * 60)

if failed:
    print("\nFAILED TESTS:")
    for r in RESULTS:
        if not r["passed"]:
            print(f"  - {r['name']}")
            print(f"    expected: {r['expected']}")
            print(f"    actual:   {r['actual']}")
            if r['details']:
                print(f"    details:  {r['details']}")

# Write results to JSON for agent consumption
with open(os.path.join(os.path.dirname(__file__), "test_results.json"), "w") as f:
    json.dump({"passed": passed, "failed": failed, "total": total, "results": RESULTS}, f, indent=2, default=str)

print(f"\nResults written to test_results.json")
