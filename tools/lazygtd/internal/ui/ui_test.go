package ui

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jesseduffield/gocui"

	"github.com/Lettuce222/lazygtd/internal/gtd"
	"github.com/Lettuce222/lazygtd/internal/watch"
)

// The screen on gocui's simulated terminal, over a copy of the folder scripts/demo-home.sh makes
// with the real gtd.py: what the user sees, and that each key goes through gtd.py.

var (
	demoOnce sync.Once
	demoDir  string
	demoErr  error
)

func demo(t *testing.T) (string, *gtd.Client) {
	t.Helper()
	script := gtd.DefaultScript()
	if _, err := os.Stat(script); err != nil {
		t.Skip("gtd.py is not here")
	}
	demoOnce.Do(func() {
		base, err := os.MkdirTemp("", "lazygtd-demo-")
		if err != nil {
			demoErr = err
			return
		}
		demoDir = filepath.Join(base, "gtd")
		out, err := exec.Command("sh", "../../scripts/demo-home.sh", demoDir).CombinedOutput()
		if err != nil {
			demoErr = errors.New(string(out))
		}
	})
	if demoErr != nil {
		t.Fatalf("demo-home.sh: %v", demoErr)
	}
	home := filepath.Join(t.TempDir(), "gtd")
	if out, err := exec.Command("cp", "-R", demoDir, home).CombinedOutput(); err != nil {
		t.Fatalf("cp: %v %s", err, out)
	}
	return home, gtd.New(script, []string{"GTD_HOME=" + home})
}

func TestMain(m *testing.M) {
	code := m.Run()
	if demoDir != "" {
		os.RemoveAll(filepath.Dir(demoDir))
	}
	os.Exit(code)
}

type screen struct {
	t     *testing.T
	g     *gocui.Gui
	a     *App
	home  string
	ended chan error
}

func start(t *testing.T) *screen {
	t.Helper()
	home, client := demo(t)
	g, err := gocui.NewGui(gocui.NewGuiOpts{OutputMode: gocui.OutputTrue, Headless: true, Width: 160, Height: 45})
	if err != nil {
		t.Fatal(err)
	}
	a, err := newApp(g, client)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- g.MainLoop() }()
	s := &screen{t: t, g: g, a: a, home: home, ended: done}
	t.Cleanup(func() {
		// Let the writes under way end before the folder goes.
		a.running.Wait()
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

// do runs f in the screen's loop and waits until the screen is drawn after it. UpdateAsync, not
// Update: Update spawns a goroutine, so two of them may run in either order.
func (s *screen) do(f func()) {
	ch := make(chan struct{})
	s.g.UpdateAsync(func(*gocui.Gui) error { f(); return nil })
	s.g.UpdateAsync(func(*gocui.Gui) error { close(ch); return nil })
	select {
	case <-ch:
	case err := <-s.ended:
		s.ended <- err
		s.t.Fatalf("the main loop ended: %v", err)
	}
}

// press sends keys as the bindings get them: a rune, or a named key in angle brackets.
func (s *screen) press(keys ...string) {
	for _, k := range keys {
		kp := keyPress{named: strings.Trim(k, "<>")}
		if !strings.HasPrefix(k, "<") {
			kp = keyPress{ch: []rune(k)[0]}
		}
		s.do(func() { _ = s.a.onKey(kp) })
	}
}

// typeIn writes text into the input that is open, as the keyboard does.
func (s *screen) typeIn(text string) {
	s.do(func() {
		v, err := s.g.View(vInput)
		if err != nil || s.a.popup == nil {
			v, err = s.g.View(vFilter)
		}
		if s.a.replying {
			v, err = s.g.View(vReply)
		}
		if err != nil {
			s.t.Error("no input is open")
			return
		}
		for _, r := range text {
			if r == '\n' {
				if s.a.replying {
					s.a.typeReply("\n")
				} else {
					s.a.newLine()
				}
				continue
			}
			v.Editor.Edit(v, 0, r, gocui.ModNone)
		}
	})
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

// pick selects the row whose title is title in the list worked in (the ids, so the order, are
// random), waiting for a read to bring it.
func (s *screen) pick(title string) {
	s.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for {
		found := false
		s.do(func() {
			for i, it := range s.a.model.Rows(s.a.model.Cur()) {
				if it.Title == title {
					s.a.model.SelectIndex(s.a.model.Cur(), i)
					found = true
				}
			}
		})
		if found {
			return
		}
		if time.Now().After(deadline) {
			s.t.Fatalf("no row %q in %s", title, s.a.model.Cur())
		}
		time.Sleep(50 * time.Millisecond)
	}
}

// item reads an item's file by its title.
func (s *screen) item(title string) string {
	s.t.Helper()
	files, _ := filepath.Glob(filepath.Join(s.home, "items", "*.md"))
	for _, f := range files {
		b, _ := os.ReadFile(f)
		// YAML may quote a title (one with ": " in it).
		for _, line := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(line, "title: ") && strings.Trim(strings.TrimPrefix(line, "title: "), `"'`) == title {
				return string(b)
			}
		}
	}
	return ""
}

func (s *screen) log() string {
	b, _ := os.ReadFile(filepath.Join(s.home, ".log", "changes.jsonl"))
	return string(b)
}

// lineOf is the row of the screen where want first is.
func lineOf(screen, want string) int {
	for i, l := range strings.Split(screen, "\n") {
		if strings.Contains(l, want) {
			return i
		}
	}
	return -1
}

func TestTheScreenIsLazygits(t *testing.T) {
	s := start(t)
	got := s.until("[1]─あなたの番")
	for _, want := range []string{
		"╭─[1]─あなたの番 (", " - 窓口 (4) ●2", "[2]─inbox (8)", "[3]─次の行動 (23) - プロジェクト (4)", "[4]─連絡待ち (6)",
		"[5]─いつか (7) - 資料 (5) - 完了 (9)", "[0]─詳細", "1 of 8", "返事", "<enter> で書く",
		"新規: c | 返事: r | 完了: <space>", "lazygtd " + Version,
	} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q:\n%s", want, got)
		}
	}
	// The panels keep their size whatever is worked in (expandFocusedSidePanel: false).
	before := []int{lineOf(got, "[2]─"), lineOf(got, "[3]─"), lineOf(got, "[4]─"), lineOf(got, "[5]─")}
	// The selected row is reversed: text in the background's color on the text's.
	s.press("4", "j", "k")
	got = s.text()
	after := []int{lineOf(got, "[2]─"), lineOf(got, "[3]─"), lineOf(got, "[4]─"), lineOf(got, "[5]─")}
	for i := range before {
		if before[i] != after[i] {
			t.Errorf("panel %d moved from row %d to %d", i+2, before[i], after[i])
		}
	}
}

func TestTheDetailRendersMarkdown(t *testing.T) {
	s := start(t)
	s.press("3")
	s.pick("計測の仕組みを下書きする")
	got := s.until("リードタイム")
	for _, want := range []string{"背景", "変更の失敗率", "python3 collect.py"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "| --- |") || strings.Contains(got, "**開発の流れ**") {
		t.Errorf("the Markdown is not rendered:\n%s", got)
	}
	// 0 and j scroll the detail; Esc goes back.
	s.press("0")
	s.do(func() {
		if !s.a.model.Main {
			t.Error("0 does not go to the detail")
		}
	})
	s.press("j", "j", "<Esc>")
	s.do(func() {
		if s.a.model.Main {
			t.Error("Esc does not go back")
		}
	})
}

func TestCreateWithABody(t *testing.T) {
	s := start(t)
	s.press("2", "c")
	s.until("新しい項目（inbox）")
	s.typeIn("TUI から足した\n本文の一行目\n二行目")
	s.do(func() { s.a.submitInput() })
	s.until("inboxに作った")
	got := s.item("TUI から足した")
	if !strings.Contains(got, "list: inbox") || !strings.Contains(got, "本文の一行目\n二行目") {
		t.Errorf("the item:\n%s", got)
	}
	if !strings.Contains(s.log(), `"action": "add", "by": "user"`) {
		t.Error("no add by user in the log")
	}
}

func TestSpaceMarksDone(t *testing.T) {
	s := start(t)
	s.press("2")
	s.pick("名刺の整理")
	s.press("<Space>")
	s.until("完了にした")
	if !strings.Contains(s.item("名刺の整理"), "list: done") {
		t.Error("<space> did not mark it done")
	}
	// In 完了, <space> brings it back to 次の行動.
	s.press("5", "[")
	s.pick("名刺の整理")
	s.press("<Space>")
	s.until("次の行動に戻した")
	if !strings.Contains(s.item("名刺の整理"), "list: next") {
		t.Error("<space> in 完了 did not bring it back")
	}
}

func TestMoveAndAskTheOrchestrator(t *testing.T) {
	s := start(t)
	s.press("2")
	s.pick("会議の議題を 3 つ集める")
	s.press("m")
	s.until("移す先")
	s.press("s")
	s.until("移した: いつか")
	if !strings.Contains(s.log(), `"action": "move:someday", "by": "user"`) {
		t.Error("no move by user in the log")
	}
	s.until("1 of 7")
	s.pick("経費の精算（11 月分のタクシー 2 件）")
	s.press("a")
	s.until("窓口に頼む")
	s.press("a")
	s.until("窓口に頼んだ")
	got := s.item("経費の精算（11 月分のタクシー 2 件）")
	if !strings.Contains(got, "list: next") || !strings.Contains(got, "actor: agent") || strings.Contains(got, "worker:") {
		t.Errorf("not an agent's item in next with no worker:\n%s", got)
	}
}

func TestReplyInTheBoxUnderTheDetail(t *testing.T) {
	s := start(t)
	s.press("2")
	s.pick("名刺の整理")
	s.press("<Enter>")
	s.until("送る: <enter>")
	// An empty box sends nothing.
	s.do(func() { s.a.sendReply() })
	s.do(func() {
		if !s.a.replying {
			t.Error("an empty reply left the box")
		}
	})
	s.typeIn("確かめました\n二行目")
	s.do(func() { s.a.sendReply() })
	s.until("返事を書いた")
	s.until("窓口 (5)")
	got := s.item("名刺の整理")
	if !strings.Contains(got, ": 確かめました 二行目") {
		t.Errorf("the reply is not in the item as one line:\n%s", got)
	}
	// The detail shows the talk.
	s.until("窓口とのやり取り")
}

func TestStepsOfAProject(t *testing.T) {
	s := start(t)
	s.press("3", "]")
	s.pick("計測を始める")
	s.press("<Enter>")
	got := s.until("プロジェクト › 計測")
	for _, want := range []string{"✓ 指標を決める", "▶ 集める処理を書く", "· ダッシュボードを作る", "1 of 5"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q:\n%s", want, got)
		}
	}
	s.press("c")
	s.until("新しいステップ（計測）")
	s.typeIn("振り返る")
	s.do(func() { s.a.submitInput() })
	s.until("1 of 6")
	// <c-j> moves the selected step down.
	s.pick("ダッシュボードを作る")
	s.press("<CtrlJ>")
	deadline := time.Now().Add(10 * time.Second)
	for {
		got = s.text()
		// The rows of the steps (the detail shows the selected step's title too).
		if l := lineOf(got, "· チームに見せて直す"); l >= 0 && l < lineOf(got, "· ダッシュボードを作る") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("not moved:\n%s", got)
		}
		time.Sleep(50 * time.Millisecond)
	}
	s.press("<Esc>")
	s.until("[3]─次の行動 (")
}

func TestAnAgentsWriteShowsUp(t *testing.T) {
	s := start(t)
	stop, err := watch.Start(s.home, s.a.reload, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer stop()
	s.press("2")
	s.until("1 of 8")
	cmd := exec.Command("python3", gtd.DefaultScript(), "add", "--title=エージェントが足した", "--by", "agent:test")
	cmd.Env = append(os.Environ(), "GTD_HOME="+s.home)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	s.until("1 of 9")
}

func TestAConflictReadsAgainAndTells(t *testing.T) {
	s := start(t)
	s.press("2")
	s.pick("名刺の整理")
	var id string
	s.do(func() { id = s.a.model.Selected().ID })
	cmd := exec.Command("python3", gtd.DefaultScript(), "set", id, "due=2026-12-01", "--by", "agent:test")
	cmd.Env = append(os.Environ(), "GTD_HOME="+s.home)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	s.press("<Space>")
	// Read again, then told on the bottom line (SPEC 4.4).
	got := s.until("ぶつかった")
	if !strings.Contains(got, "12/01") {
		t.Errorf("not read again:\n%s", got)
	}
	s.do(func() {
		if s.a.popup != nil {
			t.Error("told in a popup, not on the bottom line")
		}
	})
}

func TestFilterAndKeysMenu(t *testing.T) {
	s := start(t)
	s.press("3", "/")
	s.until("絞り込み:")
	s.typeIn("PR")
	got := s.until("/PR")
	if !strings.Contains(got, "依存ライブラリを最新に上げる PR を作る") || !strings.Contains(got, "1 of 2") {
		t.Errorf("not narrowed:\n%s", got)
	}
	s.do(func() { s.a.endFilter(true) })
	s.until("絞り込み中: 'PR'")
	s.press("<Esc>")
	s.until("of 23")
	s.press("x")
	got = s.until("この箱")
	for _, want := range []string{"どこでも", "新しい項目を作る", "[5] いつか - 資料 - 完了"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q", want)
		}
	}
	// A key in the menu runs its act: 5 goes to panel 5.
	s.press("5")
	s.do(func() {
		if s.a.popup != nil || s.a.model.Panel != 4 {
			t.Errorf("the menu's 5: popup %v, panel %d", s.a.popup, s.a.model.Panel)
		}
	})
}

func TestMoveToTheCalendar(t *testing.T) {
	s := start(t)
	s.press("2")
	s.pick("名刺の整理")
	s.press("m")
	s.until("カレンダーに入れる")
	s.press("c")
	s.until("カレンダーに入れる次の行動にした")
	got := s.item("カレンダーに入れる: 名刺の整理")
	if !strings.Contains(got, "list: next") || !strings.Contains(got, "actor: me") {
		t.Errorf("the item:\n%s", got)
	}
}

func TestAnEmptyCreateIsNotSent(t *testing.T) {
	s := start(t)
	s.press("2", "c")
	s.until("新しい項目（inbox）")
	s.typeIn("   ")
	s.do(func() { s.a.submitInput() })
	s.do(func() {
		if s.a.popup == nil {
			t.Error("an empty input closed the popup")
		}
	})
}
