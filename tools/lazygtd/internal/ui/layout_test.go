package ui

import (
	"reflect"
	"testing"
)

func TestPanelHeightsStayEqual(t *testing.T) {
	if got := PanelHeights(5, 44); !reflect.DeepEqual(got, []int{9, 9, 9, 9, 8}) {
		t.Errorf("got %v", got)
	}
	if got := PanelHeights(5, 20); !reflect.DeepEqual(got, []int{4, 4, 4, 4, 4}) {
		t.Errorf("got %v", got)
	}
}

func TestPopupIsLazygits(t *testing.T) {
	// 4/7 of the screen, at least 80, at most 90.
	for maxX, want := range map[int]int{100: 80, 140: 80, 160: 90, 300: 90, 60: 58} {
		if got := popupWidth(maxX); got != want {
			t.Errorf("%d: got %d, want %d", maxX, got, want)
		}
	}
	x0, y0, x1, y1 := popupBox(160, 45, 90, 4)
	if x1-x0+1 != 90 || y1-y0+1 != 6 {
		t.Errorf("box %d %d %d %d", x0, y0, x1, y1)
	}
	// At most 3/4 of the height.
	_, y0, _, y1 = popupBox(160, 40, 90, 100)
	if y1-y0+1 > 30 {
		t.Errorf("too tall: %d", y1-y0+1)
	}
}

func TestOptionsLineIsCutWithAnEllipsis(t *testing.T) {
	if got := stripANSI("\x1b[38;2;1;2;3mab\x1b[0mc"); got != "abc" {
		t.Errorf("got %q", got)
	}
}
