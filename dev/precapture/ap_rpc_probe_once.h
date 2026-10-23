/* Offline RPC component; NEVER call from the AP service's loader/init.
 * Synchronous kernel RPC can wait indefinitely. A future adapter needs an
 * isolated lifetime-tracked process, fresh body/source/FD/mapping binding,
 * serialized access and durable job fencing. source must come from that
 * context's independently verified native binding, never a donor constant
 * or allocator sentinel. ap_rpc_context.c supplies an OFFLINE fresh-context
 * composition; no live gate, physical launcher or install is supplied.
 */
#ifndef PRECAPTURE_AP_RPC_PROBE_H
#define PRECAPTURE_AP_RPC_PROBE_H
#include "ap_probe_once.h"
enum rpc_probe_phase { RPC_ALLOCATING=1, RPC_ALLOCATED, RPC_WAITING, RPC_RETURNED,
    RPC_RELEASING, RPC_DONE, RPC_REJECTED, RPC_UNCERTAIN, RPC_GUARDING };
/* PRESENT is a historical model value; v4 accepts only original default replies. */
enum rpc_reply_kind { RPC_REPLY_NONE, RPC_OBSERVER_ABSENT, RPC_OBSERVER_PRESENT, RPC_REPLY_UNEXPECTED,
    RPC_ORIGINAL_DEFAULT_REPLY=RPC_OBSERVER_ABSENT };
enum rpc_probe_ownership { RPC_OWN_NONE, RPC_OWN_CALLER, RPC_OWN_IN_FLIGHT, RPC_OWN_UNKNOWN };
struct rpc_probe_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 nonce,allocation_attempts,rpc_attempts,release_attempts;
    probe_i64 allocation_status,rpc_status,release_status;
    probe_u64 message,callback,callback_context;
    probe_u32 response_status,nonce_echo,tail_nonce,processor_state;
    probe_u32 reply_kind,source,gate_calls;probe_i32 gate_status;
};
enum rpc_gate_stage { RPC_GATE_BEFORE_ALLOC=1, RPC_GATE_BEFORE_SEND };
/* A gate with unresolved resources must retain the whole child/context.
 * Distinguish it from a known refusal with no remaining gate ownership. */
enum { RPC_GATE_UNKNOWN_STATUS=-117 };
/* Zero means the separately qualified conditions still hold. A known nonzero
 * refusal has no unresolved gate resources. RPC_GATE_UNKNOWN_STATUS instead
 * retains the whole context, even before allocation. This interface alone
 * is NOT source/CPU/scheduler/lifetime admission. ap_rpc_conditions.c checks
 * native necessary conditions but ALWAYS denies stage2; no sender admitted.
 */
typedef probe_i32 (*probe_rpc_gate)(probe_u32 stage,void *context);
int precapture_rpc_probe_guarded_once(const struct probe_binding *,volatile struct rpc_probe_result *,
    probe_u32 nonce,probe_u32 source,probe_ioctl,probe_rpc_gate,void *gate_context);
/* Retired unguarded ABI: returns-95 before touching state or issuing I/O. */
int precapture_rpc_probe_once(const struct probe_binding *,volatile struct rpc_probe_result *,
                             probe_u32 nonce,probe_u32 source,probe_ioctl);
#endif
