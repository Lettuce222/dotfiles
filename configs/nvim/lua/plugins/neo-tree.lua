return {
  "nvim-neo-tree/neo-tree.nvim",
  opts = {
    filesystem = {
      filtered_items = {
        visible = true, -- 隠しファイルを常に表示
        hide_dotfiles = false, -- ドットファイルを非表示にしない
        hide_gitignored = false, -- gitignoreされたファイルも表示
      },
    },
  },
}
