# Coding-agent integrations

All app integrations and the marketplace live in this repository. They use the
same Python package, local service, and stable runtime. There is no second
classifier or synthesizer.

Pi uses an extension package with `/awaitonal-setup`, `/awaitonal-status`,
`/awaitonal-mute`, and `/awaitonal-unmute` commands. Install it with
`pi install git:github.com/sindarknave/awaitonal@v0.8.0`, or use
`pi install /absolute/path/to/awaitonal` for a local checkout. Remove it with
`pi remove` followed by that same source. See the [Pi guide](pi.md) for setup and
updates. Pi owns extension registration; setup only installs/updates the shared
Python runtime and starts the service.

OpenCode 1.18.33 uses a native V1 plugin entrypoint at `extensions/opencode.ts`
in the v0.8.0 release checkout.
Register that file in OpenCode's `plugin` configuration and run
`sh scripts/plugin-runtime.sh setup --adapter opencode` explicitly from this
checkout. Registration remains owned by OpenCode. See the [OpenCode guide](opencode.md);
this entrypoint does not support OpenCode V2.

## Install in Codex from this checkout

Install the Codex package from a local checkout with a current Codex CLI and
[uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
codex plugin marketplace add /absolute/path/to/awaitonal
codex plugin add awaitonal@awaitonal
```

Start a new Codex task, invoke Awaitonal's setup skill, and ask for its status.
The setup skill runs the installed plugin's wrapper with `setup --adapter codex`.
It installs the shared runtime, starts the service, and registers tracked Codex
user hooks pointing at that stable runtime. The hook changes show a diff and
create a backup; unrelated hooks remain intact. It does not modify Claude's settings. Review and trust the current
Awaitonal hook definitions in Codex's `/hooks` view; setup does not bypass hook
trust. [OpenAI plugin documentation](https://developers.openai.com/plugins/build/plugins)

To use the package directly without installing the plugin, install Awaitonal
from this checkout, then preview and apply its Codex hook configuration:

```sh
awaitonal init --adapter codex
awaitonal init --adapter codex --apply
awaitonal service start
awaitonal doctor --adapter codex
```

The default Codex hook file is `~/.codex/hooks.json` (or under `CODEX_HOME` when
configured). Pass `--settings /absolute/path/to/hooks.json` to target another
file. `doctor --adapter codex` inspects that file; use Codex's own hook view to
check active hooks and trust. Codex plugin setup uses the same tracked standalone
registration as `init`; rerunning setup updates those entries without duplication.

The Codex manifests explicitly set `hooks: []`: setup owns hook registration,
and neither manifest can accidentally load Claude's `hooks/hooks.json`. A Codex
hook template remains in `hooks/codex.json` for reference. Codex receives `Stop`, `PermissionRequest`,
`PreToolUse` for `request_user_input` and `request_user_input_async`, and
`UserPromptSubmit`. No unsupported `StopFailure` hook is registered for Codex.
Do not add the template on top of setup's hooks. Setup rejects a `--mode` override
for Codex to keep registration consistent.

After updating a local checkout, reinstall the Codex plugin with
`codex plugin add awaitonal@awaitonal`, start a new task, and rerun the setup skill
to update the runtime. This repository package is separate from a public listing
in OpenAI's plugin directory.

## Install in Claude Code

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

The shared installed runtime is under
`${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin`, outside Claude's versioned
and Codex's versioned plugin caches. Setup builds a regular installed package with `uv tool install`;
it is not an editable install pointing into a disposable cache directory.
The runtime therefore survives plugin cache moves and old-version cleanup.
`AWAITONAL_PLUGIN_RUNTIME` can override the absolute runtime directory; set it
consistently for setup and all app processes. `AWAITONAL_SOCKET` can similarly
choose an existing private socket location.

## Disable or remove

To temporarily silence notifications, use `/awaitonal:mute`. Resume them with
`/awaitonal:unmute`; `/awaitonal:status` shows the current mute state.

These controls apply to all Claude, Codex, Pi, and OpenCode sessions sharing the service. The process and model
stay loaded, queued notifications are discarded, and sounds received while muted
are not replayed later. A cue already starting or playing may finish. Mute lasts until an
explicit unmute or service restart. The commands require a running, up-to-date
runtime; they do not install dependencies, start services, or change system volume.
Unmuting does not override diagnostic `--silent` mode.

The corresponding terminal commands are `awaitonal service mute` and
`awaitonal service unmute`. The plugin calls its own stable runtime through
`scripts/plugin-runtime.sh mute` or `scripts/plugin-runtime.sh unmute`.

To disable the Claude plugin's hooks and skills:

```sh
claude plugin disable awaitonal@awaitonal
```

Disabling removes the plugin's hooks from subsequent Claude sessions. It does not
stop a shared service or delete its runtime. To remove only the Codex integration,
run the following from a checkout (or use the installed plugin's uninstall skill):

```sh
sh scripts/plugin-runtime.sh detach --adapter codex
codex plugin remove awaitonal@awaitonal
```

Pass the original `--settings` path to `detach` if setup targeted a custom hook
file. Detach removes only Awaitonal's tracked Codex hooks and leaves the shared
runtime and Claude integration working. Removing or disabling the Codex plugin
alone leaves its setup-managed user hooks active.

Removing the shared runtime and automatic startup stops notifications in all connected
apps. Request runtime removal explicitly through the Awaitonal uninstall skill,
or run `sh scripts/plugin-runtime.sh uninstall --adapter codex` from a checkout.
The Codex runtime-uninstall command first removes its tracked hooks from the
default Codex hook file; detach any custom hook file first. The wrapper leaves
both plugin registrations alone; remove the desired plugin afterward through
its app. Claude's removal command is:

```sh
claude plugin uninstall awaitonal@awaitonal
```

User palette files and settings backups remain intact. If the plugin was removed
first, the runtime can still be removed from a checkout with
`sh scripts/plugin-runtime.sh uninstall` (defaults to Claude instructions).

## Development and compatibility

Audio playback and automatic startup currently target macOS. Linux supports
classification, WAV rendering, and the hook transport, but has no built-in audio
player. Python 3.11 or newer is required; setup lets uv find or install a compatible
Python. Codex CLI 0.155.0-alpha.16.4 was used to verify local marketplace discovery,
installation, listing, and removal with an isolated temporary configuration.
Its native hook inventory recognized all four standalone hooks as untrusted with
no errors. Bundled plugin hooks did not appear in that build's inventory, even
at the default hook path, so Codex setup deliberately manages user hooks instead.
These checks did not run models or trust hooks. Claude Code 2.1.158 was used to verify
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
declare that file in `.claude-plugin/plugin.json`, which would register the hooks
twice. Codex deliberately disables bundled hook discovery in its own manifests
and installs tracked user hooks during setup.

Primary references: [plugin manifests](https://code.claude.com/docs/en/plugins-reference)
and [marketplace installation](https://code.claude.com/docs/en/plugin-marketplaces).
