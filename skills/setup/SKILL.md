---
name: setup
description: Install or update Awaitonal's local runtime and start its notification service.
disable-model-invocation: true
---

Run this command using Bash:

```sh
sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" setup
```

This explicitly installs Python dependencies with uv, migrates Awaitonal-managed manual hooks, and starts the local service. It does not install the optional semantic model. Report the command's result. If uv is missing, report its installation link; do not install additional tools automatically.

For an old hand-pasted hook configuration, inspect Awaitonal's settings diff first and use `--legacy-executable` only with the exact installed Awaitonal path the user wants migrated. Do not delete unrelated hooks. For automatic startup, the user can explicitly request `sh "${CLAUDE_PLUGIN_ROOT}/scripts/plugin-runtime.sh" service install`.
