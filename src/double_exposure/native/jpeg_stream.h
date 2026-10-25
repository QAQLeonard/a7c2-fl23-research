#ifndef A7C2_JPEG_STREAM_H
#define A7C2_JPEG_STREAM_H
#include <stddef.h>
#include <stdint.h>

#define A7_JPEG_MAX_INPUT (96ull * 1024 * 1024)
enum a7_jpeg_status {
    A7_JPEG_OK = 0, A7_JPEG_INVALID = -1, A7_JPEG_IO = -2,
    A7_JPEG_FORMAT = -3, A7_JPEG_CANCELLED = -4, A7_JPEG_MEMORY = -5
};
struct a7_jpeg_input {
    void *context;
    uint64_t length;
    /* Return bytes read (0 = EOF) or a negative error. Short reads are valid. */
    int64_t (*read)(void *, void *, size_t);
};
struct a7_jpeg_output {
    void *context;
    /* Return known bytes written or a negative error. Zero is a failure.
     * After an error the core does not retry that write. */
    int64_t (*write)(void *, const void *, size_t);
};
struct a7_jpeg_control {
    void *context;
    int (*cancelled)(void *);
};
struct a7_jpeg_result {
    uint32_t width, height, orientation;
    int32_t status;
    int64_t io_error;
    uint64_t input_bytes[2], output_bytes;
    char message[512];
};

/* Synchronous, sequential 50/50 RGB mean. No path, open/close, filesystem,
 * media-library, global signal or firmware dependency. The caller owns the
 * input/output handles and any temporary output, and performs flush/close,
 * publication and media registration only after this returns A7_JPEG_OK.
 * An error can leave a partial output in the caller's owned staging stream.
 * Callback state stays valid until return; callbacks do not throw/longjmp.
 * Input length is the completed file size supplied by the I/O adapter.
 */
#ifdef _WIN32
#define A7_JPEG_API __declspec(dllexport)
#else
#define A7_JPEG_API __attribute__((visibility("default")))
#endif
A7_JPEG_API int a7_jpeg_mean(const struct a7_jpeg_input *, const struct a7_jpeg_input *,
                 const struct a7_jpeg_output *, const struct a7_jpeg_control *,
                 struct a7_jpeg_result *);
#endif
