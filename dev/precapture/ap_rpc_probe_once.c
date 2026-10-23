#include "ap_rpc_probe_once.h"
#include "ap_binding_guard.h"
#define ROUTE 0x908f084bu
#define ALLOCATE 0x8000000aull
#define SYNC 0x80000005ull
#define RELEASE 0x8000000bull
struct native_request { probe_u32 route,pad;probe_u64 argument; };
struct allocation_request { probe_u64 output;probe_u32 bytes,wait; };
struct sync_request { probe_u64 message,callback,context; };
_Static_assert(sizeof(struct sync_request)==24,"native sync request ABI");
_Static_assert(sizeof(struct rpc_probe_result)==112,"RPC result ABI");
static probe_u32 get32(const probe_u8*p){return p[0]|(probe_u32)p[1]<<8|(probe_u32)p[2]<<16|(probe_u32)p[3]<<24;}
static void put32(probe_u8*p,probe_u32 v){p[0]=v;p[1]=v>>8;p[2]=v>>16;p[3]=v>>24;}
static int fresh(volatile struct rpc_probe_result*r){
    const volatile probe_u8*p=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(p[i])return 0;return 1;
}
static int uncertain(volatile struct rpc_probe_result*r){r->ownership=RPC_OWN_UNKNOWN;r->phase=RPC_UNCERTAIN;return -5;}
static int release_once(const struct probe_binding*b,volatile struct rpc_probe_result*r,
    probe_ioctl invoke,probe_u32 terminal){
    struct native_request request={ROUTE,0,r->message};
    r->phase=RPC_RELEASING;r->release_attempts=1;
    r->release_status=invoke(b->descriptor,RELEASE,&request);
    if(r->release_status)return uncertain(r);
    r->ownership=RPC_OWN_NONE;r->phase=terminal;return 0;
}
int precapture_rpc_probe_guarded_once(const struct probe_binding*b,volatile struct rpc_probe_result*r,
    probe_u32 nonce,probe_u32 source,probe_ioctl invoke,probe_rpc_gate gate,void*gate_context){
    if(!invoke||!gate||!gate_context||!nonce||!precapture_own_queue_id(source)||
       !precapture_private_binding(b,r,sizeof(*r)))return -22;
    if(!fresh(r))return -16;
    r->magic=0x31504352u;r->version=4;r->nonce=nonce;r->source=source;
    r->allocation_status=r->rpc_status=r->release_status=-1;
    r->phase=RPC_GUARDING;r->gate_calls=1;
    r->gate_status=gate(RPC_GATE_BEFORE_ALLOC,gate_context);
    if(r->gate_status){r->phase=RPC_REJECTED;return -95;}
    r->phase=RPC_ALLOCATING;r->allocation_attempts=1;
    probe_u64 message=0;
    struct allocation_request allocation={(probe_u64)(probe_uptr)&message,24,0};
    struct native_request request={ROUTE,0,(probe_u64)(probe_uptr)&allocation};
    probe_i64 result=invoke(b->descriptor,ALLOCATE,&request);
    r->allocation_status=result;r->message=message;
    if(result){
        if(!message&&(result==-22||result==-1021||result==-1023||result==-1024)){
            r->ownership=RPC_OWN_NONE;r->phase=RPC_REJECTED;return -5;
        }return uncertain(r);
    }
    if((message&63u)||message<b->shared_begin+64||message>b->shared_begin+b->shared_bytes-28)return uncertain(r);
    probe_u8*p=(probe_u8*)(probe_uptr)message;
    if(p[-16]!=2||p[-15]!=0x41||p[-14]!=1||p[-13]||get32(p-12)!=0xa5a5a5a5u||
       get32(p-8)!=24||get32(p-4)!=0x55555555u||get32(p+24)!=0x77777777u)return uncertain(r);
    r->ownership=RPC_OWN_CALLER;r->phase=RPC_ALLOCATED;
    /* Recheck after the allocator and BEFORE writing request/source bytes.
     * A refused second gate still owns an untouched, never-sent allocation;
     * cancel that allocation once, without entering the synchronous sender.
     */
    r->gate_calls=2;r->gate_status=gate(RPC_GATE_BEFORE_SEND,gate_context);
    if(r->gate_status){
        if(release_once(b,r,invoke,RPC_REJECTED))return -5;
        return -95;
    }
    for(probe_u32 i=0;i<24;i++)p[i]=0;
    p[0]=0xe1;put32(p+20,nonce);
    /* Same displacement as original osal_set_msg_src. Source provenance
     * belongs to the future context adapter; structural checks cannot prove
     * it. All other allocator metadata, including payload-4, is preserved.
     */
    put32(p-12,source);
    struct sync_request sync={message,0,0};
    request.argument=(probe_u64)(probe_uptr)&sync;
    r->ownership=RPC_OWN_IN_FLIGHT;r->phase=RPC_WAITING;r->rpc_attempts=1;
    result=invoke(b->descriptor,SYNC,&request);
    r->rpc_status=result;r->callback=sync.callback;r->callback_context=sync.context;
    if(result||sync.message!=message||sync.callback||sync.context)return uncertain(r);
    /* A zero native return alone does not prove remote receipt/ownership.
     * Only the exact original unsupported-mode response qualifies here.
     * Keep the mapping/process on any other reply; never free it on a guess.
     */
    r->response_status=p[1];r->nonce_echo=get32(p+8);r->tail_nonce=get32(p+20);
    r->processor_state=get32(p+16);
    int qualified=p[0]==0xe1&&p[1]==0x80&&r->tail_nonce==nonce;
    for(probe_u32 i=2;i<20;i++)if(p[i])qualified=0;
    if(!qualified){r->reply_kind=RPC_REPLY_UNEXPECTED;return uncertain(r);}
    r->reply_kind=RPC_ORIGINAL_DEFAULT_REPLY;r->ownership=RPC_OWN_CALLER;r->phase=RPC_RETURNED;
    /* No response word is interpreted as a memory address or length.
     * Word12 remains validation-only and is never copied to a result field. */
    if(release_once(b,r,invoke,RPC_DONE))return -5;
    return 0;
}
int precapture_rpc_probe_once(const struct probe_binding*b,volatile struct rpc_probe_result*r,
    probe_u32 nonce,probe_u32 source,probe_ioctl invoke){
    (void)b;(void)r;(void)nonce;(void)source;(void)invoke;
    return -95;
}
