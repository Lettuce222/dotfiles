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
	"github.com/mattn/go-runewidth"
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
	Purple = "#bb9af7"
	Red    = "#f7768e"
	Cyan   = "#7dcfff"
	// Dim is the faint text. SPEC 5.2 keeps it readable: the same as Muted, never #4e5575.
	Dim = Muted
	// Yellow is kept for the orchestrator's questions and approvals (SPEC 5.2); a due date that
	// comes soon and why an item is the user's turn take TokyoNight's orange.
	Yellow = "#e0af68"
	Soon   = "#ff9e64"
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
			c = Soon
		}
	}
	return Color(c, MMDD(due))
}

// Chips are the marks of a row: the talk, why it is in あなたの番, who does it, its due date. They
// come before the title, so that a long title cut at the box's edge does not hide them.
func Chips(it *gtd.Item, box, today string) []string {
	var out []string
	if it.Unread() {
		out = append(out, Color(Blue, "●窓口の返事"))
	} else if it.Waiting() {
		out = append(out, Color(Muted, "…答え待ち"))
	}
	if m := gtd.S(it.Mine); m != "" && box == "mine" {
		label := desk.MineLabel[m]
		if label == "" {
			label = m
		}
		out = append(out, Color(Soon, label))
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

// Row is the line of an item in a list, as lazygit's rows of branches and commits: a short date
// column (the due date in color, else how long ago it came, dim, as a branch's recency), a mark
// column (● an answer not read, … waiting for one, ◆ an agent's), the title, then dim words (why
// it is the user's turn, who is waited for, the project). key is the list key the row is in.
func Row(it *gtd.Item, key, today string) string {
	var b strings.Builder
	b.WriteString(dateCol(it, today) + " ")
	switch {
	case it.Unread():
		b.WriteString(Color(Blue, "●"))
	case it.Waiting():
		b.WriteString(Color(Muted, "…"))
	case it.IsAgent() && gtd.S(it.Actor) != "me":
		b.WriteString(Color(Purple, "◆"))
	default:
		b.WriteString(" ")
	}
	b.WriteString(" ")
	title := it.Title
	if strings.HasPrefix(key, desk.StepsPrefix) {
		switch it.List {
		case "done":
			title = Color(Dim, "✓ "+title)
		case "next":
			title = Color(Green, "▶ ") + title
		case "waiting":
			title = Color(Muted, "… ") + title
		default:
			title = Color(Dim, "· ") + title
		}
	} else if it.List == "done" {
		title = Color(Dim, title)
	}
	b.WriteString(title)
	var tail []string
	if m := gtd.S(it.Mine); m != "" && key == "mine" {
		label := desk.MineLabel[m]
		if label == "" {
			label = m
		}
		tail = append(tail, Color(Soon, label))
	}
	if it.List == "waiting" && gtd.S(it.Who) != "" {
		tail = append(tail, Color(Muted, gtd.S(it.Who)))
	}
	if it.List == "project" && len(it.Steps) > 0 {
		tail = append(tail, Color(Muted, fmt.Sprintf("%d ステップ", len(it.Steps))))
	}
	if w := gtd.S(it.Worker); w != "" && key != "mine" {
		tail = append(tail, Color(Purple, w))
	}
	if len(tail) > 0 {
		b.WriteString(" " + strings.Join(tail, " "))
	}
	return b.String()
}

// dateCol is the row's first column, five wide.
func dateCol(it *gtd.Item, today string) string {
	if d := gtd.S(it.Due); d != "" {
		return dueChip(d, today)
	}
	if it.List == "waiting" && gtd.S(it.FollowUp) != "" {
		f := gtd.S(it.FollowUp)
		c := Muted
		if f < today {
			c = Red
		} else if f == today {
			c = Soon
		}
		return Color(c, MMDD(f))
	}
	since := gtd.S(it.Since)
	if it.List == "done" && gtd.S(it.Done) != "" {
		since = gtd.S(it.Done)
	}
	a := age(since, today)
	return Color(Dim, strings.Repeat(" ", max(5-runewidth.StringWidth(a), 0))+a)
}

// age is how long ago a date was, as lazygit's recency ("3d", "2w").
func age(d, today string) string {
	t1, err1 := time.Parse("2006-01-02", d[:min(10, len(d))])
	t2, err2 := time.Parse("2006-01-02", today)
	if err1 != nil || err2 != nil {
		return ""
	}
	days := int(t2.Sub(t1).Hours() / 24)
	switch {
	case days <= 0:
		return "今日"
	case days < 14:
		return fmt.Sprintf("%dd", days)
	case days < 60:
		return fmt.Sprintf("%dw", days/7)
	}
	return fmt.Sprintf("%dm", days/30)
}

// Detail is the right box's text for an item: its title, its fields, its steps, deliverables and
// links, then its body as Markdown wrapped to width.
func Detail(it *gtd.Item, m *desk.Model, width int) string {
	var b strings.Builder
	b.WriteString(Bold(Fg, it.Title) + "\n")
	if chips := Chips(it, m.Cur(), m.State.Today); len(chips) > 0 {
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
					mark = Color(Soon, "あなたの番")
				default:
					mark = Color(Green, "次の行動")
				}
			}
			fmt.Fprintf(&b, "%s %s %s\n", Color(Dim, fmt.Sprintf("%2d.", i+1)), title, mark)
		}
	}
	if len(it.Deliverables) > 0 {
		b.WriteString("\n" + Bold(Blue, "成果物") + Color(Dim, "（o で開く）") + "\n")
		for _, d := range it.Deliverables {
			b.WriteString("  " + d + "\n")
		}
	}
	b.WriteString("\n" + Color(Rule, strings.Repeat("─", max(width-1, 10))) + "\n")
	if strings.TrimSpace(it.Body) == "" {
		b.WriteString(Color(Dim, "（本文なし）") + "\n")
	} else {
		// The talk with the orchestrator, in the order it was said, after the rest (SPEC 5.5).
		rest, talk := SplitTalk(it.Body)
		b.WriteString(Markdown(strings.TrimSpace(rest+"\n\n"+TalkMarkdown(talk)), width))
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
