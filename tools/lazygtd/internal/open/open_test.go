package open

import (
	"os"
	"path/filepath"
	"testing"
)

func TestTargetStaysInTheItems(t *testing.T) {
	root := t.TempDir()
	items := filepath.Join(root, "items")
	must(t, os.MkdirAll(filepath.Join(items, "x1"), 0o755))
	must(t, os.WriteFile(filepath.Join(items, "x1.md"), []byte("x"), 0o644))
	must(t, os.WriteFile(filepath.Join(items, "x1", "report.md"), []byte("x"), 0o644))
	must(t, os.WriteFile(filepath.Join(root, "secret.md"), []byte("x"), 0o644))
	must(t, os.Symlink(filepath.Join(root, "secret.md"), filepath.Join(items, "x1", "link.md")))

	if got, err := Target(items, "x1", ""); err != nil || got != filepath.Join(items, "x1.md") {
		t.Errorf("the item: %q %v", got, err)
	}
	if got, err := Target(items, "x1", "report.md"); err != nil || got != filepath.Join(items, "x1", "report.md") {
		t.Errorf("a deliverable: %q %v", got, err)
	}
	for _, rel := range []string{"../x1.md", "../../secret.md", "/etc/hosts", "link.md", "missing.md", "."} {
		if got, err := Target(items, "x1", rel); err == nil {
			t.Errorf("%s: opened %q", rel, got)
		}
	}
}

func TestInOrcaFollowsTheSetting(t *testing.T) {
	t.Setenv("ORCA_PANE_KEY", "")
	t.Setenv("LAZYGTD_EDITOR", "")
	if InOrca() {
		t.Error("outside Orca")
	}
	t.Setenv("ORCA_PANE_KEY", "pane-1")
	if !InOrca() {
		t.Error("in Orca")
	}
	t.Setenv("LAZYGTD_EDITOR", "nvim")
	if InOrca() {
		t.Error("LAZYGTD_EDITOR=nvim wins")
	}
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}
