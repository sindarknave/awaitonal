"""Plugin bootstrap and provider routing without modifying real app settings."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Plugin targets macOS/Linux shells")


@pytest.fixture
def plugin_env(tmp_path):
    # Both install paths may contain spaces, as on a normal macOS machine.
    source = tmp_path / "plugin cache" / "0.3.0"
    shutil.copytree(ROOT / "scripts", source / "scripts")
    runtime = tmp_path / "user data" / "plugin runtime"
    bin_dir = tmp_path / "test bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    log = tmp_path / "calls"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "AWAITONAL_PLUGIN_RUNTIME": str(runtime),
        "CALLS": str(log),
    }
    return source, runtime, bin_dir, log, env


def script(plugin_env, action, *args, data=""):
    source, _, _, _, env = plugin_env
    return subprocess.run(
        ["/bin/sh", str(source / "scripts/plugin-runtime.sh"), action, *args],
        input=data, text=True, capture_output=True, env=env, timeout=10,
    )


def install_fake_runtime(plugin_env):
    _, runtime, _, _, _ = plugin_env
    executable = runtime / "bin/awaitonal"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\n')
    executable.chmod(0o700)
    return executable


def install_fake_uv(plugin_env, fails=False):
    _, _, bin_dir, _, _ = plugin_env
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/bin/sh\n'
        'printf "uv %s\\n" "$*" >> "$CALLS"\n'
        'printf "tools %s\\nbin %s\\n" "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" >> "$CALLS"\n'
        + ('exit 1\n' if fails else 'exit 0\n')
    )
    uv.chmod(0o700)


def test_marketplace_resolves_to_same_plugin_root_and_hooks_are_not_duplicated():
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    assert marketplace["plugins"][0]["source"] == "./"
    assert marketplace["plugins"][0]["name"] == manifest["name"] == "awaitonal"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]
    assert "hooks" not in manifest  # hooks/hooks.json is automatically loaded.
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
    assert set(hooks) == {"Stop", "StopFailure", "PermissionRequest", "PreToolUse", "UserPromptSubmit"}
    assert hooks["PreToolUse"][0]["matcher"] == "AskUserQuestion"
    for groups in hooks.values():
        assert len(groups) == 1
        assert len(groups[0]["hooks"]) == 1
        handler = groups[0]["hooks"][0]
        assert handler["timeout"] <= 2
        assert "plugin-hook.sh" in handler["command"]
        assert "--dry-run" not in handler["command"]


def test_codex_manifest_disables_bundled_hooks_and_template_uses_supported_events():
    portable = json.loads((ROOT / "plugin.json").read_text())
    compatibility = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert portable["name"] == compatibility["name"] == "awaitonal"
    assert portable["version"] == compatibility["version"] == project["version"]
    extension = portable["extensions"]["com.openai"]
    assert extension["interface"] == compatibility["interface"]
    assert extension["hooks"] == compatibility["hooks"] == []
    # Setup manages Codex's user hooks so removal must not depend on a live
    # plugin cache. Empty overrides also prevent discovering Claude's defaults.
    hooks_path = ROOT / "hooks/codex.json"
    hooks = json.loads(hooks_path.read_text())["hooks"]
    assert set(hooks) == {"Stop", "PermissionRequest", "PreToolUse", "UserPromptSubmit"}
    matcher = hooks["PreToolUse"][0]["matcher"]
    for name in ("request_user_input", "request_user_input_async"):
        assert re.fullmatch(matcher, name)
    for name in ("AskUserQuestion", "exec_command", "request_user_input_extra"):
        assert not re.fullmatch(matcher, name)
    for groups in hooks.values():
        assert len(groups) == len(groups[0]["hooks"]) == 1
        handler = groups[0]["hooks"][0]
        assert handler["type"] == "command" and handler["timeout"] <= 2
        assert "${PLUGIN_ROOT}" in handler["command"] and "--adapter codex" in handler["command"]
        assert "--dry-run" not in handler["command"]


@pytest.mark.parametrize("adapter", ["claude", "codex"])
@pytest.mark.parametrize("installed", [False, True])
def test_plugin_hook_is_quiet_and_successful_even_when_runtime_fails(plugin_env, installed, adapter):
    source, _, _, log, env = plugin_env
    if installed:
        executable = install_fake_runtime(plugin_env)
        executable.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
            'printf "unexpected output"\nprintf "unexpected error" >&2\nexit 17\n'
        )
    result = subprocess.run(
        ["/bin/sh", str(source / "scripts/plugin-hook.sh"), "--adapter", adapter],
        input='{"hook_event_name":"Stop","last_assistant_message":"Done."}',
        text=True, capture_output=True, env=env, timeout=2,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    assert log.read_text() == f"hook {adapter}\n" if installed else not log.exists()


@pytest.mark.parametrize("name,root_variable", [("hooks.json", "CLAUDE_PLUGIN_ROOT"), ("codex.json", "PLUGIN_ROOT")])
def test_registered_hook_is_quiet_if_old_plugin_cache_has_been_removed(tmp_path, name, root_variable):
    hooks = json.loads((ROOT / "hooks" / name).read_text())["hooks"]
    command = hooks["Stop"][0]["hooks"][0]["command"]
    result = subprocess.run(
        ["/bin/sh", "-c", command], capture_output=True, text=True, timeout=2,
        env={**os.environ, root_variable: str(tmp_path / "removed plugin cache")},
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


def test_setup_reinstalls_in_stable_path_and_migrates_after_service_is_ready(plugin_env):
    source, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "setup", "--settings", "/tmp/custom settings.json")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls == [
        f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal",
        f"uv tool install --python >=3.11 --force --reinstall-package awaitonal {source}",
        f"tools {runtime}/tools",
        f"bin {runtime}/bin",
        "awaitonal service start",
        "awaitonal init --adapter claude --mode plugin --apply --settings /tmp/custom settings.json",
    ]
    # A new plugin cache version still installs into the exact same runtime.
    moved_source = source.with_name("0.3.1")
    source.rename(moved_source)
    updated_env = (moved_source, *plugin_env[1:])
    assert script(updated_env, "setup").returncode == 0
    assert log.read_text().count(f"bin {runtime}/bin\n") == 2


def test_failed_update_restarts_existing_runtime_and_does_not_change_hooks(plugin_env):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env, fails=True)
    result = script(plugin_env, "setup")
    assert result.returncode == 1
    calls = log.read_text()
    assert calls.startswith(f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal\n")
    assert calls.endswith("awaitonal service start\n")
    assert "init" not in calls


def test_setup_does_not_migrate_hooks_when_service_start_fails(plugin_env):
    _, _, _, log, _ = plugin_env
    executable = install_fake_runtime(plugin_env)
    executable.write_text(
        '#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\n'
        'if [ "$1 $2" = "service start" ]; then exit 1; fi\n'
    )
    install_fake_uv(plugin_env)
    assert script(plugin_env, "setup").returncode == 1
    assert "init" not in log.read_text()


def test_setup_refuses_to_replace_runtime_when_service_ownership_is_uncertain(plugin_env):
    _, runtime, _, log, _ = plugin_env
    executable = install_fake_runtime(plugin_env)
    executable.write_text(
        '#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\nexit 1\n'
    )
    install_fake_uv(plugin_env)
    assert script(plugin_env, "setup").returncode == 1
    assert log.read_text() == f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal\n"


def test_setup_without_uv_fails_before_stopping_existing_service(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, "setup")
    assert result.returncode == 1
    assert "needs uv" in result.stderr
    assert not log.exists()


def test_status_is_read_only_and_does_not_require_uv(plugin_env):
    _, _, _, log, _ = plugin_env
    assert script(plugin_env, "status").returncode == 1
    assert not log.exists()
    install_fake_runtime(plugin_env)
    assert script(plugin_env, "status", "--json").returncode == 0
    assert log.read_text() == "awaitonal doctor --adapter claude --json\n"


@pytest.mark.parametrize("action", ["mute", "unmute"])
def test_mute_controls_use_only_owned_runtime_without_uv(plugin_env, action):
    _, runtime, _, log, _ = plugin_env
    missing = script(plugin_env, action)
    assert missing.returncode == 1
    assert "/awaitonal:setup" in missing.stderr
    assert not log.exists()
    install_fake_runtime(plugin_env)
    result = script(plugin_env, action)
    assert result.returncode == 0, result.stderr
    assert log.read_text() == f"awaitonal service {action} --expected-executable {runtime}/bin/awaitonal\n"


@pytest.mark.parametrize("action", ["mute", "unmute"])
def test_mute_control_failure_is_not_reported_as_success(plugin_env, action):
    executable = install_fake_runtime(plugin_env)
    executable.write_text('#!/bin/sh\nprintf "service unavailable\\n" >&2\nexit 17\n')
    result = script(plugin_env, action)
    assert result.returncode == 17
    assert "service unavailable" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("action", ["mute", "unmute"])
def test_mute_controls_reject_arguments_before_touching_runtime(plugin_env, action):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, action, "30m")
    assert result.returncode == 1
    assert "takes no arguments" in result.stderr
    assert not log.exists()


def test_uninstall_removes_only_managed_runtime_after_stopping_service(plugin_env):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "uninstall")
    assert result.returncode == 0
    expected = [f"awaitonal service uninstall --expected-executable {runtime}/bin/awaitonal"] if sys.platform == "darwin" else []
    assert log.read_text().splitlines() == expected + [
        f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal",
        "uv tool uninstall awaitonal",
        f"tools {runtime}/tools",
        f"bin {runtime}/bin",
    ]
    assert "claude plugin uninstall awaitonal@awaitonal" in result.stdout


def test_relative_runtime_path_is_rejected(plugin_env):
    plugin_env[-1]["AWAITONAL_PLUGIN_RUNTIME"] = "relative directory"
    result = script(plugin_env, "setup")
    assert result.returncode == 1
    assert "absolute path" in result.stderr


def test_codex_setup_targets_only_codex_after_shared_runtime_is_ready(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "setup", "--adapter", "codex", "--settings", "/tmp/codex hooks.json")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls[-2:] == ["awaitonal service start",
                          "awaitonal init --adapter codex --mode standalone --apply --settings /tmp/codex hooks.json"]
    assert not any("claude" in line for line in calls)


def test_codex_status_is_read_only_and_routes_the_provider(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, "status", "--adapter", "codex", "--json")
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "awaitonal doctor --adapter codex --json\n"


@pytest.mark.parametrize("args", [("--adapter",), ("--adapter", "other"), ("--adapter=codex",),
                                   ("--settings", "/tmp/hooks.json", "--adapter", "codex")])
def test_adapter_errors_fail_before_installing_or_stopping_service(plugin_env, args):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "setup", *args)
    assert result.returncode == 1
    assert "adapter" in result.stderr
    assert not log.exists()


@pytest.mark.parametrize("args", [("--adapter",), ("--adapter", "other"), ("codex",)])
def test_hook_rejects_unrecognized_provider_quietly(plugin_env, args):
    source, _, _, log, env = plugin_env
    install_fake_runtime(plugin_env)
    result = subprocess.run(["/bin/sh", str(source / "scripts/plugin-hook.sh"), *args],
                            input="{}", text=True, capture_output=True, env=env, timeout=2)
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert not log.exists()


def test_registered_codex_hook_uses_codex_even_with_claude_compatibility_variables(plugin_env):
    source, _, _, log, env = plugin_env
    install_fake_runtime(plugin_env)
    command = json.loads((ROOT / "hooks/codex.json").read_text())["hooks"]["Stop"][0]["hooks"][0]["command"]
    result = subprocess.run(["/bin/sh", "-c", command], input="{}", text=True, capture_output=True,
                            env={**env, "PLUGIN_ROOT": str(source), "CLAUDE_PLUGIN_ROOT": str(source)}, timeout=2)
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert log.read_text() == "awaitonal hook codex\n"


@pytest.mark.parametrize("action", ["mute", "unmute"])
def test_codex_controls_use_the_same_shared_runtime(plugin_env, action):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    assert script(plugin_env, action, "--adapter", "codex").returncode == 0
    assert log.read_text() == f"awaitonal service {action} --expected-executable {runtime}/bin/awaitonal\n"


def test_codex_runtime_uninstall_does_not_remove_claude_plugin(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "uninstall", "--adapter", "codex")
    assert result.returncode == 0, result.stderr
    assert "both Claude and Codex" in result.stdout
    assert "codex plugin remove" in result.stdout
    assert "claude plugin uninstall" not in result.stdout
    assert "plugin remove" not in log.read_text() and "plugin uninstall" not in log.read_text()
    calls = log.read_text().splitlines()
    assert calls[0] == "awaitonal uninstall --adapter codex --apply"
    assert "awaitonal uninstall --adapter claude" not in calls


def test_codex_detach_removes_only_its_tracked_hooks_without_stopping_shared_service(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, "detach", "--adapter", "codex", "--settings", "/tmp/codex hooks.json")
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "awaitonal uninstall --adapter codex --apply --settings /tmp/codex hooks.json\n"


@pytest.mark.parametrize("args", [("--mode", "plugin"), ("--mode=plugin",), ("--mode", "standalone")])
def test_codex_setup_cannot_switch_to_unregistered_plugin_hooks(plugin_env, args):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "setup", "--adapter", "codex", *args)
    assert result.returncode == 1 and "--mode overrides" in result.stderr
    assert not log.exists()


def test_failed_codex_detach_keeps_shared_runtime_installed(plugin_env):
    _, _, _, log, _ = plugin_env
    executable = install_fake_runtime(plugin_env)
    executable.write_text('#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\nexit 17\n')
    install_fake_uv(plugin_env)
    result = script(plugin_env, "uninstall", "--adapter", "codex")
    assert result.returncode == 17
    assert log.read_text() == "awaitonal uninstall --adapter codex --apply\n"
