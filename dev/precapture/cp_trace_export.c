#include "cp_trace_export.h"
typedef __UINTPTR_TYPE__ trace_export_ptr;
static int separate(const void *a,u32 an,const void *b,u32 bn) {
    trace_export_ptr x=(trace_export_ptr)a,y=(trace_export_ptr)b;
    if(!a||!b||(x&3u)||(y&3u)||x+an<x||y+bn<y)return 0;
    return x>=y ? x-y>=bn : y-x>=an;
}
static int finalized(const volatile struct pc_trace_lane *v,u32 nonce) {
    return v->magic==PC_TRACE_MAGIC&&v->abi==PC_TRACE_ABI&&v->bytes==sizeof(*v)&&
        v->source_tag&&(v->epoch_lo||v->epoch_hi)&&v->owner&&v->clock_domain&&
        v->capacity&&v->capacity<=PC_TRACE_CAPACITY&&v->written<=v->capacity&&
        v->frozen==1&&!v->busy&&v->overflow<=1&&!v->reserved[0]&&!v->reserved[1]&&
        nonce&&v->nonce==nonce;
}
int precapture_trace_read_packet(const struct pc_trace_lane *p,struct pc_trace_packet *m) {
    if(!separate(p,sizeof(*p),m,sizeof(*m)))return -22;
    if(m->mode!=PC_TRACE_READ_MODE)return 0;
    u32 nonce=m->nonce,offset=m->offset;int input=m->status==0&&m->count==0;
    for(u32 i=0;i<12;i++)if(m->data[i])input=0;
    m->status=0x83;m->count=0;
    for(u32 i=0;i<12;i++)((volatile u8*)m->data)[i]=0;
    const volatile struct pc_trace_lane *v=p;
    if(!input||offset>=sizeof(*p)||!finalized(v,nonce))return 1;
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    u32 n=sizeof(*p)-offset;if(n>12)n=12;
    const volatile u8 *source=(const volatile u8*)p;
    for(u32 i=0;i<n;i++)m->data[i]=source[offset+i];
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    /* Selected header drift recheck, not proof of absent writers or ABA. */
    if(!finalized(v,nonce)) {
        for(u32 i=0;i<12;i++)((volatile u8*)m->data)[i]=0;
        return 1;
    }
    m->count=(unsigned short)n;m->status=1;return 1;
}
