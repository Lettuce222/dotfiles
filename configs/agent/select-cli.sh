#!/bin/sh
# The installer and fish launchers share this selector.
selection=${DOTFILES_AGENT:-}
config=${1:-"$HOME/.config/dotfiles-agent-cli"}
if [ -z "$selection" ] && [ -e "$config" ]; then
    selection=$(cat "$config") || exit 1
fi
if [ -z "$selection" ]; then
    case "$(uname -s)" in
        Linux) selection=codex ;;
        *) selection=claude ;;
    esac
fi

case "$selection" in
    claude|codex) printf '%s\n' "$selection" ;;
    *) printf 'dotfiles: expected claude or codex in DOTFILES_AGENT or %s (got %s)\n' "$config" "$selection" >&2
       exit 2 ;;
esac
