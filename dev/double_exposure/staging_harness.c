/* Test-only local protocol runner. Never a device transport or libJit entry. */
#define _GNU_SOURCE
#include "staging.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef A7_STAGE_TESTING
static const char *test_root;
static int armed, writes, failed_fd = -1, failed_sync;
static int fault_is(const char *name)
{ const char *fault = getenv("A7_STAGE_FAULT"); return fault && !strcmp(fault, name); }
ssize_t a7_stage_test_write(int fd, const void *data, size_t bytes)
{
    if (fault_is("short-write")) return write(fd, data, bytes > 7 ? 7 : bytes);
    if (armed && fault_is("write-prefix-error")) {
        if (writes++) { errno = EIO; return -1; }
        return write(fd, data, bytes > 7 ? 7 : bytes);
    }
    if (armed && fault_is("write-zero")) return 0;
    return write(fd, data, bytes);
}
ssize_t a7_stage_test_read(int fd, void *data, size_t bytes)
{
    if (armed && fault_is("read-error")) { errno = EIO; return -1; }
    return read(fd, data, bytes);
}
int a7_stage_test_fsync(int fd)
{
    int result = fsync(fd);
    if (armed && fault_is("fsync-error")) {
        if (failed_sync++) _exit(75); /* a failed flush must not be replayed */
        errno = EIO; return -1;
    }
    return result;
}
int a7_stage_test_close(int fd)
{
    if (fd == failed_fd) _exit(75); /* even an uncertain close is attempted once */
    int result = close(fd);
    if (armed && fault_is("close-error") && failed_fd < 0) {
        failed_fd = fd; errno = EIO; return -1;
    }
    return result;
}
void a7_stage_test_step(const char *name)
{
    const char *fault = getenv("A7_STAGE_FAULT");
    if (!strcmp(name, "chunk-intent") && !fault_is("read-error")) armed = 1;
    if (!strcmp(name, "chunk-data") && fault_is("read-error")) armed = 1;
    if (fault && !strcmp(fault, "collision") && !strcmp(name, "assembly-data")) {
        char path[4096];
        if (snprintf(path, sizeof(path), "%s/core.so", test_root) >= (int)sizeof(path)) _exit(74);
        FILE *stream = fopen(path, "wx");
        if (!stream || fputs("user output", stream) < 0 || fclose(stream)) _exit(74);
    }
    if (fault && !strcmp(name, fault)) _exit(73);
}
#endif
static size_t load(const char *path, unsigned char *data, size_t capacity)
{
    FILE *stream = fopen(path, "rb");
    if (!stream) { perror("fixture input"); exit(2); }
    size_t bytes = fread(data, 1, capacity, stream);
    if (ferror(stream) || fgetc(stream) != EOF) { fprintf(stderr, "fixture exceeds limit\n"); exit(2); }
    if (fclose(stream)) exit(2);
    return bytes;
}
int main(int argc, char **argv)
{
    if (argc != 3 && argc != 4) return 2;
#ifdef A7_STAGE_TESTING
    test_root = argv[1];
#endif
    unsigned char wire[A7_STAGE_MAX_WIRE + 1], payload[A7_STAGE_CHUNK + 1];
    size_t length = load(argv[2], wire, sizeof(wire));
    size_t bytes = argc == 4 ? load(argv[3], payload, sizeof(payload)) : 0;
    struct a7_stage_report report;
    int result = a7_stage_execute(argv[1], wire, length, bytes ? payload : NULL, bytes, &report);
    if (result != report.status || report.abi != 1) return 3;
    printf("{\"status\":%d,\"phase\":%u,\"completed\":%u,\"chunks\":%u,"
           "\"mutated\":%u,\"published\":%u,\"locked\":%u,\"io_error\":%d,"
           "\"close_error\":%d,\"written_bytes\":%llu,\"verified_bytes\":%llu,\"camera_io\":false}\n",
           result, report.phase, report.completed, report.chunks, report.mutated,
           report.published, report.locked, report.io_error, report.close_error,
           (unsigned long long)report.written_bytes, (unsigned long long)report.verified_bytes);
    return 0;
}
