#ifndef A7C2_MEDIA_CATALOG_H
#define A7C2_MEDIA_CATALOG_H
#include "mpr_stream.h"

#define A7_SIDB_RECORD_BYTES 0x620u
struct a7_sidb_record { uint64_t words[A7_SIDB_RECORD_BYTES / 8]; };
struct a7_catalog_api {
    void (*clear)(void *);
    int32_t (*select)(uint32_t, uint32_t, void *, uint8_t);
    int32_t (*issue)(uint32_t, uint32_t *, uint8_t);
    int32_t (*update)(uint32_t, const void *, uint8_t, uint8_t);
    int32_t (*media)(uint32_t, uint32_t *);
    int32_t (*flush)(uint32_t);
};
enum a7_catalog_phase {
    A7_CAT_EMPTY, A7_CAT_PREPARED, A7_CAT_ISSUE_INTENT, A7_CAT_ISSUED,
    A7_CAT_UPDATE_INTENT, A7_CAT_UPDATED, A7_CAT_VERIFIED, A7_CAT_REVIEW,
    A7_CAT_FLUSH_INTENT, A7_CAT_FLUSHED
};
enum a7_catalog_error { A7_CAT_INVALID = -14001, A7_CAT_STATE = -14002,
    A7_CAT_NATIVE = -14003, A7_CAT_MISMATCH = -14004 };
struct a7_catalog {
    uint64_t epoch, generation, bytes;
    uint32_t media_id, phase, uid, uid_valid, source[2];
    int32_t native_error;
    char path[262];
    struct a7_sidb_record source_record, proposed, confirmed;
};
/* 2.01 SIDB ABI, using existing native clear/Select/IssueUniqueId/Update and
 * GetMediaIdFromUniqueId exports. No fabricated C++ string/map objects.
 * Call prepare only after a closed, published, independently owned JPEG exists
 * at a numerically distinct DCF destination. The caller owns DCF allocation,
 * file verification, serialization, native module leases and persistence.
 * Persist each prepare_* intent before its mutating SDK call. An SDK error
 * can have side effects and enters REVIEW; never replay issue/update.
 * Verification uses a fresh native Select, not the submitted record buffer.
 */
A7_JPEG_API int a7_catalog_prepare(struct a7_catalog *, const struct a7_catalog_api *,
    uint64_t epoch, uint64_t generation, uint32_t media, const uint32_t source[2],
    const char *owned_path, uint64_t bytes);
A7_JPEG_API int a7_catalog_prepare_issue(struct a7_catalog *);
A7_JPEG_API int a7_catalog_issue(struct a7_catalog *, const struct a7_catalog_api *);
A7_JPEG_API int a7_catalog_prepare_update(struct a7_catalog *);
A7_JPEG_API int a7_catalog_update(struct a7_catalog *, const struct a7_catalog_api *);
A7_JPEG_API int a7_catalog_verify(struct a7_catalog *, const struct a7_catalog_api *);
A7_JPEG_API int a7_catalog_prepare_flush(struct a7_catalog *);
A7_JPEG_API int a7_catalog_flush(struct a7_catalog *, const struct a7_catalog_api *);
#endif
