-- keybinder.lua - Hotkey binding module
-- Sets up keyboard shortcuts for layouts

local M = {}

local layout_manager = require("layout_manager")
local logger = hs.logger.new("keybinder", "info")

-- Track bound hotkeys for cleanup
local boundHotkeys = {}

-- Resolve modifier key aliases
-- Converts named modifiers (like "hyper") to actual key arrays
-- @param mods: String or table of modifiers
-- @param modifierDefs: Modifier definitions from config
-- @return table: Array of modifier keys
local function resolveModifiers(mods, modifierDefs)
    if type(mods) == "string" then
        -- Check if it's a defined alias
        if modifierDefs and modifierDefs[mods] then
            return modifierDefs[mods]
        else
            -- Single modifier key
            return {mods}
        end
    elseif type(mods) == "table" then
        -- Already an array of modifiers
        return mods
    end
    return {}
end

-- Set up hotkeys for all layouts
-- @param layouts: Array of layout configurations
-- @param modifierDefs: Modifier definitions (aliases)
function M.setup(layouts, modifierDefs)
    -- Clear existing hotkeys
    for _, hk in ipairs(boundHotkeys) do
        hk:delete()
    end
    boundHotkeys = {}

    if not layouts then
        logger:w("No layouts to bind")
        return
    end

    for _, layout in ipairs(layouts) do
        if layout.hotkey then
            local mods = resolveModifiers(layout.hotkey.mods, modifierDefs)
            local key = layout.hotkey.key

            if key then
                local modString = table.concat(mods, "+")
                local layoutName = layout.name or "unnamed"

                logger:i("Binding: " .. modString .. "+" .. key .. " -> " .. layoutName)

                local hk = hs.hotkey.bind(mods, key, function()
                    layout_manager.applyLayout(layout)
                end)

                table.insert(boundHotkeys, hk)
            else
                logger:w("Layout missing hotkey key: " .. (layout.name or "unnamed"))
            end
        end
    end

    logger:i("Bound " .. #boundHotkeys .. " hotkeys")
end

-- Get the number of bound hotkeys
-- @return number: Count of bound hotkeys
function M.getHotkeyCount()
    return #boundHotkeys
end

-- Unbind all hotkeys
function M.unbindAll()
    for _, hk in ipairs(boundHotkeys) do
        hk:delete()
    end
    boundHotkeys = {}
    logger:i("Unbound all hotkeys")
end

return M
