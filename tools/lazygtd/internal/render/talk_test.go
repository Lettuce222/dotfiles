package render

import (
	"reflect"
	"strings"
	"testing"
)

func TestSplitTalkOrdersTheTalk(t *testing.T) {
	body := `- メモの行

## あなたの番への返事

- 11/24 17:50: 最初の問い
- 11/24 18:10: 二つ目

## 窓口の返事

### 11/24 18:00

#### 案

- configs/x に置く

### 11/24 18:30

了解です

## メモ

- あとで`
	rest, talk := SplitTalk(body)
	want := []Said{
		{"11/24 17:50", "あなた", "最初の問い"},
		{"11/24 18:00", "窓口", "#### 案\n\n- configs/x に置く"},
		{"11/24 18:10", "あなた", "二つ目"},
		{"11/24 18:30", "窓口", "了解です"},
	}
	if !reflect.DeepEqual(talk, want) {
		t.Errorf("got %#v", talk)
	}
	if rest != "- メモの行\n\n## メモ\n\n- あとで" {
		t.Errorf("rest: %q", rest)
	}
	md := TalkMarkdown(talk)
	if !strings.Contains(md, "**あなた** 11/24 17:50") || !strings.Contains(md, "> 二つ目") {
		t.Errorf("markdown: %s", md)
	}
}

func TestNoTalk(t *testing.T) {
	rest, talk := SplitTalk("## 背景\n\n本文")
	if len(talk) != 0 || rest != "## 背景\n\n本文" || TalkMarkdown(nil) != "" {
		t.Errorf("%q %v", rest, talk)
	}
}
