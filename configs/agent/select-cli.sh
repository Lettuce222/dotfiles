#!/bin/sh
# The installer and fish launchers share this selector.
selection=${DOTFILES_AGENT:-}
config=${1:-"$HOME/.config/dotfiles-agent-cli"}
if [ -z "$selection" ] && [ -e "$config" ]; then
    selection=$(cat "$config") || exit 1
fi
selection=${selection:-claude}

case "$selection" in
    [!a-zA-Z0-9]*|*[!a-zA-Z0-9._+-]*)
        printf 'dotfiles: use a single command name in DOTFILES_AGENT or %s (got %s)\n' "$config" "$selection" >&2
        exit 2
        ;;
    *) printf '%s\n' "$selection" ;;
esac
