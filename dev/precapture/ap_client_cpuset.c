#include "ap_client_cpuset.h"
#define GROUP_ORIGINAL "1:cpuset:/cpu0_1_2_3rt\n"
#define GROUP_TARGET "1:cpuset:/cpu2\n"
#define ORIGINAL_TASKS "/dev/cgroup/cpu0_1_2_3rt/tasks"
#define TARGET_TASKS "/dev/cgroup/cpu2/tasks"
_Static_assert(sizeof(struct client_cpuset_result)==112,"cpuset result ABI");
static probe_i64 invoke(volatile struct client_cpuset_result*r,ap_a64_syscall sc,
    probe_i64 n,probe_i64 a,probe_i64 b,probe_i64 c,probe_i64 d){
    r->calls++;r->last_result=sc(n,a,b,c,d,0,0);return r->last_result;
}
static int uncertain(volatile struct client_cpuset_result*r){r->phase=CPUSET_UNKNOWN;r->status=-5;return -5;}
static int read_group(volatile struct client_cpuset_result*r,ap_a64_syscall sc,const char*expected){
    probe_i64 fd=invoke(r,sc,56,-100,(probe_i64)"/proc/self/cgroup",AP_A64_OPEN_READ,0);
    if(fd<0)return -1;
    char data[128];probe_i64 bytes=invoke(r,sc,63,fd,(probe_i64)data,sizeof(data),0);
    probe_i64 close=invoke(r,sc,57,fd,0,0,0);
    if(close||bytes<=0||bytes>=(probe_i64)sizeof(data))return -1;
    r->read_bytes=(probe_u32)bytes;
    probe_u32 i=0;for(;expected[i];i++)if(i>=(probe_u32)bytes||data[i]!=expected[i])return -1;
    return i==(probe_u32)bytes?0:-1;
}
static int move_self(volatile struct client_cpuset_result*r,ap_a64_syscall sc,int restore){
    const char text[2]={'0','\n'};
    r->descriptor=invoke(r,sc,56,-100,(probe_i64)(restore?ORIGINAL_TASKS:TARGET_TASKS),
        AP_A64_O_WRONLY|AP_A64_O_CLOEXEC|AP_A64_O_NOFOLLOW,0);
    if(r->descriptor<0)return -1;
    /* Kernel tasks-file PID0 means current only; even a short "0" cannot
     * name another process. No CREATE/TRUNCATE, seek or write replay.
     */
    if(restore)r->restore_writes++;else r->move_writes++;
    probe_i64 result=invoke(r,sc,64,r->descriptor,(probe_i64)text,2,0);
    if(result!=2)return -1;
    if(invoke(r,sc,57,r->descriptor,0,0,0))return -1;
    r->descriptor=-1;return 0;
}
int precapture_client_cpuset_enter(volatile struct client_cpuset_result*r,probe_u32 parent,
    probe_u32 CPU,ap_a64_syscall sc){
    if(!r||!sc||!parent||parent>0x7fffffff||CPU>=64)return -22;
    const volatile probe_u8*raw=(const volatile probe_u8*)r;
    for(probe_u32 i=0;i<sizeof(*r);i++)if(raw[i])return -16;
    r->magic=0x31504343u;r->version=1;r->CPU=CPU;r->phase=CPUSET_INSPECT;r->descriptor=-1;r->status=-1;
    r->pid=invoke(r,sc,172,0,0,0,0);r->tid=invoke(r,sc,178,0,0,0,0);r->parent=invoke(r,sc,173,0,0,0,0);
    if(r->pid<=0||r->pid>0x7fffffff||r->pid!=r->tid||r->pid==parent||r->parent!=parent)goto reject;
    if(invoke(r,sc,120,0,0,0,0))goto reject;
    probe_i32 priority=0;if(invoke(r,sc,121,0,(probe_i64)&priority,0,0)||priority)goto reject;
    if(invoke(r,sc,123,0,8,(probe_i64)&r->affinity_before,0)!=8||!(r->affinity_before&(1ull<<CPU)))goto reject;
    if(read_group(r,sc,GROUP_ORIGINAL))goto reject;
    r->phase=CPUSET_MOVE;r->ownership=1;
    if(move_self(r,sc,0))return uncertain(r);
    r->phase=CPUSET_VERIFY;
    if(read_group(r,sc,GROUP_TARGET))return uncertain(r);
    if(invoke(r,sc,123,0,8,(probe_i64)&r->affinity_target,0)!=8||r->affinity_target!=(1ull<<CPU))return uncertain(r);
    probe_u32 observed=~0u;
    if(invoke(r,sc,168,(probe_i64)&observed,0,0,0)||observed!=CPU)return uncertain(r);
    r->observed_CPU=observed;r->phase=CPUSET_BOUND;r->status=0;return 0;
reject:r->phase=CPUSET_REJECTED;r->status=-95;return -95;
}
int precapture_client_cpuset_leave(volatile struct client_cpuset_result*r,ap_a64_syscall sc){
    if(!r||!sc||r->magic!=0x31504343u||r->version!=1||r->phase!=CPUSET_BOUND||r->ownership!=1||
       r->status||r->move_writes!=1||r->restore_writes||r->descriptor!=-1||r->CPU>=64||
       r->affinity_target!=(1ull<<r->CPU))return -22;
    r->phase=CPUSET_RESTORE;
    if(move_self(r,sc,1))return uncertain(r);
    r->phase=CPUSET_VERIFY_ORIGINAL;
    if(read_group(r,sc,GROUP_ORIGINAL))return uncertain(r);
    if(invoke(r,sc,123,0,8,(probe_i64)&r->affinity_restored,0)!=8||r->affinity_restored!=r->affinity_before)return uncertain(r);
    r->ownership=0;r->phase=CPUSET_RESTORED;r->status=0;return 0;
}
