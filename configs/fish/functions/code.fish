function code --description 'alias code ghq list -p | fzf | code'
  if [ "$argv[1]" != "" ]
    echo $argv[1]
    command code $argv
    return
  end

  set --local repo $(ghq list -p | fzf)
  if [ "$repo" != "" ]
    echo $repo
    command code $repo
  end
end
