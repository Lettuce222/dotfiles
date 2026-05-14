function plan-issue --description 'plan issue'
  set repository (gh repo view --jq .nameWithOwner --json nameWithOwner)
  set current_branch (git rev-parse --abbrev-ref HEAD)

  # Extract issue number from current branch name (assuming format: {issue_number}-branch-name)
  set issue_number (echo $current_branch | grep -oE '^[0-9]+' | head -n 1)


  if [ "$argv[1]" != "" ]
    set appendix $argv[1]
  else
    set appendix ""
  end

  git push origin HEAD
  goose run --recipe $HOME/.goose/recipes/github-issue-to-plan.yaml \
      --params "issue_number=$issue_number" \
      --params "repository=$repository" \
      --params "appendix=$appendix"
end
