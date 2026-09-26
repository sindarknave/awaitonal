---
name: status
description: Diagnose Awaitonal's local service and Claude hook setup without playing a sound.
disable-model-invocation: true
---

Run this command using Bash and explain the result:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" status
```

Do not install dependencies, restart services, or change settings just to inspect status. If the user explicitly requests an audible check, append `--test-sound`.
