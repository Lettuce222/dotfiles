package ui

import (
	"strings"
	"unicode/utf8"

	"github.com/jesseduffield/gocui"

	"github.com/Lettuce222/lazygtd/internal/desk"
	"github.com/Lettuce222/lazygtd/internal/open"
)

// bind sends every key the desk knows to onKey (internal/desk decides what it does), and the
// input's Enter, Ctrl+J and Esc to the input.
func (a *App) bind() error {
	g := a.g
	if err := g.SetKeybinding("", gocui.KeyCtrlC, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return gocui.ErrQuit }); err != nil {
		return err
	}
	if err := g.SetKeybinding("", gocui.KeyCtrlR, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { a.reload(); return nil }); err != nil {
		return err
	}
	// Every printable ASCII key: the screen's loop skips these while the input is being written in.
	for ch := rune('!'); ch <= '~'; ch++ {
		k := desk.Key{Ch: ch}
		if err := g.SetKeybinding("", ch, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return a.onKey(k) }); err != nil {
			return err
		}
	}
	named := map[gocui.Key]string{
		gocui.KeyTab: "Tab", gocui.KeyBacktab: "BackTab", gocui.KeyEnter: "Enter", gocui.KeyEsc: "Esc",
		gocui.KeyCtrlD: "CtrlD", gocui.KeyCtrlU: "CtrlU", gocui.KeyPgdn: "PgDn", gocui.KeyPgup: "PgUp",
		gocui.KeyArrowDown: "Down", gocui.KeyArrowUp: "Up",
	}
	for key, name := range named {
		k := desk.Key{Named: name}
		if err := g.SetKeybinding("", key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error {
			if a.mode == mInput {
				return nil // the input's own keys come first; the others do nothing there
			}
			return a.onKey(k)
		}); err != nil {
			return err
		}
	}
	for key, f := range map[gocui.Key]func() error{
		gocui.KeyEnter: func() error { return a.submit(false) },
		gocui.KeyCtrlJ: func() error { a.typeIn("\n"); return nil },
		gocui.KeyEsc:   func() error { return a.cancelInput() },
	} {
		f := f
		if err := g.SetKeybinding(vInput, key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return f() }); err != nil {
			return err
		}
	}
	// The mouse: a click on a row selects it, the wheel scrolls the detail.
	for i, b := range desk.Boxes {
		id := b.ID
		_ = i
		if err := g.SetKeybinding("box:"+id, gocui.MouseLeft, gocui.ModNone, func(_ *gocui.Gui, v *gocui.View) error {
			if a.mode != mList {
				return nil
			}
			a.model.Focus(id)
			a.model.SelectIndex(id, v.SelectedLineIdx())
			return nil
		}); err != nil {
			return err
		}
	}
	for key, d := range map[gocui.Key]int{gocui.MouseWheelDown: 3, gocui.MouseWheelUp: -3} {
		d := d
		if err := g.SetKeybinding(vDetail, key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { a.scrollDetail(d); return nil }); err != nil {
			return err
		}
	}
	return nil
}

func (a *App) onKey(k desk.Key) error {
	if a.mode == mInput {
		return nil
	}
	if k.Named == "Down" {
		k = desk.Key{Ch: 'j'}
	} else if k.Named == "Up" {
		k = desk.Key{Ch: 'k'}
	}
	switch a.mode {
	case mHelp:
		if k.Named == "Esc" || k.Ch == '?' || k.Ch == 'q' {
			a.mode = mList
		}
		return nil
	case mDeliv:
		return a.delivKey(k)
	}
	m := desk.ModeList
	if a.mode == mG {
		m = desk.ModeG
	} else if a.mode == mMenu {
		m = desk.ModeMenu
	}
	it := a.model.Selected()
	act := desk.KeyAction(k, m, it != nil)
	if a.mode == mG {
		a.mode = mList
	}
	switch act.Do {
	case "box":
		a.model.MoveBox(act.Delta)
	case "focus":
		a.model.Focus(act.Box)
	case "step":
		a.model.Step(act.Delta)
	case "scroll":
		_, h := a.detailSize()
		a.scrollDetail(act.Delta * max(h/2, 1))
	case "g":
		a.mode = mG
	case "help":
		a.mode = mHelp
	case "migrate":
		a.flash("移し替え（旧案件）は lazygtd には無い。ブラウザのデスクの i で")
	case "filter":
		a.startInput("filter", "", a.model.Filters[a.model.Cur])
	case "add":
		a.startInput("add", "", "")
	case "write":
		if it.List == "done" {
			a.flash("完了した項目には返事を書かない")
			return nil
		}
		a.startInput("reply", it.ID, "")
	case "open":
		a.openFile(it.ID, "")
	case "deliv":
		switch len(it.Deliverables) {
		case 0:
			a.flash("成果物はまだ無い")
		case 1:
			a.openFile(it.ID, it.Deliverables[0])
		default:
			a.mode, a.menuFor, a.delivSel = mDeliv, it.ID, 0
		}
	case "move":
		a.mode, a.menuFor = mMenu, it.ID
	case "menu":
		a.mode = mList
		if t := a.model.Item(a.menuFor); t != nil {
			if t.List == act.List {
				a.flash("もうそこにある")
				return nil
			}
			id, hash, list := t.ID, t.Hash, act.List
			a.write(id, "移した: "+listLabel(list), func() error { return a.gtd.Move(id, list, hash) })
		}
	case "close":
		a.mode = mList
	case "done":
		id, hash := it.ID, it.Hash
		a.write(id, "完了にした", func() error { return a.gtd.Done(id, hash) })
	}
	return nil
}

func listLabel(list string) string {
	for _, t := range desk.MoveTo {
		if t.List == list {
			return t.Label
		}
	}
	return list
}

func (a *App) delivKey(k desk.Key) error {
	it := a.model.Item(a.menuFor)
	if it == nil {
		a.mode = mList
		return nil
	}
	n := len(it.Deliverables)
	switch {
	case k.Named == "Esc" || k.Ch == 'q':
		a.mode = mList
	case k.Ch == 'j':
		a.delivSel = min(a.delivSel+1, n-1)
	case k.Ch == 'k':
		a.delivSel = max(a.delivSel-1, 0)
	case k.Named == "Enter":
		a.mode = mList
		a.openFile(it.ID, it.Deliverables[a.delivSel])
	case k.Ch >= '1' && k.Ch <= '9' && int(k.Ch-'1') < n:
		a.mode = mList
		a.openFile(it.ID, it.Deliverables[k.Ch-'1'])
	}
	return nil
}

func (a *App) detailSize() (int, int) {
	v, err := a.g.View(vDetail)
	if err != nil {
		return 0, 0
	}
	return v.InnerSize()
}

func (a *App) scrollDetail(delta int) {
	v, err := a.g.View(vDetail)
	if err != nil {
		return
	}
	_, h := v.InnerSize()
	limit := max(v.ViewLinesHeight()-h, 0)
	v.SetOriginY(min(max(v.OriginY()+delta, 0), limit))
}

// ---------------------------------------------------------------- the input

func (a *App) startInput(kind, id, text string) {
	a.mode, a.inputKind, a.inputFor = mInput, kind, id
	// The view is made by the next layout; its text is set once it is there.
	a.g.Update(func(g *gocui.Gui) error {
		v, err := g.View(vInput)
		if err != nil {
			return nil
		}
		v.ClearTextArea()
		if text != "" {
			v.TextArea.TypeString(text)
			v.RenderTextArea()
		}
		return nil
	})
}

func (a *App) inputText() string {
	v, err := a.g.View(vInput)
	if err != nil {
		return ""
	}
	return v.TextArea.GetContent()
}

func (a *App) typeIn(s string) {
	if a.inputKind != "reply" {
		return // one line only
	}
	if v, err := a.g.View(vInput); err == nil {
		v.TextArea.TypeString(s)
		v.RenderTextArea()
	}
}

// edit is the input's editor: gocui's, and the filter follows each key.
func (a *App) edit(v *gocui.View, key gocui.Key, ch rune, mod gocui.Modifier) bool {
	if key == gocui.KeyEnter || key == gocui.KeyTab {
		return true // Enter is the input's binding; no tab in a line
	}
	ok := gocui.SimpleEditor(v, key, ch, mod)
	if a.inputKind == "filter" {
		a.setFilter(v.TextArea.GetContent())
	}
	return ok
}

func (a *App) setFilter(q string) {
	q = strings.TrimSpace(q)
	if q == "" {
		delete(a.model.Filters, a.model.Cur)
	} else {
		a.model.Filters[a.model.Cur] = q
	}
	a.model.SetState(a.model.State)
}

func (a *App) cancelInput() error {
	if a.inputKind == "filter" {
		a.setFilter("")
	}
	a.mode = mList
	return nil
}

// oneLine is a text as one line: gtd.py writes a reply as a line of the body (as the desk does).
func oneLine(s string) string { return strings.Join(strings.Fields(s), " ") }

func (a *App) submit(bool) error {
	text := a.inputText()
	switch a.inputKind {
	case "filter":
		a.setFilter(text)
		a.mode = mList
	case "add":
		title := oneLine(text)
		if title == "" {
			a.mode = mList
			return nil
		}
		if utf8.RuneCountInString(title) > titleMax {
			a.flash("1 行で 300 字まで")
			return nil
		}
		a.mode = mList
		a.write("", "inbox に足した", func() error { return a.gtd.Add(title) })
	case "reply":
		said := oneLine(text)
		if said == "" {
			a.flash("返事が空")
			return nil
		}
		if utf8.RuneCountInString(said) > replyMax {
			a.flash("返事は 2000 字まで")
			return nil
		}
		id := a.inputFor
		a.mode = mList
		// The Hub tells the orchestrator of the reply from the change log (src/change-log.mjs of the
		// Hub (local) plugin), whichever screen wrote it, while Orca runs.
		a.write(id, "返事を書いた（Orca の Hub が動いていれば窓口に知らせる）", func() error { return a.gtd.Say(id, said) })
	}
	return nil
}

// ---------------------------------------------------------------- opening files

// openFile opens an item (rel "") or a deliverable in Orca's editor, or in nvim outside Orca.
func (a *App) openFile(id, rel string) {
	path, err := open.Target(a.itemsDir(), id, rel)
	if err != nil {
		a.flash(err.Error())
		return
	}
	if open.InOrca() {
		go func() {
			if err := open.Orca(path); err != nil {
				a.flash(err.Error() + "（LAZYGTD_EDITOR=nvim で nvim を使う）")
				return
			}
			a.flash("Orca のエディタで開いた")
		}()
		return
	}
	a.runNvim(path)
}

// runNvim gives the terminal to nvim and takes it back when nvim ends, as lazygit runs a subprocess.
func (a *App) runNvim(path string) {
	if err := a.g.Suspend(); err != nil {
		a.flash("画面を明け渡せない: " + err.Error())
		return
	}
	runErr := open.Nvim(path).Run()
	if err := a.g.Resume(); err != nil {
		a.flash("画面に戻れない: " + err.Error())
		return
	}
	if runErr != nil {
		a.flash("nvim: " + runErr.Error())
	}
	// A save from the editor is seen by the watcher too; read now in case the watcher missed it.
	a.reload()
}
