local wezterm = require 'wezterm'
local act = wezterm.action
local config = wezterm.config_builder()
local is_windows = wezterm.target_triple:find('windows', 1, true) ~= nil
local is_mac = wezterm.target_triple:find('apple-darwin', 1, true) ~= nil

config.color_scheme = 'Tokyo Night Storm'
config.colors = { split = '#414868' }
config.font = wezterm.font_with_fallback { 'UDEV Gothic NF', 'JetBrains Mono' }
config.font_size = 14.0
config.line_height = 1.10 -- Approximate Ghostty's extra 2 pixels across DPI settings.
config.default_cursor_style = 'SteadyBar'
config.scrollback_lines = 100000
config.hide_tab_bar_if_only_one_tab = true
config.window_close_confirmation = 'NeverPrompt'

config.keys = {
  { key = '\\', mods = 'CTRL', action = act.SplitHorizontal { domain = 'CurrentPaneDomain' } },
  { key = '-', mods = 'CTRL', action = act.SplitVertical { domain = 'CurrentPaneDomain' } },
}

if is_mac then
  config.send_composed_key_when_left_alt_is_pressed = false
  config.send_composed_key_when_right_alt_is_pressed = false
end

if is_windows then
  config.font_dirs = { wezterm.home_dir .. '/.local/share/wezterm/fonts' }
  local domains = wezterm.default_wsl_domains()
  for _, domain in ipairs(domains) do
    if domain.distribution == 'Ubuntu' then
      config.default_domain = domain.name
      domain.default_prog = {
        '/bin/bash', '-lc',
        'if command -v fish >/dev/null 2>&1; then exec fish; else exec bash -i; fi',
      }
      break
    end
  end
  config.wsl_domains = domains
end

-- Normal text selection and tmux mouse handling are preserved. Only an
-- intentional modifier-click may open a URL; reject file/other URI schemes.
local link_mod = is_mac and 'SUPER' or 'CTRL'
local left_up = { Up = { streak = 1, button = 'Left' } }
config.mouse_bindings = {
  { event = left_up, mods = 'NONE', action = act.CompleteSelection 'ClipboardAndPrimarySelection' },
  { event = left_up, mods = 'SHIFT', action = act.CompleteSelection 'ClipboardAndPrimarySelection' },
  { event = { Down = { streak = 1, button = 'Left' } }, mods = link_mod, action = act.Nop },
  { event = left_up, mods = link_mod, action = act.OpenLinkAtMouseCursor },
}
wezterm.on('open-uri', function(_, _, uri)
  return uri:lower():match('^https?://') ~= nil
end)

return config
