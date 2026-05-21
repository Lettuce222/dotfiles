-- AstroUI provides the basis for configuring the AstroNvim User Interface
-- Configuration documentation can be found with `:h astroui`
-- NOTE: We highly recommend setting up the Lua Language Server (`:LspInstall lua_ls`)
--       as this provides autocomplete and documentation while editing

-- 薄い文字色は背景 #1f2335 / #24283b に対して WCAG 4.5:1 以上を確保するよう持ち上げる。
-- dim   = #7e89ac (vs #1f2335 ≈ 4.5:1, vs #24283b ≈ 4.2:1) — 弱め強調
-- soft  = #9aa5ce (vs #24283b ≈ 6.0:1) — 通常の補助テキスト
-- bright = #c0caf5 — 前景強調
local transparent = {
  Normal = { bg = "NONE" },
  NormalNC = { bg = "NONE" },
  NormalFloat = { bg = "NONE" },
  FloatBorder = { bg = "NONE" },
  FloatTitle = { bg = "NONE" },
  SignColumn = { bg = "NONE" },
  LineNr = { bg = "NONE", fg = "#7e89ac" },
  CursorLineNr = { bg = "NONE", fg = "#c0caf5", bold = true },
  Comment = { fg = "#9aa5ce", italic = true },
  NonText = { fg = "#7e89ac" },
  Whitespace = { fg = "#7e89ac" },
  Conceal = { fg = "#9aa5ce" },
  EndOfBuffer = { bg = "NONE" },
  Folded = { bg = "NONE", fg = "#9aa5ce" },
  MsgArea = { bg = "NONE" },
  WinSeparator = { bg = "NONE", fg = "#7e89ac" },
  VertSplit = { bg = "NONE", fg = "#7e89ac" },
  NeoTreeNormal = { bg = "NONE" },
  NeoTreeNormalNC = { bg = "NONE" },
  NeoTreeEndOfBuffer = { bg = "NONE" },
  NeoTreeWinSeparator = { bg = "NONE" },
  NeoTreeFloatBorder = { bg = "NONE" },
  NeoTreeFloatTitle = { bg = "NONE" },
  SnacksNormal = { bg = "NONE" },
  SnacksNormalNC = { bg = "NONE" },
  SnacksDashboardNormal = { bg = "NONE" },
  SnacksPicker = { bg = "NONE" },
  SnacksPickerBorder = { bg = "NONE" },
  SnacksPickerTitle = { bg = "NONE" },
  SnacksPickerPreview = { bg = "NONE" },
  SnacksPickerInput = { bg = "NONE" },
  SnacksPickerList = { bg = "NONE" },
  SnacksPickerBox = { bg = "NONE" },
  TelescopeNormal = { bg = "NONE" },
  TelescopeBorder = { bg = "NONE" },
  TelescopePromptNormal = { bg = "NONE" },
  TelescopePromptBorder = { bg = "NONE" },
  TelescopeResultsNormal = { bg = "NONE" },
  TelescopePreviewNormal = { bg = "NONE" },
}

---@type LazySpec
return {
  "AstroNvim/astroui",
  ---@type AstroUIOpts
  opts = {
    -- change colorscheme
    colorscheme = "tokyonight-storm",
    -- AstroUI allows you to easily modify highlight groups easily for any and all colorschemes
    highlights = {
      init = transparent,
      astrodark = transparent,
      ["tokyonight-storm"] = transparent,
    },
    -- Icons can be configured throughout the interface
    icons = {
      -- configure the loading of the lsp in the status line
      LSPLoading1 = "⠋",
      LSPLoading2 = "⠙",
      LSPLoading3 = "⠹",
      LSPLoading4 = "⠸",
      LSPLoading5 = "⠼",
      LSPLoading6 = "⠴",
      LSPLoading7 = "⠦",
      LSPLoading8 = "⠧",
      LSPLoading9 = "⠇",
      LSPLoading10 = "⠏",
    },
  },
}
