# Codex hooks

The Codex adapter targets local sessions with native command hooks. It feeds the
same resident service as Claude Code; it does not start another model or player.
The contract was checked against the [official Codex hooks documentation](https://learn.chatgpt.com/docs/hooks)
on September 26, 2026. The local CLI reports `0.155.0-alpha.16.4`.

## Setup from a checkout

```sh
uv sync --dev
uv run awaitonal service start
uv run awaitonal init --adapter codex
uv run awaitonal init --adapter codex --apply
```

The first `init` previews changed handlers; `--apply` backs up and updates the
JSON file. Review and trust these hooks using `/hooks` in Codex CLI. Hooks must be
trusted again after their definitions change. Awaitonal does not change trust
settings or bypass that review. Open a new session after setup.

The default target is `${CODEX_HOME:-$HOME/.codex}/hooks.json`. `--settings PATH`
selects another JSON hook file; it does not accept `config.toml`. Existing inline
TOML hooks and other plugin hooks are not rewritten. Codex loads hooks from multiple
sources. Awaitonal's Codex plugin setup manages the same tracked user hooks,
pointing at its stable runtime; its manifests disable bundled-hook discovery to
avoid duplicate registrations. Claude's plugin continues to use bundled hooks.

Generated commands use a shell-quoted absolute executable path. If you move or
replace the environment, rerun `init` and review the new definition. Hooks only
adapt input and perform a bounded socket handoff; they do not install packages,
start a service, load NumPy or a model, or access the network.

## Event mapping

| Codex event | Awaitonal behavior |
| --- | --- |
| `UserPromptSubmit` | Store session/turn timing; discard prompt text. |
| `Stop` | Classify nonempty `last_assistant_message`; use `turn_id` to finish timing. |
| `PermissionRequest` | Play `needs-you` without approving or denying the request. |
| `PreToolUse`, `request_user_input` | Play `decision` for a nonempty `questions` list. |
| `PreToolUse`, `request_user_input_async` | Play `decision` for questions using the async `title` format. |
| Other events | Ignore. No `SubagentStop` registration. |

Normal hooks emit no output and exit successfully, including when the service is
absent or input is malformed. They return no agent instructions or permission
decisions. `--dry-run` prints diagnostics and must never be registered as a hook.

Every supported event uses `session_id`; turn-scoped events use `turn_id`.
Codex identities are prefixed with `codex:` (long IDs are reduced to a bounded
fingerprint). Subagent markers are rejected. `transcript_path`, working directory,
model, permission mode, prompt text, and tool arguments are not sent to the
service. Tool arguments contribute only a deduplication fingerprint. Final reply
text is transiently classified locally and omitted from service logs.

Input has the same 64 KiB limit and short stdin/socket deadlines as the Claude
adapter. Unknown or ambiguous turn timing keeps ordinary playback. Timed
suppression applies to routine results; questions and approvals remain audible.
Long turns can use the longer endings. Both agents share the queue, global mute,
and optional rotating voices while retaining separate session identities.

## Inspect, migrate, and remove

```sh
uv run awaitonal hook codex --dry-run < examples/codex-stop.json
uv run awaitonal hook codex --dry-run < examples/codex-question.json
uv run awaitonal hook codex --dry-run < examples/codex-question-async.json
uv run awaitonal hook-config --adapter codex
uv run awaitonal doctor --adapter codex --json
uv run awaitonal uninstall --adapter codex
uv run awaitonal uninstall --adapter codex --apply
```

Run fixture commands from the repository root. Doctor inventories only the chosen
JSON hook file and reports Codex trust as unknown. Its `ok` field describes checks
it could perform, not proof that Codex has trusted or executed the hook. Use
`/hooks` for the authoritative combined hook inventory and trust state.

Ownership is recorded beside the target as `hooks.json.awaitonal-codex.json`.
Uninstall removes only exact tracked handlers and preserves user edits. To migrate
an untracked fragment, pass its exact `--legacy-executable` path. Codex plugin
setup replaces tracked hooks with equivalent commands pointing at its stable
runtime. To remove only that integration, run its `detach --adapter codex`
wrapper before removing the plugin; this leaves the shared service available to
Claude. `init --mode plugin` is intended for integrations with verified native
bundled hooks and is not part of the Codex setup path.

## Coverage and limits

On the tested Codex build, plugin installation succeeds but bundled hooks do not
appear in `plugin/read` or `hooks/list`. The same four handlers installed in the
user hook file are discovered with no errors, all awaiting trust. This is why
Codex plugin setup uses tracked user hooks. It does not change Codex's trust
requirements.

Fixture and socket tests cover final text, synchronous and asynchronous questions,
approvals, timing, malformed input, duplicate suppression, concurrent Claude/Codex
sessions, and shared voice assignment. These exercise the adapter and local
service; they do not establish that every Codex build exposes every tool hook.
See [observed validation](../VALIDATION.md) for measured runs.

Codex's current documented events do not include Claude's `StopFailure`, so
rate-limit, authentication-error, and API-crash notifications have no structured
Codex mapping. No background-task count is inferred. An ordinary reply explaining
a problem can still be classified normally.

Audio playback uses the local macOS service. Remote/cloud agents cannot reach
your Mac's private Unix socket; this integration does not add a network bridge.
Full live Codex hook invocation requires installation and explicit hook trust;
fixture tests do not claim that those user steps have occurred.
