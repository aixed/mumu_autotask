local lines = {}
for key, value in pairs(GameMsg or {}) do
    lines[#lines + 1] = table.concat({tostring(key), type(value), tostring(value)}, "\t")
end
table.sort(lines)
return table.concat(lines, "\n")
