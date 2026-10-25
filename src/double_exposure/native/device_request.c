#include "device_request.h"
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
_Static_assert(sizeof(struct a7_pipe_snapshot) == 2800, "Unsupported pipeline wire report ABI");
_Static_assert(sizeof(struct a7_device_report) == 2832, "Unsupported device wire report ABI");
struct a7_device {
    struct a7_pipeline *pipeline;
    uint8_t instance[16], last_wire[64];
    struct a7_device_report last;
    int (*save)(void *, const struct a7_device_report *);
    void *context;
    atomic_flag busy;
    int poisoned;
};
static uint32_t u32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t u64(const uint8_t *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
struct a7_device *a7_device_create(const uint8_t instance[16], const struct a7_pipe_backend *backend,
                                  int (*save)(void *, const struct a7_device_report *))
{
    if (!instance || !backend || !save) return NULL;
    unsigned any = 0;
    for (unsigned i = 0; i < 16; ++i) any |= instance[i];
    if (!any) return NULL;
    struct a7_device *d = calloc(1, sizeof(*d));
    if (!d) return NULL;
    d->pipeline = a7_pipeline_create(backend);
    if (!d->pipeline) { free(d); return NULL; }
    memcpy(d->instance, instance, 16); d->save = save; d->context = backend->context;
    atomic_flag_clear(&d->busy); return d;
}
int a7_device_execute(struct a7_device *d, const void *wire, size_t length, struct a7_device_report *out)
{
    if (!out) return A7_DEVICE_INVALID;
    memset(out, 0, sizeof(*out)); out->abi = 1;
    const uint8_t *w = wire;
    if (!d || !w || length != 64 || memcmp(w, "A7DEX001", 8) || u32(w + 12) ||
        memcmp(w + 48, d->instance, 16)) return out->status = A7_DEVICE_INVALID;
    out->operation = u32(w + 8); out->request_id = u64(w + 16);
    if (out->operation < A7_DEVICE_ARM || out->operation > A7_DEVICE_DISABLE || !out->request_id)
        return out->status = A7_DEVICE_INVALID;
    if (out->operation == A7_DEVICE_ARM ? (!u64(w + 24) || !u64(w + 32) || u32(w + 44) > 0xffffffu) :
        (u64(w + 24) || u64(w + 32) || u32(w + 40) || u32(w + 44)))
        return out->status = A7_DEVICE_INVALID;
    if (atomic_flag_test_and_set(&d->busy)) return out->status = A7_DEVICE_BUSY;
    int status;
    if (out->operation == A7_DEVICE_QUERY) {
        status = a7_pipeline_query(d->pipeline, &out->pipeline);
        out->review = d->poisoned || out->pipeline.review;
    } else if (d->poisoned) {
        out->review = 1; status = A7_DEVICE_REVIEW;
    } else if (out->request_id <= d->last.request_id) {
        if (out->request_id == d->last.request_id && !memcmp(w, d->last_wire, 64)) {
            *out = d->last; status = out->status;
        } else status = A7_DEVICE_STALE;
    } else {
        out->intent = 1;
        status = d->save(d->context, out);
        if (status) { out->journal_error = status; out->review = 1; d->poisoned = 1; status = A7_DEVICE_REVIEW; }
        else {
            if (out->operation == A7_DEVICE_ARM) status = a7_pipeline_arm(d->pipeline,
                u64(w + 24), u32(w + 40), u64(w + 32), u32(w + 44));
            else if (out->operation == A7_DEVICE_WORK) status = a7_pipeline_work(d->pipeline);
            else status = a7_pipeline_disable(d->pipeline);
            out->status = status; out->intent = 0;
            int queried = a7_pipeline_query(d->pipeline, &out->pipeline);
            if (queried && !status) status = queried;
            out->review = out->pipeline.review;
            out->status = status;
            int saved = d->save(d->context, out);
            if (saved) { out->journal_error = saved; out->review = 1; d->poisoned = 1; status = A7_DEVICE_REVIEW; }
            if (out->review) d->poisoned = 1;
        }
        out->status = status; d->last = *out; memcpy(d->last_wire, w, 64);
    }
    out->status = status;
    atomic_flag_clear(&d->busy); return status;
}
int a7_device_destroy(struct a7_device *d)
{
    if (!d) return A7_DEVICE_INVALID;
    if (atomic_flag_test_and_set(&d->busy)) return A7_DEVICE_BUSY;
    int status = a7_pipeline_destroy(d->pipeline);
    if (!status) free(d);
    else atomic_flag_clear(&d->busy);
    return status;
}
int a7_device_background_work(struct a7_device *d, struct a7_device_report *out)
{
    if (!d || !out) return A7_DEVICE_INVALID;
    memset(out, 0, sizeof(*out)); out->abi = 1; out->operation = A7_DEVICE_WORK;
    if (atomic_flag_test_and_set(&d->busy)) return out->status = A7_DEVICE_BUSY;
    int status = d->poisoned ? A7_DEVICE_REVIEW : a7_pipeline_work(d->pipeline);
    a7_pipeline_query(d->pipeline, &out->pipeline);
    out->review = d->poisoned || out->pipeline.review;
    if (out->review) d->poisoned = 1;
    out->status = status;
    if (out->review) {
        int saved = d->save(d->context, out);
        if (saved) { out->journal_error = saved; d->poisoned = 1; status = A7_DEVICE_REVIEW; out->status = status; }
    }
    atomic_flag_clear(&d->busy); return status;
}
