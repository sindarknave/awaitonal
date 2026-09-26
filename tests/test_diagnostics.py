import json

import pytest

from awaitonal import __version__
from awaitonal.cli import main
from awaitonal.diagnostics import diagnose


def test_doctor_reports_absent_service_and_no_audio_test(tmp_path):
    result = diagnose(tmp_path / "settings.json", tmp_path / "absent.sock")
    assert not result["ok"] and not result["audio_tested"]
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["service"]["status"] == "needs-attention"
    assert checks["hooks"]["status"] == "needs-attention"


def test_doctor_reports_version_and_duplicates_without_command_content(tmp_path, monkeypatch):
    from awaitonal import lifecycle
    monkeypatch.setattr(lifecycle, "service_status", lambda _: {"status": "running", "version": "0.0.1"})
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enabledPlugins": {"awaitonal@awaitonal": True}, "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "/private/SECRET/awaitonal hook claude"}]}]}}))
    result = diagnose(path)
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["version"]["status"] == "needs-attention"
    assert checks["duplicates"]["status"] == "needs-attention"
    assert checks["hook-executables"]["status"] == "needs-attention"
    assert checks["installation"]["status"] == "needs-attention"
    assert "SECRET" not in json.dumps(result)


def test_doctor_cli_json_and_explicit_audio_only(tmp_path, capsys, monkeypatch):
    from awaitonal import playback
    calls = []
    monkeypatch.setattr(playback, "play_file", lambda *args, **kwargs: calls.append(args))
    args = ["doctor", "--settings", str(tmp_path / "none"), "--socket", str(tmp_path / "absent"), "--json"]
    assert main(args) == 1
    assert not json.loads(capsys.readouterr().out)["audio_tested"] and not calls
    assert main(args + ["--test-sound"]) == 1
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["audio_tested"] is True


@pytest.mark.parametrize("muted", [False, True])
def test_doctor_explains_intentional_mute_without_calling_it_broken(tmp_path, monkeypatch, muted):
    from awaitonal import lifecycle
    monkeypatch.setattr(lifecycle, "service_status", lambda _: {
        "status": "running", "version": __version__, "muted": muted,
    })
    result = diagnose(tmp_path / "settings.json")
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["notifications"]["status"] == "ok"
    if muted:
        assert "muted" in checks["notifications"]["message"]
        assert "awaitonal service unmute" in checks["notifications"]["message"]
        assert "warm" in checks["notifications"]["message"]
    else:
        assert checks["notifications"]["message"] == "notifications unmuted"
