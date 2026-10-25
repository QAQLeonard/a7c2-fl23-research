/* Camera-side two-JPEG mean processor.  No firmware addresses or USB access.
 * This software is based in part on the work of the Independent JPEG Group.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <setjmp.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <process.h>
#include <windows.h>
#define close _close
#define unlink _unlink
#define fdopen _fdopen
#define fileno _fileno
#define fsync _commit
#define getpid _getpid
#ifndef S_ISREG
#define S_ISREG(m) (((m) & S_IFMT) == S_IFREG)
#endif
#else
#include <unistd.h>
#include <sys/syscall.h>
#endif
#include <jconfig.h>
#include "jpeg_stream.h"
#define STRING_VALUE_INNER(x) #x
#define STRING_VALUE(x) STRING_VALUE_INNER(x)
struct job {
    FILE *source[2], *destination;
    struct stat before[2];
    struct a7_jpeg_result result;
    int temporary, committed;
    char temp[4096], message[512];
};
static volatile sig_atomic_t cancelled;
static void cancel_job(int number) { (void)number; cancelled = 1; }
static int fail(struct job *j, const char *message)
{
    snprintf(j->message, sizeof(j->message), "%s", message); return -1;
}
static int check_cancel(void *context) { (void)context; return cancelled != 0; }
static int64_t read_file(void *context, void *buffer, size_t bytes)
{
    FILE *file = context;
    if (ferror(file)) return errno ? -errno : -EIO;
    size_t count = fread(buffer, 1, bytes, file);
    return !count && ferror(file) ? (errno ? -errno : -EIO) : (int64_t)count;
}
static int64_t write_file(void *context, const void *buffer, size_t bytes)
{
    FILE *file = context;
    if (ferror(file)) return errno ? -errno : -EIO;
    size_t count = fwrite(buffer, 1, bytes, file);
    return !count && ferror(file) ? (errno ? -errno : -EIO) : (int64_t)count;
}
static int publish(const char *temporary, const char *destination, char *error, size_t capacity)
{
#ifdef _WIN32
    /* No REPLACE_EXISTING: an existing result/source is never replaced. */
    if (MoveFileExA(temporary, destination, MOVEFILE_WRITE_THROUGH)) return 0;
    unsigned long code = GetLastError();
    snprintf(error, capacity, "Cannot publish output JPEG (Win32 error %lu)", code);
    return -1;
#else
    /* Avoid hard links, which FAT/exFAT cannot provide. Unsupported
     * no-replace rename operations fail without an overwrite fallback. */
    int result = (int)syscall(SYS_renameat2, AT_FDCWD, temporary, AT_FDCWD,
                              destination, 1u);
    if (result) {
        int code = errno;
        snprintf(error, capacity, "Cannot publish output JPEG: %s (errno %d)",
                 strerror(code), code);
    }
    return result;
#endif
}

static int process(struct job *j, char **paths)
{
    struct a7_jpeg_input input[2];
    for (int i = 0; i < 2; ++i) {
        j->source[i] = fopen(paths[i], "rb");
        if (!j->source[i]) return fail(j, "Cannot open input JPEG");
        if (fstat(fileno(j->source[i]), &j->before[i]) || !S_ISREG(j->before[i].st_mode) ||
            j->before[i].st_size <= 0 || (uint64_t)j->before[i].st_size > A7_JPEG_MAX_INPUT)
            return fail(j, "Input must be a completed regular JPEG of at most 96 MiB");
        input[i] = (struct a7_jpeg_input){j->source[i], (uint64_t)j->before[i].st_size, read_file};
    }
    int n = snprintf(j->temp, sizeof(j->temp), "%s.a7c2-%lu.part", paths[2], (unsigned long)getpid());
    if (n < 0 || (size_t)n >= sizeof(j->temp)) return fail(j, "Output path is too long");
    int flags = O_WRONLY | O_CREAT | O_EXCL;
#ifdef _WIN32
    flags |= O_BINARY;
#endif
    int fd = open(j->temp, flags, 0600);
    if (fd < 0) return fail(j, "Cannot create exclusive output staging file");
    j->temporary = 1; j->destination = fdopen(fd, "wb");
    if (!j->destination) { close(fd); return fail(j, "Cannot open output stream"); }
    struct a7_jpeg_output output = {j->destination, write_file};
    struct a7_jpeg_control control = {j, check_cancel};
    if (a7_jpeg_mean(&input[0], &input[1], &output, &control, &j->result))
        return fail(j, j->result.message);
    for (int i = 0; i < 2; ++i) {
        struct stat after;
        if (fstat(fileno(j->source[i]), &after) || j->before[i].st_size != after.st_size ||
            j->before[i].st_mtime != after.st_mtime) return fail(j, "Input changed during composition");
    }
    if (fflush(j->destination) || fsync(fileno(j->destination))) return fail(j, "Cannot flush output JPEG");
    int closed = fclose(j->destination); j->destination = NULL;
    if (closed) return fail(j, "Cannot close output JPEG");
    if (cancelled) return fail(j, "Composition cancelled");
    char error[256];
    if (publish(j->temp, paths[2], error, sizeof(error))) return fail(j, error);
    j->temporary = 0; j->committed = 1; return 0;
}
int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        puts("a7c2-average 0.2; libjpeg-turbo " STRING_VALUE(LIBJPEG_TURBO_VERSION)); return 0;
    }
    if (argc != 4) { fputs("Usage: a7c2-average first.jpg second.jpg new-result.jpg\n", stderr); return 2; }
    struct job *j = calloc(1, sizeof(*j));
    if (!j) { fputs("Cannot allocate composition state\n", stderr); return 1; }
    signal(SIGINT, cancel_job); signal(SIGTERM, cancel_job); process(j, argv + 1);
    for (int i = 0; i < 2; ++i) if (j->source[i]) fclose(j->source[i]);
    if (j->destination) fclose(j->destination);
    if (j->temporary && unlink(j->temp)) fprintf(stderr, "Staging cleanup failed: %s\n", strerror(errno));
    int result = j->committed ? 0 : 1;
    if (result) fprintf(stderr, "%s\n", j->message);
    else printf("{\"status\":\"saved\",\"width\":%u,\"height\":%u,\"orientation\":%u,"
                "\"mode\":\"mean-50-50\"}\n", j->result.width, j->result.height, j->result.orientation);
    free(j); return result;
}
