function ls --wraps eza --description 'ls with eza'
    command eza --icons auto --time-style relative -F always --hyperlink -h $argv
end
