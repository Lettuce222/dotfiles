// Package render turns items into the text of the views: one line per row of a box, and the
// detail of the selected item with its body as terminal Markdown (glamour). Colors are TokyoNight
// Storm, as the browser desk's (desk/desk.css), written as 24-bit ANSI sequences that gocui reads.
package render

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/glamour/styles"
	"github.com/muesli/termenv"

	"github.com/Lettuce222/lazygtd/internal/desk"
	"github.com/Lettuce222/lazygtd/internal/gtd"
)

// TokyoNight Storm (desk/desk.css).
const (
	Bg     = "#24283b"
	Fg     = "#c0caf5"
	Muted  = "#a9b1d6"
	Rule   = "#414868"
	Sel    = "#364a82"
	Focus  = "#9ece6a"
	Blue   = "#7aa2f7"
	Green  = "#9ece6a"
	Orange = "#e0af68"
	Purple = "#bb9af7"
	Red    = "#f7768e"
	Cyan   = "#7dcfff"
	Dim    = "#565f89"
)

// RGB splits "#rrggbb".
func RGB(hex string) (r, g, b int32) {
	fmt.Sscanf(hex, "#%02x%02x%02x", &r, &g, &b)
	return
}

// Color writes s in a color.
func Color(hex, s string) string {
	r, g, b := RGB(hex)
	return fmt.Sprintf("\x1b[38;2;%d;%d;%dm%s\x1b[0m", r, g, b, s)
}

// Bold writes s bold, in a color.
func Bold(hex, s string) string {
	r, g, b := RGB(hex)
	return fmt.Sprintf("\x1b[1;38;2;%d;%d;%dm%s\x1b[0m", r, g, b, s)
}

// MMDD is a date's month and day ("2026-11-28" → "11/28").
func MMDD(d string) string {
	if len(d) >= 10 {
		return d[5:7] + "/" + d[8:10]
	}
	return d
}

func dueChip(due, today string) string {
	if due == "" {
		return ""
	}
	d, err1 := time.Parse("2006-01-02", due[:min(10, len(due))])
	t, err2 := time.Parse("2006-01-02", today)
	c := Muted
	if err1 == nil && err2 == nil {
		switch days := d.Sub(t).Hours() / 24; {
		case days < 0:
			c = Red
		case days <= 2:
			c = Orange
		}
	}
	return Color(c, MMDD(due))
}

// Chips are the marks of a row: the talk, why it is in あなたの番, who does it, its due date. They
// come before the title, so that a long title cut at the box's edge does not hide them.
func Chips(it *gtd.Item, box, today string) []string {
	var out []string
	if it.Unread() {
		out = append(out, Color(Cyan, "●窓口の返事"))
	} else if it.Waiting() {
		out = append(out, Color(Muted, "…答え待ち"))
	}
	if m := gtd.S(it.Mine); m != "" && box == "mine" {
		label := desk.MineLabel[m]
		if label == "" {
			label = m
		}
		out = append(out, Color(Orange, label))
	}
	if it.IsAgent() {
		out = append(out, Color(Purple, "agent"))
	} else if gtd.S(it.Actor) == "me" {
		out = append(out, Color(Muted, "me"))
	}
	if c := dueChip(gtd.S(it.Due), today); c != "" {
		out = append(out, c)
	}
	if it.List == "waiting" && gtd.S(it.FollowUp) != "" && gtd.S(it.FollowUp) < today && gtd.S(it.Mine) != "follow_up" {
		out = append(out, Color(Red, "確かめる日"))
	}
	return out
}

// Row is the line of an item in a box.
func Row(it *gtd.Item, box, today string) string {
	chips := Chips(it, box, today)
	head := ""
	if len(chips) > 0 {
		head = strings.Join(chips, " ") + " "
	}
	return head + it.Title
}

// Detail is the right box's text for an item: its title, its fields, its steps, deliverables and
// links, then its body as Markdown wrapped to width.
func Detail(it *gtd.Item, m *desk.Model, width int) string {
	var b strings.Builder
	b.WriteString(Bold(Fg, it.Title) + "\n")
	if chips := Chips(it, m.Cur, m.State.Today); len(chips) > 0 {
		b.WriteString(strings.Join(chips, " ") + "\n")
	}
	b.WriteString("\n")
	field := func(k, v string) {
		if v != "" {
			b.WriteString(Color(Blue, fmt.Sprintf("%-10s", k)) + v + "\n")
		}
	}
	field("id", it.ID)
	field("list", it.List)
	if p := gtd.S(it.Project); p != "" {
		field("project", m.ProjectShort(p)+Color(Dim, " ("+p+")"))
	}
	for _, kv := range [][2]string{
		{"actor", gtd.S(it.Actor)}, {"worker", gtd.S(it.Worker)}, {"due", gtd.S(it.Due)}, {"since", gtd.S(it.Since)},
		{"done", gtd.S(it.Done)}, {"who", gtd.S(it.Who)}, {"follow_up", gtd.S(it.FollowUp)}, {"then", gtd.S(it.Then)},
		{"outcome", gtd.S(it.Outcome)}, {"short", gtd.S(it.Short)}, {"from", gtd.S(it.From)}, {"source", gtd.S(it.Source)},
	} {
		field(kv[0], kv[1])
	}
	for _, w := range it.Watch {
		field("watch", w)
	}
	for _, l := range it.Links {
		field("links", l)
	}
	if len(it.Steps) > 0 {
		b.WriteString("\n" + Bold(Blue, "ステップ") + "\n")
		for i, id := range it.Steps {
			s := m.Item(id)
			title, mark := id, ""
			if s != nil {
				title = s.Title
				switch {
				case s.List == "done":
					mark, title = Color(Dim, "済"), Color(Dim, title)
				case s.List == "planned":
					mark = Color(Muted, "まだ")
				case s.List == "waiting":
					mark = Color(Muted, "待ち")
				case s.Mine != nil:
					mark = Color(Orange, "あなたの番")
				default:
					mark = Color(Green, "次の行動")
				}
			}
			fmt.Fprintf(&b, "%s %s %s\n", Color(Dim, fmt.Sprintf("%2d.", i+1)), title, mark)
		}
	}
	if len(it.Deliverables) > 0 {
		b.WriteString("\n" + Bold(Blue, "成果物") + Color(Dim, "（d で開く）") + "\n")
		for _, d := range it.Deliverables {
			b.WriteString("  " + d + "\n")
		}
	}
	b.WriteString("\n" + Color(Rule, strings.Repeat("─", max(width-1, 10))) + "\n")
	if strings.TrimSpace(it.Body) == "" {
		b.WriteString(Color(Dim, "（本文なし）") + "\n")
	} else {
		b.WriteString(Markdown(it.Body, width))
	}
	if it.Waiting() {
		b.WriteString("\n" + Color(Muted, "窓口の答えを待っています。") + "\n")
	}
	return b.String()
}

var (
	mdMu    sync.Mutex
	mdCache = map[string]string{}
	mdR     = map[int]*glamour.TermRenderer{}
)

// Markdown renders a body for a terminal of width columns, TokyoNight, kept by body and width so
// that j and k do not render it again.
func Markdown(body string, width int) string {
	width = max(width, 20)
	key := fmt.Sprintf("%d\x00%s", width, body)
	mdMu.Lock()
	defer mdMu.Unlock()
	if out, ok := mdCache[key]; ok {
		return out
	}
	r := mdR[width]
	if r == nil {
		style := styles.TokyoNightStyleConfig
		// The body sits in a framed box already: no margin around the document.
		zero := uint(0)
		style.Document.Margin = &zero
		var err error
		r, err = glamour.NewTermRenderer(
			glamour.WithStyles(style),
			glamour.WithColorProfile(termenv.TrueColor),
			glamour.WithWordWrap(width-1),
		)
		if err != nil {
			return body
		}
		mdR[width] = r
	}
	out, err := r.Render(body)
	if err != nil {
		out = body
	}
	out = strings.Trim(out, "\n") + "\n"
	if len(mdCache) > 500 {
		mdCache = map[string]string{}
	}
	mdCache[key] = out
	return out
}
