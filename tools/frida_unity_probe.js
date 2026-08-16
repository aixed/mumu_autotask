"use strict";

rpc.exports = {
  inspect() {
    return Process.enumerateThreads()
      .filter((thread) => /UnityMain/i.test(thread.name || ""))
      .map((thread) => ({
        id: thread.id,
        name: thread.name,
        state: thread.state,
        stack: Thread.backtrace(thread.context, Backtracer.ACCURATE)
          .map(DebugSymbol.fromAddress)
          .map(String),
      }));
  },
};
