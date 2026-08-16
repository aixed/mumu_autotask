"use strict";

const GC_POINTER_HIGH_MASK = 0x7fff;
const TYPE_NAMES = new Map([
  [-1, "nil"],
  [-2, "false"],
  [-3, "true"],
  [-4, "lightuserdata"],
  [-5, "string"],
  [-6, "upvalue"],
  [-7, "thread"],
  [-8, "prototype"],
  [-9, "function"],
  [-10, "trace"],
  [-11, "cdata"],
  [-12, "table"],
  [-13, "userdata"],
  [-14, "integer"],
]);

function hex32(value, width) {
  return (value >>> 0).toString(16).padStart(width, "0");
}

function taggedType(valueAddress) {
  const high = valueAddress.add(4).readU32();
  const tag = high >>> 15;
  return tag < 0x10000 ? null : tag - 0x20000;
}

function taggedPointer(valueAddress) {
  const low = valueAddress.readU32();
  const high = valueAddress.add(4).readU32() & GC_POINTER_HIGH_MASK;
  return ptr(`0x${hex32(high, 4)}${hex32(low, 8)}`);
}

function readGcString(address) {
  if (address.add(9).readU8() !== 4) {
    throw new Error(`${address} is not a LuaJIT GC string`);
  }
  const length = address.add(20).readU32();
  if (length > 4096) {
    throw new Error(`LuaJIT GC string at ${address} is too long: ${length}`);
  }
  return address.add(24).readUtf8String(length);
}

function valueSummary(valueAddress, key, showValues) {
  const tag = taggedType(valueAddress);
  const type = TYPE_NAMES.get(tag) || "number";
  const result = { type };
  if (tag !== null && tag >= -13 && tag <= -4) {
    result.address = taggedPointer(valueAddress).toString();
  }
  if (!showValues) {
    return result;
  }
  if (/account|token|password|passwd|email|secret|credential|session|cookie/i.test(key)) {
    result.value = "<redacted>";
  } else if (tag === -14) {
    result.value = valueAddress.readS32();
  } else if (tag === null) {
    result.value = valueAddress.readDouble();
  } else if (tag === -3) {
    result.value = true;
  } else if (tag === -2) {
    result.value = false;
  } else if (tag === -1) {
    result.value = null;
  } else if (tag === -5) {
    result.value = readGcString(taggedPointer(valueAddress));
  }
  return result;
}

function tableEntries(tableAddress, showValues) {
  const table = ptr(tableAddress);
  if (table.add(9).readU8() !== 11) {
    throw new Error(`${table} is not a LuaJIT GC table`);
  }
  const array = table.add(0x10).readPointer();
  const metatable = table.add(0x20).readPointer();
  const nodes = table.add(0x28).readPointer();
  const arraySize = table.add(0x30).readU32();
  const hashMask = table.add(0x34).readU32();
  if (arraySize > (1 << 20) || hashMask > (1 << 20) - 1) {
    throw new Error(`unreasonable LuaJIT table size: array=${arraySize}, hash=${hashMask}`);
  }

  const entries = [];
  for (let index = 0; index <= hashMask; index += 1) {
    const node = nodes.add(index * 24);
    const keyAddress = node.add(8);
    const keyType = taggedType(keyAddress);
    let key = null;
    if (keyType === -5) {
      key = readGcString(taggedPointer(keyAddress));
    } else if (keyType === -14) {
      key = String(keyAddress.readS32());
    } else if (keyType === null) {
      key = String(keyAddress.readDouble());
    }
    if (key !== null) {
      entries.push({ key, ...valueSummary(node, key, showValues) });
    }
  }
  for (let index = 0; index < arraySize; index += 1) {
    const valueAddress = array.add(index * 8);
    if (taggedType(valueAddress) !== -1) {
      const key = String(index);
      entries.push({ key, ...valueSummary(valueAddress, key, showValues) });
    }
  }
  entries.sort((left, right) => left.key.localeCompare(right.key));
  return {
    table: table.toString(),
    metatable: metatable.isNull() ? null : metatable.toString(),
    entryCount: entries.length,
    entries,
  };
}

function exactTableEntry(tableAddress, key) {
  const result = tableEntries(tableAddress, false);
  const matches = result.entries.filter((entry) => entry.key === key);
  if (matches.length !== 1) {
    throw new Error(`${result.table} contains ${matches.length} entries named ${key}`);
  }
  if (matches[0].type !== "table" || !matches[0].address) {
    throw new Error(`${key} in ${result.table} is ${matches[0].type}, not a table`);
  }
  return ptr(matches[0].address);
}

function nextTable(tableAddress, segment) {
  if (segment !== "@metatable") {
    return exactTableEntry(tableAddress, segment);
  }
  const table = ptr(tableAddress);
  if (table.add(9).readU8() !== 11) {
    throw new Error(`${table} is not a LuaJIT GC table`);
  }
  const metatable = table.add(0x20).readPointer();
  if (metatable.isNull()) {
    throw new Error(`${table} has no metatable`);
  }
  if (metatable.add(9).readU8() !== 11) {
    throw new Error(`${table} has a non-table metatable at ${metatable}`);
  }
  return metatable;
}

rpc.exports = {
  inspect(stateAddress, path, filterText, showValues) {
    const state = ptr(stateAddress);
    if (state.add(9).readU8() !== 6) {
      throw new Error(`${state} is not a LuaJIT state`);
    }
    let table = state.add(0x48).readPointer();
    for (const segment of path || []) {
      table = nextTable(table, String(segment));
    }
    const result = tableEntries(table, Boolean(showValues));
    if (filterText) {
      const pattern = new RegExp(filterText, "i");
      result.entries = result.entries.filter((entry) => pattern.test(entry.key));
    }
    result.path = path || [];
    result.matchedCount = result.entries.length;
    return result;
  },
};
