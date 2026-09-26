import json
import threading
import time

import pytest

from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import EventQueue, Service
from awaitonal.types import Event
from awaitonal.voices import SESSION_VOICES, VOICE_NAMES, SessionVoices
from test_service import eventually, running_service
from test_service_control import control, request


def test_new_sessions_rotate_without_repeating_until_each_voice_is_used():
    voices = SessionVoices(ttl=10)
    assigned = tuple(voices.assign(f"session-{index}", 0)
                     for index in range(len(SESSION_VOICES) * 2))
    assert assigned == SESSION_VOICES * 2
    assert set(SESSION_VOICES) <= set(VOICE_NAMES)
    for index, voice in enumerate(assigned):
        assert voices.assign(f"session-{index}", 5) == voice
    # Refreshing existing sessions must not consume a new rotation slot.
    assert voices.assign("new", 5) == SESSION_VOICES[0]


def test_explicit_cycle_is_copied_and_respects_requested_order():
    cycle = [SESSION_VOICES[2], "default", SESSION_VOICES[0]]
    voices = SessionVoices(voice_cycle=cycle)
    cycle.clear()
    assert tuple(voices.assign(str(index), 0) for index in range(6)) == voices.voice_cycle * 2


def test_single_voice_cycle_keeps_all_sessions_on_that_voice():
    voices = SessionVoices(voice_cycle=(SESSION_VOICES[0],))
    assert {voices.assign(str(index), 0) for index in range(12)} == {SESSION_VOICES[0]}


def test_least_used_voice_wins_and_equal_counts_follow_the_cursor():
    cycle = SESSION_VOICES[:3]
    voices = SessionVoices(ttl=10, voice_cycle=cycle)
    for index in range(5):
        assert voices.assign(str(index), 0) == cycle[index % 3]
    # The third voice now has one user; the first two each have two.
    assert voices.assign("5", 1) == cycle[2]
    assert voices.assign("6", 1) == cycle[0]
    # Keep only two users of voice 0 and one of voice 1 alive. Voice 2 must
    # be reused before any occupied voice even though the cursor points to 1.
    for session in ("3", "4", "6"):
        voices.assign(session, 5)
    assert voices.assign("unused", 11) == cycle[2]
    # Counts are now 2, 1, 1 and the cursor is 0: skip its more-used voice.
    assert voices.assign("least-used", 11) == cycle[1]
    # Counts 2, 2, 1 force voice 2 again, then equal counts rotate from 0.
    assert voices.assign("least-used-again", 11) == cycle[2]
    assert voices.assign("tie", 11) == cycle[0]


def test_idle_assignment_can_be_retired_but_never_evicts_an_active_neighbor():
    cycle = SESSION_VOICES[:3]
    voices = SessionVoices(ttl=10, voice_cycle=cycle)
    assert voices.assign("a", 0) == cycle[0]
    assert voices.assign("b", 1) == cycle[1]
    assert voices.assign("b", 9) == cycle[1]
    assert voices.assign("new", 10) == cycle[2]
    assert "a" not in voices.sessions
    assert voices.assign("a", 11) == cycle[0]
    assert voices.assign("b", 11) == cycle[1]


def test_expiring_all_sessions_preserves_rotation_but_restart_resets_it():
    voices = SessionVoices(ttl=10)
    assert voices.assign("a", 0) == SESSION_VOICES[0]
    assert voices.assign("b", 10) == SESSION_VOICES[1]
    assert list(voices.sessions) == ["b"]
    assert SessionVoices(ttl=10).assign("b", 10) == SESSION_VOICES[0]


def test_capacity_overflow_never_evicts_or_reassigns_live_sessions():
    cycle = SESSION_VOICES[:3]
    voices = SessionVoices(capacity=3, ttl=10, voice_cycle=cycle)
    for name in ("a", "b", "c"):
        voices.assign(name, 0)
    for index in range(200):
        assert voices.assign(f"overflow-{index}", 1) == "default"
        assert len(voices.sessions) == 3
    assert voices.assign("c", 9) == cycle[2]
    # a/b have expired, but the untracked overflow window still protects their
    # fallback assignment. Newly tracked default sessions stay default later.
    assert voices.assign("overflow-0", 10) == "default"
    assert voices.assign("new", 11) == cycle[0]
    assert voices.assign("overflow-0", 12) == "default"
    assert voices.assign("c", 12) == cycle[2]
    assert len(voices.sessions) == 3


def test_active_untracked_overflow_extends_its_stability_window():
    voices = SessionVoices(capacity=1, ttl=10)
    assert voices.assign("a", 0) == SESSION_VOICES[0]
    assert voices.assign("overflow", 1) == "default"
    assert voices.assign("overflow", 9) == "default"
    assert voices.assign("overflow", 11) == "default"
    assert list(voices.sessions) == ["overflow"]
    assert voices.assign("overflow", 20) == "default"
    assert voices.assign("new", 30) == SESSION_VOICES[1]


@pytest.mark.parametrize("options", [
    {"capacity": 0}, {"capacity": True}, {"capacity": 1.5},
    {"ttl": 0}, {"ttl": -1}, {"ttl": True}, {"ttl": float("inf")}, {"ttl": float("nan")},
    {"voice_cycle": []}, {"voice_cycle": ()}, {"voice_cycle": "wood"},
    {"voice_cycle": b"wood"}, {"voice_cycle": {"default"}}, {"voice_cycle": 3},
    {"voice_cycle": ["unknown"]}, {"voice_cycle": ["default", "default"]},
    {"voice_cycle": [None]}, {"voice_cycle": [[]]},
])
def test_registry_rejects_invalid_bounds(options):
    with pytest.raises(ValueError):
        SessionVoices(**options)


@pytest.mark.parametrize("options", [
    {"session_voices": 1}, {"voice_player": 1}, {"session_voices": True},
])
def test_service_rejects_invalid_voice_configuration(options):
    with pytest.raises(ValueError):
        Service(RulesClassifier(), lambda *_: None, **options)


@pytest.mark.parametrize("cycle", [[], "wood", ["unknown"], ["default", "default"], [None]])
def test_service_rejects_invalid_custom_cycles_before_starting(cycle):
    with pytest.raises(ValueError, match="voice cycle"):
        Service(RulesClassifier(), lambda *_: None, session_voices=True,
                voice_player=lambda *_: None, voice_cycle=cycle)


def test_other_session_waiting_ignores_same_session_expired_entries_and_closed_queue():
    queue = EventQueue(ttl=8)
    assert queue.put(Event("same", "1", "Done."), now=1)
    assert not queue.other_session_waiting("same", now=2)
    assert queue.other_session_waiting("other", now=2)
    assert not queue.other_session_waiting("other", now=9)
    queue.close()
    assert not queue.other_session_waiting("other", now=2)


def test_session_voice_is_assigned_at_start_and_inherited_by_notifications():
    played = []
    sessions = ("PRIVATE-a", "PRIVATE-b", "PRIVATE-c", "PRIVATE-d")
    expected = dict(zip(sessions, (SESSION_VOICES[index % len(SESSION_VOICES)] for index in range(4))))
    stop_order = ("PRIVATE-c", "PRIVATE-a", "PRIVATE-d", "PRIVATE-b")
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        for session in sessions:
            send_event(Event(session, "start", kind="turn-start", evidence_source="claude:UserPromptSubmit"), path)
            eventually(lambda: session in service.voices.sessions)
        assert not played
        for index, session in enumerate(stop_order):
            send_event(Event(session, "stop", "Done."), path)
            eventually(lambda: len(played) == index + 1)
        assert played == [("done", 5, expected[session], False) for session in stop_order]
        assert [record["voice"] for record in logs] == [expected[session] for session in stop_order]
        assert "PRIVATE" not in json.dumps(logs)


def test_service_uses_custom_rotation_and_keeps_existing_session_identity():
    played = []
    cycle = (SESSION_VOICES[-1], SESSION_VOICES[0])
    with running_service(session_voices=True, voice_cycle=cycle,
                         voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        for index, session in enumerate(("a", "b", "c", "b")):
            send_event(Event(session, str(index), "Done."), path)
            eventually(lambda: len(played) == index + 1)
        assert [args[2] for args in played] == [cycle[0], cycle[1], cycle[0], cycle[1]]
        assert [record["voice"] for record in logs] == [args[2] for args in played]
        assert service.voices.voice_cycle == cycle


def test_default_service_does_not_allocate_or_log_session_voices():
    voice_played = []
    with running_service(voice_player=lambda *args: voice_played.append(args)) as (service, path, played, logs):
        send_event(Event("s", "1", "Done."), path)
        eventually(lambda: played == ["done"])
        assert service.voices is None
        assert not voice_played
        assert "voice" not in logs[0] and "burst_compacted" not in logs[0]


def test_worker_preserves_captured_voice_if_registry_retires_session_during_classification():
    entered, release = threading.Event(), threading.Event()
    played = []

    class PausedClassifier:
        def classify(self, event):
            if event.event_id == "blocked":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=PausedClassifier(), session_voices=True,
                         voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        try:
            send_event(Event("old", "blocked", "Done."), path)
            assert entered.wait(2)
            # Change only the listener's simulated idle time; the Pending voice
            # belongs to the event, not to the next owner of this slot.
            service.voices.sessions.clear()
            service._intake(Event("new", "start", kind="turn-start"), RulesClassifier(), time.monotonic())
            service._intake(Event("old", "start", kind="turn-start"), RulesClassifier(), time.monotonic())
            assert service.voices.sessions["old"].voice == SESSION_VOICES[2]
        finally:
            release.set()
        eventually(lambda: played == [("done", 5, SESSION_VOICES[0], False)])
        assert logs[0]["voice"] == SESSION_VOICES[0]


@pytest.mark.parametrize("ensemble", [False, True])
def test_burst_uses_normal_routine_duration_only_when_session_voices_are_enabled(ensemble):
    entered, release = threading.Event(), threading.Event()
    played = []

    class PausedClassifier:
        def classify(self, event):
            if event.session_id == "long":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    options = {"session_voices": ensemble, "voice_player": lambda g, n, v, long: played.append((g, v, long)),
               "long_turn_player": lambda g, n: played.append((g, "default", True))}
    with running_service(classifier=PausedClassifier(), player=lambda g, n: played.append((g, "default", False)),
                         long_turn_seconds=120, **options) as (service, path, _, logs):
        try:
            now = time.monotonic()
            service._intake(Event("long", "start", kind="turn-start", turn_id="t"), RulesClassifier(), now - 150)
            service._intake(Event("long", "done", "Done.", evidence_source="claude:Stop", turn_id="t"),
                            RulesClassifier(), now)
            assert entered.wait(2)
            send_event(Event("urgent", "handoff", explicit_state="needs-you"), path)
            eventually(lambda: len(service.queue.items) == 1)
        finally:
            release.set()
        eventually(lambda: len(played) == 2)
        assert played == [("done", SESSION_VOICES[0] if ensemble else "default", not ensemble),
                          ("needs-you", SESSION_VOICES[1] if ensemble else "default", False)]
        assert logs[0]["long_turn"] is (not ensemble)
        if ensemble:
            assert logs[0]["burst_compacted"] is True
            assert logs[1]["burst_compacted"] is False


def test_single_session_keeps_long_turn_voice_and_duration():
    played = []
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args),
                         long_turn_seconds=120) as (service, _, _, logs):
        now = time.monotonic()
        service._intake(Event("long", "start", kind="turn-start", turn_id="t"), RulesClassifier(), now - 150)
        service._intake(Event("long", "done", "Done.", evidence_source="claude:Stop", turn_id="t"),
                        RulesClassifier(), now)
        eventually(lambda: played == [("done", 5, SESSION_VOICES[0], True)])
        assert logs[0]["long_turn"] and not logs[0]["burst_compacted"]


def test_mute_preserves_voice_but_never_revives_classifying_queued_or_muted_events():
    entered, release = threading.Event(), threading.Event()
    played = []

    class PausedClassifier:
        def classify(self, event):
            if event.event_id == "classifying":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=PausedClassifier(), session_voices=True,
                         voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        try:
            send_event(Event("one", "classifying", "Done."), path)
            assert entered.wait(2)
            send_event(Event("two", "queued", explicit_state="needs-you"), path)
            eventually(lambda: len(service.queue.items) == 1)
            assert control(path, service, "mute")["muted"]
            assert not service.queue.items
            send_event(Event("muted-new", "start", kind="turn-start", evidence_source="claude:UserPromptSubmit"), path)
            # A status request is a listener barrier after the muted event.
            assert request(path, {"awaitonal_control": "status", "protocol": 1})["muted"]
            assert "muted-new" not in service.voices.sessions
            assert control(path, service, "unmute")["muted"] is False
            release.set()
            eventually(lambda: any(record.get("suppressed") == "muted" for record in logs))
            assert not played
            send_event(Event("one", "fresh", "Done."), path)
            eventually(lambda: played == [("done", 5, SESSION_VOICES[0], False)])
            assert service.voices.sessions["two"].voice == SESSION_VOICES[1]
        finally:
            release.set()
