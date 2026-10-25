/* Test-only synthetic MPR backend for the real ARM64 shared library. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "mpr_stream.h"

#define BASE_HANDLE 0x100000000ull
#define NATIVE_ERROR ((int32_t)0x80000010u)
static FILE *files[3];
static const char *paths[2], *mode;
static unsigned reads, writes, closes, flushes, cancel_checks;
static unsigned foreign_codec_calls;
/* A deliberately incompatible pre-existing host codec symbol. The real
 * shared core must bind its own codec and never call this function. */
void *jpeg_std_error(void *pointer)
{
    (void)pointer; ++foreign_codec_calls; return NULL;
}
static int is(const char *name) { return !strcmp(mode, name); }
static unsigned slot(uint64_t handle)
{
    return handle > BASE_HANDLE && handle <= BASE_HANDLE + 3 ? (unsigned)(handle - BASE_HANDLE - 1) : 3;
}
static int32_t open_input(char *path, uint32_t flags, uint64_t *handle)
{
    if (flags != 1) return NATIVE_ERROR;
    unsigned index = !strcmp(path, "A:/first.jpg") ? 0 : !strcmp(path, "A:/second.jpg") ? 1 : 2;
    if (index == 2) return NATIVE_ERROR;
    if (is("partial-open")) { *handle = BASE_HANDLE + 99; return NATIVE_ERROR; }
    files[index] = fopen(paths[index], "rb");
    if (!files[index]) return NATIVE_ERROR;
    *handle = BASE_HANDLE + index + 1; return 0;
}
static int32_t read_input(char drive, uint64_t handle, void *buffer, uint32_t bytes)
{
    ++reads; unsigned index = slot(handle);
    if (drive != 'A' || index >= 2 || !files[index] || is("read-error")) return NATIVE_ERROR;
    if (is("short") && bytes > 7) bytes = 7;
    size_t count = fread(buffer, 1, bytes, files[index]);
    return !count && ferror(files[index]) ? NATIVE_ERROR : (int32_t)count;
}
static int32_t write_output(char drive, uint64_t handle, void *buffer, uint32_t bytes)
{
    ++writes;
    if (drive != 'A' || slot(handle) != 2 || !files[2]) return NATIVE_ERROR;
    if (is("write-error")) {
        if (writes > 1) return NATIVE_ERROR;
        if (bytes > 11) bytes = 11;
    }
    if (is("zero-write")) return 0;
    if (is("short") && bytes > 5) bytes = 5;
    size_t count = fwrite(buffer, 1, bytes, files[2]);
    return !count && ferror(files[2]) ? NATIVE_ERROR : (int32_t)count;
}
static int32_t close_file(char drive, uint64_t handle)
{
    ++closes; unsigned index = slot(handle);
    if (drive != 'A' || index > 2 || !files[index]) return NATIVE_ERROR;
    int result = fclose(files[index]); files[index] = NULL;
    return result || is("close-error") ? NATIVE_ERROR : 0;
}
static int32_t stat_input(char *path, uint64_t *size)
{
    if (is("stat-error")) return NATIVE_ERROR;
    unsigned index = !strcmp(path, "A:/first.jpg") ? 0 : 1;
    if (!files[index]) return NATIVE_ERROR;
    struct stat state;
    if (fstat(fileno(files[index]), &state) || state.st_size < 0) return NATIVE_ERROR;
    *size = (uint64_t)state.st_size; return 0;
}
static int32_t flush_output(uint64_t handle)
{
    ++flushes;
    if (slot(handle) != 2 || !files[2] || is("flush-error")) return NATIVE_ERROR;
    return fflush(files[2]) ? NATIVE_ERROR : 0;
}
static int cancel(void *context)
{
    (void)context; ++cancel_checks;
    return is("cancel") && cancel_checks > 8;
}
int main(int argc, char **argv)
{
    if (argc != 5) return 2;
    paths[0] = argv[1]; paths[1] = argv[2]; mode = argv[4];
    int fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) return 2;
    files[2] = fdopen(fd, "wb");
    if (!files[2]) { close(fd); unlink(argv[3]); return 2; }
    struct a7_mpr_api api = {open_input, read_input, write_output, close_file, stat_input, flush_output};
    struct a7_mpr_stream streams[3] = {0};
    struct a7_jpeg_input a = {0}, b = {0};
    struct a7_jpeg_output output = {0};
    struct a7_jpeg_control control = {NULL, cancel};
    struct a7_jpeg_result result = {0};
    int status = a7_mpr_open_reader(&streams[0], &api, "A:/first.jpg");
    if (!status) status = a7_mpr_open_reader(&streams[1], &api, "A:/second.jpg");
    if (!status) status = a7_mpr_attach_writer(&streams[2], &api, "A:/owned.tmp", BASE_HANDLE + 3);
    if (!status) status = a7_mpr_get_input(&streams[0], &a);
    if (!status) status = a7_mpr_get_input(&streams[1], &b);
    if (!status) status = a7_mpr_get_output(&streams[2], &output);
    if (!status) status = a7_jpeg_mean(&a, &b, &output, &control, &result);
    if (!status) status = a7_mpr_flush_writer(&streams[2]);
    for (unsigned i = 0; i < 3; ++i) {
        if (streams[i].owned && !streams[i].close_attempted) {
            int closed = a7_mpr_close(&streams[i]);
            if (!status && closed) status = closed;
        }
    }
    /* Only test-owned host FILEs are cleaned here. Never a live SDK retry. */
    for (unsigned i = 0; i < 3; ++i) if (files[i]) fclose(files[i]);
    if (status) unlink(argv[3]);
    printf("{\"backend\":\"synthetic-mpr\",\"status\":%d,\"codec\":%d,"
           "\"io_error\":%lld,\"reads\":%u,\"writes\":%u,\"closes\":%u,"
           "\"flushes\":%u,\"bytes\":%llu,\"input0_phase\":%u,\"foreign_codec_calls\":%u}\n",
           status, result.status, (long long)result.io_error, reads, writes, closes,
           flushes, (unsigned long long)result.output_bytes, streams[0].phase, foreign_codec_calls);
    return status ? 1 : 0;
}
