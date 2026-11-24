# lazygtd

The hub's desk (hub v2's GTD board) in a terminal, after lazygit: the lists on the left, the
selected item on the right, the keys on the bottom line. A trial beside the browser desk of the
Hub (local) Orca plugin.

Every read and write goes through `gtd.py` (`json`, `move`, `done`, `add`, `say`, `read`, with
`--by user` and, where gtd.py checks it, `--hash`), so people and agents write the same way and
share one history. lazygtd watches `items/` and `.log/` and reads again when anyone changes them.
A conflict (gtd.py's exit 3) is read again first, then told.

## Run

```sh
go build -o lazygtd .
./lazygtd                       # the real items: gtd.py's GTD_HOME (~/hub/gtd)
scripts/demo-home.sh /tmp/lazygtd-demo && ./lazygtd --gtd-home /tmp/lazygtd-demo   # sample items
```

- `s` and `d` open the file in Orca's editor (`orca file open --focus`) when lazygtd runs in an
  Orca terminal (`ORCA_PANE_KEY` is set), else in nvim. `LAZYGTD_EDITOR=nvim` or `=orca` decides.
- `LAZYGTD_GTD_PY` (or `--gtd-py`) points at another gtd.py.

## Keys

`?` in the screen lists them. As on the browser desk: `h`/`l`・`Tab` boxes, `j`/`k` rows,
`q w e r t y u` the lists and `o` the talk with the orchestrator, `a` add, `s` editor, `d`
deliverables, `f` move, `x` done, `Enter` reply (`Ctrl+J` new line), `/` filter, `g` + initial.
`Ctrl+D`/`Ctrl+U` scroll the detail, `Ctrl+R` reads again, `Ctrl+C` quits.

Not here yet: the orchestrator's questions, approvals and permission dialogs, the workers'
questions (`⇧Q`〜`⇧R` on the desk), the migration of the old cases (`i`), and `v` (a worker's
terminal).

## Test

```sh
go test ./...   # the screen tests run the real gtd.py on a folder of sample items
```
