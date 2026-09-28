"""Metadata-only installation checks; audio testing remains explicit."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys

from . import __version__


def diagnose(settings_path=None, socket_path=None, *, adapter="claude"):
    from .lifecycle import service_status
    from .setup import default_settings, hook_inventory
    if adapter in ("pi", "opencode"):
        if settings_path is not None:
            if adapter == "pi":
                raise ValueError("Pi manages its extensions; use pi list instead of --settings")
            raise ValueError("OpenCode manages its plugins; inspect its plugin configuration instead of --settings")
    else:
        settings_path = settings_path or default_settings(adapter)
    checks = []

    def check(name, ok, message):
        checks.append({"name": name, "status": "ok" if ok else "needs-attention", "message": message})

    executable = Path(sys.executable).parent / "awaitonal"
    check("runtime", executable.is_file() and os.access(executable, os.X_OK),
          f"Awaitonal {__version__}; executable {'available' if executable.is_file() else 'missing'}")
    check("dependencies", importlib.util.find_spec("numpy") is not None, "NumPy " +
          ("available" if importlib.util.find_spec("numpy") is not None else "missing; run setup"))
    try:
        status = service_status(socket_path)
        running = status.get("status") == "running"
        check("service", running, "authenticated listener running" if running else "not running; use awaitonal service start")
        if running:
            if type(status.get("muted")) is bool:
                check("notifications", True,
                      "muted; model stays warm. Use awaitonal service unmute to resume" if status["muted"] else
                      "notifications unmuted")
            else:
                check("notifications", False, "mute state unavailable; upgrade and restart the service")
            check("version", status.get("version") == __version__,
                  "runtime versions match" if status.get("version") == __version__ else "restart the service after upgrading")
            matches = Path(status.get("executable", "/unavailable")).resolve() == executable.resolve()
            check("installation", matches, "service uses this installation" if matches else
                  "service belongs to another installation; use its CLI to stop it before switching")
    except (OSError, ValueError, RuntimeError):
        check("service", False, "listener could not be verified; inspect socket ownership/permissions. If upgrading from v0.2, stop its foreground service in its terminal, then start this version")
    if adapter == "pi":
        checks.append({"name": "extension", "status": "unknown", "message":
                       "Pi owns extension registration. Use pi list and /awaitonal-status in Pi; active extensions were not inspected"})
    elif adapter == "opencode":
        checks.append({"name": "plugin", "status": "unknown", "message":
                       "OpenCode owns plugin registration. Check its plugin configuration and startup log; active plugin instances were not inspected"})
    else:
        try:
            inventory = hook_inventory(settings_path, adapter=adapter)
            configured = bool(inventory["manual_hooks"]) or inventory["plugin_enabled"]
            check("hooks", configured, "hooks configured" if configured else "no Awaitonal hooks found in this settings scope")
            if adapter == "codex":
                # Plugin and inline TOML hooks are additive and their trust is owned
                # by Codex. A JSON-file inventory cannot establish that they run.
                checks[-1]["message"] = ("manual Codex hooks configured" if configured else
                                         "no manual Codex hooks in this file; plugin and inline hooks are not inspected")
                checks[-1]["status"] = "ok" if configured else "unknown"
                checks.append({"name": "hook-trust", "status": "unknown", "message":
                               "Use /hooks in Codex CLI to review all hook sources and trust new or changed hooks; trust was not inspected"})
            check("hook-executables", inventory["broken_manual_hooks"] == 0,
                  "manual hook executables available" if not inventory["broken_manual_hooks"] else
                  "manual hook executable missing or not executable; rerun setup/migrate the old path")
            check("duplicates", not inventory["duplicates"], "duplicate installations detected; migrate manual hooks" if inventory["duplicates"] else
                  ("no duplicate manual hooks in this file; plugin/inline registrations not inspected" if adapter == "codex" else
                   "no duplicate manual/plugin registration detected in this scope"))
        except (OSError, ValueError):
            check("hooks", False, "settings are malformed or unavailable; no changes made")
    player = shutil.which("afplay") if sys.platform == "darwin" else None
    check("playback", bool(player), "afplay available; audible output not tested" if player else "macOS afplay unavailable; rendering still works")
    return {"ok": all(item["status"] != "needs-attention" for item in checks), "checks": checks,
            "audio_tested": False, "settings_scope": str(settings_path) if settings_path is not None else None}
