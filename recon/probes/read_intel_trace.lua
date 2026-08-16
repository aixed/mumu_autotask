local captures = rawget(_G, "__MUMU_AUTOTASK_INTEL_TRACE_TEXTS")
if type(captures) ~= "table" then
    return table.concat({
        "MUMU_AUTOTASK_INTEL_TRACE_READ\t1",
        "COUNT\t" .. tostring(rawget(_G, "__MUMU_AUTOTASK_INTEL_TRACE_COUNT") or 0),
        "END\t0",
    }, "\n")
end

local lines = {
    "MUMU_AUTOTASK_INTEL_TRACE_READ\t1",
    "COUNT\t" .. tostring(rawget(_G, "__MUMU_AUTOTASK_INTEL_TRACE_COUNT") or #captures),
}
for index, text in ipairs(captures) do
    lines[#lines + 1] = "BEGIN_RECORD\t" .. tostring(index)
    lines[#lines + 1] = text
    lines[#lines + 1] = "END_RECORD\t" .. tostring(index)
end
lines[#lines + 1] = "END\t" .. tostring(#captures)
return table.concat(lines, "\n")
