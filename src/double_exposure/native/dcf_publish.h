#ifndef A7C2_DCF_PUBLISH_H
#define A7C2_DCF_PUBLISH_H
#include "pipeline.h"
enum a7_dcf_phase { A7_DCF_EMPTY, A7_DCF_PLANNED, A7_DCF_DIR_INTENT,
    A7_DCF_OWNED, A7_DCF_MOVE_INTENT, A7_DCF_MOVED, A7_DCF_VERIFIED, A7_DCF_REVIEW,
    A7_DCF_CACHE_RESERVED };
struct a7_dcf_state {
    uint32_t phase, directory_owned, close_attempted, handle_owned;
    int32_t native_error, close_error;
    uint64_t bytes, pending_handle;
    char staging[512], directory[512], path[512];
    uint8_t checksum[32];
};
struct a7_dcf_api {
    void *context;
    int32_t (*first)(char *, uint8_t, void *);
    int32_t (*next)(void *);
    int32_t (*mkdir)(char *);
    int32_t (*move)(char *, char *);
    struct a7_mpr_api files;
    int (*save)(void *, const struct a7_dcf_state *);
    void *cache_context;
    int (*reserve)(void *, uint32_t media, uint16_t number, const char *name);
    int (*ready)(void *, uint32_t media, uint16_t number, const char *name);
};
/* Select a FREE NUMERIC folder identity after enumerating all DCIM names.
 * Create one new owned DCF folder, publish A7AV0001.JPG within it, compare
 * source/destination full SHA256 and sizes. Never merely change a prefix.
 * Initial prototype uses one new folder per result; it never modifies camera
 * numbering settings. No retries, deletions, registration or rollback.
 * Every mutating intent is persisted through save before its SDK call.
 * Caller holds an AP job lease through uncertainty/handle reconciliation.
 */
A7_JPEG_API int a7_dcf_publish(struct a7_dcf_state *, const struct a7_dcf_api *,
    const struct a7_pair_job *, const char *, uint64_t, const uint8_t expected[32], struct a7_pipe_publication *);
#endif
