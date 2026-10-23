/* OFFLINE composition, no launcher or physical-send admission. An isolated,
 * lifetime-tracked caller must supply a separately qualified live gate.
 * Never call from AP initialization. See ap_rpc_probe_once.h for send risks.
 */
#ifndef PRECAPTURE_AP_RPC_CONTEXT_H
#define PRECAPTURE_AP_RPC_CONTEXT_H
#include "ap_ipc_context.h"
#include "ap_rpc_probe_once.h"

struct rpc_context_result {
    /* version2/reserved1 identify RPC: legacy probe.send_attempts is NOT
     * the send counter for this operation. Inspect rpc.rpc_attempts instead. */
    struct ipc_context_result context;
    struct rpc_probe_result rpc;
};
/* Complete result/workspace are fresh, disjoint private storage. Source is
 * derived solely from this fresh descriptor's info[3], never supplied by host.
 * UNKNOWN retains mapping/FD/process; no retry or deadline-based teardown.
 */
int precapture_rpc_context_once(volatile struct rpc_context_result *,
    struct ipc_context_workspace *,probe_u32 nonce,ap_a64_syscall,probe_ioctl,
    probe_rpc_gate,void *gate_context);
#endif
