#define _GNU_SOURCE
#include "file_entry.h"
#include <dlfcn.h>
#include <link.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <sys/stat.h>
#include <unistd.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#include "../../fl23/native/sha256.h"
enum { ENTRY_INVALID = -17001, ENTRY_IO = -17002, ENTRY_EXISTS = -17003 };
static atomic_flag busy = ATOMIC_FLAG_INIT;
static uint8_t wire[A7_STAGE_MAX_WIRE], payload[A7_STAGE_CHUNK], plan[A7_STAGE_MAX_WIRE];
static union { struct a7_stage_report stage; struct a7_device_report device; } report;
static uint32_t get32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t get64(const uint8_t *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static int valid_control(const uint8_t *w)
{
    unsigned op = get32(w + 8), any = 0;
    for (unsigned i = 48; i < 64; ++i) any |= w[i];
    return any && !get32(w + 12) && get64(w + 16) && op >= A7_DEVICE_ARM && op <= A7_DEVICE_DISABLE &&
        (op == A7_DEVICE_ARM ? (get64(w + 24) && get64(w + 32) && get32(w + 44) <= 0xffffffu) :
         (!get64(w + 24) && !get64(w + 32) && !get32(w + 40) && !get32(w + 44)));
}
static int write_all(int fd, const void *data, size_t bytes)
{
    const uint8_t *p = data; size_t done = 0;
    while (done < bytes) {
        ssize_t count = write(fd, p + done, bytes - done);
        if (count <= 0 || (size_t)count > bytes - done) return ENTRY_IO;
        done += (size_t)count;
    }
    return 0;
}
static int read_file(int directory, const char *name, uint8_t *out, size_t capacity, size_t *bytes)
{
    int fd = openat(directory, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return ENTRY_IO;
    struct stat state;
    int result = fstat(fd, &state) || !S_ISREG(state.st_mode) || state.st_size < 0 ||
                 (uint64_t)state.st_size > capacity ? ENTRY_INVALID : 0;
    size_t done = 0;
    while (!result && done < (size_t)state.st_size) {
        ssize_t count = read(fd, out + done, (size_t)state.st_size - done);
        if (count <= 0) result = ENTRY_IO;
        else done += (size_t)count;
    }
    uint8_t extra;
    if (!result && read(fd, &extra, 1) != 0) result = ENTRY_IO;
    if (close(fd)) result = ENTRY_IO;
    if (!result) *bytes = done;
    return result;
}
static int module_owns(void *module, void *symbol)
{
    struct link_map *map = NULL; Dl_info info;
    return !dlinfo(module, RTLD_DI_LINKMAP, &map) && map && dladdr(symbol, &info) &&
           (void *)map->l_addr == info.dli_fbase;
}
static int control(const uint8_t *wire, size_t length, const char *root, const char *journal,
                   struct a7_device_report *out)
{
    char core[1024], plan_path[1024];
    if (snprintf(core, sizeof(core), "%s/core.so", root) >= (int)sizeof(core) ||
        snprintf(plan_path, sizeof(plan_path), "%s", root) >= (int)sizeof(plan_path)) return ENTRY_INVALID;
    unsigned op = get32(wire + 8);
    if (length != 64 || op < A7_DEVICE_ARM || op > A7_DEVICE_DISABLE) return ENTRY_INVALID;
    if (op == A7_DEVICE_ARM) {
        int dir = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (dir < 0) return ENTRY_IO;
        size_t size = 0;
        int status = read_file(dir, "plan.bin", plan, sizeof(plan), &size);
        if (close(dir)) status = ENTRY_IO;
        if (status || size < 80 || memcmp(plan + 16, wire + 48, 16)) return ENTRY_INVALID;
        uint32_t query = A7_STAGE_QUERY; memcpy(plan + 8, &query, 4);
        struct a7_stage_report stage;
        status = a7_stage_execute(root, plan, 80, NULL, 0, &stage);
        if (status || stage.phase != A7_STAGE_READY) return status ? status : ENTRY_INVALID;
        struct a7_boot_report boot;
        status = a7_boot_dispatch(core, A7_BOOT_START, NULL, &boot);
        if (status != 0 && status != A7_AP_ALREADY) return status;
    }
    void *module = dlopen(core, A7_AP_NOLOAD_NOW);
    if (!module) return A7_BOOT_NOT_RESIDENT;
    void *symbol = dlsym(module, "a7_resident_request");
    void *abi_symbol = dlsym(module, "a7_resident_abi");
    int status = A7_BOOT_SYMBOL;
    if (symbol && abi_symbol && module_owns(module, symbol) && module_owns(module, abi_symbol)) {
        int (*request)(const void *, size_t, const char *, struct a7_device_report *);
        uint64_t (*abi)(void);
        memcpy(&request, &symbol, sizeof(request)); memcpy(&abi, &abi_symbol, sizeof(abi));
        if (abi() != ((1ull << 32) | sizeof(*out))) status = A7_BOOT_VERSION;
        else status = request(wire, length, journal, out);
    }
    if (dlclose(module)) return A7_BOOT_CLOSE;
    return status;
}
static int run(const char *directory)
{
    if (!directory || directory[0] != '/' || strnlen(directory, 512) >= 512) return ENTRY_INVALID;
    int dir = open(directory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dir < 0) return ENTRY_IO;
    size_t length = 0, bytes = 0;
    int status = read_file(dir, "a7c2.dex.request", wire, sizeof(wire), &length);
    if (status) { close(dir); return status; }
    unsigned kind = length >= 80 && !memcmp(wire, "A7STG001", 8) ? 1 :
                    length == 64 && !memcmp(wire, "A7DEX001", 8) ? 2 : 0;
    int result = openat(dir, "a7c2.dex.result", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (result < 0) { close(dir); return ENTRY_EXISTS; }
    uint8_t header[64] = {0}; memcpy(header, "A7ENT001", 8);
    uint32_t abi = 1; memcpy(header + 8, &abi, 4); memcpy(header + 12, &kind, 4);
    SHA256 sha; sha_init(&sha); sha_add(&sha, wire, (uint32_t)length); sha_end(&sha, header + 32);
    status = write_all(result, header, sizeof(header));
    if (!status && (fsync(result) || fsync(dir))) status = ENTRY_IO;
    if (status) { close(result); close(dir); return status; }
    memset(&report, 0, sizeof(report));
    uint32_t report_bytes = kind == 1 ? sizeof(report.stage) : sizeof(report.device);
    if (!status) {
        const uint8_t empty[16] = {0};
        const uint8_t *identity = kind == 1 ? wire + 16 : kind == 2 ? wire + 48 : empty;
        char token[33], root[1024], journal[1024];
        for (unsigned i = 0; i < 16; ++i) snprintf(token + i * 2, 3, "%02x", identity[i]);
        if (!kind || snprintf(root, sizeof(root), "%s/a7c2-dex-%s", directory, token) >= (int)sizeof(root) ||
            snprintf(journal, sizeof(journal), "%s/a7c2-dex-run-%s", directory, token) >= (int)sizeof(journal))
            status = ENTRY_INVALID;
        else if (kind == 1) {
            if (get32(wire + 8) == A7_STAGE_PUT)
                status = read_file(dir, "a7c2.dex.payload", payload, sizeof(payload), &bytes);
            if (!status) status = a7_stage_execute(root, wire, length, bytes ? payload : NULL, bytes, &report.stage);
        } else status = valid_control(wire) ? control(wire, length, root, journal, &report.device) : ENTRY_INVALID;
    }
    /* Completion is an append-only receipt. A partial write/close keeps the
     * intent/header and payload evidence; this module never retries a command. */
    uint32_t tail[2] = {(uint32_t)status, report_bytes};
    SHA256 receipt; uint8_t checksum[32]; sha_init(&receipt);
    sha_add(&receipt, header, sizeof(header)); sha_add(&receipt, (const uint8_t *)tail, sizeof(tail));
    sha_add(&receipt, (const uint8_t *)&report, report_bytes); sha_end(&receipt, checksum);
    int written = write_all(result, tail, sizeof(tail));
    if (!written) written = write_all(result, &report, report_bytes);
    if (!written) written = write_all(result, checksum, sizeof(checksum));
    if (!written) written = write_all(result, "A7DONE01", 8);
    if (!written && fsync(result)) written = ENTRY_IO;
    if (close(result)) written = ENTRY_IO;
    if (!written && fsync(dir)) written = ENTRY_IO;
    if (close(dir)) written = ENTRY_IO;
    return written ? written : status;
}
int a7_file_entry_run(const char *directory)
{
    if (atomic_flag_test_and_set(&busy)) return ENTRY_EXISTS;
    int status = run(directory);
    atomic_flag_clear(&busy); return status;
}
#ifndef A7_ENTRY_NO_AUTORUN
__attribute__((constructor)) static void entry(void) { (void)a7_file_entry_run("/tmp/jiritsu"); }
#endif
