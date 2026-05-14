if status is-interactive
  ~/.local/bin/mise activate fish | source
  direnv hook fish | source
  zoxide init fish | source

  if test (uname) = "Darwin"
    eval (/opt/homebrew/bin/brew shellenv)
  end
end

set -p fish_function_path ~/.config/fish/functions/local
