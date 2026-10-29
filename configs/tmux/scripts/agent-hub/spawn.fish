#!/usr/bin/env fish

# hub から呼ばれ、worktree を用意して worker の Claude Code を tmux window で起動する
# Usage: spawn.fish <repo> <task> <prompt-file>
#   repo: owner/repo, repo 名, または絶対パス
#   task: kebab-case のタスク名（ブランチ名・worktree 名にもなる）
#   prompt-file: worker への指示書

set -l script_dir (status dirname)
set -l hub_name (set -q AGENT_HUB_NAME; and echo $AGENT_HUB_NAME; or echo hub)
set -l state_dir (set -q XDG_STATE_HOME; and echo $XDG_STATE_HOME; or echo $HOME/.local/state)/agent-hub

function die
    echo "spawn: $argv" >&2
    exit 1
end

test (count $argv) -eq 3; or die "usage: spawn.fish <repo> <task> <prompt-file>"
set -l repo_spec $argv[1]
set -l task $argv[2]
set -l prompt_file $argv[3]

set -q TMUX; or die "tmux の中で実行してください"
string match -qr '^[a-z0-9][a-z0-9-]*$' -- $task; or die "task は kebab-case にしてください: $task"
test -f $prompt_file; or die "指示書がありません: $prompt_file"

# リポジトリを解決する（無ければ owner/repo 指定のときだけ clone する）
set -l repo_path
if string match -q '/*' -- $repo_spec
    set repo_path $repo_spec
else
    set -l matches (ghq list --full-path | string match -r ".*/$repo_spec\$")
    if test (count $matches) -eq 0; and string match -q '*/*' -- $repo_spec
        ghq get $repo_spec >&2; or die "clone に失敗しました: $repo_spec"
        set matches (ghq list --full-path | string match -r ".*/$repo_spec\$")
    end
    test (count $matches) -eq 1; or die "リポジトリを 1 つに絞れません: $repo_spec ($matches)"
    set repo_path $matches[1]
end
git -C $repo_path rev-parse --git-dir >/dev/null 2>&1; or die "git リポジトリではありません: $repo_path"

set -l repo (basename $repo_path)
set -l worktree_dir (dirname $repo_path)/$repo.worktrees/$task

# worktree を用意する（既にあれば使い回す）
if not test -d $worktree_dir
    git -C $repo_path fetch --quiet origin >&2
    if git -C $repo_path show-ref --quiet --verify refs/heads/$task
        git -C $repo_path worktree add $worktree_dir $task >&2
    else if git -C $repo_path show-ref --quiet --verify refs/remotes/origin/$task
        git -C $repo_path worktree add --track -b $task $worktree_dir origin/$task >&2
    else
        set -l base (git -C $repo_path symbolic-ref --quiet --short refs/remotes/origin/HEAD)
        test -n "$base"; or set base origin/main
        git -C $repo_path worktree add --no-track -b $task $worktree_dir $base >&2
    end
    or die "worktree を作れませんでした: $worktree_dir"
end

# hub の名前を添えた指示書を残す（worker の初期プロンプトと記録を兼ねる）
set -l worker_name $repo-$task
mkdir -p $state_dir
set -l initial_prompt $state_dir/$worker_name.md
begin
    echo "窓口（hub）のセッション名: $hub_name"
    echo "あなたのセッション名: $worker_name"
    echo "作業場所: $worktree_dir"
    echo
    cat $prompt_file
end >$initial_prompt

set -l window_id (tmux new-window -d -P -F '#{window_id}' -n "$repo:$task" -c $worktree_dir \
    -e AGENT_HUB_WORKER=$worker_name \
    -e AGENT_HUB_RULES=$script_dir/worker-rules.md \
    -e AGENT_HUB_PROMPT=$initial_prompt \
    'fish -c \'claude -n $AGENT_HUB_WORKER --permission-mode auto --append-system-prompt-file $AGENT_HUB_RULES (string collect < $AGENT_HUB_PROMPT)\'')
or die "tmux window を作れませんでした"

# 一覧（pick.fish）で worker の window を見分けるための印
tmux set-option -w -t $window_id @agent-hub-worker $worker_name

echo "started: $worker_name ($worktree_dir)"
