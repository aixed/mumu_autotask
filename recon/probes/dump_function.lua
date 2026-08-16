local function to_hex(value)
    return (value:gsub(".", function(char)
        return string.format("%02x", string.byte(char))
    end))
end

return to_hex(string.dump(assert(DUMP_TARGET, "DUMP_TARGET is not set")))
