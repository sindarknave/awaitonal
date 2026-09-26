# Claude Code plugin

The Claude Code plugin and its marketplace both live in this repository. The
plugin uses the same Python package and local service as the command-line install.
It does not contain a second classifier or synthesizer.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) first, then:

```sh
claude plugin marketplace add sindarknave/awaitonal
claude plugin install awaitonal@awaitonal
```

Restart Claude Code and run:

```text
/awaitonal:setup
/awaitonal:status
```

Setup explicitly installs the package and its Python dependencies, then starts
the service. It uses rules by default and does not download a semantic model.
The plugin registers `Stop`, `StopFailure`, `PermissionRequest`,
`PreToolUse` for `AskUserQuestion`, and `UserPromptSubmit` for optional turn timing.
Normal notifications are quiet, bounded, and never install packages, start
services, call a model, or use the network. Before setup, or while the service is
stopped, the hooks quietly do nothing.

On macOS, ask Claude to enable Awaitonal's automatic startup after setup, or run
the following from this repository's root:

```sh
sh scripts/plugin-runtime.sh service install
```

Without automatic startup, run `service start` through the same script when
needed. Use `service stop` to stop playback and `service status` to inspect it.
`/awaitonal:status` runs the broader `doctor` checks; an audible check is explicit
with `sh scripts/plugin-runtime.sh status --test-sound`.

## Existing manual hooks

Setup removes manual hooks previously tracked by `awaitonal init`, showing a diff
and making a settings backup. Claude manages the plugin's hooks, so setup does
not add another copy to settings. Other plugins and unrelated hooks are retained.

The old v0.2 `hook-config` fragment was not tracked. To migrate it, use its exact
executable path, with the same script from the installed plugin or a checkout:

```sh
sh scripts/plugin-runtime.sh setup --legacy-executable '/absolute/path/to/awaitonal'
```

Inspect a migration before applying it with:

```sh
awaitonal init --mode plugin --legacy-executable '/absolute/path/to/awaitonal'
```

If the old fragment is in a project settings file, pass `--settings` for that file
as well. Leaving an untracked manual hook in place can generate duplicate events.

Before upgrading from v0.2, stop its foreground service with Ctrl-C in the terminal
where you started it, then run setup. That release has no service-control protocol,
so the new installer cannot authenticate or stop its listener. Setup does not kill
a process based on an old socket or PID. If another Awaitonal installation owns the
socket, stop it with that installation's service command or use a separate
`AWAITONAL_SOCKET`; setup will not evict it.

## Update

```sh
claude plugin marketplace update awaitonal
claude plugin update awaitonal@awaitonal
```

Restart Claude Code, then rerun `/awaitonal:setup` to update the installed runtime.
Plugin updates do not install Python dependencies in the background. The old
runtime remains available until explicit setup upgrades it.
Setup stops its own service before replacing the package and starts it again
afterward. An existing Awaitonal login service resumes under macOS supervision
with its saved settings. If installation fails while the old runtime is still
available, setup attempts to restart it.

The installed runtime is under
`${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin`, outside Claude's versioned
plugin cache. Setup builds a regular installed package with `uv tool install`;
it is not an editable install pointing into a disposable cache directory.
The runtime therefore survives plugin cache moves and old-version cleanup.
`AWAITONAL_PLUGIN_RUNTIME` can override the absolute runtime directory; set it
consistently for setup and the Claude process. `AWAITONAL_SOCKET` can similarly
choose an existing private socket location.

## Disable or remove

To temporarily silence notifications, use `/awaitonal:mute`. Resume them with
`/awaitonal:unmute`; `/awaitonal:status` shows the current mute state.

These controls apply to all sessions sharing the service. The process and model
stay loaded, queued notifications are discarded, and sounds received while muted
are not replayed later. A cue already starting or playing may finish. Mute lasts until an
explicit unmute or service restart. The commands require a running, up-to-date
runtime; they do not install dependencies, start services, or change system volume.
Unmuting does not override diagnostic `--silent` mode.

The corresponding terminal commands are `awaitonal service mute` and
`awaitonal service unmute`. The plugin calls its own stable runtime through
`scripts/plugin-runtime.sh mute` or `scripts/plugin-runtime.sh unmute`.

To disable the plugin's hooks and skills:

```sh
claude plugin disable awaitonal@awaitonal
```

Disabling removes the plugin's hooks from subsequent Claude sessions. It does not
stop a shared service or delete its runtime. To remove both, run
`/awaitonal:uninstall` before removing the plugin. The skill removes the plugin
runtime and its automatic startup, then runs:

```sh
claude plugin uninstall awaitonal@awaitonal
```

User palette files and settings backups remain intact. If the plugin was removed
first, the runtime can still be removed from a checkout with
`sh scripts/plugin-runtime.sh uninstall`.

## Development and compatibility

Audio playback and automatic startup currently target macOS. Linux supports
classification, WAV rendering, and the hook transport, but has no built-in audio
player. Python 3.11 or newer is required; setup lets uv find or install a compatible
Python. Claude Code 2.1.158 was used to verify
manifest validation, install, update, disable, enable, and uninstall in an
isolated `CLAUDE_CONFIG_DIR`, including paths containing spaces.

```sh
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json
claude --plugin-dir /absolute/path/to/awaitonal
```

For a local marketplace test, run `claude plugin marketplace add` with the
repository's absolute path. The marketplace source `./` is relative to this
repository root. Hooks are auto-discovered from `hooks/hooks.json`; do not also
declare that file in `plugin.json`, which would register the hooks twice.

Primary references: [plugin manifests](https://code.claude.com/docs/en/plugins-reference)
and [marketplace installation](https://code.claude.com/docs/en/plugin-marketplaces).
