---
name: uninstall
description: Stop Awaitonal, remove its automatic startup and plugin runtime, and explain plugin removal.
disable-model-invocation: true
---

Run this command using Bash:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" uninstall
```

This stops the shared Awaitonal service, removes Awaitonal's automatic startup, and removes only its isolated plugin runtime. It leaves user configuration and settings backups intact. After the command succeeds, run `claude plugin uninstall awaitonal@awaitonal` to remove this plugin's hooks and skills. Report both results. Do not remove the marketplace or other plugins.
