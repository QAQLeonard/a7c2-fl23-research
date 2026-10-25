#ifndef A7C2_SONY_SDK_H
#define A7C2_SONY_SDK_H
#include "dcf_publish.h"
#include "capture_delegate.h"
struct a7_sony_sdk {
    struct a7_ap_lease lease;
    struct a7_catalog_api catalog;
    struct a7_dcf_api dcf;
    void *modules[2];
    uint32_t bound, close_attempts, review;
    int32_t status;
    void *dcf_cache, *dcf_mutex, *msidconv;
    void (*number_lock)(void *);
    void (*number_unlock)(void *);
    uint32_t (*slot_id)(void *, uint32_t);
    void (*file_info_ctor)(void *);
    void *(*string_assign)(void *, const char *);
    void (*folder_update)(uint32_t, uint16_t, void *, uint32_t, uint32_t);
    void (*file_update)(uint32_t, uint16_t, uint16_t);
};
/* Resolve only the already-loaded 2.01 SDK, keep a job lease and qualified
 * module references until all API/handle users have drained. No SDK init,
 * photos or callback slot writes occur in bind(). Failed closes never retry.
 * dcf.context/save are supplied by the transaction owner after binding.
 */
A7_JPEG_API int a7_sony_sdk_bind(struct a7_sony_sdk *);
A7_JPEG_API int a7_sony_sdk_close(struct a7_sony_sdk *);
/* Build the verified 2.01 AP delegate registry adapter for an explicitly
 * identified loaded AP base. Check mapped extents and native instruction
 * positions before admitting its mutex/slot. Does not attach a callback.
 */
A7_JPEG_API int a7_sony_delegate_api(uintptr_t ap_base, struct a7_delegate_api *);
A7_JPEG_API int a7_sony_find_ap(uintptr_t *);
#endif
