"""Explicit, reviewable Claude settings edits; never used by notification hooks."""
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import stat
import tempfile


def default_settings():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json"


def _read(path):
    if not path.exists() and not path.is_symlink():
        return None, {}
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError(f"refusing non-regular or foreign settings file: {path}")
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"invalid JSON settings: {path}") from error
    if not isinstance(data, dict):
        raise ValueError(f"settings must be a JSON object: {path}")
    return raw, data


def _validate_hooks(data):
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object")
    for groups in hooks.values():
        if not isinstance(groups, list) or not all(
            isinstance(group, dict) and isinstance(group.get("hooks"), list)
            and all(isinstance(handler, dict) for handler in group["hooks"])
            for group in groups
        ):
            raise ValueError("invalid hook groups; settings left unchanged")


def _group_options(group):
    return {key: value for key, value in group.items() if key != "hooks"}


def _remove(data, owned):
    if not owned:
        return
    hooks = data.get("hooks", {})
    for event, groups in owned.items():
        remaining = []
        for group in hooks.get(event, []):
            updated = deepcopy(group)
            for known in groups:
                if _group_options(group) == _group_options(known):
                    updated["hooks"] = [h for h in updated["hooks"] if h not in known["hooks"]]
            if updated["hooks"] or not group["hooks"]:
                remaining.append(updated)
        if event in hooks:
            if remaining:
                hooks[event] = remaining
            else:
                del hooks[event]
    if not hooks:
        data.pop("hooks", None)


def _add(data, desired):
    """Do not adopt pre-existing identical user hooks as installation-owned."""
    added = {}
    for event, groups in desired.items():
        for group in groups:
            present = [h for existing in data.get("hooks", {}).get(event, [])
                       if _group_options(existing) == _group_options(group) for h in existing["hooks"]]
            new = [h for h in group["hooks"] if h not in present]
            if new:
                entry = {**deepcopy(_group_options(group)), "hooks": deepcopy(new)}
                data.setdefault("hooks", {}).setdefault(event, []).append(entry)
                added.setdefault(event, []).append(deepcopy(entry))
    return added


def _entries(data):
    return [(event, {**_group_options(group), "hooks": [handler]})
            for event, groups in data.get("hooks", {}).items()
            for group in groups for handler in group["hooks"]]


def _difference(left, right):
    remaining = list(right)
    result = {}
    for event, group in left:
        if (event, group) in remaining:
            remaining.remove((event, group))
        else:
            result.setdefault(event, []).append(group)
    return result


def _atomic(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure_hooks(settings_path, fragment=None, *, mode="standalone", apply=False,
                    legacy_fragment=None):
    """Preview by default. Only exact tracked (or explicitly supplied legacy) handlers are removed."""
    if mode not in ("standalone", "plugin", "uninstall"):
        raise ValueError("unknown setup mode")
    path = Path(settings_path).expanduser().absolute()
    manifest = path.with_name(path.name + ".awaitonal.json")
    raw, original = _read(path)
    manifest_raw, installed = _read(manifest)
    _validate_hooks(original)
    if installed and (installed.get("schema") != 1 or not isinstance(installed.get("hooks"), dict)):
        raise ValueError("invalid Awaitonal ownership manifest")
    _validate_hooks(installed)
    desired = fragment or {"hooks": {}}
    _validate_hooks(desired)
    if legacy_fragment:
        _validate_hooks(legacy_fragment)
    updated = deepcopy(original)
    _remove(updated, installed.get("hooks", {}))
    if legacy_fragment:
        _remove(updated, legacy_fragment.get("hooks", {}))
    owned = _add(updated, desired["hooks"]) if mode == "standalone" else {}
    removed = _difference(_entries(original), _entries(updated))
    added = _difference(_entries(updated), _entries(original))
    if not removed and not added:
        # Removing/readding owned handlers must not reorder existing user hooks.
        updated = original
    # Repeating installation should not reorder hooks or rewrite formatting.
    if updated == original:
        rendered = raw or ""
    else:
        rendered = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    ownership = json.dumps({"schema": 1, "hooks": owned}, indent=2) + "\n"
    # Never display full settings or unchanged commands: they can contain
    # credentials unrelated to the handlers this operation changes.
    before = json.dumps({"hooks": removed}, indent=2) + "\n"
    after = json.dumps({"hooks": added}, indent=2) + "\n"
    difference = "".join(difflib.unified_diff(before.splitlines(keepends=True),
                                           after.splitlines(keepends=True),
                                           fromfile=str(path), tofile=str(path)))
    result = {"changed": bool(difference), "applied": False, "diff": difference, "backup": None}
    if not apply:
        return result
    # A concurrent edit must not be overwritten by a plan built from older data.
    if _read(path)[0] != raw or _read(manifest)[0] != manifest_raw:
        raise ValueError("settings changed during setup; run setup again")
    if difference:
        if raw is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = path.with_name(path.name + f".awaitonal-backup-{stamp}")
            _atomic(backup, raw)
            result["backup"] = str(backup)
        _atomic(path, rendered)
    if owned:
        if ownership != manifest_raw:
            _atomic(manifest, ownership)
    elif manifest_raw is not None:
        manifest.unlink()
    result["applied"] = True
    return result


def hook_inventory(settings_path):
    """Summarize potential manual duplicates without exposing command contents."""
    import shlex
    import shutil
    _, data = _read(Path(settings_path).expanduser())
    _validate_hooks(data)
    counts = {}
    broken = 0
    for event, groups in data.get("hooks", {}).items():
        count = 0
        for group in groups:
            for handler in group["hooks"]:
                try:
                    parts = shlex.split(handler.get("command", ""))
                except (ValueError, TypeError):
                    continue
                if len(parts) >= 3 and Path(parts[0]).name == "awaitonal" and parts[1:3] == ["hook", "claude"]:
                    count += 1
                    target = Path(parts[0]) if Path(parts[0]).is_absolute() else Path(shutil.which(parts[0]) or "/nonexistent-awaitonal")
                    if not target.is_file() or not os.access(target, os.X_OK):
                        broken += 1
        if count:
            counts[event] = count
    plugins = data.get("enabledPlugins", {})
    plugin_enabled = isinstance(plugins, dict) and any(
        name.startswith("awaitonal@") and enabled is True for name, enabled in plugins.items())
    return {"manual_hooks": counts, "broken_manual_hooks": broken, "plugin_enabled": plugin_enabled,
            "duplicates": any(n > 1 for n in counts.values()) or (bool(counts) and plugin_enabled)}
