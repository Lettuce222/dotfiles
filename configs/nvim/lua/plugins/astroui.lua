-- AstroUI provides the basis for configuring the AstroNvim User Interface
-- Configuration documentation can be found with `:h astroui`
-- NOTE: We highly recommend setting up the Lua Language Server (`:LspInstall lua_ls`)
--       as this provides autocomplete and documentation while editing

local transparent = {
  Normal = { bg = "NONE" },
  NormalNC = { bg = "NONE" },
  NormalFloat = { bg = "NONE" },
  FloatBorder = { bg = "NONE" },
  FloatTitle = { bg = "NONE" },
  SignColumn = { bg = "NONE" },
  LineNr = { bg = "NONE" },
  CursorLineNr = { bg = "NONE" },
  EndOfBuffer = { bg = "NONE" },
  Folded = { bg = "NONE" },
  MsgArea = { bg = "NONE" },
  WinSeparator = { bg = "NONE" },
  VertSplit = { bg = "NONE" },
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
    colorscheme = "astrodark",
    -- AstroUI allows you to easily modify highlight groups easily for any and all colorschemes
    highlights = {
      init = transparent,
      astrodark = transparent,
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
