#!/usr/bin/env fish

# hub から呼ばれ、worktree を用意して worker の Claude Code を tmux window で起動する
# Usage: spawn.fish [--resume] <repo> <task> <prompt-file>
#   repo: owner/repo, repo 名, またはリポジトリ内の絶対パス
#   task: kebab-case のタスク名。ブランチは agent/<task>、worktree は <repo>.worktrees/agent/<task> になる
#   prompt-file: worker への指示書
#   --resume: 既にある worktree やブランチ agent/<task> で作業を再開する

set -l script_dir (path resolve -- (status dirname))
set -l hub_name (test -n "$AGENT_HUB_NAME"; and echo $AGENT_HUB_NAME; or echo hub)
set -l state_dir (test -n "$XDG_STATE_HOME"; and echo $XDG_STATE_HOME; or echo $HOME/.local/state)/agent-hub

function die
    echo "spawn: $argv" >&2
    exit 1
end

# worktree やサブディレクトリのパスを、元のリポジトリのトップに揃える
function repo_root --argument-names dir
    set -l common_dir (git -C $dir rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    or return 1
    test (basename $common_dir) = .git; or return 1
    dirname $common_dir
end

argparse resume -- $argv; or die "usage: spawn.fish [--resume] <repo> <task> <prompt-file>"
test (count $argv) -eq 3; or die "usage: spawn.fish [--resume] <repo> <task> <prompt-file>"
set -l repo_spec $argv[1]
set -l task $argv[2]
set -l prompt_file $argv[3]

set -q TMUX; or die "tmux の中で実行してください"
string match -qr '^[a-z0-9][a-z0-9-]*$' -- $task; or die "task は kebab-case にしてください: $task"
test -f $prompt_file; or die "指示書がありません: $prompt_file"

# リポジトリを解決する（無ければ owner/repo 指定のときだけ clone する）
set -l repo_path
if string match -q '/*' -- $repo_spec
    set repo_path (repo_root $repo_spec)
    or die "git リポジトリ（bare 以外）ではありません: $repo_spec"
else
    # ghq list には worktree も出るので、元のリポジトリのトップそのものだけを候補にする
    set -l pattern '/'(string escape --style=regex -- $repo_spec)'$'
    set -l matches (ghq list --full-path | string match -ri -- ".*$pattern")
    if test (count $matches) -eq 0; and string match -q '*/*' -- $repo_spec
        ghq get $repo_spec >&2; or die "clone に失敗しました: $repo_spec"
        set matches (ghq list --full-path | string match -ri -- ".*$pattern")
    end
    set -l roots
    for match in $matches
        set -l root (repo_root $match); and test (path resolve -- $root) = (path resolve -- $match); and set -a roots $root
    end
    test (count $roots) -eq 1; or die "リポジトリを 1 つに絞れません: $repo_spec ($roots)"
    set repo_path $roots[1]
end

set -l repo (basename $repo_path)
set -l branch agent/$task
# tm-pr.fish と同じく <repo>.worktrees/<ブランチ名> に置く。prefix + p で worker の PR を開くとこの worktree が開く
set -l worktree_dir (dirname $repo_path)/$repo.worktrees/$branch
# task には . を使えないので、repo と task の組み合わせごとに一意になる
set -l worker_name $repo.$task
set -l initial_prompt $state_dir/$worker_name.md

test (path resolve -- $prompt_file) != (path resolve -- $initial_prompt)
or die "記録ファイルは指示書として渡せません。新しい指示書を書いてください"

# 別 owner の同名リポジトリの worker と名前が重なるなら止める
if test -f $initial_prompt; and not grep -qxF "作業場所: $worktree_dir" $initial_prompt
    die "$worker_name は別の作業場所で使われています。task 名を変えてください"
end

# 同じ worker が動いていたら止める（セッション名が重なると報告が届かない）
for line in (tmux list-windows -a -F '#{window_id} #{@agent-hub-worker}')
    set -l fields (string split ' ' -- $line)
    if test "$fields[2]" = $worker_name
        die "$worker_name は既に window $fields[1] で動いています"
    end
end

# worktree を用意する。既存のブランチや worktree は --resume のときだけ使う
if test -d $worktree_dir
    set -q _flag_resume; or die "worktree が既にあります: $worktree_dir（続きなら --resume）"
    set -l checked_out (git -C $worktree_dir symbolic-ref --quiet --short HEAD)
    test "$checked_out" = $branch; or die "$worktree_dir は $branch ではなく '$checked_out' を checkout しています"
    git -C $repo_path fetch --prune --quiet origin >&2
    or echo "spawn: warning: origin を fetch できませんでした" >&2
else
    git -C $repo_path fetch --prune --quiet origin >&2
    or echo "spawn: warning: origin を fetch できませんでした。手元の古い状態から作業を始めます" >&2
    if git -C $repo_path show-ref --quiet --verify refs/heads/$branch
        set -q _flag_resume; or die "ブランチ $branch が既にあります（続きなら --resume）"
        git -C $repo_path worktree add $worktree_dir $branch >&2
    else if git -C $repo_path show-ref --quiet --verify refs/remotes/origin/$branch
        set -q _flag_resume; or die "ブランチ origin/$branch が既にあります（続きなら --resume）"
        git -C $repo_path worktree add --track -b $branch $worktree_dir origin/$branch >&2
    else
        set -q _flag_resume; and die "再開できる worktree もブランチ $branch もありません"
        # origin/HEAD が未設定、または既定ブランチの改名で古いままなら取り直す
        set -l base (git -C $repo_path symbolic-ref --quiet --short refs/remotes/origin/HEAD)
        if test -z "$base"; or not git -C $repo_path rev-parse --verify --quiet $base >/dev/null
            git -C $repo_path remote set-head origin --auto >/dev/null 2>&1
            set base (git -C $repo_path symbolic-ref --quiet --short refs/remotes/origin/HEAD)
        end
        test -n "$base"; or die "origin の既定ブランチが分かりません: $repo_path"
        git -C $repo_path worktree add --no-track -b $branch $worktree_dir $base >&2
    end
    or die "worktree を作れませんでした: $worktree_dir"
end

# 再開のときは、レビューで足されたコミットなど origin 側の進みを取り込む
if set -q _flag_resume; and git -C $repo_path show-ref --quiet --verify refs/remotes/origin/$branch
    git -C $worktree_dir merge --ff-only --quiet origin/$branch >&2
    or echo "spawn: warning: origin/$branch を fast-forward で取り込めませんでした。worker に統合を任せます" >&2
end

# hub の名前を添えた指示書を残す（worker の初期プロンプトと記録を兼ねる）
# 再開のときは元の指示を残したまま追記し、worker には全体を渡す
# 記録には議事録由来の文脈が入りうるので、自分だけが読めるようにする
mkdir -p $state_dir; and chmod 700 $state_dir; or die "記録用のディレクトリを作れません: $state_dir"
if set -q _flag_resume
    begin
        # 記録が失われていても、再開の案内は必ず渡す
        if not test -f $initial_prompt
            echo "あなたのセッション名: $worker_name"
            echo "作業場所: $worktree_dir"
            echo "作業ブランチ: $branch"
        end
        echo
        echo "## 再開（"(date '+%Y-%m-%d %H:%M')"）"
        echo
        echo "窓口（hub）のセッション名: $hub_name（この記録で最後に書かれた窓口のセッション名を使う）"
        echo
        echo "ここから以前の作業の再開です。上の元の指示と、作業ブランチの既存のコミットを確かめてください。`git fetch` して origin/$branch に自分の手元に無いコミットがあれば、force push せずに取り込んでから作業してください。`gh pr list --head $branch --state open` で open の PR があれば、新しく作らずそれを更新してください。"
        echo
        cat $prompt_file
    end >>$initial_prompt
else
    begin
        echo "窓口（hub）のセッション名: $hub_name"
        echo "あなたのセッション名: $worker_name"
        echo "作業場所: $worktree_dir"
        echo "作業ブランチ: $branch"
        echo
        cat $prompt_file
    end >$initial_prompt
end
or die "指示書を書き込めません: $initial_prompt"
chmod 600 $initial_prompt
# 記録に取り込んだので、/tmp に置かれた元の指示書は残さない（ほかの場所のファイルは消さない）
if string match -q -r '^(/private)?/tmp/agent-hub-[^/]*$' -- (path resolve -- $prompt_file)
    rm -f -- $prompt_file
end

# AGENT_HUB_WORKER と AGENT_HUB_BRANCH は worker の印で、hook（external-post-guard.py）も読む。
# worker から送ってよい外部への書き込みを、作業ブランチの draft PR に絞るため
set -l window_id (tmux new-window -d -P -F '#{window_id}' -n "$repo:$task" -c $worktree_dir \
    -e AGENT_HUB_WORKER=$worker_name \
    -e AGENT_HUB_BRANCH=$branch \
    -e AGENT_HUB_RULES=$script_dir/worker-rules.md \
    -e AGENT_HUB_PROMPT=$initial_prompt \
    -e AGENT_HUB_ENV=$script_dir/agent-env.fish \
    'fish -c \'source $AGENT_HUB_ENV; claude -n $AGENT_HUB_WORKER --permission-mode auto --append-system-prompt-file $AGENT_HUB_RULES (string collect < $AGENT_HUB_PROMPT)\'')
or die "tmux window を作れませんでした"

# 一覧（pick.fish）で worker の window を見分けるための印
tmux set-option -w -t $window_id @agent-hub-worker $worker_name
or die "worker の window $window_id がすぐに閉じました。claude の起動に失敗しています"

echo "started: $worker_name window=$window_id worktree=$worktree_dir branch=$branch record=$initial_prompt"
