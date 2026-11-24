package desk

import "strings"

// The keys are lazygit's defaults (pkg/config/user_config.go of lazygit 0.65, Universal and the
// side panels'), with GTD's acts put where lazygit has the nearest one: c makes a new item as c
// makes a commit, r writes a reply as r rewords a commit, <space> marks an item done as it stages a
// file, Enter goes into a project's steps as it goes into a commit's files, <c-j>/<c-k> move a step
// as they move a commit. Bindings is the one table: the keys do what it says, the bottom line shows
// its short words, and ? lists it.

// Key is a key pressed: a character, or one of the named keys.
type Key struct {
	Ch    rune
	Named string // "Tab", "BackTab", "Enter", "Esc", "Space", "Up", "Down", "Left", "Right", "PgUp", "PgDn", "Home", "End", "CtrlD", "CtrlU", "CtrlJ", "CtrlK", "CtrlO"
}

// Label is the key as lazygit writes it.
func (k Key) Label() string {
	if k.Named == "" {
		return string(k.Ch)
	}
	if strings.HasPrefix(k.Named, "Ctrl") {
		return "<c-" + strings.ToLower(strings.TrimPrefix(k.Named, "Ctrl")) + ">"
	}
	return "<" + strings.ToLower(k.Named) + ">"
}

// Binding is a key's act in a context.
type Binding struct {
	Ctx   string // global, list (a list of items; steps too), steps (a project's steps), main (the detail)
	Keys  []Key
	Do    string
	Arg   int
	Desc  string // in the menu (?)
	Short string // on the bottom line; "" for none
	Item  bool   // needs a selected item
	Git   string // lazygit's act on this key, for the report's table
}

func ch(r rune) Key       { return Key{Ch: r} }
func named(n string) Key  { return Key{Named: n} }
func keys(k ...Key) []Key { return k }

// Bindings are every key, the context's own first; a context's key hides the global one.
var Bindings = []Binding{
	// A list of items.
	{Ctx: "list", Keys: keys(ch('c')), Do: "create", Desc: "新しい項目を作る（1 行目が題、<c-j> のあとが本文）", Short: "新規", Git: "コミット"},
	{Ctx: "list", Keys: keys(ch('r')), Do: "reply", Desc: "返事の欄へ（「あなたの番への返事」に足す）", Short: "返事", Item: true, Git: "コミットの文を直す（reword）"},
	{Ctx: "list", Keys: keys(named("Space")), Do: "toggle", Desc: "完了にする（完了のタブでは次の行動に戻す）", Short: "完了", Item: true, Git: "ステージ／戻す、ブランチを切り替える"},
	{Ctx: "list", Keys: keys(named("Enter")), Do: "enter", Desc: "中に入る（プロジェクトはステップ、ほかは返事の欄）", Item: true, Git: "中に入る"},
	{Ctx: "list", Keys: keys(ch('m')), Do: "move", Desc: "移す（メニュー）", Short: "移す", Item: true, Git: "rebase のメニュー"},
	{Ctx: "list", Keys: keys(ch('a')), Do: "ask", Desc: "窓口に頼む（次の行動の agent の項目にする）", Short: "窓口に頼む", Item: true, Git: "すべてをステージ"},
	{Ctx: "list", Keys: keys(ch('e')), Do: "edit", Desc: "エディタで開く（Orca のエディタ、外では nvim）", Short: "開く", Item: true, Git: "ファイルを編集する"},
	{Ctx: "list", Keys: keys(ch('o')), Do: "open", Desc: "成果物を開く", Item: true, Git: "ファイルを開く"},
	{Ctx: "list", Keys: keys(named("CtrlO")), Do: "copy", Desc: "id と題を写す", Item: true, Git: "クリップボードに写す"},
	{Ctx: "list", Keys: keys(ch('j'), named("Down")), Do: "step", Arg: 1, Desc: "下へ", Git: "下へ"},
	{Ctx: "list", Keys: keys(ch('k'), named("Up")), Do: "step", Arg: -1, Desc: "上へ", Git: "上へ"},
	{Ctx: "list", Keys: keys(ch('.')), Do: "page", Arg: 1, Desc: "次のページ", Git: "次のページ"},
	{Ctx: "list", Keys: keys(ch(',')), Do: "page", Arg: -1, Desc: "前のページ", Git: "前のページ"},
	{Ctx: "list", Keys: keys(ch('>'), named("End")), Do: "bottom", Desc: "いちばん下へ", Git: "いちばん下へ"},
	{Ctx: "list", Keys: keys(ch('<'), named("Home")), Do: "top", Desc: "いちばん上へ", Git: "いちばん上へ"},
	{Ctx: "list", Keys: keys(ch('/')), Do: "filter", Desc: "絞り込む", Short: "絞り込み", Git: "絞り込む／探す"},
	// A project's steps (after Enter on a project).
	{Ctx: "steps", Keys: keys(ch('c')), Do: "createStep", Desc: "ステップを足す", Short: "ステップを足す", Git: "コミット"},
	{Ctx: "steps", Keys: keys(named("CtrlJ")), Do: "stepMove", Arg: 1, Desc: "ステップを下げる", Short: "下げる", Item: true, Git: "コミットを下げる"},
	{Ctx: "steps", Keys: keys(named("CtrlK")), Do: "stepMove", Arg: -1, Desc: "ステップを上げる", Short: "上げる", Item: true, Git: "コミットを上げる"},
	{Ctx: "steps", Keys: keys(named("Esc")), Do: "back", Desc: "プロジェクトに戻る", Short: "戻る", Git: "戻る"},
	// The detail.
	{Ctx: "main", Keys: keys(ch('j'), named("Down")), Do: "scroll", Arg: 1, Desc: "下へめくる", Git: "下へ"},
	{Ctx: "main", Keys: keys(ch('k'), named("Up")), Do: "scroll", Arg: -1, Desc: "上へめくる", Git: "上へ"},
	{Ctx: "main", Keys: keys(ch('r')), Do: "reply", Desc: "返事を書く", Short: "返事", Item: true, Git: "—"},
	{Ctx: "main", Keys: keys(ch('e')), Do: "edit", Desc: "エディタで開く", Short: "開く", Item: true, Git: "ファイルを編集する"},
	{Ctx: "main", Keys: keys(ch('o')), Do: "open", Desc: "成果物を開く", Item: true, Git: "ファイルを開く"},
	{Ctx: "main", Keys: keys(named("Esc")), Do: "back", Desc: "箱に戻る", Short: "戻る", Git: "戻る"},
	// Everywhere.
	{Ctx: "global", Keys: keys(ch('1')), Do: "panel", Arg: 0, Desc: "[1] あなたの番 - 窓口", Git: "[1] へ"},
	{Ctx: "global", Keys: keys(ch('2')), Do: "panel", Arg: 1, Desc: "[2] inbox", Git: "[2] へ"},
	{Ctx: "global", Keys: keys(ch('3')), Do: "panel", Arg: 2, Desc: "[3] 次の行動 - プロジェクト", Git: "[3] へ"},
	{Ctx: "global", Keys: keys(ch('4')), Do: "panel", Arg: 3, Desc: "[4] 連絡待ち", Git: "[4] へ"},
	{Ctx: "global", Keys: keys(ch('5')), Do: "panel", Arg: 4, Desc: "[5] いつか - 資料 - 完了", Git: "[5] へ"},
	{Ctx: "global", Keys: keys(ch('0')), Do: "main", Desc: "[0] 詳細へ", Git: "メインの画面へ"},
	{Ctx: "global", Keys: keys(ch('l'), named("Right"), named("Tab")), Do: "panelStep", Arg: 1, Desc: "次の箱", Git: "次の箱"},
	{Ctx: "global", Keys: keys(ch('h'), named("Left"), named("BackTab")), Do: "panelStep", Arg: -1, Desc: "前の箱", Git: "前の箱"},
	{Ctx: "global", Keys: keys(ch(']')), Do: "tab", Arg: 1, Desc: "次のタブ", Git: "次のタブ"},
	{Ctx: "global", Keys: keys(ch('[')), Do: "tab", Arg: -1, Desc: "前のタブ", Git: "前のタブ"},
	{Ctx: "global", Keys: keys(ch('J'), named("PgDn"), named("CtrlD")), Do: "scroll", Arg: 1, Desc: "詳細を下へめくる", Git: "メインを下へ"},
	{Ctx: "global", Keys: keys(ch('K'), named("PgUp"), named("CtrlU")), Do: "scroll", Arg: -1, Desc: "詳細を上へめくる", Git: "メインを上へ"},
	{Ctx: "global", Keys: keys(ch('+')), Do: "screen", Arg: 1, Desc: "画面の広さを変える（ふつう・半分・全部）", Git: "次の画面の広さ"},
	{Ctx: "global", Keys: keys(ch('_')), Do: "screen", Arg: -1, Desc: "画面の広さを戻す", Git: "前の画面の広さ"},
	{Ctx: "global", Keys: keys(ch('R')), Do: "refresh", Desc: "読み直す", Git: "読み直す"},
	{Ctx: "global", Keys: keys(ch('x'), ch('?')), Do: "menu", Desc: "キーとメニュー", Short: "キー", Git: "キーのメニュー（?）"},
	{Ctx: "global", Keys: keys(named("Esc")), Do: "back", Desc: "戻る（絞り込みを解く）", Git: "戻る"},
	{Ctx: "global", Keys: keys(ch('q')), Do: "quit", Desc: "終わる", Git: "終わる"},
}

// Action is what a key does.
type Action struct {
	Do  string
	Arg int
}

// contexts are where a context's keys are looked up, in order.
func contexts(ctx string) []string {
	switch ctx {
	case "steps":
		return []string{"steps", "list", "global"}
	case "main":
		return []string{"main", "global"}
	}
	return []string{"list", "global"}
}

// Lookup is the binding of a key in a context, or nil.
func Lookup(k Key, ctx string) *Binding {
	for _, c := range contexts(ctx) {
		for i := range Bindings {
			b := &Bindings[i]
			if b.Ctx != c {
				continue
			}
			for _, bk := range b.Keys {
				if bk == k {
					return b
				}
			}
		}
	}
	return nil
}

// KeyAction is what a key does in a context; hasItem tells whether a row is selected.
func KeyAction(k Key, ctx string, hasItem bool) Action {
	b := Lookup(k, ctx)
	if b == nil || (b.Item && !hasItem) {
		return Action{Do: "none"}
	}
	return Action{Do: b.Do, Arg: b.Arg}
}

// Shown are the bindings of a context the menu (?) lists: the context's own, then the global ones
// they do not hide, as lazygit's "Local" and "Global".
func Shown(ctx string) (local, global []Binding) {
	hidden := map[Key]bool{}
	for _, c := range contexts(ctx) {
		for _, b := range Bindings {
			if b.Ctx != c {
				continue
			}
			var free []Key
			for _, k := range b.Keys {
				if !hidden[k] {
					free = append(free, k)
				}
			}
			for _, k := range b.Keys {
				hidden[k] = true
			}
			if len(free) == 0 {
				continue
			}
			b.Keys = free
			if c == "global" {
				global = append(global, b)
			} else {
				local = append(local, b)
			}
		}
	}
	return
}

// Options are the bottom line's [description, key] pairs of a context (lazygit's options bar).
func Options(ctx string) [][2]string {
	local, global := Shown(ctx)
	var out [][2]string
	for _, b := range append(local, global...) {
		if b.Short != "" {
			out = append(out, [2]string{b.Short, b.Keys[0].Label()})
		}
	}
	return out
}
