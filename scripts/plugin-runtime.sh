#!/bin/sh
# Explicit setup only. Never invoked by a notification hook.
set -eu
umask 077

action="${1:-status}"
if [ "$#" -gt 0 ]; then shift; fi
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
        # Pass only explicit init options (for example --settings or
        # --legacy-executable); init validates them before touching settings.
        find_uv
        plugin_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
        if [ -x "$executable" ]; then
            "$executable" service stop --expected-executable "$executable"
        fi
        mkdir -p "$runtime"
        # Install a wheel into a stable user environment, never an editable
        # dependency on Claude's versioned plugin cache. Force rebuilding our
        # own package also supports local development without version bumps.
        if ! "$uv_executable" tool install --python '>=3.11' --force --reinstall-package awaitonal "$plugin_root"; then
            printf '%s\n' 'Awaitonal installation failed; rerun setup to retry.' >&2
            if [ -x "$executable" ]; then "$executable" service start || true; fi
            exit 1
        fi
        "$executable" service start
        "$executable" init --mode plugin --apply "$@"
        printf 'Awaitonal is ready. Runtime: %s\n' "$runtime"
        ;;
    status)
        if [ ! -x "$executable" ]; then
            printf '%s\n' 'Awaitonal runtime is not installed. Run /awaitonal:setup.'
            exit 1
        fi
        exec "$executable" doctor "$@"
        ;;
    mute|unmute)
        [ "$#" -eq 0 ] || { printf '%s\n' "$action takes no arguments." >&2; exit 1; }
        if [ ! -x "$executable" ]; then
            printf '%s\n' 'Awaitonal runtime is not installed. Run /awaitonal:setup.' >&2
            exit 1
        fi
        exec "$executable" service "$action" --expected-executable "$executable"
        ;;
    uninstall)
        [ "$#" -eq 0 ] || { printf '%s\n' 'uninstall takes no arguments.' >&2; exit 1; }
        if [ -x "$executable" ]; then
            find_uv
            if [ "$(uname -s)" = Darwin ]; then
                "$executable" service uninstall --expected-executable "$executable"
            fi
            "$executable" service stop --expected-executable "$executable"
            "$uv_executable" tool uninstall awaitonal
        fi
        printf '%s\n' 'Awaitonal runtime removed. Run: claude plugin uninstall awaitonal@awaitonal'
        ;;
    service)
        if [ ! -x "$executable" ]; then
            printf '%s\n' 'Awaitonal runtime is not installed. Run /awaitonal:setup.' >&2
            exit 1
        fi
        exec "$executable" service "$@"
        ;;
    *)
        printf '%s\n' 'Usage: plugin-runtime.sh setup [init options] | status [doctor options] | mute | unmute | service <action> | uninstall' >&2
        exit 1
        ;;
esac
