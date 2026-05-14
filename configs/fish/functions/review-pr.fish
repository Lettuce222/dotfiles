function review-pr -d "List review-requested PRs and checkout selected one"
    set pr_number (gh pr list --search "is:open review-requested:@me" --json number,title,headRefName,author,body --template '{{range .}}{{.number}}|{{.title}}|{{.headRefName}}|{{.author.login}}{{"\n"}}{{end}}' | fzf \
        --preview 'set pr_num (echo {} | cut -d"|" -f1); gh pr view $pr_num --json title,author,body,headRefName,baseRefName,createdAt,updatedAt --template "
Title: {{.title}}
Author: {{.author.login}}
Branch: {{.headRefName}} → {{.baseRefName}}
Created: {{.createdAt | timeago}}
Updated: {{.updatedAt | timeago}}

Description:
{{if .body}}{{.body}}{{else}}No description provided{{end}}"' \
        --preview-window=right:60% \
        | sed -r 's/^([0-9]+).*/\1/')

    if test -n "$pr_number"
        gh pr checkout $pr_number
    end
end
