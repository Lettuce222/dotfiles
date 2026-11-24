#Requires AutoHotkey v2.0
#SingleInstance Ignore
; Window placement and focus only. All ordinary key remaps live in Kanata.
; Ctrl+Alt+Shift+F12 exits. Tray menu can also suspend or exit.
^!+F12::ExitApp()
#HotIf IsDesktopWindow()
!u::Tile("left")
!i::Tile("right")
!o::Tile("full")
!+u::Tile("left", 1)
!+i::Tile("right", 1)
!+o::Tile("full", 1)
!h::FocusSide(-1)
!l::FocusSide(1)
!j::FocusMonitor(1)
!k::FocusMonitor(-1)
#HotIf

IsDesktopWindow() {
    h := WinExist("A")
    if !h
        return false
    try return IsCandidate(h) && !RegExMatch(WinGetProcessName("ahk_id " h), "i)^(League of Legends|VALORANT-Win64-Shipping|TslGame)\.exe$")
    catch
        return false
}
IsCandidate(h) {
    id := "ahk_id " h
    try return WinGetMinMax(id) != -1 && !RegExMatch(WinGetClass(id), "^(Progman|WorkerW|Shell_TrayWnd|Shell_SecondaryTrayWnd)$")
        && !(WinGetExStyle(id) & 0x80) && WinGetTitle(id) != ""
    catch
        return false
}
Center(h) {
    WinGetPos(&x, &y, &w, &hgt, "ahk_id " h)
    return [x + w/2, y + hgt/2]
}
MonitorFor(x, y) {
    best := 1
    dist := 1e30
    Loop MonitorGetCount() {
        MonitorGet(A_Index, &l, &t, &r, &b)
        d := Max(l-x, 0, x-r)**2 + Max(t-y, 0, y-b)**2
        if (d < dist) {
            best := A_Index
            dist := d
        }
    }
    return best
}
StepMonitor(m, delta) {
    n := MonitorGetCount()
    return Mod(m-1+delta+n, n)+1
}
Tile(where, delta := 0) {
    h := WinExist("A")
    if !h
        return
    id := "ahk_id " h
    try {
        c := Center(h)
        idx := StepMonitor(MonitorFor(c[1], c[2]), delta)
        MonitorGetWorkArea(idx, &l, &t, &r, &b)
        w := r-l
        split := Floor(w/2)
        if WinGetMinMax(id)
            WinRestore(id)
        if where = "left"
            WinMove(l, t, split, b-t, id)
        else if where = "right"
            WinMove(l+split, t, w-split, b-t, id)
        else
            WinMove(l, t, w, b-t, id)
    }
}
FocusSide(delta) {
    h := WinExist("A")
    if !h
        return
    c := Center(h)
    idx := MonitorFor(c[1], c[2])
    best := 0
    dist := 1e30
    for other in WinGetList() {
        if other = h || !IsCandidate(other)
            continue
        try {
            o := Center(other)
            dx := (o[1]-c[1])*delta
            if dx <= 0 || MonitorFor(o[1], o[2]) != idx
                continue
            d := dx**2 + (o[2]-c[2])**2
            if d < dist {
                best := other
                dist := d
            }
        }
    }
    if best
        try WinActivate("ahk_id " best)
}
FocusMonitor(delta) {
    h := WinExist("A")
    if !h || MonitorGetCount() < 2
        return
    c := Center(h)
    idx := StepMonitor(MonitorFor(c[1], c[2]), delta)
    for other in WinGetList() {
        if other = h || !IsCandidate(other)
            continue
        try {
            o := Center(other)
            if MonitorFor(o[1], o[2]) = idx {
                WinActivate("ahk_id " other)
                return
            }
        }
    }
}
