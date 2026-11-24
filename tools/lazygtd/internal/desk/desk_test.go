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
	for box, want := range map[string]string{
		"mine":  "c",   // a done item is not the user's turn
		"talk":  "ed",  // the unread answer first, then the one that waits
		"next":  "bea", // the user's own first, then the agents'
		"inbox": "cd",
		"done":  "f",
	} {
		if got := ids(m.Rows(box)); got != want {
			t.Errorf("%s: got %q, want %q", box, got, want)
		}
	}
}

func TestSelectionStaysOrKeepsItsPlace(t *testing.T) {
	m := New()
	m.SetState(state())
	m.Focus("next")
	m.Step(1)
	if m.Selected().ID != "e" {
		t.Fatalf("got %s", m.Selected().ID)
	}
	// e leaves next: the row at the same place is selected.
	s := state()
	s.Items[4].List = "someday"
	m.SetState(s)
	if m.Selected().ID != "a" {
		t.Errorf("got %s, want a", m.Selected().ID)
	}
	m.Step(-5)
	if m.Selected().ID != "b" {
		t.Errorf("kept within the box: got %s", m.Selected().ID)
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

func TestMoveBoxGoesRound(t *testing.T) {
	m := New()
	m.MoveBox(-1)
	if m.Cur != "reference" {
		t.Errorf("got %s", m.Cur)
	}
	m.MoveBox(2)
	if m.Cur != "talk" {
		t.Errorf("got %s", m.Cur)
	}
}

func TestKeys(t *testing.T) {
	cases := []struct {
		k       Key
		mode    Mode
		hasItem bool
		want    Action
	}{
		{Key{Ch: 'q'}, ModeList, false, Action{Do: "focus", Box: "mine"}},
		{Key{Ch: 'o'}, ModeList, false, Action{Do: "focus", Box: "talk"}},
		{Key{Ch: 'u'}, ModeList, false, Action{Do: "focus", Box: "reference"}},
		{Key{Ch: 'i'}, ModeList, false, Action{Do: "migrate"}},
		{Key{Ch: 'l'}, ModeList, false, Action{Do: "box", Delta: 1}},
		{Key{Named: "BackTab"}, ModeList, false, Action{Do: "box", Delta: -1}},
		{Key{Ch: 'j'}, ModeList, false, Action{Do: "step", Delta: 1}},
		{Key{Ch: 's'}, ModeList, true, Action{Do: "open"}},
		{Key{Ch: 's'}, ModeList, false, Action{Do: "none"}},
		{Key{Ch: 'd'}, ModeList, true, Action{Do: "deliv"}},
		{Key{Ch: 'f'}, ModeList, true, Action{Do: "move"}},
		{Key{Ch: 'x'}, ModeList, true, Action{Do: "done"}},
		{Key{Named: "Enter"}, ModeList, true, Action{Do: "write"}},
		{Key{Ch: 'a'}, ModeList, false, Action{Do: "add"}},
		{Key{Ch: '/'}, ModeList, false, Action{Do: "filter"}},
		{Key{Ch: '?'}, ModeList, false, Action{Do: "help"}},
		// The menu takes every key while it is open: s is いつか there, not the editor.
		{Key{Ch: 's'}, ModeMenu, true, Action{Do: "menu", List: "someday"}},
		{Key{Ch: 't'}, ModeMenu, true, Action{Do: "menu", List: "planned"}},
		{Key{Ch: 'x'}, ModeMenu, true, Action{Do: "none"}},
		{Key{Named: "Esc"}, ModeMenu, true, Action{Do: "close"}},
		// After g, the initials.
		{Key{Ch: 'n'}, ModeG, false, Action{Do: "focus", Box: "next"}},
		{Key{Ch: 'y'}, ModeG, false, Action{Do: "focus", Box: "mine"}},
		{Key{Ch: 'q'}, ModeG, false, Action{Do: "none"}},
	}
	for _, c := range cases {
		if got := KeyAction(c.k, c.mode, c.hasItem); got != c.want {
			t.Errorf("%+v in %d: got %+v, want %+v", c.k, c.mode, got, c.want)
		}
	}
}

func TestEveryBoxHasItsOwnKey(t *testing.T) {
	seen := map[rune]string{MigrateKey: "migrate"}
	for _, b := range Boxes {
		if other, ok := seen[b.Key]; ok {
			t.Errorf("%s and %s share %c", b.ID, other, b.Key)
		}
		seen[b.Key] = b.ID
		if _, clash := itemActs[b.Key]; clash {
			t.Errorf("%s's key %c is an act on the item", b.ID, b.Key)
		}
	}
}
