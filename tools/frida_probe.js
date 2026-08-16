"use strict";

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

rpc.exports = {
  nativeBridge() {
    const bridges = ["libnb.so", "libhoudini.so"].map((moduleName) => {
      const module = Process.getModuleByName(moduleName);
      const table = module.getExportByName("NativeBridgeItf");
      const slots = [];
      for (let index = 0; index < 20; index += 1) {
        slots.push(table.add(index * Process.pointerSize).readPointer().toString());
      }
      return {
        module: moduleName,
        table: table.toString(),
        version: table.readU32(),
        slots,
      };
    });
    return { arch: Process.arch, bridges };
  },

  modules() {
    return Process.enumerateModules()
      .filter((module) =>
        /houdini|nativebridge|libnb|libc\.so|gof|nesec/i.test(
          `${module.name} ${module.path}`,
        ),
      )
      .map((module) => ({
        name: module.name,
        base: module.base.toString(),
        size: module.size,
        path: module.path,
      }));
  },

  trampolineProbe(bridgeModule, libraryPath, symbolName, shorties, invoke) {
    const table = Process.getModuleByName(bridgeModule).getExportByName(
      "NativeBridgeItf",
    );
    const loadLibrary = new NativeFunction(
      table.add(2 * Process.pointerSize).readPointer(),
      "pointer",
      ["pointer", "int"],
    );
    const getTrampoline = new NativeFunction(
      table.add(3 * Process.pointerSize).readPointer(),
      "pointer",
      ["pointer", "pointer", "pointer", "uint"],
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
    const library = Memory.allocUtf8String(libraryPath);
    const loadAttempts = [];
    let handle = NULL;
    for (const flags of [1, 2]) {
      const candidate = loadLibrary(library, flags);
      loadAttempts.push({ kind: "loadLibrary", flags, handle: candidate.toString() });
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
        if (namespace.pointer.isNull()) {
          loadAttempts.push({
            kind: "loadLibraryExt",
            namespace: namespace.name,
            namespacePointer: namespace.pointer.toString(),
            handle: NULL.toString(),
          });
          continue;
        }
        const candidate = loadLibraryExt(library, 2, namespace.pointer);
        loadAttempts.push({
          kind: "loadLibraryExt",
          namespace: namespace.name,
          namespacePointer: namespace.pointer.toString(),
          handle: candidate.toString(),
        });
        if (!candidate.isNull()) {
          handle = candidate;
          break;
        }
      }
    }
    if (handle.isNull()) {
      return { bridgeModule, handle: handle.toString(), loadAttempts };
    }
    const symbol = Memory.allocUtf8String(symbolName);
    const attempts = [];
    const candidates = [null].concat(shorties || []);
    for (const shortyText of candidates) {
      const shorty =
        shortyText === null ? NULL : Memory.allocUtf8String(shortyText);
      const trampoline = getTrampoline(
        handle,
        symbol,
        shorty,
        shortyText === null ? 0 : shortyText.length,
      );
      attempts.push({
        shorty: shortyText,
        trampoline: trampoline.toString(),
      });
    }
    let result = null;
    if (invoke) {
      const chosen = attempts.find(
        (attempt) => attempt.shorty === "J" && attempt.trampoline !== "0x0",
      );
      if (chosen === undefined) {
        throw new Error("invoke requires a successful --shorty J trampoline");
      }
      const jni = attachJniThread();
      const call = new NativeFunction(
        ptr(chosen.trampoline),
        "pointer",
        ["pointer", "pointer"],
      );
      try {
        result = {
          env: jni.env.toString(),
          value: call(jni.env, NULL).toString(),
        };
      } finally {
        jni.detach();
      }
    }
    return {
      bridgeModule,
      handle: handle.toString(),
      loadAttempts,
      attempts,
      result,
    };
  },
};
