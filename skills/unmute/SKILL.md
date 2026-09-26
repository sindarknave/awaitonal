---
name: unmute
description: Resume Awaitonal notification sounds when the user asks to unmute Awaitonal or turn its notifications back on.
---

Run this command using Bash:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" unmute
```

Report success only if the command confirms `muted: false`. Future notifications resume for all sessions using this Awaitonal service; notifications discarded while muted are not replayed. Unmuting does not play a test sound.

If the service is stopped, report that unmute cannot start it. If the runtime is missing, the command is unrecognized, or the service reports an older version, explain that the user needs to update the plugin and rerun `/awaitonal:setup`. Do not claim unmute succeeded, start a service, install dependencies, or change system volume as a fallback. A service started with diagnostic `--silent` stays silent.
