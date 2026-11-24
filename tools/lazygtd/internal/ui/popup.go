package ui

import (
	"fmt"
	"strings"

	"github.com/jesseduffield/gocui"
	"github.com/mattn/go-runewidth"

	"github.com/Lettuce222/lazygtd/internal/render"
)

// popup is what lazygit shows in the middle of the screen: a menu (the keys, where to move, which
// deliverable), an input (a new item, a reply, a new step) or a message (an error, a conflict).
type popup struct {
	title string
	kind  string // menu, input, message

	items []menuItem
	sel   int

	input     bool
	multiline bool         // <c-j> starts a new line: the first line is the title, the rest the body
	submit    func(string) // the input's Enter
	hint      string       // the input's line under the title

	text  string
	error bool
}

type menuItem struct {
	key    string
	desc   string
	header bool
	run    func()
}

func (p *popup) options() [][2]string {
	switch p.kind {
	case "menu":
		return [][2]string{{"実行", "<enter>"}, {"閉じる", "<esc>"}}
	case "input":
		if p.multiline {
			return [][2]string{{"作る", "<enter>"}, {"本文へ（改行）", "<c-j>"}, {"やめる", "<esc>"}}
		}
		return [][2]string{{"送る", "<enter>"}, {"やめる", "<esc>"}}
	}
	return [][2]string{{"閉じる", "<enter>"}}
}

// selectable moves the menu's selection delta items, over the headers.
func (p *popup) step(delta int) {
	n := len(p.items)
	for i := p.sel + delta; i >= 0 && i < n; i += delta {
		if !p.items[i].header {
			p.sel = i
			return
		}
	}
}

func (a *App) menu(title string, items []menuItem) {
	p := &popup{title: title, kind: "menu", items: items}
	for i, it := range items {
		if !it.header {
			p.sel = i
			break
		}
	}
	a.popup = p
}

func (a *App) message(title, text string, isError bool) {
	a.popup = &popup{title: title, kind: "message", text: text, error: isError}
}

func (a *App) inputPopup(title, hint string, multiline bool, submit func(string)) {
	a.popup = &popup{title: title, kind: "input", input: true, multiline: multiline, submit: submit, hint: hint}
}

func (a *App) closePopup() {
	a.popup = nil
	_ = a.g.DeleteView(vPad)
	_ = a.g.DeleteView(vPopup)
	_ = a.g.DeleteView(vInput)
}

// popupWidth is lazygit's getPopupPanelWidth(90): 4/7 of the screen, at least 80, at most 90.
func popupWidth(maxX int) int {
	w := min(4*maxX/7, 90)
	if w < 80 {
		w = min(maxX-2, 80)
	}
	return w
}

// popupBox is lazygit's getPopupPanelDimensionsAux: centered, at most 3/4 of the height.
func popupBox(maxX, maxY, width, contentHeight int) (int, int, int, int) {
	h := min(contentHeight+2, maxY*3/4)
	return maxX/2 - width/2, maxY/2 - h/2 - h%2, maxX/2 + width/2 - 1, maxY/2 + h/2 - 1
}

// padPopup blanks the column left of a popup. A wide character (Japanese) of the view under it that
// starts there would cover the popup's left frame: blanking its first half drops it whole.
func (a *App) padPopup(g *gocui.Gui, x0, y0, y1 int) error {
	v, err := g.SetView(vPad, x0-2, y0-1, x0, y1+1, 0)
	if err != nil && !isNew(err) {
		return err
	}
	v.Frame = false
	v.Clear()
	fmt.Fprint(v, strings.Repeat(" \n", y1-y0+1))
	_, err = g.SetViewOnTop(vPad)
	return err
}

func (a *App) layoutPopup(g *gocui.Gui, maxX, maxY int) error {
	p := a.popup
	if p == nil {
		_ = g.DeleteView(vPopup)
		_ = g.DeleteView(vInput)
		_ = g.DeleteView(vPad)
		return nil
	}
	width := popupWidth(maxX)
	switch p.kind {
	case "input":
		_ = g.DeleteView(vPopup)
		h := 1
		if p.multiline {
			h = 8
		}
		x0, y0, x1, y1 := popupBox(maxX, maxY, width, h)
		if err := a.padPopup(g, x0, y0, y1); err != nil {
			return err
		}
		v, err := g.SetView(vInput, x0, y0, x1, y1, 0)
		if err != nil && !isNew(err) {
			return err
		}
		if isNew(err) {
			v.Editable = true
			v.Wrap = true
			v.Editor = gocui.EditorFunc(a.editInput)
		}
		a.styleView(v)
		v.Title = p.title
		v.Subtitle = p.hint
		_, err = g.SetViewOnTop(vInput)
		return err
	}
	_ = g.DeleteView(vInput)
	var lines []string
	switch p.kind {
	case "menu":
		keyW := 0
		for _, it := range p.items {
			keyW = max(keyW, runewidth.StringWidth(it.key))
		}
		for _, it := range p.items {
			if it.header {
				lines = append(lines, render.Bold(render.Fg, it.desc))
				continue
			}
			pad := strings.Repeat(" ", keyW-runewidth.StringWidth(it.key))
			lines = append(lines, render.Color(render.Cyan, it.key)+pad+" "+it.desc)
		}
	case "message":
		for _, l := range strings.Split(p.text, "\n") {
			lines = append(lines, render.Bold(render.Fg, l))
		}
	}
	x0, y0, x1, y1 := popupBox(maxX, maxY, width, len(lines))
	if err := a.padPopup(g, x0, y0, y1); err != nil {
		return err
	}
	v, err := g.SetView(vPopup, x0, y0, x1, y1, 0)
	if err != nil && !isNew(err) {
		return err
	}
	a.styleView(v)
	v.Wrap = p.kind == "message"
	v.Title = p.title
	v.Highlight = p.kind == "menu"
	v.Subtitle = ""
	v.Footer = ""
	if p.error {
		v.FrameColor, v.TitleColor = rgb(render.Red), rgb(render.Red)
	}
	v.Clear()
	fmt.Fprint(v, strings.Join(lines, "\n"))
	if p.kind == "menu" {
		v.FocusPoint(0, p.sel, true)
		n := 0
		at := 0
		for i, it := range p.items {
			if !it.header {
				n++
				if i <= p.sel {
					at = n
				}
			}
		}
		v.Footer = fmt.Sprintf("%d of %d", at, n)
	}
	_, err = g.SetViewOnTop(vPopup)
	return err
}

// popupKey handles a key while a menu or a message is open.
func (a *App) popupKey(k keyPress) {
	p := a.popup
	switch p.kind {
	case "message":
		if k.named == "Enter" || k.named == "Esc" || k.ch == 'q' {
			a.closePopup()
		}
		return
	case "menu":
		switch {
		case k.named == "Esc" || k.ch == 'q':
			a.closePopup()
		case k.ch == 'j' || k.named == "Down":
			p.step(1)
		case k.ch == 'k' || k.named == "Up":
			p.step(-1)
		case k.named == "Enter":
			a.runItem(p.items[p.sel])
		default:
			label := string(k.ch)
			if k.named != "" {
				label = keyLabel(k.named)
			}
			for _, it := range p.items {
				if !it.header && it.key == label {
					a.runItem(it)
					return
				}
			}
		}
	}
}

func (a *App) runItem(it menuItem) {
	a.closePopup()
	if it.run != nil {
		it.run()
	}
}

// layoutReply is the reply box under the detail: shown while an item is selected, written in after
// Enter (or r). <c-j> starts a new line, Enter sends, Esc leaves it (SPEC 6.3).
func (a *App) layoutReply(g *gocui.Gui, x0, y0, x1, y1 int, show bool) error {
	if !show {
		a.replying = false
		_ = g.DeleteView(vReply)
		return nil
	}
	v, err := g.SetView(vReply, x0, y0, x1, y1, 0)
	if err != nil && !isNew(err) {
		return err
	}
	if isNew(err) {
		v.Editable = true
		v.Wrap = true
		v.Editor = gocui.EditorFunc(a.editInput)
	}
	a.styleView(v)
	v.Title = "返事"
	if sel := a.model.Selected(); sel != nil && a.replyFor != sel.ID && !a.replying {
		v.ClearTextArea()
		a.replyFor = sel.ID
	}
	if a.replying {
		v.Subtitle = " 送る: <enter> | 改行: <c-j> | 抜ける: <esc> "
	} else {
		v.Subtitle = " <enter> で書く "
	}
	return nil
}
