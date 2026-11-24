package render

import (
	"regexp"
	"sort"
	"strings"
)

// The talk with the orchestrator is kept in two sections of an item's body (gtd.py writes them):
// 「窓口の返事」, a `### MM/DD HH:MM` heading over each answer in Markdown, and
// 「あなたの番への返事」, one `- MM/DD HH:MM: text` line for each reply of the user. The detail
// shows them as one talk, in the order they were said.

const (
	answersSection = "窓口の返事"
	repliesSection = "あなたの番への返事"
)

// Said is one turn of the talk.
type Said struct {
	When string // "MM/DD HH:MM", or "MM/DD"
	Who  string // 窓口, あなた
	Text string // Markdown
}

var (
	answerHead = regexp.MustCompile(`^###\s+(\d{2}/\d{2}(?: \d{2}:\d{2})?)\s*$`)
	replyLine  = regexp.MustCompile(`^[-*]\s+(\d{2}/\d{2}(?: \d{2}:\d{2})?):\s?(.*)$`)
)

// SplitTalk takes the two sections out of a body: what is left, and the talk in the order it was
// said (by time, an answer before a reply of the same minute).
func SplitTalk(body string) (string, []Said) {
	var rest []string
	var talk []Said
	section := ""
	var cur *Said
	flush := func() {
		if cur != nil {
			cur.Text = strings.Trim(cur.Text, "\n")
			talk = append(talk, *cur)
			cur = nil
		}
	}
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(line, "## ") {
			flush()
			section = strings.TrimSpace(strings.TrimPrefix(line, "## "))
			if section != answersSection && section != repliesSection {
				rest = append(rest, line)
			}
			continue
		}
		switch section {
		case answersSection:
			if m := answerHead.FindStringSubmatch(line); m != nil {
				flush()
				cur = &Said{When: m[1], Who: "窓口"}
			} else if cur != nil {
				cur.Text += line + "\n"
			}
		case repliesSection:
			if m := replyLine.FindStringSubmatch(line); m != nil {
				flush()
				talk = append(talk, Said{When: m[1], Who: "あなた", Text: m[2]})
			}
		default:
			rest = append(rest, line)
		}
	}
	flush()
	sort.SliceStable(talk, func(i, j int) bool { return talk[i].When < talk[j].When })
	return strings.TrimRight(strings.Join(rest, "\n"), "\n"), talk
}

// TalkMarkdown writes the talk as Markdown for the detail.
func TalkMarkdown(talk []Said) string {
	if len(talk) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("## 窓口とのやり取り\n")
	for _, s := range talk {
		b.WriteString("\n**" + s.Who + "** " + s.When + "\n\n")
		if s.Who == "あなた" {
			b.WriteString("> " + s.Text + "\n")
		} else {
			b.WriteString(s.Text + "\n")
		}
	}
	return b.String()
}
