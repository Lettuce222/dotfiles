package ui

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jesseduffield/gocui"

	"github.com/Lettuce222/lazygtd/internal/desk"
	"github.com/Lettuce222/lazygtd/internal/gtd"
	"github.com/Lettuce222/lazygtd/internal/watch"
)

// The screen on gocui's simulated terminal, over a GTD folder made by scripts/demo-home.sh with
// the real gtd.py: what the user sees, and that each key goes through gtd.py.

type screen struct {
	t     *testing.T
	g     *gocui.Gui
	a     *App
	ended chan error // the main loop's end
}

func demo(t *testing.T) (string, *gtd.Client) {
	t.Helper()
	script := gtd.DefaultScript()
	if _, err := os.Stat(script); err != nil {
		t.Skip("gtd.py is not here")
	}
	home := filepath.Join(t.TempDir(), "gtd")
	out, err := exec.Command("sh", "../../scripts/demo-home.sh", home).CombinedOutput()
	if err != nil {
		t.Fatalf("demo-home.sh: %v\n%s", err, out)
	}
	return home, gtd.New(script, []string{"GTD_HOME=" + home})
}

func start(t *testing.T, client *gtd.Client) *screen {
	t.Helper()
	g, err := gocui.NewGui(gocui.NewGuiOpts{OutputMode: gocui.OutputTrue, Headless: true, Width: 140, Height: 45})
	if err != nil {
		t.Fatal(err)
	}
	a, err := newApp(g, client)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- g.MainLoop() }()
	s := &screen{t: t, g: g, a: a, ended: done}
	t.Cleanup(func() {
		g.Update(func(*gocui.Gui) error { return gocui.ErrQuit })
		select {
		case err := <-done:
			if err != nil && !errors.Is(err, gocui.ErrQuit) {
				t.Error(err)
			}
		case <-time.After(5 * time.Second):
			t.Error("the main loop did not end")
		}
		g.Close()
	})
	return s
}

// do runs f in the screen's loop and waits until the screen is drawn after it.
func (s *screen) do(f func()) {
	ch := make(chan struct{})
	// UpdateAsync, not Update: Update spawns a goroutine, so two of them may run in either order.
	s.g.UpdateAsync(func(*gocui.Gui) error { f(); return nil })
	s.g.UpdateAsync(func(*gocui.Gui) error { close(ch); return nil })
	select {
	case <-ch:
	case err := <-s.ended:
		s.ended <- err
		s.t.Fatalf("the main loop ended: %v", err)
	}
}

func (s *screen) keys(ks ...desk.Key) {
	for _, k := range ks {
		s.do(func() { _ = s.a.onKey(k) })
	}
}

func (s *screen) text() string {
	var out string
	s.do(func() {})
	s.do(func() { out = s.g.Snapshot() })
	return out
}

// until waits for the screen to show want.
func (s *screen) until(want string) string {
	s.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for {
		got := s.text()
		if strings.Contains(got, want) {
			return got
		}
		if time.Now().After(deadline) {
			s.t.Fatalf("the screen never showed %q:\n%s", want, got)
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func ch(r rune) desk.Key { return desk.Key{Ch: r} }

// pick selects the row of the box worked in whose title is title (the ids, so the order, are random).
func (s *screen) pick(title string) {
	s.t.Helper()
	found := false
	s.do(func() {
		for i, it := range s.a.model.Rows(s.a.model.Cur) {
			if it.Title == title {
				s.a.model.SelectIndex(s.a.model.Cur, i)
				found = true
			}
		}
	})
	if !found {
		s.t.Fatalf("no row %q", title)
	}
}

func TestScreenShowsTheBoxesAndTheDetail(t *testing.T) {
	_, client := demo(t)
	s := start(t, client)
	got := s.until("[q] あなたの番 (2)")
	for _, want := range []string{"[o] 窓口 (1)", "[w] inbox (2)", "[e] 次の行動 (5)", "[r] プロジェクト (1)", "[t] 連絡待ち (1)", "[y] いつか／たぶん (1)", "[u] 資料 (1)", "下書きを確かめてほしい", "あなたに戻った"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q:\n%s", want, got)
		}
	}
	// 次の行動: the body's Markdown, rendered.
	s.keys(ch('e'))
	s.pick("計測の仕組みを下書きする")
	got = s.until("リードタイム")
	for _, want := range []string{"背景", "リードタイム", "gtd.py json | jq .counts", "引用: 小さく始める"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q:\n%s", want, got)
		}
	}
	// glamour keeps the heading's marks (## 背景) to show its level; the table and the emphasis are drawn.
	if strings.Contains(got, "| --- |") || strings.Contains(got, "**5 つ**") {
		t.Errorf("the Markdown is not rendered:\n%s", got)
	}
}

func TestMoveAndDoneGoThroughGtd(t *testing.T) {
	home, client := demo(t)
	s := start(t, client)
	s.keys(ch('w')) // inbox
	s.pick("名刺の整理")
	s.keys(ch('f'))
	s.until("移す先")
	s.keys(ch('s')) // いつか
	s.until("[y] いつか／たぶん (2)")
	log, _ := os.ReadFile(filepath.Join(home, ".log", "changes.jsonl"))
	if !strings.Contains(string(log), `"action": "move:someday", "by": "user"`) {
		t.Errorf("no move by user in the log:\n%s", log)
	}
	s.keys(ch('x'))
	s.until("[w] inbox (0)")
}

func TestReplyAndAdd(t *testing.T) {
	home, client := demo(t)
	s := start(t, client)
	s.keys(ch('w'))
	s.pick("名刺の整理")
	s.keys(desk.Key{Named: "Enter"})
	s.until("返事（")
	s.do(func() { s.a.typeIn("一行目"); s.a.typeIn("\n"); s.a.typeIn("二行目") })
	s.do(func() { _ = s.a.submit(false) })
	got := s.until("[o] 窓口 (2)")
	if !strings.Contains(got, "答え待ち") {
		t.Errorf("no 答え待ち:\n%s", got)
	}
	files, _ := filepath.Glob(filepath.Join(home, "items", "*.md"))
	found := false
	for _, f := range files {
		b, _ := os.ReadFile(f)
		if strings.Contains(string(b), "名刺の整理") && strings.Contains(string(b), ": 一行目 二行目") {
			found = true
		}
	}
	if !found {
		t.Error("the reply is not in the item as one line")
	}
	s.keys(ch('a'))
	s.until("inbox に足す")
	s.do(func() {
		v, _ := s.g.View(vInput)
		v.TextArea.TypeString("新しい項目")
		_ = s.a.submit(false)
	})
	s.until("[w] inbox (3)")
}

func TestAnAgentsWriteShowsUp(t *testing.T) {
	home, client := demo(t)
	s := start(t, client)
	stop, err := watch.Start(home, s.a.reload, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer stop()
	s.until("[w] inbox (2)")
	// An agent adds an item with gtd.py, not through lazygtd.
	cmd := exec.Command("python3", gtd.DefaultScript(), "add", "--title=エージェントが足した", "--by", "agent:test")
	cmd.Env = append(os.Environ(), "GTD_HOME="+home)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	s.until("[w] inbox (3)")
}

func TestAConflictReadsAgainAndTells(t *testing.T) {
	home, client := demo(t)
	s := start(t, client)
	s.keys(ch('w'))
	s.pick("名刺の整理")
	// Someone else changes the selected item after lazygtd read it.
	var id string
	s.do(func() { id = s.a.model.Selected().ID })
	cmd := exec.Command("python3", gtd.DefaultScript(), "set", id, "due=2026-12-01", "--by", "agent:test")
	cmd.Env = append(os.Environ(), "GTD_HOME="+home)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	s.keys(ch('x'))
	got := s.until("ぶつかった")
	if !strings.Contains(got, "12/01") {
		t.Errorf("not read again:\n%s", got)
	}
}

func TestFilterAndHelp(t *testing.T) {
	_, client := demo(t)
	s := start(t, client)
	s.keys(ch('e'), ch('/'))
	s.until("絞り込み: 次の行動")
	s.do(func() {
		v, _ := s.g.View(vInput)
		for _, r := range "設定" {
			s.a.edit(v, 0, r, gocui.ModNone)
		}
	})
	got := s.until("[e] 次の行動 (1/5)")
	if strings.Contains(got, "計測の仕組み") {
		t.Errorf("not narrowed:\n%s", got)
	}
	s.do(func() { _ = s.a.cancelInput() })
	s.until("[e] 次の行動 (5)")
	s.keys(ch('?'))
	s.until("キー（Esc か ? で閉じる）")
	s.keys(desk.Key{Named: "Esc"})
}
