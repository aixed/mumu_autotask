local records = rawget(_G, "__MUMU_AUTOTASK_RESCUE_TRACE_SLIM")
local lines = {
    "MUMU_AUTOTASK_RESCUE_TRACE_SLIM_READ\t1",
}
if type(records) ~= "table" then
    lines[#lines + 1] = "COUNT\t0"
    lines[#lines + 1] = "END\t0"
    return table.concat(lines, "\n")
end
lines[#lines + 1] = "COUNT\t" .. tostring(#records)
for index, record in ipairs(records) do
    lines[#lines + 1] = tostring(index) .. "\t" .. tostring(record)
end
lines[#lines + 1] = "END\t" .. tostring(#records)
return table.concat(lines, "\n")
