-- yaml_loader.lua - YAML configuration file loader
-- Loads and parses YAML configuration files for Hammerspoon

local M = {}

local tinyyaml = require("tinyyaml")
local logger = hs.logger.new("yaml_loader", "info")

-- Load and parse a YAML file
-- @param filepath: Absolute path to the YAML file
-- @return table: Parsed YAML content, or nil on error
function M.load(filepath)
    local file = io.open(filepath, "r")
    if not file then
        logger:e("Cannot open file: " .. filepath)
        return nil
    end

    local content = file:read("*all")
    file:close()

    if not content or content == "" then
        logger:e("File is empty: " .. filepath)
        return nil
    end

    local success, result = pcall(function()
        return tinyyaml.parse(content)
    end)

    if not success then
        logger:e("YAML parse error: " .. tostring(result))
        return nil
    end

    logger:i("Successfully loaded: " .. filepath)
    return result
end

-- Reload the configuration file
-- @param filepath: Absolute path to the YAML file
-- @return table: Parsed YAML content, or nil on error
function M.reload(filepath)
    logger:i("Reloading configuration...")
    return M.load(filepath)
end

return M
