"""Both hook providers share outcome, timing and attention behavior."""
from dataclasses import replace
import json
import time

import pytest

from awaitonal.adapter import adapt_codex
from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import EventQueue, Service
from awaitonal.types import Event
from awaitonal.voices import SESSION_VOICES
from test_service import eventually, running_service


@pytest.fixture(params=("claude", "codex"))
def provider(request):
    return request.param


def event(provider, name, *, session="s", turn="t", text="", identifier=None):
    return Event(
        f"codex:{session}" if provider == "codex" else session,
        identifier or f"{name}:{turn}", text,
        explicit_state="needs-you" if name in ("PreToolUse", "PermissionRequest") else None,
        evidence_source=f"{provider}:{name}", turn_id=turn,
        kind="turn-start" if name == "UserPromptSubmit" else "notification",
    )


@pytest.mark.parametrize("name,gesture", [("PreToolUse", "decision"), ("PermissionRequest", "needs-you")])
def test_structured_handoffs_choose_the_same_gesture_for_each_provider(provider, name, gesture):
    result = RulesClassifier().classify(event(provider, name))
    assert result.gesture == gesture
    assert result.attention and result.expectancy == "required-handoff"
    assert result.evidence_source == f"{provider}:{name}"


@pytest.mark.parametrize("text,gesture", [
    ("Implemented the fix and all tests pass.", "done"),
    ("Implemented the fix, but the integration tests are still failing.", "caveats"),
    ("Please review the patch when you have time.", "review"),
    ("Which database should I use? I need your choice before continuing.", "decision"),
    ("Please sign in before I can continue.", "needs-you"),
])
def test_final_prose_uses_the_same_palette_for_each_provider(provider, text, gesture):
    assert RulesClassifier().classify(event(provider, "Stop", text=text)).gesture == gesture


@pytest.mark.parametrize("elapsed,suppressed,long", [(2, True, False), (45, False, False), (150, False, True)])
def test_correlated_turns_drive_duration_variants_for_each_provider(provider, elapsed, suppressed, long):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    start = event(provider, "UserPromptSubmit")
    stop = event(provider, "Stop", text="Done.")
    service._intake(start, rules, 10)
    service._intake(stop, rules, 10 + elapsed)
    pending, = service.queue.items
    assert pending.turn_seconds == elapsed
    result = rules.classify(stop)
    assert service._suppress(result, pending.turn_seconds) is suppressed
    assert service._long_turn(result, pending.turn_seconds) is long
    assert service.timings.finish(stop, 11 + elapsed) is None


@pytest.mark.parametrize("turn", ["", "different"])
def test_uncorrelated_codex_stop_remains_audible(turn):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    service._intake(event("codex", "UserPromptSubmit"), rules, 10)
    stop = event("codex", "Stop", turn=turn, text="Done.")
    service._intake(stop, rules, 12)
    pending, = service.queue.items
    assert pending.turn_seconds is None
    assert service._suppression_reason(rules.classify(stop), pending.turn_seconds) is None
    assert not service._long_turn(rules.classify(stop), pending.turn_seconds)


@pytest.mark.parametrize("name", ["PreToolUse", "PermissionRequest"])
def test_structured_attention_does_not_consume_timing_or_get_short_turn_suppression(provider, name):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    service._intake(event(provider, "UserPromptSubmit"), rules, 10)
    attention = event(provider, name)
    service._intake(attention, rules, 11)
    pending, = service.queue.items
    assert pending.turn_seconds is None
    assert service._suppression_reason(rules.classify(attention), 1) is None
    stop = event(provider, "Stop", text="Done.")
    service._intake(stop, rules, 160)
    pending, = service.queue.items
    assert pending.event == stop and pending.turn_seconds == 150


@pytest.mark.parametrize("closing", ["Okay.", "I need your choice before continuing."])
def test_stop_does_not_repeat_a_recent_structured_handoff(provider, closing):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    question = event(provider, "PreToolUse")
    service._intake(question, rules, now)
    assert service.queue.get() == question
    service._intake(event(provider, "Stop", text=closing), rules, now + 0.1)
    assert not service.queue.items
    # A distinct follow-up question still receives attention in the same turn.
    following = event(provider, "PreToolUse", identifier="question:second")
    service._intake(following, rules, now + 0.2)
    assert service.queue.get() == following


def test_final_delivery_replaces_only_its_own_sessions_queued_attention(provider):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    first = event(provider, "PreToolUse")
    other_provider = "claude" if provider == "codex" else "codex"
    other = event(other_provider, "PermissionRequest")
    service._intake(first, rules, now)
    service._intake(other, rules, now)
    stop = event(provider, "Stop", text="Done.")
    service._intake(stop, rules, now + 0.1)
    assert service.queue.get() == other
    assert service.queue.get() == stop
    assert not service.queue.items


def test_same_tool_question_and_permission_aliases_are_deduplicated(provider):
    queue = EventQueue()
    now = time.monotonic()
    question = replace(event(provider, "PreToolUse", identifier="question:one"), dedup_key="tool:fingerprint")
    permission = replace(event(provider, "PermissionRequest", identifier="permission:one"), dedup_key="tool:fingerprint")
    assert queue.put(question, True, now=now)
    assert not queue.put(permission, True, now=now + 0.1)
    assert queue.put(replace(question, event_id="question:two"), True, now=now + 0.2)


def test_unrecognized_evidence_does_not_gain_stop_or_question_semantics():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30)
    service._intake(event("codex", "UserPromptSubmit"), rules, 10)
    question = event("codex", "PreToolUse")
    service._intake(question, rules, 11)
    manual = replace(event("codex", "Stop", text="Done."), evidence_source="other:Stop")
    service._intake(manual, rules, 12)
    assert [p.event for p in service.queue.items] == [question, manual]
    assert all(p.turn_seconds is None for p in service.queue.items)
    actual_stop = event("codex", "Stop", text="Done.", identifier="stop:real")
    service._intake(actual_stop, rules, 15)
    pending, = service.queue.items
    assert pending.event == actual_stop and pending.turn_seconds == 5
    unknown_question = replace(question, evidence_source="other:PreToolUse")
    assert rules.classify(unknown_question).gesture == "needs-you"


def test_live_codex_and_claude_share_rotation_without_sharing_session_identity():
    played = []
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        for provider in ("claude", "codex"):
            start = event(provider, "UserPromptSubmit", session="same-id")
            send_event(start, path)
            eventually(lambda: start.session_id in service.voices.sessions)
        assert not played
        for index, provider in enumerate(("codex", "claude", "codex")):
            stop = event(provider, "Stop", session="same-id", turn=f"t{index}", text="Done.")
            send_event(stop, path)
            eventually(lambda: len(played) == index + 1)
        assert [args[2] for args in played] == [SESSION_VOICES[1], SESSION_VOICES[0], SESSION_VOICES[1]]
        assert [record["evidence_source"] for record in logs] == ["codex:Stop", "claude:Stop", "codex:Stop"]
        assert "same-id" not in json.dumps(logs)


def test_native_codex_hooks_round_trip_through_the_service_with_private_timing_and_handoffs():
    common = {"session_id": "PRIVATE-session", "turn_id": "PRIVATE-turn",
              "transcript_path": "/PRIVATE/transcript.jsonl"}
    start = adapt_codex({**common, "hook_event_name": "UserPromptSubmit", "prompt": "PRIVATE prompt"})
    question = adapt_codex({**common, "hook_event_name": "PreToolUse", "tool_name": "request_user_input",
                            "tool_use_id": "q1", "tool_input": {"questions": [{"question": "PRIVATE choice?"}]}})
    permission = adapt_codex({**common, "hook_event_name": "PermissionRequest", "tool_name": "exec_command",
                              "tool_input": {"cmd": "PRIVATE command"}})
    stop = adapt_codex({**common, "hook_event_name": "Stop", "last_assistant_message": "Done. PRIVATE result"})
    assert all(item is not None for item in (start, question, permission, stop))
    with running_service(min_turn_seconds=30) as (service, path, played, logs):
        send_event(start, path)
        eventually(lambda: start.session_id in service.timings.sessions)
        send_event(question, path)
        eventually(lambda: played == ["decision"])
        send_event(permission, path)
        eventually(lambda: played == ["decision", "needs-you"])
        send_event(stop, path)
        eventually(lambda: len(logs) == 3)
        assert played == ["decision", "needs-you"]
        assert [record["suppressed"] for record in logs] == [None, None, "short-turn"]
        assert logs[-1]["turn_seconds"] is not None and 0 <= logs[-1]["turn_seconds"] < 30
        assert "PRIVATE" not in json.dumps(logs)
