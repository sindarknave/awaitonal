"""Phrase variety belongs to admitted playback, never notification intake."""
import json
import threading
import time

import pytest

from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import Service
from awaitonal.types import Event
from awaitonal.voices import SESSION_VOICES
from test_service import eventually, running_service
from test_service_control import control


def playback_logs(logs):
    return [record for record in logs if record.get("event") == "playback"]


@pytest.mark.parametrize("ensemble", [False, True])
@pytest.mark.parametrize("long_turn", [False, True])
def test_live_answer_and_done_cycles_preserve_voice_and_long_turn_routing(ensemble, long_turn):
    varied, legacy = [], []
    rules = RulesClassifier()
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args),
                         session_voices=ensemble, voice_player=lambda *args: legacy.append(args),
                         long_turn_player=lambda *args: legacy.append(args),
                         long_turn_seconds=120) as (service, _, played, logs):
        for index in range(16):
            session = "PRIVATE-session-a" if index % 2 == 0 else "PRIVATE-session-b"
            gesture = "done" if (index // 2) % 2 == 0 else "answer"
            text = "Done." if gesture == "done" else "The server uses port 8080."
            now = time.monotonic()
            turn = str(index)
            service._intake(Event(session, "start", kind="turn-start", turn_id=turn), rules,
                            now - (150 if long_turn else 30))
            service._intake(Event(session, turn, text, evidence_source="claude:Stop", turn_id=turn), rules, now)
            eventually(lambda: len(playback_logs(logs)) == index + 1)
            expected_voice = SESSION_VOICES[index % 2] if ensemble else "default"
            assert varied[-1][:4] == (gesture, len(text), expected_voice, long_turn)
        assert not played and not legacy
        for offset in range(4):
            expected = ((1, 3) if offset < 2 else (2, 3)) if long_turn else ((0, 2) if offset < 2 else (0, 1))
            assert [entry[4] for entry in varied[offset::4]] == list(expected) * 2
        assert [entry["variation"] for entry in playback_logs(logs)] == [entry[4] for entry in varied]
        assert all(set(entry) == {"event", "gesture", "variation", "voice", "long_turn", "variation_group", "turn_seconds"}
                   for entry in playback_logs(logs))
        assert all(entry["variation_group"] == ("full" if long_turn else "light")
                   and entry["turn_seconds"] == (150 if long_turn else 30) for entry in playback_logs(logs))
        assert "PRIVATE" not in json.dumps(logs)


@pytest.mark.parametrize("source", ["claude:Stop", "codex:Stop", "pi:agent_settled"])
def test_matched_start_stop_tracks_variation_duration_with_other_timing_features_off(source):
    varied = []
    rules = RulesClassifier()
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args)) as (service, _, _, logs):
        for index, seconds in enumerate((119.999, 120, 30, 150)):
            now = time.monotonic()
            turn = str(index)
            service._intake(Event("s", "start", kind="turn-start", turn_id=turn), rules, now - seconds)
            assert service.timings.sessions["s"].started is not None
            service._intake(Event("s", turn, "Done.", evidence_source=source, turn_id=turn), rules, now)
            eventually(lambda: len(playback_logs(logs)) == index + 1)
        assert [entry[4] for entry in varied] == [0, 1, 2, 3]
        assert all(entry[3] is False for entry in varied)
        assert [entry["variation_group"] for entry in playback_logs(logs)] == ["light", "full", "light", "full"]
        assert [entry["turn_seconds"] for entry in playback_logs(logs)] == [119.999, 120, 30, 150]


def test_custom_group_mapping_and_cutoff_are_independent_of_extended_endings():
    varied = []
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args),
                         variation_groups={"done": {"light": (0, 1), "full": (3, 2)}},
                         variation_full_after_seconds=60, long_turn_seconds=120) as (service, _, _, logs):
        for index, seconds in enumerate((59, 60, 150, 40)):
            service.queue.put(Event("s", str(index), "Done."), turn_seconds=seconds)
            eventually(lambda: len(playback_logs(logs)) == index + 1)
        assert [(entry[4], entry[3]) for entry in varied] == [(0, False), (3, False), (2, True), (1, False)]


def test_missing_timing_uses_original_even_for_long_response_then_avoids_immediate_repeat():
    varied = []
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args)) as (service, _, _, logs):
        for index, text in enumerate(("Done.", "x" * 8000, "Done.")):
            service.queue.put(Event("s", str(index), text, explicit_state="done"))
            eventually(lambda: len(playback_logs(logs)) == index + 1)
        service.queue.put(Event("s", "timed", "Done."), turn_seconds=30)
        eventually(lambda: len(playback_logs(logs)) == 4)
        assert [entry[4] for entry in varied] == [0, 0, 0, 2]
        assert [entry["variation_group"] for entry in playback_logs(logs)] == ["ordinary"] * 3 + ["light"]
        assert [entry["turn_seconds"] for entry in playback_logs(logs)] == [None, None, None, 30]


@pytest.mark.parametrize("seconds", [-1, True, float("nan"), float("inf")])
def test_invalid_timing_logs_unknown_duration_and_uses_original(seconds):
    varied = []
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args)) as (service, _, _, logs):
        service.queue.put(Event("s", "1", "Done."), turn_seconds=seconds)
        eventually(lambda: len(playback_logs(logs)) == 1)
        assert varied[0][4] == 0
        assert playback_logs(logs)[0]["variation_group"] == "ordinary"
        assert playback_logs(logs)[0]["turn_seconds"] is None


@pytest.mark.parametrize("enabled", [False, True])
def test_variation_callback_routes_other_cues_and_unavailable_variants_as_original(enabled):
    varied = []
    with running_service(gesture_variations=enabled, variation_counts={"answer": 1, "done": 1},
                         variation_player=lambda *args: varied.append(args)) as (service, path, played, logs):
        for index, event in enumerate((Event("s", "done", "Done."),
                                       Event("s", "answer", "The server uses port 8080."),
                                       Event("s", "handoff", explicit_state="needs-you"))):
            send_event(event, path)
            eventually(lambda: len(varied) == index + 1)
        assert [entry[0] for entry in varied] == ["done", "answer", "needs-you"]
        assert all(entry[4] == 0 for entry in varied)
        assert not played and not playback_logs(logs)
        assert service.variations is None or not service.variations.sessions


def test_disabled_variations_with_callback_never_create_history():
    varied = []
    with running_service(variation_player=lambda *args: varied.append(args)) as (service, path, _, logs):
        for index in range(5):
            send_event(Event("s", str(index), "Done."), path)
            eventually(lambda: len(varied) == index + 1)
        assert [entry[4] for entry in varied] == [0] * 5
        assert service.variations is None and not playback_logs(logs)


def test_default_without_callback_keeps_legacy_player_and_log_shape():
    with running_service() as (service, path, played, logs):
        send_event(Event("s", "1", "Done."), path)
        eventually(lambda: played == ["done"])
        assert service.variations is None and len(logs) == 1
        assert "variation" not in logs[0] and "event" not in logs[0]


def test_suppressed_muted_and_duplicate_events_do_not_advance_a_cycle():
    varied = []
    rules = RulesClassifier()
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args),
                         min_turn_seconds=30) as (service, path, _, logs):
        now = time.monotonic()
        service._intake(Event("s", "start", kind="turn-start", turn_id="short"), rules, now - 1)
        service._intake(Event("s", "short", "Done.", evidence_source="claude:Stop", turn_id="short"), rules, now)
        eventually(lambda: any(record.get("suppressed") == "short-turn" for record in logs))
        assert not service.variations.sessions
        assert control(path, service, "mute")["muted"]
        service._intake(Event("s", "muted", "Done."), rules, now)
        assert not service.variations.sessions
        assert not control(path, service, "unmute")["muted"]
        event = Event("s", "first", "Done.", evidence_source="claude:Stop", turn_id="first")
        service._intake(Event("s", "start", kind="turn-start", turn_id="first"), rules, time.monotonic() - 40)
        service._intake(event, rules, time.monotonic())
        eventually(lambda: len(varied) == 1)
        service._intake(event, rules, time.monotonic())
        for index in range(1, 4):
            service._intake(Event("s", "start", kind="turn-start", turn_id=str(index)), rules, time.monotonic() - 40)
            service._intake(Event("s", str(index), "Done.", evidence_source="claude:Stop", turn_id=str(index)), rules, time.monotonic())
            eventually(lambda: len(varied) == index + 1)
        assert [entry[4] for entry in varied] == [0, 2, 0, 2]
        assert len(playback_logs(logs)) == 4


def test_queued_cues_that_expire_or_are_superseded_do_not_reserve_phrases():
    entered, release = threading.Event(), threading.Event()
    varied = []

    class GatedClassifier:
        def classify(self, event):
            if event.event_id == "gate":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=GatedClassifier(), gesture_variations=True,
                         variation_player=lambda *args: varied.append(args)) as (service, path, _, logs):
        try:
            send_event(Event("gate", "gate", explicit_state="needs-you"), path)
            assert entered.wait(2)
            now = time.monotonic()
            # Queue expiry uses receive time; insert directly so no wall-clock
            # sleeps or model timing are needed to exercise the boundary.
            assert service.queue.put(Event("expired", "expired", "Done."),
                                     now=now - service.queue.ttl - 1, turn_seconds=30)
            assert service.queue.put(Event("s", "old", "Done."), now=now, turn_seconds=30)
            assert service.queue.put(Event("s", "latest", "Done."), now=now, turn_seconds=30)
            assert not service.variations.sessions
            release.set()
            eventually(lambda: len(playback_logs(logs)) == 1)
            assert [entry[0] for entry in varied] == ["needs-you", "done"]
            assert varied[-1][4] == 0
            assert list(service.variations.sessions) == ["s"]
            assert not service.queue.items
        finally:
            release.set()


@pytest.mark.parametrize("cancel", ["quiet-end", "mute", "shutdown"])
def test_cancellation_after_classification_before_admission_consumes_no_variation(cancel):
    entered, release = threading.Event(), threading.Event()
    varied = []
    with running_service(gesture_variations=True, variation_player=lambda *args: varied.append(args)) as (service, path, _, logs):
        original_logger = service.logger

        def gated_logger(record):
            original_logger(record)
            if record.get("gesture") == "done" and record.get("event") != "playback":
                entered.set()
                assert release.wait(3)

        service.logger = gated_logger
        try:
            send_event(Event("s", "done", "Done.", turn_id="turn"), path)
            assert entered.wait(2)
            assert service.variations.sessions == {}
            if cancel == "quiet-end":
                service._intake(Event("s", "end", kind="turn-end", turn_id="turn"),
                                RulesClassifier(), time.monotonic())
            elif cancel == "mute":
                control(path, service, "mute")
            else:
                service._stop.set()
            release.set()
            eventually(lambda: service.queue.current is None)
            assert not varied and not playback_logs(logs) and not service.variations.sessions
        finally:
            release.set()


def test_playback_failure_consumes_only_its_admitted_variant_and_worker_recovers():
    attempts = []

    def failing_once(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise RuntimeError("PRIVATE callback details")

    with running_service(gesture_variations=True, variation_player=failing_once) as (service, path, played, logs):
        for index in range(4):
            service.queue.put(Event("s", str(index), "Done."), turn_seconds=150)
            eventually(lambda: len(attempts) == index + 1)
        eventually(lambda: len(playback_logs(logs)) == 3)
        assert [entry[4] for entry in attempts] == [1, 3, 1, 3]
        assert not played and {"error": "RuntimeError"} in logs
        assert "PRIVATE" not in json.dumps(logs)


@pytest.mark.parametrize("options", [
    {"gesture_variations": 1}, {"gesture_variations": "true"},
    {"gesture_variations": True}, {"variation_player": 1},
    {"variation_counts": {"done": 0}}, {"variation_counts": {"done": True}},
    {"variation_counts": {"review": 4}}, {"variation_counts": []},
    {"variation_groups": []}, {"variation_groups": {"done": {"light": [0], "full": [1]}}},
    {"variation_full_after_seconds": 0}, {"variation_full_after_seconds": True},
    {"variation_full_after_seconds": float("inf")},
])
def test_invalid_variation_configuration_fails_before_startup(options):
    with pytest.raises(ValueError):
        Service(RulesClassifier(), lambda *_: None, **options)
