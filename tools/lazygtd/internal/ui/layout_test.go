package ui

import (
	"reflect"
	"testing"
)

func TestBoxHeights(t *testing.T) {
	rows := []int{5, 0, 2, 9, 1, 4, 0, 3}
	// Room for every box's first 3 rows: an empty box shows （なし）, the box worked in takes the rest.
	got := BoxHeights(rows, 3, 60, 3)
	want := []int{5, 3, 4, 0, 3, 5, 3, 5}
	want[3] = 60 - (5 + 3 + 4 + 3 + 5 + 3 + 5)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
	// A short terminal: the others give up rows so that the box worked in keeps MinFocused.
	got = BoxHeights(rows, 3, 30, 3)
	sum := 0
	for _, h := range got {
		sum += h
	}
	if sum != 30 || got[3]-2 < MinFocused {
		t.Errorf("got %v (sum %d)", got, sum)
	}
	// Too short for that: titles only, and the rest to the box worked in.
	got = BoxHeights(rows, 0, 18, 3)
	if got[1] != 2 || got[0] != 18-7*2 {
		t.Errorf("got %v", got)
	}
}
