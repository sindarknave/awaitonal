"""Structured API errors and opt-in timing never turn uncertainty into silence."""
import json

import pytest

from awaitonal.adapter import adapt_claude, event_from_wire
from awaitonal.classify import RulesClassifier
from awaitonal.service import EventQueue, Service, TurnTimings
from awaitonal.types import ACTION_FAILURE_CODES, FAILURE_CODES, Classification, Controls, Event, controls_for, map_controls


def hook(name, turn="t", session="s", **fields):
    return adapt_claude({"hook_event_name": name, "session_id": session, "prompt_id": turn, **fields})


def start(turn="t", session="s"):
    return hook("UserPromptSubmit", turn, session, prompt="PRIVATE-PROMPT")


def stop(turn="t", session="s"):
    return hook("Stop", turn, session, last_assistant_message="Implemented the fix and all tests pass.")


@pytest.mark.parametrize("code", FAILURE_CODES)
def test_failure_codes_bypass_prose_and_keep_only_safe_metadata(code):
    event = hook("StopFailure", error=code, error_details="SECRET-KEY", last_assistant_message="PRIVATE-ERROR")
    assert event_from_wire(event.to_dict()) == event
    result = RulesClassifier().classify(event)
    expected = "needs-you" if code in ACTION_FAILURE_CODES else "failed"
    assert result.state == result.gesture == expected
    assert result.failure_code == code and result.attention
    assert result.expectancy == ("required-handoff" if expected == "needs-you" else "none")
    assert result.controls.rejected is False
    serialized = json.dumps([event.to_dict(), result.to_dict()])
    assert "SECRET" not in serialized and "PRIVATE" not in serialized


def test_future_error_codes_are_generic_failures_without_forwarding_code_text():
    event = hook("StopFailure", error="NEW-PRIVATE-ERROR")
    assert event.failure_code == "unknown"
    assert event.explicit_state == "failed"
    assert "NEW-PRIVATE" not in json.dumps(event.to_dict())


@pytest.mark.parametrize("value", [None, "", " ", [], {}, 1, "x" * 257])
def test_malformed_failure_does_not_manufacture_an_outcome(value):
    assert hook("StopFailure", error=value) is None


def test_start_marker_never_contains_prompt_or_has_an_outcome():
    event = start()
    assert event.kind == "turn-start" and event.text == ""
    assert event_from_wire(event.to_dict()) == event
    assert RulesClassifier().classify(event) is None
    assert "PRIVATE" not in json.dumps(event.to_dict())
    # Existing notification events retain their wire shape.
    assert "kind" not in stop().to_dict() and "failure_code" not in stop().to_dict()


@pytest.mark.parametrize("name,fields", [
    ("Stop", {"last_assistant_message": "Done."}),
    ("StopFailure", {"error": "server_error"}),
    ("UserPromptSubmit", {"prompt": "PRIVATE"}),
])
@pytest.mark.parametrize("turn", ["t" * 256, "é" * 128])
def test_maximum_length_turn_identifiers_round_trip(name, fields, turn):
    event = hook(name, turn=turn, **fields)
    assert event is not None and event.turn_id == turn
    assert len(event.event_id) <= 256
    assert event_from_wire(event.to_dict()) == event


def test_multibyte_turn_ids_must_fit_wire_limit():
    assert hook("UserPromptSubmit", turn="é" * 129) is None


def test_long_structured_question_id_round_trips():
    event = hook("PreToolUse", tool_name="AskUserQuestion", tool_use_id="q" * 256,
                 tool_input={"questions": [{"question": "Which option?"}]})
    assert event_from_wire(event.to_dict()) == event


@pytest.mark.parametrize("patch", [
    {"text": "PRIVATE"}, {"explicit_state": "done"}, {"explicit_state": "rejected"},
    {"failure_code": "unrecognized"}, {"failure_code": []}, {"evidence_source": "text"},
    {"kind": "turn-start"},
])
def test_failure_wire_rejects_inconsistent_fields(patch):
    event = hook("StopFailure", error="server_error").to_dict()
    assert event_from_wire({**event, **patch}) is None


@pytest.mark.parametrize("patch", [{"text": "private"}, {"explicit_state": "needs-you"},
                                  {"failure_code": "unknown"}, {"dedup_key": "x"},
                                  {"evidence_source": "text"}])
def test_start_wire_accepts_only_minimal_metadata(patch):
    assert event_from_wire({**start().to_dict(), **patch}) is None


def test_failed_control_is_distinct_from_refusal_and_has_explicit_precedence():
    assert map_controls(Controls(failed=True)) == "failed"
    assert map_controls(Controls(loose_ends=1, failed=True)) == "failed"
    assert map_controls(Controls(needs_you=True, failed=True)) == "needs-you"
    assert map_controls(Controls(rejected=True, failed=True)) == "rejected"
    with pytest.raises(ValueError):
        Controls(failed=1)


def test_timing_is_actual_correlated_intake_and_is_consumed():
    timings = TurnTimings()
    timings.start(start(), 10)
    assert timings.finish(stop(), 12.5) == 2.5
    assert timings.finish(stop(), 13) is None
    clean = TurnTimings()
    clean.start(start(), 10)
    assert clean.finish(stop(), 11) == 1
    clean.start(start("next"), 12)
    assert clean.finish(stop("next"), 15) == 3


@pytest.mark.parametrize("first,second,terminal", [
    (start(""), None, stop("")), (start(), start(), stop()),
    (start(), start("other"), stop("other")), (start(), None, stop("other")),
    (start(), None, stop("")), (start(" "), None, stop(" ")),
])
def test_missing_duplicate_mismatched_or_overlapping_turns_fail_open(first, second, terminal):
    timings = TurnTimings()
    timings.start(first, 10)
    if second is not None:
        timings.start(second, 11)
    assert timings.finish(terminal, 12) is None
    timings.start(start("later"), 13)
    assert timings.finish(stop("later"), 14) is None


def test_timing_is_bounded_expires_and_does_not_survive_a_restart():
    timings = TurnTimings(capacity=2, ttl=10)
    for number in range(3):
        timings.start(start(session=str(number)), number)
    assert len(timings.sessions) == 2
    assert timings.finish(stop(session="0"), 3) is None
    assert timings.finish(stop(session="1"), 20) is None
    assert TurnTimings().finish(stop(session="2"), 3) is None


def test_parallel_sessions_do_not_share_timing_or_delay_measurements():
    service = Service(RulesClassifier(), lambda *_: None, min_turn_seconds=3)
    rules = RulesClassifier()
    service._intake(start(session="a"), rules, 10)
    service._intake(start(session="b"), rules, 11)
    service._intake(stop(session="a"), rules, 12)
    service._intake(stop(session="b"), rules, 18)
    assert [(p.event.session_id, p.turn_seconds) for p in service.queue.items] == [("a", 2), ("b", 7)]
    assert service._suppress(rules.classify(stop()), service.queue.items[0].turn_seconds)
    assert not service._suppress(rules.classify(stop()), service.queue.items[1].turn_seconds)


@pytest.mark.parametrize("seconds,expected", [(None, False), (-1, False), (0, True), (2.999, True), (3, False), (4, False)])
def test_threshold_boundary(seconds, expected):
    service = Service(None, None, min_turn_seconds=3)
    assert service._suppress(RulesClassifier().classify(stop()), seconds) is expected


@pytest.mark.parametrize("state,delivery,expectancy,handoff,expected", [
    ("done", "change", "none", "action", True),
    ("done", "answer", "none", "action", True),
    ("done", "plan", "none", "action", True),
    ("done", "artifact", "none", "action", True),
    ("done", "published", "none", "action", True),
    ("done", "answer", "review-requested", "action", False),
    ("caveats", "change", "none", "action", False),
    ("needs-you", "unknown", "required-handoff", "action", False),
    ("needs-you", "unknown", "required-handoff", "decision", False),
    ("rejected", "unknown", "none", "action", False),
    ("failed", "unknown", "none", "action", False),
])
def test_only_routine_completed_deliveries_are_suppressed(state, delivery, expectancy, handoff, expected):
    result = Classification(state, controls_for(state), "test", "test", delivery_kind=delivery,
                            expectancy=expectancy, handoff_kind=handoff)
    assert Service(None, None, min_turn_seconds=3)._suppress(result, 1) is expected
    assert Service(None, None)._suppress(result, 1) is False


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf"), "3", [], {}])
def test_invalid_threshold_is_rejected(value):
    with pytest.raises(ValueError):
        Service(None, None, min_turn_seconds=value)


def test_retry_clears_only_that_sessions_queued_failures_and_failure_dedup():
    queue = EventQueue()
    failure = hook("StopFailure", error="server_error")
    other = hook("StopFailure", session="other", error="rate_limit")
    question = Event("s", "q", explicit_state="needs-you")
    assert queue.put(failure, True)
    assert not queue.put(failure, True)
    assert queue.put(other, True)
    assert queue.put(question, True)
    queue.begin_turn(start())
    assert [p.event for p in queue.items] == [other, question]
    assert queue.put(failure, True)  # An actual retry can fail again inside dedup window.


def test_final_handoff_supersedes_a_queued_authentication_failure():
    queue = EventQueue()
    failure = hook("StopFailure", error="authentication_failed")
    assert queue.put(failure, True, state="needs-you")
    final = hook("Stop", last_assistant_message="I need your approval before I can continue.")
    assert queue.put(final, True, state="needs-you")
    assert [p.event for p in queue.items] == [final]
