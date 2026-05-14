function rgopen
    set -l description "Search non-empty lines with rg/grep and open in editor"

    # Set default grep command
    set -l grep_cmd "grep --recursive --line-number --invert-match --regexp '^\\s*\$' * 2>/dev/null"

    # Use rg if available
    if command -v rg > /dev/null
        set grep_cmd "rg --line-number --no-heading --invert-match '^\\s*\$' 2>/dev/null"
    end

    # Execute grep/rg and pipe to fzf
    set -l result (eval $grep_cmd | fzf --exit-0)

    if test -z "$result"
        return
    end

    # Parse file and line number from result
    set -l file (echo $result | cut -d: -f1)
    set -l line (echo $result | cut -d: -f2)

    # Check if file and line are valid
    if test -z "$file" -o -z "$line"
        return
    end

    emacs +$line $file
end
