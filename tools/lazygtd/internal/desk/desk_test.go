package desk

import (
	"testing"

	"github.com/Lettuce222/lazygtd/internal/gtd"
)

func p(s string) *string { return &s }

func state() *gtd.State {
	return &gtd.State{Today: "2026-11-24", Items: []gtd.Item{
		{ID: "a", Title: "Alpha", List: "next", Actor: p("agent")},
		{ID: "b", Title: "Bravo", List: "next", Actor: p("me")},
		{ID: "c", Title: "Charlie", List: "inbox", Mine: p("handback")},
		{ID: "d", Title: "Delta", List: "inbox", Asked: p("2026-11-24T10:00")},
		{ID: "e", Title: "Echo", List: "next", Answered: p("2026-11-24T11:00"), Read: p("2026-11-24T10:00")},
		{ID: "f", Title: "Foxtrot", List: "done", Mine: p("due"), Answered: p("2026-11-24T11:00")},
		{ID: "g", Title: "Golf", List: "project", Steps: []string{"h", "b"}, Short: p("G")},
		{ID: "h", Title: "Hotel", List: "planned", Project: p("g")},
	}}
}

func ids(rows []*gtd.Item) string {
	out := ""
	for _, r := range rows {
		out += r.ID
	}
	return out
}

func TestRowsFollowTheDesk(t *testing.T) {
	m := New()
	m.SetState(state())
	for key, want := range map[string]string{
		"mine":             "c",   // a done item is not the user's turn
		"talk":             "ed",  // the unread answer first, then the one that waits
		"next":             "bea", // the user's own first, then the agents'
		"inbox":            "cd",
		"done":             "f",
		StepsPrefix + "g":  "hb", // a project's steps in its order
		StepsPrefix + "zz": "",
	} {
		if got := ids(m.Rows(key)); got != want {
			t.Errorf("%s: got %q, want %q", key, got, want)
		}
	}
}

func TestPanelsAndTabs(t *testing.T) {
	m := New()
	m.SetState(state())
	if m.Cur() != "mine" {
		t.Fatalf("got %s", m.Cur())
	}
	m.MoveTab(1)
	if m.Cur() != "talk" {
		t.Errorf("] : got %s", m.Cur())
	}
	m.MoveTab(1) // round
	if m.Cur() != "mine" {
		t.Errorf("] round: got %s", m.Cur())
	}
	m.FocusPanel(4)
	m.MoveTab(-1)
	if m.Cur() != "done" {
		t.Errorf("[ from いつか: got %s", m.Cur())
	}
	m.MovePanel(1)
	if m.Panel != 0 {
		t.Errorf("l from the last panel: got %d", m.Panel)
	}
	m.FocusList("project")
	if m.Panel != 2 || m.Cur() != "project" {
		t.Errorf("FocusList: %d %s", m.Panel, m.Cur())
	}
}

func TestStepsAreEnteredAndLeft(t *testing.T) {
	m := New()
	m.SetState(state())
	m.FocusList("project")
	m.EnterSteps("g")
	if m.Cur() != StepsPrefix+"g" || m.Selected().ID != "h" {
		t.Fatalf("got %s %v", m.Cur(), m.Selected())
	}
	// The project goes: its steps are left.
	s := state()
	s.Items[6].List = "done"
	m.SetState(s)
	if m.Cur() != "project" {
		t.Errorf("got %s", m.Cur())
	}
	m.SetState(state())
	m.EnterSteps("g")
	if !m.LeaveSteps() || m.Cur() != "project" || m.Selected().ID != "g" {
		t.Errorf("Esc: %s %v", m.Cur(), m.Selected())
	}
}

func TestSelectionStaysOrKeepsItsPlace(t *testing.T) {
	m := New()
	m.SetState(state())
	m.FocusList("next")
	m.Step(1)
	if m.Selected().ID != "e" {
		t.Fatalf("got %s", m.Selected().ID)
	}
	s := state()
	s.Items[4].List = "someday"
	m.SetState(s)
	if m.Selected().ID != "a" {
		t.Errorf("got %s, want a", m.Selected().ID)
	}
	m.Step(-5)
	if m.Selected().ID != "b" {
		t.Errorf("a page stops at the top: got %s", m.Selected().ID)
	}
	m.Step(-1)
	if m.Selected().ID != "a" {
		t.Errorf("k goes round to the bottom: got %s", m.Selected().ID)
	}
	m.Step(1)
	if m.Selected().ID != "b" {
		t.Errorf("j goes round to the top: got %s", m.Selected().ID)
	}
}

func TestFilterNeedsEveryWord(t *testing.T) {
	m := New()
	m.SetState(state())
	m.Filters["next"] = "al  PHA"
	if got := ids(m.Rows("next")); got != "a" {
		t.Errorf("got %q", got)
	}
	if got := len(m.AllRows("next")); got != 3 {
		t.Errorf("AllRows is not narrowed: %d", got)
	}
}

func TestKeysAreLazygits(t *testing.T) {
	cases := []struct {
		k       Key
		ctx     string
		hasItem bool
		want    Action
	}{
		{ch('q'), "list", false, Action{Do: "quit"}},
		{ch('1'), "list", false, Action{Do: "panel", Arg: 0}},
		{ch('5'), "main", false, Action{Do: "panel", Arg: 4}},
		{ch('0'), "list", false, Action{Do: "main"}},
		{ch(']'), "list", false, Action{Do: "tab", Arg: 1}},
		{ch('['), "steps", false, Action{Do: "tab", Arg: -1}},
		{named("Tab"), "list", false, Action{Do: "panelStep", Arg: 1}},
		{ch('h'), "list", false, Action{Do: "panelStep", Arg: -1}},
		{ch('j'), "list", false, Action{Do: "step", Arg: 1}},
		{named("Up"), "list", false, Action{Do: "step", Arg: -1}},
		{ch('j'), "main", false, Action{Do: "scroll", Arg: 1}},
		{ch('J'), "list", false, Action{Do: "scroll", Arg: 1}},
		{named("CtrlD"), "list", false, Action{Do: "scroll", Arg: 1}},
		{named("Space"), "list", true, Action{Do: "toggle"}},
		{named("Space"), "list", false, Action{Do: "none"}},
		{named("Enter"), "list", true, Action{Do: "enter"}},
		{ch('c'), "list", false, Action{Do: "create"}},
		{ch('c'), "steps", false, Action{Do: "createStep"}},
		{ch('r'), "list", true, Action{Do: "reply"}},
		{ch('m'), "list", true, Action{Do: "move"}},
		{ch('a'), "list", true, Action{Do: "ask"}},
		{ch('e'), "list", true, Action{Do: "edit"}},
		{ch('o'), "list", true, Action{Do: "open"}},
		{named("CtrlJ"), "steps", true, Action{Do: "stepMove", Arg: 1}},
		{named("CtrlJ"), "list", true, Action{Do: "none"}},
		{ch('x'), "list", false, Action{Do: "menu"}},
		{ch('?'), "main", false, Action{Do: "menu"}},
		{ch('/'), "list", false, Action{Do: "filter"}},
		{ch('R'), "list", false, Action{Do: "refresh"}},
		{ch('+'), "list", false, Action{Do: "screen", Arg: 1}},
		{named("Esc"), "steps", false, Action{Do: "back"}},
		{named("Esc"), "list", false, Action{Do: "back"}},
	}
	for _, c := range cases {
		if got := KeyAction(c.k, c.ctx, c.hasItem); got != c.want {
			t.Errorf("%s in %s: got %+v, want %+v", c.k.Label(), c.ctx, got, c.want)
		}
	}
}

func TestEveryKeyMeansOneThingInAContext(t *testing.T) {
	for _, ctx := range []string{"list", "steps", "main", "global"} {
		seen := map[Key]string{}
		for _, b := range Bindings {
			if b.Ctx != ctx {
				continue
			}
			for _, k := range b.Keys {
				if other, ok := seen[k]; ok {
					t.Errorf("%s: %s is %s and %s", ctx, k.Label(), other, b.Do)
				}
				seen[k] = b.Do
			}
		}
	}
}

func TestOptionsLineAndMenu(t *testing.T) {
	opts := Options("steps")
	if len(opts) == 0 || opts[0] != [2]string{"ステップを足す", "c"} {
		t.Errorf("steps' own first: %v", opts)
	}
	local, global := Shown("main")
	for _, b := range global {
		for _, k := range b.Keys {
			if k == ch('j') || k == named("Esc") {
				t.Errorf("main's %s is listed as global too", k.Label())
			}
		}
	}
	if len(local) == 0 {
		t.Error("no local keys")
	}
	if got := (Key{Named: "CtrlJ"}).Label(); got != "<c-j>" {
		t.Errorf("label: %s", got)
	}
	if got := (Key{Named: "Space"}).Label(); got != "<space>" {
		t.Errorf("label: %s", got)
	}
}
