# Pi integration

Awaitonal's Pi package lives in this repository alongside its Claude Code and
Codex integrations. It uses the same local Python service, classifier, palette,
global mute, and optional rotating session voices. Playback currently uses macOS
`afplay`; Linux can classify and render WAVs but has no built-in audio player.

## Install

Use Pi 0.87.1 or newer, Python 3.11+, and [uv](https://docs.astral.sh/uv/).
Install the release from GitHub:

```sh
pi install git:github.com/sindarknave/awaitonal@v0.6.0
```

For local development, use `pi install /absolute/path/to/awaitonal` instead.

Start Pi or run `/reload`, then:

```text
/awaitonal-setup
/awaitonal-status
```

Setup explicitly installs Awaitonal into its stable user runtime and starts the
service. Updating that runtime also updates the code used by Claude and Codex.
Setup does not register or remove hooks for either app. If a different Awaitonal
installation owns the socket, stop it with its own CLI before switching.

The Pi package manifest loads only `extensions/pi.ts`. It does not automatically
load the Claude/Codex setup skills. Pi owns package registration and settings;
Awaitonal's `init`, `uninstall`, and `hook-config` commands are for Claude/Codex
hook files, not Pi packages.

The release install is pinned to v0.6.0. When installing a newer release, use its
tag, then `/reload` and rerun `/awaitonal-setup` to update the Python runtime.
For a local installation, run those same commands after changing the checkout.
Keep that checkout at its installed path, or reinstall it from its new location.

## Controls

| Pi command | Effect |
| --- | --- |
| `/awaitonal-setup` | Explicitly install/update the stable runtime and start the service |
| `/awaitonal-status` | Inspect the shared service |
| `/awaitonal-mute` | Mute every session using that service |
| `/awaitonal-unmute` | Resume future notifications without replaying missed ones |

Mute leaves the process and model loaded. It does not change your system volume.
The extension never installs dependencies or starts the service in response to
an agent event. Missing or stopped runtimes make notifications quietly inactive.

For login startup on macOS, run this explicit command from the checkout:

```sh
sh scripts/plugin-runtime.sh service --adapter pi install
```

Run `awaitonal doctor --adapter pi` for runtime and playback checks. It reports
extension registration as unknown: inspect `pi list` and the commands available
inside Pi to verify that Pi loaded the package.

## Standalone runtime

If Awaitonal is already installed separately, set `AWAITONAL_EXECUTABLE` to its
absolute executable path before launching Pi. Otherwise the extension uses the
stable plugin runtime, then an `awaitonal` executable on `PATH`.

```sh
AWAITONAL_EXECUTABLE=/absolute/path/to/awaitonal pi
```

`AWAITONAL_PLUGIN_RUNTIME` overrides the stable runtime directory (an absolute
path). Its default is `${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin`.
`AWAITONAL_SOCKET` selects the socket; use the same value for the service and Pi.
An executable override controls notification delivery and service controls;
setup still installs the managed runtime, so use your own install/update process
when deliberately keeping a standalone installation.

## Events and privacy

| Pi event | Awaitonal behavior |
| --- | --- |
| First `agent_start` in an activity | Begin elapsed-time tracking |
| `message_end` | Keep only the latest assistant text in memory |
| `agent_before_settle` | Observe the completion/error/cancellation outcome before settlement |
| `agent_settled` | Notify once after retries, compaction, and automatic continuations finish |
| `ui_prompt_start` during an active run | Play the decision cue for a blocking extension dialog |
| Session change or shutdown | Close unfinished tracking quietly |

Intermediate `agent_end` and `turn_end` events do not play completion sounds.
Retries retain the original activity start time. Timing measures elapsed work,
not thinking tokens or model reasoning duration. Aborted or text-free settlements
close timing without a sound, so the next activity can still be timed.

Terminal errors play the generic `failed` cue. Raw errors are discarded, so this
integration does not distinguish rate limits, authentication errors, or billing
errors. Prose requests for sign-in still use Awaitonal's normal classifier.
Pi has no built-in permission system; its extension dialogs are treated as
questions rather than guessed to be permission requests. Idle menus stay quiet.

Pi's `agent_settled` event has no outcome field. If it arrives without an observed
pre-settlement outcome (for example, cancellation during retry backoff), Awaitonal
ends quietly. A different extension that cancels after Awaitonal's pre-settlement
handler may not expose that later cancellation through Pi's public events.

Inspect the normalized bridge fixtures without playing audio:

```sh
uv run awaitonal hook pi --dry-run < examples/pi-settled.json
uv run awaitonal hook pi --dry-run < examples/pi-question.json
uv run awaitonal hook pi --dry-run < examples/pi-error.json
uv run awaitonal hook pi --dry-run < examples/pi-aborted.json
```

The bridge sends only bounded assistant text, generated activity/request IDs,
and a provider-scoped session identity. It excludes thinking blocks, user prompts,
tool arguments/results, transcript paths, dialog titles, and raw error details.
Oversized final text is omitted instead of being truncated into a misleading
completion; its activity still closes quietly.

Notification subprocesses use argument arrays and stdin, with no shell or model
loading. The existing Python client authenticates the private Unix socket before
sending text. Queueing, playback, and the global mute state remain in the resident
service. Remote Pi sessions need a separate local bridge to reach your Mac.

## Remove

Remove the package using the same source used for installation:

```sh
pi remove git:github.com/sindarknave/awaitonal@v0.6.0
```

For a local installation, use `pi remove /absolute/path/to/awaitonal` instead.

Then `/reload` or restart Pi. This leaves Claude, Codex, and the shared service
working. Remove the shared runtime only when you want to stop all integrations:

```sh
sh scripts/plugin-runtime.sh uninstall --adapter pi
```

Removing the runtime does not remove other apps' plugin registrations or hooks.

## Compatibility references

The extension targets the current `@earendil-works/pi-coding-agent` API. Older Pi
versions without the final settlement boundary are not supported; falling back
to `agent_end` could announce completion before an automatic retry.

Primary references: [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md),
[event types](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/extensions/types.ts),
and [Pi packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md).
