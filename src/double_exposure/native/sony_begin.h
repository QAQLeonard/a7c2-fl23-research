#ifndef A7C2_SONY_BEGIN_H
#define A7C2_SONY_BEGIN_H
#include "pipeline.h"
typedef void (*a7_sony_event_function)(void *);
struct a7_sony_event_slots {
    a7_sony_event_function *begin, *finish;
    a7_sony_event_function expected_begin, expected_finish;
};
/* Observes full SDK countdown/write-finished payloads before AP marshaling.
 * Native SDK callback pointer replacement is an aligned AArch64 atomic CAS.
 * Original function is forwarded unchanged. The wrapper keeps a PERMANENT
 * AP callback lease until process exit because native SDK pointer dispatch has
 * no proven unload rundown. detach drains sink/context users and removes the
 * sink only; the forwarding wrapper remains mapped. Never pretend this permits
 * retiring/upgrading the core in the current AP process.
 */
A7_JPEG_API int a7_sony_begin_attach(a7_pipe_sink, void *, uint64_t, uint32_t, uint64_t);
A7_JPEG_API int a7_sony_begin_detach(void *);
/* Explicit SDK provider seam. Caller validates slots, expected original
 * functions, alignment and module lifetime; offline fixtures use synthetic
 * SDK slots. Slots/original-function modules must stay valid until AP process
 * exit, including after context detach. No production discovery fallback. */
A7_JPEG_API int a7_sony_events_attach_bound(const struct a7_sony_event_slots *,
    a7_pipe_sink, void *, uint64_t, uint32_t, uint64_t);
#endif
