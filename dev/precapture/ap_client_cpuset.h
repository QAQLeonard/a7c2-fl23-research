/* Isolated single-thread child ONLY. Exact paths must come from independently
 * read/qualified group policy. This does not admit any UIPC/CP operation.
 */
#ifndef PRECAPTURE_AP_CLIENT_CPUSET_H
#define PRECAPTURE_AP_CLIENT_CPUSET_H
#include "ap_client_binding.h"
enum client_cpuset_phase { CPUSET_INSPECT=1,CPUSET_MOVE,CPUSET_VERIFY,CPUSET_BOUND,
    CPUSET_RESTORE,CPUSET_VERIFY_ORIGINAL,CPUSET_RESTORED,CPUSET_REJECTED,CPUSET_UNKNOWN };
struct client_cpuset_result {
    probe_u32 magic,version,phase,ownership;
    probe_u32 CPU,calls,move_writes,restore_writes;
    probe_i64 pid,tid,parent,descriptor,last_result,status;
    probe_u64 affinity_before,affinity_target,affinity_restored;
    probe_u32 observed_CPU,read_bytes;
};
int precapture_client_cpuset_enter(volatile struct client_cpuset_result *,probe_u32 parent,
    probe_u32 CPU,ap_a64_syscall);
/* Only after all independent native/context ownership has been resolved. */
int precapture_client_cpuset_leave(volatile struct client_cpuset_result *,ap_a64_syscall);
#endif
