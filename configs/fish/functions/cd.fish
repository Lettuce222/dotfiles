function cd --description 'alias cd ghq list -p | fzf | cd'
  if [ "$argv[1]" != "" ]
    echo $argv[1]
    builtin cd $argv
    return
  end

  set --local repo $(ghq list -p | fzf)
  if [ "$repo" != "" ]
    echo $repo
    builtin cd $repo
  end
end
