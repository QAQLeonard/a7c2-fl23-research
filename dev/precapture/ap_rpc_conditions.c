#include "ap_rpc_conditions.h"
#include "ap_binding_guard.h"
#define CATCHABLE (~((1ull<<8)|(1ull<<18)))
#define KTHREAD_FLAG 0x00200000u
_Static_assert(sizeof(struct rpc_conditions_expected)==32,"expected ABI");
_Static_assert(sizeof(struct rpc_condition_sample)==104,"sample ABI");
_Static_assert(sizeof(struct rpc_conditions_result)==256,"condition ABI");
_Static_assert(sizeof(struct rpc_conditions_workspace)==688,"workspace ABI");

static probe_i64 call(struct rpc_conditions_gate *g,probe_i64 n,probe_i64 a,
    probe_i64 b,probe_i64 c,probe_i64 d){
    g->result->syscalls++;
    return g->result->last_status=g->syscall(n,a,b,c,d,0,0);
}
static probe_u64 word(const probe_u8 *p,probe_u32 count){
    probe_u64 v=0;for(probe_u32 i=0;i<count;i++)v|=(probe_u64)p[i]<<(8*i);return v;
}
static int same(const probe_u8 *p,probe_u32 n,const char *s){
    probe_u32 i=0;while(s[i]){if(i>=n||p[i]!=(probe_u8)s[i])return 0;i++;}return i==n;
}
static void path(struct rpc_conditions_gate *g,const char *tail){
    char *out=g->workspace->path;const char *prefix="/proc/";
    probe_u32 at=0,n=0,pid=g->expected->worker;char digits[10];
    while(prefix[at]){out[at]=prefix[at];at++;}
    do{digits[n++]='0'+pid%10;pid/=10;}while(pid);
    while(n)out[at++]=digits[--n];out[at++]='/';
    for(probe_u32 i=0;tail[i];i++)out[at++]=tail[i];out[at]=0;
}
/* Each file is opened once, read with a finite bound and closed once. No
 * close retry; a failed close or impossible descriptor remains UNKNOWN. */
static int read_file(struct rpc_conditions_gate *g,const char *name,probe_u32 *used){
    volatile struct rpc_conditions_result *r=g->result;
    struct rpc_conditions_workspace *w=g->workspace;
    *used=0;r->file_reads++;
    probe_i64 fd=call(g,AP_A64_SYS_OPENAT,-100,(probe_i64)name,AP_A64_OPEN_READ,0);
    if(fd<0)return fd < -4095 ? RPC_GATE_UNKNOWN_STATUS : (int)fd;
    r->pending_fd=fd;
    if(fd>0x7fffffff)return RPC_GATE_UNKNOWN_STATUS;
    int status=-5;
    for(probe_u32 i=0;i<sizeof(w->stat);i++)w->stat[i]=0;
    if(call(g,AP_A64_SYS_FSTAT,fd,(probe_i64)w->stat,0,0)||
       (word(w->stat+16,4)&0xf000)!=0x8000)goto done;
    status=-75;
    for(probe_u32 i=0;i<64;i++){
        probe_u8 extra;
        probe_u32 remain=sizeof(w->text)-*used;
        probe_i64 n=call(g,63,fd,(probe_i64)(remain?w->text+*used:&extra),remain?remain:1,0);
        if(n<0){status=n>=-4095?(int)n:-5;break;}
        if(!n){status=0;break;}
        if(!remain||(probe_u64)n>remain)break;
        *used+=(probe_u32)n;
    }
done:
    if(call(g,AP_A64_SYS_CLOSE,fd,0,0,0))return RPC_GATE_UNKNOWN_STATUS;
    r->pending_fd=-1;return status;
}
static int number(const probe_u8 **at,const probe_u8 *end,probe_u64 *out,int *negative){
    const probe_u8 *p=*at;probe_u64 v=0;*negative=0;
    if(p<end&&*p=='-'){*negative=1;p++;}
    if(p==end||*p<'0'||*p>'9')return 0;
    do{probe_u32 d=*p-'0';if(v>(~0ull-d)/10)return 0;v=v*10+d;p++;}
    while(p<end&&*p>='0'&&*p<='9');
    *at=p;*out=v;return 1;
}
static int stat_identity(struct rpc_conditions_gate *g,probe_u32 n,probe_u64 *start,probe_u32 *flags){
    const probe_u8 *p=g->workspace->text,*end=p+n;probe_u64 value;int negative;
    if(!number(&p,end,&value,&negative)||negative||value!=g->expected->worker)return 0;
    const char *prefix=" (pcieif_esynsnd) ";
    for(probe_u32 i=0;prefix[i];i++){if(p==end||*p++!=(probe_u8)prefix[i])return 0;}
    if(p==end||(*p!='D'&&*p!='S'&&*p!='R'))return 0;p++;
    probe_u32 field=4;*start=0;*flags=0;
    while(p<end&&*p==' '&&field<=64){
        p++;if(!number(&p,end,&value,&negative))return 0;
        if(field==9){if(negative||value>0xffffffffu)return 0;*flags=(probe_u32)value;}
        if(field==22){if(negative||!value)return 0;*start=value;}
        field++;
    }
    return field>22&&p+1==end&&*p=='\n'&&*start==g->expected->worker_start&&(*flags&KTHREAD_FLAG);
}
static int self_conditions(struct rpc_conditions_gate *g,volatile struct rpc_condition_sample *s){
    const struct rpc_conditions_expected *e=g->expected;
    s->reason=RPC_CONDITION_SELF;
    probe_i64 pid=call(g,172,0,0,0,0),parent=call(g,173,0,0,0,0);
    if(pid!=e->self||parent!=e->parent)return -95;
    s->self=(probe_u32)pid;s->parent=(probe_u32)parent;s->reason=RPC_CONDITION_SELF_POLICY;
    s->policy=call(g,120,0,0,0,0);probe_i32 priority=-1;
    if(s->policy||call(g,121,0,(probe_i64)&priority,0,0)||priority)return -95;
    s->priority=priority;s->reason=RPC_CONDITION_CPU;
    probe_u64 mask=0;
    if(call(g,123,0,8,(probe_i64)&mask,0)!=8||mask!=(1ull<<e->CPU))return -95;
    s->affinity=mask;probe_u32 CPU=~0u;
    if(call(g,168,(probe_i64)&CPU,0,0,0)||CPU!=e->CPU)return -95;
    s->CPU=CPU;s->reason=RPC_CONDITION_SIGNALS;probe_u64 signals=0;
    /* set=NULL: queries only, never changes a signal mask. */
    if(call(g,135,0,0,(probe_i64)&signals,8)||signals!=CATCHABLE)return -95;
    s->signals=signals;return 0;
}
static int descriptor_identity(struct rpc_conditions_gate *g,volatile struct rpc_condition_sample *s){
    volatile struct ipc_context_result *c=&g->context->context;
    probe_u8 *raw=g->workspace->stat;s->reason=RPC_CONDITION_DESCRIPTOR;
    for(probe_u32 i=0;i<128;i++)raw[i]=0;
    /* A lost/replaced descriptor invalidates ownership; do not guess that
     * closing its number would still close this context's original file. */
    if(call(g,AP_A64_SYS_FSTAT,c->descriptor,(probe_i64)raw,0,0)||
       (word(raw+16,4)&0xf000)!=0x2000||word(raw,8)!=c->device||
       word(raw+8,8)!=c->inode||word(raw+32,8)!=c->rdev)return RPC_GATE_UNKNOWN_STATUS;
    return 0;
}
static int collect(struct rpc_conditions_gate *g,volatile struct rpc_condition_sample *s){
    if(descriptor_identity(g,s))return RPC_GATE_UNKNOWN_STATUS;
    if(self_conditions(g,s))return -95;
    probe_u32 used=0,flags=0;probe_u64 before=0,after=0;int status;
    s->reason=RPC_CONDITION_WORKER_STAT;path(g,"stat");
    status=read_file(g,g->workspace->path,&used);if(status)return status;
    if(!stat_identity(g,used,&before,&flags))return -95;
    s->worker_start_before=before;s->worker_flags=flags;
    s->reason=RPC_CONDITION_WORKER_NAME;path(g,"comm");
    status=read_file(g,g->workspace->path,&used);if(status)return status;
    if(!same(g->workspace->text,used,"pcieif_esynsnd\n"))return -95;
    s->reason=RPC_CONDITION_WORKER_POLICY;
    s->worker_policy=call(g,120,g->expected->worker,0,0,0);
    if(s->worker_policy!=1)return -95;
    s->reason=RPC_CONDITION_WORKER_PRIORITY;probe_i32 priority=-1;
    if(call(g,121,g->expected->worker,(probe_i64)&priority,0,0)||priority!=148)return -95;
    s->worker_priority=priority;s->reason=RPC_CONDITION_WORKER_MASK;probe_u64 mask=0;
    if(call(g,123,g->expected->worker,8,(probe_i64)&mask,0)!=8||mask!=(1ull<<g->expected->CPU))return -95;
    s->worker_affinity=mask;s->reason=RPC_CONDITION_WORKER_STAT;path(g,"stat");
    status=read_file(g,g->workspace->path,&used);if(status)return status;
    if(!stat_identity(g,used,&after,&flags)||after!=before||flags!=s->worker_flags)return -95;
    s->worker_start_after=after;s->reason=RPC_CONDITION_RT_RUNTIME;
    status=read_file(g,"/proc/sys/kernel/sched_rt_runtime_us",&used);if(status)return status;
    if(!same(g->workspace->text,used,"-1\n"))return -95;s->rt_runtime=-1;
    s->reason=RPC_CONDITION_RT_PERIOD;
    status=read_file(g,"/proc/sys/kernel/sched_rt_period_us",&used);if(status)return status;
    if(!same(g->workspace->text,used,"1000000\n"))return -95;s->rt_period=1000000;
    s->reason=RPC_CONDITION_RECHECK;
    struct rpc_condition_sample again={0};
    if(self_conditions(g,&again))return -95;
    if(descriptor_identity(g,s))return RPC_GATE_UNKNOWN_STATUS;
    s->matches=1;s->reason=RPC_CONDITION_NONE;return 0;
}
probe_i32 precapture_rpc_conditions_sample_stage(struct rpc_conditions_gate *g,probe_u32 stage){
    probe_u64 gp=(probe_u64)(probe_uptr)g;
    if(!g||gp+sizeof(*g)<=gp)return -22;
    if(!g->expected||!g->result||!g->workspace||!g->context||!g->syscall||
       (stage!=RPC_GATE_BEFORE_ALLOC&&stage!=RPC_GATE_BEFORE_SEND))return -22;
    const struct rpc_conditions_expected *e=g->expected;
    volatile struct rpc_context_result *c=g->context;
    volatile struct rpc_conditions_result *r=g->result;
    const volatile void *regions[]={g,e,r,g->workspace,c};
    probe_u64 sizes[]={sizeof(*g),sizeof(*e),sizeof(*r),sizeof(*g->workspace),sizeof(*c)};
    for(probe_u32 i=0;i<5;i++){
        probe_u64 p=(probe_u64)(probe_uptr)regions[i];
        if(p+sizes[i]<=p)return -22;
        for(probe_u32 j=0;j<i;j++)if(!precapture_spans_disjoint(regions[i],sizes[i],regions[j],sizes[j]))return -22;
    }
    if(!e->self||e->self>0x7fffffff||!e->parent||e->parent>0x7fffffff||
       !e->worker||e->worker>0x7fffffff||e->self==e->parent||e->worker==e->self||e->worker==e->parent||
       e->CPU>=64||!e->worker_start||e->reserved[0]||e->reserved[1]||
       c->context.descriptor<0||c->context.descriptor>0x7fffffff||c->context.version!=2||
       c->context.reserved!=1||c->context.phase!=IPC_RPC||c->context.ownership!=IPC_OWN_MAPPING||
       c->context.info[0]!=0x200000||c->context.info[1]!=0x80000||c->context.info[2]!=0x20000||
       !precapture_own_queue_id(c->context.info[3])||c->rpc.source!=c->context.info[3]||
       !c->context.nonce||c->context.nonce!=c->rpc.nonce||c->rpc.version!=4||c->rpc.gate_calls!=stage||
       c->rpc.phase!=(stage==1?RPC_GUARDING:RPC_ALLOCATED))return -22;
    struct probe_binding b={(probe_i32)c->context.descriptor,0,c->context.shared_begin,c->context.shared_bytes};
    for(probe_u32 i=0;i<5;i++){
        if(!precapture_private_binding(&b,regions[i],sizes[i]))return -22;
    }
    if(stage==1){
        const volatile probe_u8 *raw=(const volatile probe_u8 *)r;
        /* A consumed record may retain an earlier gate descriptor. Reject
         * without overwriting it or assuming that ownership was resolved. */
        for(probe_u32 i=0;i<sizeof(*r);i++)if(raw[i])return RPC_GATE_UNKNOWN_STATUS;
        r->magic=0x31434752u;r->version=1;r->pending_fd=-1;
    }else if(r->magic!=0x31434752u||r->version!=1||r->calls!=1||r->phase!=RPC_CONDITIONS_CHECKED||
        r->status||r->pending_fd!=-1||!r->samples[0].matches)return RPC_GATE_UNKNOWN_STATUS;
    r->calls=stage;r->phase=RPC_CONDITIONS_READING;
    volatile struct rpc_condition_sample *s=&r->samples[stage-1];
    int status=collect(g,s);r->status=status;
    if(status==RPC_GATE_UNKNOWN_STATUS||r->pending_fd!=-1){
        r->phase=RPC_CONDITIONS_UNKNOWN;return RPC_GATE_UNKNOWN_STATUS;
    }
    if(status){r->phase=RPC_CONDITIONS_DENIED;return -95;}
    r->phase=RPC_CONDITIONS_CHECKED;return 0;
}
probe_i32 precapture_rpc_conditions_gate(probe_u32 stage,void *context){
    struct rpc_conditions_gate *g=context;
    int status=precapture_rpc_conditions_sample_stage(g,stage);
    if(status||stage==RPC_GATE_BEFORE_ALLOC)return status;
    /* Necessary scheduling samples are not a loaded-text or callback lifetime
     * contract. Keep the actual sender unreachable regardless of the sample. */
    volatile struct rpc_conditions_result *r=g->result;
    r->samples[stage-1].reason=RPC_CONDITION_LIFETIME_UNQUALIFIED;r->status=-95;
    r->phase=RPC_CONDITIONS_DENIED;return -95;
}
