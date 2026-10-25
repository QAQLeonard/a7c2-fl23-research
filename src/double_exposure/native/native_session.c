#include "native_session.h"
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <pthread.h>
struct a7_native_session {
    struct a7_sony_sdk sdk;
    struct a7_native_bindings bindings;
    struct a7_native_journal journal;
    struct a7_dcf_state publication;
    struct a7_device *device;
    struct a7_capture_delegate *finish;
    a7_pipe_sink sink;
    void *sink_context;
    uint64_t epoch, generation;
    uint32_t media;
    uint8_t instance[16], wire[64];
    struct a7_device_report last;
    pthread_mutex_t mutex;
    pthread_cond_t wake;
    pthread_t thread;
    unsigned busy, pending, events, stopping, owns_sdk, began;
};
static uint32_t get32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t get64(const uint8_t *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static int save_pipeline(void *context, const struct a7_pipe_snapshot *snapshot)
{
    struct a7_native_session *s = context;
    return s->journal.pipeline(s->journal.context, snapshot);
}
static int save_request(void *context, const struct a7_device_report *report)
{
    struct a7_native_session *s = context;
    return s->journal.request(s->journal.context, report);
}
static int save_publication(void *context, const struct a7_dcf_state *state)
{
    struct a7_native_session *s = context;
    return s->journal.publication(s->journal.context, state);
}
static void route(void *context, const struct a7_pipe_event *event)
{
    struct a7_native_session *s = context;
    pthread_mutex_lock(&s->mutex);
    unsigned stopped = s->stopping || s->last.review;
    pthread_mutex_unlock(&s->mutex);
    if (stopped) return;
    s->sink(s->sink_context, event);
    pthread_mutex_lock(&s->mutex);
    if (!s->last.review) s->events = 1;
    pthread_cond_signal(&s->wake); pthread_mutex_unlock(&s->mutex);
}
static void finished(void *context, const uint8_t raw[20])
{
    struct a7_native_session *s = context;
    if (get32(raw) != s->media) return;
    struct a7_pipe_event event = {0};
    event.kind = A7_PIPE_SAVED; event.epoch = s->epoch; event.generation = s->generation;
    event.media = s->media; event.content = get32(raw + 4); event.capture = event.content + 1;
    event.outcome = get32(raw + 16) ? A7_PAIR_UNKNOWN : A7_PAIR_SUCCESS;
    route(s, &event);
}
static int attach(void *context, a7_pipe_sink sink, void *opaque)
{
    struct a7_native_session *s = context;
    s->sink = sink; s->sink_context = opaque;
    int status = a7_pipeline_identity(opaque, &s->epoch, &s->media, &s->generation);
    if (status) return status;
    memset(&s->publication, 0, sizeof(s->publication));
    if (s->bindings.finish.slot) {
        s->finish = a7_capture_delegate_create(&s->bindings.finish, finished, s);
        if (!s->finish) return A7_PIPE_BACKEND;
        status = a7_capture_delegate_attach(s->finish);
        if (status) return status;
    }
    s->began = 1; /* an error can still leave a registered source */
    return s->bindings.begin_attach(route, s, s->epoch, s->media, s->generation);
}
static int detach(void *context)
{
    struct a7_native_session *s = context;
    int status = s->began ? s->bindings.begin_detach(s) : 0;
    if (status) return status;
    s->began = 0;
    if (!s->finish) return 0;
    status = a7_capture_delegate_detach(s->finish);
    if (status) return status;
    status = a7_capture_delegate_destroy(s->finish);
    if (!status) s->finish = NULL;
    return status;
}
static int resolve(void *context, struct a7_pipe_event *event)
{
    struct a7_native_session *s = context;
    if (event->outcome != A7_PAIR_SUCCESS || event->content > UINT32_MAX) return A7_PIPE_BACKEND;
    uint32_t media = UINT32_MAX;
    int status = s->bindings.sdk->catalog.media((uint32_t)event->content, &media);
    if (status || media != event->media) return A7_PIPE_BACKEND;
    struct a7_sidb_record record = {0};
    s->bindings.sdk->catalog.clear(&record);
    status = s->bindings.sdk->catalog.select(UINT32_MAX, (uint32_t)event->content, &record, 0);
    if (status) return status;
    const uint8_t *raw = (const uint8_t *)&record;
    if (get32(raw + 4) != event->content || !raw[0xc0] || !memchr(raw + 0xc1, 0, 262))
        return A7_PIPE_BACKEND;
    memcpy(event->path, raw + 0xc1, 262);
    return 0;
}
static int publish(void *context, const struct a7_pair_job *job, const char *temp,
                    uint64_t bytes, const uint8_t expected[32], struct a7_pipe_publication *out)
{
    struct a7_native_session *s = context;
    struct a7_dcf_api api = s->bindings.sdk->dcf;
    api.context = s; api.save = save_publication;
    return a7_dcf_publish(&s->publication, &api, job, temp, bytes, expected, out);
}
static void *worker(void *context)
{
    struct a7_native_session *s = context;
    for (;;) {
        uint8_t wire[64];
        pthread_mutex_lock(&s->mutex);
        while (!s->pending && !s->events && !s->stopping) pthread_cond_wait(&s->wake, &s->mutex);
        if (s->stopping) { pthread_mutex_unlock(&s->mutex); return NULL; }
        unsigned command = s->pending;
        if (command) { memcpy(wire, s->wire, 64); s->pending = 0; }
        s->events = 0; s->busy = 1;
        pthread_mutex_unlock(&s->mutex);
        struct a7_device_report report;
        int status = command ? a7_device_execute(s->device, wire, 64, &report) :
                               a7_device_background_work(s->device, &report);
        pthread_mutex_lock(&s->mutex);
        if (command) s->last = report;
        else {
            s->last.pipeline = report.pipeline;
            s->last.review = report.review;
            if (status != A7_PIPE_STATE) s->last.status = status;
        }
        if (command && get32(wire + 8) == A7_DEVICE_DISABLE && !status) s->events = 0;
        if (s->last.review) s->events = 0;
        s->busy = 0; pthread_cond_broadcast(&s->wake); pthread_mutex_unlock(&s->mutex);
    }
}
static struct a7_native_session *start(struct a7_native_session *s, const uint8_t instance[16],
                                      const struct a7_native_journal *journal, int *status)
{
    if (!journal || !journal->pipeline || !journal->request || !journal->publication) {
        *status = A7_DEVICE_INVALID; return NULL;
    }
    s->journal = *journal; memcpy(s->instance, instance, 16); s->last.abi = 1;
    struct a7_pipe_backend backend = {s, save_pipeline, attach, detach, publish, resolve, s->bindings.sdk->catalog};
    s->device = a7_device_create(instance, &backend, save_request);
    if (!s->device) { *status = A7_DEVICE_INVALID; return NULL; }
    *status = pthread_mutex_init(&s->mutex, NULL);
    if (*status) goto device_failed;
    *status = pthread_cond_init(&s->wake, NULL);
    if (*status) goto mutex_failed;
    pthread_attr_t attributes;
    *status = pthread_attr_init(&attributes);
    if (!*status) {
        *status = pthread_attr_setstacksize(&attributes, 512u * 1024u);
        if (!*status) *status = pthread_create(&s->thread, &attributes, worker, s);
        pthread_attr_destroy(&attributes);
    }
    if (!*status) return s;
    pthread_cond_destroy(&s->wake);
mutex_failed:
    pthread_mutex_destroy(&s->mutex);
device_failed:
    a7_device_destroy(s->device); s->device = NULL; return NULL;
}
struct a7_native_session *a7_native_session_create(const uint8_t instance[16], uintptr_t ap_base,
    const struct a7_native_journal *journal, int *status)
{
    if (!status) return NULL;
    if (!instance) { *status = A7_DEVICE_INVALID; return NULL; }
    struct a7_native_session *s = calloc(1, sizeof(*s));
    if (!s) { *status = A7_PIPE_BACKEND; return NULL; }
    uintptr_t identified = 0;
    *status = a7_sony_find_ap(&identified);
    if (!*status && identified != ap_base) *status = A7_AP_OWNER;
    if (!*status) *status = a7_sony_sdk_bind(&s->sdk);
    if (*status) { if (!s->sdk.review) free(s); return NULL; }
    s->owns_sdk = 1; s->bindings.sdk = &s->sdk;
    s->bindings.begin_attach = a7_sony_begin_attach; s->bindings.begin_detach = a7_sony_begin_detach;
    if (start(s, instance, journal, status)) return s;
    int closing = a7_sony_sdk_close(&s->sdk);
    if (closing) { *status = closing; return NULL; } /* retain uncertain references */
    free(s); return NULL;
}
struct a7_native_session *a7_native_session_create_bound(const uint8_t instance[16],
    const struct a7_native_bindings *bindings, const struct a7_native_journal *journal, int *status)
{
    if (!status) return NULL;
    if (!instance || !bindings || !bindings->sdk || !bindings->sdk->bound ||
        !bindings->begin_attach || !bindings->begin_detach) { *status = A7_DEVICE_INVALID; return NULL; }
    struct a7_native_session *s = calloc(1, sizeof(*s));
    if (!s) { *status = A7_PIPE_BACKEND; return NULL; }
    s->bindings = *bindings;
    if (start(s, instance, journal, status)) return s;
    free(s); return NULL;
}
int a7_native_session_poll(struct a7_native_session *s, struct a7_device_report *out)
{
    if (!s || !out) return A7_DEVICE_INVALID;
    pthread_mutex_lock(&s->mutex); *out = s->last;
    if (s->busy || s->pending || s->events) { out->intent = 1; out->status = A7_DEVICE_BUSY; }
    pthread_mutex_unlock(&s->mutex); return out->status;
}
int a7_native_session_submit(struct a7_native_session *s, const void *wire, size_t size,
                            struct a7_device_report *out)
{
    if (!s || !wire || !out || size != 64) return A7_DEVICE_INVALID;
    const uint8_t *w = wire;
    unsigned op = get32(w + 8);
    if (memcmp(w, "A7DEX001", 8) || memcmp(w + 48, s->instance, 16) || get32(w + 12) ||
        !get64(w + 16) || op < A7_DEVICE_ARM || op > A7_DEVICE_DISABLE ||
        (op == A7_DEVICE_ARM ? (!get64(w + 24) || !get64(w + 32) || get32(w + 44) > 0xffffffu) :
         (get64(w + 24) || get64(w + 32) || get32(w + 40) || get32(w + 44)))) return A7_DEVICE_INVALID;
    if (get32(w + 8) == A7_DEVICE_QUERY) return a7_native_session_poll(s, out);
    pthread_mutex_lock(&s->mutex);
    if (s->stopping || s->pending || (s->busy && op != A7_DEVICE_DISABLE)) { pthread_mutex_unlock(&s->mutex); return A7_DEVICE_BUSY; }
    memcpy(s->wire, wire, 64); s->pending = 1;
    memset(out, 0, sizeof(*out)); out->abi = 1; out->operation = get32(w + 8);
    out->request_id = get64(w + 16); out->intent = 1;
    s->last = *out;
    pthread_cond_signal(&s->wake); pthread_mutex_unlock(&s->mutex); return 0;
}
int a7_native_session_destroy(struct a7_native_session *s)
{
    if (!s) return A7_DEVICE_INVALID;
    pthread_mutex_lock(&s->mutex);
    if (s->stopping || s->busy || s->pending || s->events || s->last.pipeline.active || s->last.review) {
        pthread_mutex_unlock(&s->mutex); return A7_DEVICE_BUSY;
    }
    s->stopping = 1; pthread_cond_signal(&s->wake); pthread_mutex_unlock(&s->mutex);
    if (pthread_join(s->thread, NULL)) return A7_AP_UNCERTAIN;
    int status = a7_device_destroy(s->device);
    if (status) return status;
    if (s->owns_sdk && (status = a7_sony_sdk_close(&s->sdk))) return status;
    pthread_cond_destroy(&s->wake); pthread_mutex_destroy(&s->mutex);
    free(s); return 0;
}
#else
struct a7_native_session *a7_native_session_create(const uint8_t i[16], uintptr_t b,
 const struct a7_native_journal *j, int *s) { (void)i; (void)b; (void)j; if(s)*s=A7_AP_INVALID; return NULL; }
struct a7_native_session *a7_native_session_create_bound(const uint8_t i[16],
 const struct a7_native_bindings *b, const struct a7_native_journal *j, int *s)
{ (void)i; (void)b; (void)j; if(s)*s=A7_AP_INVALID; return NULL; }
int a7_native_session_submit(struct a7_native_session *s,const void *w,size_t n,struct a7_device_report *r)
{ (void)s; (void)w; (void)n; (void)r; return A7_AP_INVALID; }
int a7_native_session_poll(struct a7_native_session *s,struct a7_device_report *r)
{ (void)s; (void)r; return A7_AP_INVALID; }
int a7_native_session_destroy(struct a7_native_session *s) { (void)s; return A7_AP_INVALID; }
#endif
