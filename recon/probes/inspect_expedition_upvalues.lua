local class = require("game.module.ui.view.formation.ExpeditionView")
local methods = {"GoOnMarch", "GoOnMarchEx", "OnBtnAverageClick", "CheckMarchCondition"}
local lines = {}

local function module_name(value)
    for name, loaded in pairs(package.loaded) do
        if loaded == value then
            return tostring(name)
        end
    end
    return ""
end

for _, method in ipairs(methods) do
    local func = class[method]
    if type(func) == "function" then
        for index = 1, 16 do
            local name, value = debug.getupvalue(func, index)
            if name == nil then
                break
            end
            lines[#lines + 1] = table.concat({
                method,
                tostring(index),
                tostring(name),
                type(value),
                module_name(value),
            }, "\t")
        end
    end
end
return table.concat(lines, "\n")
