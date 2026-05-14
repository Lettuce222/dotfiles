# .config/fish/functions/killport.fish
function killport -d "Kill process on a given port"
  set -l port $argv[1]
  if test -z "$port"
    echo "Usage: killport <port>"
    return 1
  end
  
  echo "Killing process on port $port..."
  set -l pids (lsof -t -i:$port)
  
  if test -n "$pids"
    echo $pids | xargs kill -9
    echo "Done."
  else
    echo "No process found on port $port."
  end
end