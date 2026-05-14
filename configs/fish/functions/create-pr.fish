function create-pr --description 'Create a pull request for the current branch in the current repository using goose'
  set repository (gh repo view --jq .nameWithOwner --json nameWithOwner)
  set default_branch (git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')
  set current_branch (git rev-parse --abbrev-ref HEAD)
  set commit_logs (git log "$default_branch..$current_branch" --pretty=format:"- %s (%an, %ad)" --date=short | jq -Rs '@json')
  set git_diff (git diff "$default_branch..$current_branch" | head -1000 | jq -Rs '@json')

  # Extract issue number from current branch name (assuming format: {issue_number}-branch-name)
  set issue_number (echo $current_branch | grep -oE '^[0-9]+' | head -n 1)

  if [ "$issue_number" != "" ]
    set ticket_url "https://github.com/$repository/issues/$issue_number"

    # Get milestone from GitHub issue
    set milestone (gh issue view $issue_number --repo $repository --jq '.milestone.title' --json milestone 2>/dev/null)
    if test -z "$milestone" -o "$milestone" = "null"
      set milestone ""
    end
  else
    set ticket_url ""
    set milestone ""
  end

  git push origin HEAD
  goose run --recipe $HOME/.goose/recipes/create-pr.yaml \
      --params "commit_logs=$commit_logs" \
      --params "current_branch=$current_branch" \
      --params "default_branch=$default_branch" \
      --params "git_diff=$git_diff" \
      --params "pr_template=$PR_TEMPLATE" \
      --params "repository=$repository" \
      --params "ticket_url=$ticket_url"
end
