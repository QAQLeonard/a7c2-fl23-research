#include "media_catalog.h"
#include <string.h>
static uint8_t *record(struct a7_sidb_record *r) { return (uint8_t *)r; }
static uint32_t get32(const void *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static void put32(void *p, uint32_t v) { memcpy(p, &v, 4); }
static int review(struct a7_catalog *c, int code, int native)
{ c->phase = A7_CAT_REVIEW; c->native_error = native; return code; }
static int path_length(const char *p)
{
    if (!p || p[0] < 'A' || p[0] > 'Z' || p[1] != ':' || p[2] != '/') return 0;
    size_t n = 3;
    while (n < 262 && p[n]) { if ((unsigned char)p[n] < 32 || p[n] == '\\') return 0; ++n; }
    if (n >= 262 || n < 29 || memcmp(p + n - 4, ".JPG", 4)) return 0;
    const char *file = strrchr(p, '/');
    if (!file || strlen(file + 1) != 12 || file - p < 14 || memcmp(file - 14, "/DCIM/", 6)) return 0;
    for (unsigned i = 0; i < 8; ++i) {
        char c = file[-8 + (int)i];
        if (i < 3 ? (c < '0' || c > '9' || (!i && c == '0')) :
            !((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return 0;
    }
    for (unsigned i = 1; i <= 8; ++i) {
        char c = file[i];
        if (i <= 4 ? !((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_') :
            (c < '0' || c > '9')) return 0;
    }
    return (int)n;
}
static int same_ci(const char *a, const char *b)
{
    for (size_t i = 0; i < 262; ++i) {
        unsigned x = (unsigned char)a[i], y = (unsigned char)b[i];
        if (x >= 'a' && x <= 'z') x -= 32;
        if (y >= 'a' && y <= 'z') y -= 32;
        if (x != y) return 0;
        if (!x) return 1;
    }
    return 0;
}
static int valid_api(const struct a7_catalog_api *a)
{ return a && a->clear && a->select && a->issue && a->update && a->media && a->flush; }
static int select_source(struct a7_catalog *c, const struct a7_catalog_api *a,
                         unsigned index, struct a7_sidb_record *r)
{
    uint32_t media = UINT32_MAX;
    int status = a->media(c->source[index], &media);
    if (status) return review(c, A7_CAT_NATIVE, status);
    if (media != c->media_id) return review(c, A7_CAT_MISMATCH, 0);
    memset(r, 0, sizeof(*r)); a->clear(r);
    status = a->select(UINT32_MAX, c->source[index], r, 0);
    if (status) return review(c, A7_CAT_NATIVE, status);
    uint8_t *raw = record(r);
    if (get32(raw + 4) != c->source[index] || !raw[0xc0] ||
        !memchr(raw + 0xc1, 0, 262) || same_ci((char *)raw + 0xc1, c->path))
        return review(c, A7_CAT_MISMATCH, 0);
    return 0;
}
int a7_catalog_prepare(struct a7_catalog *c, const struct a7_catalog_api *a,
    uint64_t epoch, uint64_t generation, uint32_t media, const uint32_t source[2],
    const char *path, uint64_t bytes)
{
    int n = path_length(path);
    if (!c || !valid_api(a) || !epoch || !generation || !source || source[0] == source[1] ||
        !n || !bytes || bytes > 256ull * 1024 * 1024) return A7_CAT_INVALID;
    if (c->phase != A7_CAT_EMPTY) return A7_CAT_STATE;
    c->epoch = epoch; c->generation = generation; c->media_id = media; c->bytes = bytes;
    c->source[0] = source[0]; c->source[1] = source[1]; memcpy(c->path, path, (size_t)n + 1);
    int status = select_source(c, a, 0, &c->source_record);
    if (!status) status = select_source(c, a, 1, &c->confirmed);
    if (status) return status;
    /* Match the minimal JPEG record populated by 2.01's native DCF importer.
     * The timestamp consists of its native 8+4 bytes, copied without casting. */
    memset(&c->proposed, 0, sizeof(c->proposed)); a->clear(&c->proposed);
    uint8_t *raw = record(&c->proposed), *origin = record(&c->source_record);
    put32(raw, 1); put32(raw + 8, 0);
    memcpy(raw + 0xc, origin + 0xc, 12);
    raw[0x1c] = 1; put32(raw + 0x20, 0); raw[0x24] = 0; /* newly-created writable result */
    raw[0xc0] = 1; memcpy(raw + 0xc1, path, (size_t)n + 1);
    put32(raw + 0x4e8, (uint32_t)bytes);
    raw[0x619] = 0; raw[0x61a] = 1; raw[0x61c] = 0;
    c->phase = A7_CAT_PREPARED; return 0;
}
int a7_catalog_prepare_issue(struct a7_catalog *c)
{
    if (!c || c->phase != A7_CAT_PREPARED) return A7_CAT_STATE;
    c->phase = A7_CAT_ISSUE_INTENT; return 0;
}
int a7_catalog_issue(struct a7_catalog *c, const struct a7_catalog_api *a)
{
    if (!c || !valid_api(a) || c->phase != A7_CAT_ISSUE_INTENT) return A7_CAT_STATE;
    c->phase = A7_CAT_REVIEW;
    int status = a->issue(c->media_id, &c->uid, 0);
    if (status) return review(c, A7_CAT_NATIVE, status);
    c->uid_valid = 1;
    uint32_t media = UINT32_MAX;
    status = a->media(c->uid, &media);
    if (status) return review(c, A7_CAT_NATIVE, status);
    if (media != c->media_id || c->uid == c->source[0] || c->uid == c->source[1])
        return review(c, A7_CAT_MISMATCH, 0);
    put32(record(&c->proposed) + 4, c->uid);
    c->phase = A7_CAT_ISSUED; return 0;
}
int a7_catalog_prepare_update(struct a7_catalog *c)
{
    if (!c || c->phase != A7_CAT_ISSUED || !c->uid_valid) return A7_CAT_STATE;
    c->phase = A7_CAT_UPDATE_INTENT; return 0;
}
int a7_catalog_update(struct a7_catalog *c, const struct a7_catalog_api *a)
{
    if (!c || !valid_api(a) || c->phase != A7_CAT_UPDATE_INTENT) return A7_CAT_STATE;
    c->phase = A7_CAT_REVIEW;
    int status = a->update(UINT32_MAX, &c->proposed, 0, 0);
    if (status) return review(c, A7_CAT_NATIVE, status);
    c->phase = A7_CAT_UPDATED; return 0;
}
int a7_catalog_verify(struct a7_catalog *c, const struct a7_catalog_api *a)
{
    if (!c || !valid_api(a) || c->phase != A7_CAT_FLUSHED) return A7_CAT_STATE;
    memset(&c->confirmed, 0, sizeof(c->confirmed)); a->clear(&c->confirmed);
    int status = a->select(UINT32_MAX, c->uid, &c->confirmed, 0);
    if (status) return review(c, A7_CAT_NATIVE, status);
    uint8_t *raw = record(&c->confirmed);
    if (get32(raw) != 1 || get32(raw + 4) != c->uid || !raw[0xc0] ||
        !memchr(raw + 0xc1, 0, 262) || !same_ci((char *)raw + 0xc1, c->path) ||
        get32(raw + 0x4e8) != c->bytes || memcmp(raw + 0xc, record(&c->proposed) + 0xc, 12))
        return review(c, A7_CAT_MISMATCH, 0);
    c->phase = A7_CAT_VERIFIED; return 0;
}
int a7_catalog_prepare_flush(struct a7_catalog *c)
{
    if (!c || c->phase != A7_CAT_UPDATED) return A7_CAT_STATE;
    c->phase = A7_CAT_FLUSH_INTENT; return 0;
}
int a7_catalog_flush(struct a7_catalog *c, const struct a7_catalog_api *a)
{
    if (!c || !valid_api(a) || c->phase != A7_CAT_FLUSH_INTENT) return A7_CAT_STATE;
    c->phase = A7_CAT_REVIEW;
    int status = a->flush(c->media_id);
    if (status) return review(c, A7_CAT_NATIVE, status);
    c->phase = A7_CAT_FLUSHED; return 0;
}
