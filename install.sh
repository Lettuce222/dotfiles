#!/bin/sh

# =============================================================================
# Phase 1: sh で実行（Homebrew, fish, symlinks）
# =============================================================================

# Symlinks point at this checkout, so running from a git worktree would rewire
# $HOME to a directory that disappears when the worktree is removed.
refuse_worktree_checkout() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    command -v git >/dev/null 2>&1 || return 0
    git_dir=$(git -C "$script_dir" rev-parse --path-format=absolute --git-dir 2>/dev/null) || return 0
    common_dir=$(git -C "$script_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
    if [ "$git_dir" != "$common_dir" ]; then
        echo "install.sh must be run from the main checkout, not a git worktree: $script_dir" >&2
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# --links-only: place symlinks and generate settings without installing
# anything. It is safe to run unattended: it never touches the network, never
# asks for a password, and only changes things under $HOME. Anything that is
# not a symlink is left in place and reported instead of being replaced.
# Without --links-only these helpers behave exactly as the full install did.
# -----------------------------------------------------------------------------
LINKS_ONLY=0
DRY_RUN=0
LINK_CHANGES=""
LINK_SKIPS=""

record_change() {
    if [ "$DRY_RUN" -eq 1 ]; then
        LINK_CHANGES="${LINK_CHANGES}(dry-run) $1
"
    else
        LINK_CHANGES="${LINK_CHANGES}$1
"
    fi
}

record_skip() {
    LINK_SKIPS="${LINK_SKIPS}skip: $1
"
}

# Run a command that changes $HOME, unless this is a dry run.
run_change() {
    [ "$DRY_RUN" -eq 1 ] || "$@"
}

ensure_dir() {
    if [ "$LINKS_ONLY" -eq 0 ]; then
        mkdir -p "$1"
        return
    fi
    [ -d "$1" ] && return 0
    if [ -e "$1" ] || [ -L "$1" ]; then
        record_skip "$1 exists and is not a directory; left it in place"
        return 1
    fi
    record_change "mkdir $1"
    run_change mkdir -p "$1"
}

# Point $2 at $1.
place_link() {
    if [ "$LINKS_ONLY" -eq 0 ]; then
        ln -snfv "$1" "$2"
        return
    fi
    if [ -L "$2" ]; then
        link_current=$(readlink "$2")
        [ "$link_current" = "$1" ] && return 0
        record_change "relink $2 -> $1 (was $link_current)"
        run_change ln -snf "$1" "$2"
    elif [ -e "$2" ]; then
        record_skip "$2 is not a symlink; left it in place instead of linking $1"
    else
        record_change "link $2 -> $1"
        run_change ln -sn "$1" "$2"
    fi
}

# chmod +x the linked script. $1 = link, $2 = its source.
make_executable() {
    if [ "$LINKS_ONLY" -eq 0 ]; then
        chmod +x "$1"
        return
    fi
    [ -x "$2" ] && return 0
    record_change "chmod +x $2"
    run_change chmod +x "$2"
}

print_link_summary() {
    if [ -n "$LINK_CHANGES" ]; then
        printf '%s' "$LINK_CHANGES"
    elif [ "$DRY_RUN" -eq 1 ]; then
        echo "(dry-run) 変更なし"
    else
        echo "変更なし"
    fi
    printf '%s' "$LINK_SKIPS"
}

usage() {
    cat <<'USAGE'
Usage: ./install.sh [--links-only] [--dry-run]

  (no options)  Full setup: Homebrew, fish, login shell, symlinks, mise, apps,
                macOS defaults.
  --links-only  Only place the symlinks and generate ~/.claude/settings.json
                and configs/git/ignore.
                Never installs anything, asks for a password, or replaces a
                file that is not a symlink. Prints one line per change.
  --dry-run     Like --links-only, but changes nothing and prints the plan.
USAGE
}

install_homebrew() {
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew is not installed. Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)"
    else
        echo "Homebrew is already installed."
    fi
}

install_fish() {
    if ! command -v fish >/dev/null 2>&1; then
        echo "Installing fish..."
        brew install fish
    else
        echo "fish is already installed."
    fi
}

set_fish_as_default_shell() {
    fish_path=$(command -v fish)

    if [ -z "$fish_path" ]; then
        echo "fish is not installed. Skipping default shell setup."
        return 1
    fi

    # Check if fish is already in /etc/shells
    if ! grep -q "^$fish_path$" /etc/shells; then
        echo "Adding fish to /etc/shells (requires sudo)..."
        echo "$fish_path" | sudo tee -a /etc/shells
    fi

    # Check if fish is already the default shell
    if [ "$SHELL" != "$fish_path" ]; then
        echo "Setting fish as default shell..."
        chsh -s "$fish_path"
    else
        echo "fish is already the default shell."
    fi
}

create_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)

    if [ ! -d "$script_dir/configs" ]; then
        return 1
    fi

    ensure_dir "$HOME/.config"

    for dir in "$script_dir/configs"/*; do
        if [ -d "$dir" ]; then
            dirname=$(basename "$dir")
            # Skip dirs handled separately:
            #   claude/agent -> ~/.claude (per-file/per-skill), hammerspoon -> ~/.hammerspoon
            if [ "$dirname" = "claude" ] || [ "$dirname" = "agent" ] || [ "$dirname" = "hammerspoon" ]; then
                continue
            fi
            source_path="$script_dir/configs/$dirname"
            target_path="$HOME/.config/$dirname"

            place_link "$source_path" "$target_path"
        fi
    done
}

create_claude_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    claude_config_dir="$script_dir/configs/claude"

    if [ ! -d "$claude_config_dir" ]; then
        return 0
    fi

    ensure_dir "$HOME/.claude"

    # Claude-specific files only (statusline.sh, ...).
    # Shared assets (CLAUDE.md / skills / hooks) live in configs/agent and are
    # linked by create_shared_agent_symlinks.
    # settings*.json are merged into a real file by generate_claude_settings.
    for file in "$claude_config_dir"/*; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            case "$filename" in
                settings.json|settings.local.json) continue ;;
            esac
            place_link "$file" "$HOME/.claude/$filename"
            # Make shell scripts executable
            if [ "${filename##*.}" = "sh" ]; then
                make_executable "$HOME/.claude/$filename" "$file"
            fi
        fi
    done
}

# Write ~/.claude/settings.json as a real file merged from the tracked
# configs/claude/settings.json and the gitignored settings.local.json.
# Claude Code reads user settings only from ~/.claude/settings.json and also
# writes to it (`claude plugin enable`, /config, /model). A symlink would send
# those writes, including work-only plugins, into the tracked file.
# Merge rules follow Claude Code's own: objects merge by key, arrays
# concatenate without duplicates, and local scalars win.
# A snapshot of the last generated file detects writes made since then; the
# changed file is backed up before it is overwritten.
generate_claude_settings() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    base="$script_dir/configs/claude/settings.json"
    local_file="$script_dir/configs/claude/settings.local.json"
    dest="$HOME/.claude/settings.json"
    snapshot="$HOME/.claude/settings.json.generated"

    [ -f "$base" ] || return 0
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 is not installed; skipping $dest" >&2
        return 1
    fi

    tmp=$(mktemp "${TMPDIR:-/tmp}/claude-settings.XXXXXX") || return 1
    if ! python3 -I - "$base" "$local_file" >"$tmp" <<'EOF'
import json
import os
import sys


def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for key, value in b.items():
            out[key] = merge(a[key], value) if key in a else value
        return out
    if isinstance(a, list) and isinstance(b, list):
        return a + [item for item in b if item not in a]
    return b


base_path, local_path = sys.argv[1], sys.argv[2]
with open(base_path) as f:
    settings = json.load(f)
if os.path.isfile(local_path):
    with open(local_path) as f:
        settings = merge(settings, json.load(f))
json.dump(settings, sys.stdout, indent=2, ensure_ascii=False)
sys.stdout.write("\n")
EOF
    then
        echo "Failed to merge Claude settings; leaving $dest unchanged" >&2
        rm -f "$tmp"
        return 1
    fi

    if [ "$LINKS_ONLY" -eq 1 ]; then
        update_claude_settings_safely "$tmp" "$dest" "$snapshot" "$local_file"
        rm -f "$tmp"
        return 0
    fi

    if [ -L "$dest" ]; then
        # Migrate from the old symlink layout.
        rm -f "$dest"
    elif [ -f "$dest" ] && ! cmp -s "$dest" "$tmp"; then
        if [ ! -f "$snapshot" ] || ! cmp -s "$dest" "$snapshot"; then
            backup="$dest.bak.$(date +%Y%m%d%H%M%S)"
            cp "$dest" "$backup"
            echo "WARNING: $dest was changed outside install.sh (e.g. by claude plugin enable)." >&2
            echo "  Backed up to $backup. Move what you need into configs/claude/settings.local.json." >&2
        fi
    fi

    mv "$tmp" "$dest"
    cp "$dest" "$snapshot"
    echo "Generated $dest"

    # ~/.claude/settings.local.json is not a user settings file; drop the old link.
    old_local="$HOME/.claude/settings.local.json"
    if [ -L "$old_local" ] && [ "$(readlink "$old_local")" = "$local_file" ]; then
        rm -f "$old_local"
    fi
}

# Write the global gitignore configs/git/ignore (git reads it as
# ~/.config/git/ignore through the configs/git symlink) from the tracked
# configs/git/ignore.shared. Tools append their own rules to that file:
# Claude Code adds `**/.claude/.cc-writes/` to the file that
# `git config --global core.excludesfile` names, or ~/.config/git/ignore.
# So the file itself is gitignored and machine-specific; the tracked rules go
# into a marked block at its top, and lines outside the block are kept as is.
GIT_IGNORE_BEGIN="# >>> dotfiles: configs/git/ignore.shared から install.sh が書く。ここから下の区切りまでは直さない"
GIT_IGNORE_END="# <<< dotfiles"
generate_git_ignore() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    shared="$script_dir/configs/git/ignore.shared"
    dest="$script_dir/configs/git/ignore"

    [ -f "$shared" ] || return 0
    if [ -e "$dest" ] && [ ! -f "$dest" ]; then
        record_skip "$dest is not a regular file; left it in place"
        return 0
    fi

    tmp=$(mktemp "${TMPDIR:-/tmp}/git-ignore.XXXXXX") || return 1
    {
        printf '%s\n' "$GIT_IGNORE_BEGIN"
        awk 1 "$shared"
        printf '%s\n' "$GIT_IGNORE_END"
        if [ -f "$dest" ]; then
            awk -v begin="$GIT_IGNORE_BEGIN" -v end="$GIT_IGNORE_END" '
                $0 == begin { inside = 1; next }
                inside && $0 == end { inside = 0; next }
                !inside
            ' "$dest"
        fi
    } >"$tmp"

    if [ -f "$dest" ] && cmp -s "$dest" "$tmp"; then
        rm -f "$tmp"
        return 0
    fi
    chmod 644 "$tmp"
    if [ "$LINKS_ONLY" -eq 1 ]; then
        if [ -f "$dest" ]; then
            record_change "update $dest from $shared"
        else
            record_change "write $dest from $shared"
        fi
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        rm -f "$tmp"
        return 0
    fi
    mv "$tmp" "$dest"
    [ "$LINKS_ONLY" -eq 1 ] || echo "Generated $dest"
}

# Print what changes from settings file $1 to $2, one line per JSON path.
summarize_settings_diff() {
    python3 -I - "$1" "$2" <<'EOF'
import json
import sys

LIMIT = 20


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def short(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def walk(old, new, path, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in new:
            sub = f"{path}.{key}" if path else key
            if key not in old:
                out.append(f"+ {sub}: {short(new[key])}")
            else:
                walk(old[key], new[key], sub, out)
        for key in old:
            if key not in new:
                out.append(f"- {path}.{key}" if path else f"- {key}")
    elif isinstance(old, list) and isinstance(new, list):
        out.extend(f"+ {path}[]: {short(item)}" for item in new if item not in old)
        out.extend(f"- {path}[]: {short(item)}" for item in old if item not in new)
        if not out and old != new:
            out.append(f"~ {path}: reordered")
    elif old != new:
        out.append(f"~ {path}: {short(old)} -> {short(new)}")


old, new = load(sys.argv[1]), load(sys.argv[2])
lines = []
if old is None:
    lines.append("~ (current file is not valid JSON)")
else:
    walk(old, new, "", lines)
for line in lines[:LIMIT]:
    print(f"    {line}")
if len(lines) > LIMIT:
    print(f"    ... and {len(lines) - LIMIT} more")
EOF
}

# --links-only part of generate_claude_settings.
#   $1 = merged settings, $2 = ~/.claude/settings.json, $3 = snapshot,
#   $4 = configs/claude/settings.local.json
# Rewrites $2 only when it still holds what install.sh last generated, so
# changes made by `claude plugin enable` or /config are never overwritten.
update_claude_settings_safely() {
    new="$1"
    dest="$2"
    snapshot="$3"
    local_file="$4"

    if [ -L "$dest" ]; then
        record_change "replace symlink $dest with generated settings"
        run_change rm -f "$dest"
        run_change cp -p "$new" "$dest"
        run_change cp -p "$new" "$snapshot"
    elif [ -e "$dest" ] && [ ! -f "$dest" ]; then
        record_skip "$dest is not a regular file; left it in place"
    elif [ ! -e "$dest" ]; then
        record_change "write $dest"
        run_change cp -p "$new" "$dest"
        run_change cp -p "$new" "$snapshot"
    elif cmp -s "$dest" "$new"; then
        if [ ! -f "$snapshot" ] || ! cmp -s "$dest" "$snapshot"; then
            record_change "update snapshot $snapshot"
            run_change cp -p "$new" "$snapshot"
        fi
    elif [ -f "$snapshot" ] && cmp -s "$dest" "$snapshot"; then
        record_change "rewrite $dest:
$(summarize_settings_diff "$dest" "$new")"
        run_change cp -p "$new" "$dest"
        run_change cp -p "$new" "$snapshot"
    else
        record_skip "$dest was changed outside install.sh (e.g. by claude plugin enable); not overwriting it. Move the change into configs/claude/settings.local.json, or run ./install.sh to back it up and regenerate. Regenerating would change:
$(summarize_settings_diff "$dest" "$new")"
    fi

    old_local="$HOME/.claude/settings.local.json"
    if [ -L "$old_local" ] && [ "$(readlink "$old_local")" = "$local_file" ]; then
        record_change "remove $old_local"
        run_change rm -f "$old_local"
    fi
}

# Link the agent assets in configs/agent into a single tool home.
#   $1 = destination home dir (e.g. ~/.claude)
#   $2 = filename for the instructions file in that home (e.g. CLAUDE.md)
link_agent_assets() {
    home_dir="$1"
    instructions_name="$2"
    script_dir=$(cd "$(dirname "$0")" && pwd)
    agent_dir="$script_dir/configs/agent"

    ensure_dir "$home_dir"

    # Instructions file: one source, linked under the name the tool reads.
    if [ -f "$agent_dir/AGENTS.md" ]; then
        place_link "$agent_dir/AGENTS.md" "$home_dir/$instructions_name"
    fi

    # Skills: link each skill dir individually so unmanaged skills
    # (skills installed by other means) survive.
    if [ -d "$agent_dir/skills" ]; then
        ensure_dir "$home_dir/skills"
        resolved_target=$(cd "$home_dir/skills" 2>/dev/null && pwd -P)
        resolved_source=$(cd "$agent_dir/skills" 2>/dev/null && pwd -P)
        if [ "$resolved_target" != "$resolved_source" ]; then
            for skill_dir in "$agent_dir/skills"/*; do
                if [ -d "$skill_dir" ]; then
                    place_link "$skill_dir" "$home_dir/skills/$(basename "$skill_dir")"
                fi
            done
        else
            [ "$LINKS_ONLY" -eq 1 ] || echo "$home_dir/skills already points to source directory, skipping symlinks."
        fi
    fi

    # Hooks: shell scripts (tmux window title, etc.).
    # NOTE: this only places the scripts. Wiring them up is done in
    # configs/claude/settings.json.
    if [ -d "$agent_dir/hooks" ]; then
        ensure_dir "$home_dir/hooks"
        resolved_target=$(cd "$home_dir/hooks" 2>/dev/null && pwd -P)
        resolved_source=$(cd "$agent_dir/hooks" 2>/dev/null && pwd -P)
        if [ "$resolved_target" != "$resolved_source" ]; then
            for hook in "$agent_dir/hooks"/*; do
                if [ -f "$hook" ]; then
                    filename=$(basename "$hook")
                    place_link "$hook" "$home_dir/hooks/$filename"
                    make_executable "$home_dir/hooks/$filename" "$hook"
                fi
            done
        else
            [ "$LINKS_ONLY" -eq 1 ] || echo "$home_dir/hooks already points to source directory, skipping symlinks."
        fi
    fi
}

create_shared_agent_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    agent_dir="$script_dir/configs/agent"

    if [ ! -d "$agent_dir" ]; then
        return 0
    fi

    link_agent_assets "$HOME/.claude" "CLAUDE.md"
}

# dotfiles no longer manages Codex. Remove the symlinks it used to place under
# ~/.codex (AGENTS.md, skills, hooks, prompts, rules) and leave everything
# Codex owns untouched. Idempotent.
cleanup_codex_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    codex_home="$HOME/.codex"

    [ -d "$codex_home" ] || return 0

    for link in "$codex_home/AGENTS.md" \
        "$codex_home/skills"/* "$codex_home/hooks"/* \
        "$codex_home/prompts"/* "$codex_home/rules"/*; do
        [ -L "$link" ] || continue
        case "$(readlink "$link")" in
            "$script_dir"/configs/*)
                echo "Removing codex symlink: $link"
                rm -f "$link"
                ;;
        esac
    done

    for dir in "$codex_home/hooks" "$codex_home/prompts" "$codex_home/rules"; do
        rmdir "$dir" 2>/dev/null && echo "Removed empty dir: $dir"
    done
    return 0
}

create_hammerspoon_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    hammerspoon_config_dir="$script_dir/configs/hammerspoon"

    if [ ! -d "$hammerspoon_config_dir" ]; then
        return 0
    fi

    # Symlink the entire hammerspoon directory to ~/.hammerspoon
    place_link "$hammerspoon_config_dir" "$HOME/.hammerspoon"
}

for arg in "$@"; do
    case "$arg" in
        --links-only) LINKS_ONLY=1 ;;
        --dry-run) LINKS_ONLY=1; DRY_RUN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

refuse_worktree_checkout

if [ "$LINKS_ONLY" -eq 1 ]; then
    create_symlinks
    create_claude_symlinks
    generate_claude_settings || record_skip "could not generate ~/.claude/settings.json (see the message above)"
    generate_git_ignore || record_skip "could not generate configs/git/ignore"
    create_shared_agent_symlinks
    create_hammerspoon_symlinks
    print_link_summary
    exit 0
fi

# Phase 1 実行
echo "=== Phase 1: Setting up Homebrew, fish, and symlinks ==="
install_homebrew
install_fish
set_fish_as_default_shell
create_symlinks
create_claude_symlinks
generate_claude_settings
generate_git_ignore
create_shared_agent_symlinks
cleanup_codex_symlinks
create_hammerspoon_symlinks

# =============================================================================
# Phase 2: fish で実行（mise, apps, macOS設定）
# =============================================================================

echo ""
echo "=== Phase 2: Running remaining setup in fish ==="

fish -c '
    function install_udev_gothic_nf
        if brew list --cask font-udev-gothic-nf >/dev/null 2>&1
            echo "UDEV Gothic NF is already installed."
        else
            echo "Installing UDEV Gothic NF..."
            brew install --cask font-udev-gothic-nf
        end
    end

    function install_mise
        if not type -q mise
            echo "Installing mise..."
            curl https://mise.run | sh
        else
            echo "mise is already installed."
        end

        # Install tools managed by mise
        echo "Installing tools via mise..."
        mise install
    end

    function install_textlint
        # Packages for the agent textlint hook (configs/agent/hooks/textlint-markdown.sh)
        echo "Installing textlint packages..."
        # npm ci --prefix misreads the lockfile, so run it inside the directory.
        pushd ~/.config/textlint
        mise exec -- npm ci
        popd
    end

    function configure_macos
        echo "Configuring macOS keyboard settings..."
        defaults write -g KeyRepeat -int 1
        defaults write -g InitialKeyRepeat -int 11
        echo "macOS keyboard settings configured. (Restart may be required)"
    end

    function is_app_installed
        set -l cask_name $argv[1]
        set -l app_name $argv[2]

        # Check if installed via brew cask
        if brew list --cask "$cask_name" >/dev/null 2>&1
            return 0
        end

        # Check if app exists in /Applications
        if test -d "/Applications/$app_name.app"
            return 0
        end

        return 1
    end

    function install_apps
        if not type -q brew
            echo "Homebrew is not installed. Please install Homebrew first."
            return 1
        end

        # CLI tools
        if not type -q nvim
            echo "Installing neovim..."
            brew install neovim
        else
            echo "neovim is already installed."
        end

        if not type -q op
            echo "Installing 1password-cli..."
            brew install 1password-cli
        else
            echo "1password-cli is already installed."
        end

        if not type -q tmuxinator
            echo "Installing tmuxinator..."
            brew install tmuxinator
        else
            echo "tmuxinator is already installed."
        end

        if not type -q claude
            echo "Installing claude-code..."
            brew install --cask claude-code
        else
            echo "claude-code is already installed."
        end

        if not type -q gh
            echo "Installing gh..."
            brew install gh
        else
            echo "gh is already installed."
        end

        if not type -q lazygit
            echo "Installing lazygit..."
            brew install lazygit
        else
            echo "lazygit is already installed."
        end

        # Cask apps
        set -l cask_apps "slack:Slack" "ghostty:Ghostty" "raycast:Raycast" "figma:Figma" "karabiner-elements:Karabiner-Elements" "meetingbar:MeetingBar" "obsidian:Obsidian" "1password:1Password" "hammerspoon:Hammerspoon"

        for entry in $cask_apps
            set -l parts (string split ":" $entry)
            set -l cask_name $parts[1]
            set -l app_name $parts[2]

            if not is_app_installed "$cask_name" "$app_name"
                echo "Installing $cask_name..."
                brew install --cask "$cask_name"
            else
                echo "$cask_name is already installed."
            end
        end
    end

    # Phase 2 実行
    install_udev_gothic_nf
    install_mise
    install_textlint
    install_apps
    configure_macos

    echo ""
    echo "=== Setup complete! ==="
'
