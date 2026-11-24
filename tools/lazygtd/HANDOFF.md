# lazygtd の引き継ぎ

lazygtd を続けて作るコーディングエージェント向けのメモ。前の会話を知らなくても、このページと `README.md`・`NOTICE.md`・コードだけで続けられるように書く。

## lazygtd とは

hub v2 のデスク（GTD のボード）を、lazygit に寄せたターミナルの画面にしたもの。Go と jesseduffield/gocui（lazygit が使う gocui の fork）で作る。左に「あなたの番・窓口・inbox・次の行動・プロジェクト・連絡待ち・いつか・資料」の 8 つの箱、右に選んだ項目の詳細（本文は glamour の Markdown、色は TokyoNight Storm）、最下行にその場のキーを出す。

もとはブラウザのデスク（Hub (local) の Orca plugin、`configs/orca/plugins/hub/desk/`）と比べるための試しとして、別のリポジトリで作った。2026 年 11 月 24 日に、その main（`89227f6`）を 1 つのコミットにまとめて dotfiles に取り込んだ。これからは dotfiles の中で磨く。

### データの決まり

- 正は `gtd.py`（`configs/agent/skills/agents-orchestrator/scripts/gtd.py`）。項目は `${GTD_HOME:-~/hub/gtd}/items/<id>.md`（1 項目 1 ファイル、frontmatter 付きの Markdown）で、成果物は `items/<id>/` の下に置く。
- 人もエージェントも同じ形で書く。lazygtd も、ブラウザのデスクも、窓口や worker も、書き込みはすべて `gtd.py` のコマンドを通す。lazygtd は `--by user` を付け、エージェントは `--by agent:<名前>` を付ける。ファイルを直接書き換えない。
- `move`・`done` のように `gtd.py` が読んだときの hash を確かめるコマンドには、`--hash` を付ける。ほかの人が先に直していると、`gtd.py` は終了コード 3 で断る。lazygtd は読み直してから、最下行で知らせる。
- 書き込みはすべて `.log/changes.jsonl` に 1 行ずつ残る。人の変更は `gtd.py record` がまとめてコミットする（Hub (local) のデスクが 1 分ごとに動かす。lazygtd は動かさない）。
- lazygtd が読むのは `gtd.py json` の出力だけ。形が変わったら `internal/gtd/model.go` を合わせる。

### Hub (local)・ブラウザのデスクとの関係

- ブラウザのデスクと lazygtd は、同じ `gtd.py` の上の 2 つの画面。どちらから書いても同じ記録になり、相手の画面にもすぐ出る（lazygtd は fsnotify で `items/` と `.log/` の変化を受け、0.2 秒まとめて読み直す）。
- 窓口への知らせは Hub (local) が出す。Hub は `.log/changes.jsonl` の新しい行から、ユーザーの返事（`say`）と inbox への追加（`add`）を読んで窓口に 1 行で知らせる（`configs/orca/plugins/hub/src/change-log.mjs`）。lazygtd からの書き込みも対象になる。ただし Orca と Hub (local) が動いているときだけ。
- 次の行動に入った `actor: agent` の項目の知らせも、Hub がファイルの変化から出すので、lazygtd から移しても出る。
- 窓口の問い・承認の問い・許可の確認と、worker の問いへの答えは、まだブラウザのデスクとパネルにしか無い。答えを worker に渡す処理と承認の記録が Hub の worker の中にあるため。

## 作りの地図

| 場所 | 中身 |
| --- | --- |
| `main.go` | 引数（`--gtd-home`、`--gtd-py`、`--version`）を読んで画面を始める |
| `internal/gtd/` | `gtd.py` を動かす。`json`・`move`・`done`・`add`・`say`・`read`。値は `--title=…` の形で渡し、フラグに見える文も文のまま渡す。終了コード 3 をぶつかりとして見分ける。`model.go` は `gtd.py json` の形 |
| `internal/desk/` | 画面の無い状態。箱・行・選択・絞り込み（`desk.go`）と、キーから操作を決める関数とキーの一覧（`keys.go`）。テストしやすいよう gocui に頼らない |
| `internal/render/` | 行と詳細の文。本文は glamour で描き、幅ごとに覚えておく |
| `internal/ui/` | gocui の画面（`ui.go`）、キーの配線（`keys.go`）、左の列の箱の高さ（`layout.go`）。書き込みは画面のループの外で動かし、同じ項目への二重の書き込みを止める |
| `internal/open/` | `s`・`d` で開く。Orca のターミナルの中（`ORCA_PANE_KEY` がある）なら `orca file open <path> --focus`、外なら nvim（画面を明け渡し、閉じたら戻る）。`LAZYGTD_EDITOR=nvim` か `=orca` で決められる。開けるのは `items/<id>.md` と `items/<id>/` の下だけ（リンクの先も確かめる） |
| `internal/watch/` | fsnotify で `items/`・`items/<id>/`・`.log/` の変化を受ける |
| `scripts/demo-home.sh` | `gtd.py` でデモの項目を作る。本物の hub を触らずに試せる |

## 作り方・試し方・テスト

go は mise で入る（`configs/mise/config.local.toml`）。コマンドは `tools/lazygtd` で実行する。

```sh
# 作る。引数なしの install.sh も同じものを ~/.local/bin/lazygtd に作る
go build -o ~/.local/bin/lazygtd .

# デモの項目で試す（フォルダはまだ無い場所を指す）
scripts/demo-home.sh /tmp/lazygtd-demo
lazygtd --gtd-home /tmp/lazygtd-demo

# 本物の項目（gtd.py の既定の ~/hub/gtd）
lazygtd

# テスト
go test ./...
```

- 実行ファイルはコミットしない（`.gitignore` の `/lazygtd`）。`./install.sh --links-only` はビルドしないので、コードを変えたら上の `go build` か引数なしの `./install.sh` で作り直す。
- 画面のテスト（`internal/ui/ui_test.go`）は、gocui の headless と `Snapshot()` で、本物の `gtd.py` をデモのフォルダに対して動かす。表示、Markdown、`f` で移す（記録に `by: user` が残る）、`x` で完了、返事、`a` で追加、エージェントの書き込みが画面に出ること、ぶつかりの読み直し、絞り込み、`?` の一覧を確かめる。
- テストが使う `gtd.py` は `gtd.DefaultScript()`（`LAZYGTD_GTD_PY`、無ければ `~/.claude/skills/agents-orchestrator/scripts/gtd.py`）。配置済みの `gtd.py` なので、dotfiles の worktree で `gtd.py` を直したときは `LAZYGTD_GTD_PY=<worktree>/configs/agent/skills/agents-orchestrator/scripts/gtd.py go test ./...` で流す。見つからなければ画面のテストは skip になる。
- `s`・`d` の `orca file open --focus` は、Orca の中で人が試したことがまだ無い。

## いまできていること

- 8 つの箱と詳細。1 項目を 1 行にし、印（窓口の返事・あなたの番の理由・agent・締め切り）を題の前に置く。
- 箱の高さ: 操作中の箱を大きくし、ほかは先頭の数行に縮める。端末が低いと、ほかの箱を枠と題だけまで縮める（`internal/ui/layout.go`）。
- キー（ブラウザのデスクに合わせたもの）: `h`/`l`・`Tab` で箱、`j`/`k` で行、`q w e r t y u` でリストの箱へ、`o` で窓口の箱へ、`a` で inbox に追加、`s` でエディタ、`d` で成果物、`f` で移す（メニュー）、`x` で完了、`Enter` で返事（`Ctrl+J` で改行、送るときは 1 行にまとまる）、`/` で絞り込み、`g` + 頭文字で箱へ、`Ctrl+D`/`Ctrl+U` で詳細をめくる、`Ctrl+R` で読み直す、`Ctrl+C` で終わる、`?` で一覧。
- 窓口とのやり取りの表示と、0.8 秒表示したら読んだ印を付けること（`gtd.py read`）。j/k で通り過ぎただけでは付けない。
- 速さ: 起動から最初の画面まで約 75 ms、`j` から描き直しまで約 11 ms（tmux で測った）。`gtd.py json` は 17 件で約 42 ms。

## いまできていないこと

- 窓口の問い・承認の問い・許可の確認、worker の問い（デスクの ⇧Q〜⇧R）。
- あなたの番の `ask`（worker の問いがある）・`agent_done`（worker が終わった）、worker の進み具合（タスクの数）、`v`（worker の画面へ切り替え）。どれも Hub の worker が持つセッションの情報が要る。
- 旧案件の移し替え（デスクの `i`）。一度きりの作業なのでブラウザのデスクに任せた。
- プロジェクトのステップの追加・並べ替え（`gtd.py step`）、締め切りの入力。
- 日本語の表の最後の列が少しずれることがある。Markdown のリンクは押せず、URL を出すだけ。
- 人の変更の記録（`gtd.py record`）と、エディタでの保存の記録（`action: edit`）は lazygtd では付けない。Hub が付ける。

## これからの方向

ユーザーは lazygtd を私用でも磨いていく。決まっている向きは次のとおり。

- 操作感と見た目を lazygit に寄せる。今のデスクのキー（`q`〜`u` で箱へ、など）は守らなくてよい。lazygit の決まり（数字のキーで箱へ、`[`/`]` でタブ、`?` のメニュー、`Esc` で戻る、`q` で終わる、選んだ行の色、枠の題の付け方など）を手本にして選び直す。キーを変えたら `internal/desk/keys.go` の `KeyAction`・`Hints`・`Help` と、`internal/ui/ui_test.go` を一緒に直す。
- 箱の大きさは変えない。今は操作中の箱を大きくしてほかを縮めているが、操作する箱を移っても、それぞれの箱の大きさが変わらないようにする（lazygit の既定と同じ）。`internal/ui/layout.go` の `BoxHeights` を、フォーカスに頼らない割り振りにする。
- `c` で inbox に項目を作る（今の `a` の役目）。lazygit の `c`（commit）と同じく、作る操作を `c` に置く。
- 窓口のターミナルを開かずに、lazygtd だけで頼みごとまで済ませる。
  - 頼む: `c` で inbox に足せば、Hub が窓口に知らせる（済み）。詳細を書けるよう、題だけでなく本文も入れられる欄にするとよい。
  - 窓口の返事を読んで答える: `o` の箱と返事の欄で済む（済み）。
  - 窓口や worker の問い・承認に答える: まだできない。「どの画面からも同じ口」の考えで、答えを渡す CLI（例: `asks.py answer <id> <番号>`）を Hub と skill の側に作り、ブラウザのデスクと lazygtd の両方から呼ぶ形を勧める。Hub のデスクの HTTP を lazygtd から呼ぶ案もあるが、トークンを渡す口が要り、決まりが 2 か所に分かれる。承認の記録は窓口でしか作れないので、承認の要る問いは lazygtd でも「窓口で答える」と出す。
  - worker の様子: `~/hub/state/asks/<id>.json`（worker の問い）は lazygtd からも読める。worker の進み具合と画面の切り替えは、Hub の側に読める口ができてから。

## 試しで分かったこと

別のリポジトリで作ったときの見立て。今の Hub は上の「Hub (local)・ブラウザのデスクとの関係」まで進んでいる。

- 速さと日々の操作（inbox を片付ける、移す、完了にする、本文を速く読む）は TUI のほうが上で、不具合も起きにくい。頼るのは `gtd.py json` の形と端末だけで、Orca に頼るのは `s`・`d` の `orca file open` だけ（失敗しても nvim に回せる）。
- ブラウザのデスクは、表・見出し・リンクの読みやすさと、問い・承認・権限のカード、worker の様子で上回る。ブラウザのデスクは Orca のタブ・ポート・トークンの扱いで不具合が出やすかった。
- 作りの手間: lazygtd はカード無しで約 2,000 行（テストを除く）。HTTP もトークンも要らない。カードと worker の進み具合は、Hub の側に口が無いと作れない。
- TUI を主にするなら、Orca のターミナルのペインに lazygtd を常に置き、ブラウザのデスクは Markdown の読みもの用に残す形がよいと見ている。

## 試しのときに決めたこと

- lazygit のコードは写していない。設計（左に箱、右に詳細、最下行にキー、画面を明け渡して子のプロセスを動かす）だけを手本にした。写すときは、写したコードに lazygit の著作権とライセンスの表示を付ける（`NOTICE.md`）。
- 終わるキーは `Ctrl+C` だけにした。`q` は箱のキー、⇧Q〜⇧R はデスクで問いに答えるキーだったため。lazygit に寄せるなら見直してよい。
- 返事は 1 行にまとめて `gtd.py say` に渡す。デスクと同じで、`say` が本文に 1 行を足すため。
- Orca の中かどうかは `ORCA_PANE_KEY` で見る。dotfiles の hook が Orca のターミナルの印として読む変数のため。
- `orca file open` は `--worktree` を付けず、項目のフォルダで動かす。CLI が cwd からワークスペースを決めるため。
- Go の module の名前は、もとのリポジトリと同じ `github.com/Lettuce222/lazygtd` のまま。

## 最初の一手

`tools/lazygtd` で `go test ./...` を通し、`scripts/demo-home.sh /tmp/lazygtd-demo && go run . --gtd-home /tmp/lazygtd-demo` で今の画面を見る。そのうえで、上の「これからの方向」のうち、キーを lazygit に寄せる（`c` で inbox を含む）と、箱の大きさを固定する、から始める。
