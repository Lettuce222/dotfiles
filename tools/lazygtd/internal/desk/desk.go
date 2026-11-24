// Package desk is the state of the screen without the screen: the boxes of the left column, the
// rows of each, which row is selected, and the filters. It follows the browser desk of the Hub
// (local) Orca plugin (desk/desk.mjs, desk/sections.mjs) so that the two show the same lists.
package desk

import (
	"strings"

	"github.com/Lettuce222/lazygtd/internal/gtd"
)

// Box is a box of the left column.
type Box struct {
	ID    string
	Label string
	Key   rune // the key that jumps to it
	G     rune // the initial after g (0 for none)
	Hint  string
}

// Boxes are the boxes in the order of the column (h, l and Tab go round them), as on the desk:
// あなたの番, then the talk with the orchestrator under it, then the lists.
var Boxes = []Box{
	{"mine", "あなたの番", 'q', 'y', "承認・要判断・確かめてほしいもの"},
	{"talk", "窓口", 'o', 0, "窓口の返事（まだ読んでいないもの）と、窓口の答えを待っているもの"},
	{"inbox", "inbox", 'w', 'i', "1 件ずつ何をするか決めて移す（f）"},
	{"next", "次の行動", 'e', 'n', "自分とエージェント。プロジェクトの「次」もここに出る"},
	{"project", "プロジェクト", 'r', 'p', "要る行動を順に"},
	{"waiting", "連絡待ち", 't', 'w', "相手・渡した日・確かめる日"},
	{"someday", "いつか／たぶん", 'y', 's', "今はやらない"},
	{"reference", "資料", 'u', 'r', "資料と成果物"},
}

// MigrateKey is the desk's key of the migration of the old cases, which lazygtd leaves to the
// browser desk.
const MigrateKey = 'i'

// MoveTo are where f moves an item, with the key of each in the menu (desk/desk.mjs MOVE_TO).
var MoveTo = []struct {
	List, Label string
	Key         rune
}{
	{"inbox", "inbox", 'i'},
	{"next", "次の行動", 'n'},
	{"planned", "プロジェクトのステップ（まだ）", 't'},
	{"waiting", "連絡待ち", 'w'},
	{"someday", "いつか／たぶん", 's'},
	{"reference", "資料", 'r'},
}

// MineLabel names why an item is in あなたの番 (gtd.py json's mine).
var MineLabel = map[string]string{
	"handback": "あなたに戻った", "ask": "問いがある", "agent_done": "完了・確かめて",
	"follow_up": "確かめる日が来た", "due": "締め切り", "conflict": "ぶつかり",
}

// SmallRows is how many rows a box shows while another one is worked in.
const SmallRows = 3

// Model is the screen's state.
type Model struct {
	State   *gtd.State
	Cur     string            // the box worked in
	sel     map[string]string // the selected item's id, by box
	idx     map[string]int    // the selected row's index, by box (to stay put when the item goes)
	Filters map[string]string // the filter (/) of each box
	byID    map[string]*gtd.Item
}

// New is the model of an empty desk, with あなたの番 worked in.
func New() *Model {
	return &Model{State: &gtd.State{}, Cur: "mine", sel: map[string]string{}, idx: map[string]int{}, Filters: map[string]string{}, byID: map[string]*gtd.Item{}}
}

// SetState takes what gtd.py json read. Each box keeps its selected item, or the row at the same
// place when the item left the box.
func (m *Model) SetState(s *gtd.State) {
	m.State = s
	m.byID = make(map[string]*gtd.Item, len(s.Items))
	for i := range s.Items {
		m.byID[s.Items[i].ID] = &s.Items[i]
	}
	for _, b := range Boxes {
		rows := m.Rows(b.ID)
		if id, ok := m.sel[b.ID]; ok && indexOf(rows, id) >= 0 {
			m.idx[b.ID] = indexOf(rows, id)
			continue
		}
		if len(rows) == 0 {
			delete(m.sel, b.ID)
			continue
		}
		i := min(max(m.idx[b.ID], 0), len(rows)-1)
		m.sel[b.ID], m.idx[b.ID] = rows[i].ID, i
	}
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

// AllRows are the rows of a box before its filter.
func (m *Model) AllRows(box string) []*gtd.Item {
	var out []*gtd.Item
	items := m.State.Items
	open := func(it *gtd.Item) bool { return it.List != "done" }
	switch box {
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
	default:
		for i := range items {
			if items[i].List == box {
				out = append(out, &items[i])
			}
		}
	}
	return out
}

// Rows are the rows of a box, narrowed by its filter: the rows whose title holds every word of
// it, case aside (desk/sections.mjs filterRows).
func (m *Model) Rows(box string) []*gtd.Item {
	return Filter(m.AllRows(box), m.Filters[box])
}

// Filter narrows rows to those whose title holds every word of query.
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

// SelectedIn is the selected item of a box, or nil.
func (m *Model) SelectedIn(box string) *gtd.Item {
	rows := m.Rows(box)
	if i := indexOf(rows, m.sel[box]); i >= 0 {
		return rows[i]
	}
	if len(rows) > 0 {
		return rows[0]
	}
	return nil
}

// Selected is the selected item of the box worked in, or nil.
func (m *Model) Selected() *gtd.Item { return m.SelectedIn(m.Cur) }

// SelectedIndex is the index of the selected row in a box's rows, or -1.
func (m *Model) SelectedIndex(box string) int {
	rows := m.Rows(box)
	if len(rows) == 0 {
		return -1
	}
	return max(indexOf(rows, m.SelectedIn(box).ID), 0)
}

// Step moves the selection delta rows in the box worked in, kept within it (j, k).
func (m *Model) Step(delta int) {
	rows := m.Rows(m.Cur)
	if len(rows) == 0 {
		return
	}
	i := indexOf(rows, m.sel[m.Cur])
	if i < 0 {
		i = 0
	} else {
		i += delta
	}
	i = min(max(i, 0), len(rows)-1)
	m.sel[m.Cur], m.idx[m.Cur] = rows[i].ID, i
}

// SelectIndex selects the i-th row of a box (a click).
func (m *Model) SelectIndex(box string, i int) {
	rows := m.Rows(box)
	if i < 0 || i >= len(rows) {
		return
	}
	m.sel[box], m.idx[box] = rows[i].ID, i
}

// BoxIndex is the index of a box in Boxes, or -1.
func BoxIndex(id string) int {
	for i, b := range Boxes {
		if b.ID == id {
			return i
		}
	}
	return -1
}

// MoveBox works in the box delta boxes from the current one, round the column (h, l, Tab).
func (m *Model) MoveBox(delta int) {
	n := len(Boxes)
	i := max(BoxIndex(m.Cur), 0)
	m.Cur = Boxes[((i+delta)%n+n)%n].ID
}

// Focus works in a box.
func (m *Model) Focus(box string) {
	if BoxIndex(box) >= 0 {
		m.Cur = box
	}
}

// ProjectShort is the short name of a project, or its id.
func (m *Model) ProjectShort(id string) string {
	if p := m.byID[id]; p != nil && gtd.S(p.Short) != "" {
		return gtd.S(p.Short)
	}
	return id
}
