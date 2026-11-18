# orchestrator が窓口と案件の一覧を起動する前に source する。
# 非対話の fish では conf.d/00-init.fish の mise / direnv が動かないので、
# 起動ディレクトリ（worktree など）の環境を明示的に取り込む。

fish_add_path --path "$HOME/.local/bin"

set -l mise_bin (command -s mise; or echo ~/.local/bin/mise)
if test -x $mise_bin
    $mise_bin env -s fish 2>/dev/null | source
end

# direnv は allow 済みの .envrc だけを読み込む
if command -q direnv
    direnv export fish 2>/dev/null | source
end

# 明示されたローカルの gh ラッパーは、mise の gh より先に探す。
if test -n "$AGENT_GH_WRAPPER_DIR"; and test -x "$AGENT_GH_WRAPPER_DIR/gh"
    fish_add_path -gpm "$AGENT_GH_WRAPPER_DIR"
end
