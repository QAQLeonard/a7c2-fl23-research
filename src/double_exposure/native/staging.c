#define _GNU_SOURCE
#include "staging.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#include "../../fl23/native/sha256.h"
_Static_assert(sizeof(struct a7_stage_report) == 112, "Unsupported staging report ABI");
struct stage {
    int dir;
    u8 plan[A7_STAGE_MAX_WIRE];
    size_t plan_length;
    u64 size;
    u32 count;
    u8 *buffer;
    struct a7_stage_report *out;
};
#ifdef A7_STAGE_TESTING
/* Test executable only: process termination at durability boundaries. */
extern void a7_stage_test_step(const char *);
extern ssize_t a7_stage_test_write(int, const void *, size_t);
extern ssize_t a7_stage_test_read(int, void *, size_t);
extern int a7_stage_test_fsync(int);
extern int a7_stage_test_close(int);
#define STEP(name) a7_stage_test_step(name)
#define STAGE_WRITE a7_stage_test_write
#define STAGE_READ a7_stage_test_read
#define STAGE_FSYNC a7_stage_test_fsync
#define STAGE_CLOSE a7_stage_test_close
#else
#define STEP(name) ((void)0)
#define STAGE_WRITE write
#define STAGE_READ read
#define STAGE_FSYNC fsync
#define STAGE_CLOSE close
#endif
static u32 read32(const u8 *p)
{ return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static u64 read64(const u8 *p) { return read32(p) | (u64)read32(p + 4) << 32; }
static void write32(u8 *p, u32 v)
{ for (unsigned i = 0; i < 4; ++i) p[i] = (u8)(v >> (8 * i)); }
static void hash(const void *data, size_t length, u8 digest[32])
{ SHA256 sha; sha_init(&sha); sha_add(&sha, data, (u32)length); sha_end(&sha, digest); }
static int io_failure(struct stage *s)
{
    if (!s->out->io_error) s->out->io_error = errno ? errno : EIO;
    return A7_STAGE_IO;
}
static int close_file(struct stage *s, int fd)
{
    if (!STAGE_CLOSE(fd)) return 0;
    if (!s->out->close_error) {
        s->out->close_error = errno ? errno : EIO;
        s->out->pending_fd = fd; /* evidence only; never retry close */
    }
    return A7_STAGE_UNCERTAIN;
}
static int sync_dir(struct stage *s)
{ return STAGE_FSYNC(s->dir) ? io_failure(s) : 0; }
static int sync_parent(struct stage *s, const char *root)
{
    char parent[1024];
    size_t length = (size_t)(strrchr(root, '/') - root);
    if (!length) length = 1;
    memcpy(parent, root, length); parent[length] = 0;
    int fd = open(parent, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return io_failure(s);
    int result = STAGE_FSYNC(fd) ? io_failure(s) : 0;
    int closing = close_file(s, fd);
    return closing ? closing : result;
}
static int write_all(struct stage *s, int fd, const u8 *data, size_t length)
{
    size_t done = 0;
    while (done < length) {
        ssize_t count = STAGE_WRITE(fd, data + done, length - done);
        if (count < 0) return io_failure(s);
        if (!count || (size_t)count > length - done) { errno = EIO; return io_failure(s); }
        done += (size_t)count;
        s->out->written_bytes += (u64)count;
    }
    return 0;
}
static int read_all(struct stage *s, int fd, u8 *data, size_t length)
{
    size_t done = 0;
    while (done < length) {
        ssize_t count = STAGE_READ(fd, data + done, length - done);
        if (count < 0) return io_failure(s);
        if (!count || (size_t)count > length - done) return A7_STAGE_UNCERTAIN;
        done += (size_t)count;
    }
    u8 extra;
    ssize_t count = STAGE_READ(fd, &extra, 1);
    if (count < 0) return io_failure(s);
    return count ? A7_STAGE_UNCERTAIN : 0;
}
static int read_file(struct stage *s, const char *name, u8 *data, size_t length)
{
    int fd = openat(s->dir, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return io_failure(s);
    struct stat info;
    int result = fstat(fd, &info) ? io_failure(s) : 0;
    if (!result && (!S_ISREG(info.st_mode) || info.st_nlink != 1 || info.st_size != (off_t)length))
        result = A7_STAGE_UNCERTAIN;
    if (!result) result = read_all(s, fd, data, length);
    int closing = close_file(s, fd);
    return closing ? closing : result;
}
static int read_plan(struct stage *s)
{
    struct stat info;
    if (fstatat(s->dir, "plan.bin", &info, AT_SYMLINK_NOFOLLOW)) return io_failure(s);
    if (!S_ISREG(info.st_mode) || info.st_nlink != 1 || info.st_size < A7_STAGE_HEADER ||
        info.st_size > A7_STAGE_MAX_WIRE) return A7_STAGE_UNCERTAIN;
    s->plan_length = (size_t)info.st_size;
    return read_file(s, "plan.bin", s->plan, s->plan_length);
}
static int create_file(struct stage *s, const char *name, const u8 *data, size_t length)
{
    s->out->mutated = 1;
    int fd = openat(s->dir, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return io_failure(s);
    int result = write_all(s, fd, data, length);
    if (!result && STAGE_FSYNC(fd)) result = io_failure(s);
    int closing = close_file(s, fd);
    if (closing) result = closing;
    if (!result) result = sync_dir(s);
    return result;
}
static int present(struct stage *s, const char *name)
{
    struct stat info;
    if (!fstatat(s->dir, name, &info, AT_SYMLINK_NOFOLLOW)) return 1;
    return errno == ENOENT ? 0 : io_failure(s);
}
static int valid_request(const u8 *wire, size_t length, const void *payload, size_t bytes)
{
    if (!wire || length < A7_STAGE_HEADER || memcmp(wire, "A7STG001", 8) || read32(wire + 44))
        return 0;
    u32 op = read32(wire + 8), index = read32(wire + 12), count = read32(wire + 40);
    u64 size = read64(wire + 32);
    unsigned nonzero = 0;
    for (unsigned i = 16; i < 32; ++i) nonzero |= wire[i];
    if (!nonzero || !size || size > A7_STAGE_MAX_BYTES ||
        count != (size + A7_STAGE_CHUNK - 1) / A7_STAGE_CHUNK ||
        op < A7_STAGE_CREATE || op > A7_STAGE_QUERY) return 0;
    size_t expected = A7_STAGE_HEADER + (op == A7_STAGE_CREATE ? 32u * count : 0);
    if (length != expected) return 0;
    if (op != A7_STAGE_PUT) return !index && !bytes;
    if (index >= count || !payload) return 0;
    size_t chunk = (size_t)(size - (u64)index * A7_STAGE_CHUNK);
    if (chunk > A7_STAGE_CHUNK) chunk = A7_STAGE_CHUNK;
    return bytes == chunk;
}
static int valid_root(const char *root)
{
    if (!root || root[0] != '/') return 0;
    size_t n = 0;
    while (n < 1024 && root[n]) ++n;
    if (!n || n == 1024 || root[n - 1] == '/') return 0;
    const char *part = root + 1;
    for (const char *p = part; ; ++p) {
        if (*p && (unsigned char)*p < 32) return 0;
        if (*p != '/' && *p) continue;
        size_t length = (size_t)(p - part);
        if (!length || (length == 1 && part[0] == '.') ||
            (length == 2 && part[0] == '.' && part[1] == '.')) return 0;
        if (!*p) return 1;
        part = p + 1;
    }
}
static void header(struct stage *s, u32 operation, u32 index, u8 out[A7_STAGE_HEADER])
{
    memcpy(out, s->plan, A7_STAGE_HEADER);
    write32(out + 8, operation); write32(out + 12, index);
}
static int record_matches(struct stage *s, const char *name, u32 operation, u32 index)
{
    u8 expected[A7_STAGE_HEADER], actual[A7_STAGE_HEADER];
    header(s, operation, index, expected);
    int result = read_file(s, name, actual, sizeof(actual));
    return result ? result : memcmp(expected, actual, sizeof(actual)) ? A7_STAGE_UNCERTAIN : 0;
}
static size_t chunk_size(struct stage *s, u32 index)
{
    u64 size = s->size - (u64)index * A7_STAGE_CHUNK;
    return size > A7_STAGE_CHUNK ? A7_STAGE_CHUNK : (size_t)size;
}
static int read_chunk(struct stage *s, u32 index, u8 *data)
{
    char name[32]; u8 checksum[32];
    snprintf(name, sizeof(name), "%04u.chunk", index);
    size_t bytes = chunk_size(s, index);
    int result = read_file(s, name, data, bytes);
    if (result) return result;
    hash(data, bytes, checksum);
    if (memcmp(checksum, s->plan + A7_STAGE_HEADER + 32u * index, 32)) return A7_STAGE_DIGEST;
    s->out->verified_bytes += bytes;
    return 0;
}
static int check_core(struct stage *s, u8 buffer[A7_STAGE_CHUNK])
{
    int fd = openat(s->dir, "core.so", O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return io_failure(s);
    struct stat info;
    int result = fstat(fd, &info) ? io_failure(s) : 0;
    if (!result && (!S_ISREG(info.st_mode) || info.st_nlink != 1 || info.st_size != (off_t)s->size))
        result = A7_STAGE_UNCERTAIN;
    SHA256 sha; sha_init(&sha);
    u8 checksum[32]; u64 done = 0;
    while (!result && done < s->size) {
        size_t bytes = s->size - done > A7_STAGE_CHUNK ? A7_STAGE_CHUNK : (size_t)(s->size - done);
        ssize_t count = STAGE_READ(fd, buffer, bytes);
        if (count < 0) result = io_failure(s);
        else if (!count || (size_t)count > bytes) result = A7_STAGE_UNCERTAIN;
        else { sha_add(&sha, buffer, (u32)count); done += (u64)count; }
    }
    if (!result) {
        ssize_t count = STAGE_READ(fd, buffer, 1);
        if (count < 0) result = io_failure(s);
        else if (count) result = A7_STAGE_UNCERTAIN;
    }
    if (!result) {
        sha_end(&sha, checksum);
        if (memcmp(checksum, s->plan + 48, 32)) result = A7_STAGE_DIGEST;
        else s->out->verified_bytes += done;
    }
    int closing = close_file(s, fd);
    return closing ? closing : result;
}
static int allowed_name(struct stage *s, const char *name)
{
    if (!strcmp(name, ".") || !strcmp(name, "..") || !strcmp(name, "plan.bin")) return 1;
    if (s->out->phase == A7_STAGE_READY &&
        (!strcmp(name, "core.so") || !strcmp(name, "assemble.intent") || !strcmp(name, "assemble.done"))) return 1;
    char expected[32];
    const char *suffixes[] = {"intent", "chunk", "done"};
    for (u32 i = 0; i < s->out->completed; ++i)
        for (unsigned j = 0; j < 3; ++j) {
            snprintf(expected, sizeof(expected), "%04u.%s", i, suffixes[j]);
            if (!strcmp(name, expected)) return 1;
        }
    return 0;
}
static int verify_directory(struct stage *s)
{
    int copy = dup(s->dir);
    if (copy < 0) return io_failure(s);
    DIR *directory = fdopendir(copy);
    if (!directory) { int result = io_failure(s); close_file(s, copy); return result; }
    int result = 0;
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) { if (errno) result = io_failure(s); break; }
        if (!allowed_name(s, entry->d_name)) { result = A7_STAGE_UNCERTAIN; break; }
    }
    if (closedir(directory)) {
        if (!s->out->close_error) { s->out->close_error = errno; s->out->pending_fd = copy; }
        result = A7_STAGE_UNCERTAIN;
    }
    return result;
}
static int verify(struct stage *s)
{
    u8 *buffer = s->buffer;
    for (u32 i = 0; i < s->count; ++i) {
        char name[32];
        snprintf(name, sizeof(name), "%04u.intent", i);
        int exists = present(s, name);
        if (exists < 0) return exists;
        if (!exists) break;
        int result = record_matches(s, name, A7_STAGE_PUT, i);
        if (result) return result;
        snprintf(name, sizeof(name), "%04u.done", i);
        if ((result = record_matches(s, name, A7_STAGE_PUT, i))) return result;
        if ((result = read_chunk(s, i, buffer))) return result;
        ++s->out->completed;
    }
    int assembly = present(s, "assemble.intent");
    if (assembly < 0) return assembly;
    s->out->phase = A7_STAGE_RECEIVING;
    if (assembly) {
        if (s->out->completed != s->count) return A7_STAGE_UNCERTAIN;
        int result = record_matches(s, "assemble.intent", A7_STAGE_ASSEMBLE, 0);
        if (!result) result = record_matches(s, "assemble.done", A7_STAGE_ASSEMBLE, 0);
        if (!result) result = check_core(s, buffer);
        if (result) return result;
        s->out->phase = A7_STAGE_READY; s->out->published = 1;
    }
    return verify_directory(s);
}
static int put_chunk(struct stage *s, const u8 *request, const u8 *data, size_t bytes)
{
    u32 index = read32(request + 12);
    if (s->out->phase != A7_STAGE_RECEIVING || index != s->out->completed) return A7_STAGE_ORDER;
    u8 checksum[32]; hash(data, bytes, checksum);
    if (memcmp(checksum, s->plan + A7_STAGE_HEADER + 32u * index, 32)) return A7_STAGE_DIGEST;
    char name[32];
    snprintf(name, sizeof(name), "%04u.intent", index);
    int result = create_file(s, name, request, A7_STAGE_HEADER);
    if (result) return result;
    STEP("chunk-intent");
    snprintf(name, sizeof(name), "%04u.chunk", index);
    if ((result = create_file(s, name, data, bytes))) return result;
    STEP("chunk-data");
    if ((result = read_chunk(s, index, s->buffer))) return result;
    snprintf(name, sizeof(name), "%04u.done", index);
    if ((result = create_file(s, name, request, A7_STAGE_HEADER))) return result;
    STEP("chunk-done");
    ++s->out->completed;
    return 0;
}
static int assemble(struct stage *s, const u8 *request)
{
    if (s->out->phase != A7_STAGE_RECEIVING || s->out->completed != s->count) return A7_STAGE_ORDER;
    int result = create_file(s, "assemble.intent", request, A7_STAGE_HEADER);
    if (result) return result;
    STEP("assemble-intent");
    int fd = openat(s->dir, "assembling.tmp", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return io_failure(s);
    SHA256 sha; sha_init(&sha);
    u8 *data = s->buffer, checksum[32];
    for (u32 i = 0; !result && i < s->count; ++i) {
        result = read_chunk(s, i, data);
        size_t bytes = chunk_size(s, i);
        if (!result) { sha_add(&sha, data, (u32)bytes); result = write_all(s, fd, data, bytes); }
    }
    if (!result) {
        sha_end(&sha, checksum);
        if (memcmp(checksum, s->plan + 48, 32)) result = A7_STAGE_DIGEST;
    }
    if (!result && STAGE_FSYNC(fd)) result = io_failure(s);
    int closing = close_file(s, fd);
    if (closing) result = closing;
    if (result) return result;
    if ((result = sync_dir(s))) return result;
    STEP("assembly-data");
    /* Jiritsu staging is FAT on the camera: hard links are unsupported.
     * Exclusively create the final name, then copy acknowledged chunks. A
     * partial final file is evidence only: the loader requires assemble.done
     * and a fresh full digest check before it can load anything. */
    fd = openat(s->dir, "core.so", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return io_failure(s);
    STEP("core-created");
    for (u32 i = 0; !result && i < s->count; ++i) {
        result = read_chunk(s, i, data);
        if (!result) result = write_all(s, fd, data, chunk_size(s, i));
        if (!result) STEP("core-copy-data");
    }
    if (!result && STAGE_FSYNC(fd)) result = io_failure(s);
    closing = close_file(s, fd);
    if (closing) result = closing;
    if (result) return result;
    if ((result = sync_dir(s))) return result;
    if ((result = check_core(s, data))) return result;
    s->out->published = 1;
    if ((result = sync_dir(s))) return result;
    STEP("published");
    if (unlinkat(s->dir, "assembling.tmp", 0)) return io_failure(s);
    if ((result = sync_dir(s))) return result;
    STEP("temp-removed");
    if ((result = check_core(s, data))) return result;
    if ((result = create_file(s, "assemble.done", request, A7_STAGE_HEADER))) return result;
    STEP("assemble-done");
    s->out->phase = A7_STAGE_READY;
    return 0;
}
int a7_stage_execute(const char *root, const void *wire, size_t length,
                     const void *payload, size_t bytes, struct a7_stage_report *out)
{
    if (!out) return A7_STAGE_INVALID;
    memset(out, 0, sizeof(*out)); out->abi = A7_STAGE_ABI; out->pending_fd = -1;
    struct stage s = {.dir = -1, .out = out};
    const u8 *request = wire;
    if (!valid_root(root) || !valid_request(request, length, payload, bytes))
        return out->status = A7_STAGE_INVALID;
    out->operation = read32(request + 8);
    out->chunks = read32(request + 40);
    memcpy(out->transaction, request + 16, 16); memcpy(out->sha256, request + 48, 32);
    s.buffer = malloc(A7_STAGE_CHUNK);
    if (!s.buffer) { errno = ENOMEM; return out->status = io_failure(&s); }
    if (out->operation == A7_STAGE_CREATE) {
        if (mkdir(root, 0700)) {
            out->io_error = errno; out->phase = A7_STAGE_REVIEW;
            int status = errno == EEXIST ? A7_STAGE_EXISTS : A7_STAGE_IO;
            free(s.buffer); return out->status = status;
        }
        out->mutated = 1;
    }
    s.dir = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (s.dir < 0) { out->phase = A7_STAGE_REVIEW; int status = io_failure(&s); free(s.buffer); return out->status = status; }
    int result = 0;
    if (flock(s.dir, LOCK_EX | LOCK_NB)) {
        out->io_error = errno;
        result = errno == EWOULDBLOCK ? A7_STAGE_BUSY : A7_STAGE_IO;
        goto done;
    }
    out->locked = 1;
    if (out->operation == A7_STAGE_CREATE) {
        result = sync_parent(&s, root);
        if (!result) result = create_file(&s, "plan.bin", request, length);
        if (!result) { STEP("plan-done"); out->phase = A7_STAGE_RECEIVING; }
        goto done;
    }
    result = read_plan(&s);
    if (result) goto done;
    if (!valid_request(s.plan, s.plan_length, NULL, 0) || read32(s.plan + 8) != A7_STAGE_CREATE) {
        result = A7_STAGE_UNCERTAIN; goto done;
    }
    if (memcmp(request, s.plan, 8) || memcmp(request + 16, s.plan + 16, A7_STAGE_HEADER - 16)) {
        result = A7_STAGE_IDENTITY; goto done;
    }
    s.size = read64(s.plan + 32); s.count = read32(s.plan + 40);
    result = verify(&s);
    if (result) out->phase = A7_STAGE_REVIEW;
    if (!result && out->operation == A7_STAGE_PUT) result = put_chunk(&s, request, payload, bytes);
    else if (!result && out->operation == A7_STAGE_ASSEMBLE) result = assemble(&s, request);
done:
    if (out->locked && result && result != A7_STAGE_ORDER &&
        (result != A7_STAGE_DIGEST || out->mutated) && result != A7_STAGE_IDENTITY)
        out->phase = A7_STAGE_REVIEW;
    int closing = close_file(&s, s.dir); /* releases the directory lock */
    if (closing) { result = closing; out->phase = A7_STAGE_REVIEW; }
    out->status = result;
    free(s.buffer);
    return result;
}
