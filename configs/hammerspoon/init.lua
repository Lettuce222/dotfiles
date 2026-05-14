-- Hammerspoon Configuration
-- Window layout manager with YAML configuration

-- Get config directory path
local configPath = hs.configdir

-- Set up module search paths
package.path = package.path .. ";" .. configPath .. "/modules/?.lua"
package.path = package.path .. ";" .. configPath .. "/lib/?.lua"

-- Load modules
local yaml_loader = require("yaml_loader")
local layout_manager = require("layout_manager")
local keybinder = require("keybinder")

-- Configuration file path
local configFile = configPath .. "/layouts.yml"

-- Load and apply configuration
local function loadConfig()
    local config = yaml_loader.load(configFile)

    if not config then
        hs.alert.show("Failed to load layouts.yml", 3)
        return false
    end

    -- Initialize layout manager with settings
    layout_manager.init(config.settings or {})

    -- Set up hotkeys
    keybinder.setup(config.layouts, config.modifiers or {})

    local hotkeyCount = keybinder.getHotkeyCount()
    hs.alert.show("Hammerspoon loaded (" .. hotkeyCount .. " layouts)", 1.5)

    return true
end

-- Initial load
loadConfig()

-- Reload hotkey (Cmd+Alt+Ctrl+R)
hs.hotkey.bind({"cmd", "alt", "ctrl"}, "R", function()
    hs.reload()
end)

-- Helper function to get windows on a specific screen
local function getWindowsOnScreen(screen)
    local result = {}
    local allWindows = hs.window.allWindows()
    for _, w in ipairs(allWindows) do
        if w:screen():id() == screen:id() and w:isStandard() and not w:isMinimized() then
            table.insert(result, w)
        end
    end
    return result
end

-- Window focus navigation (vim-style)
-- Alt + H: Focus window to the left (same screen only)
hs.hotkey.bind({"alt"}, "H", function()
    local win = hs.window.focusedWindow()
    if win then
        local currentScreen = win:screen()
        local westWindows = win:windowsToWest(nil, true)
        for _, w in ipairs(westWindows) do
            if w:screen():id() == currentScreen:id() then
                w:focus()
                return
            end
        end
    end
end)

-- Alt + L: Focus window to the right (same screen only)
hs.hotkey.bind({"alt"}, "L", function()
    local win = hs.window.focusedWindow()
    if win then
        local currentScreen = win:screen()
        local eastWindows = win:windowsToEast(nil, true)
        for _, w in ipairs(eastWindows) do
            if w:screen():id() == currentScreen:id() then
                w:focus()
                return
            end
        end
    end
end)

-- Alt + J: Focus next monitor
hs.hotkey.bind({"alt"}, "J", function()
    local currentScreen = hs.screen.mainScreen()
    local win = hs.window.focusedWindow()
    if win then
        currentScreen = win:screen()
    end
    local nextScreen = currentScreen:next()

    -- Z-order順でウィンドウを取得し、対象モニターの最前面ウィンドウを見つける
    local orderedWindows = hs.window.orderedWindows()
    for _, w in ipairs(orderedWindows) do
        if w:screen():id() == nextScreen:id() and w:isStandard() and not w:isMinimized() then
            w:focus()
            return
        end
    end

    -- ウィンドウがない場合、マウスを移動してFinderにフォーカス
    local screenFrame = nextScreen:frame()
    local centerPoint = {
        x = screenFrame.x + screenFrame.w / 2,
        y = screenFrame.y + screenFrame.h / 2
    }
    hs.mouse.absolutePosition(centerPoint)
    local finder = hs.application.get("Finder")
    if finder then
        finder:activate()
    end
end)

-- Alt + K: Focus previous monitor
hs.hotkey.bind({"alt"}, "K", function()
    local currentScreen = hs.screen.mainScreen()
    local win = hs.window.focusedWindow()
    if win then
        currentScreen = win:screen()
    end
    local prevScreen = currentScreen:previous()

    -- Z-order順でウィンドウを取得し、対象モニターの最前面ウィンドウを見つける
    local orderedWindows = hs.window.orderedWindows()
    for _, w in ipairs(orderedWindows) do
        if w:screen():id() == prevScreen:id() and w:isStandard() and not w:isMinimized() then
            w:focus()
            return
        end
    end

    -- ウィンドウがない場合、マウスを移動してFinderにフォーカス
    local screenFrame = prevScreen:frame()
    local centerPoint = {
        x = screenFrame.x + screenFrame.w / 2,
        y = screenFrame.y + screenFrame.h / 2
    }
    hs.mouse.absolutePosition(centerPoint)
    local finder = hs.application.get("Finder")
    if finder then
        finder:activate()
    end
end)

-- Move window to next screen and apply layout
local function moveToNextScreenAndApply(layoutFn)
    local win = hs.window.focusedWindow()
    if not win then return end
    local nextScreen = win:screen():next()
    if nextScreen:id() ~= win:screen():id() then
        win:moveToScreen(nextScreen, false, true)
    end
    layoutFn()
end

-- Layout functions
local function applyLeftHalf()
    local win = hs.window.focusedWindow()
    if win then
        local frame = win:screen():frame()
        win:setFrame({
            x = frame.x,
            y = frame.y,
            w = frame.w / 2,
            h = frame.h
        })
    end
end

local function applyRightHalf()
    local win = hs.window.focusedWindow()
    if win then
        local frame = win:screen():frame()
        win:setFrame({
            x = frame.x + frame.w / 2,
            y = frame.y,
            w = frame.w / 2,
            h = frame.h
        })
    end
end

local function applyFullscreen()
    local win = hs.window.focusedWindow()
    if win then
        win:setFrame(win:screen():frame())
    end
end

-- Alt + U: Left half
hs.hotkey.bind({"alt"}, "U", applyLeftHalf)

-- Alt + I: Right half
hs.hotkey.bind({"alt"}, "I", applyRightHalf)

-- Alt + O: Fullscreen
hs.hotkey.bind({"alt"}, "O", applyFullscreen)

-- Alt + Shift + U/I/O: Move to next screen, then apply layout
hs.hotkey.bind({"alt", "shift"}, "U", function()
    moveToNextScreenAndApply(applyLeftHalf)
end)

hs.hotkey.bind({"alt", "shift"}, "I", function()
    moveToNextScreenAndApply(applyRightHalf)
end)

hs.hotkey.bind({"alt", "shift"}, "O", function()
    moveToNextScreenAndApply(applyFullscreen)
end)

-- Watch for config file changes and auto-reload
local configWatcher = hs.pathwatcher.new(configPath, function(files)
    for _, file in ipairs(files) do
        if file:match("layouts%.yml$") then
            hs.alert.show("Config changed, reloading...", 1)
            hs.timer.doAfter(0.5, function()
                hs.reload()
            end)
            break
        end
    end
end)
configWatcher:start()
