function fish_prompt
	set -g __fish_git_prompt_showcolorhints yes
	set -g __fish_git_prompt_showdirtystate yes
	set -g __fish_git_prompt_showuntrackedfiles yes
	set -g __fish_git_prompt_showupstream yes
	set_color $fish_color_cwd
	echo -n (prompt_pwd)
	set_color normal
	echo -n (fish_git_prompt)
	echo -n ' $ '
end
