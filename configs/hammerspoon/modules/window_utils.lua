-- window_utils.lua - Window manipulation utilities
-- Provides functions for window placement, app launching, and screen management

local M = {}

local settings = {}
local logger = hs.logger.new("window_utils", "info")

-- Border padding to match window border width in init.lua
local BORDER_PADDING = 2

-- Initialize with settings
-- @param cfg: Settings table with launch_wait, animation_duration
function M.init(cfg)
    settings = cfg or {}
    settings.launch_wait = settings.launch_wait or 1.5
    settings.animation_duration = settings.animation_duration or 0.2

    -- Set animation duration
    hs.window.animationDuration = settings.animation_duration
end

-- Get the screen that currently has focus
-- Falls back to mouse position screen, then main screen
-- @return hs.screen: The focused screen
function M.getFocusedScreen()
    local win = hs.window.focusedWindow()
    if win then
        return win:screen()
    end
    -- フォーカスウィンドウがない場合、マウスの位置からモニターを取得
    local mousePoint = hs.mouse.absolutePosition()
    local screens = hs.screen.allScreens()
    for _, screen in ipairs(screens) do
        local frame = screen:frame()
        if mousePoint.x >= frame.x and mousePoint.x < frame.x + frame.w and
           mousePoint.y >= frame.y and mousePoint.y < frame.y + frame.h then
            return screen
        end
    end
    return hs.screen.mainScreen()
end

-- Get an application by name or bundle ID, launching if necessary
-- @param appName: Application name (e.g., "Google Chrome")
-- @param bundleId: Bundle identifier (e.g., "com.google.Chrome")
-- @return hs.application: The application object, or nil on failure
function M.getOrLaunchApp(appName, bundleId)
    local app = nil

    -- Try to find by name first
    if appName then
        app = hs.application.get(appName)
    end

    -- Try bundle ID if name didn't work
    if not app and bundleId then
        app = hs.application.get(bundleId)
    end

    -- Launch if not running
    if not app then
        logger:i("Launching app: " .. (appName or bundleId))

        if bundleId then
            hs.application.launchOrFocusByBundleID(bundleId)
        else
            hs.application.launchOrFocus(appName)
        end

        -- Wait for app to launch
        local waitTime = settings.launch_wait or 1.5
        hs.timer.usleep(waitTime * 1000000)

        -- Try to get the app again
        if appName then
            app = hs.application.get(appName)
        end
        if not app and bundleId then
            app = hs.application.get(bundleId)
        end
    end

    return app
end

-- Get all visible windows from an application
-- Windows are sorted by ID for consistent ordering
-- @param app: Application object
-- @return table: Array of visible windows
function M.getAllWindows(app)
    if not app then return {} end

    local windows = app:allWindows()

    -- Filter to standard, non-minimized windows
    local visibleWindows = {}
    for _, win in ipairs(windows) do
        if win:isStandard() and not win:isMinimized() then
            table.insert(visibleWindows, win)
        end
    end

    -- Sort by window ID for consistent ordering
    table.sort(visibleWindows, function(a, b)
        return a:id() < b:id()
    end)

    return visibleWindows
end

-- Get a specific window instance from an application
-- Windows are sorted by ID for consistent ordering
-- @param app: Application object
-- @param instanceNum: Which window to get (1-indexed)
-- @return window, count: The window and total visible window count
function M.getWindowInstance(app, instanceNum)
    local visibleWindows = M.getAllWindows(app)
    local count = #visibleWindows

    -- Return nil if requested instance doesn't exist
    if instanceNum > count then
        logger:i("Window instance " .. instanceNum .. " not found (have " .. count .. ")")
        return nil, count
    end

    return visibleWindows[instanceNum], count
end

-- Place a window at a specific position on a screen
-- Position is specified as ratios (0.0 to 1.0)
-- Automatically applies border padding for window border visibility
-- @param win: Window to place
-- @param position: Table with x, y, w, h (all 0.0-1.0)
-- @param screen: Target screen (optional, defaults to focused screen)
-- @return boolean: Success
function M.placeWindow(win, position, screen)
    if not win or not position then return false end

    screen = screen or M.getFocusedScreen()
    local screenFrame = screen:frame()
    local padding = BORDER_PADDING

    -- Calculate pixel coordinates from ratios
    local newFrame = {
        x = screenFrame.x + (screenFrame.w * position.x),
        y = screenFrame.y + (screenFrame.h * position.y),
        w = screenFrame.w * position.w,
        h = screenFrame.h * position.h
    }

    -- Apply border padding on all edges
    newFrame.x = newFrame.x + padding
    newFrame.y = newFrame.y + padding
    newFrame.w = newFrame.w - (padding * 2)
    newFrame.h = newFrame.h - (padding * 2)

    win:setFrame(newFrame)
    return true
end

-- Create a new window for an application using Cmd+N
-- @param app: Application object
-- @param appName: Application name for AppleScript
-- @return window: The new window, or nil on failure
function M.createNewWindow(app, appName)
    if not app then return nil end

    logger:i("Creating new window for: " .. appName)

    -- Use AppleScript to send Cmd+N
    local script = string.format([[
        tell application "%s"
            activate
        end tell
        delay 0.2
        tell application "System Events"
            keystroke "n" using command down
        end tell
    ]], appName)

    local success, _, _ = hs.osascript.applescript(script)

    if not success then
        logger:w("Failed to create new window via AppleScript")
        return nil
    end

    -- Wait for window to be created
    hs.timer.usleep(500000)  -- 0.5 seconds

    -- Return the focused window (should be the new one)
    return app:focusedWindow()
end

-- Move a window to a specific screen if not already there
-- @param win: Window to move
-- @param targetScreen: Screen to move to
function M.moveToScreen(win, targetScreen)
    if not win or not targetScreen then return end

    if win:screen():id() ~= targetScreen:id() then
        win:moveToScreen(targetScreen, false, true)
    end
end

return M
