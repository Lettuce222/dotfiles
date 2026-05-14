#!/bin/sh

# =============================================================================
# Phase 1: sh で実行（Homebrew, fish, symlinks）
# =============================================================================

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

    mkdir -p "$HOME/.config"

    for dir in "$script_dir/configs"/*; do
        if [ -d "$dir" ]; then
            dirname=$(basename "$dir")
            # Skip claude and hammerspoon directories (handled separately)
            if [ "$dirname" = "claude" ] || [ "$dirname" = "hammerspoon" ]; then
                continue
            fi
            source_path="$script_dir/configs/$dirname"
            target_path="$HOME/.config/$dirname"

            ln -snfv "$source_path" "$target_path"
        fi
    done
}

create_claude_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    claude_config_dir="$script_dir/configs/claude"

    if [ ! -d "$claude_config_dir" ]; then
        return 0
    fi

    mkdir -p "$HOME/.claude"
    mkdir -p "$HOME/.claude/hooks"

    # Create symlinks for individual files (not the whole directory)
    for file in "$claude_config_dir"/*; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            ln -snfv "$file" "$HOME/.claude/$filename"
            # Make shell scripts executable
            if [ "${filename##*.}" = "sh" ]; then
                chmod +x "$HOME/.claude/$filename"
            fi
        fi
    done

    # Create symlinks for hooks directory
    if [ -d "$claude_config_dir/hooks" ]; then
        mkdir -p "$HOME/.claude/hooks"
        # Skip if target resolves to the same directory (e.g., managed by home-manager)
        resolved_target=$(cd "$HOME/.claude/hooks" 2>/dev/null && pwd -P)
        resolved_source=$(cd "$claude_config_dir/hooks" 2>/dev/null && pwd -P)
        if [ "$resolved_target" != "$resolved_source" ]; then
            for file in "$claude_config_dir/hooks"/*; do
                if [ -f "$file" ]; then
                    filename=$(basename "$file")
                    ln -snfv "$file" "$HOME/.claude/hooks/$filename"
                    chmod +x "$HOME/.claude/hooks/$filename"
                fi
            done
        else
            echo "~/.claude/hooks already points to source directory, skipping symlinks."
        fi
    fi

    # Create symlinks for commands directory (slash commands)
    if [ -d "$claude_config_dir/commands" ]; then
        mkdir -p "$HOME/.claude/commands"
        # Skip if target resolves to the same directory (e.g., managed by home-manager)
        resolved_target=$(cd "$HOME/.claude/commands" 2>/dev/null && pwd -P)
        resolved_source=$(cd "$claude_config_dir/commands" 2>/dev/null && pwd -P)
        if [ "$resolved_target" != "$resolved_source" ]; then
            for file in "$claude_config_dir/commands"/*; do
                if [ -f "$file" ]; then
                    filename=$(basename "$file")
                    ln -snfv "$file" "$HOME/.claude/commands/$filename"
                fi
            done
        else
            echo "~/.claude/commands already points to source directory, skipping symlinks."
        fi
    fi

    # Create symlinks for skills directory (each skill is a directory)
    if [ -d "$claude_config_dir/skills" ]; then
        mkdir -p "$HOME/.claude/skills"
        resolved_target=$(cd "$HOME/.claude/skills" 2>/dev/null && pwd -P)
        resolved_source=$(cd "$claude_config_dir/skills" 2>/dev/null && pwd -P)
        if [ "$resolved_target" != "$resolved_source" ]; then
            for skill_dir in "$claude_config_dir/skills"/*; do
                if [ -d "$skill_dir" ]; then
                    skill_name=$(basename "$skill_dir")
                    ln -snfv "$skill_dir" "$HOME/.claude/skills/$skill_name"
                fi
            done
        else
            echo "~/.claude/skills already points to source directory, skipping symlinks."
        fi
    fi
}

create_hammerspoon_symlinks() {
    script_dir=$(cd "$(dirname "$0")" && pwd)
    hammerspoon_config_dir="$script_dir/configs/hammerspoon"

    if [ ! -d "$hammerspoon_config_dir" ]; then
        return 0
    fi

    # Symlink the entire hammerspoon directory to ~/.hammerspoon
    ln -snfv "$hammerspoon_config_dir" "$HOME/.hammerspoon"
}

# Phase 1 実行
echo "=== Phase 1: Setting up Homebrew, fish, and symlinks ==="
install_homebrew
install_fish
set_fish_as_default_shell
create_symlinks
create_claude_symlinks
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
    install_apps
    configure_macos

    echo ""
    echo "=== Setup complete! ==="
'
