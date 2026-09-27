"""Provider isolation, safe installation, and honest Codex diagnostics."""
import json
import shlex

import pytest

from awaitonal.cli import hook_configuration, main
from awaitonal.diagnostics import diagnose
from awaitonal.setup import configure_hooks, default_settings, hook_inventory


def executable(tmp_path):
    path = tmp_path / "path with spaces" / "awaitonal"
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return path


def test_codex_setup_uses_own_home_and_leaves_claude_untouched(tmp_path, monkeypatch, capsys):
    codex_home = tmp_path / "codex"
    claude_home = tmp_path / "claude"
    claude_home.mkdir()
    claude_settings = claude_home / "settings.json"
    claude_settings.write_text('{"keep": "claude"}\n')
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    assert default_settings("codex") == codex_home / "hooks.json"
    assert default_settings() == claude_settings
    args = ["init", "--adapter", "codex", "--executable", str(executable(tmp_path))]
    assert main(args) == 0
    assert not codex_home.exists()
    assert "Preview only" in capsys.readouterr().out
    assert main(args + ["--apply"]) == 0
    assert "trust" in capsys.readouterr().out
    path = codex_home / "hooks.json"
    hooks = json.loads(path.read_text())["hooks"]
    assert set(hooks) == {"Stop", "PreToolUse", "PermissionRequest", "UserPromptSubmit"}
    for groups in hooks.values():
        assert shlex.split(groups[0]["hooks"][0]["command"])[1:] == ["hook", "codex"]
    assert claude_settings.read_text() == '{"keep": "claude"}\n'
    assert main(["uninstall", "--adapter", "codex", "--apply"]) == 0
    assert json.loads(path.read_text()) == {}
    assert claude_settings.read_text() == '{"keep": "claude"}\n'


@pytest.mark.parametrize("mode", ["uninstall", "plugin"])
def test_codex_migration_removes_only_codex_owned_hooks_even_in_shared_file(tmp_path, mode):
    path = tmp_path / "mixed.json"
    binary = executable(tmp_path)
    claude = hook_configuration(binary)
    codex = hook_configuration(binary, adapter="codex")
    configure_hooks(path, claude, apply=True)
    configure_hooks(path, codex, adapter="codex", apply=True)
    assert hook_inventory(path)["manual_hooks"]["Stop"] == 1
    assert hook_inventory(path, adapter="codex")["manual_hooks"]["Stop"] == 1
    configure_hooks(path, adapter="codex", mode=mode, apply=True)
    assert json.loads(path.read_text()) == claude
    assert path.with_name("mixed.json.awaitonal.json").exists()
    assert not path.with_name("mixed.json.awaitonal-codex.json").exists()


def test_codex_preview_backup_and_idempotence_preserve_user_hooks(tmp_path):
    path = tmp_path / "hooks.json"
    original = '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo keep"}]}]}}\n'
    path.write_text(original)
    fragment = hook_configuration(executable(tmp_path), adapter="codex")
    assert configure_hooks(path, fragment, adapter="codex")["changed"]
    assert path.read_text() == original
    result = configure_hooks(path, fragment, adapter="codex", apply=True)
    from pathlib import Path
    assert Path(result["backup"]).read_text() == original
    installed = path.read_text()
    assert not configure_hooks(path, fragment, adapter="codex", apply=True)["changed"]
    assert path.read_text() == installed
    configure_hooks(path, adapter="codex", mode="uninstall", apply=True)
    assert json.loads(path.read_text()) == json.loads(original)


def test_codex_inventory_does_not_claim_plugin_or_trust_verification(tmp_path):
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"enabledPlugins": {"awaitonal@awaitonal": True}}))
    inventory = hook_inventory(path, adapter="codex")
    assert not inventory["plugin_enabled"]
    result = diagnose(path, tmp_path / "absent", adapter="codex")
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["hooks"]["status"] == "unknown"
    assert "inline" in checks["hooks"]["message"]
    assert checks["hook-trust"]["status"] == "unknown"
    assert "/hooks" in checks["hook-trust"]["message"]


def test_codex_hook_config_cli_routes_custom_socket_and_quotes_paths(tmp_path, capsys):
    binary = executable(tmp_path)
    socket = tmp_path / "socket with spaces"
    assert main(["hook-config", "--adapter", "codex", "--executable", str(binary),
                 "--socket", str(socket)]) == 0
    result = json.loads(capsys.readouterr().out)
    command = result["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert shlex.split(command) == [str(binary), "hook", "codex", "--socket", str(socket)]


def test_codex_doctor_cli_has_codex_scope(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert main(["doctor", "--adapter", "codex", "--socket", str(tmp_path / "absent"), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["settings_scope"] == str(tmp_path / "hooks.json")
    assert not result["audio_tested"]
