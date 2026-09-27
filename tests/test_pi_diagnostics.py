"""Pi owns registration; doctor must not claim that it inspected active extensions."""
import json
import sys
from pathlib import Path

import pytest

from awaitonal import __version__
from awaitonal.cli import main
from awaitonal.diagnostics import diagnose


def test_pi_doctor_checks_shared_service_without_reading_agent_settings(monkeypatch):
    from awaitonal import lifecycle, setup
    monkeypatch.setattr(lifecycle, "service_status", lambda _: {
        "status": "running", "version": __version__, "muted": True,
        "executable": str(Path(sys.executable).parent / "awaitonal"),
    })

    def unexpected(*args, **kwargs):
        raise AssertionError("Pi settings are owned by Pi")

    monkeypatch.setattr(setup, "default_settings", unexpected)
    monkeypatch.setattr(setup, "hook_inventory", unexpected)
    result = diagnose(adapter="pi")
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["service"]["status"] == "ok"
    assert checks["notifications"]["status"] == "ok"
    assert "muted" in checks["notifications"]["message"]
    assert checks["extension"]["status"] == "unknown"
    assert "pi list" in checks["extension"]["message"]
    assert result["settings_scope"] is None
    assert not result["audio_tested"]
    assert "hooks" not in checks


def test_pi_doctor_cli_reports_absent_service(tmp_path, capsys):
    assert main(["doctor", "--adapter", "pi", "--socket", str(tmp_path / "absent"), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result["ok"]
    assert any(check["name"] == "extension" and check["status"] == "unknown" for check in result["checks"])


def test_pi_doctor_rejects_settings_override_before_inspecting_any_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("unrelated content")
    with pytest.raises(ValueError, match="Pi manages its extensions"):
        diagnose(settings, adapter="pi")
    assert settings.read_text() == "unrelated content"
