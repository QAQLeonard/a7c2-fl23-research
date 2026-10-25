#ifndef A7C2_AP_RUNTIME_H
#define A7C2_AP_RUNTIME_H
#include "mpr_stream.h"
#include "output_reservation.h"

#define A7_AP_RUNTIME_ABI 1u
#define A7_AP_NOLOAD_NOW 6 /* Linux RTLD_NOLOAD | RTLD_NOW, RTLD_LOCAL == 0 */
#define A7_AP_MAX_LEASES 32
enum a7_ap_phase { A7_AP_IDLE, A7_AP_BOUND, A7_AP_REVIEW };
enum a7_ap_lease_kind { A7_AP_JOB = 1, A7_AP_CALLBACK = 2 };
enum a7_ap_error {
    A7_AP_ALREADY = 1, A7_AP_MPR_MISSING = -11001, A7_AP_FSYS_MISSING = -11002,
    A7_AP_SYMBOL = -11003, A7_AP_OWNER = -11004, A7_AP_PIN = -11005,
    A7_AP_BUSY = -11006, A7_AP_LEASE = -11007, A7_AP_UNCERTAIN = -11008,
    A7_AP_INVALID = -11009
};
struct a7_ap_loader {
    void *context;
    void *(*open)(void *, const char *, int);
    void *(*symbol)(void *, void *, const char *);
    int (*close)(void *, void *);
    int (*owner)(void *, void *symbol, const char *module);
    void *(*pin_self)(void *);
    const char *(*error)(void *);
};
struct a7_ap_report {
    uint32_t abi, phase, bound_mask, jobs, callbacks, owned_sdk_mask;
    uint32_t failed_symbol, close_attempts;
    int32_t status, close_error, primary_status, reserved;
    uint64_t generation;
    void *release_handle;
    char message[256];
};
struct a7_ap_lease {
    uint64_t generation, token;
    uint32_t kind, reserved;
    struct a7_mpr_api api;
    a7_mkdir_fn mkdir;
};

/* Process-local singleton. With loader==NULL, use Linux dlopen(NOLOAD),
 * dlsym and dladdr; custom loader operations support offline tests and must
 * not re-enter this API. BOUND means symbols resolved, not SDK readiness.
 * No SDK Init/Open/Read/Write, thread creation or callback installation occurs.
 * The caller keeps a temporary core-module reference during every call.
 */
A7_JPEG_API uint32_t a7_ap_runtime_abi(void);
A7_JPEG_API int a7_ap_start(const struct a7_ap_loader *, struct a7_ap_report *);
A7_JPEG_API int a7_ap_query(struct a7_ap_report *);
A7_JPEG_API int a7_ap_acquire(uint32_t kind, struct a7_ap_lease *, struct a7_ap_report *);
A7_JPEG_API int a7_ap_release(struct a7_ap_lease *, struct a7_ap_report *);
A7_JPEG_API int a7_ap_retire(struct a7_ap_report *);

/* A job lease lasts through SDK I/O and closure/reconciliation of its handles.
 * A callback lease lasts through native unregistration AND rundown. Release
 * clears the lease's function table; copied/stale tokens cannot release twice.
 * The manager cannot establish native callback rundown on the caller's behalf.
 *
 * start failure or successful retire may return release_handle. It transfers
 * ONE core-module reference to the caller. dlclose it OUTSIDE this module,
 * after this call returns, while the caller's temporary reference still holds.
 * Never persist handles, leases or function pointers across process/module life.
 */
#endif
