package gtd

import (
	"reflect"
	"testing"
)

func TestTheNewWrites(t *testing.T) {
	var calls []call
	c := fake("{}", "", 0, &calls)
	_ = c.Add("next", "題", "本文\n2 行目")
	_ = c.Ask("x1", "0123456789abcdef")
	_ = c.StepAdd("p1", "ステップ")
	_ = c.StepMove("p1", "x1", 2)
	want := [][]string{
		// next is the user's own, as on the desk.
		{"gtd.py", "add", "--title=題", "--list=next", "--actor=me", "--body=本文\n2 行目", "--by", "user"},
		// One write: the Hub tells the orchestrator of an agent's item in next with no worker.
		{"gtd.py", "set", "x1", "actor=agent", "list=next", "--hash=0123456789abcdef", "--by", "user"},
		{"gtd.py", "step", "add", "p1", "--title=ステップ", "--by", "user"},
		{"gtd.py", "step", "move", "p1", "x1", "2", "--by", "user"},
	}
	for i, w := range want {
		if !reflect.DeepEqual(calls[i].args, w) {
			t.Errorf("call %d: got %q, want %q", i, calls[i].args, w)
		}
	}
}
