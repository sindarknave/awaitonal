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


def test_first_three_sessions_get_unique_stable_voices_and_overflow_keeps_default():
    voices = SessionVoices(ttl=10)
    assert VOICE_NAMES == ("default", "wood", "glass", "round")
    assert tuple(voices.assign(name, 0) for name in ("a", "b", "c")) == SESSION_VOICES
    assert voices.assign("d", 0) == "default"
    assert voices.assign("c", 5) == "round"
    assert voices.assign("d", 5) == "default"
    # a/b expire, but c/d keep their identities; a new session takes the first
    # free instrument. The default voice does not opportunistically change.
    assert voices.assign("d", 10) == "default"
    assert voices.assign("new", 10) == "wood"
    assert voices.assign("c", 10) == "round"
    assert "a" not in voices.sessions and "b" not in voices.sessions


def test_idle_assignment_can_be_retired_but_never_evicts_an_active_neighbor():
    voices = SessionVoices(ttl=10)
    assert voices.assign("a", 0) == "wood"
    assert voices.assign("b", 1) == "glass"
    assert voices.assign("b", 9) == "glass"
    assert voices.assign("new", 10) == "wood"
    assert voices.assign("a", 11) == "round"
    assert voices.assign("b", 11) == "glass"


def test_capacity_overflow_never_evicts_or_reassigns_live_sessions():
    voices = SessionVoices(capacity=3, ttl=10)
    for name in ("a", "b", "c"):
        voices.assign(name, 0)
    for index in range(200):
        assert voices.assign(f"overflow-{index}", 1) == "default"
        assert len(voices.sessions) == 3
    assert voices.assign("c", 9) == "round"
    # a/b have expired, but the untracked overflow window still protects their
    # fallback assignment. Newly tracked default sessions stay default later.
    assert voices.assign("overflow-0", 10) == "default"
    assert voices.assign("new", 11) == "wood"
    assert voices.assign("overflow-0", 12) == "default"
    assert voices.assign("c", 12) == "round"
    assert len(voices.sessions) == 3


def test_active_untracked_overflow_extends_its_stability_window():
    voices = SessionVoices(capacity=1, ttl=10)
    assert voices.assign("a", 0) == "wood"
    assert voices.assign("overflow", 1) == "default"
    assert voices.assign("overflow", 9) == "default"
    assert voices.assign("overflow", 11) == "default"
    assert list(voices.sessions) == ["overflow"]
    assert voices.assign("overflow", 20) == "default"
    assert voices.assign("new", 30) == "wood"


@pytest.mark.parametrize("options", [
    {"capacity": 0}, {"capacity": True}, {"capacity": 1.5},
    {"ttl": 0}, {"ttl": -1}, {"ttl": True}, {"ttl": float("inf")}, {"ttl": float("nan")},
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
    with running_service(session_voices=True, voice_player=lambda *args: played.append(args)) as (service, path, _, logs):
        for session in ("PRIVATE-a", "PRIVATE-b", "PRIVATE-c", "PRIVATE-d"):
            send_event(Event(session, "start", kind="turn-start", evidence_source="claude:UserPromptSubmit"), path)
            eventually(lambda: session in service.voices.sessions)
        assert not played
        for session, voice in zip(("PRIVATE-c", "PRIVATE-a", "PRIVATE-d", "PRIVATE-b"),
                                  ("round", "wood", "default", "glass")):
            send_event(Event(session, "stop", "Done."), path)
            eventually(lambda: any(args[2] == voice for args in played))
        assert played == [("done", 5, voice, False) for voice in ("round", "wood", "default", "glass")]
        assert [record["voice"] for record in logs] == ["round", "wood", "default", "glass"]
        assert "PRIVATE" not in json.dumps(logs)


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
            assert service.voices.sessions["old"].voice == "glass"
        finally:
            release.set()
        eventually(lambda: played == [("done", 5, "wood", False)])
        assert logs[0]["voice"] == "wood"


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
        assert played == [("done", "wood" if ensemble else "default", not ensemble),
                          ("needs-you", "glass" if ensemble else "default", False)]
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
        eventually(lambda: played == [("done", 5, "wood", True)])
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
            eventually(lambda: played == [("done", 5, "wood", False)])
            assert service.voices.sessions["two"].voice == "glass"
        finally:
            release.set()
