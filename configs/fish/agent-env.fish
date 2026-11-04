# orchestrator が窓口と claude agents を起動する前に source する。
# 非対話の fish では conf.d/00-init.fish の mise / direnv が動かないので、
# 起動ディレクトリ（worktree など）の環境を明示的に取り込む。

set -l mise_bin (command -s mise; or echo ~/.local/bin/mise)
if test -x $mise_bin
    $mise_bin env -s fish 2>/dev/null | source
end

# direnv は allow 済みの .envrc だけを読み込む
if command -q direnv
    direnv export fish 2>/dev/null | source
end

# 上の mise env は mise の gh を PATH の先頭に置く。gh のラッパー（ghtkn で
# トークンを渡すもの）を入れたマシンでは、それを最優先にする。
# 無いマシンでは何もしない。
set -l gh_wrapper_dir ~/.local/share/gh-ghtkn/bin
if test -x $gh_wrapper_dir/gh
    fish_add_path -gpm $gh_wrapper_dir
end
