-- Formatter configuration using conform.nvim
-- Uses tools installed via mise (not Mason)

---@type LazySpec
return {
  "stevearc/conform.nvim",
  event = { "BufWritePre" },
  cmd = { "ConformInfo" },
  opts = {
    formatters_by_ft = {
      -- Lua: stylua (uses .stylua.toml in nvim config)
      lua = { "stylua" },

      -- Shell: shfmt
      sh = { "shfmt" },
      bash = { "shfmt" },
      zsh = { "shfmt" },

      -- Fish: fish_indent (built-in)
      fish = { "fish_indent" },

      -- TOML: taplo
      toml = { "taplo" },

      -- YAML: prettier via npx
      yaml = { "prettier" },
      yml = { "prettier" },

      -- JSON: prettier via npx
      json = { "prettier" },
      jsonc = { "prettier" },

      -- Markdown: prettier via npx
      markdown = { "prettier" },
    },
    -- Format on save
    format_on_save = {
      timeout_ms = 3000,
      lsp_format = "fallback",
    },
    -- Use npx for prettier
    formatters = {
      prettier = {
        command = "npx",
        args = { "prettier", "--stdin-filepath", "$FILENAME" },
      },
    },
  },
}
