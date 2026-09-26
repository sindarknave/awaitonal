"""Untrusted Unix endpoints must never receive notification text."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
from types import SimpleNamespace

import pytest

from awaitonal import client
from awaitonal.types import Event


EVENT = Event("session", "event", "Private notification text.")


@contextmanager
def listener():
    # Keep paths below the Unix socket path limit on macOS.
    with tempfile.TemporaryDirectory(prefix="aw-client-", dir="/tmp") as directory:
        path = Path(directory) / "service.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)
            server.settimeout(0.05)
            yield server, path


def assert_no_connection(server):
    with pytest.raises(socket.timeout):
        server.accept()


def assert_connected_without_payload(server):
    connection, _ = server.accept()
    with connection:
        connection.settimeout(0.2)
        assert connection.recv(1) == b""


@pytest.mark.parametrize("target,mode", [
    ("directory", 0o755), ("directory", 0o770),
    ("socket", 0o644), ("socket", 0o666),
])
def test_permissive_endpoints_receive_no_connection(target, mode):
    with listener() as (server, path):
        (path.parent if target == "directory" else path).chmod(mode)
        with pytest.raises(ValueError):
            client.send_event(EVENT, path)
        assert_no_connection(server)


@pytest.mark.parametrize("target", ["directory", "socket"])
def test_foreign_owner_receives_no_connection(monkeypatch, target):
    with listener() as (server, path):
        foreign = path.parent if target == "directory" else path
        original = Path.lstat

        def lstat(candidate):
            info = original(candidate)
            if candidate == foreign:
                return SimpleNamespace(st_uid=os.getuid() + 1, st_mode=info.st_mode,
                                       st_dev=info.st_dev, st_ino=info.st_ino)
            return info

        monkeypatch.setattr(Path, "lstat", lstat)
        with pytest.raises(ValueError):
            client.send_event(EVENT, path)
        assert_no_connection(server)


def test_socket_symlink_receives_no_connection():
    with listener() as (server, path):
        alias = path.with_name("alias.sock")
        alias.symlink_to(path)
        with pytest.raises(ValueError):
            client.send_event(EVENT, alias)
        assert_no_connection(server)


def test_parent_symlink_receives_no_connection():
    with listener() as (server, path):
        alias = path.parent / "alias"
        alias.symlink_to(path.parent, target_is_directory=True)
        with pytest.raises(ValueError):
            client.send_event(EVENT, alias / path.name)
        assert_no_connection(server)


@pytest.mark.parametrize("target", ["directory", "socket"])
def test_non_socket_or_non_directory_is_rejected(tmp_path, target):
    tmp_path.chmod(0o700)
    regular = tmp_path / "regular"
    regular.write_text("not a socket")
    regular.chmod(0o600)
    path = regular / "service.sock" if target == "directory" else regular
    with pytest.raises(ValueError):
        client.send_event(EVENT, path)


def test_foreign_connected_peer_receives_no_payload(monkeypatch):
    with listener() as (server, path):
        monkeypatch.setattr(client, "_peer_uid", lambda connection: os.getuid() + 1)
        with pytest.raises(ValueError, match="peer"):
            client.send_event(EVENT, path)
        assert_connected_without_payload(server)


def test_unavailable_peer_credentials_receive_no_payload(monkeypatch):
    with listener() as (server, path):
        def unavailable(connection):
            raise OSError("credentials unavailable")

        monkeypatch.setattr(client, "_peer_uid", unavailable)
        with pytest.raises(OSError):
            client.send_event(EVENT, path)
        assert_connected_without_payload(server)


def test_endpoint_replacement_receives_no_payload(monkeypatch):
    with listener() as (server, path):
        original = client._endpoint_identity
        calls = 0

        def replaced(candidate):
            nonlocal calls
            calls += 1
            identity = original(candidate)
            return (*identity[:-1], identity[-1] + 1) if calls == 2 else identity

        monkeypatch.setattr(client, "_endpoint_identity", replaced)
        with pytest.raises(ValueError, match="changed"):
            client.send_event(EVENT, path)
        assert_connected_without_payload(server)


def test_peer_validation_does_not_restart_the_send_deadline(monkeypatch):
    with listener() as (server, path):
        # Start, before connect, after credentials: the original 80 ms budget
        # has expired, so even an authenticated peer must receive no payload.
        ticks = iter((0.0, 0.01, 0.081))
        monkeypatch.setattr(client.time, "monotonic", lambda: next(ticks))
        with pytest.raises(TimeoutError):
            client.send_event(EVENT, path)
        assert_connected_without_payload(server)


def test_private_same_user_listener_receives_event_without_reply():
    with listener() as (server, path):
        client.send_event(EVENT, path)
        connection, _ = server.accept()
        with connection:
            connection.settimeout(0.2)
            data = bytearray()
            while chunk := connection.recv(8192):
                data.extend(chunk)
        assert json.loads(data) == EVENT.to_dict()


class CredentialsSocket:
    def __init__(self, credentials):
        self.credentials = credentials
        self.requests = []

    def getsockopt(self, level, option, size):
        self.requests.append((level, option, size))
        return self.credentials


def test_linux_kernel_credentials_extract_uid(monkeypatch):
    monkeypatch.setattr(client.sys, "platform", "linux")
    monkeypatch.setattr(client.socket, "SO_PEERCRED", 17, raising=False)
    connection = CredentialsSocket(struct.pack("=iII", 123, 456, 789))
    assert client._peer_uid(connection) == 456
    assert connection.requests == [(socket.SOL_SOCKET, 17, 12)]


def test_macos_kernel_credentials_extract_uid(monkeypatch):
    monkeypatch.setattr(client.sys, "platform", "darwin")
    monkeypatch.setattr(client.socket, "LOCAL_PEERCRED", 1, raising=False)
    connection = CredentialsSocket(struct.pack("=II", 0, 456) + bytes(68))
    assert client._peer_uid(connection) == 456
    assert connection.requests == [(0, 1, 76)]


def test_macos_unknown_credential_version_is_rejected(monkeypatch):
    monkeypatch.setattr(client.sys, "platform", "darwin")
    monkeypatch.setattr(client.socket, "LOCAL_PEERCRED", 1, raising=False)
    with pytest.raises(OSError):
        client._peer_uid(CredentialsSocket(struct.pack("=II", 1, os.getuid()) + bytes(68)))


def test_getpeereid_platform_support():
    connection = SimpleNamespace(getpeereid=lambda: (456, 789))
    assert client._peer_uid(connection) == 456
