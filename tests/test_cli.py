import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import wave

import pytest


def cli(*args):
    return subprocess.run([sys.executable, "-m", "awaitonal", *map(str, args)],
                          capture_output=True, text=True, timeout=20)


def test_render_and_classify_commands(tmp_path):
    target = tmp_path / "demo.wav"
    result = cli("demo", "--out", target)
    assert result.returncode == 0, result.stderr
    with wave.open(str(target)) as sound:
        assert sound.getnchannels() == 1
        assert sound.getframerate() == 48000
        assert 19 < sound.getnframes() / sound.getframerate() < 22
    result = cli("classify", "--text", "Done. Integration tests were unavailable.", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "caveats"


def test_neutral_outcome_and_long_turn_audition(tmp_path):
    result = cli("classify", "--text", "Thanks for the context.", "--json")
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["state"] == "unknown" and output["gesture"] == "answer"
    normal, long = tmp_path / "normal.wav", tmp_path / "long.wav"
    for path, flags in ((normal, ()), (long, ("--long-turn",))):
        rendered = cli("play", "verdict", "--out", path, *flags)
        assert rendered.returncode == 0, rendered.stderr
    with wave.open(str(normal)) as short_wav, wave.open(str(long)) as long_wav:
        assert long_wav.getnframes() - short_wav.getnframes() == 38400


def test_explicit_cli_reports_service_missing(tmp_path):
    result = cli("notify", "--text", "Done.", "--socket", tmp_path / "absent")
    assert result.returncode == 1
    assert "awaitonal:" in result.stderr


def test_explicit_cli_reports_empty_prose_and_missing_model(tmp_path):
    result = cli("classify", "--text", "```\nprint('done')\n```", "--json")
    assert result.returncode == 1
    assert "no assistant prose" in result.stderr
    result = cli("classify", "--text", "Done.", "--classifier", "semantic", "--model-dir", tmp_path / "missing")
    assert result.returncode == 1
    assert "model-setup" in result.stderr


@pytest.mark.parametrize("backend", ["rules", pytest.param("semantic", marks=pytest.mark.semantic)])
def test_foreground_cli_hook_from_unrelated_directory_and_clean_stop(backend):
    model = os.getenv("AWAITONAL_TEST_MODEL")
    if backend == "semantic" and not model:
        pytest.skip("Set AWAITONAL_TEST_MODEL for real offline semantic service integration")
    with tempfile.TemporaryDirectory(prefix="at-cli-", dir="/tmp") as directory:
        socket_path = Path(directory) / "s.sock"
        command = [sys.executable, "-m", "awaitonal", "serve", "--silent", "--socket", str(socket_path), "--classifier", backend]
        if backend == "semantic":
            command.extend(["--model-dir", model])
        environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        process = subprocess.Popen(command, cwd=directory, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 30
            while not socket_path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert socket_path.exists(), process.communicate(timeout=1)
            payload = {"hook_event_name": "PermissionRequest", "session_id": "cli-integration", "tool_name": "Bash", "tool_input": {"command": "pwd"}}
            hook = subprocess.run([sys.executable, "-m", "awaitonal", "hook", "claude", "--socket", str(socket_path)],
                                  input=json.dumps(payload), capture_output=True, text=True, cwd=directory, timeout=2)
            assert hook.returncode == 0 and not hook.stdout and not hook.stderr
            # Read a classification record from the foreground service itself.
            import select
            deadline = time.monotonic() + 3
            found = False
            received = ""
            while time.monotonic() < deadline:
                if select.select([process.stderr], [], [], .1)[0]:
                    received += os.read(process.stderr.fileno(), 65536).decode()
                    for line in received.splitlines(keepends=True):
                        if line.endswith("\n") and line.startswith("{") and json.loads(line).get("state") == "needs-you":
                            found = True
                    if found:
                        break
            assert found
        finally:
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, stderr
            assert not stdout
            assert not socket_path.exists()
