#ifndef A7C2_STAGING_H
#define A7C2_STAGING_H
#include "jpeg_stream.h"

#define A7_STAGE_ABI 1u
#define A7_STAGE_HEADER 80u
#define A7_STAGE_CHUNK (48u * 1024u)
#define A7_STAGE_MAX_BYTES (8u * 1024u * 1024u)
#define A7_STAGE_MAX_CHUNKS ((A7_STAGE_MAX_BYTES + A7_STAGE_CHUNK - 1) / A7_STAGE_CHUNK)
#define A7_STAGE_MAX_WIRE (A7_STAGE_HEADER + 32u * A7_STAGE_MAX_CHUNKS)
enum a7_stage_operation { A7_STAGE_CREATE = 1, A7_STAGE_PUT, A7_STAGE_ASSEMBLE, A7_STAGE_QUERY };
enum a7_stage_phase { A7_STAGE_EMPTY, A7_STAGE_RECEIVING, A7_STAGE_READY, A7_STAGE_REVIEW };
enum a7_stage_error {
    A7_STAGE_INVALID = -13001, A7_STAGE_EXISTS = -13002, A7_STAGE_IO = -13003,
    A7_STAGE_IDENTITY = -13004, A7_STAGE_ORDER = -13005, A7_STAGE_DIGEST = -13006,
    A7_STAGE_UNCERTAIN = -13007, A7_STAGE_BUSY = -13008
};
struct a7_stage_report {
    uint32_t abi, operation, phase, completed, chunks, mutated, published, locked;
    int32_t status, io_error, close_error, pending_fd;
    uint64_t written_bytes, verified_bytes;
    uint8_t transaction[16], sha256[32];
};

/* Linux POSIX staging, explicit calls only. No SDK, USB, loading or cleanup.
 * Caller supplies a trusted absolute path under a private staging parent.
 * CREATE owns a newly-created directory; existing paths never imply ownership.
 * Requests are little-endian bytes, not C structs:
 *   0 magic[8]="A7STG001", 8 operation:u32, 12 chunk_index:u32,
 *   16 transaction[16] (nonzero), 32 size:u64, 40 chunk_count:u32,
 *   44 reserved:u32=0, 48 whole_sha256[32].
 * CREATE appends exactly chunk_count SHA256 values. Other requests are 80 bytes.
 * Only PUT has a payload, exactly the planned chunk size, at most 48 KiB.
 * Non-PUT index is zero. Plan/transaction stay immutable across all requests.
 * Hashes detect transfer corruption, not authorship. READY is verified bytes.
 *
 * An exclusive nonblocking directory flock serializes cooperating callers.
 * File I/O uses descriptor-relative, no-follow, create-exclusive operations.
 * Completed chunks require exact intent + data + confirmation files. An
 * unfinished intent, malformed journal or foreign file stops without replay.
 * Only QUERY can reconcile a lost acknowledgement; PUT is never idempotent.
 * No directory, chunk or evidence is deleted. Successful local publication
 * removes only this operation's assembly temporary link. Camera filesystem,
 * directory fsync and power-loss semantics require separate validation.
 */
A7_JPEG_API int a7_stage_execute(const char *root, const void *wire, size_t wire_length,
                               const void *payload, size_t payload_length,
                               struct a7_stage_report *);
#endif
