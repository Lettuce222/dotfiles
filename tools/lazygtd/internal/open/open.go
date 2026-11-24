// Package open opens an item, or one of its deliverables, for the user to edit: in Orca's editor
// when lazygtd runs in an Orca terminal (`orca file open --focus`), else in nvim on the terminal
// lazygtd runs in. Only the item's file and the files under items/<id>/ are opened (as the browser
// desk's fileOf).
package open

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// InOrca tells whether lazygtd runs in a terminal of Orca. Orca sets ORCA_PANE_KEY in its
// terminals (the hooks of the dotfiles read it); LAZYGTD_EDITOR=nvim or =orca decides instead.
func InOrca() bool {
	switch os.Getenv("LAZYGTD_EDITOR") {
	case "orca":
		return true
	case "nvim":
		return false
	}
	return os.Getenv("ORCA_PANE_KEY") != ""
}

// Target is the file to open for an item: items/<id>.md when rel is "", else items/<id>/<rel>.
// It errs when the file would be outside them (a link out included) or is not there.
func Target(itemsDir, id, rel string) (string, error) {
	if rel == "" {
		return check(itemsDir, filepath.Join(itemsDir, id+".md"))
	}
	if filepath.IsAbs(rel) || strings.ContainsRune(rel, 0) {
		return "", errors.New("開けるのは項目と、その成果物だけ")
	}
	folder := filepath.Join(itemsDir, id)
	target := filepath.Clean(filepath.Join(folder, rel))
	r, err := filepath.Rel(folder, target)
	if err != nil || r == "." || strings.HasPrefix(r, "..") {
		return "", errors.New("開けるのは項目と、その成果物だけ")
	}
	return check(itemsDir, target)
}

func check(itemsDir, target string) (string, error) {
	st, err := os.Stat(target)
	if err != nil || !st.Mode().IsRegular() {
		return "", errors.New("ファイルが無い")
	}
	real, err1 := filepath.EvalSymlinks(target)
	items, err2 := filepath.EvalSymlinks(itemsDir)
	if err1 != nil || err2 != nil {
		return "", errors.New("ファイルを確かめられない")
	}
	if r, err := filepath.Rel(items, real); err != nil || strings.HasPrefix(r, "..") || filepath.IsAbs(r) {
		return "", errors.New("開けるのは項目と、その成果物だけ")
	}
	return target, nil
}

// Orca opens path in Orca's editor, in the workspace that holds it, and brings the user to it.
// The CLI infers the workspace from the working directory, so it runs in the file's folder.
func Orca(path string) error {
	cmd := exec.Command("orca", "file", "open", path, "--focus", "--json")
	cmd.Dir = filepath.Dir(path)
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if len(msg) > 200 {
			msg = msg[:200]
		}
		return fmt.Errorf("orca file open が失敗した: %s", msg)
	}
	return nil
}

// Nvim is the command that edits path on this terminal: $EDITOR, else nvim (SPEC 6.4). The ui
// suspends the screen while it runs.
func Nvim(path string) *exec.Cmd {
	editor := strings.Fields(os.Getenv("EDITOR"))
	if len(editor) == 0 {
		editor = []string{"nvim"}
	}
	cmd := exec.Command(editor[0], append(editor[1:], path)...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	return cmd
}
