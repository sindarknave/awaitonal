"""OpenCode reuses shared lifecycle, admission, and session controls."""
from dataclasses import replace
import json
import threading
import time

import pytest

from awaitonal.adapter import adapt_claude, adapt_codex, adapt_opencode, adapt_pi
from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import Service
from awaitonal.voices import SESSION_VOICES
from test_opencode_adapter import NEXT_TURN, REQUEST_ID, TURN_ID, payload
from test_service import eventually, running_service
from test_service_control import control


@pytest.mark.parametrize("seconds,suppressed,long_turn,variation", [(2, True, False, None),
                                                                    (45, False, False, 0),
                                                                    (150, False, True, 1)])
def test_correlated_lifecycle_reuses_suppression_duration_groups_and_long_endings(seconds, suppressed, long_turn, variation):
    played = []
    rules = RulesClassifier()
    with running_service(min_turn_seconds=30, long_turn_seconds=120, gesture_variations=True,
                         variation_player=lambda *args: played.append(args)) as (service, _, _, logs):
        now = time.monotonic()
        service._intake(adapt_opencode(payload("agent_start")), rules, now - seconds)
        service._intake(adapt_opencode(payload()), rules, now)
        eventually(lambda: any("classification_ms" in row for row in logs))
        if suppressed:
            assert not played and logs[0]["suppressed"] == "short-turn"
            assert not service.variations.sessions
        else:
            eventually(lambda: len(played) == 1)
            assert played[0][0] == "done" and played[0][3:] == (long_turn, variation)
        assert logs[0]["turn_seconds"] == seconds


@pytest.mark.parametrize("quiet_patch", [{"outcome": "aborted"}, {"last_assistant_message": ""},
                                         {"last_assistant_message": None}])
def test_quiet_end_releases_timing_and_matching_attention_without_allocating_a_voice(quiet_patch):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, long_turn_seconds=120,
                      session_voices=True, voice_player=lambda *_: None)
    quiet = adapt_opencode(payload(**quiet_patch))
    service._intake(quiet, rules, 5)
    assert not service.voices.sessions
    service._intake(adapt_opencode(payload("agent_start")), rules, 10)
    service._intake(adapt_opencode(payload("question_asked")), rules, 11)
    service._intake(quiet, rules, 12)
    assert not service.queue.items
    service._intake(adapt_opencode(payload("agent_start", turn_id=NEXT_TURN)), rules, 20)
    service._intake(adapt_opencode(payload(turn_id=NEXT_TURN)), rules, 160)
    pending, = service.queue.items
    assert pending.turn_seconds == 140
    assert service._long_turn(rules.classify(pending.event), pending.turn_seconds)


def test_quiet_end_does_not_touch_other_session_or_turn():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, long_turn_seconds=120)
    now = time.monotonic()
    service._intake(adapt_opencode(payload("agent_start")), rules, now)
    matching = adapt_opencode(payload("question_asked"))
    others = [replace(matching, session_id="opencode:other"), replace(matching, turn_id=NEXT_TURN)]
    for event in (matching, *others):
        service.queue.put(event, attention=True, now=now, supersede=False)
    service._intake(adapt_opencode(payload(outcome="aborted")), rules, now + 1)
    assert [pending.event for pending in service.queue.items] == others
    service._intake(adapt_opencode(payload("agent_start", turn_id=NEXT_TURN)), rules, now + 2)
    # A late quiet end of the old turn cannot consume the newly tracked one.
    service._intake(adapt_opencode(payload(outcome="aborted")), rules, now + 3)
    assert service.timings.sessions[matching.session_id].turn_id == NEXT_TURN
    assert service.timings.sessions[matching.session_id].started == now + 2


def test_attention_dedup_and_settled_waiting_do_not_repeat_the_same_handoff():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    question = adapt_opencode(payload("question_asked"))
    service._intake(question, rules, now)
    assert service.queue.get() == question
    service._intake(question, rules, now + 0.1)
    service._intake(adapt_opencode(payload(last_assistant_message="I need your choice before continuing.")), rules, now + 0.2)
    assert not service.queue.items
    next_request = adapt_opencode(payload("question_asked", request_id=NEXT_TURN))
    service._intake(next_request, rules, now + 0.3)
    assert service.queue.get() == next_request


def test_completed_reply_resolves_queued_question_and_permission_only_for_its_session():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    question = adapt_opencode(payload("question_asked"))
    permission = adapt_opencode(payload("permission_asked", request_id=NEXT_TURN))
    other = adapt_codex({"hook_event_name": "PermissionRequest", "session_id": "session-123",
                         "turn_id": TURN_ID, "tool_name": "exec_command", "tool_input": {}})
    for event in (question, permission, other):
        service._intake(event, rules, now)
    done = adapt_opencode(payload())
    service._intake(done, rules, now + 0.1)
    assert service.queue.get() == other
    assert service.queue.get() == done
    assert not service.queue.items


def test_generic_error_is_unsuppressed_and_retry_retires_queued_failure():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    service._intake(adapt_opencode(payload("agent_start")), rules, 10)
    failure = adapt_opencode(payload(outcome="error"))
    service._intake(failure, rules, 11)
    pending, = service.queue.items
    assert pending.attention and pending.turn_seconds == 1
    assert service._suppression_reason(rules.classify(failure), pending.turn_seconds) is None
    service._intake(adapt_opencode(payload("agent_start", turn_id=NEXT_TURN)), rules, 12)
    assert not service.queue.items
    service._intake(adapt_opencode(payload(turn_id=NEXT_TURN)), rules, 17)
    pending, = service.queue.items
    assert pending.turn_seconds == 5


def test_provider_namespaces_keep_timing_dedup_and_voice_assignments_independent():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, session_voices=True, voice_player=lambda *_: None)
    common = {"session_id": "session-123", "hook_event_name": "Stop", "last_assistant_message": "Done.",
              "turn_id": TURN_ID, "prompt_id": TURN_ID}
    events = [adapt_claude(common), adapt_codex(common), adapt_pi(payload()), adapt_opencode(payload())]
    for index, event in enumerate(events):
        service._intake(event, rules, 10 + index)
    assert [pending.voice for pending in service.queue.items] == list(SESSION_VOICES[:4])
    assert len(service.voices.sessions) == 4
    assert service.voices.assign(events[-1].session_id, 20) == SESSION_VOICES[3]


def test_live_private_socket_routes_handoffs_and_drops_sensitive_identity_from_logs():
    with running_service() as (service, path, played, logs):
        for index, (name, gesture) in enumerate((("question_asked", "decision"), ("permission_asked", "needs-you"))):
            event = adapt_opencode(payload(name, session_id="PRIVATE SESSION", request_id=REQUEST_ID if index == 0 else NEXT_TURN))
            send_event(event, path)
            eventually(lambda: len(played) == index + 1)
            assert played[-1] == gesture
        send_event(adapt_opencode(payload(outcome="error", session_id="PRIVATE SESSION")), path)
        eventually(lambda: played == ["decision", "needs-you", "failed"])
        assert "PRIVATE" not in json.dumps(logs)
        assert logs[-1]["failure_code"] == "unknown"


def test_global_mute_drops_opencode_events_and_preserves_existing_voice():
    played = []
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        send_event(adapt_opencode(payload()), path)
        eventually(lambda: len(played) == 1)
        first_voice = played[0][2]
        assert control(path, service, "mute")["muted"]
        rules = RulesClassifier()
        for source in (payload("agent_start"), payload("question_asked"), payload("permission_asked"),
                       payload(outcome="error"), payload(turn_id=NEXT_TURN)):
            service._intake(adapt_opencode(source), rules, time.monotonic())
        assert len(played) == 1 and not service.queue.items
        assert not control(path, service, "unmute")["muted"]
        send_event(adapt_opencode(payload(turn_id=NEXT_TURN)), path)
        eventually(lambda: len(played) == 2)
        assert played[-1][2] == first_voice and len(logs) == 2


@pytest.mark.parametrize("quiet_patch", [{"outcome": "aborted"}, {"last_assistant_message": ""}])
def test_quiet_end_cancels_matching_active_classifier_and_other_session_still_plays(quiet_patch):
    entered, release = threading.Event(), threading.Event()

    class GatedClassifier:
        def classify(self, event):
            if event.evidence_source == "opencode:question_asked":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=GatedClassifier()) as (service, path, played, logs):
        try:
            send_event(adapt_opencode(payload("question_asked")), path)
            assert entered.wait(2)
            send_event(adapt_opencode(payload(**quiet_patch)), path)
            eventually(lambda: service.queue.current is not None and service.queue.current.cancelled)
            send_event(adapt_opencode(payload(session_id="other-session")), path)
            release.set()
            eventually(lambda: played == ["done"])
            assert [row["suppressed"] for row in logs] == ["turn-ended", None]
        finally:
            release.set()


def test_quiet_end_after_classification_cannot_consume_variation_or_admit_audio():
    entered, release = threading.Event(), threading.Event()
    varied = []
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args)) as (service, path, _, logs):
        original = service.logger

        def logger(record):
            original(record)
            if record.get("evidence_source") == "opencode:agent_settled":
                entered.set()
                assert release.wait(3)

        service.logger = logger
        try:
            send_event(adapt_opencode(payload()), path)
            assert entered.wait(2)
            send_event(adapt_opencode(payload(outcome="aborted")), path)
            eventually(lambda: service.queue.current is not None and service.queue.current.cancelled)
            release.set()
            eventually(lambda: service.queue.current is None)
            assert not varied and not service.variations.sessions
            assert not any(record.get("event") == "playback" for record in logs)
        finally:
            release.set()
