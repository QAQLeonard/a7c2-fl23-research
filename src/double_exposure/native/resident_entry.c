#define _GNU_SOURCE
#include "resident_entry.h"
#include <string.h>
#include <stdatomic.h>
uint64_t a7_resident_abi(void) { return (1ull << 32) | sizeof(struct a7_device_report); }
#ifndef _WIN32
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#include "../../fl23/native/sha256.h"
static struct {
    struct a7_native_session *session;
    uint8_t instance[16];
    char root[512];
    uint64_t sequence;
    int directory;
    atomic_int poisoned;
} resident = {.directory = -1};
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t journal_mutex = PTHREAD_MUTEX_INITIALIZER;
static uint32_t get32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t get64(const uint8_t *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static int write_all(int fd, const void *data, size_t size)
{
    const uint8_t *bytes = data; size_t done = 0;
    while (done < size) {
        ssize_t count = write(fd, bytes + done, size - done);
        if (count <= 0 || (size_t)count > size - done) return -1;
        done += (size_t)count;
    }
    return 0;
}
static int write_record(unsigned kind, const void *data, uint32_t size)
{
    if (resident.poisoned || resident.directory < 0 || resident.sequence == UINT64_MAX) return -1;
    char name[64]; snprintf(name, sizeof(name), "%020llu.%u.record", (unsigned long long)++resident.sequence, kind);
    uint64_t head[3] = {0}; memcpy(head, "A7JRN001", 8);
    memcpy((uint8_t *)head + 8, &kind, 4); memcpy((uint8_t *)head + 12, &size, 4); head[2] = resident.sequence;
    SHA256 sha; uint8_t checksum[32]; sha_init(&sha);
    sha_add(&sha, (const uint8_t *)head, sizeof(head)); sha_add(&sha, data, size); sha_end(&sha, checksum);
    int fd = openat(resident.directory, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    int result = fd < 0 ? -1 : 0;
    if (!result) result = write_all(fd, head, sizeof(head));
    if (!result) result = write_all(fd, data, size);
    if (!result) result = write_all(fd, checksum, sizeof(checksum));
    if (!result) result = fsync(fd);
    if (fd >= 0 && close(fd)) result = -1;
    if (!result) result = fsync(resident.directory);
    if (result) resident.poisoned = 1;
    return result;
}
static int save_record(unsigned kind, const void *data, uint32_t size)
{
    pthread_mutex_lock(&journal_mutex);
    int status = write_record(kind, data, size);
    pthread_mutex_unlock(&journal_mutex); return status;
}
static int pipeline_save(void *context, const struct a7_pipe_snapshot *s)
{ (void)context; return save_record(1, s, sizeof(*s)); }
static int request_save(void *context, const struct a7_device_report *s)
{ (void)context; return save_record(2, s, sizeof(*s)); }
static int dcf_save(void *context, const struct a7_dcf_state *s)
{ (void)context; return save_record(3, s, sizeof(*s)); }
int a7_resident_request(const void *wire, size_t size, const char *root, struct a7_device_report *out)
{
    if (!out) return A7_DEVICE_INVALID;
    memset(out, 0, sizeof(*out)); out->abi = 1;
    const uint8_t *w = wire;
    if (!w || size != 64 || memcmp(w, "A7DEX001", 8) || !root || root[0] != '/' ||
        strnlen(root, 512) >= 512) return out->status = A7_DEVICE_INVALID;
    unsigned op = get32(w + 8), any = 0;
    for (unsigned i = 48; i < 64; ++i) any |= w[i];
    if (!any || get32(w + 12) || !get64(w + 16) || op < A7_DEVICE_ARM || op > A7_DEVICE_DISABLE ||
        (op == A7_DEVICE_ARM ? (!get64(w + 24) || !get64(w + 32) || get32(w + 44) > 0xffffffu) :
         (get64(w + 24) || get64(w + 32) || get32(w + 40) || get32(w + 44))))
        return out->status = A7_DEVICE_INVALID;
    pthread_mutex_lock(&mutex);
    int status = 0;
    if (resident.poisoned) {
        if (op == A7_DEVICE_QUERY && resident.session) a7_native_session_poll(resident.session, out);
        out->review = 1; status = A7_DEVICE_REVIEW;
    }
    else if (resident.session && (memcmp(resident.instance, w + 48, 16) || strcmp(resident.root, root)))
        status = A7_DEVICE_STALE;
    else if (!resident.session) {
        if (get32(w + 8) != A7_DEVICE_ARM) status = A7_DEVICE_STALE;
        else {
            uintptr_t ap_base = 0;
            status = a7_sony_find_ap(&ap_base);
            if (!status && mkdir(root, 0700)) status = A7_DEVICE_REVIEW;
            if (!status) {
                resident.directory = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
                if (resident.directory < 0) status = A7_DEVICE_REVIEW;
            }
            if (!status) {
                memcpy(resident.instance, w + 48, 16); snprintf(resident.root, sizeof(resident.root), "%s", root);
                out->intent = 1; status = save_record(4, out, sizeof(*out));
            }
            if (!status) {
                struct a7_native_journal journal = {NULL, pipeline_save, request_save, dcf_save};
                resident.session = a7_native_session_create(resident.instance, ap_base, &journal, &status);
                if (!resident.session && !status) status = A7_DEVICE_REVIEW;
            }
            if (status && resident.directory >= 0) { resident.poisoned = 1; out->review = 1; }
        }
    }
    if (!status && op != A7_DEVICE_QUERY && save_record(5, wire, 64)) {
        out->review = 1; status = A7_DEVICE_REVIEW;
    }
    if (!status) status = a7_native_session_submit(resident.session, wire, size, out);
    out->status = status;
    pthread_mutex_unlock(&mutex); return status;
}
#else
int a7_resident_request(const void *wire,size_t size,const char *root,struct a7_device_report *out)
{ (void)wire;(void)size;(void)root;if(out){memset(out,0,sizeof(*out));out->abi=1;out->status=A7_AP_INVALID;}return A7_AP_INVALID; }
#endif
