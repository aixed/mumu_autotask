local trace = _G.__MUMU_AUTOTASK_LIGHT_SEARCH_TRACE
if type(trace) ~= "table" or type(trace.records) ~= "table" then
    return "LIGHT_SEARCH_TRACE\tNOT_INSTALLED"
end
local lines = { "LIGHT_SEARCH_TRACE\tRECORDS\t" .. tostring(#trace.records) }
for _, record in ipairs(trace.records) do lines[#lines + 1] = record end
return table.concat(lines, "\n")
