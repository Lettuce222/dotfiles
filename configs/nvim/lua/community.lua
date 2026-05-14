-- AstroCommunity: import any community modules here
-- We import this file in `lazy_setup.lua` before the `plugins/` folder.
-- This guarantees that the specs are processed before any user plugins.

---@type LazySpec
return {
  "AstroNvim/astrocommunity",
  -- Language packs
  { import = "astrocommunity.pack.lua" },
  { import = "astrocommunity.pack.json" },
  { import = "astrocommunity.pack.bash" },
  { import = "astrocommunity.pack.fish" },
  { import = "astrocommunity.pack.toml" },
  { import = "astrocommunity.pack.yaml" },
  -- Editing support
  { import = "astrocommunity.editing-support.auto-save-nvim" },
  { import = "astrocommunity.quickfix.quicker-nvim" },
  -- Git
  { import = "astrocommunity.git.octo-nvim" },
  { import = "astrocommunity.git.diffview-nvim" },
  -- Markdown
  { import = "astrocommunity.markdown-and-latex.render-markdown-nvim" },
  -- import/override with your plugins folder
}
