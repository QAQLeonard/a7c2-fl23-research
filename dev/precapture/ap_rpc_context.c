#include "ap_rpc_context.h"
#include "ap_ipc_transport.h"
#include "ap_binding_guard.h"
_Static_assert(sizeof(struct rpc_context_result)==360,"RPC context ABI");

int precapture_rpc_context_once(volatile struct rpc_context_result *r,
    struct ipc_context_workspace *w,probe_u32 nonce,ap_a64_syscall sc,probe_ioctl invoke,
    probe_rpc_gate gate,void *gate_context){
    if(!r||!w||!nonce||!sc||!invoke||!gate||!gate_context||
       !precapture_spans_disjoint(r,sizeof(*r),w,sizeof(*w)))return -22;
    const volatile probe_u8 *raw=(const volatile probe_u8 *)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(raw[i])return -16;
    volatile struct ipc_context_result *c=&r->context;
    c->reserved=1;
    int status=ipc_transport_open(c,w,nonce,sc,invoke,sizeof(*r),2);
    /* Even early rejections identify the operation; never infer no-send from
     * the unused legacy nested probe alone. */
    if(status)return status;
    if(!precapture_own_queue_id(c->info[3]))return finish_mapping(c,-84,sc);
    struct probe_binding binding={(probe_i32)c->descriptor,0,c->shared_begin,c->shared_bytes};
    if(!precapture_private_binding(&binding,r,sizeof(*r)))return unknown(c);
    c->phase=IPC_RPC;
    status=precapture_rpc_probe_guarded_once(&binding,&r->rpc,nonce,c->info[3],invoke,gate,gate_context);
    if(r->rpc.ownership!=RPC_OWN_NONE||
       (r->rpc.phase!=RPC_DONE&&r->rpc.phase!=RPC_REJECTED))return unknown(c);
    return finish_mapping(c,status,sc);
}
