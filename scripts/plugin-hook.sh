#!/bin/sh
# Notification-only: no installation, network, model loading, or service startup.
# This must remain quiet even before setup or after a runtime has been removed.
exec >/dev/null 2>&1
[ -n "${HOME:-}" ] || exit 0
adapter=claude
if [ "$#" -gt 0 ]; then
    [ "$#" -eq 2 ] && [ "$1" = --adapter ] || exit 0
    adapter="$2"
fi
case "$adapter" in claude|codex|pi) ;; *) exit 0 ;; esac
runtime="${AWAITONAL_PLUGIN_RUNTIME:-${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin}"
case "$runtime" in /*) ;; *) exit 0 ;; esac
if [ -x "$runtime/bin/awaitonal" ]; then
    "$runtime/bin/awaitonal" hook "$adapter"
fi
exit 0
