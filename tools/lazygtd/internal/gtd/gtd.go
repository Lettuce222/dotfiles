// Package gtd runs gtd.py, the script that owns the format of hub v2's items
// (<gtd>/items/<id>.md). lazygtd never writes an item itself: every write is one gtd.py
// command with --by user, so lazygtd, the browser desk, the editor and the agents all go
// through the same checks and the same history (.log/changes.jsonl and the git of GTD_HOME).
package gtd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// Exit codes of gtd.py.
const (
	ExitNotFound = 1
	ExitBadValue = 2
	ExitConflict = 3
)

// Error is a gtd.py command that exited nonzero: Msg is gtd.py's one line to the person
// (the part after `gtd.py <command>: `), Code its exit code.
type Error struct {
	Code int
	Msg  string
}

func (e *Error) Error() string { return e.Msg }

// IsConflict tells whether err is gtd.py's conflict (someone changed the item first).
func IsConflict(err error) bool {
	var ge *Error
	return errors.As(err, &ge) && ge.Code == ExitConflict
}

// Client runs gtd.py.
type Client struct {
	Python  string
	Script  string
	Env     []string // added to the process environment (GTD_HOME, …)
	Timeout time.Duration
	// run is replaced by the tests.
	run func(ctx context.Context, name string, args []string, env []string) (stdout, stderr []byte, code int, err error)
}

// DefaultScript is where the agents-orchestrator skill keeps gtd.py.
func DefaultScript() string {
	if s := os.Getenv("LAZYGTD_GTD_PY"); s != "" {
		return s
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "skills", "agents-orchestrator", "scripts", "gtd.py")
}

// New returns a client of the gtd.py at script.
func New(script string, env []string) *Client {
	return &Client{Python: "python3", Script: script, Env: env, Timeout: 20 * time.Second}
}

var prefix = regexp.MustCompile(`^gtd\.py [\w-]+: `)

func execRun(ctx context.Context, name string, args []string, env []string) ([]byte, []byte, int, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = append(os.Environ(), env...)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	err := cmd.Run()
	code := 0
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		code = ee.ExitCode()
		err = nil
	}
	return out.Bytes(), errb.Bytes(), code, err
}

// Run runs `gtd.py <args>` and returns its stdout.
func (c *Client) Run(args ...string) ([]byte, error) {
	run := c.run
	if run == nil {
		run = execRun
	}
	timeout := c.Timeout
	if timeout == 0 {
		timeout = 20 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	out, errOut, code, err := run(ctx, c.Python, append([]string{c.Script}, args...), c.Env)
	if err != nil {
		return nil, &Error{Code: -1, Msg: fmt.Sprintf("gtd.py を動かせない: %v", err)}
	}
	if code != 0 {
		lines := strings.Split(strings.TrimSpace(string(errOut)), "\n")
		line := strings.TrimSpace(lines[len(lines)-1])
		if line == "" {
			line = fmt.Sprintf("gtd.py が %d で終わった", code)
		}
		return nil, &Error{Code: code, Msg: prefix.ReplaceAllString(line, "")}
	}
	return out, nil
}

// State reads every item (gtd.py json).
func (c *Client) State() (*State, error) {
	out, err := c.Run("json")
	if err != nil {
		return nil, err
	}
	var s State
	if err := json.Unmarshal(out, &s); err != nil {
		return nil, &Error{Code: -1, Msg: fmt.Sprintf("gtd.py の出力を読めない: %v", err)}
	}
	return &s, nil
}

// The writes. Each one is a gtd.py command with --by user and, where gtd.py checks it, the hash
// the item had when it was read. Values go as --flag=value so that text that looks like a flag is
// never read as one.

func hashArg(hash string) []string {
	if hash == "" {
		return nil
	}
	return []string{"--hash=" + hash}
}

func (c *Client) write(args ...string) error {
	_, err := c.Run(append(args, "--by", "user")...)
	return err
}

// Add makes a new item in a list ("" for inbox), with a body ("" for none). An item of next is the
// user's own (actor: me), as the desk's.
func (c *Client) Add(list, title, body string) error {
	args := []string{"add", "--title=" + title}
	if list != "" {
		args = append(args, "--list="+list)
	}
	if list == "next" {
		args = append(args, "--actor=me")
	}
	if body != "" {
		args = append(args, "--body="+body)
	}
	return c.write(args...)
}

// Ask hands an item to the orchestrator: an agent's item in next with no worker yet, which the Hub
// tells the orchestrator of (src/agent-items.mjs), and the orchestrator starts a worker for.
func (c *Client) Ask(id, hash string) error {
	return c.write(append([]string{"set", id, "actor=agent", "list=next"}, hashArg(hash)...)...)
}

// ToCalendar makes an item the next action of putting it in the calendar: the user's own, in next,
// its title led by prefix.
func (c *Client) ToCalendar(id, title, hash string) error {
	return c.write(append([]string{"set", id, "title=" + title, "list=next", "actor=me"}, hashArg(hash)...)...)
}

// StepAdd adds a new step at the end of a project.
func (c *Client) StepAdd(project, title string) error {
	return c.write("step", "add", project, "--title="+title)
}

// StepMove puts a step at position pos (from 1) of its project.
func (c *Client) StepMove(project, id string, pos int) error {
	return c.write("step", "move", project, id, fmt.Sprint(pos))
}

// Move moves an item to another list.
func (c *Client) Move(id, list, hash string) error {
	return c.write(append([]string{"move", id, list}, hashArg(hash)...)...)
}

// Done marks an item done.
func (c *Client) Done(id, hash string) error {
	return c.write(append([]string{"done", id}, hashArg(hash)...)...)
}

// Say adds the user's reply to 「あなたの番への返事」 and marks that the user waits for the
// orchestrator's answer (asked). gtd.py appends it, so it takes no hash: two replies never conflict.
func (c *Client) Say(id, text string) error { return c.write("say", id, "--text="+text) }

// Read marks the orchestrator's answers to an item read.
func (c *Client) Read(id string) error { return c.write("read", id) }
