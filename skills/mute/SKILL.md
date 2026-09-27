---
name: mute
description: Mute Awaitonal notification sounds when the user asks to silence Awaitonal while keeping its service running.
---

Resolve the installed plugin root two levels above this skill's directory. Run
the bundled script using the host's shell:

```sh
sh "<plugin-root>/scripts/plugin-runtime.sh" mute --adapter codex
```

Replace `<plugin-root>` with the resolved absolute path. In Claude Code use
`--adapter claude`. Report success only if the command confirms `muted: true`.
This silences Claude, Codex, and Pi sessions sharing the service until the user
unmutes Awaitonal or restarts it. The service and model stay loaded; queued
notifications are discarded. A cue already starting or playing may finish.

If the runtime is missing, the command is unrecognized, or the service reports an
older version, explain that the user needs to update the plugin and rerun the
Awaitonal setup skill. If the service is stopped, report that it is already
quiet. Do not claim mute succeeded, install, restart, or change system volume as
a fallback. This command does not schedule an automatic unmute.
