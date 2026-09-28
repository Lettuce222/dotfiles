function claude --wraps claude --description 'claude with per-machine ~/.claude/settings.local.json'
  # Claude Code does not read ~/.claude/settings.local.json as user settings, so pass it explicitly.
  set --local local_settings ~/.claude/settings.local.json
  if test -f $local_settings
    command claude --settings $local_settings $argv
  else
    command claude $argv
  end
end
