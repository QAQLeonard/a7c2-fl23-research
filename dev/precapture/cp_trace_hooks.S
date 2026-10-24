/* UNINSTALLED exposure entry wrappers, source-qualified in the offline check.
 * Address definitions are supplied by an explicit lab build. No loader, patch
 * manifest or allocated native trace storage is supplied. These64 stack bytes
 * and the C/native calls need real task/IRQ/stack/timing admission before use.
 */
#ifndef PRECAPTURE_TRACE_BEGIN_LANE
#error "Explicit allocated begin-owner lane required"
#endif
#ifndef PRECAPTURE_TRACE_END_LANE
#error "Explicit allocated end-owner lane required"
#endif
.syntax unified
.thumb
.text
.macro exposure_trace name,after,lane,kind,value,resume
.global \name
.type \name,%function
.thumb_func
\name:
    push.w {r0-r12,lr}
    mrs r12,apsr
    push {r12,lr}
    mov r2,r0
    ldr r0,=\lane
    movs r1,#\kind
    bl precapture_trace_native_edge
/* Independent after-observer slice, not a successful native service stub. */
.global \after
.type \after,%function
.thumb_func
\after:
    pop {r12,lr}
    msr APSR_nzcvqg,r12
    pop.w {r0-r12,lr}
    /* Exact original displaced6-byte entry prefix. */
    push {r4,r6,r7,lr}
    add r7,sp,#8
    movs r0,#\value
    ldr pc,=\resume
.size \after,.-\after
.size \name,.-\name
.endm
exposure_trace precapture_trace_begin_hook,precapture_trace_begin_after,PRECAPTURE_TRACE_BEGIN_LANE,5,0,0x49e7fb
exposure_trace precapture_trace_end_hook,precapture_trace_end_after,PRECAPTURE_TRACE_END_LANE,6,4,0x49e87f
