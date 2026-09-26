import json
import os
from pathlib import Path
import selectors
import socket
import sys
import threading

import pytest

from awaitonal import __version__
from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import Service
from awaitonal.types import Event
from test_service import eventually, running_service


def request(path, payload):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(1)
        connection.connect(str(path))
        connection.sendall(json.dumps(payload).encode() + b"\n")
        response = connection.recv(4096)
        return json.loads(response) if response else None


def test_status_and_guarded_stop_reply_before_listener_exits():
    with running_service() as (service, path, played, logs):
        status = request(path, {"awaitonal_control": "status", "protocol": 1})
        assert status == {"service": "awaitonal", "protocol": 1, "version": __version__,
                          "pid": os.getpid(), "instance_id": service.instance_id, "status": "running",
                          "executable": str(Path(sys.argv[0]).resolve()), "muted": False}
        assert request(path, {"awaitonal_control": "stop", "protocol": 1, "instance_id": "wrong"}) is None
        assert not service._stop.is_set()
        response = request(path, {"awaitonal_control": "stop", "protocol": 1, "instance_id": service.instance_id})
        assert response["status"] == "stopping"
        assert response["instance_id"] == service.instance_id
        eventually(lambda: not path.exists())
        assert played == logs == []


@pytest.mark.parametrize("payload", [
    {"awaitonal_control": "status", "protocol": True},
    {"awaitonal_control": "status", "protocol": 2},
    {"awaitonal_control": "status"},
    {"awaitonal_control": "unknown", "protocol": 1},
    {"awaitonal_control": [], "protocol": 1},
    {"awaitonal_control": "status", "protocol": 1, "text": "Done."},
    {"awaitonal_control": "stop", "protocol": 1},
    {"awaitonal_control": "mute", "protocol": 1},
    {"awaitonal_control": "unmute", "protocol": 1},
    {"awaitonal_control": "mute", "protocol": 1, "instance_id": "wrong"},
    {"awaitonal_control": "unmute", "protocol": 1, "instance_id": "wrong"},
])
def test_malformed_controls_never_classify_or_stop(payload):
    with running_service() as (service, path, played, logs):
        assert request(path, payload) is None
        assert not service._stop.is_set() and not service.muted and played == logs == []


def test_control_requires_matching_peer_uid(monkeypatch):
    monkeypatch.setattr("awaitonal.service._peer_uid", lambda _connection: os.getuid() + 1)
    with running_service() as (service, path, played, logs):
        assert request(path, {"awaitonal_control": "status", "protocol": 1}) is None
        assert request(path, {"awaitonal_control": "stop", "protocol": 1,
                              "instance_id": service.instance_id}) is None
        for action in ("mute", "unmute"):
            assert request(path, {"awaitonal_control": action, "protocol": 1,
                                  "instance_id": service.instance_id}) is None
        assert not service.muted
        assert not service._stop.is_set() and played == logs == []


def test_failed_control_reply_does_not_stop_service(monkeypatch):
    monkeypatch.setattr("awaitonal.service._peer_uid", lambda _connection: os.getuid())

    class BrokenConnection:
        def settimeout(self, seconds):
            assert 0 < seconds <= 0.05
        def sendall(self, data):
            raise BrokenPipeError()

    service = Service(None, None)
    stop = threading.Event()
    assert service._control({"awaitonal_control": "stop", "protocol": 1,
                             "instance_id": service.instance_id}, BrokenConnection(), stop)
    assert not stop.is_set()


def control(path, service, action):
    return request(path, {"awaitonal_control": action, "protocol": 1, "instance_id": service.instance_id})


def test_mute_unmute_idempotence_keeps_instance_running():
    with running_service() as (service, path, played, logs):
        for action, muted in (("mute", True), ("unmute", False)):
            response = control(path, service, action)
            assert response["muted"] is muted and response["changed"] is True
            assert response["instance_id"] == service.instance_id
            assert response["status"] == "running"
            repeated = control(path, service, action)
            assert repeated["muted"] is muted and repeated["changed"] is False
            assert request(path, {"awaitonal_control": "status", "protocol": 1})["muted"] is muted
        assert not played and not logs and not service._stop.is_set()


def test_mute_discards_queued_and_classifying_events_even_after_unmute():
    entered, release = threading.Event(), threading.Event()

    class BlockingClassifier:
        def classify(self, event):
            if event.event_id == "classifying":
                entered.set()
                assert release.wait(3)
            return RulesClassifier().classify(event)

    with running_service(classifier=BlockingClassifier()) as (service, path, played, logs):
        try:
            send_event(Event("one", "classifying", text="Done."), path)
            assert entered.wait(2)
            send_event(Event("two", "queued", explicit_state="needs-you"), path)
            eventually(lambda: len(service.queue.items) == 1)
            assert control(path, service, "mute")["muted"]
            assert not service.queue.items
            # No queued or ongoing classification is allowed to revive when
            # mute is lifted before the classifier returns.
            assert control(path, service, "unmute")["muted"] is False
            release.set()
            eventually(lambda: any(row.get("suppressed") == "muted" for row in logs))
            assert not played
            send_event(Event("three", "fresh", text="Done."), path)
            eventually(lambda: played == ["done"])
        finally:
            release.set()


def test_mute_never_waits_for_current_player_and_next_cue_is_fresh():
    entered, release = threading.Event(), threading.Event()
    played = []

    def player(state, _length):
        played.append(state)
        if len(played) == 1:
            entered.set()
            assert release.wait(3)

    with running_service(player=player) as (service, path, _, logs):
        try:
            send_event(Event("one", "playing", text="Done."), path)
            assert entered.wait(2)
            send_event(Event("two", "queued", explicit_state="needs-you"), path)
            eventually(lambda: len(service.queue.items) == 1)
            # Both controls must reply while synchronous playback is blocked.
            assert control(path, service, "mute")["muted"]
            assert control(path, service, "unmute")["muted"] is False
            send_event(Event("three", "fresh", explicit_state="rejected"), path)
            eventually(lambda: len(service.queue.items) == 1)
            release.set()
            eventually(lambda: played == ["done", "rejected"])
        finally:
            release.set()


def test_mute_between_logging_and_playback_prevents_admission():
    entered, release = threading.Event(), threading.Event()
    with running_service() as (service, path, played, logs):
        def logger(record):
            logs.append(record)
            if len(logs) == 1:
                entered.set()
                assert release.wait(3)
        service.logger = logger
        try:
            send_event(Event("one", "before-mute", text="Done."), path)
            assert entered.wait(2)
            control(path, service, "mute")
            control(path, service, "unmute")
            release.set()
            send_event(Event("two", "fresh", explicit_state="rejected"), path)
            eventually(lambda: played == ["rejected"])
        finally:
            release.set()


def test_intake_received_before_mute_cannot_revive_in_same_batch():
    service = Service(None, None)
    event = Event("one", "old-batch", text="Done.")
    generation = service._mute_generation
    # Exercise the listener's deferred-intake path with the captured receipt
    # generation, after later controls in its batch have toggled mute twice.
    service.muted = True
    service._mute_generation += 1
    service.muted = False
    service._intake(event, RulesClassifier(), 1, generation)
    assert not service.queue.items
    service._intake(Event("two", "fresh", text="Done."), RulesClassifier(), 2)
    assert len(service.queue.items) == 1


def test_muted_event_then_unmute_in_same_read_batch_never_queues_event(monkeypatch):
    original_selector = selectors.DefaultSelector
    collect_batch = threading.Event()
    batch_sent = threading.Event()

    class BatchedSelector:
        """Hold client reads until both test sockets have been accepted."""
        def __init__(self):
            self.selector = original_selector()
            self.listener = None

        def __getattr__(self, name):
            return getattr(self.selector, name)

        def register(self, fileobj, *args):
            if self.listener is None:
                self.listener = fileobj
            return self.selector.register(fileobj, *args)

        def select(self, timeout):
            ready = self.selector.select(timeout)
            if collect_batch.is_set():
                if len(self.selector.get_map()) < 3:
                    return [(key, mask) for key, mask in ready if key.fileobj is self.listener]
                assert batch_sent.wait(1)
                ready = self.selector.select(timeout)
                # Connections are accepted in order: notification, unmute.
                assert len(ready) == 2
                collect_batch.clear()
                return sorted(ready, key=lambda entry: entry[0].fd)
            return ready

    monkeypatch.setattr("awaitonal.service.selectors.DefaultSelector", BatchedSelector)
    with running_service() as (service, path, played, logs):
        assert control(path, service, "mute")["muted"]
        collect_batch.set()
        with socket.socket(socket.AF_UNIX) as event_connection, socket.socket(socket.AF_UNIX) as unmute_connection:
            event_connection.connect(str(path))
            event_connection.sendall(json.dumps(Event("muted", "discard", "Done.").to_dict()).encode() + b"\n")
            unmute_connection.settimeout(2)
            unmute_connection.connect(str(path))
            unmute_connection.sendall(json.dumps({"awaitonal_control": "unmute", "protocol": 1,
                                                 "instance_id": service.instance_id}).encode() + b"\n")
            batch_sent.set()
            assert json.loads(unmute_connection.recv(4096))["muted"] is False
        send_event(Event("fresh", "after-unmute", explicit_state="rejected"), path)
        eventually(lambda: played == ["rejected"])
        assert len(logs) == 1 and not collect_batch.is_set()


def test_mute_state_is_not_inherited_by_new_service():
    with running_service() as (service, path, _, _):
        assert control(path, service, "mute")["muted"]
    with running_service() as (service, path, _, _):
        assert request(path, {"awaitonal_control": "status", "protocol": 1})["muted"] is False
