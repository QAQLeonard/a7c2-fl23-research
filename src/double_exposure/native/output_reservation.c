#include "output_reservation.h"
#include <stdio.h>
#include <string.h>

static int alpha(unsigned char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
static int equal_ci(const char *a, const char *b, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        unsigned char x = a[i], y = b[i];
        if (x >= 'a' && x <= 'z') x -= 'a' - 'A';
        if (y >= 'a' && y <= 'z') y -= 'a' - 'A';
        if (x != y) return 0;
    }
    return 1;
}
static size_t parent_length(const char *path)
{
    if (!path || !alpha(path[0]) || path[1] != ':' || path[2] != '/') return 0;
    size_t n = 3, segment = 3;
    for (; n < 480 && path[n]; ++n) {
        if (path[n] == '\r' || path[n] == '\n' || path[n] == '\\') return 0;
        if (path[n] == '/') {
            size_t length = n - segment;
            if (!length || (length == 1 && path[segment] == '.') ||
                (length == 2 && path[segment] == '.' && path[segment + 1] == '.')) return 0;
            segment = n + 1;
        }
    }
    if (n >= 480 || n < 16 || n - segment != 8 || !equal_ci(path + segment - 6, "/DCIM/", 6)) return 0;
    for (size_t i = 0; i < 8; ++i) {
        unsigned char c = path[segment + i];
        if (i < 3) { if (c < '0' || c > '9' || (!i && c == '0')) return 0; }
        else if (!alpha(c) && !(c >= '0' && c <= '9') && c != '_') return 0;
    }
    return n;
}
static int matches(const struct a7_output_reservation *r, uint64_t epoch)
{ return r && epoch && r->epoch == epoch; }
int a7_output_plan(struct a7_output_reservation *r, uint64_t epoch, const char *parent, uint32_t nonce)
{
    size_t length = parent_length(parent);
    if (!r || !epoch || !length || nonce > 0xffffffu) return A7_OUT_INVALID;
    if (r->phase != A7_OUT_EMPTY) return A7_OUT_STATE;
    char directory[512];
    int size = snprintf(directory, sizeof(directory), "%s/A7%06X", parent, nonce);
    if (size < 0 || (size_t)size + sizeof("/MEAN.TMP") > sizeof(r->path)) return A7_OUT_INVALID;
    memset(r, 0, sizeof(*r)); r->epoch = epoch;
    memcpy(r->directory, directory, (size_t)size + 1);
    if (r->directory[0] >= 'a' && r->directory[0] <= 'z') r->directory[0] -= 'a' - 'A';
    snprintf(r->path, sizeof(r->path), "%s/MEAN.TMP", r->directory);
    r->phase = A7_OUT_PLANNED; return 0;
}
int a7_output_prepare_mkdir(struct a7_output_reservation *r, uint64_t epoch)
{
    if (!matches(r, epoch)) return A7_OUT_STALE;
    if (r->phase != A7_OUT_PLANNED) return A7_OUT_STATE;
    r->phase = A7_OUT_DIR_INTENT; return 0;
}
int a7_output_create_dir(struct a7_output_reservation *r, uint64_t epoch, a7_mkdir_fn mkdir)
{
    if (!matches(r, epoch)) return A7_OUT_STALE;
    if (!mkdir) return A7_OUT_INVALID;
    if (r->phase != A7_OUT_DIR_INTENT) return A7_OUT_STATE;
    r->phase = A7_OUT_DIR_CALL;
    int32_t result = mkdir(r->directory); r->native_error = result;
    if (result) { r->phase = A7_OUT_REVIEW; return A7_OUT_NATIVE; }
    r->directory_owned = 1; r->phase = A7_OUT_DIR_OWNED; return 0;
}
int a7_output_prepare_open(struct a7_output_reservation *r, uint64_t epoch)
{
    if (!matches(r, epoch)) return A7_OUT_STALE;
    if (r->phase != A7_OUT_DIR_OWNED || !r->directory_owned) return A7_OUT_STATE;
    r->phase = A7_OUT_FILE_INTENT; return 0;
}
int a7_output_open_temp(struct a7_output_reservation *r, uint64_t epoch, const struct a7_mpr_api *api)
{
    if (!matches(r, epoch)) return A7_OUT_STALE;
    if (!api || !api->open || !api->write || !api->close || !api->flush) return A7_OUT_INVALID;
    if (r->phase != A7_OUT_FILE_INTENT || !r->directory_owned) return A7_OUT_STATE;
    r->phase = A7_OUT_FILE_CALL;
    int32_t result = api->open(r->path, 6u, &r->pending_handle);
    r->native_error = result;
    if (result) { r->phase = A7_OUT_REVIEW; return A7_OUT_NATIVE; }
    r->file_owned = 1;
    result = a7_mpr_attach_writer(&r->writer, api, r->path, r->pending_handle);
    if (result) { r->native_error = result; r->phase = A7_OUT_REVIEW; return A7_OUT_NATIVE; }
    r->phase = A7_OUT_OPEN; return 0;
}
int a7_output_note_closed(struct a7_output_reservation *r, uint64_t epoch, uint64_t bytes)
{
    if (!matches(r, epoch)) return A7_OUT_STALE;
    if (r->phase != A7_OUT_OPEN || !r->file_owned || !bytes) return A7_OUT_STATE;
    if (r->writer.phase != A7_MPR_CLOSED || r->writer.owned ||
        !r->writer.close_attempted || r->writer.close_error || r->writer.last_error) {
        r->phase = A7_OUT_REVIEW; return A7_OUT_STATE;
    }
    r->encoded_bytes = bytes; r->phase = A7_OUT_CLOSED; return 0;
}
