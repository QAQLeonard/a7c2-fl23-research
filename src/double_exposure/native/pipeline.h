#ifndef A7C2_PIPELINE_H
#define A7C2_PIPELINE_H
#include "capture_pair.h"
#include "ap_runtime.h"
#include "media_catalog.h"

#define A7_PIPE_ABI 1u
#define A7_PIPE_QUEUE 16u
enum a7_pipe_event_kind { A7_PIPE_BEGIN = 1, A7_PIPE_SAVED, A7_PIPE_EVENT_FAULT };
enum a7_pipe_step { A7_PIPE_ARM = 1, A7_PIPE_EVENT, A7_PIPE_RESERVE_DIR,
    A7_PIPE_RESERVE_FILE, A7_PIPE_ENCODE, A7_PIPE_PUBLISH, A7_PIPE_ISSUE,
    A7_PIPE_UPDATE, A7_PIPE_VERIFY, A7_PIPE_DETACH, A7_PIPE_CHECKPOINT, A7_PIPE_FLUSH };
enum a7_pipe_error { A7_PIPE_INVALID = -15001, A7_PIPE_STATE = -15002,
    A7_PIPE_JOURNAL = -15003, A7_PIPE_BACKEND = -15004, A7_PIPE_OVERFLOW = -15005 };
struct a7_pipe_event {
    uint64_t epoch, capture, generation, content;
    uint32_t kind, media, outcome, reserved;
    char path[512];
};
struct a7_pipe_publication {
    uint64_t bytes;
    uint32_t owned, distinct_dcf_number;
    char path[512];
};
struct a7_pipe_snapshot {
    uint32_t abi, step, intent, active, review, queued, processing, attached;
    int32_t status, backend_error;
    uint64_t sequence;
    struct a7_pair_session pair;
    uint32_t output_phase, catalog_phase;
    uint64_t pending_handle, output_bytes;
    struct a7_pipe_publication publication;
    uint32_t catalog_uid, catalog_uid_valid;
    int32_t catalog_error, output_error;
    uint64_t input_handles[2];
    uint32_t input_phases[2];
    uint8_t encoded_digest[32];
};
typedef void (*a7_pipe_sink)(void *, const struct a7_pipe_event *);
struct a7_pipe_backend {
    void *context;
    /* save must durably preserve the semantic snapshot before returning 0. */
    int (*save)(void *, const struct a7_pipe_snapshot *);
    /* Adapter preserves/forwards the original native delegate. Successful
     * detach MUST include actual native rundown, not only pointer removal. */
    int (*attach)(void *, a7_pipe_sink, void *);
    int (*detach)(void *);
    /* Runs on worker caller after output flush/close. Must reserve a distinct
     * native DCF numeric identity, publish without overwrite and verify file
     * contents/size. Unknown outcome returns error, retains all evidence. */
    int (*publish)(void *, const struct a7_pair_job *, const char *, uint64_t,
                   const uint8_t expected[32], struct a7_pipe_publication *);
    /* Optional worker-side UID -> completed JPEG resolver; never callback I/O. */
    int (*resolve)(void *, struct a7_pipe_event *);
    struct a7_catalog_api catalog;
};
struct a7_pipeline;
/* Process-local object, AP runtime must already be BOUND. All file/SDK work
 * runs only in work(), called by a background worker. Sink only copies events.
 * Backend attach/detach/publish must be validated native adapters; supplying
 * synthetic ones proves offline flow only. No implicit fallback implementation.
 * destroy succeeds only after disable/rundown and release of all job leases.
 * No pointer-bearing object/lease is persisted; save receives semantic data.
 */
A7_JPEG_API struct a7_pipeline *a7_pipeline_create(const struct a7_pipe_backend *);
A7_JPEG_API int a7_pipeline_arm(struct a7_pipeline *, uint64_t epoch,
    uint32_t media, uint64_t generation, uint32_t nonce);
A7_JPEG_API void a7_pipeline_notify(void *, const struct a7_pipe_event *);
A7_JPEG_API int a7_pipeline_work(struct a7_pipeline *);
A7_JPEG_API int a7_pipeline_query(struct a7_pipeline *, struct a7_pipe_snapshot *);
A7_JPEG_API int a7_pipeline_identity(struct a7_pipeline *, uint64_t *, uint32_t *, uint64_t *);
A7_JPEG_API int a7_pipeline_disable(struct a7_pipeline *);
A7_JPEG_API int a7_pipeline_destroy(struct a7_pipeline *);
#endif
