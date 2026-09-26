"""Lifecycle tests use private sockets and never the user's configured service."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

from awaitonal import __version__
from awaitonal import lifecycle as life


@contextmanager
def short_directory():
    with tempfile.TemporaryDirectory(prefix="aw-life-", dir="/tmp") as directory:
        yield Path(directory)


def identity(**changes):
    return {"service": "awaitonal", "protocol": 1, "version": __version__,
            "pid": os.getpid(), "instance_id": "a" * 32, "status": "running",
            "executable": str(Path(sys.executable).resolve()), "muted": False, **changes}


@contextmanager
def responding_socket(response):
    with short_directory() as directory:
        path = directory / "service.sock"
        requests, errors = [], []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o600)
            listener.listen(2)
            listener.settimeout(1)
            def respond():
                try:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(1)
                        data = bytearray()
                        while b"\n" not in data:
                            part = connection.recv(4096)
                            if not part:
                                return
                            data.extend(part)
                        requests.append(json.loads(data))
                        payload = response if isinstance(response, bytes) else json.dumps(response).encode() + b"\n"
                        connection.sendall(payload)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=respond)
            thread.start()
            try:
                yield path, requests
            finally:
                thread.join(2)
                assert not thread.is_alive()
                assert not errors


def test_missing_and_stale_service_status():
    with short_directory() as directory:
        path = directory / "service.sock"
        assert life.service_status(path)["reason"] == "missing"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o600)
        assert life.service_status(path)["reason"] == "stale"
        assert not life.stop_service(path)["changed"]


def test_status_verifies_protocol_and_version():
    with responding_socket(identity()) as (path, requests):
        result = life.service_status(path)
        assert result["status"] == "running"
        assert result["version_matches"] is True
    assert requests == [{"awaitonal_control": "status", "protocol": 1}]


def test_other_version_is_identified_without_claiming_compatibility():
    with responding_socket(identity(version="0.0.1")) as (path, _):
        assert life.service_status(path)["version_matches"] is False


@pytest.mark.parametrize("reply", [
    b"not json\n", b"{}\n", b"x" * 4097, b"", b"[]\n",
    identity(service="other"), identity(protocol=2), identity(protocol=True),
    identity(version=[]), identity(pid=True), identity(pid=0),
    identity(instance_id="invalid"), identity(status="stopping"),
    identity(executable="relative/path"),
    identity(muted=0), identity(muted=None),
])
def test_malformed_or_foreign_replies_are_not_stopped_services(reply):
    with responding_socket(reply) as (path, _):
        with pytest.raises(life.LifecycleError):
            life.service_status(path)


def test_untrusted_socket_directory_is_not_treated_as_missing():
    with short_directory() as directory:
        directory.chmod(0o755)
        with pytest.raises(life.LifecycleError):
            life.service_status(directory / "service.sock")


def test_start_refuses_unidentified_listener_without_spawning(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not spawn over an unidentified service")
    monkeypatch.setattr(life.subprocess, "Popen", forbidden)
    with responding_socket(identity(service="other")) as (path, _):
        with pytest.raises(life.LifecycleError):
            life.start_service(socket_path=path, executable=sys.executable)


def test_stop_installation_mismatch_sends_no_stop(monkeypatch):
    monkeypatch.setattr(life.os, "kill", lambda *args: pytest.fail("must not kill by claimed PID"))
    with responding_socket(identity(executable="/some/other/awaitonal")) as (path, requests):
        with pytest.raises(life.LifecycleError, match="another.*installation"):
            life.stop_service(path, expected_executable=sys.executable)
    assert [request["awaitonal_control"] for request in requests] == ["status"]


@pytest.mark.parametrize("muted", [True, False])
def test_mute_absent_service_fails_without_starting(muted, monkeypatch):
    monkeypatch.setattr(life.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not start a service"))
    with short_directory() as directory:
        with pytest.raises(life.LifecycleError, match="not running"):
            life.set_service_muted(muted, directory / "missing.sock")


@pytest.mark.parametrize("muted", [True, False])
def test_mute_installation_mismatch_sends_no_mutation(muted):
    with responding_socket(identity(executable="/some/other/awaitonal")) as (path, requests):
        with pytest.raises(life.LifecycleError, match="another.*installation"):
            life.set_service_muted(muted, path, expected_executable=sys.executable)
    assert [request["awaitonal_control"] for request in requests] == ["status"]


@pytest.mark.parametrize("version,capability", [("0.0.1", True), ("0.0.1", False), (__version__, False)])
def test_mute_older_service_requires_update_and_restart(version, capability):
    reply = identity(version=version)
    if not capability:
        reply.pop("muted")
    with responding_socket(reply) as (path, requests):
        with pytest.raises(life.LifecycleError, match="upgrade/restart"):
            life.set_service_muted(True, path)
    assert [request["awaitonal_control"] for request in requests] == ["status"]


@pytest.mark.parametrize("change", [
    {"instance_id": "b" * 32}, {"muted": False}, {"muted": 1}, {"changed": 1},
])
def test_mute_requires_same_instance_and_valid_state_reply(change, monkeypatch):
    original = identity(version_matches=True)
    monkeypatch.setattr(life, "service_status", lambda *args: original)
    with responding_socket({**identity(muted=True, changed=True), **change}) as (path, requests):
        with pytest.raises(life.LifecycleError, match="could not confirm mute"):
            life.set_service_muted(True, path)
    assert requests == [{"awaitonal_control": "mute", "protocol": 1, "instance_id": original["instance_id"]}]


def test_mute_and_unmute_verified_service_keep_classifier_instance():
    from test_service import running_service
    with running_service() as (service, path, played, logs):
        for muted in (True, False):
            first = life.set_service_muted(muted, path, expected_executable=sys.argv[0])
            repeated = life.set_service_muted(muted, path, expected_executable=sys.argv[0])
            assert first["changed"] is True and repeated["changed"] is False
            assert first["muted"] is muted and first["instance_id"] == service.instance_id
        assert played == logs == []


def test_start_failure_reports_exit_and_does_not_leave_a_service(tmp_path):
    executable = tmp_path / "failed startup"
    executable.write_text("#!/bin/sh\nexit 7\n")
    executable.chmod(0o700)
    with short_directory() as directory:
        path = directory / "service.sock"
        with pytest.raises(life.LifecycleError, match="exit 7"):
            life.start_service(executable=executable, socket_path=path)
        assert life.service_status(path)["status"] == "stopped"


def test_real_detached_silent_start_status_stop_are_idempotent():
    executable = Path(sys.executable).parent / "awaitonal"
    with short_directory() as directory:
        path = directory / "service.sock"
        started = None
        try:
            started = life.start_service(executable=executable, socket_path=path, silent=True)
            assert started["changed"] is True
            assert started["status"] == "running"
            assert started["version"] == __version__
            repeated = life.start_service(executable=executable, socket_path=path, silent=True)
            assert repeated["changed"] is False
            assert repeated["instance_id"] == started["instance_id"]
            status = life.service_status(path)
            assert status["instance_id"] == started["instance_id"]
            assert life.stop_service(path, expected_executable=executable)["changed"] is True
            assert life.stop_service(path)["changed"] is False
        finally:
            if started:
                life.stop_service(path, expected_executable=executable)
                # Reap only the child created by this test, never signal a PID
                # received from an arbitrary service identity.
                os.waitpid(started["pid"], 0)


def test_launch_agent_argv_preserves_spaces_and_xml_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    executable = tmp_path / "tool with & spaces"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    folder = tmp_path / "Agents with spaces"
    options = dict(executable=executable, directory=folder, label="dev.awaitonal.test",
                   socket_path=tmp_path / "private socket" / "s.sock",
                   config=tmp_path / "palette & custom.toml", classifier="semantic",
                   model_dir=tmp_path / "local model", semantic_config=tmp_path / "anchors config.json",
                   min_turn_seconds=12, silent=True, load=False)
    result = life.install_launch_agent(**options)
    path = Path(result["path"])
    document = plistlib.loads(path.read_bytes())
    assert result["changed"] is True
    assert document["ProgramArguments"] == life.service_command(
        **{key: value for key, value in options.items() if key not in ("directory", "label", "load")})
    assert document["KeepAlive"] == {"SuccessfulExit": False}
    assert path.stat().st_mode & 0o777 == 0o600
    assert life.install_launch_agent(**options)["changed"] is False
    assert life.uninstall_launch_agent(directory=folder, label=options["label"],
                                     expected_executable=executable, unload=False)["changed"] is True
    assert life.uninstall_launch_agent(directory=folder, label=options["label"], unload=False)["changed"] is False


def test_launch_agent_does_not_overwrite_foreign_file_or_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    label = "dev.awaitonal.test"
    path = tmp_path / (label + ".plist")
    path.write_text("unrelated configuration")
    options = dict(directory=tmp_path, label=label, executable=sys.executable, load=False)
    with pytest.raises(life.LifecycleError):
        life.install_launch_agent(**options)
    assert path.read_text() == "unrelated configuration"
    target = tmp_path / "other"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(life.LifecycleError):
        life.uninstall_launch_agent(directory=tmp_path, label=label, unload=False)
    assert path.is_symlink() and target.read_text() == "unrelated configuration"


def test_launch_agent_uninstall_preserves_other_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    installed = life.install_launch_agent(directory=tmp_path, executable=sys.executable, load=False)
    with pytest.raises(life.LifecycleError, match="another.*installation"):
        life.uninstall_launch_agent(directory=tmp_path, expected_executable="/different/awaitonal", unload=False)
    assert Path(installed["path"]).exists()


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_launch_agent_platform_handling(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(life.sys, "platform", platform)
    with pytest.raises(life.LifecycleError, match="macOS"):
        life.install_launch_agent(directory=tmp_path, executable=sys.executable, load=False)
    assert not list(tmp_path.iterdir())


def test_loaded_foreign_launch_agent_is_never_booted_out(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    calls = []
    def launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(life, "_launchctl", launchctl)
    with pytest.raises(life.LifecycleError, match="unowned"):
        life.install_launch_agent(directory=tmp_path, executable=sys.executable)
    assert [args[0] for args in calls] == ["print"]
    assert not list(tmp_path.iterdir())


def test_failed_login_start_rolls_back_new_job_and_file(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    calls = []
    def launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if args[0] == "print" else 0)
    monkeypatch.setattr(life, "_launchctl", launchctl)
    monkeypatch.setattr(life, "stop_service", lambda *args, **kwargs: {"status": "stopped"})
    def never_ready(*args):
        raise life.LifecycleError("not ready")
    monkeypatch.setattr(life, "_wait_running", never_ready)
    with pytest.raises(life.LifecycleError, match="not ready"):
        life.install_launch_agent(directory=tmp_path, executable=sys.executable)
    assert [args[0] for args in calls] == ["print", "bootstrap", "kickstart", "bootout"]
    assert not list(tmp_path.iterdir())


def test_failed_login_update_restores_previous_managed_job(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    installed = life.install_launch_agent(directory=tmp_path, executable=sys.executable, load=False)
    path = Path(installed["path"])
    previous = plistlib.loads(path.read_bytes())
    calls = []
    def launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(life, "_launchctl", launchctl)
    monkeypatch.setattr(life, "stop_service", lambda *args, **kwargs: {"status": "stopped"})
    def never_ready(*args):
        raise life.LifecycleError("not ready")
    monkeypatch.setattr(life, "_wait_running", never_ready)
    with pytest.raises(life.LifecycleError, match="not ready"):
        life.install_launch_agent(directory=tmp_path, executable=sys.executable,
                                  config=tmp_path / "different.toml")
    assert plistlib.loads(path.read_bytes()) == previous
    assert [args[0] for args in calls] == ["print", "bootout", "bootstrap", "kickstart", "bootout", "bootstrap"]


def test_loaded_but_stopped_login_job_is_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    life.install_launch_agent(directory=tmp_path, executable=sys.executable, load=False)
    calls = []
    def launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(life, "_launchctl", launchctl)
    monkeypatch.setattr(life, "service_status", lambda *args, **kwargs: {"status": "stopped"})
    monkeypatch.setattr(life, "stop_service", lambda *args, **kwargs: {"status": "stopped"})
    monkeypatch.setattr(life, "_wait_running", lambda *args: identity(version_matches=True))
    result = life.install_launch_agent(directory=tmp_path, executable=sys.executable)
    assert result["changed"] and result["loaded"]
    assert result["service"]["status"] == "running"
    assert [args[0] for args in calls] == ["print", "bootout", "bootstrap", "kickstart"]


def test_start_resumes_matching_login_agent_and_preserves_saved_options(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    monkeypatch.setattr(life.Path, "home", lambda: tmp_path)
    with short_directory() as directory:
        path = directory / "service.sock"
        installed = life.install_launch_agent(executable=sys.executable, socket_path=path,
                                             classifier="semantic", min_turn_seconds=37,
                                             model_dir=tmp_path / "chosen model", silent=True, load=False)
        agent_path = Path(installed["path"])
        saved = agent_path.read_bytes()
        calls = []
        def launchctl(*args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(life, "_launchctl", launchctl)
        monkeypatch.setattr(life, "service_status", lambda *args, **kwargs: {"status": "stopped"})
        monkeypatch.setattr(life, "_wait_running", lambda *args: identity(version_matches=True))
        monkeypatch.setattr(life.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must retain launchd supervision"))
        result = life.start_service(executable=sys.executable, socket_path=path)
        assert result["supervision"] == "launch_agent"
        assert result["status"] == "running"
        assert agent_path.read_bytes() == saved
        assert [args[0] for args in calls] == ["print", "kickstart"]
        # The previous process may still be exiting after its socket closes.
        assert calls[-1] == ("kickstart", "-k", f"gui/{os.getuid()}/{life.DEFAULT_LABEL}")


def test_start_does_not_resume_another_installations_or_sockets_job(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    monkeypatch.setattr(life.Path, "home", lambda: tmp_path)
    life.install_launch_agent(executable=sys.executable, socket_path=tmp_path / "first.sock", load=False)
    monkeypatch.setattr(life, "_launchctl", lambda *args, **kwargs: pytest.fail("unrelated job must not be controlled"))
    assert life._resume_login_agent([str(Path(sys.executable).resolve())], tmp_path / "other.sock", 1) is None
    assert life._resume_login_agent(["/different/awaitonal"], tmp_path / "first.sock", 1) is None


def test_known_shutdown_requires_confirmation_after_transient_closed_reply(monkeypatch):
    states = iter((life.LifecycleError("closed during shutdown"), {"status": "stopped", "reason": "missing"}))
    def status(*args):
        result = next(states)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(life, "service_status", status)
    assert life._wait_stopped("/unused", timeout=.5)["status"] == "stopped"


def test_install_never_evicts_managed_job_from_another_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(life.sys, "platform", "darwin")
    installed = life.install_launch_agent(directory=tmp_path, executable=sys.executable, load=False)
    path = Path(installed["path"])
    original = path.read_bytes()
    other = tmp_path / "different awaitonal"
    other.write_text("#!/bin/sh\nexit 0\n")
    other.chmod(0o700)
    calls = []
    def launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)  # The unrelated job is loaded.
    monkeypatch.setattr(life, "_launchctl", launchctl)
    with pytest.raises(life.LifecycleError, match="another.*installation"):
        life.install_launch_agent(directory=tmp_path, executable=other)
    assert not calls
    assert path.read_bytes() == original
