import json
import os
from pathlib import Path
import socket
import sys
import threading

import pytest

from awaitonal import __version__
from awaitonal.service import Service
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
                          "executable": str(Path(sys.argv[0]).resolve())}
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
])
def test_malformed_controls_never_classify_or_stop(payload):
    with running_service() as (service, path, played, logs):
        assert request(path, payload) is None
        assert not service._stop.is_set() and played == logs == []


def test_control_requires_matching_peer_uid(monkeypatch):
    monkeypatch.setattr("awaitonal.service._peer_uid", lambda _connection: os.getuid() + 1)
    with running_service() as (service, path, played, logs):
        assert request(path, {"awaitonal_control": "status", "protocol": 1}) is None
        assert request(path, {"awaitonal_control": "stop", "protocol": 1,
                              "instance_id": service.instance_id}) is None
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
