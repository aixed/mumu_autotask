local captures = rawget(_G, "__MUMU_AUTOTASK_BATTLE_CAPTURE_TEXTS")
if type(captures) ~= "table" or #captures == 0 then
    return table.concat({
        "MUMU_AUTOTASK_BATTLE_CAPTURE_READ\t1",
        "COUNT\t" .. tostring(_G.__MUMU_AUTOTASK_BATTLE_CAPTURE_COUNT or 0),
        "EMPTY\t1",
        "END\t1",
    }, "\n")
end
local parts = {
    "MUMU_AUTOTASK_BATTLE_CAPTURE_READ\t1",
    "COUNT\t" .. tostring(_G.__MUMU_AUTOTASK_BATTLE_CAPTURE_COUNT or #captures),
}
for index, text in ipairs(captures) do
    parts[#parts + 1] = "CAPTURE_INDEX\t" .. tostring(index)
    parts[#parts + 1] = text
end
parts[#parts + 1] = "END\t1"
return table.concat(parts, "\n")
