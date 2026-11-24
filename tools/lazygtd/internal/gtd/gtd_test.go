package gtd

import (
	"context"
	"reflect"
	"testing"
)

type call struct{ args []string }

func fake(stdout, stderr string, code int, calls *[]call) *Client {
	c := New("gtd.py", nil)
	c.run = func(_ context.Context, _ string, args []string, _ []string) ([]byte, []byte, int, error) {
		*calls = append(*calls, call{args})
		return []byte(stdout), []byte(stderr), code, nil
	}
	return c
}

func TestWritesAreByUserWithTheHash(t *testing.T) {
	var calls []call
	c := fake("{}", "", 0, &calls)
	_ = c.Move("x1", "next", "0123456789abcdef")
	_ = c.Done("x1", "")
	_ = c.Say("x1", "--list done")
	_ = c.Add("-x")
	_ = c.Read("x1")
	want := [][]string{
		{"gtd.py", "move", "x1", "next", "--hash=0123456789abcdef", "--by", "user"},
		{"gtd.py", "done", "x1", "--by", "user"},
		// A text that looks like a flag stays the text.
		{"gtd.py", "say", "x1", "--text=--list done", "--by", "user"},
		{"gtd.py", "add", "--title=-x", "--by", "user"},
		{"gtd.py", "read", "x1", "--by", "user"},
	}
	for i, w := range want {
		if !reflect.DeepEqual(calls[i].args, w) {
			t.Errorf("call %d: got %q, want %q", i, calls[i].args, w)
		}
	}
}

func TestAConflictIsTold(t *testing.T) {
	var calls []call
	c := fake("", "warning\ngtd.py move: x1 はほかの人が先に直した（読み直してください）\n", 3, &calls)
	err := c.Move("x1", "next", "")
	if !IsConflict(err) {
		t.Fatalf("not a conflict: %v", err)
	}
	if err.Error() != "x1 はほかの人が先に直した（読み直してください）" {
		t.Errorf("message: %q", err.Error())
	}
	c = fake("", "gtd.py move: 移す先が違う\n", 2, &calls)
	if err := c.Move("x1", "nope", ""); IsConflict(err) || err == nil {
		t.Errorf("got %v", err)
	}
}

func TestTalkMarks(t *testing.T) {
	s := func(v string) *string { return &v }
	it := Item{Asked: s("2026-11-24T10:00")}
	if !it.Waiting() || it.Unread() {
		t.Error("asked, no answer: waiting")
	}
	it.Answered = s("2026-11-24T11:00")
	if it.Waiting() || !it.Unread() {
		t.Error("answered later: unread, not waiting")
	}
	it.Read = s("2026-11-24T11:00")
	if it.Unread() {
		t.Error("read")
	}
}
