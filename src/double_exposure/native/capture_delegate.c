#include "capture_delegate.h"
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
struct a7_capture_delegate {
    struct a7_delegate_object object;
    void (*methods[1])(struct a7_delegate_object *, void *);
    struct a7_delegate_api api;
    struct a7_delegate_object *original;
    a7_delegate_sink sink;
    void *context;
    unsigned attached;
    atomic_uint review;
};
static void notify(struct a7_delegate_object *object, void *payload)
{
    struct a7_capture_delegate *d = (struct a7_capture_delegate *)object;
    uint8_t copy[20];
    if (payload && !d->review) {
        memcpy(copy, payload, sizeof(copy));
        d->sink(d->context, copy);
    }
    /* Native callback owns payload; forwarding is unconditional and exact. */
    d->original->vtable[0](d->original, payload);
}
struct a7_capture_delegate *a7_capture_delegate_create(const struct a7_delegate_api *a,
                                                       a7_delegate_sink sink, void *context)
{
    if (!a || !a->slot || !a->lock || !a->unlock || !sink) return NULL;
    struct a7_capture_delegate *d = calloc(1, sizeof(*d));
    if (!d) return NULL;
    d->api = *a; d->sink = sink; d->context = context; atomic_init(&d->review, 0);
    d->methods[0] = notify; d->object.vtable = d->methods;
    return d;
}
int a7_capture_delegate_attach(struct a7_capture_delegate *d)
{
    if (!d || d->attached || d->review) return -1;
    if (d->api.lock(d->api.context)) { d->review = 1; return -2; }
    int status = 0;
    struct a7_delegate_object *original = *d->api.slot;
    if (!original || !original->vtable || !original->vtable[0] || original == &d->object) status = -3;
    else {
        d->original = original; d->attached = 1;
        *d->api.slot = &d->object;
    }
    if (d->api.unlock(d->api.context)) { d->review = 1; status = -2; }
    return status;
}
int a7_capture_delegate_detach(struct a7_capture_delegate *d)
{
    if (!d || !d->attached || d->review) return -1;
    if (d->api.lock(d->api.context)) { d->review = 1; return -2; }
    int status = 0;
    if (*d->api.slot != &d->object) { d->review = 1; status = -3; }
    else *d->api.slot = d->original;
    if (d->api.unlock(d->api.context)) { d->review = 1; status = -2; }
    if (!status) d->attached = 0;
    return status;
}
int a7_capture_delegate_destroy(struct a7_capture_delegate *d)
{
    if (!d || d->attached || d->review) return -1;
    free(d); return 0;
}
