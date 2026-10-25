#ifndef A7C2_FILE_ENTRY_H
#define A7C2_FILE_ENTRY_H
#include "staging.h"
#include "bootstrap.h"
#include "resident_entry.h"
/* Small one-shot AP file request module. The production constructor runs this
 * with /tmp/jiritsu only when explicitly loaded by the native libJit path.
 * Does not open USB, alter firmware/settings, install a boot hook or spawn a
 * child process. A missing request is a no-op. Receipts are created exclusively
 * BEFORE execution and appended with payload/hash/commit marker afterwards;
 * incomplete receipts are never replayed or overwritten.
 * Fixed input names: a7c2.dex.request, a7c2.dex.payload (PUT only).
 * Output: a7c2.dex.result. Host must preserve/verify a receipt before explicitly
 * preparing another operation. ARM queues work; receipt completion != photo
 * completion. QUERY/DISABLE require the core already resident (NOLOAD).
 */
A7_JPEG_API int a7_file_entry_run(const char *directory);
#endif
