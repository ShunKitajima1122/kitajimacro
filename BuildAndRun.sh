#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
app=$root/ubuntu/main.py

if [[ $EUID -eq 0 ]]; then
    printf '%s\n' 'Run Kitajimacro as your desktop user. Only ubuntu/setup-input.sh uses sudo.' >&2
    exit 1
fi
if ! /usr/bin/python3 -B -c 'import evdev, gi, pyudev; gi.require_version("Gtk", "3.0"); gi.require_version("AyatanaAppIndicator3", "0.1")' >/dev/null 2>&1; then
    printf '%s\n' 'Install the Ubuntu packages listed in README.md, then run this script again.' >&2
    exit 1
fi
if [[ -z ${DISPLAY:-} && -z ${WAYLAND_DISPLAY:-} ]]; then
    printf '%s\n' 'Run Kitajimacro from a graphical desktop session.' >&2
    exit 1
fi
if [[ ${1:-} == --foreground ]]; then
    shift
    exec /usr/bin/python3 -B "$app" "$@"
fi
if [[ ${1:-} == --exit ]]; then
    exec /usr/bin/python3 -B "$app" "$@"
fi

state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/kitajimacro"
mkdir -p -- "$state_dir"
nohup /usr/bin/python3 -B "$app" "$@" </dev/null >>"$state_dir/kitajimacro.log" 2>&1 &
