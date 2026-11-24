// lazygtd is the hub's desk (hub v2's GTD board) in a terminal, after lazygit: the lists on the
// left, the selected item on the right. Every read and write goes through gtd.py (--by user), as
// the browser desk's, so people and agents write the same way and share one history.
package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/Lettuce222/lazygtd/internal/gtd"
	"github.com/Lettuce222/lazygtd/internal/ui"
)

var version = "0.1.0"

func main() {
	home := flag.String("gtd-home", "", "the GTD folder (GTD_HOME; by default gtd.py's: ${AGENT_ORCHESTRATOR_HOME:-~/hub}/gtd)")
	script := flag.String("gtd-py", gtd.DefaultScript(), "gtd.py to run (LAZYGTD_GTD_PY)")
	showVersion := flag.Bool("version", false, "print the version")
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "usage: lazygtd [--gtd-home DIR] [--gtd-py PATH]\n\nThe hub's desk in a terminal. Keys: ? in the screen.\n\n")
		flag.PrintDefaults()
	}
	flag.Parse()
	if *showVersion {
		fmt.Println("lazygtd", version)
		return
	}
	var env []string
	if *home != "" {
		env = append(env, "GTD_HOME="+*home)
	}
	if _, err := os.Stat(*script); err != nil {
		fmt.Fprintf(os.Stderr, "lazygtd: gtd.py が無い: %s\n", *script)
		os.Exit(1)
	}
	if err := ui.Run(gtd.New(*script, env)); err != nil {
		fmt.Fprintf(os.Stderr, "lazygtd: %v\n", err)
		os.Exit(1)
	}
}
