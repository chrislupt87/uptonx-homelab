local wezterm = require 'wezterm'
local config = wezterm.config_builder()
local act = wezterm.action

-- Theme
config.color_scheme = 'Catppuccin Mocha'

-- Font
config.font = wezterm.font('JetBrains Mono')
config.font_size = 14.0

-- Window
config.window_decorations = 'INTEGRATED_BUTTONS|RESIZE'
config.window_close_confirmation = 'NeverPrompt'
config.window_background_opacity = 0.92
config.window_padding = {
  left = 8,
  right = 8,
  top = 8,
  bottom = 8,
}

-- Tab bar
config.use_fancy_tab_bar = false
config.hide_tab_bar_if_only_one_tab = false
config.tab_bar_at_bottom = false

-- Inactive panes slightly dimmed
config.inactive_pane_hsb = {
  saturation = 0.9,
  brightness = 0.75,
}

-- Scrollback
config.scrollback_lines = 50000
config.enable_scroll_bar = true

-- Cursor
config.default_cursor_style = 'BlinkingBar'
config.cursor_blink_rate = 500

-- Keys
config.keys = {
  -- Copy / Paste
  { key = 'c', mods = 'CTRL|SHIFT', action = act.CopyTo('Clipboard') },
  { key = 'v', mods = 'CTRL|SHIFT', action = act.PasteFrom('Clipboard') },
  { key = 'Insert', mods = 'SHIFT', action = act.PasteFrom('Clipboard') },

  -- Splits
  { key = '|', mods = 'CTRL|SHIFT', action = act.SplitHorizontal({ domain = 'CurrentPaneDomain' }) },
  { key = '_', mods = 'CTRL|SHIFT', action = act.SplitVertical({ domain = 'CurrentPaneDomain' }) },

  -- Navigate panes
  { key = 'LeftArrow', mods = 'CTRL|SHIFT', action = act.ActivatePaneDirection('Left') },
  { key = 'RightArrow', mods = 'CTRL|SHIFT', action = act.ActivatePaneDirection('Right') },
  { key = 'UpArrow', mods = 'CTRL|SHIFT', action = act.ActivatePaneDirection('Up') },
  { key = 'DownArrow', mods = 'CTRL|SHIFT', action = act.ActivatePaneDirection('Down') },

  -- Resize panes
  { key = 'LeftArrow', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ 'Left', 5 }) },
  { key = 'RightArrow', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ 'Right', 5 }) },
  { key = 'UpArrow', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ 'Up', 5 }) },
  { key = 'DownArrow', mods = 'CTRL|ALT', action = act.AdjustPaneSize({ 'Down', 5 }) },

  -- Close pane
  { key = 'w', mods = 'CTRL|SHIFT', action = act.CloseCurrentPane({ confirm = false }) },

  -- Tabs
  { key = 't', mods = 'CTRL|SHIFT', action = act.SpawnTab('CurrentPaneDomain') },
  { key = 'Tab', mods = 'CTRL', action = act.ActivateTabRelative(1) },
  { key = 'Tab', mods = 'CTRL|SHIFT', action = act.ActivateTabRelative(-1) },

  -- Font size
  { key = '=', mods = 'CTRL', action = act.IncreaseFontSize },
  { key = '-', mods = 'CTRL', action = act.DecreaseFontSize },
  { key = '0', mods = 'CTRL', action = act.ResetFontSize },

  -- Search
  { key = 'f', mods = 'CTRL|SHIFT', action = act.Search({ CaseInSensitiveString = '' }) },

  -- Scroll
  { key = 'PageUp', mods = 'SHIFT', action = act.ScrollByPage(-1) },
  { key = 'PageDown', mods = 'SHIFT', action = act.ScrollByPage(1) },
}

-- Tab number shortcuts (Ctrl+1 through Ctrl+9)
for i = 1, 9 do
  table.insert(config.keys, {
    key = tostring(i),
    mods = 'CTRL',
    action = act.ActivateTab(i - 1),
  })
end

-- Dynamic window title icons
local function icon_for_title(title)
  local t = (title or ''):lower()

  if t:find('frigate') or t:find('camera') then
    return '󰈈'
  elseif t:find('home') or t:find('ha') then
    return '󰟐'
  elseif t:find('ssh') or t:find('server') then
    return '󰣀'
  elseif t:find('code') or t:find('nvim') or t:find('vim') then
    return '󰨞'
  elseif t:find('docker') or t:find('compose') then
    return ''
  elseif t:find('log') then
    return '󰌱'
  elseif t:find('backup') then
    return '󰁯'
  elseif t:find('danger') or t:find('prod') then
    return ''
  else
    return ''
  end
end

wezterm.on('format-window-title', function(tab, pane, tabs, panes, cfg)
  local title = pane:get_title()
  if title == nil or title == '' then
    title = 'WezTerm'
  end

  local icon = icon_for_title(title)
  return icon .. ' ' .. title
end)

return config
