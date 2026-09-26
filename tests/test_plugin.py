"""Plugin bootstrap and hook behavior, independent of Claude/user settings."""

import json
import os
from pathlib import Path
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


@pytest.mark.parametrize("installed", [False, True])
def test_plugin_hook_is_quiet_and_successful_even_when_runtime_fails(plugin_env, installed):
    source, _, _, log, env = plugin_env
    if installed:
        executable = install_fake_runtime(plugin_env)
        executable.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
            'printf "unexpected output"\nprintf "unexpected error" >&2\nexit 17\n'
        )
    result = subprocess.run(
        ["/bin/sh", str(source / "scripts/plugin-hook.sh")],
        input='{"hook_event_name":"Stop","last_assistant_message":"Done."}',
        text=True, capture_output=True, env=env, timeout=2,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    assert log.read_text() == "hook claude\n" if installed else not log.exists()


def test_registered_hook_is_quiet_if_old_plugin_cache_has_been_removed(tmp_path):
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
    command = hooks["Stop"][0]["hooks"][0]["command"]
    result = subprocess.run(
        ["/bin/sh", "-c", command], capture_output=True, text=True, timeout=2,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(tmp_path / "removed plugin cache")},
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
        "awaitonal init --mode plugin --apply --settings /tmp/custom settings.json",
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
    assert log.read_text() == "awaitonal doctor --json\n"


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
