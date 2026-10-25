#define _GNU_SOURCE
#include "ap_runtime.h"
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#include <pthread.h>
#endif

struct lease_record { uint64_t token; uint32_t kind; };
static struct {
    struct a7_ap_loader loader;
    struct a7_mpr_api api;
    a7_mkdir_fn mkdir;
    void *sdk[2], *self;
    struct lease_record leases[A7_AP_MAX_LEASES];
    uint64_t generation, next_token;
    uint32_t phase, mask, failed, close_attempts;
    int status, close_error, primary_status;
    char message[256];
} runtime;
#ifdef _WIN32
static SRWLOCK runtime_lock = SRWLOCK_INIT;
#else
static pthread_mutex_t runtime_lock = PTHREAD_MUTEX_INITIALIZER;
#endif
static const char *modules[2] = {"libmpr.so", "libInfraFsys.so"};
static const char *symbols[7] = {
    "_ZN3mpr4file4OpenEPcNS0_8OpenFlagEPm", "_ZN3mpr4file4ReadEcmPvj",
    "_ZN3mpr4file5WriteEcmPvj", "_ZN3mpr4file5CloseEcm",
    "_ZN3mpr4file4StatEPcPm", "Fsys_Flush", "Fsys_Mkdir"
};
_Static_assert(sizeof(struct a7_mpr_api) == 6 * sizeof(void *), "Unsupported function-table ABI");
#ifdef _WIN32
static void lock(void) { AcquireSRWLockExclusive(&runtime_lock); }
static void unlock(void) { ReleaseSRWLockExclusive(&runtime_lock); }
#else
static void lock(void) { pthread_mutex_lock(&runtime_lock); }
static void unlock(void) { pthread_mutex_unlock(&runtime_lock); }
#endif
uint32_t a7_ap_runtime_abi(void) { return A7_AP_RUNTIME_ABI; }

#ifndef _WIN32
static void *native_open(void *context, const char *name, int flags)
{ (void)context; dlerror(); return dlopen(name, flags); }
static void *native_symbol(void *context, void *module, const char *name)
{ (void)context; dlerror(); return dlsym(module, name); }
static int native_close(void *context, void *module)
{ (void)context; dlerror(); return dlclose(module); }
static int native_owner(void *context, void *symbol, const char *module)
{
    (void)context; dlerror(); Dl_info info;
    if (!dladdr(symbol, &info) || !info.dli_fname) return 0;
    const char *name = strrchr(info.dli_fname, '/');
    return !strcmp(name ? name + 1 : info.dli_fname, module);
}
static void *native_pin(void *context)
{
    (void)context; dlerror(); Dl_info info;
    if (!dladdr((void *)&a7_ap_start, &info) || !info.dli_fname) return NULL;
    return dlopen(info.dli_fname, RTLD_NOW | RTLD_NOLOAD | RTLD_LOCAL);
}
static const char *native_error(void *context) { (void)context; return dlerror(); }
static const struct a7_ap_loader native_loader = {
    NULL, native_open, native_symbol, native_close, native_owner, native_pin, native_error
};
#endif

static void report(struct a7_ap_report *out, int status, void *release)
{
    memset(out, 0, sizeof(*out));
    out->abi = A7_AP_RUNTIME_ABI; out->phase = runtime.phase; out->bound_mask = runtime.mask;
    out->generation = runtime.generation; out->failed_symbol = runtime.failed;
    out->status = status; out->close_error = runtime.close_error;
    out->primary_status = runtime.primary_status;
    out->close_attempts = runtime.close_attempts; out->release_handle = release;
    for (unsigned i = 0; i < 2; ++i) if (runtime.sdk[i]) out->owned_sdk_mask |= 1u << i;
    for (unsigned i = 0; i < A7_AP_MAX_LEASES; ++i) {
        if (!runtime.leases[i].token) continue;
        if (runtime.leases[i].kind == A7_AP_JOB) ++out->jobs; else ++out->callbacks;
    }
    snprintf(out->message, sizeof(out->message), "%s", runtime.message);
}
static void failure(int status, unsigned index, const char *message)
{
    runtime.status = status; runtime.failed = index;
    const char *detail = runtime.loader.error ? runtime.loader.error(runtime.loader.context) : NULL;
    snprintf(runtime.message, sizeof(runtime.message), "%s%s%s", message,
             detail && *detail ? ": " : "", detail && *detail ? detail : "");
}
static int close_sdk(void)
{
    /* Each acquired reference is released once. Keep the core pin and all
     * remaining state if a close reports an uncertain result. */
    for (int i = 1; i >= 0; --i) {
        if (!runtime.sdk[i]) continue;
        if (runtime.close_attempts & (1u << i)) return A7_AP_UNCERTAIN;
        runtime.close_attempts |= 1u << i;
        int result = runtime.loader.close(runtime.loader.context, runtime.sdk[i]);
        if (result) {
            if (runtime.status && !runtime.primary_status) runtime.primary_status = runtime.status;
            runtime.close_error = result; runtime.phase = A7_AP_REVIEW;
            failure(A7_AP_UNCERTAIN, runtime.failed, "SDK module close failed");
            return A7_AP_UNCERTAIN;
        }
        runtime.sdk[i] = NULL;
    }
    return 0;
}
int a7_ap_start(const struct a7_ap_loader *loader, struct a7_ap_report *out)
{
    if (!out) return A7_AP_INVALID;
#ifndef _WIN32
    if (!loader) loader = &native_loader;
#endif
    lock();
    if (runtime.phase == A7_AP_BOUND || runtime.phase == A7_AP_REVIEW) {
        int result = runtime.phase == A7_AP_BOUND ? A7_AP_ALREADY : A7_AP_UNCERTAIN;
        report(out, result, NULL); unlock(); return result;
    }
    if (!loader || !loader->open || !loader->symbol || !loader->close ||
        !loader->owner || !loader->pin_self || runtime.generation == UINT64_MAX) {
        report(out, A7_AP_INVALID, NULL); unlock(); return A7_AP_INVALID;
    }
    runtime.loader = *loader; runtime.failed = UINT32_MAX; runtime.close_attempts = 0;
    runtime.close_error = 0; runtime.primary_status = 0;
    runtime.status = 0; runtime.mask = 0; runtime.message[0] = 0;
    memset(&runtime.api, 0, sizeof(runtime.api));
    runtime.mkdir = NULL;
    runtime.self = runtime.loader.pin_self(runtime.loader.context);
    if (!runtime.self) failure(A7_AP_PIN, UINT32_MAX, "Cannot retain the core module");
    for (unsigned i = 0; !runtime.status && i < 2; ++i) {
        runtime.sdk[i] = runtime.loader.open(runtime.loader.context, modules[i], A7_AP_NOLOAD_NOW);
        if (!runtime.sdk[i]) failure(i ? A7_AP_FSYS_MISSING : A7_AP_MPR_MISSING,
                                     UINT32_MAX, "Required AP SDK module is not loaded");
    }
    void *resolved[7] = {0};
    for (unsigned i = 0; !runtime.status && i < 7; ++i) {
        unsigned module = i >= 5 ? 1 : 0;
        resolved[i] = runtime.loader.symbol(runtime.loader.context, runtime.sdk[module], symbols[i]);
        if (!resolved[i]) failure(A7_AP_SYMBOL, i, "Missing native SDK export");
        else if (runtime.loader.owner(runtime.loader.context, resolved[i], modules[module]) != 1)
            failure(A7_AP_OWNER, i, "Native SDK export belongs to a different module");
        else runtime.mask |= 1u << i;
    }
    if (!runtime.status) {
        memcpy(&runtime.api, resolved, sizeof(runtime.api));
        memcpy(&runtime.mkdir, &resolved[6], sizeof(runtime.mkdir));
        ++runtime.generation; runtime.phase = A7_AP_BOUND;
        report(out, 0, NULL); unlock(); return 0;
    }
    int result = runtime.status;
    void *release = NULL;
    if (!close_sdk()) {
        release = runtime.self; runtime.self = NULL; runtime.mask = 0;
        runtime.phase = A7_AP_IDLE;
    } else result = A7_AP_UNCERTAIN;
    report(out, result, release); unlock(); return result;
}
int a7_ap_query(struct a7_ap_report *out)
{
    if (!out) return A7_AP_INVALID;
    lock(); report(out, runtime.status, NULL); unlock(); return 0;
}
int a7_ap_acquire(uint32_t kind, struct a7_ap_lease *lease, struct a7_ap_report *out)
{
    if (!out || !lease) return A7_AP_INVALID;
    lock();
    int result = 0; unsigned slot = A7_AP_MAX_LEASES;
    if ((kind != A7_AP_JOB && kind != A7_AP_CALLBACK) || lease->token) result = A7_AP_LEASE;
    else if (runtime.phase != A7_AP_BOUND) result = A7_AP_BUSY;
    else if (runtime.next_token == UINT64_MAX) result = A7_AP_LEASE;
    else {
        for (unsigned i = 0; i < A7_AP_MAX_LEASES; ++i)
            if (!runtime.leases[i].token) { slot = i; break; }
        if (slot == A7_AP_MAX_LEASES) result = A7_AP_BUSY;
    }
    if (!result) {
        lease->generation = runtime.generation; lease->token = ++runtime.next_token;
        lease->kind = kind; lease->reserved = 0; lease->api = runtime.api;
        lease->mkdir = kind == A7_AP_JOB ? runtime.mkdir : NULL;
        runtime.leases[slot] = (struct lease_record){lease->token, kind};
    }
    report(out, result, NULL); unlock(); return result;
}
int a7_ap_release(struct a7_ap_lease *lease, struct a7_ap_report *out)
{
    if (!out || !lease) return A7_AP_INVALID;
    lock(); unsigned slot = A7_AP_MAX_LEASES;
    if (runtime.phase == A7_AP_BOUND && lease->token && lease->generation == runtime.generation)
        for (unsigned i = 0; i < A7_AP_MAX_LEASES; ++i)
            if (runtime.leases[i].token == lease->token && runtime.leases[i].kind == lease->kind) { slot = i; break; }
    int result = slot == A7_AP_MAX_LEASES ? A7_AP_LEASE : 0;
    if (!result) { runtime.leases[slot].token = 0; runtime.leases[slot].kind = 0; memset(lease, 0, sizeof(*lease)); }
    report(out, result, NULL); unlock(); return result;
}
int a7_ap_retire(struct a7_ap_report *out)
{
    if (!out) return A7_AP_INVALID;
    lock(); int result = 0; void *release = NULL;
    if (runtime.phase == A7_AP_REVIEW) result = A7_AP_UNCERTAIN;
    else if (runtime.phase != A7_AP_BOUND) result = A7_AP_BUSY;
    else {
        for (unsigned i = 0; i < A7_AP_MAX_LEASES; ++i)
            if (runtime.leases[i].token) { result = A7_AP_BUSY; break; }
    }
    if (!result) {
        result = close_sdk();
        if (!result) {
            release = runtime.self; runtime.self = NULL; runtime.phase = A7_AP_IDLE;
            runtime.mask = 0; runtime.status = 0; runtime.message[0] = 0;
            memset(&runtime.api, 0, sizeof(runtime.api));
            runtime.mkdir = NULL;
        }
    }
    report(out, result, release); unlock(); return result;
}
