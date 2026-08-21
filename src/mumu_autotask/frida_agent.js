"use strict";

let bridge = null;
let bridgeAllocations = [];
const BRIDGE_CODE_CAPACITY = 16384;
let unityFrameHook = null;
const unityJobs = [];
const UNITY_JOB_TIMEOUT_MS = 5000;

function attachJniThread() {
  const getCreatedJavaVms = new NativeFunction(
    Process.getModuleByName("libart.so").getExportByName("JNI_GetCreatedJavaVMs"),
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
  if (handle.isNull()) {
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
    throw new Error(
      `NativeBridge failed to load ${libraryPath}: ${JSON.stringify(attempts)}`,
    );
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
  const trampoline = getTrampoline(handle, symbol, shorty, shortyText.length);
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

function readBridgeOutput(address, length) {
  if (length === 0) {
    return "";
  }
  const buffer = address.readByteArray(length);
  if (buffer === null) {
    throw new Error("bridge output buffer is unreadable");
  }
  const bytes = new Uint8Array(buffer);
  try {
    return address.readUtf8String(length);
  } catch (error) {
    const preview = Array.from(bytes.slice(0, 256))
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
    return `[invalid UTF-8 bridge output: length=${length}, hex=${preview}]`;
  }
}

function nativeBridgeError(result, output) {
  // A Lua error also uses -(output length + 1). That means short Lua errors
  // collide with every fixed native error below (for example, one byte is
  // -2 and nine bytes is -10). Treat a value as a native error only when the
  // bridge left the explicitly zeroed output buffer untouched.
  if (output.readU8() !== 0) {
    return null;
  }
  switch (result) {
    case -1:
      return "native bridge execute failed (-1): execution state is unavailable";
    case -2:
      return (
        "native bridge execute failed (-2): invalid state/source/output " +
        "argument, empty source, or output capacity below 2 bytes"
      );
    case -3:
      return (
        "native bridge execute failed (-3): fixed buffer capacity exceeded " +
        `(source must be below ${BRIDGE_CODE_CAPACITY} bytes and output must ` +
        "not exceed 16384 bytes)"
      );
    case -10:
      return (
        'native bridge execute failed (-10): could not load "libtolua.so"'
      );
    case -11:
      return (
        "native bridge execute failed (-11): libtolua.so is missing one or " +
        "more required Lua API exports (lua_gettop, lua_settop, " +
        "luaL_loadbuffer, lua_pcall, lua_tolstring)"
      );
    default:
      return null;
  }
}

function executeBridgeNow(current, stateAddress, code, outputCapacity) {
  const capacity = outputCapacity || 16384;
  if (capacity < 2 || capacity > 16384) {
    throw new Error("output capacity must be between 2 and 16384 bytes");
  }
  const codeLength = utf8ByteLength(code);
  if (codeLength <= 0 || codeLength >= BRIDGE_CODE_CAPACITY) {
    throw new Error(
      `Lua source must be between 1 and ${BRIDGE_CODE_CAPACITY - 1} UTF-8 bytes; ` +
        `received ${codeLength}`,
    );
  }
  const codeBuffer = Memory.allocUtf8String(code);
  const output = Memory.alloc(capacity);
  output.writeU8(0);
  const threadId = Process.getCurrentThreadId();
  const thread = Process.enumerateThreads().find(
    (candidate) => candidate.id === threadId,
  );
  const result = invokeJni(current.execute, [
    ptr(stateAddress),
    codeBuffer,
    ptr(codeLength),
    output,
    ptr(capacity),
  ]).toInt32();
  const nativeError = nativeBridgeError(result, output);
  const length = nativeError === null ? Math.max(0, Math.abs(result) - 1) : 0;
  return {
    ok: result > 0,
    result,
    output: nativeError || readBridgeOutput(output, length),
    threadId,
    threadName: thread?.name || "UnityMain",
    threadMode: "unity-frame-hook",
  };
}

function ensureUnityFrameHook() {
  if (unityFrameHook !== null) {
    return;
  }
  const egl = Process.findModuleByName("libEGL.so");
  if (egl === null) {
    throw new Error("libEGL.so is unavailable");
  }
  const swapBuffers = egl.getExportByName("eglSwapBuffers");
  unityFrameHook = Interceptor.attach(swapBuffers, {
    onEnter() {
      const job = unityJobs[0];
      if (job === undefined) {
        return;
      }
      try {
        if (!ptr(job.stateAddress).add(0x50).readPointer().isNull()) {
          return;
        }
        unityJobs.shift();
        clearTimeout(job.timeoutId);
        job.resolve(job.execute());
      } catch (error) {
        unityJobs.shift();
        clearTimeout(job.timeoutId);
        job.reject(error);
      }
    },
  });
}

function executeOnUnityThread(current, stateAddress, code, outputCapacity) {
  ensureUnityFrameHook();
  return new Promise((resolve, reject) => {
    const job = {
      stateAddress,
      execute: () =>
        executeBridgeNow(current, stateAddress, code, outputCapacity),
      resolve,
      reject,
      timeoutId: null,
    };
    job.timeoutId = setTimeout(() => {
      const index = unityJobs.indexOf(job);
      if (index < 0) {
        return;
      }
      unityJobs.splice(index, 1);
      reject(new Error(
        "Unity Lua execution did not reach an idle main-state frame within 5 seconds",
      ));
    }, UNITY_JOB_TIMEOUT_MS);
    unityJobs.push(job);
  });
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

  execute(stateAddress, code, outputCapacity) {
    const current = requireBridge();
    return executeOnUnityThread(current, stateAddress, code, outputCapacity);
  },
};
