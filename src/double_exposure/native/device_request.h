#ifndef A7C2_DEVICE_REQUEST_H
#define A7C2_DEVICE_REQUEST_H
#include "pipeline.h"
#define A7_DEVICE_REQUEST_BYTES 64u
enum a7_device_operation { A7_DEVICE_ARM = 1, A7_DEVICE_WORK, A7_DEVICE_QUERY, A7_DEVICE_DISABLE };
enum a7_device_error { A7_DEVICE_INVALID = -16001, A7_DEVICE_STALE = -16002,
    A7_DEVICE_REVIEW = -16003, A7_DEVICE_BUSY = -16004 };
struct a7_device_report {
    uint32_t abi, operation, intent, review;
    uint64_t request_id;
    int32_t status, journal_error;
    struct a7_pipe_snapshot pipeline;
};
struct a7_device;
/* Explicit binary request entry; it does not discover/open USB or load files.
 * Wire64: magic A7DEX001@0, op:u32@8, reserved0:u32@12, request_id:u64@16,
 * epoch:u64@24, generation:u64@32, media:u32@40, nonce:u32@44, instance16@48.
 * ARM supplies the four arm fields; other operations require them all zero.
 * ARM media==UINT32_MAX selects the first eligible SDK begin media; the pair
 * then stays bound to that actual native media ID (not a slot-number guess).
 * Instance identity is process-local and fixed at create. IDs increase for
 * mutating requests. Exact replay returns only the cached completed report;
 * mismatched replay, incomplete persistence and unknown results never execute.
 * Query is read-only. WORK must be dispatched from a background caller.
 * save_request durably persists reports before and after each mutation. It
 * must not call back into this entry. The backend must supply actual validated
 * camera adapters for device use; local fake backends are offline tests only.
 */
A7_JPEG_API struct a7_device *a7_device_create(const uint8_t instance[16],
    const struct a7_pipe_backend *, int (*save_request)(void *, const struct a7_device_report *));
A7_JPEG_API int a7_device_execute(struct a7_device *, const void *, size_t, struct a7_device_report *);
A7_JPEG_API int a7_device_destroy(struct a7_device *);
A7_JPEG_API int a7_device_background_work(struct a7_device *, struct a7_device_report *);
#endif
