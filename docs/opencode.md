# OpenCode integration

Awaitonal includes a native plugin for **OpenCode 1.18.33 (V1)**. It forwards
notifications to the same local Python service used by Claude Code, Codex, and Pi.
Classification, musical variations, optional session instruments, and mute controls
are shared. Audio playback currently uses macOS `afplay`; classification and WAV
rendering also work without an audio device.

OpenCode V2 has a separate plugin interface. This entrypoint targets the stable
V1 package and does not claim V2 compatibility. Upstream references:
[OpenCode V1 plugins](https://opencode.ai/docs/plugins/) and
[V1/V2 migration](https://opencode.ai/v2/docs/build/plugins/migrate-v1).

## Install

Use OpenCode 1.18.33, Python 3.11+, and [uv](https://docs.astral.sh/uv/). Clone the
v0.8.0 release into a location you can keep available:

```sh
git clone --branch v0.8.0 --depth 1 https://github.com/sindarknave/awaitonal.git
cd awaitonal
```

An existing local checkout containing the v0.8.0 integration also works.

From the Awaitonal repository root:

```sh
sh scripts/plugin-runtime.sh setup --adapter opencode
```

Setup explicitly installs or updates the shared Python runtime and starts its
service. It does not edit OpenCode or another agent's settings. If a different
Awaitonal installation owns the socket, stop it using that installation's CLI
before switching.

Add an entry to your existing `opencode.json` or `opencode.jsonc`, preserving other
settings and plugins:

```json
{
  "plugin": ["file:///absolute/path/to/awaitonal/extensions/opencode.ts"]
}
```

Generate the correct file URL, including escaped spaces, from the checkout:

```sh
uv run python -c 'from pathlib import Path; print((Path.cwd() / "extensions/opencode.ts").as_uri())'
```

Restart OpenCode after registering or updating the plugin. Register it once:
using both the configuration entry and a local auto-loaded wrapper can duplicate
notifications. Keep the checkout available for OpenCode to load the plugin;
the Python runtime is installed separately in its stable user location.

The package exposes `awaitonal/opencode` for loaders that support package
subpaths. Neither the Pi host nor OpenCode is installed as a mandatory runtime
dependency. The plugin uses Node-compatible standard-library APIs and imports
OpenCode types only for development validation.

## Controls

Run these from the Awaitonal checkout:

```sh
sh scripts/plugin-runtime.sh status --adapter opencode
sh scripts/plugin-runtime.sh mute --adapter opencode
sh scripts/plugin-runtime.sh unmute --adapter opencode
```

Mute applies to every session using the shared service, including the other
agents. It keeps the classifier loaded; unmute does not replay muted cues.
Control commands do not install a missing runtime or start a stopped service.
Rerun setup explicitly after updating the checkout to update the installed Python
code as well. Updating just the plugin cannot upgrade the service.

For a standalone Python installation, use the existing service commands and set
`AWAITONAL_EXECUTABLE` to its absolute `awaitonal` executable before starting
OpenCode. A configured override is authoritative. The plugin otherwise uses the
stable runtime under `AWAITONAL_PLUGIN_RUNTIME` (or the default user data path),
then the `awaitonal` command on `PATH`. `AWAITONAL_SOCKET` can select a private
service socket. Missing or unavailable executables/services leave the agent quiet.

```sh
awaitonal service start
awaitonal doctor --adapter opencode
awaitonal service mute
awaitonal service unmute
```

Doctor checks the shared runtime and service. It reports plugin registration as
unknown: it does not read OpenCode settings or claim to have inspected a running
plugin. Check OpenCode's configuration and startup log for loading problems.

## Notification boundaries

The bridge observes native activity, message, permission, question, and error
events. It correlates them within a primary session before forwarding a normalized
notification. Session idle alone does not prove a successful response.

- Final assistant prose is classified only after a recognized completed response.
- Active permission requests and questions request attention; their contents are
  not forwarded. Reply/rejection events remove matching attention still waiting
  in the plugin's send queue. Those events do not recall attention already handed
  to the service; turn settlement clears pending service attention.
- Terminal failures use a generic failure cue; raw error details are discarded.
- Cancelled, empty, oversized, or uncertain results end quietly. A matching quiet
  end cancels queued or still-classifying notifications before audio admission.
- Child sessions stay quiet, leaving the parent to report its final outcome.

Each observed activity gets an opaque turn identity for timing and cancellation.
Elapsed time includes tools and waiting; it does not measure reasoning duration.
Missing or ambiguous timing uses the existing ordinary-cue fallback. Namespaced
OpenCode sessions do not collide with identities from other agents.
For a resumed session whose parent/root metadata is verified after activity starts,
the first activity uses that fallback instead of reporting a shortened duration.

Only bounded final assistant text and lifecycle identifiers cross the local bridge.
Prompts, reasoning, tool inputs/results, files, permission patterns, question text,
and raw error details are excluded. The bridge keeps temporary bounded state in
memory. It does not read transcript files, call a model, install dependencies, or
start the service in response to events. Hook failures never return an agent
control decision.

Native event ordering and retry behavior are version-specific. The adapter should
be revalidated when upgrading OpenCode. An already-admitted sound may finish after
cancellation or mute; later activity is not replayed.

## Check the adapter without audio

The files in `examples/opencode-*.json` contain the bridge's normalized protocol,
not raw OpenCode events. From the checkout:

```sh
uv run awaitonal hook opencode --dry-run < examples/opencode-settled.json
uv run awaitonal hook opencode --dry-run < examples/opencode-question.json
uv run awaitonal hook opencode --dry-run < examples/opencode-aborted.json
node --experimental-strip-types --test tests/opencode-plugin.test.mjs
```

Dry runs classify the fixtures without sending to the service or playing audio.
The Node tests exercise native event ordering with synthetic fixtures. See
[validation](../VALIDATION.md) for tested versions and integration-check limits.
The native loader and installed-wheel service were also checked with synthetic
completion, attention, retry, cancellation, failure, and mute cases. These checks
did not call a live model, interact with real TUI prompts, or play audio.

## Remove

Remove only Awaitonal's entry from the `plugin` list or its local wrapper file,
then restart OpenCode. Do not delete other plugin entries. This leaves the shared
service available to the other integrations.

```sh
sh scripts/plugin-runtime.sh detach --adapter opencode
```

That command explains removal; it does not edit OpenCode's files or stop audio for
other agents. To remove the shared runtime as well, use the explicit `uninstall`
action. Doing so stops notifications for every integration sharing that runtime.
