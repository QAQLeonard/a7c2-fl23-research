#ifndef A7C2_MPR_STREAM_H
#define A7C2_MPR_STREAM_H
#include "jpeg_stream.h"

enum a7_mpr_phase { A7_MPR_EMPTY, A7_MPR_READING, A7_MPR_WRITING,
                    A7_MPR_ERROR, A7_MPR_CLOSED, A7_MPR_REVIEW };
enum a7_mpr_error { A7_MPR_INVALID = -10001, A7_MPR_LENGTH = -10002,
                    A7_MPR_STATE = -10003, A7_MPR_CONTRACT = -10004 };
struct a7_mpr_api {
    int32_t (*open)(char *, uint32_t, uint64_t *);
    int32_t (*read)(char, uint64_t, void *, uint32_t);
    int32_t (*write)(char, uint64_t, void *, uint32_t);
    int32_t (*close)(char, uint64_t);
    int32_t (*stat)(char *, uint64_t *);
    int32_t (*flush)(uint64_t);
};
struct a7_mpr_stream {
    struct a7_mpr_api api;
    uint64_t handle, length;
    uint32_t phase, owned, close_attempted;
    int32_t last_error, last_native_result, close_error;
    char path[512];
};

/* Bind to the existing initialized AP's mpr::file::{Open,Read,Write,Close,Stat}
 * exports and Fsys_Flush. Calls are synchronous and must run on a background
 * caller, not the MPR file-task thread or a capture callback. MPR Open flag 1
 * follows the native read-lock path. Keep this context alive through close.
 * No library loading, device discovery, hook or filename reservation occurs.
 */
A7_JPEG_API int a7_mpr_open_reader(struct a7_mpr_stream *, const struct a7_mpr_api *, const char *);
A7_JPEG_API int a7_mpr_attach_writer(struct a7_mpr_stream *, const struct a7_mpr_api *,
                                    const char *owned_path, uint64_t owned_handle);
A7_JPEG_API int a7_mpr_get_input(struct a7_mpr_stream *, struct a7_jpeg_input *);
A7_JPEG_API int a7_mpr_get_output(struct a7_mpr_stream *, struct a7_jpeg_output *);
A7_JPEG_API int a7_mpr_flush_writer(struct a7_mpr_stream *);
A7_JPEG_API int a7_mpr_close(struct a7_mpr_stream *);

/* Writer attachment requires a handle already created/owned by the caller's
 * reserved temporary-output transaction. It never opens/truncates a path.
 * Errors do not publish/delete anything. A close is attempted at most once;
 * failed/partial opens or closes retain their handle/error for review.
 */
#endif
