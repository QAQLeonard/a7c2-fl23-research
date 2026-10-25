#include "cp_raw_lease.h"
typedef __UINTPTR_TYPE__ raw_ptr;
_Static_assert(sizeof(void *)==4,"Native CP lease requires ARM32");

/* Exact ILCE-7CM2 2.01 original entries, including their actual ISA bits. */
static int context_task(void) {
    int (*get_task)(u32 *)=(void *)(raw_ptr)0x5f1f24u;
    u32 task=0;
    int status=get_task(&task);
    return status?status:task==136u?0:-1;
}
static int enter(void) {
    int status=context_task();
    if(status)return status;
    int (*try_lock)(u32)=(void *)(raw_ptr)0x5ee6f0u;
    return try_lock(0x6cu);
}
static int leave(void) {
    int (*unlock)(u32)=(void *)(raw_ptr)0x5ee8a8u;
    return unlock(0x6cu);
}
static volatile u8 *record(u32 handle) {
    const volatile u32 *pool=(const volatile u32 *)(raw_ptr)0x1a8c558u;
    if(*pool!=0x22a4760u||(handle&0xffff0000u)||(handle&0x8000u)==0u||
       (handle&1023u)==1023u)return 0;
    return (volatile u8 *)(raw_ptr)(*pool+(handle&1023u)*64u);
}
static u32 word(const volatile u8 *p,u32 at) {
    return *(const volatile u32 *)(p+at);
}
static u32 half(const volatile u8 *p,u32 at) {
    return *(const volatile unsigned short *)(p+at);
}
static int matches(const volatile u8 *p,u32 handle,u32 sequence) {
    return p&&p[11]==((handle>>10)&31u)&&word(p,0)==0x50504u&&
        word(p,4)==sequence&&sequence!=0xffffffffu;
}
static int backing_nodes(const volatile u8 *p,u32 count,u32 sequence) {
    const volatile u32 *base=(const volatile u32 *)(raw_ptr)0x1a8c0acu;
    if(*base!=0x22b4f40u)return 0;
    for(u32 i=0;i<count;i++) {
        u32 address=word(p,16u+4u*i);
        if(address<*base||address>*base+0x1b800u-80u||
           (address-*base)%80u)return 0;
        const volatile u8 *node=(const volatile u8 *)(raw_ptr)address;
        if(word(node,0x28)!=(u32)(raw_ptr)p||word(node,0x2c)!=sequence)return 0;
    }
    return 1;
}
static int finish(struct pc_raw_lease *lease,int status) {
    int release=leave();
    if(release) {
        lease->phase=PC_RAW_UNKNOWN;lease->native_status=(u32)release;return -5;
    }
    return status;
}

int precapture_raw_hold(struct pc_raw_lease *lease,u32 epoch,u32 serial,u32 handle) {
    if(!lease||((raw_ptr)lease&3u)||!epoch||!serial||lease->phase!=PC_RAW_EMPTY)return -22;
    int status=enter();
    if(status)return status; /* No ownership mutation if context/try-lock refuses. */
    volatile u8 *p=record(handle);
    if(!p||p[11]!=((handle>>10)&31u)||word(p,0)!=0x50504u||
       !p[8]||p[8]==255u||p[9]==255u||
       (half(p,12)!=1u&&half(p,12)!=2u)||
       !half(p,14)||half(p,14)>PC_RAW_EXTENTS||word(p,4)==0xffffffffu)
        return finish(lease,-116);
    u32 owners=p[8],pins=p[9],sequence=word(p,4),count=half(p,14);
    if(!backing_nodes(p,count,sequence))return finish(lease,-116);
    lease->phase=PC_RAW_UNKNOWN;lease->epoch=epoch;lease->serial=serial;
    lease->handle=handle;lease->kind=0x50504u;lease->sequence=sequence;
    lease->count=0;lease->native_status=0;
    int (*add_owner)(u32,u32)=(void *)(raw_ptr)0xc1e779u;
    status=add_owner(lease->kind,handle);
    lease->native_status=(u32)status;
    if(status||!matches(p,handle,sequence)||p[8]!=owners+1u)
        return finish(lease,-5);
    for(u32 i=0;i<PC_RAW_EXTENTS;i++) {
        lease->extents[i].low=lease->extents[i].high=0;
        lease->extents[i].bytes=lease->extents[i].reserved=0;
    }
    unsigned short number=0;
    int (*pin)(u32,u32,struct pc_raw_extent *,unsigned short *)=(void *)(raw_ptr)0xc1ea53u;
    status=pin(handle,1u,lease->extents,&number);
    lease->native_status=(u32)status;
    if(status||number!=count||!matches(p,handle,sequence)||
       p[8]!=owners+1u||p[9]!=pins+1u||half(p,12)!=2u)
        return finish(lease,-5);
    for(u32 i=0;i<number;i++) {
        const struct pc_raw_extent *e=&lease->extents[i];
        /* Source configuration's CP-DDR root bounds only; these checks do not
         * establish physical ownership or authorize dereferencing any pixels. */
        if(e->high!=5u||!e->bytes||e->bytes>0x40000000u||
           e->low>0x40000000u-e->bytes)return finish(lease,-5);
    }
    lease->count=number;
    status=leave();
    if(status){lease->native_status=(u32)status;return -5;}
    lease->phase=PC_RAW_HELD;
    return 0;
}

int precapture_raw_drop(struct pc_raw_lease *lease,u32 epoch,u32 serial) {
    if(!lease||((raw_ptr)lease&3u)||lease->phase!=PC_RAW_HELD||
       lease->epoch!=epoch||lease->serial!=serial)return -22;
    int status=enter();
    if(status)return status;
    volatile u8 *p=record(lease->handle);
    if(!matches(p,lease->handle,lease->sequence)||!p[8]||!p[9]||
       half(p,12)!=2u||half(p,14)!=lease->count||
       !backing_nodes(p,lease->count,lease->sequence)){
        lease->phase=PC_RAW_UNKNOWN;return finish(lease,-116);
    }
    lease->phase=PC_RAW_UNKNOWN;
    int (*unpin)(u32)=(void *)(raw_ptr)0xc1eb4du;
    int (*drop_owner)(u32)=(void *)(raw_ptr)0xc1ebd7u;
    status=unpin(lease->handle);lease->native_status=(u32)status;
    if(status)return finish(lease,-5);
    status=drop_owner(lease->handle);lease->native_status=(u32)status;
    if(status)return finish(lease,-5);
    status=leave();
    if(status){lease->native_status=(u32)status;return -5;}
    lease->phase=PC_RAW_DROPPED;
    return 0;
}
