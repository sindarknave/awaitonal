"""OpenCode owns plugin registration; setup only manages the shared runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from awaitonal import __version__
from awaitonal.cli import main
from awaitonal.diagnostics import diagnose
from test_plugin import install_fake_runtime, install_fake_uv, plugin_env, script


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
def test_setup_preserves_host_settings_and_only_updates_shared_runtime(plugin_env):
    source, runtime, _, log, env = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    settings = Path(env['HOME']) / '.config/opencode/opencode.json'
    settings.parent.mkdir(parents=True)
    original = '{"plugin":["unrelated-plugin"],"unrelated":true}\n'
    settings.write_text(original)
    result = script(plugin_env, 'setup', '--adapter', 'opencode')
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        f'awaitonal service stop --expected-executable {runtime}/bin/awaitonal',
        f'uv tool install --python >=3.11 --force --reinstall-package awaitonal {source}',
        f'tools {runtime}/tools', f'bin {runtime}/bin', 'awaitonal service start',
    ]
    assert settings.read_text() == original


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
@pytest.mark.parametrize('action', ['setup', 'status', 'detach'])
@pytest.mark.parametrize('args', [('--settings', '/tmp/settings.json'), ('--mode', 'plugin'), ('extra',)])
def test_host_registration_options_are_rejected_before_side_effects(plugin_env, action, args):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env)
    result = script(plugin_env, action, '--adapter', 'opencode', *args)
    assert result.returncode == 1
    assert 'takes no arguments' in result.stderr
    assert not log.exists()


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
@pytest.mark.parametrize('action', ['status', 'mute', 'unmute'])
def test_controls_use_existing_shared_runtime_without_installing(plugin_env, action):
    _, runtime, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    result = script(plugin_env, action, '--adapter', 'opencode')
    assert result.returncode == 0, result.stderr
    expected = 'awaitonal service status\n' if action == 'status' else f'awaitonal service {action} --expected-executable {runtime}/bin/awaitonal\n'
    assert log.read_text() == expected
    if action == 'status':
        assert 'managed by OpenCode' in result.stderr


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
def test_failed_update_recovers_only_existing_service(plugin_env):
    _, _, _, log, _ = plugin_env
    install_fake_runtime(plugin_env)
    install_fake_uv(plugin_env, fails=True)
    result = script(plugin_env, 'setup', '--adapter', 'opencode')
    assert result.returncode == 1
    assert log.read_text().splitlines()[-1] == 'awaitonal service start'
    assert ' init ' not in log.read_text() and 'uninstall --adapter' not in log.read_text()


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
@pytest.mark.parametrize('installed', [False, True])
def test_detach_describes_only_plugin_removal_without_touching_service(plugin_env, installed):
    _, _, _, log, _ = plugin_env
    if installed:
        install_fake_runtime(plugin_env)
    result = script(plugin_env, 'detach', '--adapter', 'opencode')
    assert result.returncode == 0
    assert 'Awaitonal entry' in result.stdout and 'shared service remains available' in result.stdout
    assert not log.exists()


@pytest.mark.skipif(os.name != "posix", reason="Runtime wrapper requires a POSIX shell")
@pytest.mark.parametrize('installed', [False, True])
def test_hook_wrapper_discards_output_and_returns_success(plugin_env, installed):
    source, _, _, log, env = plugin_env
    if installed:
        executable = install_fake_runtime(plugin_env)
        executable.write_text('#!/bin/sh\nprintf "PRIVATE output"\nprintf "PRIVATE error" >&2\nprintf "%s\\n" "$*" >> "$CALLS"\nexit 17\n')
    result = subprocess.run(['/bin/sh', str(source/'scripts/plugin-hook.sh'), '--adapter', 'opencode'],
                            input='{}', text=True, capture_output=True, env=env, timeout=2)
    assert result.returncode == 0 and result.stdout == result.stderr == ''
    assert log.read_text() == 'hook opencode\n' if installed else not log.exists()


def test_doctor_does_not_read_or_claim_to_verify_host_configuration(monkeypatch):
    from awaitonal import lifecycle, setup
    monkeypatch.setattr(lifecycle, 'service_status', lambda _: {
        'status': 'running', 'version': __version__, 'muted': True,
        'executable': str(Path(sys.executable).parent/'awaitonal'),
    })
    def unexpected(*args, **kwargs):
        raise AssertionError('OpenCode configuration is host-owned')
    monkeypatch.setattr(setup, 'default_settings', unexpected)
    monkeypatch.setattr(setup, 'hook_inventory', unexpected)
    result = diagnose(adapter='opencode')
    checks = {item['name']: item for item in result['checks']}
    assert checks['service']['status'] == 'ok'
    assert checks['plugin']['status'] == 'unknown'
    assert 'not inspected' in checks['plugin']['message']
    assert 'muted' in checks['notifications']['message']
    assert 'hooks' not in checks and result['settings_scope'] is None


def test_doctor_settings_override_is_rejected_before_reading(tmp_path):
    path = tmp_path/'opencode.json'
    path.write_text('keep me')
    with pytest.raises(ValueError, match='OpenCode manages its plugins'):
        diagnose(path, adapter='opencode')
    assert path.read_text() == 'keep me'


def test_doctor_cli_reports_missing_service_and_unverified_plugin(tmp_path, capsys):
    assert main(['doctor', '--adapter', 'opencode', '--socket', str(tmp_path/'absent'), '--json']) == 1
    result = json.loads(capsys.readouterr().out)
    assert not result['ok']
    assert any(check['name'] == 'plugin' and check['status'] == 'unknown' for check in result['checks'])
