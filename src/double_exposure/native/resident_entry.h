#ifndef A7C2_RESIDENT_ENTRY_H
#define A7C2_RESIDENT_ENTRY_H
#include "native_session.h"
/* Core-owned process singleton, called by the small one-shot file entry.
 * job_root is a newly-owned POSIX journal directory, separate from immutable
 * core staging. No fake/native fallback and no device discovery. Unsupported
 * loaded AP/SDK stops before callback installation. QUERY never loads/creates.
 */
A7_JPEG_API int a7_resident_request(const void *, size_t, const char *, struct a7_device_report *);
A7_JPEG_API uint64_t a7_resident_abi(void);
#endif
