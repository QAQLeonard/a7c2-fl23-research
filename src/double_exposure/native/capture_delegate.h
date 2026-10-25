#ifndef A7C2_CAPTURE_DELEGATE_H
#define A7C2_CAPTURE_DELEGATE_H
#include "jpeg_stream.h"
struct a7_capture_delegate;
struct a7_delegate_object {
    void (**vtable)(struct a7_delegate_object *, void *);
};
struct a7_delegate_api {
    void *context;
    struct a7_delegate_object **slot;
    /* Exact same 2.01 AP registry mutex held by register/unregister AND native
     * dispatcher through the delegate call. Lock callbacks must not re-enter. */
    int (*lock)(void *);
    int (*unlock)(void *);
};
typedef void (*a7_delegate_sink)(void *, const uint8_t raw[20]);
/* Preserve and forward the original AP delegate with the ORIGINAL pointer and
 * ownership. Copy only the 20-byte notification before forwarding; the native
 * delegate may free the payload. A sink must only enqueue bounded data.
 * Successful detach under the SAME native lock establishes synchronous native
 * rundown. Do not detach from inside the native callback. Unknown lock/unlock
 * or a replaced slot keeps the adapter/lease alive for review.
 *
 * This is the checked bridge implementation, not an address scanner/installer.
 * Caller owns the original delegate's registration lifetime through detach;
 * an owner-managed native unregister must never encounter a proxy slot.
 * Production session uses SDK forwarding instead; this bridge is an explicit
 * integration seam for owners that can establish that lifetime contract.
 * Caller validates loaded AP identity, registry address/mutex and acquires the
 * AP callback lease BEFORE attaching; releases only AFTER successful detach.
 * The 20-byte finish notification contains media/UID/count/flags/error, but no
 * path. Resolve the UID through a fresh SIDB Select on the background worker.
 */
A7_JPEG_API struct a7_capture_delegate *a7_capture_delegate_create(
    const struct a7_delegate_api *, a7_delegate_sink, void *);
A7_JPEG_API int a7_capture_delegate_attach(struct a7_capture_delegate *);
A7_JPEG_API int a7_capture_delegate_detach(struct a7_capture_delegate *);
A7_JPEG_API int a7_capture_delegate_destroy(struct a7_capture_delegate *);
#endif
