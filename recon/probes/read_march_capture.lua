local text = _G.__MUMU_AUTOTASK_MARCH_CAPTURE_TEXT
if type(text) ~= "string" or text == "" then
    return table.concat({
        "MUMU_AUTOTASK_CAPTURE_READ\t1",
        "COUNT\t" .. tostring(_G.__MUMU_AUTOTASK_MARCH_CAPTURE_COUNT or 0),
        "EMPTY\t1",
        "END\t1",
    }, "\n")
end
return text
