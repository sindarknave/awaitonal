#!/bin/sh
# Explicit setup only. Never invoked by a notification hook.
set -eu
umask 077

action="${1:-status}"
if [ "$#" -gt 0 ]; then shift; fi
adapter=claude
if [ "${1:-}" = --adapter ]; then
    [ "$#" -ge 2 ] || { printf '%s\n' '--adapter requires claude, codex, pi, or opencode.' >&2; exit 1; }
    adapter="$2"
    shift 2
fi
case "$adapter" in
    claude|codex|pi|opencode) ;;
    *) printf '%s\n' '--adapter requires claude, codex, pi, or opencode.' >&2; exit 1 ;;
esac
for argument in "$@"; do
    case "$argument" in
        --adapter|--adapter=*)
            printf '%s\n' 'Place --adapter claude|codex|pi|opencode immediately after the action.' >&2
            exit 1 ;;
        --mode|--mode=*)
            if [ "$adapter" = codex ]; then
                printf '%s\n' 'Codex setup uses managed standalone hooks; --mode overrides are not supported.' >&2
                exit 1
            fi ;;
    esac
done
if [ "$adapter" = pi ] || [ "$adapter" = opencode ]; then
    adapter_label=Pi
    registration_label=extension
    if [ "$adapter" = opencode ]; then
        adapter_label=OpenCode
        registration_label=plugin
    fi
    case "$action" in
        setup|status|detach)
            [ "$#" -eq 0 ] || { printf '%s\n' "$adapter_label $action takes no arguments; $adapter_label manages $registration_label registration." >&2; exit 1; }
            ;;
    esac
fi
setup_command=/awaitonal:setup
if [ "$adapter" = pi ]; then setup_command=/awaitonal-setup; fi
if [ "$adapter" = opencode ]; then setup_command='sh scripts/plugin-runtime.sh setup --adapter opencode from the Awaitonal checkout'; fi
runtime="${AWAITONAL_PLUGIN_RUNTIME:-${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin}"
case "$runtime" in
    /*) ;;
    *) printf '%s\n' 'Awaitonal runtime must be an absolute path.' >&2; exit 1 ;;
esac
executable="$runtime/bin/awaitonal"

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        uv_executable=$(command -v uv)
    elif [ -x "$HOME/.local/bin/uv" ]; then
        uv_executable="$HOME/.local/bin/uv"
    else
        printf '%s\n' 'Awaitonal setup needs uv. Install it from https://docs.astral.sh/uv/getting-started/installation/ and rerun setup.' >&2
        exit 1
    fi
    export UV_TOOL_DIR="$runtime/tools"
    export UV_TOOL_BIN_DIR="$runtime/bin"
}

case "$action" in
    setup)
        # Claude and Codex accept explicit init options. Native Pi/OpenCode
        # registration is host-owned, so setup accepts no init arguments.
        find_uv
        plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
        if [ -x "$executable" ]; then
            "$executable" service stop --expected-executable "$executable"
        fi
        mkdir -p "$runtime"
        # Install a wheel into a stable user environment, never an editable
        # dependency on an app's versioned plugin cache. Force rebuilding our
        # own package also supports local development without version bumps.
        if ! "$uv_executable" tool install --python '>=3.11' --force --reinstall-package awaitonal "$plugin_root"; then
            printf '%s\n' 'Awaitonal installation failed; rerun setup to retry.' >&2
            if [ -x "$executable" ]; then "$executable" service start || true; fi
            exit 1
        fi
        "$executable" service start
        if [ "$adapter" != pi ] && [ "$adapter" != opencode ]; then
            hook_mode=plugin
            if [ "$adapter" = codex ]; then hook_mode=standalone; fi
            "$executable" init --adapter "$adapter" --mode "$hook_mode" --apply "$@"
        fi
        printf 'Awaitonal is ready. Runtime: %s\n' "$runtime"
        ;;
    status)
        if [ ! -x "$executable" ]; then
            printf 'Awaitonal runtime is not installed. Run %s.\n' "$setup_command"
            exit 1
        fi
        if [ "$adapter" = pi ]; then
            printf '%s\n' 'Pi extension loading is managed by pi install; this reports the shared service.' >&2
            exec "$executable" service status
        fi
        if [ "$adapter" = opencode ]; then
            printf '%s\n' 'OpenCode plugin loading is managed by OpenCode; this reports the shared service.' >&2
            exec "$executable" service status
        fi
        exec "$executable" doctor --adapter "$adapter" "$@"
        ;;
    mute|unmute)
        [ "$#" -eq 0 ] || { printf '%s\n' "$action takes no arguments." >&2; exit 1; }
        if [ ! -x "$executable" ]; then
            printf 'Awaitonal runtime is not installed. Run %s.\n' "$setup_command" >&2
            exit 1
        fi
        exec "$executable" service "$action" --expected-executable "$executable"
        ;;
    detach)
        if [ "$adapter" = opencode ]; then
            printf '%s\n' 'Remove only the Awaitonal entry from the OpenCode plugin list (or its local loader file), then restart OpenCode. The shared service remains available.'
            exit 0
        fi
        if [ "$adapter" = pi ]; then
            printf '%s\n' 'Remove the Pi extension with pi remove, using the original package source or path passed to pi install.'
            exit 0
        fi
        if [ ! -x "$executable" ]; then
            printf '%s\n' 'Awaitonal runtime is not installed; cannot remove its tracked hooks.' >&2
            exit 1
        fi
        # Removes only tracked hooks for the selected app. The service remains
        # available to the other app and to other installations sharing it.
        exec "$executable" uninstall --adapter "$adapter" --apply "$@"
        ;;
    uninstall)
        [ "$#" -eq 0 ] || { printf '%s\n' 'uninstall takes no arguments.' >&2; exit 1; }
        if [ -x "$executable" ]; then
            find_uv
            if [ "$adapter" = codex ]; then
                "$executable" uninstall --adapter codex --apply
            fi
            if [ "$(uname -s)" = Darwin ]; then
                "$executable" service uninstall --expected-executable "$executable"
            fi
            "$executable" service stop --expected-executable "$executable"
            "$uv_executable" tool uninstall awaitonal
        fi
        printf '%s\n' 'Shared Awaitonal runtime removed; Claude, Codex, Pi, and OpenCode notifications are now inactive.'
        if [ "$adapter" = codex ]; then
            printf '%s\n' 'Remove the Awaitonal plugin in Codex, or use codex plugin remove with its installed marketplace selector.'
        elif [ "$adapter" = pi ]; then
            printf '%s\n' 'Remove the Pi extension with pi remove, using the original package source or path passed to pi install.'
        elif [ "$adapter" = opencode ]; then
            printf '%s\n' 'Remove only the Awaitonal entry from the OpenCode plugin list (or its local loader file), then restart OpenCode.'
        else
            printf '%s\n' 'Run: claude plugin uninstall awaitonal@awaitonal'
        fi
        ;;
    service)
        if [ ! -x "$executable" ]; then
            printf 'Awaitonal runtime is not installed. Run %s.\n' "$setup_command" >&2
            exit 1
        fi
        exec "$executable" service "$@"
        ;;
    *)
        printf '%s\n' 'Usage: plugin-runtime.sh <setup|status|mute|unmute|detach|service|uninstall> [--adapter claude|codex|pi|opencode] [action options]' >&2
        exit 1
        ;;
esac
