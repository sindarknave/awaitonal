---
name: uninstall
description: Remove the requested Awaitonal integration or its shared local runtime when the user asks to uninstall Awaitonal.
---

Awaitonal's runtime, service, and automatic startup are shared by Claude, Codex,
and Pi. Removing the runtime stops notifications for all three apps. If the user asks
to remove only one app's plugin, leave the shared runtime running. For Codex,
first run the bundled script with `detach --adapter codex` (and the same
`--settings` override if used during setup), then remove the plugin through
Codex's plugin management. Codex setup installs tracked user hooks independently
of plugin activation, so removing the plugin alone does not remove those hooks.
Claude's native plugin hooks are removed with its plugin.

When removal of the shared runtime is requested, resolve the installed plugin
root two levels above this skill's directory and run its bundled script using
the host's shell:

```sh
sh "<plugin-root>/scripts/plugin-runtime.sh" uninstall --adapter codex
```

Replace `<plugin-root>` with the resolved absolute path. In Claude Code use
`--adapter claude`. This stops the service, removes Awaitonal's automatic startup,
and removes only its isolated runtime. With `--adapter codex`, it first removes
Awaitonal's tracked hooks from the default Codex hook file. Detach any custom
hook file first using the original `--settings` override. Unrelated configuration
and settings backups remain intact.

For requested plugin removal in Codex, use its plugin management tool or
`codex plugin remove` with the installed selector reported by `codex plugin list`;
do not invent a marketplace name. In Claude Code run
`claude plugin uninstall awaitonal@awaitonal`. Report each operation actually
performed. Do not remove a marketplace or another app's integration unless requested.
