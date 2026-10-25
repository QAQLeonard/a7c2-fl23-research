#define _GNU_SOURCE
#include "bootstrap.h"
#include <string.h>
_Static_assert(sizeof(struct a7_ap_report) == 320, "Unsupported AP report ABI");
_Static_assert(sizeof(struct a7_boot_report) == 352, "Unsupported bootstrap report ABI");
#ifndef _WIN32
#include <dlfcn.h>
#include <link.h>
static void *native_open(void *unused, const char *path, int flags)
{ (void)unused; return dlopen(path, flags); }
static void *native_symbol(void *unused, void *module, const char *name)
{ (void)unused; return dlsym(module, name); }
static int native_owns(void *unused, void *module, void *symbol)
{
    (void)unused;
    struct link_map *map = NULL; Dl_info info;
    return !dlinfo(module, RTLD_DI_LINKMAP, &map) && map &&
           dladdr(symbol, &info) && (void *)map->l_addr == info.dli_fbase;
}
static int native_close(void *unused, void *module)
{ (void)unused; return dlclose(module); }
static const struct a7_boot_loader native_loader = {
    NULL, native_open, native_symbol, native_owns, native_close
};
#endif

static int valid_path(const char *path)
{
    if (!path || path[0] != '/') return 0;
    size_t length = 0;
    while (length < 512 && path[length]) ++length;
    if (!length || length >= 512 || path[length - 1] == '/') return 0;
    const char *part = path + 1;
    for (const char *p = part; ; ++p) {
        if (*p && (unsigned char)*p < 32) return 0;
        if (*p != '/' && *p) continue;
        size_t count = (size_t)(p - part);
        if (!count || (count == 1 && part[0] == '.') ||
            (count == 2 && part[0] == '.' && part[1] == '.')) return 0;
        if (!*p) break;
        part = p + 1;
    }
    return 1;
}

int a7_boot_dispatch(const char *path, uint32_t operation,
                     const struct a7_boot_loader *loader, struct a7_boot_report *out)
{
    if (!out) return A7_BOOT_INVALID;
    memset(out, 0, sizeof(*out)); out->abi = A7_BOOT_ABI; out->operation = operation;
#ifndef _WIN32
    if (!loader) loader = &native_loader;
#endif
    if (!valid_path(path) || operation < A7_BOOT_START || operation > A7_BOOT_RETIRE ||
        !loader || !loader->open || !loader->symbol || !loader->owns || !loader->close)
        return out->status = A7_BOOT_INVALID;
    /* RTLD_NOW | RTLD_LOCAL; only START may create a module instance. */
    void *module = loader->open(loader->context, path,
                               operation == A7_BOOT_START ? 2 : A7_AP_NOLOAD_NOW);
    if (!module) return out->status = operation == A7_BOOT_START ? A7_BOOT_LOAD : A7_BOOT_NOT_RESIDENT;
    const char *names[] = {"a7_ap_runtime_abi", "a7_ap_start", "a7_ap_query", "a7_ap_retire"};
    void *functions[4] = {0};
    int status = 0;
    for (unsigned i = 0; i < 4; ++i) {
        functions[i] = loader->symbol(loader->context, module, names[i]);
        if (!functions[i]) { status = A7_BOOT_SYMBOL; break; }
        if (loader->owns(loader->context, module, functions[i]) != 1) {
            status = A7_BOOT_OWNER; break;
        }
    }
    if (!status) {
        uint32_t (*abi)(void);
        int (*start)(const struct a7_ap_loader *, struct a7_ap_report *);
        int (*control)(struct a7_ap_report *);
        _Static_assert(sizeof(abi) == sizeof(void *), "Unsupported loader ABI");
        memcpy(&abi, &functions[0], sizeof(abi));
        if (abi() != A7_AP_RUNTIME_ABI) status = A7_BOOT_VERSION;
        else {
            out->called = 1;
            if (operation == A7_BOOT_START) {
                memcpy(&start, &functions[1], sizeof(start));
                status = start(NULL, &out->runtime);
            } else {
                memcpy(&control, &functions[operation == A7_BOOT_QUERY ? 2 : 3], sizeof(control));
                status = control(&out->runtime);
            }
            out->core_status = status;
            if (out->runtime.phase == A7_AP_REVIEW) out->review = 1;
        }
    }
    /* Keep our temporary reference until the core has returned and its
     * transferred pin has been closed. Never unload from inside the core. */
    void *pin = out->runtime.release_handle;
    out->runtime.release_handle = NULL;
    if (pin) {
        out->close_attempts |= 1;
        out->close_error = loader->close(loader->context, pin);
    }
    if (!out->close_error) {
        out->close_attempts |= 2;
        out->close_error = loader->close(loader->context, module);
    }
    if (out->close_error) { out->review = 1; status = A7_BOOT_CLOSE; }
    out->status = status;
    return status;
}
