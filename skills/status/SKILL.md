---
name: status
description: Diagnose Awaitonal's local service and the current app's hook setup without playing a sound.
---

Resolve the installed plugin root two levels above this skill's directory. Run
the bundled script using the host's shell and explain its result:

```sh
sh "<plugin-root>/scripts/plugin-runtime.sh" status --adapter codex
```

Replace `<plugin-root>` with the resolved absolute path. In Claude Code use
`--adapter claude`. Do not install dependencies, restart services, or change
settings just to inspect status. If the user explicitly requests an audible
check, append `--test-sound`.

Codex doctor examines the selected hook file; Codex's `/hooks` view remains the
source for plugin/inline hook activation and trust. A running Awaitonal service
does not prove Codex trusts the hooks. If the service is muted, mention the
Awaitonal unmute skill to resume notifications for Claude, Codex, and Pi. Do not unmute it
merely to inspect status.
