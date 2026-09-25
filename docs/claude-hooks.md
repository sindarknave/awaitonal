# Claude Code integration

Awaitonal installs no hooks automatically. Its hooks only send local notifications;
they never approve permissions, block a turn, change tool inputs, or send instructions
back to Claude. Normal hook execution has empty stdout and exits 0, including when
input is malformed or the service is unavailable. Do not use `--dry-run` in settings.

## Verified compatibility

Checked the [official hook reference](https://code.claude.com/docs/en/hooks) on
2026-09-25 and the installed Apple Silicon Claude Code **2.1.158** using `claude
--version`, `--help`, and read-only inspection of its bundled schemas. No live Claude
conversation or settings edit was used for this check.

The current reference documents these inputs:

| Event | Relevant fields | Awaitonal behavior |
| --- | --- | --- |
| `Stop` | `last_assistant_message`, `stop_hook_active` | Classify final assistant prose if present. |
| `PreToolUse` | `tool_name`, `tool_input`, `tool_use_id` | `AskUserQuestion` selects `needs-you`. |
| `PermissionRequest` | `tool_name`, `tool_input`; **no `tool_use_id`** | Select `needs-you`. |

Common fields include `session_id`, `transcript_path`, `cwd`, and `hook_event_name`.
`agent_id` identifies a subagent; `agent_type` alone can identify the main session's
`--agent` persona. `prompt_id` requires **2.1.196+**, so the example payloads omit it.
The transcript may lag the final response. These details are documented under
[common input fields](https://code.claude.com/docs/en/hooks#common-input-fields).

The installed binary's schemas and payload builder support the three events above,
`last_assistant_message`, and `agent_id`, and omit hook `prompt_id`. Its command-hook
schema supports shell commands, `args`, `timeout`, and `async`. Awaitonal uses a quoted
absolute executable path, a two-second hook timeout, and a short synchronous socket
handoff. It does not set `async` or `asyncRewake`; synthesis, classification, and
playback happen in the already-running service.

## Conservative routing

The `agent_id` field suppresses subagent events. No `SubagentStop`, `Notification`, or
generic tool-result hook is installed. Suppressing only `agent_type` would also mute
some main sessions, so Awaitonal does not do that.

Missing, empty, or wrongly typed final text produces no completion sound. Awaitonal
does not open `transcript_path`, infer a transcript format, or use earlier messages
as a fallback. `Stop` reports what Claude said at the end of a response; it does not
establish that the project is correct or that every task finished.

Duplicate suppression is bounded and session-aware. Newer `prompt_id` values can
distinguish turns. On 2.1.158, identical events within the short deduplication window
can be indistinguishable from rapid separate turns; they are never suppressed
permanently. Permission events cannot rely on an invented `tool_use_id`, so a short
fingerprint of the tool request supports question/permission duplicate suppression.

## Try fixtures

Run these from the Awaitonal checkout after core setup:

```sh
uv run awaitonal hook claude --dry-run < examples/claude-stop.json
uv run awaitonal hook claude --dry-run < examples/claude-question.json
uv run awaitonal hook claude --dry-run < examples/claude-permission.json
uv run awaitonal hook claude --dry-run < examples/claude-subagent.json
uv run awaitonal hook claude --dry-run < examples/claude-missing-text.json
```

Expected results: `done`, `needs-you`, `needs-you`, ignored, ignored. Dry-run prints
diagnostics for fixture inspection and does not enqueue audio. The `/example/...`
paths and identifiers are synthetic; no files at those locations are needed.

Start the service in a terminal, then run a normal hook in another:

```sh
uv run awaitonal serve --classifier rules
```

```sh
uv run awaitonal hook claude < examples/claude-stop.json
```

## Add hooks manually

Generate an inspectable snippet from your installed environment:

```sh
uv run awaitonal hook-config > examples/claude-hooks.local.json
```

The generated commands use your environment's absolute executable path and work
when Claude's current directory is an unrelated project. Keep that environment and
checkout at the same location, or regenerate the snippet after moving them. The
portable [template](../examples/claude-hooks.template.json) is illustrative; its
`/absolute/path/...` placeholder must be replaced before use.

Review the snippet, then manually merge its three event groups into the `hooks`
object of the desired Claude settings file: `~/.claude/settings.json` for your user,
or `.claude/settings.local.json` for one project. Preserve every unrelated setting
and hook. Do not replace an existing settings file by redirecting this command into
it. Restart the Claude session after your edit. Start Awaitonal's service explicitly
whenever you want notifications; no launch agent is installed.

## Disable or remove

Stop the service with Ctrl-C to silence Awaitonal immediately. Installed hooks then
return quietly without sounds. To disconnect fully, remove only handlers whose
commands invoke `awaitonal hook claude`; remove an event group only if it becomes
empty. Keep all other Claude hooks and settings. Restart the Claude session. You
can then delete the local snippet and the Awaitonal checkout/environment if desired.

Live hook firing inside Claude and audible playback are separate integration checks;
schema inspection and fixture tests alone do not establish that either happened.
