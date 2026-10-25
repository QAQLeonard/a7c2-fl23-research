/* Synthetic SDK exports for loader tests. Never a camera distribution asset. */
#include <stdint.h>
#include <string.h>
static unsigned calls;
unsigned a7_fixture_calls(void) { return calls; }
#ifdef A7_FIXTURE_FSYS
int32_t Fsys_Flush(uint64_t handle)
{ ++calls; return handle == 0x100000001ull ? 0 : -1; }
int32_t Fsys_Mkdir(char *path) { (void)path; ++calls; return 0; }
#else
int32_t fixture_open(char *, uint32_t, uint64_t *) __asm__("_ZN3mpr4file4OpenEPcNS0_8OpenFlagEPm");
int32_t fixture_read(char, uint64_t, void *, uint32_t) __asm__("_ZN3mpr4file4ReadEcmPvj");
int32_t fixture_write(char, uint64_t, void *, uint32_t) __asm__("_ZN3mpr4file5WriteEcmPvj");
int32_t fixture_close(char, uint64_t) __asm__("_ZN3mpr4file5CloseEcm");
int32_t fixture_stat(char *, uint64_t *) __asm__("_ZN3mpr4file4StatEPcPm");
int32_t fixture_open(char *path, uint32_t flags, uint64_t *handle)
{ (void)path; ++calls; if (flags != 1) return -1; *handle = 0x100000001ull; return 0; }
int32_t fixture_read(char drive, uint64_t handle, void *buffer, uint32_t bytes)
{ ++calls; if (drive != 'A' || handle != 0x100000001ull || bytes != 7) return -1;
  memset(buffer, 'R', bytes); return (int32_t)bytes; }
int32_t fixture_write(char drive, uint64_t handle, void *buffer, uint32_t bytes)
{ (void)drive; (void)handle; (void)buffer; ++calls; return (int32_t)bytes; }
int32_t fixture_close(char drive, uint64_t handle)
{ (void)drive; (void)handle; ++calls; return 0; }
int32_t fixture_stat(char *path, uint64_t *size)
{ (void)path; ++calls; *size = 42; return 0; }
#endif
