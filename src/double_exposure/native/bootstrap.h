#ifndef A7C2_BOOTSTRAP_H
#define A7C2_BOOTSTRAP_H
#include "ap_runtime.h"

#define A7_BOOT_ABI 1u
enum a7_boot_operation { A7_BOOT_START = 1, A7_BOOT_QUERY, A7_BOOT_RETIRE };
enum a7_boot_error {
    A7_BOOT_INVALID = -12001, A7_BOOT_NOT_RESIDENT = -12002,
    A7_BOOT_LOAD = -12003, A7_BOOT_SYMBOL = -12004,
    A7_BOOT_OWNER = -12005, A7_BOOT_VERSION = -12006, A7_BOOT_CLOSE = -12007
};
struct a7_boot_loader {
    void *context;
    void *(*open)(void *, const char *, int);
    void *(*symbol)(void *, void *, const char *);
    int (*owns)(void *, void *module, void *symbol);
    int (*close)(void *, void *);
};
struct a7_boot_report {
    uint32_t abi, operation, called, close_attempts;
    int32_t status, core_status, close_error;
    uint32_t review;
    struct a7_ap_report runtime; /* release_handle is always cleared */
};

/* Caller serializes control requests and supplies an absolute, immutable,
 * already verified core path in its owned staging directory. START may load
 * the core (and thus execute its ELF startup code). QUERY/RETIRE use NOLOAD.
 * Resolve and qualify all control exports before calling any of them.
 * Close the returned self-pin outside the core, then the temporary reference.
 * A failed close stops without retry; review requires process-local evidence.
 * Reports contain no transferable loader references. Never replay an unknown
 * dispatch or persist loader handles across requests/processes.
 *
 * This is an explicit-call helper, not a libJit _init/device upload entry.
 * No file assembly, SDK initialization, callbacks, threads or camera transport.
 * With loader==NULL Linux uses dlopen/dlsym/dlinfo/dladdr; custom operations
 * support offline fault injection and must not re-enter the helper.
 */
A7_JPEG_API int a7_boot_dispatch(const char *path, uint32_t operation,
                               const struct a7_boot_loader *, struct a7_boot_report *);
#endif
