/* Uninstalled native RAW ownership adapter. Call only from a qualified native
 * CAM_CAP_MGR ingress; storage, source/boot identity and hook placement are not
 * supplied by this component. No exposure, pixel read or save is performed.
 * The verified build uses -mrestrict-it and checks generated instruction form.
 */
#ifndef PRECAPTURE_CP_RAW_LEASE_H
#define PRECAPTURE_CP_RAW_LEASE_H
#include "cp_control_state.h"

#define PC_RAW_EXTENTS 12u
enum pc_raw_phase { PC_RAW_EMPTY, PC_RAW_HELD, PC_RAW_DROPPED, PC_RAW_UNKNOWN };
struct pc_raw_extent { u32 low, high, bytes, reserved; };
struct pc_raw_lease {
    u32 phase, epoch, serial, handle, kind, sequence, count, native_status;
    struct pc_raw_extent extents[PC_RAW_EXTENTS];
};
/* A fresh zero lease is required. epoch/serial are the adapter's own non-reused
 * identity, not the native handle's wrapping five-bit generation. Successful
 * hold adds one actual native ownership reference AND one pin. It does not
 * assert an exposure timestamp or that the descriptor contains photograph data.
 */
int precapture_raw_hold(struct pc_raw_lease *,u32 epoch,u32 serial,u32 handle);
/* Removes only this lease's pin and ownership reference. Original final-owner
 * notification may remain in flight; a returned zero is NOT a terminal fence.
 * An interrupted/unknown call leaves UNKNOWN and cannot be replayed here.
 */
int precapture_raw_drop(struct pc_raw_lease *,u32 epoch,u32 serial);
_Static_assert(sizeof(struct pc_raw_lease)==224,"native RAW lease ABI");
#endif
