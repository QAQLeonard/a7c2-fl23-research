#define _GNU_SOURCE
#include "sony_sdk.h"
#include <string.h>
#ifndef _WIN32
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
#include <stdio.h>
static int bind_numbering(struct a7_sony_sdk *);
static int belongs(void *pointer, const char *module)
{
    Dl_info info;
    if (!pointer || !dladdr(pointer, &info) || !info.dli_fname) return 0;
    const char *slash = strrchr(info.dli_fname, '/');
    return !strcmp(slash ? slash + 1 : info.dli_fname, module);
}
static int resolve(void *module, const char *owner, const char *name, void *out)
{
    void *symbol = dlsym(module, name);
    if (!belongs(symbol, owner)) return A7_AP_OWNER;
    memcpy(out, &symbol, sizeof(symbol)); return 0;
}
int a7_sony_sdk_bind(struct a7_sony_sdk *s)
{
    if (!s || s->bound || s->review || s->lease.token || s->modules[0] || s->modules[1]) return A7_AP_INVALID;
    s->close_attempts = 0; s->status = 0;
    struct a7_ap_report report;
    int status = a7_ap_acquire(A7_AP_JOB, &s->lease, &report);
    if (status) return status;
    s->modules[0] = dlopen("libmpr.so", A7_AP_NOLOAD_NOW);
    s->modules[1] = dlopen("libInfraFsys.so", A7_AP_NOLOAD_NOW);
    if (!s->modules[0] || !s->modules[1]) status = A7_AP_MPR_MISSING;
    const char *catalog[] = {"_ZN4sidb10recordInfo5clearEv", "_ZN4sidb6SelectEjjPNS_10recordInfoEb",
        "_ZN4sidb13IssueUniqueIdEjPjb", "_ZN4sidb6UpdateEjRKNS_10recordInfoEbb",
        "_ZN4sidb22GetMediaIdFromUniqueIdEjPj", "_ZN4sidb5FlushEj"};
    const char *fsys[] = {"Fsys_FindFirst", "Fsys_FindNext", "Fsys_Mkdir", "Fsys_Move"};
    void *fields[] = {&s->catalog.clear, &s->catalog.select, &s->catalog.issue,
                      &s->catalog.update, &s->catalog.media, &s->catalog.flush};
    void *file_fields[] = {&s->dcf.first, &s->dcf.next, &s->dcf.mkdir, &s->dcf.move};
    for (unsigned i = 0; !status && i < 6; ++i)
        status = resolve(s->modules[0], "libmpr.so", catalog[i], fields[i]);
    for (unsigned i = 0; !status && i < 4; ++i)
        status = resolve(s->modules[1], "libInfraFsys.so", fsys[i], file_fields[i]);
    if (!status) status = bind_numbering(s);
    s->status = status;
    if (status) {
        int closing = a7_sony_sdk_close(s);
        return closing ? closing : status;
    }
    s->dcf.files = s->lease.api; s->bound = 1; return 0;
}
int a7_sony_sdk_close(struct a7_sony_sdk *s)
{
    if (!s || s->review) return A7_AP_UNCERTAIN;
    for (int i = 1; i >= 0; --i) {
        if (!s->modules[i]) continue;
        if (s->close_attempts & (1u << i)) { s->review = 1; return A7_AP_UNCERTAIN; }
        s->close_attempts |= 1u << i;
        int status = dlclose(s->modules[i]);
        if (status) { s->review = 1; s->status = status; return A7_AP_UNCERTAIN; }
        s->modules[i] = NULL;
    }
    if (s->lease.token) {
        struct a7_ap_report report;
        int status = a7_ap_release(&s->lease, &report);
        if (status) { s->review = 1; s->status = status; return status; }
    }
    memset(&s->catalog, 0, sizeof(s->catalog)); memset(&s->dcf, 0, sizeof(s->dcf));
    s->bound = 0; return 0;
}
struct ap_ranges { uintptr_t base; unsigned flags; };
static int contains(const struct dl_phdr_info *info, uintptr_t offset, size_t bytes, unsigned flags)
{
    for (unsigned i = 0; i < info->dlpi_phnum; ++i) {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_type == PT_LOAD && (p->p_flags & flags) == flags && offset >= p->p_vaddr &&
            bytes <= p->p_memsz && offset - p->p_vaddr <= p->p_memsz - bytes) return 1;
    }
    return 0;
}
static int numbering_extent(struct dl_phdr_info *info, size_t bytes, void *opaque)
{
    (void)bytes;
    struct ap_ranges *r = opaque;
    if ((uintptr_t)info->dlpi_addr != r->base) return 0;
    if (contains(info, 0x3928f0, 4 * 0x5570, PF_R | PF_W) &&
        contains(info, 0x3a7ee0, 64, PF_R | PF_W) &&
        contains(info, 0x123298, 0x74, PF_R | PF_X)) r->flags = 1;
    return 1;
}
static int writable_span(const void *pointer, size_t bytes)
{
    uintptr_t start = (uintptr_t)pointer;
    if (!start || bytes > UINTPTR_MAX - start) return 0;
    FILE *maps = fopen("/proc/self/maps", "r");
    if (!maps) return 0;
    char line[512], permissions[5]; unsigned long low, high;
    int valid = 0;
    while (fgets(line, sizeof(line), maps)) {
        if (sscanf(line, "%lx-%lx %4s", &low, &high, permissions) == 3 &&
            permissions[0] == 'r' && permissions[1] == 'w' && start >= low && start + bytes <= high) {
            valid = 1; break;
        }
    }
    if (fclose(maps)) valid = 0;
    return valid;
}
static int cache_update(void *context, uint32_t media, uint16_t number, const char *name, int ready)
{
    struct a7_sony_sdk *s = context;
    if (!s || !s->bound || number < 100 || number > 999 || !name || strlen(name) != 8) return A7_AP_INVALID;
    uint32_t slot = s->slot_id(s->msidconv, media);
    if (slot >= 4) return A7_AP_INVALID;
    s->number_lock(s->dcf_mutex);
    uint8_t *state = (uint8_t *)s->dcf_cache + (size_t)slot * 0x5570;
    uint8_t *entry = state + 0xf0 + (size_t)(number - 100) * 24;
    uint32_t selected = 0, create = 0, actual_number = 0;
    memcpy(&actual_number, entry, 4); memcpy(&selected, entry + 16, 4); memcpy(&create, entry + 20, 4);
    int status = 0;
    if (!state[0]) status = A7_AP_BUSY;
    else if (ready ? (actual_number != number || memcmp(entry + 4, name, 8) ||
                      (selected != 0 && selected != 1) || !(create & 0x200)) :
                     (entry[4] || create || (actual_number && actual_number != number))) status = A7_AP_BUSY;
    uint8_t *files = NULL, *file_row = NULL;
    if (!status) {
        memcpy(&files, state + 0xb8, sizeof(files));
        if (!writable_span(files, 900u * 0x4e6u)) status = A7_AP_OWNER;
        else {
            file_row = files + (size_t)(number - 100) * 0x4e6;
            if (!ready) {
                /* An empty physical folder name is insufficient: the native
                 * allocator may already have reserved file numbers there. */
                for (unsigned i = 0; i < 0x4e6; ++i) if (file_row[i]) { status = A7_AP_BUSY; break; }
            } else {
                uint16_t highest, count;
                memcpy(&highest, file_row + 0x4e2, 2); memcpy(&count, file_row + 0x4e4, 2);
                if (!(file_row[0] & 2) || !highest || !count) status = A7_AP_UNCERTAIN;
            }
        }
    }
    if (!status) {
        /* Use the native constructor and native GNU C++11 string assignment;
         * no guessed std::string/std::map allocation or destructor ABI. The
         * eight-character DCF name remains in its native SSO storage. */
        uint64_t file_info[0x88 / 8] = {0};
        s->file_info_ctor(file_info);
        uint8_t *string = (uint8_t *)file_info + 8;
        s->string_assign(string, name);
        void *characters = NULL; uint64_t length = 0;
        memcpy(&characters, string, sizeof(characters)); memcpy(&length, string + 8, 8);
        if (characters != string + 16 || length != 8) status = A7_AP_OWNER;
        else {
            /* This exported updater does NOT lock internally. Use exactly
             * the normalLock used by native DCF allocation/table snapshots. */
            s->folder_update(slot, number, string, ready ? 0 : 1, 0x200);
            /* Same native helper used by FindDcfObject: reserve numeric JPEG
             * 0001 in the new folder's bitmap/high-water/count cache as well.
             * Native capture allocation can then safely use this directory. */
            if (!ready) s->file_update(slot, number, 1);
            memcpy(&actual_number, entry, 4); memcpy(&selected, entry + 16, 4); memcpy(&create, entry + 20, 4);
            if (actual_number != number || memcmp(entry + 4, name, 8) ||
                selected != (uint32_t)(ready ? 0 : 1) || !(create & 0x200)) status = A7_AP_UNCERTAIN;
            uint16_t highest, count;
            memcpy(&highest, file_row + 0x4e2, 2); memcpy(&count, file_row + 0x4e4, 2);
            if (!(file_row[0] & 2) || !highest || !count) status = A7_AP_UNCERTAIN;
        }
    }
    s->number_unlock(s->dcf_mutex);
    return status;
}
static int cache_reserve(void *ctx, uint32_t media, uint16_t number, const char *name)
{ return cache_update(ctx, media, number, name, 0); }
static int cache_ready(void *ctx, uint32_t media, uint16_t number, const char *name)
{ return cache_update(ctx, media, number, name, 1); }
static int bind_numbering(struct a7_sony_sdk *s)
{
    void *module = s->modules[0];
    int status = resolve(module, "libmpr.so", "_ZN3mpr6thread10normalLock4lockEv", &s->number_lock);
    if (!status) status = resolve(module, "libmpr.so", "_ZN3mpr6thread10normalLock6unlockEv", &s->number_unlock);
    if (!status) status = resolve(module, "libmpr.so", "_ZN3mpr8msidconv9GetSlotIDEj", &s->slot_id);
    if (!status) status = resolve(module, "libmpr.so", "_ZN3mpr15ExistedFileInfoC1Ev", &s->file_info_ctor);
    if (!status) status = resolve(module, "libmpr.so", "_ZN8DcfNamer17UpdateFolderTableEjtNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEN3mpr15DcfDirSelectInhENS6_15DcfDirCreateInhE", &s->folder_update);
    s->msidconv = dlsym(module, "_ZN3mpr10g_msidconvE");
    void *assign = dlsym(module, "_ZNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE6assignEPKc");
    struct link_map *map = NULL; Dl_info info;
    if (status || !belongs(s->msidconv, "libmpr.so") || dlinfo(module, RTLD_DI_LINKMAP, &map) || !map ||
        !assign || !dladdr(assign, &info) || !info.dli_fname) return A7_AP_OWNER;
    const char *slash = strrchr(info.dli_fname, '/');
    if (strncmp(slash ? slash + 1 : info.dli_fname, "libstdc++.so.6", 13)) return A7_AP_OWNER;
    uintptr_t base = (uintptr_t)map->l_addr;
    if ((void *)s->file_info_ctor != (void *)(base + 0xb81cc) ||
        (void *)s->folder_update != (void *)(base + 0x123208) ||
        (void *)s->slot_id != (void *)(base + 0x9afd0)) return A7_AP_OWNER;
    struct ap_ranges range = {base, 0}; dl_iterate_phdr(numbering_extent, &range);
    if (!range.flags) return A7_AP_OWNER;
    uint32_t helper[4], ending;
    memcpy(helper, (const void *)(base + 0x123298), sizeof(helper));
    memcpy(&ending, (const void *)(base + 0x123308), 4);
    if (helper[0] != 0xd0000ec3u || helper[1] != 0x53003c21u || helper[2] != 0x2a0003e0u ||
        helper[3] != 0xd28aae04u || ending != 0xd65f03c0u) return A7_AP_OWNER;
    void *file_update = (void *)(base + 0x123298);
    memcpy(&s->file_update, &file_update, sizeof(file_update));
    memcpy(&s->string_assign, &assign, sizeof(assign));
    s->dcf_cache = (void *)(base + 0x3928f0); s->dcf_mutex = (void *)(base + 0x3a7ee0);
    s->dcf.cache_context = s; s->dcf.reserve = cache_reserve; s->dcf.ready = cache_ready;
    return 0;
}
static int inspect(struct dl_phdr_info *info, size_t bytes, void *opaque)
{
    (void)bytes;
    struct ap_ranges *ranges = opaque;
    if ((uintptr_t)info->dlpi_addr != ranges->base) return 0;
    if (contains(info, 0x09117898, sizeof(void *), PF_R | PF_W) &&
        contains(info, 0x05ef43b0, sizeof(pthread_mutex_t), PF_R | PF_W) &&
        contains(info, 0x0356bd70, 64, PF_R | PF_X) &&
        contains(info, 0x03573c2c, 192, PF_R | PF_X)) ranges->flags = 1;
    return 1;
}
static int ap_lock(void *mutex) { return pthread_mutex_lock(mutex); }
static int ap_unlock(void *mutex) { return pthread_mutex_unlock(mutex); }
static int matching_code(uintptr_t base)
{
    uint32_t words[16]; memcpy(words, (const void *)(base + 0x0356bd70), sizeof(words));
    return words[4] == 0xb0014c40u && words[6] == 0x910ec000u &&
           words[10] == 0xf9444c01u && words[12] == 0xf9044c13u;
}
static int find_ap(struct dl_phdr_info *info, size_t bytes, void *opaque)
{
    (void)bytes;
    if (contains(info, 0x09117898, sizeof(void *), PF_R | PF_W) &&
        contains(info, 0x05ef43b0, sizeof(pthread_mutex_t), PF_R | PF_W) &&
        contains(info, 0x0356bd70, 64, PF_R | PF_X) &&
        contains(info, 0x03573c2c, 192, PF_R | PF_X) && matching_code((uintptr_t)info->dlpi_addr)) {
        struct ap_ranges *r = opaque; r->base = (uintptr_t)info->dlpi_addr; r->flags = 1; return 1;
    }
    return 0;
}
int a7_sony_find_ap(uintptr_t *out)
{
    if (!out) return A7_AP_INVALID;
    struct ap_ranges ranges = {0}; dl_iterate_phdr(find_ap, &ranges);
    if (!ranges.flags) return A7_AP_OWNER;
    *out = ranges.base; return 0;
}
int a7_sony_delegate_api(uintptr_t base, struct a7_delegate_api *out)
{
    if (!out) return A7_AP_INVALID;
    memset(out, 0, sizeof(*out));
    struct ap_ranges ranges = {base, 0};
    dl_iterate_phdr(inspect, &ranges);
    if (!ranges.flags) return A7_AP_OWNER;
    /* Validate semantic instruction positions in the pinned register path:
     * native mutex address, registry slot load and registry slot store. */
    if (!matching_code(base)) return A7_AP_OWNER;
    out->context = (void *)(base + 0x05ef43b0);
    out->slot = (struct a7_delegate_object **)(base + 0x09117898);
    out->lock = ap_lock; out->unlock = ap_unlock;
    return 0;
}
#else
int a7_sony_sdk_bind(struct a7_sony_sdk *s) { (void)s; return A7_AP_INVALID; }
int a7_sony_sdk_close(struct a7_sony_sdk *s) { (void)s; return A7_AP_INVALID; }
int a7_sony_delegate_api(uintptr_t base, struct a7_delegate_api *out)
{ (void)base; if (out) memset(out, 0, sizeof(*out)); return A7_AP_INVALID; }
int a7_sony_find_ap(uintptr_t *out) { (void)out; return A7_AP_INVALID; }
#endif
