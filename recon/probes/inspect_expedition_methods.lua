local module_name = "game.module.ui.view.formation.ExpeditionView"
local class = package.loaded[module_name] or require(module_name)
if type(class) ~= "table" then
    return "ExpeditionView=" .. type(class)
end

local lines = {}
for key, value in pairs(class) do
    if type(value) == "function" then
        lines[#lines + 1] = tostring(key)
    end
end
table.sort(lines)
return table.concat(lines, "\n")
