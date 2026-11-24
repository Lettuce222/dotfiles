package ui

import (
	"fmt"
	"os/exec"
	"strings"
	"unicode/utf8"

	"github.com/jesseduffield/gocui"

	"github.com/Lettuce222/lazygtd/internal/desk"
	"github.com/Lettuce222/lazygtd/internal/gtd"
	"github.com/Lettuce222/lazygtd/internal/open"
)

// keyPress is a key as the bindings get it.
type keyPress struct {
	ch    rune
	named string
}

func keyLabel(named string) string { return desk.Key{Named: named}.Label() }

var namedKeys = map[gocui.Key]string{
	gocui.KeyTab: "Tab", gocui.KeyBacktab: "BackTab", gocui.KeyEnter: "Enter", gocui.KeyEsc: "Esc",
	gocui.KeySpace: "Space", gocui.KeyArrowUp: "Up", gocui.KeyArrowDown: "Down", gocui.KeyArrowLeft: "Left",
	gocui.KeyArrowRight: "Right", gocui.KeyPgup: "PgUp", gocui.KeyPgdn: "PgDn", gocui.KeyHome: "Home",
	gocui.KeyEnd: "End", gocui.KeyCtrlD: "CtrlD", gocui.KeyCtrlU: "CtrlU", gocui.KeyCtrlJ: "CtrlJ",
	gocui.KeyCtrlK: "CtrlK", gocui.KeyCtrlO: "CtrlO",
}

// bind sends every key to onKey (internal/desk's table decides what it does), and the inputs'
// Enter, <c-j> and Esc to the inputs. The screen's loop skips the character keys while an input is
// being written in; the named keys are skipped there by onKey.
func (a *App) bind() error {
	g := a.g
	if err := g.SetKeybinding("", gocui.KeyCtrlC, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return gocui.ErrQuit }); err != nil {
		return err
	}
	for ch := rune('!'); ch <= '~'; ch++ {
		k := keyPress{ch: ch}
		if err := g.SetKeybinding("", ch, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return a.onKey(k) }); err != nil {
			return err
		}
	}
	for key, name := range namedKeys {
		k := keyPress{named: name}
		if err := g.SetKeybinding("", key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return a.onKey(k) }); err != nil {
			return err
		}
	}
	for view, m := range map[string]map[gocui.Key]func() error{
		vInput: {
			gocui.KeyEnter: func() error { a.submitInput(); return nil },
			gocui.KeyCtrlJ: func() error { a.newLine(); return nil },
			gocui.KeyEsc:   func() error { a.closePopup(); return nil },
		},
		vReply: {
			gocui.KeyEnter: func() error { a.sendReply(); return nil },
			gocui.KeyCtrlJ: func() error { a.typeReply("\n"); return nil },
			gocui.KeyEsc:   func() error { a.replying = false; return nil },
		},
		vFilter: {
			gocui.KeyEnter: func() error { a.endFilter(true); return nil },
			gocui.KeyEsc:   func() error { a.endFilter(false); return nil },
		},
	} {
		for key, f := range m {
			f := f
			if err := g.SetKeybinding(view, key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { return f() }); err != nil {
				return err
			}
		}
	}
	// The mouse: a click selects a row or a tab, the wheel moves the selection or scrolls the detail.
	for i := range desk.Panels {
		i := i
		name := panelView(i)
		if err := g.SetKeybinding(name, gocui.MouseLeft, gocui.ModNone, func(_ *gocui.Gui, v *gocui.View) error {
			if a.popup != nil || a.filtering {
				return nil
			}
			a.model.FocusPanel(i)
			a.model.SelectIndex(a.model.Cur(), v.SelectedLineIdx())
			return nil
		}); err != nil {
			return err
		}
		if err := g.SetTabClickBinding(name, func(tab int) error {
			a.model.FocusPanel(i)
			a.model.MoveTab(tab - a.model.Tab(i))
			return nil
		}); err != nil {
			return err
		}
		for key, d := range map[gocui.Key]int{gocui.MouseWheelDown: 1, gocui.MouseWheelUp: -1} {
			d := d
			if err := g.SetKeybinding(name, key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error {
				if a.popup == nil && !a.filtering {
					a.model.FocusPanel(i)
					a.model.Step(d)
				}
				return nil
			}); err != nil {
				return err
			}
		}
	}
	if err := g.SetKeybinding(vMain, gocui.MouseLeft, gocui.ModNone, func(*gocui.Gui, *gocui.View) error {
		if a.popup == nil && !a.filtering && a.model.Selected() != nil {
			a.model.Main = true
		}
		return nil
	}); err != nil {
		return err
	}
	for key, d := range map[gocui.Key]int{gocui.MouseWheelDown: 3, gocui.MouseWheelUp: -3} {
		d := d
		if err := g.SetKeybinding(vMain, key, gocui.ModNone, func(*gocui.Gui, *gocui.View) error { a.scrollDetail(d); return nil }); err != nil {
			return err
		}
	}
	return nil
}

func (a *App) onKey(k keyPress) error {
	if a.filtering || a.replying || (a.popup != nil && a.popup.input) {
		return nil // the input's own keys come first; the others do nothing there
	}
	if a.popup != nil {
		a.popupKey(k)
		return nil
	}
	act := desk.KeyAction(desk.Key{Ch: k.ch, Named: k.named}, a.ctx(), a.model.Selected() != nil)
	return a.do(act)
}

// do runs an act of the table (internal/desk Bindings).
func (a *App) do(act desk.Action) error {
	m := a.model
	it := m.Selected()
	switch act.Do {
	case "quit":
		return gocui.ErrQuit
	case "back":
		switch {
		case m.Main:
			m.Main = false
		case m.LeaveSteps():
		case m.Filters[m.Cur()] != "":
			delete(m.Filters, m.Cur())
			m.SetState(m.State)
		}
	case "panel":
		m.FocusPanel(act.Arg)
	case "main":
		if it != nil {
			m.Main = true
		}
	case "panelStep":
		if m.Main {
			m.Main = false
		} else {
			m.MovePanel(act.Arg)
		}
	case "tab":
		m.Main = false
		m.MoveTab(act.Arg)
	case "step":
		m.Step(act.Arg)
	case "page":
		m.Step(act.Arg * max(a.panelHeight()-1, 1))
	case "top":
		m.Step(-1 << 20)
	case "bottom":
		m.Step(1 << 20)
	case "scroll":
		if a.ctx() == "main" {
			a.scrollDetail(act.Arg)
		} else {
			_, h := a.detailSize()
			a.scrollDetail(act.Arg * max(h/2, 1))
		}
	case "screen":
		a.screen = (a.screen + act.Arg + 3) % 3
	case "refresh":
		a.reload()
		a.flash("読み直した")
	case "menu":
		a.keysMenu()
	case "filter":
		a.filtering = true
		a.setSearching(true)
	case "create":
		a.create()
	case "createStep":
		a.createStep()
	case "reply":
		a.reply(it)
	case "toggle":
		a.toggle(it)
	case "enter":
		// Into a project's steps, as lazygit goes into a commit's files; else into the reply box.
		if it.List == "project" && m.Steps(m.Panel) == "" {
			m.EnterSteps(it.ID)
		} else {
			a.reply(it)
		}
	case "move":
		a.moveMenu(it)
	case "ask":
		a.askMenu(it)
	case "edit":
		a.openFile(it.ID, "")
	case "open":
		a.openDeliverable(it)
	case "copy":
		a.copy(it)
	case "stepMove":
		a.stepMove(it, act.Arg)
	}
	return nil
}

func (a *App) panelHeight() int {
	v, err := a.g.View(panelView(a.model.Panel))
	if err != nil {
		return 1
	}
	_, h := v.InnerSize()
	return h
}

func (a *App) detailSize() (int, int) {
	v, err := a.g.View(vMain)
	if err != nil {
		return 0, 0
	}
	return v.InnerSize()
}

func (a *App) scrollDetail(delta int) {
	v, err := a.g.View(vMain)
	if err != nil {
		return
	}
	_, h := v.InnerSize()
	limit := max(v.ViewLinesHeight()-h, 0)
	v.SetOriginY(min(max(v.OriginY()+delta, 0), limit))
}

// ---------------------------------------------------------------- menus

// keysMenu is lazygit's keybindings menu (?): the context's keys, then the global ones, each run by
// Enter or by its key.
func (a *App) keysMenu() {
	local, global := desk.Shown(a.ctx())
	var items []menuItem
	add := func(header string, bs []desk.Binding) {
		items = append(items, menuItem{header: true, desc: header})
		for _, b := range bs {
			if b.Do == "menu" || b.Do == "back" {
				continue
			}
			b := b
			items = append(items, menuItem{key: b.Keys[0].Label(), desc: b.Desc, run: func() {
				_ = a.do(desk.KeyAction(b.Keys[0], a.ctx(), a.model.Selected() != nil))
			}})
		}
	}
	add("この箱", local)
	add("どこでも", global)
	a.menu("キー", items)
}

func (a *App) moveMenu(it *gtd.Item) {
	var items []menuItem
	for _, t := range desk.MoveTo {
		t := t
		desc := t.Label
		if t.List == it.List {
			desc += "（今ここ）"
		}
		items = append(items, menuItem{key: string(t.Key), desc: desc, run: func() {
			if t.List == "calendar" {
				title := it.Title
				if !strings.HasPrefix(title, desk.CalendarPrefix) {
					title = desk.CalendarPrefix + title
				}
				id, hash := it.ID, it.Hash
				a.write(id, "カレンダーに入れる次の行動にした", func() error { return a.gtd.ToCalendar(id, title, hash) })
				return
			}
			if t.List == it.List {
				a.flash("もうそこにある")
				return
			}
			id, hash := it.ID, it.Hash
			a.write(id, "移した: "+t.Label, func() error { return a.gtd.Move(id, t.List, hash) })
		}})
	}
	a.menu("移す先", items)
}

// askMenu hands an item to the orchestrator, after a confirmation as lazygit asks before an act
// that reaches others: the item becomes an agent's item in next with no worker, which the Hub tells
// the orchestrator of, and the orchestrator starts a worker for.
func (a *App) askMenu(it *gtd.Item) {
	if it.List == "done" {
		a.flash("完了した項目は頼めない")
		return
	}
	if it.List == "next" && gtd.S(it.Actor) == "agent" {
		a.flash("もう窓口に頼んである")
		return
	}
	id, hash := it.ID, it.Hash
	a.menu("窓口に頼む", []menuItem{
		{key: "a", desc: "頼む（次の行動の agent の項目にする。Hub が窓口に知らせ、窓口が worker を立てる）", run: func() {
			a.write(id, "窓口に頼んだ", func() error { return a.gtd.Ask(id, hash) })
		}},
	})
}

func (a *App) openDeliverable(it *gtd.Item) {
	switch len(it.Deliverables) {
	case 0:
		a.flash("成果物はまだ無い")
	case 1:
		a.openFile(it.ID, it.Deliverables[0])
	default:
		var items []menuItem
		for i, d := range it.Deliverables {
			d := d
			key := " "
			if i < 9 {
				key = fmt.Sprint(i + 1)
			}
			items = append(items, menuItem{key: key, desc: d, run: func() { a.openFile(it.ID, d) }})
		}
		a.menu("成果物を開く", items)
	}
}

// ---------------------------------------------------------------- acts

func (a *App) toggle(it *gtd.Item) {
	id, hash := it.ID, it.Hash
	if it.List == "done" {
		a.write(id, "次の行動に戻した", func() error { return a.gtd.Move(id, "next", hash) })
		return
	}
	a.write(id, "完了にした", func() error { return a.gtd.Done(id, hash) })
}

// createList is the list c makes an item in: the list shown, where an item needs nothing more than
// a title; else inbox (lazygit's c always makes a commit, whatever panel it is pressed in).
func (a *App) createList() string {
	switch l := a.model.Cur(); l {
	case "next", "project", "someday", "reference":
		return l
	}
	return "inbox"
}

func (a *App) create() {
	list := a.createList()
	a.inputPopup("新しい項目（"+desk.Label(list)+"）", " 1 行目が題、<c-j> のあとが本文 ", true, func(text string) {
		title, body, _ := strings.Cut(text, "\n")
		title = strings.Join(strings.Fields(title), " ")
		body = strings.Trim(body, "\n")
		if title == "" {
			a.flash("題が空")
			return
		}
		if utf8.RuneCountInString(title) > titleMax {
			a.flashErr("作れなかった: 題は 1 行で 300 字まで")
			return
		}
		a.write("", desk.Label(list)+"に作った", func() error { return a.gtd.Add(list, title, body) })
	})
}

func (a *App) createStep() {
	project := a.model.Steps(a.model.Panel)
	a.inputPopup("新しいステップ（"+a.model.ProjectShort(project)+"）", "", false, func(text string) {
		title := strings.Join(strings.Fields(text), " ")
		if title == "" {
			return
		}
		a.write("", "ステップを足した", func() error { return a.gtd.StepAdd(project, title) })
	})
}

// reply goes into the reply box under the detail (SPEC 5.5, 7.3).
func (a *App) reply(it *gtd.Item) {
	if it.List == "done" {
		a.flash("完了した項目には返事を書かない")
		return
	}
	if a.replyFor != it.ID {
		if v, err := a.g.View(vReply); err == nil {
			v.ClearTextArea()
		}
	}
	a.replying, a.replyFor = true, it.ID
}

func (a *App) typeReply(s string) {
	if v, err := a.g.View(vReply); err == nil {
		v.TextArea.TypeString(s)
		v.RenderTextArea()
	}
}

// sendReply writes the reply as one line of 「あなたの番への返事」 (gtd.py say), as the desk does.
// An empty box sends nothing (SPEC 6.3).
func (a *App) sendReply() {
	v, err := a.g.View(vReply)
	if err != nil {
		return
	}
	said := strings.Join(strings.Fields(v.TextArea.GetContent()), " ")
	if said == "" {
		return
	}
	if utf8.RuneCountInString(said) > replyMax {
		a.flash("返事は 2000 字まで")
		return
	}
	id := a.replyFor
	v.ClearTextArea()
	a.replying = false
	// The Hub tells the orchestrator of the reply from the change log (SPEC 7.4); lazygtd only writes.
	a.write(id, "返事を書いた", func() error { return a.gtd.Say(id, said) })
}

func (a *App) stepMove(it *gtd.Item, delta int) {
	project := a.model.Steps(a.model.Panel)
	p := a.model.Item(project)
	if p == nil {
		return
	}
	pos := -1
	for i, s := range p.Steps {
		if s == it.ID {
			pos = i
		}
	}
	to := pos + delta
	if pos < 0 || to < 0 || to >= len(p.Steps) {
		return
	}
	id := it.ID
	a.write(id, "", func() error { return a.gtd.StepMove(project, id, to+1) })
}

func (a *App) copy(it *gtd.Item) {
	cmd := exec.Command("pbcopy")
	cmd.Stdin = strings.NewReader(it.ID + " " + it.Title)
	if err := cmd.Run(); err != nil {
		a.flash("写せなかった: " + err.Error())
		return
	}
	a.flash("写した: " + it.ID)
}

// ---------------------------------------------------------------- inputs

func (a *App) inputText() string {
	v, err := a.g.View(vInput)
	if err != nil {
		return ""
	}
	return v.TextArea.GetContent()
}

func (a *App) newLine() {
	if a.popup == nil || !a.popup.multiline {
		return
	}
	if v, err := a.g.View(vInput); err == nil {
		v.TextArea.TypeString("\n")
		v.RenderTextArea()
	}
}

func (a *App) submitInput() {
	p := a.popup
	if p == nil || !p.input {
		return
	}
	text := a.inputText()
	if strings.TrimSpace(text) == "" {
		return // an empty input sends nothing (SPEC 6.3)
	}
	a.closePopup()
	p.submit(text)
}

// editInput is the inputs' editor: gocui's, with Enter left to the input's binding.
func (a *App) editInput(v *gocui.View, key gocui.Key, ch rune, mod gocui.Modifier) bool {
	if key == gocui.KeyEnter || key == gocui.KeyTab {
		return true
	}
	return gocui.SimpleEditor(v, key, ch, mod)
}

// editFilter is the filter's editor: the rows follow each key.
func (a *App) editFilter(v *gocui.View, key gocui.Key, ch rune, mod gocui.Modifier) bool {
	if key == gocui.KeyEnter || key == gocui.KeyTab || key == gocui.KeyCtrlJ {
		return true
	}
	ok := gocui.SimpleEditor(v, key, ch, mod)
	a.setFilter(v.TextArea.GetContent())
	return ok
}

func (a *App) setFilter(q string) {
	q = strings.TrimSpace(q)
	if q == "" {
		delete(a.model.Filters, a.model.Cur())
	} else {
		a.model.Filters[a.model.Cur()] = q
	}
	a.model.SetState(a.model.State)
}

// endFilter closes the filter's input: Enter keeps the filter (Esc in the list clears it later),
// Esc clears it now.
func (a *App) endFilter(keep bool) {
	if !keep {
		a.setFilter("")
	}
	a.filtering = false
	a.setSearching(false)
	_ = a.g.DeleteView(vFilter)
	_ = a.g.DeleteView(vFilterL)
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
				a.flashErr(err.Error() + "（LAZYGTD_EDITOR=nvim で nvim を使う）")
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
	a.reload()
}
