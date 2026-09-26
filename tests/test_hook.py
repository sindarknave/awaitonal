"""Exercise the actual process boundary without audio or an ML installation."""
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from awaitonal.adapter import MAX_INPUT
from awaitonal.cli import hook_configuration


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def hook(args=None, data=b"", *, cwd=None, env=None):
    environment = os.environ.copy()
    environment["AWAITONAL_SOCKET"] = str(ROOT / "work-missing-service.sock")
    if env:
        environment.update(env)
    return subprocess.run([sys.executable, "-m", "awaitonal", *(args or ["hook", "claude"])],
                          input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=5, cwd=cwd or ROOT, env=environment)


@pytest.mark.parametrize("data", [
    b"", b"not json", b"{", b"null", b"[]", b"42", b"{}", b"\xff\xfe",
    b'{"hook_event_name":"Stop","session_id":"s"}',
    b"x" * (MAX_INPUT + 1),
    json.dumps({"session_id": "s", "hook_event_name": "Stop",
                "last_assistant_message": "Done. " + "x" * MAX_INPUT}).encode(),
])
def test_bad_hook_input_is_silent_success(data):
    result = hook(data=data)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize("args", [
    ["hook"], ["hook", "unknown"], ["hook", "claude", "--unknown"],
    ["hook", "claude", "--socket"], ["hook", "claude", "--help"],
    ["hook", "claude", "unexpected-positional"],
])
def test_bad_normal_hook_flags_are_silent_success(args):
    result = hook(args)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.parametrize("name", ["stop", "question", "permission", "subagent", "missing-text"])
def test_normal_hook_is_silent_when_service_absent(name, tmp_path):
    result = hook(data=(EXAMPLES / f"claude-{name}.json").read_bytes(), cwd=tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_closed_socket_service_failure_is_silent(tmp_path):
    fake_socket = tmp_path / "not-a-socket"
    fake_socket.write_text("not a socket")
    result = hook(["hook", "claude", "--socket", str(fake_socket)],
                  (EXAMPLES / "claude-stop.json").read_bytes())
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_untrusted_socket_is_silent_and_receives_no_connection():
    with tempfile.TemporaryDirectory(prefix="aw-hook-", dir="/tmp") as directory:
        path = Path(directory) / "service.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o600)
            path.parent.chmod(0o755)
            listener.listen(1)
            listener.settimeout(0.05)
            result = hook(["hook", "claude", "--socket", str(path)],
                          (EXAMPLES / "claude-stop.json").read_bytes())
            assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
            with pytest.raises(socket.timeout):
                listener.accept()


@pytest.mark.skipif(os.name != "posix", reason="The local service uses Unix sockets")
@pytest.mark.parametrize("size,should_send", [(MAX_INPUT, True), (MAX_INPUT + 1, False)])
def test_hook_input_byte_limit_and_handoff_without_service_response(size, should_send):
    base = (EXAMPLES / "claude-stop.json").read_bytes()
    # Padding keeps the complete input valid JSON, isolating the byte limit.
    data = base + b" " * (size - len(base))
    # A short root avoids macOS's small Unix socket pathname limit.
    with tempfile.TemporaryDirectory(prefix="aw-hook-", dir="/tmp") as directory:
        path = Path(directory) / "service.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o600)
            listener.listen(1)
            listener.settimeout(0.15)
            # Do not accept or reply until after the hook exits. Classification
            # and service acknowledgement cannot be prerequisites for exit.
            result = hook(["hook", "claude", "--socket", str(path)], data)
            assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")
            if not should_send:
                with pytest.raises(socket.timeout):
                    listener.accept()
            else:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(0.5)
                    chunks = []
                    while part := connection.recv(8192):
                        chunks.append(part)
                wire = b"".join(chunks)
                assert wire.endswith(b"\n")
                event = json.loads(wire)
                assert event["text"] == "Implemented the fix and all tests pass."
                assert event["evidence_source"] == "claude:Stop"
                assert "transcript_path" not in event


@pytest.mark.parametrize("name,state", [("stop", "done"), ("question", "needs-you"),
                                       ("permission", "needs-you"), ("subagent", None),
                                       ("missing-text", None)])
def test_dry_run_fixtures_report_routing_without_service(name, state):
    result = hook(["hook", "claude", "--dry-run"],
                  (EXAMPLES / f"claude-{name}.json").read_bytes())
    assert result.returncode == 0
    assert result.stderr == b""
    report = json.loads(result.stdout)
    if state is None:
        assert report["ignored"] is True
    else:
        assert report["state"] == state
        assert report["evidence_source"].startswith("claude:")


def test_hook_does_not_import_audio_classifier_or_ml():
    script = r'''
import builtins
import sys
attempts = []
original_import = builtins.__import__
forbidden = {"numpy", "torch", "sentence_transformers", "transformers", "huggingface_hub",
             "classify", "semantic", "synth", "playback"}
def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden or name.split(".")[-1] in forbidden:
        attempts.append(name)
        raise AssertionError("normal hook must not import " + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from awaitonal.cli import main
assert main(["hook", "claude"]) == 0
assert not attempts, attempts
'''
    env = os.environ.copy()
    env["AWAITONAL_SOCKET"] = str(ROOT / "work-missing-service.sock")
    result = subprocess.run([sys.executable, "-c", script],
                            input=(EXAMPLES / "claude-stop.json").read_bytes(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, env=env)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


@pytest.mark.skipif(os.name != "posix", reason="Unix hook stdin uses select")
def test_open_stdin_pipe_without_eof_has_bounded_exit():
    env = os.environ.copy()
    env["AWAITONAL_SOCKET"] = str(ROOT / "work-missing-service.sock")
    start = time.monotonic()
    process = subprocess.Popen([sys.executable, "-m", "awaitonal", "hook", "claude"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)
    try:
        process.stdin.write((EXAMPLES / "claude-stop.json").read_bytes())
        process.stdin.flush()
        # Deliberately keep stdin open. The client must not wait indefinitely.
        assert process.wait(timeout=3) == 0
        assert time.monotonic() - start < 3
        assert process.stdout.read() == b""
        assert process.stderr.read() == b""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def test_explicit_notify_reports_service_failure():
    result = hook(["notify", "--text", "Done."])
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"awaitonal:" in result.stderr


def test_generated_hooks_have_only_notification_handlers(tmp_path):
    executable = tmp_path / "awaitonal"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    config = hook_configuration(executable)
    assert set(config["hooks"]) == {"Stop", "PreToolUse", "PermissionRequest"}
    assert config["hooks"]["PreToolUse"][0]["matcher"] in ("AskUserQuestion", "^AskUserQuestion$")
    for groups in config["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                assert handler["type"] == "command"
                assert handler["timeout"] == 2
                assert "async" not in handler
                assert "asyncRewake" not in handler
                parts = shlex.split(handler["command"])
                assert Path(parts[0]).is_absolute()
                assert parts[1:] == ["hook", "claude"]
                assert "--dry-run" not in parts


@pytest.mark.skipif(os.name != "posix", reason="Generated hooks target POSIX shells")
def test_generated_command_quotes_spaces_and_shell_metacharacters(tmp_path):
    directory = tmp_path / "folder with spaces"
    directory.mkdir()
    executable = directory / "await'onal $(touch INJECTED) `touch OTHER`"
    executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    executable.chmod(0o700)
    socket_path = directory / "sock '; touch THIRD; '"
    config = hook_configuration(executable, socket_path)
    command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert shlex.split(command) == [str(executable), "hook", "claude", "--socket", str(socket_path)]
    result = subprocess.run(command, shell=True, cwd=tmp_path, text=True,
                            capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["hook", "claude", "--socket", str(socket_path)]
    assert result.stderr == ""
    assert not any((tmp_path / name).exists() for name in ("INJECTED", "OTHER", "THIRD"))


def test_generated_config_is_inspectable_cli_output(tmp_path):
    executable = tmp_path / "awaitonal"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    result = hook(["hook-config", "--executable", str(executable)])
    assert result.returncode == 0
    assert result.stderr == b""
    assert json.loads(result.stdout) == hook_configuration(executable)


def test_hook_config_rejects_missing_executable(tmp_path):
    result = hook(["hook-config", "--executable", str(tmp_path / "missing")])
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"executable not found" in result.stderr
