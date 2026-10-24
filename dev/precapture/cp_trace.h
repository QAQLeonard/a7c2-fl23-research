/* Bounded trace storage core. No native hooks, placement, loader or camera I/O.
 * A future adapter must prove one serialized owner per lane (including IRQ
 * exclusion), fresh allocated storage and source/boot identity. An input owner
 * value is checked for consistency only; it is not a native task query.
 */
#ifndef PRECAPTURE_CP_TRACE_H
#define PRECAPTURE_CP_TRACE_H
#include "cp_control_state.h"
#define PC_TRACE_MAGIC 0x31544350u
#define PC_TRACE_ABI 1u
#define PC_TRACE_CAPACITY 64u
enum pc_trace_kind { PC_POOL=1,PC_REQUEST,PC_REPLY,PC_RELEASE,
    PC_EXPOSURE_BEGIN,PC_EXPOSURE_END,PC_S2,PC_DIAGNOSTIC };
/* The raw32 clock is NEVER silently promoted to an exposure time or64-bit
 * epoch. Unknown generation/handle may remain0; do not forge them. context_raw
 * is a raw native argument and is NOT an identified frame or pixel lease.
 */
struct pc_trace_event {
    u32 kind,generation,ticket,handle,clock_raw,context_raw,detail[4];
};
struct pc_trace_binding {
    u32 source_tag,epoch_lo,epoch_hi,owner,capacity,clock_domain,nonce,reserved;
};
struct pc_trace_record { u32 sequence;struct pc_trace_event event;u32 guard; };
struct pc_trace_lane {
    u32 magic,abi,bytes,source_tag,epoch_lo,epoch_hi,owner,capacity;
    u32 clock_domain,nonce,written,frozen,overflow,busy,reserved[2];
    struct pc_trace_record records[PC_TRACE_CAPACITY];
};
_Static_assert(sizeof(struct pc_trace_binding)==32,"trace binding ABI");
_Static_assert(sizeof(struct pc_trace_event)==40,"trace event ABI");
_Static_assert(sizeof(struct pc_trace_record)==48,"trace record ABI");
_Static_assert(sizeof(struct pc_trace_lane)==3136,"trace lane ABI");
/* Fresh zero region only, before the owner can execute. No reset/rearm API. */
int precapture_trace_initialize(struct pc_trace_lane *,const struct pc_trace_binding *);
/* Pure recording-capacity check only; never a native/task/feature admission. */
int precapture_trace_ready(const struct pc_trace_lane *);
/* One serialized native owner only. No allocation, timer, lock, IRQ masking,
 * wait, IPC, retry, overwrite, firmware/parameter write or resource release.
 * busy detects nested calls AFTER entry; it does not serialize multiple CPUs.
 */
int precapture_trace_append(struct pc_trace_lane *,u32 owner,const struct pc_trace_event *);
/* Owner-local recording stop. This is NOT sensor stop, global quiescence,
 * backing-resource completion or permission to unload the observer.
 */
int precapture_trace_freeze(struct pc_trace_lane *,u32 owner);
/* Uninstalled CP binding, separately compiled only for ARM32. The wrapper
 * calls original get_tid with output initialized0. after_task takes explicit
 * test metadata; calling it alone is not proof a native query succeeded.
 */
int precapture_trace_native_event(struct pc_trace_lane *,const struct pc_trace_event *);
int precapture_trace_after_task(struct pc_trace_lane *,const struct pc_trace_event *,int status,u32 task);
/* Native recording prototypes, still uninstalled. Clock samples are raw0
 * counter values, not calibrated exposure intervals. No camera-wide epoch or
 * frame identity is invented. Pool observation covers metadata indices ONLY.
 */
int precapture_trace_native_edge(struct pc_trace_lane *,u32 kind,u32 native_context);
int precapture_trace_native_pool(struct pc_trace_lane *);
int precapture_trace_pool_after_task(struct pc_trace_lane *,u32 task,int status,u32 clock_raw);
#endif
