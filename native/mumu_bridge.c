#include <stddef.h>
#include <stdint.h>

#if defined(__GNUC__)
#define BRIDGE_EXPORT __attribute__((visibility("default")))
#else
#define BRIDGE_EXPORT
#endif

#define RTLD_NOW 2
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4

#define CODE_CAPACITY 16384
#define OUTPUT_CAPACITY 16384

#ifndef ENABLE_UNSAFE_INLINE_HOOK
#define ENABLE_UNSAFE_INLINE_HOOK 0
#endif

typedef void lua_State;
typedef int (*lua_gettop_fn)(lua_State *);
typedef void (*lua_settop_fn)(lua_State *, int);
typedef int (*luaL_loadbuffer_fn)(lua_State *, const char *, size_t, const char *);
typedef int (*lua_pcall_fn)(lua_State *, int, int, int);
typedef const char *(*lua_tolstring_fn)(lua_State *, int, size_t *);

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);

static long bridge_mprotect(void *address, size_t length, int protection) {
    register long x0 __asm__("x0") = (long)(uintptr_t)address;
    register long x1 __asm__("x1") = (long)length;
    register long x2 __asm__("x2") = (long)protection;
    register long x8 __asm__("x8") = 226;
    __asm__ volatile(
        "svc #0"
        : "+r"(x0)
        : "r"(x1), "r"(x2), "r"(x8)
        : "memory"
    );
    return x0;
}

static lua_State *g_lua_state;
static void *g_tolua;
static lua_gettop_fn g_original_gettop;
static void *g_original_gettop_tail;
static lua_gettop_fn g_lua_gettop;
static lua_settop_fn g_lua_settop;
static luaL_loadbuffer_fn g_luaL_loadbuffer;
static lua_pcall_fn g_lua_pcall;
static lua_tolstring_fn g_lua_tolstring;

static volatile int g_installed;
static volatile int g_request_state;
static int g_lua_status;
static size_t g_code_length;
static size_t g_output_length;
static char g_code[CODE_CAPACITY];
static char g_output[OUTPUT_CAPACITY];

static void copy_bytes(void *destination, const void *source, size_t length) {
    uint8_t *out = (uint8_t *)destination;
    const uint8_t *in = (const uint8_t *)source;
    for (size_t index = 0; index < length; ++index) {
        out[index] = in[index];
    }
}

static void clear_instruction_cache(void *start, void *end) {
    uintptr_t begin = (uintptr_t)start & ~(uintptr_t)63;
    uintptr_t finish = ((uintptr_t)end + 63) & ~(uintptr_t)63;
    for (uintptr_t address = begin; address < finish; address += 64) {
        __asm__ volatile("dc cvau, %0" : : "r"(address) : "memory");
    }
    __asm__ volatile("dsb ish" : : : "memory");
    for (uintptr_t address = begin; address < finish; address += 64) {
        __asm__ volatile("ic ivau, %0" : : "r"(address) : "memory");
    }
    __asm__ volatile("dsb ish\nisb" : : : "memory");
}

static void write_absolute_jump(void *destination, const void *target) {
    uint32_t instructions[2] = {UINT32_C(0x58000050), UINT32_C(0xD61F0200)};
    copy_bytes(destination, instructions, sizeof(instructions));
    copy_bytes((uint8_t *)destination + 8, &target, sizeof(target));
}

static size_t set_output_buffer(
    char *output,
    size_t capacity,
    const char *text,
    size_t length
) {
    if (text == NULL) {
        text = "(nil)";
        length = 5;
    }
    if (length >= capacity) {
        length = capacity - 1;
    }
    copy_bytes(output, text, length);
    output[length] = '\0';
    return length;
}

static int evaluate_lua(
    lua_State *state,
    const char *code,
    size_t code_length,
    char *output,
    size_t output_capacity,
    size_t *output_length
) {
    int stack_top = g_lua_gettop(state);
    int status = g_luaL_loadbuffer(state, code, code_length, "@mumu_bridge");
    if (status == 0) {
        status = g_lua_pcall(state, 0, 1, 0);
    }
    size_t length = 0;
    const char *result = g_lua_tolstring(state, -1, &length);
    *output_length = set_output_buffer(
        output,
        output_capacity,
        result,
        length
    );
    g_lua_settop(state, stack_top);
    return status;
}

static int resolve_tolua(void) {
    if (g_lua_gettop != NULL && g_lua_settop != NULL &&
        g_luaL_loadbuffer != NULL &&
        g_lua_pcall != NULL && g_lua_tolstring != NULL) {
        return 0;
    }
    if (g_tolua == NULL) {
        g_tolua = dlopen("libtolua.so", RTLD_NOW);
        if (g_tolua == NULL) {
            return -10;
        }
    }
    g_lua_gettop = (lua_gettop_fn)dlsym(g_tolua, "lua_gettop");
    g_lua_settop = (lua_settop_fn)dlsym(g_tolua, "lua_settop");
    g_luaL_loadbuffer = (luaL_loadbuffer_fn)dlsym(g_tolua, "luaL_loadbuffer");
    g_lua_pcall = (lua_pcall_fn)dlsym(g_tolua, "lua_pcall");
    g_lua_tolstring = (lua_tolstring_fn)dlsym(g_tolua, "lua_tolstring");
    if (g_lua_gettop == NULL || g_lua_settop == NULL ||
        g_luaL_loadbuffer == NULL ||
        g_lua_pcall == NULL || g_lua_tolstring == NULL) {
        return -11;
    }
    return 0;
}

static void execute_pending(lua_State *state) {
    g_lua_status = evaluate_lua(
        state,
        g_code,
        g_code_length,
        g_output,
        OUTPUT_CAPACITY,
        &g_output_length
    );
    __atomic_store_n(&g_request_state, 2, __ATOMIC_RELEASE);
}

static int bridge_gettop(lua_State *state) {
    g_lua_state = state;
    if (__atomic_load_n(&g_request_state, __ATOMIC_ACQUIRE) == 1) {
        __atomic_store_n(&g_request_state, 3, __ATOMIC_RELEASE);
        execute_pending(state);
    }
    return g_original_gettop(state);
}

__attribute__((naked))
static int original_gettop_gateway(lua_State *state __attribute__((unused))) {
    __asm__ volatile(
        "ldr x1, [x0, #0x28]\n"
        "ldr x0, [x0, #0x20]\n"
        "sub x0, x1, x0\n"
        "lsr x0, x0, #3\n"
        "adrp x16, g_original_gettop_tail\n"
        "ldr x16, [x16, :lo12:g_original_gettop_tail]\n"
        "br x16\n"
    );
}

static int install_gettop_hook(void *target) {
    uintptr_t target_page = (uintptr_t)target & ~(uintptr_t)4095;
    if (bridge_mprotect(
            (void *)target_page,
            4096,
            PROT_READ | PROT_WRITE | PROT_EXEC
        ) != 0) {
        return -20;
    }
    g_original_gettop_tail = (uint8_t *)target + 16;
    g_original_gettop = original_gettop_gateway;

    write_absolute_jump(target, (const void *)&bridge_gettop);
    clear_instruction_cache(target, (uint8_t *)target + 16);
    if (bridge_mprotect(
            (void *)target_page,
            4096,
            PROT_READ | PROT_EXEC
        ) != 0) {
        return -21;
    }
    return 0;
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_probe(
    void *jni_env,
    void *receiver
) {
    (void)jni_env;
    (void)receiver;
    return INT64_C(0x123456789ABCDEF);
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_install(
    void *jni_env,
    void *receiver
) {
    (void)jni_env;
    (void)receiver;
#if !ENABLE_UNSAFE_INLINE_HOOK
    return -30;
#else
    if (g_installed != 0) {
        return g_installed;
    }

    int resolve_status = resolve_tolua();
    if (resolve_status != 0) {
        return resolve_status;
    }

    int status = install_gettop_hook((void *)g_lua_gettop);
    if (status != 0) {
        return status;
    }
    g_installed = 1;
    return 1;
#endif
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_installAt(
    void *jni_env,
    void *receiver,
    int64_t target_pointer
) {
    (void)jni_env;
    (void)receiver;
#if !ENABLE_UNSAFE_INLINE_HOOK
    (void)target_pointer;
    return -30;
#else
    if (g_installed != 0) {
        return g_installed;
    }
    if (target_pointer == 0) {
        return -31;
    }

    int resolve_status = resolve_tolua();
    if (resolve_status != 0) {
        return resolve_status;
    }
    int status = install_gettop_hook((void *)(uintptr_t)target_pointer);
    if (status != 0) {
        return status;
    }
    g_installed = 1;
    return 1;
#endif
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_state(
    void *jni_env,
    void *receiver
) {
    (void)jni_env;
    (void)receiver;
    return (int64_t)(uintptr_t)g_lua_state;
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_submit(
    void *jni_env,
    void *receiver,
    int64_t code_pointer,
    int64_t code_length
) {
    (void)jni_env;
    (void)receiver;
    if (g_installed != 1 || g_lua_state == NULL) {
        return -1;
    }
    if (code_pointer == 0 || code_length <= 0 || code_length >= CODE_CAPACITY) {
        return -2;
    }
    if (__atomic_load_n(&g_request_state, __ATOMIC_ACQUIRE) != 0) {
        return -3;
    }
    copy_bytes(g_code, (const void *)(uintptr_t)code_pointer, (size_t)code_length);
    g_code_length = (size_t)code_length;
    g_output_length = 0;
    g_lua_status = 0;
    __atomic_store_n(&g_request_state, 1, __ATOMIC_RELEASE);
    return 1;
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_poll(
    void *jni_env,
    void *receiver,
    int64_t output_pointer,
    int64_t output_capacity
) {
    (void)jni_env;
    (void)receiver;
    int state = __atomic_load_n(&g_request_state, __ATOMIC_ACQUIRE);
    if (state != 2) {
        return state == 1 || state == 3 ? 0 : -1;
    }
    if (output_pointer == 0 || output_capacity <= 0) {
        return -2;
    }
    size_t capacity = (size_t)output_capacity;
    size_t length = g_output_length;
    if (length >= capacity) {
        length = capacity - 1;
    }
    copy_bytes((void *)(uintptr_t)output_pointer, g_output, length);
    ((char *)(uintptr_t)output_pointer)[length] = '\0';
    int status = g_lua_status;
    __atomic_store_n(&g_request_state, 0, __ATOMIC_RELEASE);
    return status == 0 ? (int64_t)(length + 1) : -(int64_t)(length + 1);
}

BRIDGE_EXPORT int64_t Java_mumu_autotask_Bridge_execute(
    void *jni_env,
    void *receiver,
    int64_t state_pointer,
    int64_t code_pointer,
    int64_t code_length,
    int64_t output_pointer,
    int64_t output_capacity
) {
    (void)jni_env;
    (void)receiver;
    if (state_pointer == 0 || code_pointer == 0 || code_length <= 0 ||
        output_pointer == 0 || output_capacity <= 1) {
        return -2;
    }
    if (code_length >= CODE_CAPACITY || output_capacity > OUTPUT_CAPACITY) {
        return -3;
    }
    int resolve_status = resolve_tolua();
    if (resolve_status != 0) {
        return resolve_status;
    }

    size_t length = 0;
    int status = evaluate_lua(
        (lua_State *)(uintptr_t)state_pointer,
        (const char *)(uintptr_t)code_pointer,
        (size_t)code_length,
        (char *)(uintptr_t)output_pointer,
        (size_t)output_capacity,
        &length
    );
    return status == 0 ? (int64_t)(length + 1) : -(int64_t)(length + 1);
}
