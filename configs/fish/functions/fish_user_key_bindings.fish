function fish_user_key_bindings
  fzf --fish | source
  bind \cg edit_command_buffer
end
