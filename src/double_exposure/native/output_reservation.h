#ifndef A7C2_OUTPUT_RESERVATION_H
#define A7C2_OUTPUT_RESERVATION_H
#include "mpr_stream.h"
typedef int32_t (*a7_mkdir_fn)(char *);
enum a7_output_phase { A7_OUT_EMPTY, A7_OUT_PLANNED, A7_OUT_DIR_INTENT,
    A7_OUT_DIR_CALL, A7_OUT_DIR_OWNED, A7_OUT_FILE_INTENT, A7_OUT_FILE_CALL,
    A7_OUT_OPEN, A7_OUT_CLOSED, A7_OUT_REVIEW };
enum a7_output_error { A7_OUT_INVALID = -12001, A7_OUT_STATE = -12002,
                       A7_OUT_NATIVE = -12003, A7_OUT_STALE = -12004 };
struct a7_output_reservation {
    uint64_t epoch, pending_handle, encoded_bytes;
    uint32_t phase, directory_owned, file_owned;
    int32_t native_error;
    char directory[512], path[512];
    struct a7_mpr_stream writer;
};

/* Zero-initialize and serialize access. Planning and prepare_* are pure;
 * persist their returned intent before invoking the matching SDK step.
 * mkdir must implement the native create-new-directory semantics: an existing
 * directory is an error. Only a successful new private directory establishes
 * ownership of its child MEAN.TMP. Open flag 6 means write|create, NOT exclusive;
 * it is used only inside that new transaction-owned directory.
 * Caller retains the AP job lease while handles/results need reconciliation.
 * No function publishes, registers, deletes files or cleans uncertain state.
 */
A7_JPEG_API int a7_output_plan(struct a7_output_reservation *, uint64_t epoch,
                              const char *dcf_parent, uint32_t nonce);
A7_JPEG_API int a7_output_prepare_mkdir(struct a7_output_reservation *, uint64_t epoch);
A7_JPEG_API int a7_output_create_dir(struct a7_output_reservation *, uint64_t epoch, a7_mkdir_fn);
A7_JPEG_API int a7_output_prepare_open(struct a7_output_reservation *, uint64_t epoch);
A7_JPEG_API int a7_output_open_temp(struct a7_output_reservation *, uint64_t epoch,
                                   const struct a7_mpr_api *);
A7_JPEG_API int a7_output_note_closed(struct a7_output_reservation *, uint64_t epoch,
                                     uint64_t encoded_bytes);
#endif
