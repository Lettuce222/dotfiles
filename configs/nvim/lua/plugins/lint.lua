-- Linter configuration using nvim-lint
-- Uses tools installed via mise (not Mason)

---@type LazySpec
return {
  "mfussenegger/nvim-lint",
  event = { "BufReadPre", "BufNewFile" },
  config = function()
    local lint = require "lint"

    lint.linters_by_ft = {
      -- Shell: shellcheck
      sh = { "shellcheck" },
      bash = { "shellcheck" },

      -- Fish: fish built-in linter
      fish = { "fish" },
    }

    -- Auto-lint on events
    vim.api.nvim_create_autocmd({ "BufWritePost", "BufReadPost", "InsertLeave" }, {
      callback = function()
        lint.try_lint()
      end,
    })
  end,
}
