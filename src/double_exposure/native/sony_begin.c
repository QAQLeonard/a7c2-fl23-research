#define _GNU_SOURCE
#include "sony_begin.h"
#include "sony_sdk.h"
#include <string.h>
#ifndef _WIN32
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
typedef void (*native_event)(void *);
static struct {
    native_event *slot[2], original[2];
    struct a7_ap_lease permanent;
    a7_pipe_sink sink;
    void *context;
    uint64_t epoch, generation;
    uint32_t media, active, poisoned;
} hook;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t drained = PTHREAD_COND_INITIALIZER;
static void *permanent_ap;
struct main_image { uintptr_t base; unsigned match; };
static int is_main(struct dl_phdr_info *info, size_t bytes, void *context)
{
    (void)bytes;
    struct main_image *main = context;
    if ((uintptr_t)info->dlpi_addr == main->base && (!info->dlpi_name || !*info->dlpi_name)) main->match = 1;
    return main->match ? 1 : 0;
}
static int retain_ap(uintptr_t base)
{
    if (__atomic_load_n(&permanent_ap, __ATOMIC_ACQUIRE)) return 0;
    Dl_info info;
    if (!dladdr((void *)(base + 0x03572cf0), &info) || info.dli_fbase != (void *)base || !info.dli_fname)
        return A7_AP_OWNER;
    void *pin = dlopen(info.dli_fname, A7_AP_NOLOAD_NOW);
    if (!pin) {
        struct main_image main = {base, 0}; dl_iterate_phdr(is_main, &main);
        if (main.match) pin = dlopen(NULL, RTLD_NOW);
    }
    if (!pin) return A7_AP_PIN;
    void *empty = NULL;
    if (!__atomic_compare_exchange_n(&permanent_ap, &empty, pin, 0, __ATOMIC_SEQ_CST, __ATOMIC_ACQUIRE) && dlclose(pin))
        return A7_AP_UNCERTAIN;
    return 0;
}
static uint32_t get32(const void *p) { uint32_t value; memcpy(&value, p, 4); return value; }
static void notify(void *payload, uint32_t kind)
{
    struct a7_pipe_event event = {0};
    a7_pipe_sink sink;
    void *context;
    native_event original;
    pthread_mutex_lock(&mutex);
    sink = hook.sink; context = hook.context; original = hook.original[kind == A7_PIPE_BEGIN ? 0 : 1];
    if (sink) {
        if (hook.media == UINT32_MAX && kind == A7_PIPE_BEGIN && payload &&
            get32((uint8_t *)payload + 4) == 1 && !get32((uint8_t *)payload + 0x54))
            hook.media = get32((uint8_t *)payload + 8);
        ++hook.active;
        event.kind = kind; event.epoch = hook.epoch;
        event.generation = hook.generation; event.media = hook.media;
    }
    pthread_mutex_unlock(&mutex);
    if (sink && payload && get32((uint8_t *)payload + 4) == 1 &&
        get32((uint8_t *)payload + 8) == event.media) {
        event.content = get32((uint8_t *)payload + 12);
        event.capture = event.content + 1;
        if (get32((uint8_t *)payload + 0x54)) {
            event.kind = A7_PIPE_EVENT_FAULT; event.outcome = A7_PAIR_UNKNOWN;
        }
        sink(context, &event);
    }
    original(payload);
    if (sink) {
        pthread_mutex_lock(&mutex);
        if (!--hook.active) pthread_cond_broadcast(&drained);
        pthread_mutex_unlock(&mutex);
    }
}
static void notify_begin(void *payload) { notify(payload, A7_PIPE_BEGIN); }
static void notify_finish(void *payload) { notify(payload, A7_PIPE_SAVED); }
int a7_sony_events_attach_bound(const struct a7_sony_event_slots *slots, a7_pipe_sink sink,
    void *context, uint64_t epoch, uint32_t media, uint64_t generation)
{
    if (!slots || !slots->begin || !slots->finish || slots->begin == slots->finish ||
        (uintptr_t)slots->begin % sizeof(void *) || (uintptr_t)slots->finish % sizeof(void *) ||
        !slots->expected_begin || !slots->expected_finish || !sink || !context || !epoch || !generation)
        return A7_PIPE_INVALID;
    pthread_mutex_lock(&mutex);
    int status = 0;
    if (hook.poisoned || hook.sink || hook.active) status = A7_PIPE_STATE;
    native_event *storage[2] = {slots->begin, slots->finish};
    native_event expected[2] = {slots->expected_begin, slots->expected_finish};
    native_event wrappers[2] = {notify_begin, notify_finish};
    if (!status && !hook.slot[0]) {
        for (unsigned i = 0; i < 2; ++i)
            if (__atomic_load_n(storage[i], __ATOMIC_ACQUIRE) != expected[i]) status = A7_AP_OWNER;
        if (!status) {
            struct a7_ap_report report;
            status = a7_ap_acquire(A7_AP_CALLBACK, &hook.permanent, &report);
        }
        if (!status) {
            memcpy(hook.original, expected, sizeof(expected));
            for (unsigned i = 0; i < 2; ++i) {
                native_event original = expected[i];
                if (!__atomic_compare_exchange_n(storage[i], &original, wrappers[i], 0,
                                                 __ATOMIC_SEQ_CST, __ATOMIC_ACQUIRE)) {
                    hook.poisoned = 1; status = A7_AP_UNCERTAIN; break;
                }
                hook.slot[i] = storage[i];
            }
        }
    }
    for (unsigned i = 0; !status && i < 2; ++i)
        if (hook.slot[i] != storage[i] || hook.original[i] != expected[i] ||
            __atomic_load_n(storage[i], __ATOMIC_ACQUIRE) != wrappers[i]) status = A7_PIPE_STATE;
    if (!status) {
        hook.context = context; hook.epoch = epoch; hook.media = media;
        hook.generation = generation; hook.sink = sink;
    }
    pthread_mutex_unlock(&mutex); return status;
}
int a7_sony_begin_attach(a7_pipe_sink sink, void *context, uint64_t epoch,
                         uint32_t media, uint64_t generation)
{
    void *mpr = dlopen("libmpr.so", A7_AP_NOLOAD_NOW);
    if (!mpr) return A7_AP_MPR_MISSING;
    struct a7_sony_event_slots slots = {0};
    void *symbols[2] = {dlsym(mpr, "_ZN3mpr29gp_evtStillWriteCountdownFuncE"),
                        dlsym(mpr, "_ZN3mpr28gp_evtStillWriteFinishedFuncE")};
    uintptr_t base = 0;
    int status = a7_sony_find_ap(&base);
    for (unsigned i = 0; !status && i < 2; ++i) {
        Dl_info info;
        if (!symbols[i] || !dladdr(symbols[i], &info) || !info.dli_fname) status = A7_AP_OWNER;
        else {
            const char *slash = strrchr(info.dli_fname, '/');
            if (strcmp(slash ? slash + 1 : info.dli_fname, "libmpr.so")) status = A7_AP_OWNER;
        }
    }
    if (!status) {
        slots.begin = symbols[0]; slots.finish = symbols[1];
        slots.expected_begin = (native_event)(base + 0x03572cf0);
        slots.expected_finish = (native_event)(base + 0x03573c2c);
        status = retain_ap(base);
        if (!status) status = a7_sony_events_attach_bound(&slots, sink, context, epoch, media, generation);
    }
    if (dlclose(mpr)) status = A7_AP_UNCERTAIN;
    return status;
}
int a7_sony_begin_detach(void *context)
{
    pthread_mutex_lock(&mutex);
    if (hook.context != context || !hook.sink) { pthread_mutex_unlock(&mutex); return A7_PIPE_STATE; }
    hook.sink = NULL;
    while (hook.active) pthread_cond_wait(&drained, &mutex);
    hook.context = NULL;
    pthread_mutex_unlock(&mutex); return 0;
}
#else
int a7_sony_begin_attach(a7_pipe_sink sink, void *context, uint64_t epoch, uint32_t media, uint64_t generation)
{ (void)sink; (void)context; (void)epoch; (void)media; (void)generation; return A7_AP_INVALID; }
int a7_sony_begin_detach(void *context) { (void)context; return A7_AP_INVALID; }
int a7_sony_events_attach_bound(const struct a7_sony_event_slots *slots,a7_pipe_sink sink,void *context,
 uint64_t epoch,uint32_t media,uint64_t generation)
{ (void)slots;(void)sink;(void)context;(void)epoch;(void)media;(void)generation;return A7_AP_INVALID; }
#endif
