"use strict";

let bridge = null;
let requestOutstanding = false;
let bridgeAllocations = [];

function attachJniThread() {
  const getCreatedJavaVms = new NativeFunction(
    Process.getModuleByName("libart.so").getExportByName(
      "JNI_GetCreatedJavaVMs",
    ),
    "int",
    ["pointer", "int", "pointer"],
  );
  const vmOut = Memory.alloc(Process.pointerSize);
  const countOut = Memory.alloc(4);
  const result = getCreatedJavaVms(vmOut, 1, countOut);
  if (result !== 0 || countOut.readS32() !== 1) {
    throw new Error(
      `JNI_GetCreatedJavaVMs failed: result=${result}, count=${countOut.readS32()}`,
    );
  }

  const vm = vmOut.readPointer();
  const functions = vm.readPointer();
  const getEnv = new NativeFunction(
    functions.add(6 * Process.pointerSize).readPointer(),
    "int",
    ["pointer", "pointer", "int"],
  );
  const attachCurrentThread = new NativeFunction(
    functions.add(4 * Process.pointerSize).readPointer(),
    "int",
    ["pointer", "pointer", "pointer"],
  );
  const detachCurrentThread = new NativeFunction(
    functions.add(5 * Process.pointerSize).readPointer(),
    "int",
    ["pointer"],
  );
  const envOut = Memory.alloc(Process.pointerSize);
  let status = getEnv(vm, envOut, 0x00010006);
  let attached = false;
  if (status === -2) {
    status = attachCurrentThread(vm, envOut, NULL);
    attached = status === 0;
  }
  if (status !== 0) {
    throw new Error(`cannot obtain JNIEnv for Frida thread: ${status}`);
  }
  return {
    env: envOut.readPointer(),
    detach() {
      if (attached) {
        detachCurrentThread(vm);
      }
    },
  };
}

function loadArmLibrary(libraryPath) {
  const table = Process.getModuleByName("libhoudini.so").getExportByName(
    "NativeBridgeItf",
  );
  const loadLibrary = new NativeFunction(
    table.add(2 * Process.pointerSize).readPointer(),
    "pointer",
    ["pointer", "int"],
  );
  const loadLibraryExt = new NativeFunction(
    table.add(14 * Process.pointerSize).readPointer(),
    "pointer",
    ["pointer", "int", "pointer"],
  );
  const getVendorNamespace = new NativeFunction(
    table.add(15 * Process.pointerSize).readPointer(),
    "pointer",
    [],
  );
  const getExportedNamespace = new NativeFunction(
    table.add(16 * Process.pointerSize).readPointer(),
    "pointer",
    ["pointer"],
  );
  const path = Memory.allocUtf8String(libraryPath);
  const attempts = [];
  let handle = NULL;

  for (const flags of [1, 2]) {
    const candidate = loadLibrary(path, flags);
    attempts.push({ kind: "loadLibrary", flags, handle: candidate.toString() });
    if (!candidate.isNull()) {
      handle = candidate;
      break;
    }
  }

  const namespaceCandidates = [
    { name: "vendor", pointer: getVendorNamespace() },
  ];
  for (const name of [
    "default",
    "classloader-namespace",
    "sphal",
    "vendor",
    "vndk",
  ]) {
    namespaceCandidates.push({
      name,
      pointer: getExportedNamespace(Memory.allocUtf8String(name)),
    });
  }

  if (handle.isNull()) {
    for (const namespace of namespaceCandidates) {
      const name = namespace.name;
      const namespacePointer = namespace.pointer;
      if (namespacePointer.isNull()) {
        attempts.push({
          kind: "loadLibraryExt",
          namespace: name,
          namespacePointer: namespacePointer.toString(),
          handle: NULL.toString(),
        });
        continue;
      }
      const candidate = loadLibraryExt(path, 2, namespacePointer);
      attempts.push({
        kind: "loadLibraryExt",
        namespace: name,
        namespacePointer: namespacePointer.toString(),
        handle: candidate.toString(),
      });
      if (!candidate.isNull()) {
        handle = candidate;
        break;
      }
    }
  }

  if (handle.isNull()) {
    throw new Error(`NativeBridge failed to load ${libraryPath}: ${JSON.stringify(attempts)}`);
  }
  return { table, handle, attempts };
}

function getJniTrampoline(table, handle, symbolName, shortyText) {
  const getTrampoline = new NativeFunction(
    table.add(3 * Process.pointerSize).readPointer(),
    "pointer",
    ["pointer", "pointer", "pointer", "uint"],
  );
  const symbol = Memory.allocUtf8String(symbolName);
  const shorty = Memory.allocUtf8String(shortyText);
  bridgeAllocations.push(symbol, shorty);
  getTrampoline(handle, symbol, NULL, 0);
  const trampoline = getTrampoline(
    handle,
    symbol,
    shorty,
    shortyText.length,
  );
  if (trampoline.isNull()) {
    throw new Error(`no trampoline for ${symbolName} with shorty ${shortyText}`);
  }
  return trampoline;
}

function invokeJni(nativeFunction, extraArguments) {
  const jni = attachJniThread();
  try {
    return nativeFunction(jni.env, NULL, ...extraArguments);
  } finally {
    jni.detach();
  }
}

function utf8ByteLength(text) {
  let length = 0;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < 0x80) {
      length += 1;
    } else if (code < 0x800) {
      length += 2;
    } else if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        length += 4;
        index += 1;
      } else {
        length += 3;
      }
    } else {
      length += 3;
    }
  }
  return length;
}

function requireBridge() {
  if (bridge === null) {
    throw new Error("initialize must be called first");
  }
  return bridge;
}

rpc.exports = {
  initialize(libraryPath) {
    bridgeAllocations = [];
    const loaded = loadArmLibrary(libraryPath);
    const probeTrampoline = getJniTrampoline(
      loaded.table,
      loaded.handle,
      "Java_mumu_autotask_Bridge_probe",
      "J",
    );
    const probe = new NativeFunction(
      probeTrampoline,
      "pointer",
      ["pointer", "pointer"],
    );
    const probeJni = attachJniThread();
    let probeResult;
    try {
      probeResult = probe(probeJni.env, NULL).toString();
    } finally {
      probeJni.detach();
    }
    const symbols = {
      install: ["Java_mumu_autotask_Bridge_install", "J"],
      installAt: ["Java_mumu_autotask_Bridge_installAt", "JJ"],
      state: ["Java_mumu_autotask_Bridge_state", "J"],
      submit: ["Java_mumu_autotask_Bridge_submit", "JJJ"],
      poll: ["Java_mumu_autotask_Bridge_poll", "JJJ"],
      execute: ["Java_mumu_autotask_Bridge_execute", "JJJJJJ"],
    };
    const trampolines = { probe: probeTrampoline };
    for (const [name, [symbol, shorty]] of Object.entries(symbols)) {
      trampolines[name] = getJniTrampoline(
        loaded.table,
        loaded.handle,
        symbol,
        shorty,
      );
    }
    bridge = {
      handle: loaded.handle,
      attempts: loaded.attempts,
      trampolines,
      probe,
      install: new NativeFunction(trampolines.install, "pointer", ["pointer", "pointer"]),
      installAt: new NativeFunction(trampolines.installAt, "pointer", [
        "pointer",
        "pointer",
        "pointer",
      ]),
      state: new NativeFunction(trampolines.state, "pointer", ["pointer", "pointer"]),
      submit: new NativeFunction(trampolines.submit, "pointer", [
        "pointer",
        "pointer",
        "pointer",
        "pointer",
      ]),
      poll: new NativeFunction(trampolines.poll, "pointer", [
        "pointer",
        "pointer",
        "pointer",
        "pointer",
      ]),
      execute: new NativeFunction(trampolines.execute, "pointer", [
        "pointer",
        "pointer",
        "pointer",
        "pointer",
        "pointer",
        "pointer",
        "pointer",
      ]),
    };
    return {
      arch: Process.arch,
      handle: loaded.handle.toString(),
      attempts: loaded.attempts,
      trampolines: Object.fromEntries(
        Object.entries(trampolines).map(([name, address]) => [name, address.toString()]),
      ),
      probe: probeResult,
    };
  },

  install() {
    const current = requireBridge();
    return invokeJni(current.install, []).toInt32();
  },

  installAt(targetAddress) {
    const current = requireBridge();
    return invokeJni(current.installAt, [ptr(targetAddress)]).toInt32();
  },

  state() {
    const current = requireBridge();
    return invokeJni(current.state, []).toString();
  },

  submit(code) {
    const current = requireBridge();
    const buffer = Memory.allocUtf8String(code);
    const result = invokeJni(current.submit, [buffer, ptr(utf8ByteLength(code))]);
    const value = result.toInt32();
    requestOutstanding = value === 1;
    return value;
  },

  poll(outputCapacity) {
    const current = requireBridge();
    const capacity = outputCapacity || 16384;
    if (capacity < 2) {
      throw new Error("output capacity must be at least 2 bytes");
    }
    const output = Memory.alloc(capacity);
    const result = invokeJni(current.poll, [output, ptr(capacity)]).toInt32();
    if (result === 0) {
      return { pending: true };
    }
    if (result === -1 && !requestOutstanding) {
      return { pending: false, idle: true };
    }

    requestOutstanding = false;
    const length = Math.max(0, Math.abs(result) - 1);
    return {
      pending: false,
      ok: result > 0,
      result,
      output: output.readUtf8String(length),
    };
  },

  execute(stateAddress, code, outputCapacity) {
    const current = requireBridge();
    const capacity = outputCapacity || 16384;
    if (capacity < 2 || capacity > 16384) {
      throw new Error("output capacity must be between 2 and 16384 bytes");
    }
    const codeBuffer = Memory.allocUtf8String(code);
    const output = Memory.alloc(capacity);
    const result = invokeJni(current.execute, [
      ptr(stateAddress),
      codeBuffer,
      ptr(utf8ByteLength(code)),
      output,
      ptr(capacity),
    ]).toInt32();
    const length = Math.max(0, Math.abs(result) - 1);
    return {
      ok: result > 0,
      result,
      output: output.readUtf8String(length),
    };
  },
};
