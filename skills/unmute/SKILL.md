---
name: unmute
description: Resume Awaitonal notification sounds when the user asks to unmute Awaitonal or turn its notifications back on.
---

Resolve the installed plugin root two levels above this skill's directory. Run
the bundled script using the host's shell:

```sh
sh "<plugin-root>/scripts/plugin-runtime.sh" unmute --adapter codex
```

Replace `<plugin-root>` with the resolved absolute path. In Claude Code use
`--adapter claude`. Report success only if the command confirms `muted: false`.
Future notifications resume for Claude, Codex, and Pi sessions sharing this
service; notifications discarded while muted are not replayed. Unmuting does not
play a test sound.

If the service is stopped, report that unmute cannot start it. If the runtime is
missing, the command is unrecognized, or the service reports an older version,
explain that the user needs to update the plugin and rerun the Awaitonal setup
skill. Do not claim unmute succeeded, start a service, install dependencies, or
change system volume as a fallback. A service started with diagnostic `--silent`
stays silent.
