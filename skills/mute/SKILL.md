---
name: mute
description: Mute Awaitonal notification sounds when the user asks to silence Awaitonal while keeping its service running.
---

Run this command using Bash:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" mute
```

Report success only if the command confirms `muted: true`. This silences all sessions using this Awaitonal service until `/awaitonal:unmute` or a service restart. The service and model stay loaded; queued notifications are discarded. A cue already starting or playing may finish.

If the runtime is missing, the command is unrecognized, or the service reports an older version, explain that the user needs to update the plugin and rerun `/awaitonal:setup`. If the service is stopped, report that it is already quiet. Do not claim mute succeeded, install, restart, or change system volume as a fallback. This command does not schedule an automatic unmute.
