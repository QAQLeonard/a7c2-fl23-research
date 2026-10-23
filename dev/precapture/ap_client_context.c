#include "ap_client_context.h"
_Static_assert(sizeof(struct client_context_result)==536,"composed result ABI");
static int unresolved(volatile struct client_context_result*r){
    r->phase=CLIENT_CONTEXT_UNKNOWN;r->status=-5;return -5;
}
int precapture_client_context_cancel_once(volatile struct client_context_result*r,
    struct ipc_context_workspace*w,probe_u32 parent,probe_u32 CPU,probe_u32 nonce,
    ap_a64_syscall sc,probe_ioctl ioctl){
    if(!r||!w||!sc||!ioctl||!parent||parent>0x7fffffff||CPU>=64||!nonce)return -22;
    probe_u64 rb=(probe_u64)(probe_uptr)r,wb=(probe_u64)(probe_uptr)w;
    if(rb+sizeof(*r)<=rb||wb+sizeof(*w)<=wb||
       (rb<wb+sizeof(*w)&&wb<rb+sizeof(*r)))return -22;
    const volatile probe_u8*raw=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(raw[i])return -16;
    r->magic=0x31584343u;r->version=1;r->phase=CLIENT_CONTEXT_GROUP;r->status=-1;
    int status=precapture_client_cpuset_enter(&r->group,parent,CPU,sc);
    if(status){
        if(r->group.ownership)return unresolved(r);
        r->phase=CLIENT_CONTEXT_REJECTED;r->status=status;return status;
    }
    r->phase=CLIENT_CONTEXT_BIND;
    status=precapture_client_bind_once(&r->binding,parent,CPU,sc);
    if(status){if(r->binding.ownership)return unresolved(r);}
    else{
        r->phase=CLIENT_CONTEXT_OPEN;
        status=precapture_ipc_context_cancel_once(&r->context,w,nonce,sc,ioctl);
        if(r->context.ownership||r->context.probe.send_attempts)return unresolved(r);
        r->phase=CLIENT_CONTEXT_UNBIND;
        if(precapture_client_unbind_once(&r->binding,sc))return unresolved(r);
    }
    r->phase=CLIENT_CONTEXT_UNGROUP;
    if(precapture_client_cpuset_leave(&r->group,sc))return unresolved(r);
    r->status=status;r->phase=status?CLIENT_CONTEXT_REJECTED:CLIENT_CONTEXT_DONE;
    return status;
}
