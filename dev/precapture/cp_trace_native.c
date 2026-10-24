/* Uninstalled ARM32 owner binding. No patch, loader, task migration or IPC.
 * Lane allocation/initialization, actual hook task context and IRQ exclusion
 * remain external native admission requirements; a matching task ID alone
 * cannot prove them. No timer/MMIO or arbitrary pool memory is read here.
 */
#include "cp_trace.h"
typedef __UINTPTR_TYPE__ trace_native_ptr;
_Static_assert(sizeof(void *)==4,"Native CP owner binding requires ARM32");

int precapture_trace_after_task(struct pc_trace_lane *p,
    const struct pc_trace_event *e,int status,u32 task) {
    if(status||!p||((trace_native_ptr)p&3u)||!task||task!=p->owner)return -1;
    return precapture_trace_append(p,task,e);
}
int precapture_trace_native_event(struct pc_trace_lane *p,const struct pc_trace_event *e) {
    int (*get_task)(u32 *)=(void *)(trace_native_ptr)0x5f1f24u;
    u32 task=0;
    if(!precapture_trace_ready(p)||!e||((trace_native_ptr)e&3u)||p->owner>279u)
        return -22;
    int status=get_task(&task);
    return precapture_trace_after_task(p,e,status,task);
}

static int lane_owner(const struct pc_trace_lane *p) {
    return precapture_trace_ready(p)&&p->owner<=279u&&p->clock_domain==1;
}
static void event_zero(struct pc_trace_event *e) {
    volatile u32 *words=(volatile u32 *)e;
    for(u32 i=0;i<sizeof(*e)/sizeof(u32);i++)words[i]=0;
}
int precapture_trace_native_edge(struct pc_trace_lane *p,u32 kind,u32 native_context) {
    int (*get_task)(u32 *)=(void *)(trace_native_ptr)0x5f1f24u;
    u32 (*clock0)(u32)=(void *)(trace_native_ptr)0x7a7489u;
    if(!lane_owner(p)||(kind!=PC_EXPOSURE_BEGIN&&kind!=PC_EXPOSURE_END&&kind!=PC_S2))return -22;
    u32 task=0;int status=get_task(&task);
    if(status||!task||task!=p->owner)return -1;
    struct pc_trace_event event;event_zero(&event);event.kind=kind;event.context_raw=native_context;
    /* This extra original counter read is NOT deployed/admitted by compiling
     * this source. Native hardware/task/callback timing still need review.
     */
    event.clock_raw=clock0(0);
    return precapture_trace_append(p,task,&event);
}

int precapture_trace_pool_after_task(struct pc_trace_lane *p,u32 task,int status,u32 clock_raw) {
    if(!lane_owner(p)||p->owner!=256u)return -22;
    if(status||task!=256u)return -1;
    const volatile u32 *binding=(const volatile u32 *)(trace_native_ptr)0x1a8c558u;
    /* Derivations are checked against b13994/b16314/b14220 original source.
     * No wire-selected pointer or walking into advertised pixel extents.
     */
    u32 pool=binding[0],head_pointer=binding[1],tail_pointer=binding[2],count_pointer=binding[3];
    if(pool!=0x22a4760u||head_pointer!=0x22b4720u||tail_pointer!=0x22b4728u||
       count_pointer!=0x22b4730u)return -95;
    const volatile u32 *head=(const volatile u32 *)(trace_native_ptr)0x22b4720u;
    const volatile u32 *tail=(const volatile u32 *)(trace_native_ptr)0x22b4728u;
    const volatile u32 *count=(const volatile u32 *)(trace_native_ptr)0x22b4730u;
    u32 h=*head,t=*tail,n=*count;
    if(h>1023u||t>1023u||n>1023u||((t-h)&1023u)!=n)return -84;
    /* Rechecks detect selected drift; no ABA/IRQ/global consistency claim. */
    if(binding[0]!=pool||binding[1]!=head_pointer||binding[2]!=tail_pointer||
       binding[3]!=count_pointer||*head!=h||*tail!=t||*count!=n)return -116;
    struct pc_trace_event event;event_zero(&event);event.kind=PC_POOL;event.clock_raw=clock_raw;
    event.detail[0]=h;event.detail[1]=t;event.detail[2]=n;event.detail[3]=pool;
    return precapture_trace_append(p,task,&event);
}
int precapture_trace_native_pool(struct pc_trace_lane *p) {
    int (*get_task)(u32 *)=(void *)(trace_native_ptr)0x5f1f24u;
    u32 (*clock0)(u32)=(void *)(trace_native_ptr)0x7a7489u;
    if(!lane_owner(p)||p->owner!=256u)return -22;
    u32 task=0;int status=get_task(&task);
    if(status||task!=256u)return -1;
    return precapture_trace_pool_after_task(p,task,status,clock0(0));
}
