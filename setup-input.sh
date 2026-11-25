#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
rule=/etc/udev/rules.d/70-kitajimacro-input.rules
module=/etc/modules-load.d/kitajimacro.conf

if [[ $EUID -ne 0 ]]; then
    printf '%s\n' 'Run this setup script with sudo.' >&2
    exit 1
fi
case "${1:-}" in
    '')
        if [[ ! -c /dev/uinput ]]; then
            modprobe uinput
        fi
        install -m 0644 "$root/ubuntu/70-kitajimacro-input.rules" "$rule"
        printf '%s\n' uinput >"$module"
        ;;
    --remove)
        rm -f -- "$rule" "$module"
        ;;
    *)
        printf '%s\n' 'Usage: setup-input.sh [--remove]' >&2
        exit 2
        ;;
esac
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=input
udevadm trigger --action=change --subsystem-match=misc --sysname-match=uinput
udevadm settle
printf '%s\n' 'Sign out and back in if the access change has not taken effect.'
