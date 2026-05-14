# General abbreviations
abbr b bundle
abbr g git
abbr m tmuxinator
abbr c code
abbr y yarn
abbr lg lazygit
abbr cl claude
abbr n nvim

abbr eg 'env | grep'

# Git abbreviations
abbr gps git push
abbr gpl git pull
abbr ga git add .
abbr gc git commit
abbr gg git grep
abbr gr git restore .
abbr gpso git push --set-upstream origin HEAD
abbr gpc gh pr checkout

# Ruby/Rails abbreviations
abbr spec bundle exec rspec
abbr rails bundle exec rails
abbr migrate bundle ex rails db:migrate
abbr rbcp 'bundle exec rubocop --enable-pending-cops -A $(git diff develop --name-only | grep .rb | grep -v schema.rb)'
