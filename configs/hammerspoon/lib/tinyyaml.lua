-- tinyyaml.lua - Simple YAML parser for Hammerspoon layouts
-- Supports the subset of YAML needed for layouts.yml configuration
-- Based on the structure of peposso/lua-tinyyaml (MIT License)

local M = {}

-- Trim whitespace from string
local function trim(s)
    return s:match("^%s*(.-)%s*$")
end

-- Check if string is a comment or empty line
local function isCommentOrEmpty(line)
    local trimmed = trim(line)
    return trimmed == "" or trimmed:sub(1, 1) == "#"
end

-- Get indentation level of a line
local function getIndent(line)
    local spaces = line:match("^(%s*)")
    return #spaces
end

-- Parse a scalar value (string, number, boolean, null)
local function parseScalar(value)
    if value == nil then return nil end

    local trimmed = trim(value)

    -- null values
    if trimmed == "null" or trimmed == "~" or trimmed == "" then
        return nil
    end

    -- boolean values
    if trimmed == "true" or trimmed == "True" or trimmed == "TRUE" then
        return true
    end
    if trimmed == "false" or trimmed == "False" or trimmed == "FALSE" then
        return false
    end

    -- number values
    local num = tonumber(trimmed)
    if num then
        return num
    end

    -- quoted strings
    if trimmed:sub(1, 1) == '"' and trimmed:sub(-1) == '"' then
        return trimmed:sub(2, -2)
    end
    if trimmed:sub(1, 1) == "'" and trimmed:sub(-1) == "'" then
        return trimmed:sub(2, -2)
    end

    -- unquoted string
    return trimmed
end

-- Parse flow-style array: [item1, item2, ...]
local function parseFlowArray(str)
    local result = {}
    local content = str:match("^%[(.*)%]$")
    if not content then return nil end

    -- Simple split by comma (doesn't handle nested structures)
    for item in content:gmatch("[^,]+") do
        local value = parseScalar(trim(item))
        if value ~= nil then
            table.insert(result, value)
        end
    end

    return result
end

-- Parse flow-style object: {key: value, key2: value2}
local function parseFlowObject(str)
    local result = {}
    local content = str:match("^{(.*)}$")
    if not content then return nil end

    -- Split by comma and parse key-value pairs
    for pair in content:gmatch("[^,]+") do
        local key, value = pair:match("^%s*([^:]+):%s*(.*)%s*$")
        if key then
            result[trim(key)] = parseScalar(value)
        end
    end

    return result
end

-- Main parse function
function M.parse(yaml)
    local lines = {}
    for line in yaml:gmatch("[^\r\n]+") do
        table.insert(lines, line)
    end

    local index = 1

    local function parseValue(minIndent)
        while index <= #lines and isCommentOrEmpty(lines[index]) do
            index = index + 1
        end

        if index > #lines then
            return nil
        end

        local line = lines[index]
        local indent = getIndent(line)

        if indent < minIndent then
            return nil
        end

        local content = trim(line)

        -- Check for flow-style array
        if content:match("^%[.*%]$") then
            index = index + 1
            return parseFlowArray(content)
        end

        -- Check for flow-style object
        if content:match("^{.*}$") then
            index = index + 1
            return parseFlowObject(content)
        end

        -- Check for sequence item (- value)
        if content:sub(1, 2) == "- " or content == "-" then
            local result = {}

            while index <= #lines do
                while index <= #lines and isCommentOrEmpty(lines[index]) do
                    index = index + 1
                end

                if index > #lines then break end

                local currentLine = lines[index]
                local currentIndent = getIndent(currentLine)

                if currentIndent < indent then
                    break
                end

                if currentIndent > indent then
                    break
                end

                local currentContent = trim(currentLine)

                if currentContent:sub(1, 2) ~= "- " and currentContent ~= "-" then
                    break
                end

                -- Get the value after "- "
                local itemValue = currentContent:sub(3)

                -- Check if it's a nested map (- key: value)
                local key, val = itemValue:match("^([^:]+):%s*(.*)$")
                if key then
                    -- It's a map starting with this key
                    index = index + 1
                    local item = {}
                    item[trim(key)] = parseScalar(val) ~= "" and parseScalar(val) or nil

                    -- Check for more keys at higher indent
                    while index <= #lines do
                        while index <= #lines and isCommentOrEmpty(lines[index]) do
                            index = index + 1
                        end

                        if index > #lines then break end

                        local nextLine = lines[index]
                        local nextIndent = getIndent(nextLine)

                        -- Keys belong to this item if indented more than the "-"
                        if nextIndent <= indent then
                            break
                        end

                        local nextContent = trim(nextLine)

                        -- Check for nested sequence
                        if nextContent:sub(1, 2) == "- " then
                            break
                        end

                        local k, v = nextContent:match("^([^:]+):%s*(.*)$")
                        if k then
                            local trimmedKey = trim(k)
                            local trimmedVal = trim(v)

                            -- Check for flow-style value
                            if trimmedVal:match("^%[.*%]$") then
                                item[trimmedKey] = parseFlowArray(trimmedVal)
                            elseif trimmedVal:match("^{.*}$") then
                                item[trimmedKey] = parseFlowObject(trimmedVal)
                            elseif trimmedVal == "" then
                                -- Nested structure
                                index = index + 1
                                item[trimmedKey] = parseValue(nextIndent + 1)
                            else
                                item[trimmedKey] = parseScalar(trimmedVal)
                            end

                            if trimmedVal ~= "" then
                                index = index + 1
                            end
                        else
                            break
                        end
                    end

                    table.insert(result, item)
                elseif itemValue:match("^%[.*%]$") then
                    -- Flow array as item
                    table.insert(result, parseFlowArray(itemValue))
                    index = index + 1
                elseif itemValue:match("^{.*}$") then
                    -- Flow object as item
                    table.insert(result, parseFlowObject(itemValue))
                    index = index + 1
                elseif itemValue == "" then
                    -- Nested value on next lines
                    index = index + 1
                    local nested = parseValue(indent + 1)
                    table.insert(result, nested)
                else
                    -- Simple scalar
                    table.insert(result, parseScalar(itemValue))
                    index = index + 1
                end
            end

            return result
        end

        -- Check for mapping (key: value)
        local key, value = content:match("^([^:]+):%s*(.*)$")
        if key then
            local result = {}

            while index <= #lines do
                while index <= #lines and isCommentOrEmpty(lines[index]) do
                    index = index + 1
                end

                if index > #lines then break end

                local currentLine = lines[index]
                local currentIndent = getIndent(currentLine)

                if currentIndent < indent then
                    break
                end

                if currentIndent > indent then
                    -- This shouldn't happen at top level
                    break
                end

                local currentContent = trim(currentLine)
                local k, v = currentContent:match("^([^:]+):%s*(.*)$")

                if k then
                    local trimmedKey = trim(k)
                    local trimmedVal = trim(v)

                    index = index + 1

                    if trimmedVal:match("^%[.*%]$") then
                        result[trimmedKey] = parseFlowArray(trimmedVal)
                    elseif trimmedVal:match("^{.*}$") then
                        result[trimmedKey] = parseFlowObject(trimmedVal)
                    elseif trimmedVal == "" then
                        result[trimmedKey] = parseValue(currentIndent + 1)
                    else
                        result[trimmedKey] = parseScalar(trimmedVal)
                    end
                else
                    break
                end
            end

            return result
        end

        -- Simple scalar
        index = index + 1
        return parseScalar(content)
    end

    return parseValue(0)
end

return M
