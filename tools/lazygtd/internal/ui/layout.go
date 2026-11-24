package ui

// The left column's boxes, as on the desk (desk/sections.mjs): the box worked in is large and the
// others show their first rows. When the terminal is short, the other boxes give up rows, down to
// their frame and title only, so that the box worked in keeps MinFocused rows.

// MinFocused is the rows the box worked in keeps, when the terminal allows.
const MinFocused = 5

// BoxHeights are the heights (frames included) of boxes whose row counts are rows, in a column of
// height total, with the box at index focus worked in.
func BoxHeights(rows []int, focus, total, smallRows int) []int {
	out := make([]int, len(rows))
	for small := smallRows; small >= 0; small-- {
		used := 0
		for i, n := range rows {
			if i == focus {
				continue
			}
			shown := min(n, small)
			if n == 0 && small > 0 {
				shown = 1 // （なし）
			}
			out[i] = shown + 2
			used += out[i]
		}
		left := total - used
		if left-2 >= MinFocused || small == 0 {
			out[focus] = max(left, 2)
			return out
		}
	}
	return out
}
