# lazygtd

GTD items in a terminal, laid out and keyed as lazygit: five numbered side panels with tabs on the
left, the selected item on the right with a reply box under it, the options line at the bottom,
popups in the middle. Colors are TokyoNight Storm.

Every read and write goes through `gtd.py` (`json`, `add`, `move`, `done`, `set`, `say`, `read`,
`step`, with `--by user` and, where gtd.py checks it, `--hash`), so people and agents write the
same way and share one history. lazygtd watches `items/` and `.log/` and reads again when anyone
changes them. A conflict (gtd.py's exit 3) is read again first, then told on the bottom line.

## Run

```sh
go build -o lazygtd .
./lazygtd                       # the items of gtd.py's GTD_HOME
scripts/demo-home.sh /tmp/lazygtd-demo && ./lazygtd --gtd-home /tmp/lazygtd-demo   # a week of made-up items
```

- `e` and `o` open the item or a deliverable in Orca's editor (`orca file open --focus`) when
  lazygtd runs in an Orca terminal (`ORCA_PANE_KEY` is set), else in `$EDITOR` (nvim when unset).
  `LAZYGTD_EDITOR=nvim` or `=orca` decides.
- `LAZYGTD_GTD_PY` (or `--gtd-py`) points at another gtd.py.

## Panels

| Panel | Tabs (`[` `]`) |
| --- | --- |
| `[1]` | あなたの番 - 窓口 |
| `[2]` | inbox |
| `[3]` | 次の行動 - プロジェクト (`<enter>` goes into a project's steps) |
| `[4]` | 連絡待ち |
| `[5]` | いつか - 資料 - 完了 |
| `[0]` | 詳細 (the body as Markdown, the talk with the orchestrator in order), and the reply box under it |

## Keys: lazygit's, and what lazygtd does with them

`?` or `x` lists them and runs the one picked. The table is `internal/desk/keys.go`.

| Key | lazygit | lazygtd |
| --- | --- | --- |
| `1`〜`5` | go to a side panel | go to a panel |
| `0` | go to the main view | go to the detail |
| `h` `l` `←` `→` `<tab>` `<backtab>` | previous / next panel | previous / next panel |
| `[` `]` | previous / next tab | previous / next tab |
| `j` `k` `↑` `↓` | down / up | down / up (round from one end to the other) |
| `,` `.` `<` `>` `<home>` `<end>` | page, top, bottom | page, top, bottom |
| `J` `K` `<pgdown>` `<pgup>` `<c-d>` `<c-u>` | scroll the main view | scroll the detail |
| `<enter>` | go into | a project: its steps. Else: the reply box |
| `<esc>` | back | back (out of the steps, the detail, a filter) |
| `<space>` | stage, check out | mark done (in 完了: back to 次の行動) |
| `c` | commit | new item: the first line is the title, the body after `<c-j>`. In inbox, 次の行動, プロジェクト, いつか, 資料: that list; elsewhere inbox. In a project's steps: a new step |
| `r` | reword a commit | the reply box |
| `m` | rebase menu | move menu (inbox, 次の行動, step, 連絡待ち, いつか, 資料, カレンダーに入れる) |
| `a` | stage all | hand to the orchestrator: an agent's item in 次の行動 with no worker (after a confirmation) |
| `e` | edit a file | open the item in the editor |
| `o` | open a file | open a deliverable |
| `<c-j>` `<c-k>` | move a commit down / up | move a step down / up |
| `<c-o>` | copy to the clipboard | copy the id and title |
| `/` | filter / search | filter the list (input on the bottom line) |
| `R` | refresh | read again |
| `+` `_` | next / previous screen mode | normal, half, full |
| `?` `x` | keybindings menu | keys menu |
| `q` `<c-c>` | quit | quit |

In every input, `<enter>` sends, `<c-j>` starts a new line where there can be several (and does
nothing elsewhere), `<esc>` leaves. An empty input sends nothing.

## Test

```sh
go test ./...   # the screen tests run the real gtd.py on a copy of the demo folder
```
