#include "pipeline.h"
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#include "../../fl23/native/sha256.h"
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#endif
struct a7_pipeline {
    struct a7_pipe_backend backend;
    struct a7_pipe_snapshot state;
    struct a7_pipe_event queue[A7_PIPE_QUEUE];
    uint32_t head, count, accepting, overflow, nonce, worker, event_fault;
    struct a7_ap_lease job, callback;
    struct a7_output_reservation output;
    struct a7_catalog catalog;
    struct a7_mpr_stream inputs[2];
#ifdef _WIN32
    SRWLOCK lock;
#else
    pthread_mutex_t lock;
#endif
};
#ifdef _WIN32
static void lock(struct a7_pipeline *p) { AcquireSRWLockExclusive(&p->lock); }
static void unlock(struct a7_pipeline *p) { ReleaseSRWLockExclusive(&p->lock); }
#else
static void lock(struct a7_pipeline *p) { pthread_mutex_lock(&p->lock); }
static void unlock(struct a7_pipeline *p) { pthread_mutex_unlock(&p->lock); }
#endif
static int stop(struct a7_pipeline *p, int status, int detail)
{
    lock(p); p->state.review = 1; p->state.status = status;
    p->state.backend_error = detail; p->state.pair.phase = A7_PAIR_REVIEW;
    p->accepting = 0; unlock(p); return status;
}
static void semantic_state(struct a7_pipeline *p)
{
    p->state.queued = p->count; p->state.output_phase = p->output.phase;
    p->state.pending_handle = p->output.pending_handle;
    p->state.output_bytes = p->output.encoded_bytes;
    p->state.catalog_phase = p->catalog.phase;
    p->state.catalog_uid = p->catalog.uid; p->state.catalog_uid_valid = p->catalog.uid_valid;
    p->state.catalog_error = p->catalog.native_error;
    p->state.output_error = p->output.writer.close_error ? p->output.writer.close_error : p->output.native_error;
    for (unsigned i = 0; i < 2; ++i) {
        p->state.input_handles[i] = p->inputs[i].handle;
        p->state.input_phases[i] = p->inputs[i].phase;
    }
}
static int save(struct a7_pipeline *p, uint32_t step, uint32_t intent)
{
    struct a7_pipe_snapshot copy;
    lock(p);
    p->state.step = step; p->state.intent = intent; ++p->state.sequence;
    semantic_state(p);
    copy = p->state;
    unlock(p);
    int status = p->backend.save(p->backend.context, &copy);
    return status ? stop(p, A7_PIPE_JOURNAL, status) : 0;
}
struct a7_pipeline *a7_pipeline_create(const struct a7_pipe_backend *b)
{
    if (!b || !b->save || !b->attach || !b->detach || !b->publish ||
        !b->catalog.clear || !b->catalog.select || !b->catalog.issue ||
        !b->catalog.update || !b->catalog.media || !b->catalog.flush) return NULL;
    struct a7_pipeline *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    p->backend = *b; p->state.abi = A7_PIPE_ABI;
#ifdef _WIN32
    InitializeSRWLock(&p->lock);
#else
    if (pthread_mutex_init(&p->lock, NULL)) { free(p); return NULL; }
#endif
    return p;
}
int a7_pipeline_arm(struct a7_pipeline *p, uint64_t epoch, uint32_t media,
                    uint64_t generation, uint32_t nonce)
{
    if (!p || nonce > 0xffffffu) return A7_PIPE_INVALID;
    lock(p);
    if (p->worker || p->state.active || p->state.review || p->callback.token || p->job.token) {
        unlock(p); return A7_PIPE_STATE;
    }
    int status = a7_pair_arm(&p->state.pair, epoch, media, generation);
    if (status) { unlock(p); return status; }
    p->worker = 1; p->nonce = nonce; p->state.active = 1; p->event_fault = 0; p->overflow = 0;
    memset(&p->output, 0, sizeof(p->output)); memset(&p->catalog, 0, sizeof(p->catalog));
    memset(p->inputs, 0, sizeof(p->inputs));
    memset(&p->state.publication, 0, sizeof(p->state.publication));
    memset(p->state.encoded_digest, 0, sizeof(p->state.encoded_digest));
    unlock(p);
    struct a7_ap_report report;
    status = a7_ap_acquire(A7_AP_CALLBACK, &p->callback, &report);
    if (!status) status = save(p, A7_PIPE_ARM, 1);
    if (!status) {
        lock(p); p->accepting = 1; unlock(p);
        status = p->backend.attach(p->backend.context, a7_pipeline_notify, p);
        /* Failure may still leave a callback installed; keep the lease. */
        lock(p); p->state.attached = 1; unlock(p);
        if (status) status = stop(p, A7_PIPE_BACKEND, status);
        else status = save(p, A7_PIPE_ARM, 0);
    } else if (!p->state.review) status = stop(p, A7_PIPE_BACKEND, status);
    lock(p); p->worker = 0; unlock(p);
    return status;
}
void a7_pipeline_notify(void *context, const struct a7_pipe_event *event)
{
    struct a7_pipeline *p = context;
    if (!p || !event) return;
    lock(p);
    if (!p->accepting || event->epoch != p->state.pair.epoch) { unlock(p); return; }
    if (event->kind == A7_PIPE_EVENT_FAULT) {
        p->event_fault = 1; p->accepting = 0; unlock(p); return;
    }
    if ((event->kind != A7_PIPE_BEGIN && event->kind != A7_PIPE_SAVED) || event->reserved ||
        !event->capture || !memchr(event->path, 0, sizeof(event->path)) || p->count == A7_PIPE_QUEUE) {
        p->overflow = 1; p->accepting = 0; unlock(p); return;
    }
    p->queue[(p->head + p->count) % A7_PIPE_QUEUE] = *event;
    ++p->count;
    unlock(p);
}
static int release_job(struct a7_pipeline *p)
{
    struct a7_ap_report report;
    int status = a7_ap_release(&p->job, &report);
    return status ? stop(p, A7_PIPE_BACKEND, status) : 0;
}
struct digest_writer { struct a7_jpeg_output native; SHA256 sha; };
static int64_t write_digest(void *context, const void *bytes, size_t length)
{
    struct digest_writer *writer = context;
    int64_t count = writer->native.write(writer->native.context, bytes, length);
    if (count > 0 && (uint64_t)count <= length) sha_add(&writer->sha, bytes, (uint32_t)count);
    return count;
}
static int encode(struct a7_pipeline *p, struct a7_pair_job *job)
{
    struct a7_jpeg_input inputs[2]; struct a7_jpeg_output output;
    struct digest_writer writer = {0}; sha_init(&writer.sha);
    struct a7_jpeg_result result = {0};
    int status = 0, uncertain = 0;
    for (unsigned i = 0; !status && i < 2; ++i) {
        status = a7_mpr_open_reader(&p->inputs[i], &p->job.api, job->shots[i].path);
        if (!status) status = a7_mpr_get_input(&p->inputs[i], &inputs[i]);
    }
    if (!status) status = a7_mpr_get_output(&p->output.writer, &writer.native);
    output = (struct a7_jpeg_output){&writer, write_digest};
    if (!status) status = a7_jpeg_mean(&inputs[0], &inputs[1], &output, NULL, &result);
    if (!status) status = a7_mpr_flush_writer(&p->output.writer);
    for (unsigned i = 0; i < 3; ++i) {
        struct a7_mpr_stream *s = i == 2 ? &p->output.writer : &p->inputs[i];
        if (s->owned && !s->close_attempted) {
            int closing = a7_mpr_close(s);
            if (closing && !status) status = closing;
        }
        if (s->owned || s->phase == A7_MPR_REVIEW) uncertain = 1;
    }
    if (uncertain) return stop(p, A7_PIPE_BACKEND, result.io_error ? (int32_t)result.io_error :
                               status ? status : A7_MPR_CONTRACT);
    if (!status) status = a7_output_note_closed(&p->output, job->epoch, result.output_bytes);
    if (status) return stop(p, A7_PIPE_BACKEND, result.io_error ? (int32_t)result.io_error : status);
    sha_end(&writer.sha, p->state.encoded_digest);
    return 0;
}
static int process(struct a7_pipeline *p)
{
    struct a7_ap_report report;
    int status = a7_ap_acquire(A7_AP_JOB, &p->job, &report);
    if (status) return stop(p, A7_PIPE_BACKEND, status);
    char parent[512];
    memcpy(parent, p->state.pair.shots[0].path, sizeof(parent));
    char *slash = strrchr(parent, '/');
    if (!slash) return stop(p, A7_PIPE_INVALID, 0);
    *slash = 0;
    uint64_t epoch = p->state.pair.epoch;
    status = a7_output_plan(&p->output, epoch, parent, p->nonce);
    if (!status) memcpy(p->state.pair.staging, p->output.path, sizeof(p->state.pair.staging));
    if (!status) status = a7_output_prepare_mkdir(&p->output, epoch);
    if (!status) status = save(p, A7_PIPE_RESERVE_DIR, 1);
    if (!status) status = a7_output_create_dir(&p->output, epoch, p->job.mkdir);
    if (!status) status = save(p, A7_PIPE_RESERVE_DIR, 0);
    if (!status) status = a7_output_prepare_open(&p->output, epoch);
    if (!status) status = save(p, A7_PIPE_RESERVE_FILE, 1);
    if (!status) status = a7_output_open_temp(&p->output, epoch, &p->job.api);
    if (!status) status = save(p, A7_PIPE_RESERVE_FILE, 0);
    struct a7_pair_job job = {0};
    if (!status) status = a7_pair_take(&p->state.pair, epoch, p->output.path, &job);
    if (!status) status = save(p, A7_PIPE_ENCODE, 1);
    if (!status) status = encode(p, &job);
    if (!status) status = a7_pair_encoded(&p->state.pair, epoch, A7_PAIR_SUCCESS);
    if (!status) status = save(p, A7_PIPE_ENCODE, 0);
    if (!status) status = a7_pair_register(&p->state.pair, epoch, job.media_id, job.media_generation);
    if (!status) status = save(p, A7_PIPE_PUBLISH, 1);
    if (!status) status = p->backend.publish(p->backend.context, &job, p->output.path,
                                            p->output.encoded_bytes, p->state.encoded_digest, &p->state.publication);
    if (!status && (!p->state.publication.owned || !p->state.publication.distinct_dcf_number ||
        p->state.publication.bytes != p->output.encoded_bytes ||
        !memchr(p->state.publication.path, 0, sizeof(p->state.publication.path)))) status = A7_PIPE_INVALID;
    if (!status) status = save(p, A7_PIPE_PUBLISH, 0);
    uint32_t sources[2] = {(uint32_t)job.shots[0].content_id, (uint32_t)job.shots[1].content_id};
    if (!status && (job.shots[0].content_id > UINT32_MAX || job.shots[1].content_id > UINT32_MAX))
        status = A7_PIPE_INVALID;
    if (!status) status = a7_catalog_prepare(&p->catalog, &p->backend.catalog, epoch,
        job.media_generation, job.media_id, sources, p->state.publication.path, p->output.encoded_bytes);
    if (!status) status = a7_catalog_prepare_issue(&p->catalog);
    if (!status) status = save(p, A7_PIPE_ISSUE, 1);
    if (!status) status = a7_catalog_issue(&p->catalog, &p->backend.catalog);
    if (!status) status = save(p, A7_PIPE_ISSUE, 0);
    if (!status) status = a7_catalog_prepare_update(&p->catalog);
    if (!status) status = save(p, A7_PIPE_UPDATE, 1);
    if (!status) status = a7_catalog_update(&p->catalog, &p->backend.catalog);
    if (!status) status = save(p, A7_PIPE_UPDATE, 0);
    if (!status) status = a7_catalog_prepare_flush(&p->catalog);
    if (!status) status = save(p, A7_PIPE_FLUSH, 1);
    if (!status) status = a7_catalog_flush(&p->catalog, &p->backend.catalog);
    if (!status) status = save(p, A7_PIPE_FLUSH, 0);
    if (!status) status = a7_pair_registered(&p->state.pair, epoch, A7_PAIR_SUCCESS,
                                            p->catalog.uid, p->state.publication.path);
    if (!status) status = a7_catalog_verify(&p->catalog, &p->backend.catalog);
    if (!status) status = a7_pair_verified(&p->state.pair, epoch, job.media_id,
        job.media_generation, p->catalog.uid, p->state.publication.path);
    if (!status) status = save(p, A7_PIPE_VERIFY, 0);
    if (status) return p->state.review ? status : stop(p, A7_PIPE_BACKEND, status);
    return release_job(p);
}
int a7_pipeline_work(struct a7_pipeline *p)
{
    if (!p) return A7_PIPE_INVALID;
    lock(p);
    if (p->worker || p->state.review || !p->state.active) { unlock(p); return A7_PIPE_STATE; }
    p->worker = 1; p->state.processing = 1;
    unlock(p);
    int status = 0;
    for (;;) {
        struct a7_pipe_event event;
        lock(p);
        if (p->event_fault) { unlock(p); status = stop(p, A7_PIPE_BACKEND, A7_PAIR_CONFLICT); break; }
        if (p->overflow) { unlock(p); status = stop(p, A7_PIPE_OVERFLOW, 0); break; }
        if (!p->count) { unlock(p); break; }
        event = p->queue[p->head]; p->head = (p->head + 1) % A7_PIPE_QUEUE; --p->count;
        if (p->state.pair.media_id == UINT32_MAX && event.kind == A7_PIPE_BEGIN && event.media != UINT32_MAX)
            p->state.pair.media_id = event.media;
        unlock(p);
        if (event.media != p->state.pair.media_id || event.generation != p->state.pair.media_generation) {
            status = stop(p, A7_PIPE_BACKEND, A7_PAIR_CONFLICT); break;
        }
        if (event.kind == A7_PIPE_BEGIN) status = a7_pair_begin(&p->state.pair, event.epoch, event.capture);
        else {
            int tracked = 0;
            for (unsigned i = 0; i < 2; ++i)
                if (p->state.pair.shots[i].started && p->state.pair.shots[i].capture_id == event.capture) tracked = 1;
            if (!tracked) continue;
            if (!event.path[0] && p->backend.resolve) {
                status = p->backend.resolve(p->backend.context, &event);
                if (status) { status = stop(p, A7_PIPE_BACKEND, status); break; }
            }
            status = a7_pair_saved(&p->state.pair, event.epoch, event.capture, event.media,
                event.generation, event.content, event.path, event.outcome);
        }
        if (status < 0) { status = stop(p, A7_PIPE_BACKEND, status); break; }
        status = save(p, A7_PIPE_EVENT, 0);
        if (status) break;
    }
    if (!status && p->state.pair.phase == A7_PAIR_READY) {
        lock(p); p->accepting = 0; unlock(p);
        status = process(p);
    }
    lock(p); p->worker = 0; p->state.processing = 0; unlock(p);
    return status;
}
int a7_pipeline_query(struct a7_pipeline *p, struct a7_pipe_snapshot *out)
{
    if (!p || !out) return A7_PIPE_INVALID;
    lock(p);
    /* Pair/catalog transitions occur only on the worker. Do not race copying. */
    if (p->worker) { unlock(p); return A7_PIPE_STATE; }
    semantic_state(p); *out = p->state;
    unlock(p); return 0;
}
int a7_pipeline_identity(struct a7_pipeline *p, uint64_t *epoch, uint32_t *media, uint64_t *generation)
{
    if (!p || !epoch || !media || !generation) return A7_PIPE_INVALID;
    lock(p); *epoch = p->state.pair.epoch; *media = p->state.pair.media_id;
    *generation = p->state.pair.media_generation; unlock(p); return 0;
}
int a7_pipeline_disable(struct a7_pipeline *p)
{
    if (!p) return A7_PIPE_INVALID;
    lock(p);
    if (p->worker || !p->state.active || p->state.review) { unlock(p); return A7_PIPE_STATE; }
    p->worker = 1; p->accepting = 0; unlock(p);
    if (p->state.pair.phase == A7_PAIR_COLLECTING || p->state.pair.phase == A7_PAIR_READY ||
        p->state.pair.phase == A7_PAIR_ENCODED)
        a7_pair_cancel(&p->state.pair, p->state.pair.epoch);
    int status = save(p, A7_PIPE_DETACH, 1);
    if (!status && p->state.attached) status = p->backend.detach(p->backend.context);
    if (!status) {
        struct a7_ap_report report;
        p->state.attached = 0;
        status = a7_ap_release(&p->callback, &report);
    }
    if (!status) {
        p->state.active = 0; p->count = 0;
        status = save(p, A7_PIPE_DETACH, 0);
    }
    if (status && !p->state.review) status = stop(p, A7_PIPE_BACKEND, status);
    lock(p); p->worker = 0; unlock(p);
    return status;
}
int a7_pipeline_destroy(struct a7_pipeline *p)
{
    if (!p) return A7_PIPE_INVALID;
    lock(p);
    if (p->worker || p->state.active || p->job.token || p->callback.token) { unlock(p); return A7_PIPE_STATE; }
    unlock(p);
#ifndef _WIN32
    pthread_mutex_destroy(&p->lock);
#endif
    free(p); return 0;
}
