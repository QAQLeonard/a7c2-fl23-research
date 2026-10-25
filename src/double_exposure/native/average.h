#ifndef A7C2_DOUBLE_EXPOSURE_AVERAGE_H
#define A7C2_DOUBLE_EXPOSURE_AVERAGE_H

#include <stddef.h>
#include <stdint.h>

/* A decoded, unsigned 8-bit sample plane. Strides and lengths are in bytes.
 * Both sources must already have identical dimensions, channel ordering,
 * orientation, color encoding and sample range. This does not decode JPEG,
 * interpret packed pixel words or perform RAW/linear-light development.
 *
 * A caller can supply one row at a time to avoid three full-frame buffers.
 * The caller owns all memory and must keep it valid for the entire call.
 */
struct a7_average_plane {
    uint8_t *data;
    size_t bytes;
    size_t stride;
    size_t row_bytes;
    size_t rows;
};

enum a7_average_status {
    A7_AVERAGE_OK = 0,
    A7_AVERAGE_INVALID = -1,
    A7_AVERAGE_SIZE = -2,
    A7_AVERAGE_OVERLAP = -3
};

/* Equal-weight sample mean, rounded up for an odd sum: (a + b + 1) / 2.
 * Inputs and all row padding are preserved. Output must not overlap either
 * input's used span. No data is written when validation fails.
 *
 * Source descriptors are copied before writing. The descriptor objects
 * themselves must not overlap writable image storage.
 */
int a7_average_u8(const struct a7_average_plane *first,
                  const struct a7_average_plane *second,
                  const struct a7_average_plane *output);

#endif
