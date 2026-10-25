#include "mpr_stream.h"
#include <limits.h>
#include <string.h>

static size_t path_length(const char *path)
{
    if (!path || !((path[0] >= 'A' && path[0] <= 'Z') ||
                   (path[0] >= 'a' && path[0] <= 'z')) || path[1] != ':' || path[2] != '/') return 0;
    for (size_t i = 3; i < 512; ++i) {
        if (!path[i]) return i > 3 ? i : 0;
        if (path[i] == '\r' || path[i] == '\n') return 0;
    }
    return 0;
}
static int initialize(struct a7_mpr_stream *s, const struct a7_mpr_api *api, const char *path)
{
    size_t length = path_length(path);
    if (!s || !api || !length || !api->close) return A7_MPR_INVALID;
    if (s->phase != A7_MPR_EMPTY && s->phase != A7_MPR_CLOSED) return A7_MPR_STATE;
    struct a7_mpr_api saved_api = *api;
    char saved_path[512]; memcpy(saved_path, path, length + 1);
    memset(s, 0, sizeof(*s)); s->api = saved_api;
    memcpy(s->path, saved_path, length + 1);
    if (s->path[0] >= 'a' && s->path[0] <= 'z') s->path[0] -= 'a' - 'A';
    return 0;
}
int a7_mpr_close(struct a7_mpr_stream *s)
{
    if (!s || !s->owned || s->close_attempted || !s->api.close) return A7_MPR_STATE;
    s->close_attempted = 1;
    int32_t result = s->api.close(s->path[0], s->handle);
    s->close_error = result;
    if (result) { s->phase = A7_MPR_REVIEW; return result; }
    s->owned = 0; s->phase = A7_MPR_CLOSED; return 0;
}
int a7_mpr_open_reader(struct a7_mpr_stream *s, const struct a7_mpr_api *api, const char *path)
{
    if (!api || !api->open || !api->read || !api->stat) return A7_MPR_INVALID;
    int status = initialize(s, api, path);
    if (status) return status;
    int32_t result = s->api.open(s->path, 1u, &s->handle);
    s->last_native_result = result;
    if (result) {
        s->last_error = result; s->phase = s->handle ? A7_MPR_REVIEW : A7_MPR_ERROR;
        return result;
    }
    s->owned = 1; s->phase = A7_MPR_READING;
    result = s->api.stat(s->path, &s->length);
    s->last_native_result = result;
    if (result || !s->length || s->length > A7_JPEG_MAX_INPUT) {
        int failure = result ? result : A7_MPR_LENGTH;
        s->last_error = failure;
        a7_mpr_close(s);
        return failure;
    }
    return 0;
}
int a7_mpr_attach_writer(struct a7_mpr_stream *s, const struct a7_mpr_api *api,
                         const char *path, uint64_t handle)
{
    if (!api || !api->write || !api->flush) return A7_MPR_INVALID;
    int status = initialize(s, api, path);
    if (status) return status;
    s->handle = handle; s->owned = 1; s->phase = A7_MPR_WRITING;
    return 0;
}
static int64_t read_bytes(void *context, void *buffer, size_t bytes)
{
    struct a7_mpr_stream *s = context;
    if (!s || s->phase != A7_MPR_READING) return A7_MPR_STATE;
    if (!buffer || bytes > INT32_MAX) return A7_MPR_INVALID;
    int32_t result = s->api.read(s->path[0], s->handle, buffer, (uint32_t)bytes);
    s->last_native_result = result;
    if (result < 0 || (uint32_t)result > bytes) {
        s->last_error = result < 0 ? result : A7_MPR_CONTRACT;
        s->phase = A7_MPR_ERROR; return s->last_error;
    }
    return result;
}
static int64_t write_bytes(void *context, const void *buffer, size_t bytes)
{
    struct a7_mpr_stream *s = context;
    if (!s || s->phase != A7_MPR_WRITING) return A7_MPR_STATE;
    if (!buffer || bytes > INT32_MAX) return A7_MPR_INVALID;
    int32_t result = s->api.write(s->path[0], s->handle, (void *)buffer, (uint32_t)bytes);
    s->last_native_result = result;
    if (result <= 0 || (uint32_t)result > bytes) {
        s->last_error = result < 0 ? result : A7_MPR_CONTRACT;
        s->phase = A7_MPR_ERROR;
        return result == 0 ? 0 : s->last_error;
    }
    return result;
}
int a7_mpr_get_input(struct a7_mpr_stream *s, struct a7_jpeg_input *input)
{
    if (!s || !input || s->phase != A7_MPR_READING) return A7_MPR_STATE;
    *input = (struct a7_jpeg_input){s, s->length, read_bytes}; return 0;
}
int a7_mpr_get_output(struct a7_mpr_stream *s, struct a7_jpeg_output *output)
{
    if (!s || !output || s->phase != A7_MPR_WRITING) return A7_MPR_STATE;
    *output = (struct a7_jpeg_output){s, write_bytes}; return 0;
}
int a7_mpr_flush_writer(struct a7_mpr_stream *s)
{
    if (!s || s->phase != A7_MPR_WRITING || !s->api.flush) return A7_MPR_STATE;
    int32_t result = s->api.flush(s->handle);
    s->last_native_result = result;
    if (result) { s->last_error = result; s->phase = A7_MPR_ERROR; }
    return result;
}
