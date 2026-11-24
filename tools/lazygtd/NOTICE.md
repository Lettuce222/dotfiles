# Notice

lazygtd copies no source code from lazygit. It follows lazygit's design (boxes on the left, the
selected item on the right, the keys on the bottom line, a subprocess run with the screen
suspended) and builds on these libraries, each under its own license, kept in the module cache
and not vendored here:

- [jesseduffield/gocui](https://github.com/jesseduffield/gocui): the fork of gocui that lazygit
  uses. BSD 3-Clause, Copyright (c) 2014 The gocui Authors.
- [charmbracelet/glamour](https://github.com/charmbracelet/glamour): Markdown for the terminal,
  with its TokyoNight style. MIT, Copyright (c) Charmbracelet, Inc.
- [fsnotify/fsnotify](https://github.com/fsnotify/fsnotify): file change events. BSD 3-Clause.
- [gdamore/tcell](https://github.com/gdamore/tcell) (through gocui): Apache 2.0.

lazygit itself: [jesseduffield/lazygit](https://github.com/jesseduffield/lazygit), MIT,
Copyright (c) 2018 Jesse Duffield. If code is copied from it later, keep its copyright and
permission notice with that code.

The lists, the labels and the keys follow the browser desk of the Hub (local) Orca plugin in
Lettuce222/dotfiles (configs/orca/plugins/hub/desk/), MIT.
