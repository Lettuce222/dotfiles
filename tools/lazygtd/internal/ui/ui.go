// Package ui is lazygtd's screen, on gocui (the fork lazygit uses): the boxes of the lists on the
// left, the selected item on the right, the keys on the bottom line. It keeps no item of its own:
// it reads gtd.py json, writes each change with one gtd.py command (--by user), and reads again
// when the files change, whoever changed them.
package ui

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/jesseduffield/gocui"
	"github.com/mattn/go-runewidth"

	"github.com/Lettuce222/lazygtd/internal/desk"
	"github.com/Lettuce222/lazygtd/internal/gtd"
	"github.com/Lettuce222/lazygtd/internal/render"
	"github.com/Lettuce222/lazygtd/internal/watch"
)

const (
	vDetail = "detail"
	vKeys   = "keys"
	vInput  = "input"
	vPopup  = "popup"
	// An item shown this long with an answer of the orchestrator not read yet is read (gtd.py read).
	readAfter = 800 * time.Millisecond
	toastFor  = 5 * time.Second
	// A reply goes as one line (gtd.py say), at most this long, as on the desk.
	replyMax = 2000
	titleMax = 300
)

type mode int

const (
	mList mode = iota
	mG
	mMenu  // where to move (f)
	mDeliv // which deliverable (d)
	mHelp
	mInput // reply, add or filter
)

// App is the running screen.
type App struct {
	g     *gocui.Gui
	gtd   *gtd.Client
	model *desk.Model
	root  string // GTD_HOME

	mode      mode
	inputKind string // reply, add, filter
	inputFor  string // the item a reply is for
	menuFor   string // the item the menu is for
	delivSel  int

	toast   string
	toastAt time.Time
	busy    map[string]bool // items with a write running: a key pressed twice does not write twice
	loadErr string

	detailFor string // the item the detail shows, to keep its scroll
	readTimer *time.Timer

	mu       sync.Mutex
	loading  bool
	loadMore bool
}

// Run starts the screen and returns when the user quits.
func Run(client *gtd.Client) error {
	g, err := gocui.NewGui(gocui.NewGuiOpts{OutputMode: gocui.OutputTrue, SupportOverlaps: false})
	if err != nil {
		return err
	}
	defer g.Close()
	a, err := newApp(g, client)
	if err != nil {
		return err
	}
	stop, err := watch.Start(a.root, a.reload, func(err error) { a.flash("ファイルの見張りでエラー: " + err.Error()) })
	if err != nil {
		a.flash("ファイルの変化を見張れない（Ctrl+R で読み直す）: " + err.Error())
	} else {
		defer stop()
	}
	go a.tick()
	err = g.MainLoop()
	if errors.Is(err, gocui.ErrQuit) {
		return nil
	}
	return err
}

// newApp sets the screen up on g and reads the items once, before anything is drawn, so that the
// watcher knows the root.
func newApp(g *gocui.Gui, client *gtd.Client) (*App, error) {
	a := &App{g: g, gtd: client, model: desk.New(), busy: map[string]bool{}}
	g.Mouse = true
	g.Cursor = false
	g.InputEsc = true
	g.BgColor = rgb(render.Bg)
	g.FgColor = rgb(render.Fg)
	g.FrameColor = rgb(render.Rule)
	g.SelFrameColor = rgb(render.Focus)
	g.SetManagerFunc(a.layout)
	if err := a.bind(); err != nil {
		return nil, err
	}
	s, err := client.State()
	if err != nil {
		return nil, fmt.Errorf("gtd.py json: %w", err)
	}
	a.model.SetState(s)
	a.root = s.Root
	return a, nil
}

// isNew tells whether SetView made the view just now. gocui wraps ErrUnknownView with go-errors,
// which errors.Is does not see through, so the message is compared (as lazygit does).
func isNew(err error) bool {
	return err != nil && err.Error() == gocui.ErrUnknownView.Error()
}

func rgb(hex string) gocui.Attribute {
	r, g, b := render.RGB(hex)
	return gocui.NewRGBColor(r, g, b)
}

func (a *App) itemsDir() string { return filepath.Join(a.root, "items") }

// tick redraws while a toast is up, so that it goes away.
func (a *App) tick() {
	for range time.Tick(time.Second) {
		if a.toast != "" && time.Since(a.toastAt) > toastFor {
			a.g.Update(func(*gocui.Gui) error { a.toast = ""; return nil })
		}
	}
}

// flash shows a line on the bottom line for a while.
func (a *App) flash(msg string) {
	a.g.Update(func(*gocui.Gui) error {
		a.toast, a.toastAt = msg, time.Now()
		return nil
	})
}

// reload reads gtd.py json again; reads asked for while one runs come as one more read after it.
func (a *App) reload() {
	a.mu.Lock()
	if a.loading {
		a.loadMore = true
		a.mu.Unlock()
		return
	}
	a.loading = true
	a.mu.Unlock()
	go func() {
		for {
			s, err := a.gtd.State()
			a.g.Update(func(*gocui.Gui) error {
				if err != nil {
					a.loadErr = "読めなかった: " + err.Error()
				} else {
					a.loadErr = ""
					a.model.SetState(s)
				}
				return nil
			})
			a.mu.Lock()
			if !a.loadMore {
				a.loading = false
				a.mu.Unlock()
				return
			}
			a.loadMore = false
			a.mu.Unlock()
		}
	}()
}

// write runs one gtd.py write for an item away from the screen's loop, then reads again. A conflict
// (exit 3) is read again first and then told, so that what the user sees is what changed.
func (a *App) write(id, done string, f func() error) {
	if id != "" {
		if a.busy[id] {
			return
		}
		a.busy[id] = true
	}
	go func() {
		err := f()
		a.g.Update(func(*gocui.Gui) error {
			delete(a.busy, id)
			return nil
		})
		switch {
		case gtd.IsConflict(err):
			s, rerr := a.gtd.State()
			a.g.Update(func(*gocui.Gui) error {
				if rerr == nil {
					a.model.SetState(s)
				}
				a.toast, a.toastAt = "ぶつかった: ほかの人が先に直していた。読み直したので、確かめてからもう一度", time.Now()
				return nil
			})
		case err != nil:
			a.flash("書けなかった: " + err.Error())
			a.reload()
		default:
			if done != "" {
				a.flash(done)
			}
			a.reload()
		}
	}()
}

// ---------------------------------------------------------------- layout

func (a *App) layout(g *gocui.Gui) error {
	maxX, maxY := g.Size()
	leftW := max(min(maxX*2/5, 80), min(36, maxX/2))
	bottom := maxY - 2 // the last row is the keys line

	// The left column.
	rows := make([]int, len(desk.Boxes))
	focus := max(desk.BoxIndex(a.model.Cur), 0)
	for i, b := range desk.Boxes {
		rows[i] = len(a.model.Rows(b.ID))
	}
	heights := BoxHeights(rows, focus, bottom+1, desk.SmallRows)
	y := 0
	for i, b := range desk.Boxes {
		h := heights[i]
		v, err := g.SetView("box:"+b.ID, 0, y, leftW-1, y+h-1, 0)
		if err != nil && !isNew(err) {
			return err
		}
		a.drawBox(v, b, i == focus, h-2)
		y += h
	}

	// The right column: the detail, and the input under it while writing.
	detailBottom := bottom
	if a.mode == mInput {
		h := 3
		if a.inputKind == "reply" {
			h = 6
		}
		detailBottom = bottom - h
		v, err := g.SetView(vInput, leftW, detailBottom+1, maxX-1, bottom, 0)
		if err != nil && !isNew(err) {
			return err
		}
		if isNew(err) {
			v.Editable = true
			v.Wrap = true
			v.Editor = gocui.EditorFunc(a.edit)
		}
		v.Frame = true
		v.FrameColor = rgb(render.Focus)
		v.TitleColor = rgb(render.Focus)
		v.BgColor, v.FgColor = rgb(render.Bg), rgb(render.Fg)
		v.Title = map[string]string{
			"reply":  " 返事（「あなたの番への返事」に足し、窓口の答えを待つ印を付ける） ",
			"add":    " inbox に足す（1 行） ",
			"filter": " 絞り込み: " + a.boxLabel(a.model.Cur) + " ",
		}[a.inputKind]
		if _, err := g.SetCurrentView(vInput); err != nil {
			return err
		}
	} else {
		_ = g.DeleteView(vInput)
		if _, err := g.SetCurrentView("box:" + a.model.Cur); err != nil {
			return err
		}
	}
	dv, err := g.SetView(vDetail, leftW, 0, maxX-1, detailBottom, 0)
	if err != nil && !isNew(err) {
		return err
	}
	a.drawDetail(dv)

	kv, err := g.SetView(vKeys, 0, maxY-2, maxX, maxY, 0)
	if err != nil && !isNew(err) {
		return err
	}
	kv.Frame = false
	a.drawKeys(kv)

	return a.layoutPopup(g, maxX, maxY)
}

func (a *App) boxLabel(id string) string {
	if i := desk.BoxIndex(id); i >= 0 {
		return desk.Boxes[i].Label
	}
	return id
}

func (a *App) drawBox(v *gocui.View, b desk.Box, focused bool, inner int) {
	all := a.model.AllRows(b.ID)
	rows := a.model.Rows(b.ID)
	v.Frame = true
	v.BgColor, v.FgColor = rgb(render.Bg), rgb(render.Fg)
	v.SelBgColor = rgb(render.Sel)
	v.SelFgColor = rgb(render.Fg)
	count := fmt.Sprintf("%d", len(all))
	if f := a.model.Filters[b.ID]; f != "" {
		count = fmt.Sprintf("%d/%d", len(rows), len(all))
		v.Subtitle = " /" + f + " "
	} else {
		v.Subtitle = ""
	}
	v.Title = fmt.Sprintf("[%c] %s (%s)", b.Key, b.Label, count)
	if b.ID == "talk" && hasUnread(all) {
		v.Title += " ●"
	}
	if focused {
		v.FrameColor, v.TitleColor = rgb(render.Focus), rgb(render.Focus)
	} else {
		v.FrameColor, v.TitleColor = rgb(render.Rule), rgb(render.Muted)
	}
	v.Highlight = focused && len(rows) > 0
	v.Clear()
	if len(rows) == 0 {
		fmt.Fprintln(v, render.Color(render.Dim, "（なし）"))
		v.SetOrigin(0, 0)
		return
	}
	shown := rows
	if !focused && len(shown) > inner {
		// The first rows, and how many more on the last line, as the desk's "… ほか N 件".
		if inner >= 1 {
			shown = rows[:max(inner-1, 0)]
		} else {
			shown = nil
		}
	}
	for _, it := range shown {
		fmt.Fprintln(v, render.Row(it, b.ID, a.model.State.Today))
	}
	if len(shown) < len(rows) {
		fmt.Fprint(v, render.Color(render.Dim, fmt.Sprintf("… ほか %d 件（%c）", len(rows)-len(shown), b.Key)))
	}
	if focused {
		v.FocusPoint(0, a.model.SelectedIndex(b.ID), true)
	} else {
		v.SetOrigin(0, 0)
	}
}

func hasUnread(rows []*gtd.Item) bool {
	for _, r := range rows {
		if r.Unread() {
			return true
		}
	}
	return false
}

func (a *App) drawDetail(v *gocui.View) {
	v.Frame = true
	v.Wrap = true
	v.BgColor, v.FgColor = rgb(render.Bg), rgb(render.Fg)
	v.FrameColor, v.TitleColor = rgb(render.Rule), rgb(render.Muted)
	it := a.model.Selected()
	v.Clear()
	if it == nil {
		v.Title = " 詳細 "
		a.detailFor = ""
		fmt.Fprintln(v, render.Color(render.Dim, "（この箱に項目は無い）"))
		if i := desk.BoxIndex(a.model.Cur); i >= 0 {
			fmt.Fprintln(v, "\n"+render.Color(render.Muted, desk.Boxes[i].Hint))
		}
		return
	}
	v.Title = " " + it.ID + " "
	if a.detailFor != it.ID+it.Hash {
		// Another item, or the item changed: from its top.
		if a.detailFor == "" || !strings.HasPrefix(a.detailFor, it.ID) {
			v.SetOrigin(0, 0)
		}
		a.detailFor = it.ID + it.Hash
		a.scheduleRead(it)
	}
	w, _ := v.InnerSize()
	fmt.Fprint(v, render.Detail(it, a.model, w))
}

// scheduleRead reads the orchestrator's answers to an item that stays shown for a moment.
func (a *App) scheduleRead(it *gtd.Item) {
	if a.readTimer != nil {
		a.readTimer.Stop()
	}
	if !it.Unread() {
		return
	}
	id := it.ID
	a.readTimer = time.AfterFunc(readAfter, func() {
		a.g.Update(func(*gocui.Gui) error {
			cur := a.model.Selected()
			if cur == nil || cur.ID != id || !cur.Unread() || a.busy[id] {
				return nil
			}
			a.write(id, "", func() error { return a.gtd.Read(id) })
			return nil
		})
	})
}

func (a *App) drawKeys(v *gocui.View) {
	v.Clear()
	v.BgColor, v.FgColor = rgb(render.Bg), rgb(render.Fg)
	if a.toast != "" {
		fmt.Fprint(v, render.Color(render.Orange, a.toast))
		return
	}
	if a.loadErr != "" {
		fmt.Fprint(v, render.Color(render.Red, a.loadErr))
		return
	}
	kind := ""
	switch a.mode {
	case mInput:
		kind = a.inputKind
	case mMenu:
		kind = "menu"
	case mDeliv:
		kind = "deliv"
	}
	var parts []string
	for _, h := range desk.Hints(kind) {
		parts = append(parts, render.Color(render.Blue, h[0])+" "+render.Color(render.Muted, h[1]))
	}
	if a.mode == mG {
		parts = []string{render.Color(render.Blue, "g") + " " + render.Color(render.Muted, "y i n p w s r（リストの頭文字）")}
	}
	fmt.Fprint(v, strings.Join(parts, render.Color(render.Rule, " │ ")))
}

func (a *App) layoutPopup(g *gocui.Gui, maxX, maxY int) error {
	var title string
	var lines []string
	switch a.mode {
	case mMenu:
		it := a.model.Item(a.menuFor)
		if it == nil {
			a.mode = mList
			break
		}
		title = " 移す先 "
		for _, t := range desk.MoveTo {
			mark := ""
			if t.List == it.List {
				mark = render.Color(render.Dim, "（今ここ）")
			}
			lines = append(lines, fmt.Sprintf(" %s  %s%s", render.Color(render.Blue, string(t.Key)), t.Label, mark))
		}
	case mDeliv:
		it := a.model.Item(a.menuFor)
		if it == nil || len(it.Deliverables) == 0 {
			a.mode = mList
			break
		}
		title = " 成果物を開く "
		for i, d := range it.Deliverables {
			n := " "
			if i < 9 {
				n = fmt.Sprintf("%d", i+1)
			}
			lines = append(lines, fmt.Sprintf(" %s  %s", render.Color(render.Blue, n), d))
		}
	case mHelp:
		title = " キー（Esc か ? で閉じる） "
		for _, h := range desk.Help {
			lines = append(lines, fmt.Sprintf(" %s  %s", render.Color(render.Blue, padRight(h[0], 20)), h[1]))
		}
	}
	if title == "" {
		_ = g.DeleteView(vPopup)
		return nil
	}
	w := min(maxX-4, 90)
	h := min(len(lines)+2, maxY-4)
	x0, y0 := (maxX-w)/2, (maxY-h)/2
	v, err := g.SetView(vPopup, x0, y0, x0+w, y0+h-1, 0)
	if err != nil && !isNew(err) {
		return err
	}
	v.Frame = true
	v.Title = title
	v.BgColor, v.FgColor = rgb(render.Bg), rgb(render.Fg)
	v.FrameColor, v.TitleColor = rgb(render.Focus), rgb(render.Focus)
	v.SelBgColor = rgb(render.Sel)
	v.Highlight = a.mode == mDeliv
	v.Clear()
	fmt.Fprint(v, strings.Join(lines, "\n"))
	if a.mode == mDeliv {
		v.FocusPoint(0, a.delivSel, true)
	}
	if _, err := g.SetViewOnTop(vPopup); err != nil {
		return err
	}
	_, err = g.SetCurrentView(vPopup)
	return err
}

// padRight pads s to n columns, a wide character counting two.
func padRight(s string, n int) string {
	return s + strings.Repeat(" ", max(n-runewidth.StringWidth(s), 1))
}
