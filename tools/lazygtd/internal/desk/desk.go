// Package desk is the state of the screen without the screen: the panels of the left column and
// their tabs, the rows of each list, which row is selected, the filters and the project being
// looked into. It is laid out as lazygit's side panels (five numbered windows, some with tabs:
// lazygit's "Files - Worktrees - Submodules"), with the lists of the browser desk of the Hub
// (local) Orca plugin in them.
package desk

import (
	"strings"

	"github.com/Lettuce222/lazygtd/internal/gtd"
)

// List is a list a tab shows.
type List struct {
	ID    string
	Label string
	Hint  string
}

// Lists are every list a tab can show.
var Lists = map[string]List{
	"mine":      {"mine", "あなたの番", "承認・要判断・確かめてほしいもの"},
	"talk":      {"talk", "窓口", "窓口の返事（まだ読んでいないもの）と、窓口の答えを待っているもの"},
	"inbox":     {"inbox", "inbox", "1 件ずつ何をするか決めて移す（m）。c で足す"},
	"next":      {"next", "次の行動", "自分とエージェント。プロジェクトの「次」もここに出る"},
	"project":   {"project", "プロジェクト", "Enter でステップに入る"},
	"waiting":   {"waiting", "連絡待ち", "相手・渡した日・確かめる日"},
	"someday":   {"someday", "いつか", "今はやらない"},
	"reference": {"reference", "資料", "資料と成果物"},
	"done":      {"done", "完了", "済んだもの。<space> で次の行動に戻す"},
}

// Panels are the windows of the left column, top to bottom, with their tabs; 1〜5 jump to them.
var Panels = [][]string{
	{"mine", "talk"},
	{"inbox"},
	{"next", "project"},
	{"waiting"},
	{"someday", "reference", "done"},
}

// MoveTo are where m moves an item, with the key of each in the menu.
var MoveTo = []struct {
	List, Label string
	Key         rune
}{
	{"inbox", "inbox", 'i'},
	{"next", "次の行動", 'n'},
	{"planned", "プロジェクトのステップ（まだ）", 'p'},
	{"waiting", "連絡待ち", 'w'},
	{"someday", "いつか／たぶん", 's'},
	{"reference", "資料", 'r'},
	{"calendar", "カレンダーに入れる（その旨の次の行動にする）", 'c'},
}

// CalendarPrefix starts the title of an item that is "put it in the calendar" (SPEC 2: lazygtd has
// no calendar; a dated plan is a next action to put it there).
const CalendarPrefix = "カレンダーに入れる: "

// MineLabel names why an item is in あなたの番 (gtd.py json's mine).
var MineLabel = map[string]string{
	"handback": "あなたに戻った", "ask": "問いがある", "agent_done": "完了・確かめて",
	"follow_up": "確かめる日が来た", "due": "締め切り", "conflict": "ぶつかり",
}

// StepsPrefix is the list key of a project's steps ("steps:<project id>"), the list a project's
// panel shows after Enter (lazygit's commit files after Enter on a commit).
const StepsPrefix = "steps:"

// Model is the screen's state.
type Model struct {
	State   *gtd.State
	Panel   int               // the panel worked in
	Main    bool              // the detail (main view) is worked in
	tab     []int             // the tab shown, by panel
	steps   []string          // the project looked into, by panel ("" for none)
	sel     map[string]string // the selected item's id, by list key
	idx     map[string]int    // the selected row's index, by list key (to stay put when the item goes)
	Filters map[string]string // the filter (/) of each list key
	byID    map[string]*gtd.Item
}

// New is the model of an empty desk, with the first panel worked in.
func New() *Model {
	return &Model{
		State: &gtd.State{}, tab: make([]int, len(Panels)), steps: make([]string, len(Panels)),
		sel: map[string]string{}, idx: map[string]int{}, Filters: map[string]string{}, byID: map[string]*gtd.Item{},
	}
}

// Key is the list key a panel shows: its tab's list, or the steps of the project looked into.
func (m *Model) Key(panel int) string {
	if p := m.steps[panel]; p != "" {
		return StepsPrefix + p
	}
	return Panels[panel][m.tab[panel]]
}

// Cur is the list key of the panel worked in.
func (m *Model) Cur() string { return m.Key(m.Panel) }

// Tab is the tab a panel shows.
func (m *Model) Tab(panel int) int { return m.tab[panel] }

// Steps is the project a panel looks into, or "".
func (m *Model) Steps(panel int) string { return m.steps[panel] }

// SetState takes what gtd.py json read. Each list keeps its selected item, or the row at the same
// place when the item left it. A project that is gone is left.
func (m *Model) SetState(s *gtd.State) {
	m.State = s
	m.byID = make(map[string]*gtd.Item, len(s.Items))
	for i := range s.Items {
		m.byID[s.Items[i].ID] = &s.Items[i]
	}
	for p := range Panels {
		if id := m.steps[p]; id != "" && (m.byID[id] == nil || m.byID[id].List != "project") {
			m.steps[p] = ""
		}
	}
	keys := []string{}
	for _, tabs := range Panels {
		keys = append(keys, tabs...)
	}
	for _, id := range m.steps {
		if id != "" {
			keys = append(keys, StepsPrefix+id)
		}
	}
	for _, k := range keys {
		m.keep(k)
	}
}

func (m *Model) keep(key string) {
	rows := m.Rows(key)
	if id, ok := m.sel[key]; ok && indexOf(rows, id) >= 0 {
		m.idx[key] = indexOf(rows, id)
		return
	}
	if len(rows) == 0 {
		delete(m.sel, key)
		return
	}
	i := min(max(m.idx[key], 0), len(rows)-1)
	m.sel[key], m.idx[key] = rows[i].ID, i
}

// Item is the item of an id, or nil.
func (m *Model) Item(id string) *gtd.Item { return m.byID[id] }

func indexOf(rows []*gtd.Item, id string) int {
	for i, r := range rows {
		if r.ID == id {
			return i
		}
	}
	return -1
}

// AllRows are the rows of a list key before its filter.
func (m *Model) AllRows(key string) []*gtd.Item {
	var out []*gtd.Item
	items := m.State.Items
	open := func(it *gtd.Item) bool { return it.List != "done" }
	if strings.HasPrefix(key, StepsPrefix) {
		if p := m.byID[strings.TrimPrefix(key, StepsPrefix)]; p != nil {
			for _, id := range p.Steps {
				if s := m.byID[id]; s != nil {
					out = append(out, s)
				}
			}
		}
		return out
	}
	switch key {
	case "mine":
		for i := range items {
			if items[i].Mine != nil && open(&items[i]) {
				out = append(out, &items[i])
			}
		}
	case "talk":
		for i := range items {
			if open(&items[i]) && items[i].Unread() {
				out = append(out, &items[i])
			}
		}
		for i := range items {
			if open(&items[i]) && !items[i].Unread() && items[i].Waiting() {
				out = append(out, &items[i])
			}
		}
	case "next":
		// The user's own first, then the agents' (desk/desk.mjs ordered).
		var agents []*gtd.Item
		for i := range items {
			it := &items[i]
			if it.List != "next" {
				continue
			}
			if it.IsAgent() && gtd.S(it.Actor) != "me" {
				agents = append(agents, it)
			} else {
				out = append(out, it)
			}
		}
		out = append(out, agents...)
	case "done":
		// The latest first.
		for i := len(items) - 1; i >= 0; i-- {
			if items[i].List == "done" {
				out = append(out, &items[i])
			}
		}
	default:
		for i := range items {
			if items[i].List == key {
				out = append(out, &items[i])
			}
		}
	}
	return out
}

// Rows are the rows of a list key, narrowed by its filter.
func (m *Model) Rows(key string) []*gtd.Item { return Filter(m.AllRows(key), m.Filters[key]) }

// Filter narrows rows to those whose title holds every word of query, case aside.
func Filter(rows []*gtd.Item, query string) []*gtd.Item {
	words := strings.Fields(strings.ToLower(query))
	if len(words) == 0 {
		return rows
	}
	var out []*gtd.Item
	for _, r := range rows {
		t := strings.ToLower(r.Title)
		ok := true
		for _, w := range words {
			if !strings.Contains(t, w) {
				ok = false
				break
			}
		}
		if ok {
			out = append(out, r)
		}
	}
	return out
}

// SelectedIn is the selected item of a list key, or nil.
func (m *Model) SelectedIn(key string) *gtd.Item {
	rows := m.Rows(key)
	if i := indexOf(rows, m.sel[key]); i >= 0 {
		return rows[i]
	}
	if len(rows) > 0 {
		return rows[0]
	}
	return nil
}

// Selected is the selected item of the panel worked in, or nil.
func (m *Model) Selected() *gtd.Item { return m.SelectedIn(m.Cur()) }

// SelectedIndex is the index of the selected row in a list key's rows, or -1.
func (m *Model) SelectedIndex(key string) int {
	rows := m.Rows(key)
	if len(rows) == 0 {
		return -1
	}
	return max(indexOf(rows, m.SelectedIn(key).ID), 0)
}

// Step moves the selection delta rows in the panel worked in: j and k go round, a page (",", ".")
// and the ends ("<", ">") stop at the ends.
func (m *Model) Step(delta int) {
	key := m.Cur()
	rows := m.Rows(key)
	if len(rows) == 0 {
		return
	}
	i := indexOf(rows, m.sel[key])
	switch {
	case i < 0:
		i = 0
	case delta == 1 || delta == -1:
		// j and k go round from one end to the other (SPEC 6.2).
		i = ((i+delta)%len(rows) + len(rows)) % len(rows)
	default:
		i = min(max(i+delta, 0), len(rows)-1)
	}
	m.SelectIndex(key, i)
}

// SelectIndex selects the i-th row of a list key.
func (m *Model) SelectIndex(key string, i int) {
	rows := m.Rows(key)
	if i < 0 || i >= len(rows) {
		return
	}
	m.sel[key], m.idx[key] = rows[i].ID, i
}

// Select selects an item in a list key, when it is a row of it.
func (m *Model) Select(key, id string) {
	if i := indexOf(m.Rows(key), id); i >= 0 {
		m.SelectIndex(key, i)
	}
}

// MovePanel works in the panel delta panels from the current one, round the column (h, l, Tab).
func (m *Model) MovePanel(delta int) {
	n := len(Panels)
	m.Main = false
	m.Panel = ((m.Panel+delta)%n + n) % n
}

// FocusPanel works in panel i (1〜5 give i+1).
func (m *Model) FocusPanel(i int) {
	if i >= 0 && i < len(Panels) {
		m.Panel, m.Main = i, false
	}
}

// MoveTab shows the tab delta tabs from the current one in the panel worked in ([ and ]). It
// leaves the project looked into, as lazygit's tabs leave a commit's files.
func (m *Model) MoveTab(delta int) {
	n := len(Panels[m.Panel])
	m.steps[m.Panel] = ""
	m.tab[m.Panel] = ((m.tab[m.Panel]+delta)%n + n) % n
}

// FocusList shows a list in the panel that has it, and works there.
func (m *Model) FocusList(list string) {
	for p, tabs := range Panels {
		for t, l := range tabs {
			if l == list {
				m.Panel, m.Main = p, false
				m.tab[p], m.steps[p] = t, ""
				return
			}
		}
	}
}

// EnterSteps looks into a project's steps in the panel worked in.
func (m *Model) EnterSteps(project string) { m.steps[m.Panel] = project }

// LeaveSteps goes back from a project's steps to the projects, with the project selected.
func (m *Model) LeaveSteps() bool {
	p := m.steps[m.Panel]
	if p == "" {
		return false
	}
	m.steps[m.Panel] = ""
	m.Select(m.Cur(), p)
	return true
}

// ProjectShort is the short name of a project, or its id.
func (m *Model) ProjectShort(id string) string {
	if p := m.byID[id]; p != nil && gtd.S(p.Short) != "" {
		return gtd.S(p.Short)
	}
	return id
}

// Label is a list key's name.
func Label(key string) string {
	if l, ok := Lists[key]; ok {
		return l.Label
	}
	return key
}
