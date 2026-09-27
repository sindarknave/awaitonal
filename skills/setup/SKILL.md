---
name: setup
description: Install or update Awaitonal's local runtime and start its notification service when the user requests setup or an upgrade.
---

Resolve the installed plugin root two levels above this skill's directory. Use
the host's shell to run its bundled script. Set the adapter to `codex` when
invoked in Codex, or `claude` in Claude Code; do not infer the adapter from which
other app is installed.

```sh
sh "<plugin-root>/scripts/plugin-runtime.sh" setup --adapter codex
```

Replace `<plugin-root>` with the resolved absolute path and use `--adapter claude`
for Claude Code. This explicitly installs Python dependencies with uv and starts
the shared local service. Codex setup registers tracked hooks pointing to the
stable runtime in its hook file, with a diff and backup. Claude setup migrates
tracked manual hooks to its native plugin hooks. Codex setup never modifies
Claude settings. It does not install the optional semantic model. Report the command's result. If uv is
missing, report its installation link; do not install additional tools automatically.

For an old hand-pasted hook configuration, inspect Awaitonal's settings diff first
and use `--legacy-executable` only with the exact installed Awaitonal path the user
wants migrated. Do not delete unrelated hooks. In Codex, explain that the user
must review and trust the current hook definitions in `/hooks`; installing the
runtime does not grant hook trust. Do not bypass or modify that trust decision.
Codex's bundled hooks are disabled intentionally; do not pass `--mode plugin` or
hand-register another copy. To remove only Codex's hooks later, use the same
script with `detach --adapter codex`, preserving any `--settings` override.
For requested macOS automatic startup, run the same script with
`service --adapter codex install` (or `claude`).
