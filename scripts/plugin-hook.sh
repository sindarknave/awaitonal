#!/bin/sh
# Notification-only: no installation, network, model loading, or service startup.
# This must remain quiet even before setup or after a runtime has been removed.
exec >/dev/null 2>&1
[ -n "${HOME:-}" ] || exit 0
runtime="${AWAITONAL_PLUGIN_RUNTIME:-${XDG_DATA_HOME:-$HOME/.local/share}/awaitonal/plugin}"
if [ -x "$runtime/bin/awaitonal" ]; then
    "$runtime/bin/awaitonal" hook claude
fi
exit 0
