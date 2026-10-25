#ifndef A7C2_CAPTURE_PAIR_H
#define A7C2_CAPTURE_PAIR_H
#include <stddef.h>
#include <stdint.h>

#define A7_PAIR_PATH_BYTES 512
#define A7_PAIR_NO_CONTENT UINT64_MAX
enum a7_pair_phase {
    A7_PAIR_IDLE, A7_PAIR_COLLECTING, A7_PAIR_READY, A7_PAIR_PROCESSING,
    A7_PAIR_ENCODED, A7_PAIR_REGISTERING, A7_PAIR_VERIFYING, A7_PAIR_COMPLETE,
    A7_PAIR_FAILED, A7_PAIR_REVIEW, A7_PAIR_CANCELLING, A7_PAIR_CANCELLED
};
enum a7_pair_status { A7_PAIR_OK, A7_PAIR_IGNORED, A7_PAIR_INVALID = -1,
                      A7_PAIR_BUSY = -2, A7_PAIR_CONFLICT = -3 };
enum a7_pair_outcome { A7_PAIR_SUCCESS, A7_PAIR_NO_CHANGE, A7_PAIR_UNKNOWN };
struct a7_pair_shot {
    uint64_t capture_id, content_id;
    uint32_t started, complete;
    char path[A7_PAIR_PATH_BYTES];
};
struct a7_pair_job {
    uint64_t epoch, media_generation;
    uint32_t media_id, reserved;
    struct a7_pair_shot shots[2];
    char staging[A7_PAIR_PATH_BYTES];
};
struct a7_pair_session {
    uint32_t phase, media_id;
    uint64_t media_generation, epoch;
    struct a7_pair_shot shots[2];
    char staging[A7_PAIR_PATH_BYTES], result[A7_PAIR_PATH_BYTES];
    uint64_t result_id;
};
struct a7_pair_capture_identity {
    uint32_t media_id, content_id;
    uint16_t directory_number, file_number;
};

/* Decode the 2.01 AP wrapper's 56-byte capture result for one media ID.
 * This is a reservation identity, not evidence that image writing finished.
 * The firmware adapter still has to resolve the JPEG and await completion.
 */
int a7_pair_decode_capture_result(const uint8_t *, size_t, uint32_t media,
                                 struct a7_pair_capture_identity *);

/* Caller zero-initializes the session, serializes calls, and owns persistence.
 * Epochs increase at each explicit arm. The firmware adapter must correlate
 * capture-start with a resolved, completed JPEG and supply media generations;
 * a file appearing or a successful submit is not a completed capture/save.
 * Source/catalog/staging paths may be native Fsys drive paths or POSIX paths.
 * The executing adapter must establish output ownership; the proposed path
 * alone is not a reservation. Fsys paths require the MPR stream adapter;
 * the standalone Linux JPEG executable cannot directly open them.
 * Call registered() only after the media writer has finished, and verified()
 * only after independently querying the resulting catalog entry. Output jobs
 * and input strings must not overlap session storage or each other.
 * No function performs I/O, calls firmware or runs image processing.
 */
size_t a7_pair_session_size(void);
int a7_pair_arm(struct a7_pair_session *, uint64_t epoch, uint32_t media, uint64_t generation);
int a7_pair_begin(struct a7_pair_session *, uint64_t epoch, uint64_t capture);
int a7_pair_saved(struct a7_pair_session *, uint64_t epoch, uint64_t capture,
                  uint32_t media, uint64_t generation, uint64_t content,
                  const char *path, uint32_t outcome);
int a7_pair_take(struct a7_pair_session *, uint64_t epoch, const char *staging,
                 struct a7_pair_job *);
int a7_pair_encoded(struct a7_pair_session *, uint64_t epoch, uint32_t outcome);
int a7_pair_register(struct a7_pair_session *, uint64_t epoch,
                     uint32_t media, uint64_t generation);
int a7_pair_registered(struct a7_pair_session *, uint64_t epoch, uint32_t outcome,
                       uint64_t content, const char *path);
int a7_pair_verified(struct a7_pair_session *, uint64_t epoch, uint32_t media,
                     uint64_t generation, uint64_t content, const char *path);
int a7_pair_cancel(struct a7_pair_session *, uint64_t epoch);
#endif
