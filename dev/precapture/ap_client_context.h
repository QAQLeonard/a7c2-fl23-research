/* Offline composition for an isolated diagnostic child, never an AP loader.
 * Own cpuset -> own signal/affinity guard -> fresh NEVER-SENT context ->
 * inverse guards. This API cannot send a CP request.
 */
#ifndef PRECAPTURE_AP_CLIENT_CONTEXT_H
#define PRECAPTURE_AP_CLIENT_CONTEXT_H
#include "ap_client_cpuset.h"
#include "ap_ipc_context.h"
enum client_context_phase { CLIENT_CONTEXT_GROUP=1,CLIENT_CONTEXT_BIND,
    CLIENT_CONTEXT_OPEN,CLIENT_CONTEXT_UNBIND,CLIENT_CONTEXT_UNGROUP,
    CLIENT_CONTEXT_DONE,CLIENT_CONTEXT_REJECTED,CLIENT_CONTEXT_UNKNOWN };
struct client_context_result {
    probe_u32 magic,version,phase;probe_i32 status;
    struct client_cpuset_result group;
    struct client_binding_result binding;
    struct ipc_context_result context;
};
/* Fresh zeroed result; no inverse follows unknown nested ownership. The
 * private wrapper must preserve that child and its journal, not exit/retry.
 * File/source/CPU/worker provenance remains a separate admission duty.
 */
int precapture_client_context_cancel_once(volatile struct client_context_result *,
    struct ipc_context_workspace *,probe_u32 parent,probe_u32 CPU,probe_u32 nonce,
    ap_a64_syscall,probe_ioctl);
#endif
