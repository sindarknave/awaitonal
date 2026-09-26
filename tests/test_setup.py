import json
from pathlib import Path

import pytest

from awaitonal.cli import hook_configuration, main
from awaitonal.setup import configure_hooks, hook_inventory


def fragment(tmp_path):
    executable = tmp_path / "path with spaces" / "awaitonal"
    executable.parent.mkdir(exist_ok=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    return hook_configuration(executable)


def test_preview_then_apply_backup_idempotent_and_remove(tmp_path):
    path = tmp_path / "settings.json"
    original = '{"model":"example", "hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo user"}]}]}}\n'
    path.write_text(original)
    hooks = fragment(tmp_path)
    preview = configure_hooks(path, hooks)
    assert preview["changed"] and not preview["applied"]
    assert path.read_text() == original
    applied = configure_hooks(path, hooks, apply=True)
    assert Path(applied["backup"]).read_text() == original
    first = path.read_text()
    assert not configure_hooks(path, hooks, apply=True)["changed"]
    assert path.read_text() == first
    configure_hooks(path, mode="uninstall", apply=True)
    assert json.loads(path.read_text()) == json.loads(original)
    assert not path.with_name("settings.json.awaitonal.json").exists()
    assert not configure_hooks(path, mode="uninstall", apply=True)["changed"]


def test_uninstall_preserves_modified_hooks_and_new_user_handlers(tmp_path):
    path = tmp_path / "settings.json"
    configure_hooks(path, fragment(tmp_path), apply=True)
    updated = json.loads(path.read_text())
    updated["hooks"]["Stop"][0]["hooks"][0]["command"] += " --custom"
    updated["hooks"]["PermissionRequest"][0]["hooks"].append({"type": "command", "command": "echo kept"})
    path.write_text(json.dumps(updated))
    configure_hooks(path, mode="uninstall", apply=True)
    remaining = json.loads(path.read_text())["hooks"]
    assert set(remaining) == {"Stop", "PermissionRequest"}
    assert remaining["Stop"][0]["hooks"][0]["command"].endswith(" --custom")
    assert remaining["PermissionRequest"][0]["hooks"] == [{"type": "command", "command": "echo kept"}]


def test_existing_unowned_identical_hook_is_not_adopted(tmp_path):
    path = tmp_path / "settings.json"
    hooks = fragment(tmp_path)
    path.write_text(json.dumps(hooks))
    assert not configure_hooks(path, hooks, apply=True)["changed"]
    configure_hooks(path, mode="uninstall", apply=True)
    assert json.loads(path.read_text()) == hooks


def test_plugin_migration_requires_owned_or_explicit_exact_legacy_handlers(tmp_path):
    path = tmp_path / "settings.json"
    hooks = fragment(tmp_path)
    path.write_text(json.dumps(hooks))
    assert not configure_hooks(path, mode="plugin", apply=True)["changed"]
    changed = configure_hooks(path, mode="plugin", legacy_fragment=hooks, apply=True)
    assert changed["changed"] and json.loads(path.read_text()) == {}
    configure_hooks(path, hooks, apply=True)
    configure_hooks(path, mode="plugin", apply=True)
    assert json.loads(path.read_text()) == {}


@pytest.mark.parametrize("raw", ["{", "[]", '{"hooks": []}', '{"hooks":{"Stop":[{}]}}'])
def test_malformed_settings_remain_untouched(tmp_path, raw):
    path = tmp_path / "settings.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        configure_hooks(path, fragment(tmp_path), apply=True)
    assert path.read_text() == raw


def test_settings_symlink_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_text("{}")
    path = tmp_path / "settings.json"
    path.symlink_to(target)
    with pytest.raises(ValueError):
        configure_hooks(path, fragment(tmp_path), apply=True)
    assert target.read_text() == "{}"


def test_duplicate_diagnostics_exclude_command_contents(tmp_path):
    path = tmp_path / "settings.json"
    data = fragment(tmp_path)
    data["enabledPlugins"] = {"awaitonal@awaitonal": True}
    path.write_text(json.dumps(data))
    inventory = hook_inventory(path)
    assert inventory["duplicates"] and inventory["plugin_enabled"]
    assert inventory["manual_hooks"]["Stop"] == 1
    assert "command" not in json.dumps(inventory)


def test_cli_setup_preview_and_apply(tmp_path, capsys):
    path = tmp_path / "settings.json"
    hooks = fragment(tmp_path)
    import shlex
    executable = shlex.split(hooks["hooks"]["Stop"][0]["hooks"][0]["command"])[0]
    arguments = ["init", "--settings", str(path), "--executable", executable]
    assert main(arguments) == 0
    assert "Preview only" in capsys.readouterr().out and not path.exists()
    assert main(arguments + ["--apply"]) == 0
    assert main(["uninstall", "--settings", str(path), "--apply"]) == 0
    assert json.loads(path.read_text()) == {}


def test_diff_never_displays_unrelated_settings_or_unchanged_hook_secrets(tmp_path):
    path = tmp_path / "settings.json"
    original = {"env": {"ANTHROPIC_API_KEY": "SYNTHETIC-CREDENTIAL"}, "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo UNRELATED-HOOK-TOKEN"}]}]}}
    path.write_text(json.dumps(original))
    installed = configure_hooks(path, fragment(tmp_path), apply=True)
    assert "SYNTHETIC-CREDENTIAL" not in installed["diff"]
    assert "UNRELATED-HOOK-TOKEN" not in installed["diff"]
    assert "awaitonal" in installed["diff"]
    removed = configure_hooks(path, mode="uninstall", apply=True)
    assert "SYNTHETIC-CREDENTIAL" not in removed["diff"]
    assert "UNRELATED-HOOK-TOKEN" not in removed["diff"]
    assert json.loads(path.read_text()) == original


def test_reinstall_does_not_move_owned_hooks_past_later_user_hooks(tmp_path):
    path = tmp_path / "settings.json"
    hooks = fragment(tmp_path)
    configure_hooks(path, hooks, apply=True)
    data = json.loads(path.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo later"}]})
    path.write_text(json.dumps(data))
    original = path.read_text()
    assert not configure_hooks(path, hooks, apply=True)["changed"]
    assert path.read_text() == original
