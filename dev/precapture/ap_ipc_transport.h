/* Internal fresh-transport lifecycle shared by the cancel and RPC components.
 * No send operation lives here. Call only after validating the complete result
 * extent and freshness. Unknown ownership always retains FD and mapping.
 */
#ifndef PRECAPTURE_AP_IPC_TRANSPORT_H
#define PRECAPTURE_AP_IPC_TRANSPORT_H
#include "ap_ipc_context.h"
#define INFO_QUERY 0x80000010ull
#define SHARED_BYTES 0x200000ull
struct info_request { probe_u32 route,pad;probe_u64 output; };
_Static_assert(sizeof(struct ipc_context_result)==248,"context result ABI");
_Static_assert(sizeof(struct info_request)==16,"context query ABI");
_Static_assert(sizeof(ap_a64_i64)==8,"AArch64 Linux only");

static probe_u64 word(const probe_u8 *p,probe_u32 bytes){
    probe_u64 value=0;
    for(probe_u32 i=0;i<bytes;i++)value|=(probe_u64)p[i]<<(8*i);
    return value;
}
static int overlaps(probe_u64 start,probe_u64 bytes,probe_u64 other,probe_u64 size){
    return start<other+size&&other<start+bytes;
}
static int unknown(volatile struct ipc_context_result *r){
    r->ownership=IPC_OWN_UNKNOWN;r->phase=IPC_UNCERTAIN;r->return_status=-5;return -5;
}
static int finish_fd(volatile struct ipc_context_result *r,probe_i64 status,ap_a64_syscall sc){
    r->phase=IPC_CLOSE;r->close_attempts=1;
    r->close_status=sc(AP_A64_SYS_CLOSE,r->descriptor,0,0,0,0,0);
    if(r->close_status)return unknown(r);
    r->ownership=IPC_OWN_NONE;r->phase=status?IPC_REJECTED:IPC_COMPLETE;r->return_status=status;
    return (int)status;
}
static int finish_mapping(volatile struct ipc_context_result *r,probe_i64 status,ap_a64_syscall sc){
    r->phase=IPC_UNMAP;r->unmap_attempts=1;
    r->unmap_status=sc(AP_A64_SYS_MUNMAP,r->shared_begin,r->shared_bytes,0,0,0,0);
    if(r->unmap_status)return unknown(r);
    r->ownership=IPC_OWN_FD;
    return finish_fd(r,status,sc);
}

static int ipc_transport_open(volatile struct ipc_context_result *r,
    struct ipc_context_workspace *workspace,probe_u32 nonce,ap_a64_syscall sc,
    probe_ioctl invoke,probe_u64 result_bytes,probe_u32 version){
    probe_u64 rb=(probe_u64)(probe_uptr)r,wb=(probe_u64)(probe_uptr)workspace;
    r->magic=0x58544349u;r->version=version;r->nonce=nonce;
    r->descriptor=r->path_stat_status=r->open_status=r->fd_stat_status=-1;
    r->query_status=r->map_status=r->unmap_status=r->close_status=r->return_status=-1;
    for(probe_u32 i=0;i<sizeof(*workspace);i++)((volatile probe_u8 *)workspace)[i]=0;
    r->phase=IPC_PATH_STAT;r->stat_attempts=1;
    r->path_stat_status=sc(AP_A64_SYS_FSTATAT,-100,(ap_a64_i64)"/dev/uipc",
        (ap_a64_i64)workspace->path_stat,AP_A64_AT_SYMLINK_NOFOLLOW,0,0);
    if(r->path_stat_status){
        r->phase=IPC_REJECTED;r->return_status=r->path_stat_status<0?r->path_stat_status:-5;
        return (int)r->return_status;
    }
    if((word(workspace->path_stat+16,4)&0xf000)!=0x2000){
        r->phase=IPC_REJECTED;r->return_status=-95;return -95;
    }
    r->device=word(workspace->path_stat,8);r->inode=word(workspace->path_stat+8,8);r->rdev=word(workspace->path_stat+32,8);
    r->phase=IPC_OPEN;r->open_attempts=1;
    r->open_status=sc(AP_A64_SYS_OPENAT,-100,(ap_a64_i64)"/dev/uipc",AP_A64_OPEN_RDWR,0,0,0);
    if(r->open_status<0){r->phase=IPC_REJECTED;r->return_status=r->open_status;return (int)r->open_status;}
    r->descriptor=r->open_status;
    if(r->descriptor>0x7fffffff)return unknown(r);
    r->ownership=IPC_OWN_FD;r->phase=IPC_FD_STAT;r->stat_attempts=2;
    r->fd_stat_status=sc(AP_A64_SYS_FSTAT,r->descriptor,(ap_a64_i64)workspace->fd_stat,0,0,0,0);
    if(r->fd_stat_status)return finish_fd(r,r->fd_stat_status<0?r->fd_stat_status:-5,sc);
    if((word(workspace->fd_stat+16,4)&0xf000)!=0x2000||word(workspace->fd_stat,8)!=r->device||
       word(workspace->fd_stat+8,8)!=r->inode||word(workspace->fd_stat+32,8)!=r->rdev)
        return finish_fd(r,-84,sc);
    struct info_request query={0,0,(probe_u64)(probe_uptr)r->info};
    r->phase=IPC_QUERY;r->query_attempts=1;
    r->query_status=invoke((probe_i32)r->descriptor,INFO_QUERY,&query);
    if(r->query_status)return finish_fd(r,r->query_status<0?r->query_status:-5,sc);
    /* ID3 is retained exactly. Its native grammar is audited separately;
     * this cancel-only test never routes a message using that ID.
     */
    if(r->info[0]!=SHARED_BYTES||r->info[1]!=0x80000||r->info[2]!=0x20000)
        return finish_fd(r,-84,sc);
    r->phase=IPC_MAP;r->map_attempts=1;
    r->map_status=sc(AP_A64_SYS_MMAP,0,SHARED_BYTES,AP_A64_PROT_READ|AP_A64_PROT_WRITE,
        AP_A64_MAP_SHARED,r->descriptor,0);
    if(r->map_status<0){
        if(r->map_status<-4095)return unknown(r);
        return finish_fd(r,r->map_status,sc);
    }
    r->shared_begin=(probe_u64)r->map_status;r->shared_bytes=SHARED_BYTES;
    if((r->shared_begin&4095)||r->shared_begin+SHARED_BYTES<=r->shared_begin||
       overlaps(r->shared_begin,SHARED_BYTES,rb,result_bytes)||overlaps(r->shared_begin,SHARED_BYTES,wb,sizeof(*workspace)))
        return unknown(r);
    r->ownership=IPC_OWN_MAPPING;
    if(!r->shared_begin)return finish_mapping(r,-84,sc);
    return 0;
}
#endif
