// Package ui is lazygtd's screen, on gocui (the fork lazygit uses), laid out and drawn as lazygit
// is: five numbered side panels with tabs on the left, the detail of the selected item as the main
// view on the right, the options line at the bottom, popups in the middle. It keeps no item of its
// own: it reads gtd.py json, writes each change with one gtd.py command (--by user), and reads
// again when the files change, whoever changed them.
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

// Version is shown at the right of the options line, as lazygit's.
var Version = "0.3.0"

const (
	vMain    = "main"
	vOptions = "options"
	vFilterL = "filterPrefix"
	vFilter  = "filter"
	vPopup   = "popup"
	vInput   = "input"
	vPad     = "popupPad"
	vReply   = "reply"
	// The reply box: its frame and three rows.
	replyHeight = 5
	// An item shown this long with an answer of the orchestrator not read yet is read (gtd.py read).
	readAfter = 800 * time.Millisecond
	toastFor  = 4 * time.Second
	replyMax  = 2000
	titleMax  = 300
)

// The frame of lazygit's default border, "rounded".
var frameRunes = []rune{'─', '│', '╭', '╮', '╰', '╯'}

func panelView(i int) string { return fmt.Sprintf("panel%d", i+1) }

// App is the running screen.
type App struct {
	g     *gocui.Gui
	gtd   *gtd.Client
	model *desk.Model
	root  string // GTD_HOME

	screen    int    // 0 normal, 1 half, 2 full (lazygit's + and _)
	replying  bool   // the reply box under the detail is being written in
	replyFor  string // the item the reply box is for
	filtering bool   // the filter's input is open
	popup     *popup // a menu, an input or a message
	busy      map[string]bool

	toast    string
	toastAt  time.Time
	toastErr bool // the toast is an error (red)
	loadErr  string

	detailFor string // the item the detail shows, to keep its scroll
	readTimer *time.Timer

	mu       sync.Mutex
	loading  bool
	loadMore bool
	running  sync.WaitGroup // the writes and reads under way (the tests wait for them)
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
	stop, err := watch.Start(a.root, a.reload, func(err error) { a.flash("ファイルの監視でエラー: " + err.Error()) })
	if err != nil {
		a.flash("ファイルの変化を監視できない（R で読み直す）: " + err.Error())
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

// newApp sets the screen up on g as lazygit's setColorScheme does, and reads the items once,
// before anything is drawn, so that the watcher knows the root.
func newApp(g *gocui.Gui, client *gtd.Client) (*App, error) {
	a := &App{g: g, gtd: client, model: desk.New(), busy: map[string]bool{}}
	g.Mouse = true
	g.Cursor = false
	g.InputEsc = true
	g.Highlight = true // the current view's frame in SelFrameColor
	g.ShowListFooter = true
	// TokyoNight Storm (SPEC 5.2) in lazygit's roles: the other frames in the text's color.
	g.FgColor = rgb(render.Fg)
	g.BgColor = rgb(render.Bg)
	g.FrameColor = rgb(render.Fg)
	g.SelBgColor = rgb(render.Bg) // the background of the current view's frame
	a.setSearching(false)
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

// setSearching colors the current view's frame and tab: green, cyan while filtering (lazygit's
// activeBorderColor and searchingActiveBorderColor).
func (a *App) setSearching(on bool) {
	c := rgb(render.Focus)
	if on {
		c = rgb(render.Cyan)
	}
	a.g.SelFgColor = c | gocui.AttrBold
	a.g.SelFrameColor = c | gocui.AttrBold
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

// flash shows a word at the right of the options line for a while (lazygit's app status).
func (a *App) flash(msg string) {
	a.g.Update(func(*gocui.Gui) error {
		a.toast, a.toastAt, a.toastErr = msg, time.Now(), false
		return nil
	})
}

// flashErr shows an error at the right of the options line (SPEC 4.4: the bottom line tells).
func (a *App) flashErr(msg string) {
	a.g.Update(func(*gocui.Gui) error {
		a.toast, a.toastAt, a.toastErr = msg, time.Now(), true
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
	a.running.Add(1)
	go func() {
		defer a.running.Done()
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
// (exit 3) is read again first and then told in a popup, so that what the user sees is what changed.
func (a *App) write(id, done string, f func() error) {
	if id != "" {
		if a.busy[id] {
			return
		}
		a.busy[id] = true
	}
	a.running.Add(1)
	go func() {
		defer a.running.Done()
		err := f()
		var fresh *gtd.State
		var rerr error
		if err != nil {
			fresh, rerr = a.gtd.State()
		}
		// One update: the item is free again in the same turn as the result is shown.
		a.g.UpdateAsync(func(*gocui.Gui) error {
			delete(a.busy, id)
			switch {
			case err == nil:
				if done != "" {
					a.toast, a.toastAt, a.toastErr = done, time.Now(), false
				}
			default:
				// Read again first, then tell on the bottom line (SPEC 4.4).
				if rerr == nil {
					a.model.SetState(fresh)
				}
				msg := "書けなかった: " + err.Error()
				if gtd.IsConflict(err) {
					msg = "ぶつかった: ほかの人（エージェントかもしれない）が先に直していた。読み直したので、確かめてからもう一度"
				}
				a.toast, a.toastAt, a.toastErr = msg, time.Now(), true
			}
			return nil
		})
		if err == nil {
			a.reload()
		}
	}()
}

// ctx is the context the keys are looked up in.
func (a *App) ctx() string {
	switch {
	case a.model.Main:
		return "main"
	case a.model.Steps(a.model.Panel) != "":
		return "steps"
	}
	return "list"
}

// ---------------------------------------------------------------- layout

// PanelHeights split the column's height among the panels equally, the first ones taking what is
// left over, and never change with the focus (lazygit's expandFocusedSidePanel: false).
func PanelHeights(n, total int) []int {
	out := make([]int, n)
	for i := range out {
		out[i] = total / n
		if i < total%n {
			out[i]++
		}
	}
	return out
}

func (a *App) layout(g *gocui.Gui) error {
	maxX, maxY := g.Size()
	bottom := maxY - 2 // the last row is the options line
	sideW := max(maxX/3, min(32, maxX))
	full := a.screen == 2
	if a.screen == 1 {
		sideW = maxX / 2
	}

	// The side panels.
	heights := PanelHeights(len(desk.Panels), bottom+1)
	y := 0
	for i := range desk.Panels {
		x0, y0, x1, y1 := 0, y, sideW-1, y+heights[i]-1
		visible := true
		if a.screen > 0 {
			// Half and full: the current side panel alone, the whole height (or the whole screen).
			visible = i == a.model.Panel && !(full && a.model.Main)
			y0, y1 = 0, bottom
			if full {
				x1 = maxX - 1
			}
		}
		v, err := g.SetView(panelView(i), x0, y0, x1, y1, 0)
		if err != nil && !isNew(err) {
			return err
		}
		v.Visible = visible
		a.drawPanel(v, i)
		y += heights[i]
	}

	mx0 := sideW
	if full {
		mx0 = 0
	}
	mainBottom := bottom
	sel := a.model.Selected()
	showReply := sel != nil && sel.List != "done" && (!full || a.replying)
	if showReply {
		mainBottom = bottom - replyHeight
	}
	mv, err := g.SetView(vMain, mx0, 0, maxX-1, mainBottom, 0)
	if err != nil && !isNew(err) {
		return err
	}
	mv.Visible = !full || a.model.Main
	a.drawMain(mv)
	if err := a.layoutReply(g, mx0, mainBottom+1, maxX-1, bottom, showReply); err != nil {
		return err
	}

	if err := a.layoutBottom(g, maxX, maxY); err != nil {
		return err
	}
	if err := a.layoutPopup(g, maxX, maxY); err != nil {
		return err
	}

	current := panelView(a.model.Panel)
	switch {
	case a.popup != nil && a.popup.input:
		current = vInput
	case a.popup != nil:
		current = vPopup
	case a.filtering:
		current = vFilter
	case a.replying:
		current = vReply
	case a.model.Main:
		current = vMain
	}
	if _, err := g.SetCurrentView(current); err != nil {
		return err
	}
	// The selected row of a panel is drawn bold only, when another view is worked in.
	for i := range desk.Panels {
		if v, err := g.View(panelView(i)); err == nil {
			v.HighlightInactive = !(i == a.model.Panel && !a.model.Main && a.popup == nil)
		}
	}
	return nil
}

func (a *App) styleView(v *gocui.View) {
	v.Frame = true
	v.FrameRunes = frameRunes
	v.FgColor, v.BgColor = rgb(render.Fg), rgb(render.Bg)
	v.FrameColor = rgb(render.Fg)
	v.TitleColor = rgb(render.Fg)
	// The selected row: text and background reversed in the view worked in, #364a82 in the others.
	v.SelBgColor = rgb(render.Fg)
	v.SelFgColor = a.g.SelFgColor
	v.InactiveViewSelBgColor = rgb(render.Sel)
}

func (a *App) drawPanel(v *gocui.View, i int) {
	a.styleView(v)
	m := a.model
	key := m.Key(i)
	v.TitlePrefix = fmt.Sprintf("[%d]", i+1)
	if p := m.Steps(i); p != "" {
		v.Tabs = nil
		v.Title = "プロジェクト › " + m.ProjectShort(p)
	} else {
		var tabs []string
		for _, l := range desk.Panels[i] {
			tabs = append(tabs, a.tabLabel(l))
		}
		if len(tabs) > 1 {
			v.Tabs, v.TabIndex = tabs, m.Tab(i)
			v.Title = ""
		} else {
			v.Tabs, v.Title = nil, tabs[0]
		}
	}
	if f := m.Filters[key]; f != "" {
		v.Subtitle = " /" + f + " "
	} else {
		v.Subtitle = ""
	}
	rows := m.Rows(key)
	v.Highlight = len(rows) > 0
	v.Clear()
	sel := m.SelectedIndex(key)
	active := i == m.Panel && !m.Main
	for n, it := range rows {
		line := render.Row(it, key, m.State.Today)
		if active && n == sel {
			// Reversed: the row's own colors would not read on the light background.
			line = render.Color(render.Bg, stripANSI(line))
		}
		fmt.Fprintln(v, line)
	}
	if len(rows) == 0 {
		v.Footer = ""
		v.SetOrigin(0, 0)
		v.SetCursor(0, 0)
		return
	}
	v.Footer = fmt.Sprintf("%d of %d", sel+1, len(rows))
	v.FocusPoint(0, sel, true)
}

// tabLabel is a tab's name and its count, and the answers not read yet of 窓口 (SPEC 5.1).
func (a *App) tabLabel(list string) string {
	label := fmt.Sprintf("%s (%d)", desk.Label(list), len(a.model.AllRows(list)))
	switch list {
	case "talk":
		unread := 0
		for _, it := range a.model.AllRows("talk") {
			if it.Unread() {
				unread++
			}
		}
		if unread > 0 {
			label += fmt.Sprintf(" ●%d", unread)
		}
	}
	return label
}

func (a *App) drawMain(v *gocui.View) {
	a.styleView(v)
	v.Wrap = true
	v.Highlight = false
	v.TitlePrefix = "[0]"
	v.Title = "詳細"
	v.Footer = ""
	it := a.model.Selected()
	v.Clear()
	if it == nil {
		a.detailFor = ""
		v.Subtitle = ""
		fmt.Fprintln(v, render.Color(render.Dim, "（この箱に項目は無い）"))
		if l, ok := desk.Lists[a.model.Cur()]; ok {
			fmt.Fprintln(v, "\n"+render.Color(render.Muted, l.Hint))
		}
		return
	}
	v.Subtitle = " " + it.ID + " "
	if a.detailFor != it.ID+it.Hash {
		// Another item: from its top. The same item changed: where it was.
		if !strings.HasPrefix(a.detailFor, it.ID) {
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

// layoutBottom is the options line, or the filter's input in its place (lazygit's search prompt).
func (a *App) layoutBottom(g *gocui.Gui, maxX, maxY int) error {
	ov, err := g.SetView(vOptions, -1, maxY-2, maxX, maxY, 0)
	if err != nil && !isNew(err) {
		return err
	}
	ov.Frame = false
	ov.FgColor, ov.BgColor = rgb(render.Fg), rgb(render.Bg)
	ov.Clear()
	if !a.filtering {
		_ = g.DeleteView(vFilterL)
		_ = g.DeleteView(vFilter)
		fmt.Fprint(ov, a.optionsLine(maxX))
		return nil
	}
	label := "絞り込み: "
	lw := runewidth.StringWidth(label)
	lv, err := g.SetView(vFilterL, -1, maxY-2, lw, maxY, 0)
	if err != nil && !isNew(err) {
		return err
	}
	lv.Frame = false
	lv.Clear()
	fmt.Fprint(lv, render.Color(render.Cyan, label))
	fv, err := g.SetView(vFilter, lw-1, maxY-2, maxX, maxY, 0)
	if err != nil && !isNew(err) {
		return err
	}
	if isNew(err) {
		fv.Editable = true
		fv.Editor = gocui.EditorFunc(a.editFilter)
		if q := a.model.Filters[a.model.Cur()]; q != "" {
			fv.TextArea.TypeString(q)
			fv.RenderTextArea()
		}
	}
	fv.Frame = false
	fv.FgColor, fv.BgColor = rgb(render.Fg), rgb(render.Bg)
	_, _ = g.SetViewOnTop(vFilterL)
	_, err = g.SetViewOnTop(vFilter)
	return err
}

// optionsLine is lazygit's options bar: "description: key" joined by " | " in blue, cut with an
// ellipsis, and the app's status (a toast, an error) at the right.
func (a *App) optionsLine(maxX int) string {
	var pairs [][2]string
	switch {
	case a.popup != nil:
		pairs = a.popup.options()
	default:
		pairs = desk.Options(a.ctx())
	}
	right := ""
	switch {
	case a.toast != "" && a.toastErr:
		right = render.Color(render.Red, a.toast)
	case a.toast != "":
		right = render.Color(render.Green, a.toast)
	case a.loadErr != "":
		right = render.Color(render.Red, a.loadErr)
	case len(a.model.State.Broken) > 0:
		// SPEC 9: which file cannot be read, and why.
		b := a.model.State.Broken[0]
		right = render.Color(render.Red, fmt.Sprintf("読めない項目 %d 件（%s: %s）", len(a.model.State.Broken), filepath.Base(b.Path), b.Error))
	default:
		right = render.Color(render.Dim, "lazygtd "+Version)
	}
	prefix := ""
	if f := a.model.Filters[a.model.Cur()]; f != "" && a.popup == nil {
		prefix = render.Color(render.Cyan, fmt.Sprintf("絞り込み中: '%s'（<esc> で解く）", f)) + render.Color(render.Blue, " | ")
	}
	width := maxX - 2 - runewidth.StringWidth(stripANSI(right)) - runewidth.StringWidth(stripANSI(prefix)) - 2
	var b strings.Builder
	length := 0
	const sep = " | "
	for i, p := range pairs {
		text := p[0] + ": " + p[1]
		w := runewidth.StringWidth(text)
		if i > 0 && length+len(sep)+w > width {
			b.WriteString(render.Color(render.Blue, sep+"…"))
			length += len(sep) + 1
			break
		}
		if i > 0 {
			b.WriteString(render.Color(render.Blue, sep))
			length += len(sep)
		}
		b.WriteString(render.Color(render.Blue, text))
		length += w
	}
	gap := max(maxX-1-runewidth.StringWidth(stripANSI(prefix))-length-runewidth.StringWidth(stripANSI(right)), 1)
	return prefix + b.String() + strings.Repeat(" ", gap) + right
}

// stripANSI drops the escape sequences, to measure a colored text.
func stripANSI(s string) string {
	var b strings.Builder
	in := false
	for _, r := range s {
		switch {
		case r == '\x1b':
			in = true
		case in && (r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z'):
			in = false
		case !in:
			b.WriteRune(r)
		}
	}
	return b.String()
}
