// Package watch tells lazygtd that the items changed: a write of gtd.py by anyone (an agent, the
// browser desk, lazygtd itself) adds a line to .log/changes.jsonl and rewrites items/<id>.md, and a
// save from Orca's editor rewrites the file only. Both folders are watched; the changes of a short
// while come as one call, as the desk's (src/desk.mjs DEBOUNCE_MS).
package watch

import (
	"path/filepath"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
)

// Debounce is how long the changes are gathered before one call.
const Debounce = 200 * time.Millisecond

// Relevant tells whether a changed file is one of the items or the change log: not git's,
// gtd.py's lock or a temporary file.
func Relevant(name string) bool {
	base := filepath.Base(name)
	return base != "" && !strings.HasPrefix(base, ".") && !strings.HasSuffix(base, ".lock") && !strings.HasSuffix(base, ".tmp") && !strings.HasSuffix(base, "~")
}

// Start watches <root>/items, its folders (the deliverables), and <root>/.log, and calls onChange
// after each burst of changes. It returns a function that stops watching.
func Start(root string, onChange func(), onError func(error)) (func(), error) {
	w, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}
	items := filepath.Join(root, "items")
	for _, dir := range []string{items, filepath.Join(root, ".log")} {
		if err := w.Add(dir); err != nil {
			w.Close()
			return nil, err
		}
	}
	// A deliverable added under items/<id>/ changes what the item lists.
	if entries, err := filepath.Glob(filepath.Join(items, "*")); err == nil {
		for _, e := range entries {
			_ = w.Add(e) // only folders take; a file fails and is watched through items/
		}
	}
	done := make(chan struct{})
	go func() {
		var timer *time.Timer
		for {
			select {
			case <-done:
				return
			case ev, ok := <-w.Events:
				if !ok {
					return
				}
				if ev.Op&fsnotify.Create != 0 && filepath.Dir(ev.Name) == items {
					_ = w.Add(ev.Name) // a new folder of deliverables
				}
				if !Relevant(ev.Name) {
					continue
				}
				if timer == nil {
					timer = time.AfterFunc(Debounce, onChange)
				} else {
					timer.Reset(Debounce)
				}
			case err, ok := <-w.Errors:
				if !ok {
					return
				}
				if onError != nil {
					onError(err)
				}
			}
		}
	}()
	return func() { close(done); w.Close() }, nil
}
