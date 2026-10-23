/* Offline isolated-child component. Never call from an AP loader/service.
 * It opens its own UIPC context AFTER exec and only allocates/cancels one
 * wait0 message. It cannot send an RPC, capture command or firmware write.
 * Source/kernel/device and real isolated-process admission are caller duties.
 */
#ifndef PRECAPTURE_AP_IPC_CONTEXT_H
#define PRECAPTURE_AP_IPC_CONTEXT_H
#include "ap_linux_aarch64.h"
#include "ap_probe_once.h"

enum ipc_context_phase {
    IPC_PATH_STAT=1,IPC_OPEN,IPC_FD_STAT,IPC_QUERY,IPC_MAP,IPC_ALLOC_CANCEL,
    IPC_UNMAP,IPC_CLOSE,IPC_COMPLETE,IPC_REJECTED,IPC_UNCERTAIN,IPC_RPC
};
enum ipc_context_ownership { IPC_OWN_NONE,IPC_OWN_FD,IPC_OWN_MAPPING,IPC_OWN_UNKNOWN };
struct ipc_context_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 nonce,stat_attempts,open_attempts,query_attempts;
    probe_u32 map_attempts,unmap_attempts,close_attempts,reserved;
    probe_i64 descriptor,path_stat_status,open_status,fd_stat_status;
    probe_i64 query_status,map_status,unmap_status,close_status;
    probe_u64 device,inode,rdev,shared_begin,shared_bytes;
    probe_u32 info[4]; /* native opaque user queue ID at3; not a PID */
    probe_i64 return_status;
    struct probe_result probe;
};
struct ipc_context_workspace { probe_u8 path_stat[128],fd_stat[128]; };

/* A zeroed result is consumed once; serialized use in a verified child only.
 * Workspace/result must be disjoint. All shared-buffer ownership stays in
 * the nested one-shot cancel component. UNKNOWN retains map/FD/process:
 * do not exit, retry, kill, unmap or close it based on a host deadline.
 * Native calls may block despite the bounded call count. No live entry or
 * durable launcher/result writer is supplied here.
 */
int precapture_ipc_context_cancel_once(volatile struct ipc_context_result *,
    struct ipc_context_workspace *,probe_u32 nonce,ap_a64_syscall,probe_ioctl);

#endif
