#include "ap_ipc_transport.h"

int precapture_ipc_context_cancel_once(volatile struct ipc_context_result *r,
    struct ipc_context_workspace *workspace,probe_u32 nonce,ap_a64_syscall sc,probe_ioctl invoke){
    if(!r||!workspace||!nonce||!sc||!invoke)return -22;
    probe_u64 rb=(probe_u64)(probe_uptr)r,wb=(probe_u64)(probe_uptr)workspace;
    if(rb+sizeof(*r)<=rb||wb+sizeof(*workspace)<=wb||overlaps(rb,sizeof(*r),wb,sizeof(*workspace)))return -22;
    const volatile probe_u8 *raw=(const volatile probe_u8 *)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(raw[i])return -16;
    int status=ipc_transport_open(r,workspace,nonce,sc,invoke,sizeof(*r),1);
    if(status)return status;
    struct probe_binding binding={(probe_i32)r->descriptor,0,r->shared_begin,SHARED_BYTES};
    r->phase=IPC_ALLOC_CANCEL;
    status=precapture_probe_once(&binding,&r->probe,nonce,0,invoke);
    if(r->probe.ownership!=PROBE_NONE||r->probe.send_attempts)return unknown(r);
    if(r->probe.phase!=PROBE_RELEASED&&r->probe.phase!=PROBE_REJECTED)return unknown(r);
    return finish_mapping(r,status,sc);
}
