-- AstroCore provides a central place to modify mappings, vim options, autocommands, and more!
-- Configuration documentation can be found with `:h astrocore`
-- NOTE: We highly recommend setting up the Lua Language Server (`:LspInstall lua_ls`)
--       as this provides autocomplete and documentation while editing

---@type LazySpec
return {
  "AstroNvim/astrocore",
  ---@type AstroCoreOpts
  opts = {
    -- Configure core features of AstroNvim
    features = {
      large_buf = { size = 1024 * 256, lines = 10000 }, -- set global limits for large files for disabling features like treesitter
      autopairs = true, -- enable autopairs at start
      cmp = true, -- enable completion at start
      diagnostics = { virtual_text = true, virtual_lines = false }, -- diagnostic settings on startup
      highlighturl = true, -- highlight URLs at start
      notifications = true, -- enable notifications at start
    },
    -- Diagnostics configuration (for vim.diagnostics.config({...})) when diagnostics are on
    diagnostics = {
      virtual_text = true,
      underline = true,
    },
    -- passed to `vim.filetype.add`
    filetypes = {
      -- see `:h vim.filetype.add` for usage
      extension = {
        foo = "fooscript",
      },
      filename = {
        [".foorc"] = "fooscript",
      },
      pattern = {
        [".*/etc/foo/.*"] = "fooscript",
      },
    },
    -- vim options can be configured here
    options = {
      opt = { -- vim.opt.<key>
        relativenumber = true, -- sets vim.opt.relativenumber
        number = true, -- sets vim.opt.number
        spell = false, -- sets vim.opt.spell
        signcolumn = "yes", -- sets vim.opt.signcolumn to yes
        wrap = false, -- sets vim.opt.wrap
      },
      g = { -- vim.g.<key>
        -- configure global vim variables (vim.g)
        -- NOTE: `mapleader` and `maplocalleader` must be set in the AstroNvim opts or before `lazy.setup`
        -- This can be found in the `lua/lazy_setup.lua` file
      },
    },
    -- Mappings can be configured through AstroCore as well.
    -- NOTE: keycodes follow the casing in the vimdocs. For example, `<Leader>` must be capitalized
    mappings = {
      -- first key is the mode
      n = {
        -- second key is the lefthand side of the map

        -- navigate buffer tabs
        ["]b"] = { function() require("astrocore.buffer").nav(vim.v.count1) end, desc = "Next buffer" },
        ["[b"] = { function() require("astrocore.buffer").nav(-vim.v.count1) end, desc = "Previous buffer" },

        -- Find files (always include hidden, regardless of git repo presence)
        ["<Leader>ff"] = {
          function() require("snacks").picker.files { hidden = true } end,
          desc = "Find files",
        },

        -- mappings seen under group name "Buffer"
        ["<Leader>bd"] = {
          function()
            require("astroui.status.heirline").buffer_picker(
              function(bufnr) require("astrocore.buffer").close(bufnr) end
            )
          end,
          desc = "Close buffer from tabline",
        },

        -- tables with just a `desc` key will be registered with which-key if it's installed
        -- this is useful for naming menus
        -- ["<Leader>b"] = { desc = "Buffers" },

        -- Copy relative path from project root
        ["<Leader>yr"] = {
          function()
            local filepath = vim.fn.expand "%:p"
            local root = vim.fn.getcwd()
            local relative = vim.fn.fnamemodify(filepath, ":~:.")

            -- If file is not under current directory, try to find git root
            if vim.startswith(relative, "/") or vim.startswith(relative, "..") then
              local git_root = vim.fn.systemlist("git rev-parse --show-toplevel")[1]
              if vim.v.shell_error == 0 and git_root then
                relative = vim.fn.fnamemodify(filepath, ":s?" .. git_root .. "/??")
              end
            end

            vim.fn.setreg("+", relative)
            vim.notify("Copied relative path: " .. relative, vim.log.levels.INFO)
          end,
          desc = "Copy relative path from project root",
        },

        -- Copy GitHub permanent link
        ["<Leader>yg"] = {
          function()
            local filepath = vim.fn.expand "%:p"
            local line = vim.fn.line "."

            -- Get git root
            local git_root = vim.fn.systemlist("git rev-parse --show-toplevel")[1]
            if vim.v.shell_error ~= 0 or not git_root then
              vim.notify("Not in a git repository", vim.log.levels.ERROR)
              return
            end

            -- Get relative path from git root
            local relative = vim.fn.fnamemodify(filepath, ":s?" .. git_root .. "/??")

            -- Get current commit hash
            local commit = vim.fn.systemlist("git rev-parse HEAD")[1]
            if vim.v.shell_error ~= 0 or not commit then
              vim.notify("Failed to get commit hash", vim.log.levels.ERROR)
              return
            end

            -- Get remote URL
            local remote_url = vim.fn.systemlist("git config --get remote.origin.url")[1]
            if vim.v.shell_error ~= 0 or not remote_url then
              vim.notify("Failed to get remote URL", vim.log.levels.ERROR)
              return
            end

            -- Convert SSH URL to HTTPS
            remote_url = remote_url:gsub("git@github%.com:", "https://github.com/")
            remote_url = remote_url:gsub("%.git$", "")

            -- Build GitHub permalink
            local permalink = string.format("%s/blob/%s/%s#L%d", remote_url, commit, relative, line)

            vim.fn.setreg("+", permalink)
            vim.notify("Copied GitHub permalink: " .. permalink, vim.log.levels.INFO)
          end,
          desc = "Copy GitHub permanent link",
        },

        -- RSpec: Run current file
        ["<Leader>tt"] = {
          function()
            local filepath = vim.fn.expand "%:p"
            if not filepath:match "_spec%.rb$" then
              vim.notify("Not a RSpec file", vim.log.levels.WARN)
              return
            end
            local cmd = "bundle exec rspec " .. vim.fn.shellescape(filepath)
            vim.cmd("split | terminal " .. cmd)
            vim.cmd "startinsert"
          end,
          desc = "Run RSpec for current file",
        },

        -- RSpec: Run current line
        ["<Leader>tl"] = {
          function()
            local filepath = vim.fn.expand "%:p"
            local line = vim.fn.line "."
            if not filepath:match "_spec%.rb$" then
              vim.notify("Not a RSpec file", vim.log.levels.WARN)
              return
            end
            local cmd = string.format("bundle exec rspec %s:%d", vim.fn.shellescape(filepath), line)
            vim.cmd("split | terminal " .. cmd)
            vim.cmd "startinsert"
          end,
          desc = "Run RSpec for current line",
        },

        -- setting a mapping to false will disable it
        -- ["<C-S>"] = false,
      },
      -- Insert mode: Emacs keybinds
      i = {
        ["<C-a>"] = { "<Home>", desc = "Move to beginning of line" },
        ["<C-e>"] = { "<End>", desc = "Move to end of line" },
        ["<C-f>"] = { "<Right>", desc = "Move forward" },
        ["<C-b>"] = { "<Left>", desc = "Move backward" },
        ["<C-d>"] = { "<Del>", desc = "Delete character" },
        ["<C-h>"] = { "<BS>", desc = "Delete character backward" },
      },
      -- Command-line mode: Emacs keybinds (for search, etc.)
      c = {
        ["<C-a>"] = { "<Home>", desc = "Move to beginning of line" },
        ["<C-e>"] = { "<End>", desc = "Move to end of line" },
        ["<C-f>"] = { "<Right>", desc = "Move forward" },
        ["<C-b>"] = { "<Left>", desc = "Move backward" },
        ["<C-d>"] = { "<Del>", desc = "Delete character" },
        ["<C-h>"] = { "<BS>", desc = "Delete character backward" },
      },
      -- Terminal mode: Emacs keybinds
      t = {
        ["<C-a>"] = { "<Home>", desc = "Move to beginning of line" },
        ["<C-e>"] = { "<End>", desc = "Move to end of line" },
        ["<C-f>"] = { "<Right>", desc = "Move forward" },
        ["<C-b>"] = { "<Left>", desc = "Move backward" },
        ["<C-d>"] = { "<Del>", desc = "Delete character" },
        ["<C-h>"] = { "<BS>", desc = "Delete character backward" },
      },
    },
  },
}
