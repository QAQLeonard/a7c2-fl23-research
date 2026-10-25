#include "dcf_publish.h"
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#include "../../fl23/native/sha256.h"
static int fail(struct a7_dcf_state *s, int error)
{ s->phase = A7_DCF_REVIEW; s->native_error = error; return error ? error : A7_PIPE_BACKEND; }
static int save(struct a7_dcf_state *s, const struct a7_dcf_api *a, unsigned phase)
{
    s->phase = phase;
    int status = a->save(a->context, s);
    return status ? fail(s, status) : 0;
}
static int checksum(struct a7_dcf_state *s, const struct a7_dcf_api *a,
                    const char *path, uint8_t result[32])
{
    char name[512]; snprintf(name, sizeof(name), "%s", path);
    uint64_t size = 0;
    int status = a->files.stat(name, &size);
    if (status || size != s->bytes) return fail(s, status);
    s->pending_handle = 0; s->close_attempted = 0; s->handle_owned = 0;
    status = a->files.open(name, 1, &s->pending_handle);
    if (status) return fail(s, status);
    s->handle_owned = 1;
    SHA256 sha; sha_init(&sha);
    uint8_t buffer[8192]; uint64_t done = 0;
    while (!status && done < size) {
        uint32_t bytes = size - done > sizeof(buffer) ? sizeof(buffer) : (uint32_t)(size - done);
        int32_t count = a->files.read(name[0], s->pending_handle, buffer, bytes);
        if (count <= 0 || (uint32_t)count > bytes) status = count < 0 ? count : A7_PIPE_BACKEND;
        else { sha_add(&sha, buffer, (uint32_t)count); done += (uint32_t)count; }
    }
    if (!status) {
        int32_t count = a->files.read(name[0], s->pending_handle, buffer, 1);
        if (count) status = count < 0 ? count : A7_PIPE_BACKEND;
    }
    s->close_attempted = 1;
    int closing = a->files.close(name[0], s->pending_handle);
    if (closing) { s->close_error = closing; return fail(s, closing); }
    s->handle_owned = 0;
    if (status) return fail(s, status);
    sha_end(&sha, result); return 0;
}
int a7_dcf_publish(struct a7_dcf_state *s, const struct a7_dcf_api *a,
    const struct a7_pair_job *job, const char *staging, uint64_t bytes, const uint8_t expected[32], struct a7_pipe_publication *out)
{
    if (!s || !a || !a->first || !a->next || !a->mkdir || !a->move || !a->save ||
        !a->files.stat || !a->files.open || !a->files.read || !a->files.close ||
        !job || !staging || !expected || !out || !bytes || bytes > 256ull * 1024 * 1024 || s->phase != A7_DCF_EMPTY)
        return A7_PIPE_INVALID;
    if (!memchr(job->shots[0].path, 0, 512) || !memchr(staging, 0, 512)) return A7_PIPE_INVALID;
    char root[512]; snprintf(root, sizeof(root), "%s", job->shots[0].path);
    char *file = strrchr(root, '/');
    if (!file || file - root < 14 || memcmp(file - 14, "/DCIM/", 6)) return A7_PIPE_INVALID;
    unsigned source_number = 0;
    for (unsigned i = 0; i < 3; ++i) {
        char c = file[-8 + (int)i];
        if (c < '0' || c > '9') return A7_PIPE_INVALID;
        source_number = source_number * 10 + (unsigned)(c - '0');
    }
    file[-9] = 0; /* retain native drive/load prefix and /DCIM */
    char search[512];
    if (snprintf(search, sizeof(search), "%s/*", root) >= (int)sizeof(search)) return A7_PIPE_INVALID;
    uint64_t find[0xc28 / 8] = {0}; /* exact 2.01 FSYSFINDINFO storage */
    uint8_t used[1000] = {0};
    int status = a->first(search, 0x80, find);
    unsigned entries = 0;
    while (!status) {
        const char *name = (const char *)(uintptr_t)find[0];
        if (!name || ++entries > 16384) return fail(s, A7_PIPE_BACKEND);
        size_t length = 0;
        while (length < 262 && name[length]) ++length;
        if (length == 262) return fail(s, A7_PIPE_BACKEND);
        if (length >= 3 && name[0] >= '1' && name[0] <= '9' &&
            name[1] >= '0' && name[1] <= '9' && name[2] >= '0' && name[2] <= '9')
            used[(name[0] - '0') * 100 + (name[1] - '0') * 10 + name[2] - '0'] = 1;
        status = a->next(find);
    }
    if (status != 2 || source_number < 100 || !used[source_number]) return fail(s, status);
    unsigned number = source_number + 1;
    while (number < 1000 && used[number]) ++number;
    if (number == 1000) { for (number = 100; number < 1000 && used[number]; ++number) {} }
    if (number == 1000) return fail(s, A7_PIPE_BACKEND);
    s->bytes = bytes; snprintf(s->staging, sizeof(s->staging), "%s", staging);
    if (snprintf(s->directory, sizeof(s->directory), "%s/%03uA7AVG", root, number) >= (int)sizeof(s->directory) ||
        snprintf(s->path, sizeof(s->path), "%s/A7AV0001.JPG", s->directory) >= (int)sizeof(s->path))
        return A7_PIPE_INVALID;
    status = checksum(s, a, staging, s->checksum);
    if (!status && memcmp(s->checksum, expected, 32)) status = A7_PIPE_BACKEND;
    if (!status) status = save(s, a, A7_DCF_DIR_INTENT);
    const char *folder_name = strrchr(s->directory, '/') + 1;
    if (!status && a->reserve) status = a->reserve(a->cache_context, job->media_id, (uint16_t)number, folder_name);
    if (!status && a->reserve) status = save(s, a, A7_DCF_CACHE_RESERVED);
    if (!status) status = a->mkdir(s->directory);
    if (status) return fail(s, status);
    s->directory_owned = 1;
    if ((status = save(s, a, A7_DCF_OWNED))) return status;
    /* Re-enumerate after creation: no physical directory with the same numeric
     * DCF identity may coexist, even under a different five-character suffix. */
    unsigned matches = 0, own = 0; entries = 0;
    memset(find, 0, sizeof(find)); status = a->first(search, 0x80, find);
    while (!status) {
        const char *name = (const char *)(uintptr_t)find[0];
        if (!name || ++entries > 16384) return fail(s, A7_PIPE_BACKEND);
        size_t length = 0; while (length < 262 && name[length]) ++length;
        if (length == 262) return fail(s, A7_PIPE_BACKEND);
        if (length >= 3 && name[0] >= '1' && name[0] <= '9' && name[1] >= '0' && name[1] <= '9' && name[2] >= '0' && name[2] <= '9') {
            unsigned value = (unsigned)(name[0] - '0') * 100 + (unsigned)(name[1] - '0') * 10 + (unsigned)(name[2] - '0');
            if (value == number) { ++matches; if (!strcmp(name, folder_name)) ++own; }
        }
        status = a->next(find);
    }
    if (status != 2 || matches != 1 || own != 1) return fail(s, A7_PIPE_BACKEND);
    if (a->ready && (status = a->ready(a->cache_context, job->media_id, (uint16_t)number, folder_name))) return fail(s, status);
    if ((status = save(s, a, A7_DCF_MOVE_INTENT))) return status;
    status = a->move(s->staging, s->path);
    if (status) return fail(s, status);
    if ((status = save(s, a, A7_DCF_MOVED))) return status;
    uint8_t actual[32];
    if ((status = checksum(s, a, s->path, actual))) return status;
    if (memcmp(actual, s->checksum, sizeof(actual))) return fail(s, A7_PIPE_BACKEND);
    if ((status = save(s, a, A7_DCF_VERIFIED))) return status;
    memset(out, 0, sizeof(*out)); out->bytes = bytes;
    out->owned = 1; out->distinct_dcf_number = 1; snprintf(out->path, sizeof(out->path), "%s", s->path);
    return 0;
}
