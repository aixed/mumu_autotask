"use strict";

import Java from "frida-java-bridge";

rpc.exports = {
  inspect() {
    if (!Java.available) {
      return { available: false, classes: [] };
    }
    return Java.performNow(() => {
      const selected = new Set([
        "com.unity3d.player.MyMainPlayerActivity",
        "com.unity3d.player.U0",
        "com.unity3d.player.UnityPlayer",
        "com.unity3d.player.UnityPlayerActivity",
      ]);
      const names = Java.enumerateLoadedClassesSync()
        .filter((name) => selected.has(name))
        .sort();
      const classes = [];
      for (const name of names) {
        try {
          const wrapper = Java.use(name);
          classes.push({
            name,
            methods: wrapper.class
              .getDeclaredMethods()
              .map((method) => method.toString())
              .sort(),
            fields: wrapper.class
              .getDeclaredFields()
              .map((field) => field.toString())
              .sort(),
          });
        } catch (error) {
          classes.push({ name, error: String(error) });
        }
      }
      return { available: true, classes };
    });
  },
};
