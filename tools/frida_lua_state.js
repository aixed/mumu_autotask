"use strict";

function isReadable(address, size) {
  if (address.isNull()) {
    return false;
  }
  const range = Process.findRangeByAddress(address);
  if (range === null || !range.protection.startsWith("r")) {
    return false;
  }
  return address.add(size).compare(range.base.add(range.size)) <= 0;
}

function isAligned(address) {
  return address.and(7).isNull();
}

function validateLuaState(address) {
  if (!isReadable(address, 0x60)) {
    return null;
  }
  const marked = address.add(8).readU8();
  const gct = address.add(9).readU8();
  const dummyFfid = address.add(0x0a).readU8();
  const status = address.add(0x0b).readU8();
  if (gct !== 6 || dummyFfid !== 1 || status > 14) {
    return null;
  }

  const glref = address.add(0x10).readPointer();
  const base = address.add(0x20).readPointer();
  const top = address.add(0x28).readPointer();
  const maxstack = address.add(0x30).readPointer();
  const stack = address.add(0x38).readPointer();
  const openupval = address.add(0x40).readPointer();
  const env = address.add(0x48).readPointer();
  const cframe = address.add(0x50).readPointer();
  const stacksize = address.add(0x58).readU32();

  const pointers = [glref, base, top, maxstack, stack, env];
  if (!pointers.every(isAligned)) {
    return null;
  }
  if (!isReadable(glref, 0xc8) || !isReadable(stack, 8)) {
    return null;
  }
  if (base.compare(stack) < 0 || top.compare(base) < 0) {
    return null;
  }
  if (maxstack.compare(top) < 0 || !isReadable(maxstack.sub(1), 1)) {
    return null;
  }
  if (stacksize < 32 || stacksize > 1000000) {
    return null;
  }
  const stackBytes = maxstack.sub(stack).toUInt32();
  if (stackBytes > stacksize * 8 || stackBytes + 128 < stacksize * 8) {
    return null;
  }
  if (!env.isNull() && (!isReadable(env, 16) || env.add(9).readU8() !== 11)) {
    return null;
  }

  const mainThread = glref.add(0xc0).readPointer();
  if (!isReadable(mainThread, 0x60) || mainThread.add(9).readU8() !== 6) {
    return null;
  }
  if (!mainThread.add(0x10).readPointer().equals(glref)) {
    return null;
  }

  return {
    address: address.toString(),
    marked,
    status,
    glref: glref.toString(),
    base: base.toString(),
    top: top.toString(),
    maxstack: maxstack.toString(),
    stack: stack.toString(),
    openupval: openupval.toString(),
    env: env.toString(),
    cframe: cframe.toString(),
    stacksize,
    mainThread: mainThread.toString(),
    isMain: mainThread.equals(address),
  };
}

rpc.exports = {
  findLuaStates() {
    const candidates = new Map();
    const ranges = Process.enumerateRanges({
      protection: "rw-",
      coalesce: true,
    });
    for (const range of ranges) {
      if (range.size > 512 * 1024 * 1024) {
        continue;
      }
      for (const match of Memory.scanSync(
        range.base,
        range.size,
        "06 01",
      )) {
        const candidate = validateLuaState(match.address.sub(9));
        if (candidate !== null) {
          candidates.set(candidate.address, candidate);
        }
      }
    }
    return Array.from(candidates.values());
  },

  validateLuaState(addressText) {
    return validateLuaState(ptr(addressText));
  },
};
