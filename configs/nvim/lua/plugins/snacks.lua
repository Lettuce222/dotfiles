return {
  "folke/snacks.nvim",
  opts = {
    picker = {
      sources = {
        files = {
          hidden = true,
          ignored = true,
        },
      },
    },
  },
  init = function()
    -- Make non-matching text in picker more readable (brighter grey)
    vim.api.nvim_create_autocmd("ColorScheme", {
      callback = function()
        vim.api.nvim_set_hl(0, "SnacksPickerDir", { fg = "#8a8a8a" })
        vim.api.nvim_set_hl(0, "SnacksPickerFile", { fg = "#b0b0b0" })
      end,
    })
    -- Apply immediately for the current colorscheme
    vim.api.nvim_set_hl(0, "SnacksPickerDir", { fg = "#8a8a8a" })
    vim.api.nvim_set_hl(0, "SnacksPickerFile", { fg = "#b0b0b0" })
  end,
}
