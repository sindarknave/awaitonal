"""Pi lifecycle events reuse timing, queue behavior, voices and global mute."""
from dataclasses import replace
import json
import threading
import time

import pytest

from awaitonal.adapter import adapt_claude, adapt_codex, adapt_pi
from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import Service
from awaitonal.voices import SESSION_VOICES
from test_pi_adapter import payload
from test_service import eventually, running_service
from test_service_control import control


@pytest.mark.parametrize("seconds,suppressed,long", [(2, True, False), (45, False, False), (150, False, True)])
def test_pi_correlated_turns_use_short_suppression_and_long_variants(seconds, suppressed, long):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    service._intake(adapt_pi(payload("agent_start")), rules, 10)
    stop = adapt_pi(payload())
    service._intake(stop, rules, 10 + seconds)
    pending, = service.queue.items
    assert pending.turn_seconds == seconds
    assert service._suppress(rules.classify(stop), pending.turn_seconds) is suppressed
    assert service._long_turn(rules.classify(stop), pending.turn_seconds) is long


@pytest.mark.parametrize("patch", [
    {"outcome": "aborted"}, {"last_assistant_message": None}, {"last_assistant_message": ""},
])
def test_quiet_settlement_releases_timing_for_the_next_turn_without_audio(patch):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, long_turn_seconds=120)
    service._intake(adapt_pi(payload("agent_start")), rules, 10)
    service._intake(adapt_pi(payload("ui_prompt_start")), rules, 11)
    assert len(service.queue.items) == 1
    service._intake(adapt_pi(payload(**patch)), rules, 12)
    assert not service.queue.items
    service._intake(adapt_pi(payload("agent_start", turn_id="next")), rules, 20)
    stop = adapt_pi(payload(turn_id="next"))
    service._intake(stop, rules, 160)
    pending, = service.queue.items
    assert pending.turn_seconds == 140
    assert service._long_turn(rules.classify(stop), pending.turn_seconds)


@pytest.mark.parametrize("quiet_turn", ["older", ""])
def test_unmatched_quiet_end_cannot_consume_current_timing_or_queued_attention(quiet_turn):
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, long_turn_seconds=120)
    service._intake(adapt_pi(payload("agent_start")), rules, 10)
    question = adapt_pi(payload("ui_prompt_start"))
    service._intake(question, rules, 11)
    service._intake(adapt_pi(payload(outcome="aborted", turn_id=quiet_turn)), rules, 12)
    assert [item.event for item in service.queue.items] == [question]
    service._intake(adapt_pi(payload()), rules, 140)
    pending, = service.queue.items
    assert pending.turn_seconds == 130


def test_quiet_end_removes_only_matching_session_and_turn_without_claiming_a_voice():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, session_voices=True, voice_player=lambda *_: None)
    now = time.monotonic()
    matching = adapt_pi(payload("ui_prompt_start"))
    others = [replace(matching, session_id="pi:other"), replace(matching, turn_id="newer")]
    for event in (matching, *others):
        service.queue.put(event, True, now=now, supersede=False)
    service._intake(adapt_pi(payload(outcome="aborted")), rules, now + 0.1)
    assert [item.event for item in service.queue.items] == others
    assert not service.voices.sessions


def test_ui_prompt_dedup_preserves_distinct_requests_and_suppresses_repeated_waiting():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    question = adapt_pi(payload("ui_prompt_start"))
    service._intake(question, rules, now)
    assert service.queue.get() == question
    service._intake(question, rules, now + 0.1)
    service._intake(adapt_pi(payload(last_assistant_message="I need your choice before continuing.")), rules, now + 0.2)
    assert not service.queue.items
    second = adapt_pi(payload("ui_prompt_start", request_id="8490b860-4555-4de5-98c6-6828722cf9b5"))
    service._intake(second, rules, now + 0.3)
    assert service.queue.get() == second


def test_final_pi_reply_resolves_queued_prompt_without_disturbing_another_provider():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None)
    now = time.monotonic()
    question = adapt_pi(payload("ui_prompt_start"))
    other = adapt_codex({"hook_event_name": "PermissionRequest", "session_id": "session-123",
                         "turn_id": "turn-456", "tool_name": "exec_command", "tool_input": {}})
    service._intake(question, rules, now)
    service._intake(other, rules, now)
    stop = adapt_pi(payload())
    service._intake(stop, rules, now + 0.1)
    assert service.queue.get() == other
    assert service.queue.get() == stop
    assert not service.queue.items


def test_pi_error_is_attention_and_a_fresh_start_clears_its_queued_failure():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, min_turn_seconds=30, long_turn_seconds=120)
    service._intake(adapt_pi(payload("agent_start")), rules, 10)
    error = adapt_pi(payload(outcome="error", last_assistant_message="PRIVATE ERROR"))
    service._intake(error, rules, 11)
    pending, = service.queue.items
    result = rules.classify(error)
    assert result.gesture == "failed" and pending.attention and pending.turn_seconds == 1
    assert service._suppression_reason(result, 1) is None and not service._long_turn(result, 200)
    service._intake(adapt_pi(payload("agent_start", turn_id="retry")), rules, 12)
    assert not service.queue.items
    service._intake(adapt_pi(payload(turn_id="retry")), rules, 17)
    pending, = service.queue.items
    assert pending.turn_seconds == 5


def test_live_pi_payloads_use_the_same_worker_and_hide_sensitive_metadata():
    with running_service(min_turn_seconds=30) as (service, path, played, logs):
        start = adapt_pi(payload("agent_start", prompt="PRIVATE PROMPT"))
        send_event(start, path)
        eventually(lambda: start.session_id in service.timings.sessions)
        send_event(adapt_pi(payload("ui_prompt_start", title="PRIVATE TITLE")), path)
        eventually(lambda: played == ["decision"])
        send_event(adapt_pi(payload(last_assistant_message="Done. PRIVATE RESULT")), path)
        eventually(lambda: len(logs) == 2)
        assert played == ["decision"] and logs[-1]["suppressed"] == "short-turn"
        send_event(adapt_pi(payload(turn_id="next", outcome="error", last_assistant_message="PRIVATE ERROR")), path)
        eventually(lambda: played == ["decision", "failed"])
        assert logs[-1]["failure_code"] == "unknown" and logs[-1]["evidence_source"] == "pi:agent_error"
        assert "PRIVATE" not in json.dumps(logs)


def test_live_pi_quiet_end_does_not_play_or_reserve_a_voice():
    played = []
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        quiet = adapt_pi(payload(outcome="aborted"))
        send_event(quiet, path)
        # The following status request is handled by the same listener and the
        # subsequent cue verifies that quiet metadata did not reserve a slot.
        control(path, service, "unmute")
        assert not service.voices.sessions and not played and not logs
        stop = adapt_pi(payload(session_id="different"))
        send_event(stop, path)
        eventually(lambda: len(played) == 1)
        assert played[0][2] == SESSION_VOICES[0]
        assert [record["evidence_source"] for record in logs] == ["pi:agent_settled"]


def test_pi_codex_and_claude_reuse_rotation_with_independent_sessions():
    rules = RulesClassifier()
    service = Service(rules, lambda *_: None, session_voices=True, voice_player=lambda *_: None)
    common = {"session_id": "same-id", "hook_event_name": "Stop", "last_assistant_message": "Done."}
    events = [adapt_claude(common), adapt_codex(common), adapt_pi(payload(session_id="same-id"))]
    for index, event in enumerate(events):
        service._intake(event, rules, 10 + index)
    assert [item.voice for item in service.queue.items] == list(SESSION_VOICES[:3])
    assert len(service.voices.sessions) == 3
    assert service.voices.assign(events[-1].session_id, 15) == SESSION_VOICES[2]


def test_global_mute_also_silences_pi_while_preserving_the_running_service():
    rules = RulesClassifier()
    with running_service() as (service, path, played, logs):
        assert control(path, service, "mute")["muted"]
        for source in (payload("agent_start"), payload("ui_prompt_start"), payload(outcome="error"), payload()):
            service._intake(adapt_pi(source), rules, time.monotonic())
        service._intake(adapt_codex({"hook_event_name": "Stop", "session_id": "other",
                                     "last_assistant_message": "Done."}), rules, time.monotonic())
        assert not played and not logs and not service.queue.items
        assert control(path, service, "unmute")["muted"] is False
        send_event(adapt_pi(payload(turn_id="fresh")), path)
        eventually(lambda: played == ["done"])
        assert service.ready.is_set() and len(logs) == 1


@pytest.mark.parametrize("patch", [{"outcome": "aborted"}, {"last_assistant_message": ""}])
def test_quiet_end_cancels_matching_classification_before_audio_admission(patch):
    entered, release = threading.Event(), threading.Event()

    class GatedClassifier:
        def classify(self, event):
            if event.evidence_source == "pi:ui_prompt_start":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=GatedClassifier()) as (service, path, played, logs):
        try:
            send_event(adapt_pi(payload("ui_prompt_start")), path)
            assert entered.wait(1)
            send_event(adapt_pi(payload(**patch)), path)
            eventually(lambda: service.queue.current is not None and service.queue.current.cancelled)
            # A subsequent turn is unaffected by cancellation of the old one.
            send_event(adapt_pi(payload(turn_id="next-turn")), path)
            release.set()
            eventually(lambda: played == ["done"])
            assert [row["suppressed"] for row in logs] == ["turn-ended", None]
            eventually(lambda: service.queue.current is None)
        finally:
            release.set()


@pytest.mark.parametrize("quiet_fields", [{"turn_id": "older-turn"}, {"session_id": "other-session"}, {"turn_id": ""}])
def test_quiet_end_cannot_cancel_another_active_session_or_turn(quiet_fields):
    entered, release = threading.Event(), threading.Event()

    class GatedClassifier:
        def classify(self, event):
            entered.set()
            assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=GatedClassifier()) as (service, path, played, logs):
        try:
            send_event(adapt_pi(payload("ui_prompt_start")), path)
            assert entered.wait(1)
            quiet = adapt_pi(payload(outcome="aborted", **quiet_fields))
            service._intake(quiet, RulesClassifier(), time.monotonic())
            assert service.queue.current is not None and not service.queue.current.cancelled
            release.set()
            eventually(lambda: played == ["decision"])
            assert logs[0]["suppressed"] is None
        finally:
            release.set()


def test_quiet_end_between_classification_and_admission_still_cancels_audio():
    entered, release = threading.Event(), threading.Event()
    with running_service() as (service, path, played, logs):
        def logger(record):
            logs.append(record)
            if record["evidence_source"] == "pi:ui_prompt_start":
                entered.set()
                assert release.wait(3)

        service.logger = logger
        try:
            send_event(adapt_pi(payload("ui_prompt_start")), path)
            assert entered.wait(1)
            send_event(adapt_pi(payload(outcome="aborted")), path)
            eventually(lambda: service.queue.current is not None and service.queue.current.cancelled)
            send_event(adapt_pi(payload(session_id="other-session")), path)
            release.set()
            eventually(lambda: played == ["done"])
            assert len(logs) == 2
        finally:
            release.set()


def test_quiet_end_leaves_an_already_admitted_cue_running():
    entered, release = threading.Event(), threading.Event()
    completed = []

    def player(gesture, _length):
        entered.set()
        assert release.wait(3)
        completed.append(gesture)

    with running_service(player=player) as (service, path, _, _):
        try:
            send_event(adapt_pi(payload("ui_prompt_start")), path)
            assert entered.wait(1)
            send_event(adapt_pi(payload(outcome="aborted")), path)
            eventually(lambda: service.queue.current is not None and service.queue.current.cancelled)
            release.set()
            eventually(lambda: completed == ["decision"])
            eventually(lambda: service.queue.current is None)
        finally:
            release.set()
