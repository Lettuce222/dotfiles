#!/usr/bin/env fish

# GitHub PR URL を受け取り、worktree を作成して tmux window を開く

if test (count $argv) -gt 0
    set -l pr_url $argv[1]
else
    read -P "PR URL: " pr_url
end

if test -z "$pr_url"
    echo "No URL provided"
    sleep 1
    exit 1
end

set -l match (string match -r '^https?://github\.com/([^/]+)/([^/]+)/pull/([0-9]+)' -- $pr_url)
if test (count $match) -lt 4
    echo "Invalid GitHub PR URL: $pr_url"
    sleep 2
    exit 1
end

set -l owner $match[2]
set -l repo $match[3]
set -l pr_num $match[4]

set -l repo_path (ghq list --full-path | grep -E "/$owner/$repo\$" | head -1)
if test -z "$repo_path"
    echo "Cloning github.com/$owner/$repo..."
    ghq get "github.com/$owner/$repo"
    or begin
        echo "Failed to clone repo"
        sleep 2
        exit 1
    end
    set repo_path (ghq list --full-path | grep -E "/$owner/$repo\$" | head -1)
end

if test -z "$repo_path"
    echo "Repo not found locally"
    sleep 2
    exit 1
end

set -l branch (gh pr view $pr_num -R "$owner/$repo" --json headRefName -q .headRefName)
if test -z "$branch"
    echo "Failed to fetch PR #$pr_num info"
    sleep 2
    exit 1
end

set -l parent (dirname $repo_path)
set -l worktree_dir "$parent/$repo.worktrees/$branch"

if not test -d $worktree_dir
    mkdir -p "$parent/$repo.worktrees"
    git -C $repo_path worktree add --detach $worktree_dir
    or begin
        echo "Failed to create worktree"
        sleep 2
        exit 1
    end
    pushd $worktree_dir >/dev/null
    gh pr checkout $pr_num -R "$owner/$repo"
    set -l checkout_status $status
    popd >/dev/null
    if test $checkout_status -ne 0
        echo "gh pr checkout failed"
        sleep 2
        exit 1
    end
end

set -l win_name "$repo#$pr_num"
if tmux list-windows -F '#{window_name}' 2>/dev/null | grep -qx "$win_name"
    tmux select-window -t $win_name
else
    tmux new-window -n $win_name -c $worktree_dir
end
