"""Pi package management never becomes Awaitonal-managed app configuration."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_plugin import install_fake_runtime, install_fake_uv, plugin_env, script


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Plugin targets macOS/Linux shells")


def test_pi_setup_installs_stable_runtime_and_starts_service_without_configuring_hooks(plugin_env):
    source, runtime, _, log, env = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    settings = []
    for name in (".pi/agent/settings.json", ".claude/settings.json", ".codex/hooks.json"):
        path = Path(env["HOME"]) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"unrelated": "keep this"}\n')
        settings.append(path)
    result = script(plugin_env, "setup", "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal",
        f"uv tool install --python >=3.11 --force --reinstall-package awaitonal {source}",
        f"tools {runtime}/tools",
        f"bin {runtime}/bin",
        "awaitonal service start",
    ]
    assert "Awaitonal is ready" in result.stdout
    assert all(path.read_text() == '{"unrelated": "keep this"}\n' for path in settings)


def test_pi_first_setup_starts_installed_runtime_without_init(plugin_env):
    _, runtime, bin_dir, log, _ = plugin_env
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/bin/sh\n'
        'printf "uv %s\\n" "$*" >> "$CALLS"\n'
        'mkdir -p "$UV_TOOL_BIN_DIR"\n'
        'cat > "$UV_TOOL_BIN_DIR/awaitonal" <<\'AWAITONAL\'\n'
        '#!/bin/sh\n'
        'printf "awaitonal %s\\n" "$*" >> "$CALLS"\n'
        'AWAITONAL\n'
        'chmod 700 "$UV_TOOL_BIN_DIR/awaitonal"\n'
    )
    uv.chmod(0o700)
    result = script(plugin_env, "setup", "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 2
    assert calls[0].startswith("uv tool install ")
    assert calls[1] == "awaitonal service start"
    assert (runtime / "bin/awaitonal").is_file()


@pytest.mark.parametrize("args", [
    ("--settings", "/tmp/pi.json"), ("--legacy-executable", "/tmp/awaitonal"),
    ("--mode", "plugin"), ("--mode=standalone",), ("--json",), ("--test-sound",), ("extra",),
])
def test_pi_setup_rejects_init_options_before_any_install_or_service_effect(plugin_env, args):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "setup", "--adapter", "pi", *args)
    assert result.returncode == 1
    assert "Pi setup takes no arguments" in result.stderr
    assert not log.exists()


def test_pi_failed_install_restarts_only_existing_service_and_never_configures_hooks(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env, fails=True)
    result = script(plugin_env, "setup", "--adapter", "pi")
    assert result.returncode == 1
    calls = log.read_text().splitlines()
    assert calls[-1] == "awaitonal service start"
    assert not any(" init " in call or " uninstall --adapter " in call for call in calls)


def test_pi_status_only_queries_shared_service_without_uv_or_settings(plugin_env):
    _, _, _, log, _ = plugin_env
    executable = install_fake_runtime(plugin_env)
    executable.write_text(
        '#!/bin/sh\n'
        'printf "awaitonal %s\\n" "$*" >> "$CALLS"\n'
        'printf \'{"status":"running","muted":true}\\n\'\n'
    )
    result = script(plugin_env, "status", "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "awaitonal service status\n"
    assert result.stdout == '{"status":"running","muted":true}\n'
    assert "Pi extension loading" in result.stderr


@pytest.mark.parametrize("action", ["status", "mute", "unmute", "service"])
def test_pi_missing_runtime_points_to_pi_setup_command(plugin_env, action):
    _, _, _, log, _ = plugin_env
    result = script(plugin_env, action, "--adapter", "pi")
    assert result.returncode == 1
    assert "/awaitonal-setup" in result.stdout + result.stderr
    assert not log.exists()


@pytest.mark.parametrize("action", ["status", "detach"])
def test_pi_read_only_wrapper_actions_reject_extra_options(plugin_env, action):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, action, "--adapter", "pi", "--settings", "/tmp/pi.json")
    assert result.returncode == 1
    assert "takes no arguments" in result.stderr
    assert not log.exists()


@pytest.mark.parametrize("action", ["mute", "unmute"])
def test_pi_mute_controls_share_existing_owned_runtime(plugin_env, action):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, action, "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    assert log.read_text() == f"awaitonal service {action} --expected-executable {runtime}/bin/awaitonal\n"


@pytest.mark.parametrize("installed", [False, True])
def test_pi_detach_only_explains_native_package_removal(plugin_env, installed):
    _, _, _, log, _ = plugin_env
    if installed:
        install_fake_runtime(plugin_env)
    result = script(plugin_env, "detach", "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    assert "pi remove" in result.stdout and "original package source or path" in result.stdout
    assert not log.exists()


def test_pi_runtime_uninstall_has_global_scope_without_app_configuration_changes(plugin_env):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, "uninstall", "--adapter", "pi")
    assert result.returncode == 0, result.stderr
    expected = [f"awaitonal service uninstall --expected-executable {runtime}/bin/awaitonal"] if sys.platform == "darwin" else []
    assert log.read_text().splitlines() == expected + [
        f"awaitonal service stop --expected-executable {runtime}/bin/awaitonal",
        "uv tool uninstall awaitonal",
        f"tools {runtime}/tools",
        f"bin {runtime}/bin",
    ]
    assert all(name in result.stdout for name in ("Pi", "Claude", "Codex", "pi remove"))
    assert "claude plugin uninstall" not in result.stdout and "codex plugin remove" not in result.stdout


def test_pi_uninstall_stops_if_service_ownership_cannot_be_verified(plugin_env):
    _, _, _, log, _ = plugin_env
    executable = install_fake_runtime(plugin_env)
    executable.write_text('#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\nexit 17\n')
    install_fake_uv(plugin_env)
    result = script(plugin_env, "uninstall", "--adapter", "pi")
    assert result.returncode == 17
    assert "uv tool uninstall" not in log.read_text()
    assert "runtime removed" not in result.stdout


@pytest.mark.parametrize("installed", [False, True])
def test_optional_pi_hook_wrapper_is_bounded_quiet_and_never_installs(plugin_env, installed):
    source, _, _, log, env = plugin_env
    if installed:
        executable = install_fake_runtime(plugin_env)
        executable.write_text(
            '#!/bin/sh\nprintf "awaitonal %s\\n" "$*" >> "$CALLS"\n'
            'printf "PRIVATE stdout"\nprintf "PRIVATE stderr" >&2\nexit 17\n'
        )
    result = subprocess.run(
        ["/bin/sh", str(source / "scripts/plugin-hook.sh"), "--adapter", "pi"],
        input='{"event":"agent_end"}', text=True, capture_output=True, env=env, timeout=2,
    )
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert log.read_text() == "awaitonal hook pi\n" if installed else not log.exists()
