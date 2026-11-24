package desk

// The keys, as a function of the key pressed and where the screen is; the ui does what it returns.
// They follow the browser desk (desk/keys.mjs of the Hub (local) plugin):
// - h and l (and Tab, Shift+Tab) go to the box above and below; q w e r t y u jump to a list's box
//   and o to the talk with the orchestrator; j and k go up and down in the box;
// - a adds, s opens the item in the editor, d its deliverables, f moves it, x marks it done;
// - Enter writes a reply to the selected item; ? shows every key; / narrows the rows of the box;
// - g + an initial (y i n p w s r) is another way to a list.
// Where a key means something else, the more specific place wins: the menu of where to move an item
// takes every key while it is open, and after g the letters are the lists' initials.

// Key is a key pressed: a character, or one of the named keys.
type Key struct {
	Ch    rune
	Named string // "Tab", "BackTab", "Enter", "Esc", "CtrlD", "CtrlU", "PgDn", "PgUp"
}

// Mode is where the keys go.
type Mode int

const (
	ModeList Mode = iota
	ModeG         // after g
	ModeMenu      // the menu of where to move an item (f)
)

// Action is what a key does.
type Action struct {
	Do    string // box, focus, step, add, open, deliv, move, done, write, help, filter, g, menu, close, migrate, scroll, quit, none
	Box   string
	Delta int
	List  string
}

var itemActs = map[rune]string{'s': "open", 'd': "deliv", 'f': "move", 'x': "done"}

// KeyAction is what k does in mode; hasItem tells whether a row is selected.
func KeyAction(k Key, mode Mode, hasItem bool) Action {
	switch mode {
	case ModeMenu:
		if k.Named == "Esc" || k.Ch == 'q' {
			return Action{Do: "close"}
		}
		for _, t := range MoveTo {
			if k.Named == "" && t.Key == k.Ch {
				return Action{Do: "menu", List: t.List}
			}
		}
		return Action{Do: "none"}
	case ModeG:
		for _, b := range Boxes {
			if b.G != 0 && k.Named == "" && b.G == k.Ch {
				return Action{Do: "focus", Box: b.ID}
			}
		}
		if k.Ch == 'm' {
			return Action{Do: "migrate"}
		}
		return Action{Do: "none"}
	}
	switch k.Named {
	case "Tab":
		return Action{Do: "box", Delta: 1}
	case "BackTab":
		return Action{Do: "box", Delta: -1}
	case "Enter":
		if hasItem {
			return Action{Do: "write"}
		}
		return Action{Do: "none"}
	case "CtrlD", "PgDn":
		return Action{Do: "scroll", Delta: 1}
	case "CtrlU", "PgUp":
		return Action{Do: "scroll", Delta: -1}
	case "":
	default:
		return Action{Do: "none"}
	}
	switch k.Ch {
	case '?':
		return Action{Do: "help"}
	case '/':
		return Action{Do: "filter"}
	case 'g':
		return Action{Do: "g"}
	case 'a':
		return Action{Do: "add"}
	case 'h':
		return Action{Do: "box", Delta: -1}
	case 'l':
		return Action{Do: "box", Delta: 1}
	case 'j':
		return Action{Do: "step", Delta: 1}
	case 'k':
		return Action{Do: "step", Delta: -1}
	case MigrateKey:
		return Action{Do: "migrate"}
	}
	for _, b := range Boxes {
		if b.Key == k.Ch {
			return Action{Do: "focus", Box: b.ID}
		}
	}
	if act, ok := itemActs[k.Ch]; ok {
		if hasItem {
			return Action{Do: act}
		}
		return Action{Do: "none"}
	}
	return Action{Do: "none"}
}

// Hints are the keys the bottom line shows, as [keys, what] (lazygit's options line).
func Hints(mode string) [][2]string {
	switch mode {
	case "filter":
		return [][2]string{{"Enter", "絞り込んだまま戻る"}, {"Esc", "絞り込みをやめる"}}
	case "reply":
		return [][2]string{{"Enter", "送る"}, {"Ctrl+J", "改行"}, {"Esc", "やめる"}}
	case "add":
		return [][2]string{{"Enter", "inbox に足す"}, {"Esc", "やめる"}}
	case "menu":
		return [][2]string{{"i n t w s r", "移す先"}, {"Esc", "閉じる"}}
	case "deliv":
		return [][2]string{{"j/k", "上下"}, {"Enter・1〜9", "開く"}, {"Esc", "閉じる"}}
	}
	return [][2]string{{"j/k", "上下"}, {"Enter", "返事"}, {"s", "開く"}, {"d", "成果物"}, {"f", "移す"}, {"x", "完了"}, {"a", "追加"}, {"/", "絞り込み"}, {"h/l", "箱"}, {"q〜u・o", "箱へ"}, {"?", "キー"}, {"Ctrl+C", "終わる"}}
}

// Help is the list of every key (?).
var Help = [][2]string{
	{"h / l、Tab / ⇧Tab", "左の箱を移る"},
	{"q w e r t y u", "リストの箱へ（あなたの番・inbox・次の行動・プロジェクト・連絡待ち・いつか・資料）"},
	{"o", "窓口の箱へ（窓口の返事と、答え待ち）"},
	{"i", "移し替え（lazygtd には無い。ブラウザのデスクで）"},
	{"j / k", "箱の中を上下"},
	{"Ctrl+D / Ctrl+U", "右の詳細をめくる（PgDn / PgUp、マウスのホイールも）"},
	{"/", "箱の中を絞り込む（Enter で決める、Esc でやめる）"},
	{"Enter", "返事を書く（Enter で送る）"},
	{"Ctrl+J", "書く欄で改行（送るときは 1 行にまとまる）"},
	{"Esc", "欄やメニューから抜ける"},
	{"a", "inbox に足す"},
	{"s", "Orca のエディタで開く（Orca の外なら nvim）"},
	{"d", "成果物を開く"},
	{"f", "移す（メニュー）"},
	{"x", "完了"},
	{"g + y i n p w s r", "リストの頭文字で箱へ"},
	{"Ctrl+C", "終わる（q は箱のキーなので使わない）"},
	{"?", "この一覧を閉じる"},
}
