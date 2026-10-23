/* Read-only necessary-condition checks for the native diagnostic route.
 * Still NOT a physical-send admission: stage2 ALWAYS refuses because loaded
 * source and callback lifetime remain unqualified. No enable/bypass flag.
 */
#ifndef PRECAPTURE_AP_RPC_CONDITIONS_H
#define PRECAPTURE_AP_RPC_CONDITIONS_H
#include "ap_rpc_context.h"

struct rpc_conditions_expected {
    probe_u32 self,parent,worker,CPU;
    probe_u64 worker_start;
    probe_u32 reserved[2];
};
enum rpc_condition_reason {
    RPC_CONDITION_NONE,RPC_CONDITION_SELF,RPC_CONDITION_CPU,
    RPC_CONDITION_SIGNALS,RPC_CONDITION_SELF_POLICY,RPC_CONDITION_WORKER_STAT,
    RPC_CONDITION_WORKER_NAME,RPC_CONDITION_WORKER_POLICY,
    RPC_CONDITION_WORKER_PRIORITY,RPC_CONDITION_WORKER_MASK,
    RPC_CONDITION_RT_RUNTIME,RPC_CONDITION_RT_PERIOD,
    RPC_CONDITION_RECHECK,RPC_CONDITION_LIFETIME_UNQUALIFIED,RPC_CONDITION_DESCRIPTOR
};
struct rpc_condition_sample {
    probe_u32 self,parent,CPU;probe_i32 priority;
    probe_i64 policy;
    probe_u64 affinity,signals;
    probe_i64 worker_policy;
    probe_i32 worker_priority;probe_u32 worker_flags;
    probe_u64 worker_affinity,worker_start_before,worker_start_after;
    probe_i64 rt_runtime;probe_u64 rt_period;
    probe_u32 matches,reason;
};
enum rpc_condition_phase { RPC_CONDITIONS_READING=1,RPC_CONDITIONS_CHECKED,
    RPC_CONDITIONS_DENIED,RPC_CONDITIONS_UNKNOWN };
struct rpc_conditions_result {
    probe_u32 magic,version,calls,phase;
    probe_i64 status,last_status,pending_fd;
    probe_u32 file_reads,syscalls;
    struct rpc_condition_sample samples[2];
};
struct rpc_conditions_workspace { probe_u8 stat[128],text[512];char path[48]; };
struct rpc_conditions_gate {
    const struct rpc_conditions_expected *expected;
    volatile struct rpc_conditions_result *result;
    struct rpc_conditions_workspace *workspace;
    volatile struct rpc_context_result *context;
    ap_a64_syscall syscall;
};
/* Zeroed result consumed once over ordered stages1/2 in the same private
 * child. All five regions must be private/disjoint/outside the UIPC map.
 * RPC_GATE_UNKNOWN_STATUS retains map/message/FD/process; pending_fd and
 * the component result must remain available to the durable caller.
 * Worker PID/starttime are fresh admission inputs, not constants from logs.
 */
probe_i32 precapture_rpc_conditions_gate(probe_u32 stage,void *context);
#endif
