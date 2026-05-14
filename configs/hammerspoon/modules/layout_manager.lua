-- layout_manager.lua - Layout application and variant cycling
-- Manages window layouts and handles cycling through variants and windows

local M = {}

local window_utils = require("window_utils")
local logger = hs.logger.new("layout_manager", "info")

-- Track current variant index for each layout
local currentVariantIndex = {}

-- Track current window cycle offset for each layout
-- When same hotkey is pressed multiple times, cycle through available windows
local currentWindowOffset = {}

-- Initialize the layout manager
-- @param settings: Configuration settings
function M.init(settings)
    window_utils.init(settings)
    currentVariantIndex = {}
    currentWindowOffset = {}
end

-- Apply a layout configuration
-- Handles both simple layouts and variant cycling
-- @param layout: Layout configuration table
function M.applyLayout(layout)
    if not layout then return end

    local layoutName = layout.name or "unnamed"
    logger:i("Applying layout: " .. layoutName)

    -- Get the focused screen (this is where windows will be placed)
    local targetScreen = window_utils.getFocusedScreen()
    logger:i("Target screen: " .. targetScreen:name())

    local windows = nil

    -- Handle variants (cyclic layouts)
    if layout.variants and #layout.variants > 0 then
        -- Get current index (default to 1)
        local idx = currentVariantIndex[layoutName] or 1

        -- Get windows from current variant
        windows = layout.variants[idx].windows
        local description = layout.variants[idx].description or ("Variant " .. idx)

        logger:i("Using variant " .. idx .. "/" .. #layout.variants .. ": " .. description)
        hs.alert.show(layoutName .. ": " .. description, 1)

        -- Update index for next press (cycle back to 1)
        currentVariantIndex[layoutName] = (idx % #layout.variants) + 1

        -- Reset window offset when variant changes
        currentWindowOffset[layoutName] = 0
    else
        -- Simple layout without variants
        windows = layout.windows

        -- Increment window offset for cycling through windows
        local offset = currentWindowOffset[layoutName] or 0
        currentWindowOffset[layoutName] = offset + 1
    end

    if not windows or #windows == 0 then
        logger:w("No windows defined for layout: " .. layoutName)
        return
    end

    -- Get current window offset
    local windowOffset = currentWindowOffset[layoutName] or 0

    -- Pre-create windows if needed (count required windows per app)
    M.ensureWindowsExist(windows)

    -- Place each window
    local placedWindows = {}
    for i, winConfig in ipairs(windows) do
        local win = M.placeWindowFromConfig(winConfig, targetScreen, layoutName, windowOffset, i)
        if win then
            table.insert(placedWindows, win)
        end
    end

    -- Focus the first window first to escape fullscreen space
    -- (macOS fullscreen apps are in a separate space)
    if #placedWindows > 0 then
        placedWindows[1]:focus()
        hs.timer.usleep(50000)  -- 0.05 seconds for space transition
    end

    -- Raise all windows to front (in reverse order so first window ends up on top)
    for i = #placedWindows, 1, -1 do
        placedWindows[i]:raise()
    end

    -- Focus the first window again to ensure it's on top
    if #placedWindows > 0 then
        placedWindows[1]:focus()
    end
end

-- Place a single window based on configuration
-- @param winConfig: Window configuration from layouts.yml
-- @param targetScreen: Screen to place window on
-- @param layoutName: Name of the layout (for tracking window cycles)
-- @param windowOffset: Offset for cycling through windows
-- @param windowIndex: Index of this window in the layout
-- @return window: The placed window, or nil on failure
function M.placeWindowFromConfig(winConfig, targetScreen, layoutName, windowOffset, windowIndex)
    local appName = winConfig.app
    local bundleId = winConfig.bundleId
    local position = winConfig.position

    if not position then
        logger:w("No position specified for: " .. (appName or bundleId or "unknown"))
        return nil
    end

    -- Get or launch the application
    local app = window_utils.getOrLaunchApp(appName, bundleId)
    if not app then
        logger:w("Failed to get app: " .. (appName or bundleId or "unknown"))
        return nil
    end

    local win = nil
    local windowCount = 0

    -- Check if instance is explicitly specified
    if winConfig.instance then
        -- Use explicit instance number
        win, windowCount = window_utils.getWindowInstance(app, winConfig.instance)

        -- Create new windows if needed
        if not win and winConfig.instance > windowCount then
            local needCount = winConfig.instance - windowCount
            logger:i("Creating " .. needCount .. " new window(s) for " .. appName)

            for i = 1, needCount do
                win = window_utils.createNewWindow(app, appName)
                if win then
                    hs.timer.usleep(300000)  -- 0.3 seconds between windows
                end
            end

            -- Re-fetch the window instance
            win = window_utils.getWindowInstance(app, winConfig.instance)
        end
    else
        -- No instance specified: cycle through available windows
        local allWindows = window_utils.getAllWindows(app)
        windowCount = #allWindows

        if windowCount > 0 then
            -- Calculate which window to use based on offset
            -- Use windowIndex to differentiate multiple apps in same layout
            local cycleIndex = ((windowOffset + windowIndex - 1) % windowCount) + 1
            win = allWindows[cycleIndex]

            if windowCount > 1 then
                logger:i("Cycling " .. appName .. ": window " .. cycleIndex .. "/" .. windowCount)
            end
        else
            -- No windows exist, create one
            logger:i("No windows for " .. appName .. ", creating new window")
            win = window_utils.createNewWindow(app, appName)
            if not win then
                -- Try getting any window after launch
                hs.timer.usleep(500000)
                win = window_utils.getWindowInstance(app, 1)
            end
        end
    end

    if not win then
        logger:w("Failed to get window for " .. (appName or "unknown"))
        return nil
    end

    -- Move to target screen if needed
    window_utils.moveToScreen(win, targetScreen)

    -- Place the window
    window_utils.placeWindow(win, position, targetScreen)

    return win
end

-- Ensure enough windows exist for each app in the layout
-- @param windows: Array of window configurations
function M.ensureWindowsExist(windows)
    -- Count how many windows are needed per app
    local appWindowCount = {}
    for _, winConfig in ipairs(windows) do
        local appName = winConfig.app
        if appName and not winConfig.instance then
            appWindowCount[appName] = (appWindowCount[appName] or 0) + 1
        end
    end

    -- Ensure each app has enough windows
    for appName, requiredCount in pairs(appWindowCount) do
        local app = window_utils.getOrLaunchApp(appName, nil)
        if app then
            local currentWindows = window_utils.getAllWindows(app)
            local currentCount = #currentWindows

            if currentCount < requiredCount then
                local needCount = requiredCount - currentCount
                logger:i("Creating " .. needCount .. " new window(s) for " .. appName)

                for i = 1, needCount do
                    window_utils.createNewWindow(app, appName)
                    hs.timer.usleep(300000)  -- 0.3 seconds between windows
                end
            end
        end
    end
end

-- Reset variant cycling for a layout
-- @param layoutName: Name of the layout to reset
function M.resetVariant(layoutName)
    currentVariantIndex[layoutName] = 1
    currentWindowOffset[layoutName] = 0
end

-- Reset all variant cycling
function M.resetAllVariants()
    currentVariantIndex = {}
    currentWindowOffset = {}
end

return M
