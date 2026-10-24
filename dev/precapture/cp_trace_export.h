/* Uninstalled packet adapter, not a registered callback or camera reader. */
#ifndef PRECAPTURE_CP_TRACE_EXPORT_H
#define PRECAPTURE_CP_TRACE_EXPORT_H
#include "cp_trace.h"
#define PC_TRACE_READ_MODE 0xe2u
struct pc_trace_packet {
    u8 mode,status;unsigned short count;u32 offset;u8 data[12];u32 nonce;
};
_Static_assert(sizeof(struct pc_trace_packet)==24,"trace packet ABI");
/* Caller must supply a valid, allocated lane whose original owner has frozen
 * recording, exclude every subsequent writer and keep it alive for the entire
 * export. A frozen flag alone does NOT establish those native preconditions.
 * No request contains a memory pointer. No freeze/reset/free/IPC is performed.
 * Other modes return0 with the packet untouched, for original dispatch.
 * A matched mode returns1 after producing success/refusal, or -22 for invalid
 * pointers/aliasing. Native callback/length/lifetime binding is still missing.
 */
int precapture_trace_read_packet(const struct pc_trace_lane *,struct pc_trace_packet *);
#endif
