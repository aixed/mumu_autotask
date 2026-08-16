#include <stdint.h>

#if defined(__GNUC__)
#define BRIDGE_EXPORT __attribute__((visibility("default")))
#else
#define BRIDGE_EXPORT
#endif

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_probe(
    void *jni_env,
    void *receiver
) {
    (void)jni_env;
    (void)receiver;
    return INT64_C(0x123456789ABCDEF);
}
