#ifndef A7C2_NATIVE_SESSION_H
#define A7C2_NATIVE_SESSION_H
#include "device_request.h"
#include "sony_sdk.h"
#include "sony_begin.h"
struct a7_native_journal {
    void *context;
    int (*pipeline)(void *, const struct a7_pipe_snapshot *);
    int (*request)(void *, const struct a7_device_report *);
    int (*publication)(void *, const struct a7_dcf_state *);
};
struct a7_native_bindings {
    struct a7_sony_sdk *sdk;
    struct a7_delegate_api finish;
    /* With finish.slot==NULL, this observer supplies BOTH BEGIN/SAVED and
     * drains both sink/context users. Production uses this combined mode so
     * the native AP delegate registry/lifecycle remains untouched. */
    int (*begin_attach)(a7_pipe_sink, void *, uint64_t, uint32_t, uint64_t);
    int (*begin_detach)(void *);
};
struct a7_native_session;
/* Native production constructor: already-BOUND AP, qualified loaded Sony SDK,
 * checked 2.01 AP registry and one background worker. No callback installation
 * occurs before an explicit ARM request. The caller owns journal durability.
 * Windows has no native camera backend. Never auto-fallback to a fake SDK.
 */
A7_JPEG_API struct a7_native_session *a7_native_session_create(const uint8_t instance[16],
    uintptr_t ap_base, const struct a7_native_journal *, int *status);
/* Explicit provider seam for SDK integration and offline tests. All borrowed
 * APIs/contexts/module leases must outlive the session. No address discovery. */
A7_JPEG_API struct a7_native_session *a7_native_session_create_bound(const uint8_t instance[16],
    const struct a7_native_bindings *, const struct a7_native_journal *, int *status);
/* Mutations enqueue and return intent=1, not completion. Poll for the accepted
 * request ID and intent=0; inspect pipeline phase/review separately. Callback
 * packets only enqueue/wake; all SDK/file/JPEG/catalog work runs on the worker.
 * QUERY/poll never start captures, encode, register or alter the callback slots.
 */
A7_JPEG_API int a7_native_session_submit(struct a7_native_session *, const void *, size_t,
    struct a7_device_report *);
A7_JPEG_API int a7_native_session_poll(struct a7_native_session *, struct a7_device_report *);
/* Caller serializes destruction/object lifetime. Requires completed explicit
 * DISABLE and drained callbacks. Production begin
 * forwarding code remains pinned until AP exit (see sony_begin.h). */
A7_JPEG_API int a7_native_session_destroy(struct a7_native_session *);
#endif
