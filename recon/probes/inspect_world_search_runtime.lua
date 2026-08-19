local lines = {}

local function add_table(label, value)
    if type(value) ~= "table" then
        return
    end
    for key, item in pairs(value) do
        local name = tostring(key)
        local lower = string.lower(name)
        if type(item) == "function"
            and (string.find(lower, "search", 1, true)
                or string.find(lower, "monster", 1, true)
                or string.find(lower, "world", 1, true)) then
            lines[#lines + 1] = label .. "\t" .. name
        end
    end
end

for name, value in pairs(package.loaded) do
    local text = tostring(name)
    local lower = string.lower(text)
    if string.find(lower, "search", 1, true)
        or string.find(lower, "monster", 1, true) then
        lines[#lines + 1] = "LOADED\t" .. text .. "\t" .. type(value)
        add_table("METHOD " .. text, value)
    end
end

if type(GCtrl) == "table" then
    for key, value in pairs(GCtrl) do
        local name = tostring(key)
        local lower = string.lower(name)
        if string.find(lower, "search", 1, true)
            or string.find(lower, "monster", 1, true)
            or string.find(lower, "world", 1, true) then
            lines[#lines + 1] = "GCTRL\t" .. name .. "\t" .. type(value)
            add_table("GCTRL_METHOD " .. name, value)
            if type(value) == "table" then
                add_table("GCTRL_CLASS " .. name, value.class)
            end
        end
    end
end

if type(GHelper) == "table" then
    for key, value in pairs(GHelper) do
        local name = tostring(key)
        local lower = string.lower(name)
        if string.find(lower, "search", 1, true)
            or string.find(lower, "monster", 1, true)
            or string.find(lower, "world", 1, true) then
            lines[#lines + 1] = "GHELPER\t" .. name .. "\t" .. type(value)
            add_table("GHELPER_METHOD " .. name, value)
        end
    end
end

table.sort(lines)
return table.concat(lines, "\n"):sub(1, 15000)
