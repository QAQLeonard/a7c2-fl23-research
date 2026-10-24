#include "cp_trace.h"
typedef __UINTPTR_TYPE__ trace_ptr;
static void publish(void) { __atomic_thread_fence(__ATOMIC_RELEASE); }
static int aligned(const void *p) { return p && !((trace_ptr)p&3u); }
static int separate(const void *a,u32 an,const void *b,u32 bn) {
    trace_ptr x=(trace_ptr)a,y=(trace_ptr)b;
    if(!a||!b||x+an<x||y+bn<y)return 0;
    return x>=y ? x-y>=bn : y-x>=an;
}
static int valid(const struct pc_trace_lane *p) {
    return aligned(p)&&p->magic==PC_TRACE_MAGIC&&p->abi==PC_TRACE_ABI&&
        p->bytes==sizeof(*p)&&p->source_tag&&(p->epoch_lo||p->epoch_hi)&&
        p->owner&&p->capacity&&p->capacity<=PC_TRACE_CAPACITY&&p->clock_domain&&
        p->nonce&&p->written<=p->capacity&&p->frozen<=1&&p->overflow<=1&&
        p->busy<=1&&!p->reserved[0]&&!p->reserved[1];
}
int precapture_trace_ready(const struct pc_trace_lane *p) {
    return valid(p)&&!p->frozen&&!p->busy&&!p->overflow&&p->written<p->capacity;
}
int precapture_trace_initialize(struct pc_trace_lane *p,const struct pc_trace_binding *b) {
    if(!aligned(p)||!aligned(b)||!separate(p,sizeof(*p),b,sizeof(*b))||
       !b->source_tag||!(b->epoch_lo||b->epoch_hi)||!b->owner||!b->capacity||
       b->capacity>PC_TRACE_CAPACITY||!b->clock_domain||!b->nonce||b->reserved)return -22;
    const volatile u8 *old=(const volatile u8 *)p;
    for(u32 i=0;i<sizeof(*p);i++)if(old[i])return -16;
    p->abi=PC_TRACE_ABI;p->bytes=sizeof(*p);p->source_tag=b->source_tag;
    p->epoch_lo=b->epoch_lo;p->epoch_hi=b->epoch_hi;p->owner=b->owner;
    p->capacity=b->capacity;p->clock_domain=b->clock_domain;p->nonce=b->nonce;
    publish();((volatile struct pc_trace_lane *)p)->magic=PC_TRACE_MAGIC;
    return 1;
}
int precapture_trace_append(struct pc_trace_lane *p,u32 owner,const struct pc_trace_event *e) {
    if(!valid(p)||!aligned(e)||!separate(p,sizeof(*p),e,sizeof(*e))||
       e->kind<PC_POOL||e->kind>PC_DIAGNOSTIC)return -22;
    if(owner!=p->owner)return -1;
    if(p->busy)return -16;
    if(p->frozen)return -30;
    if(p->overflow)return -28;
    if(p->written==p->capacity) {
        ((volatile struct pc_trace_lane *)p)->overflow=1;publish();return -28;
    }
    volatile struct pc_trace_lane *v=p;v->busy=1;publish();
    u32 sequence=p->written+1;
    volatile struct pc_trace_record *r=&v->records[p->written];
    if(r->sequence) {v->overflow=1;publish();v->busy=0;return -84;}
    const u32 *input=(const u32 *)e;
    volatile u32 *out=(volatile u32 *)&r->event;
    u32 guard=2166136261u;
    guard=(guard^sequence)*16777619u;
    for(u32 i=0;i<10;i++) {u32 word=input[i];out[i]=word;guard=(guard^word)*16777619u;}
    r->guard=guard;publish();r->sequence=sequence;publish();
    v->written=sequence;publish();v->busy=0;
    return 1;
}
int precapture_trace_freeze(struct pc_trace_lane *p,u32 owner) {
    if(!valid(p))return -22;
    if(owner!=p->owner)return -1;
    if(p->busy)return -16;
    if(p->frozen)return 0;
    publish();((volatile struct pc_trace_lane *)p)->frozen=1;publish();
    return 1;
}
