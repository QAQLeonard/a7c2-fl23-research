#include "average.h"

static int plane_span(const struct a7_average_plane *p, size_t *span)
{
    if (!p->data || !p->row_bytes || !p->rows || p->stride < p->row_bytes)
        return A7_AVERAGE_INVALID;
    if (p->rows - 1 > (SIZE_MAX - p->row_bytes) / p->stride)
        return A7_AVERAGE_SIZE;
    *span = (p->rows - 1) * p->stride + p->row_bytes;
    if (*span > p->bytes || *span > UINTPTR_MAX - (uintptr_t)p->data)
        return A7_AVERAGE_SIZE;
    return A7_AVERAGE_OK;
}

static int overlaps(const uint8_t *a, size_t a_bytes,
                    const uint8_t *b, size_t b_bytes)
{
    uintptr_t x = (uintptr_t)a, y = (uintptr_t)b;
    /* plane_span has already rejected wrapping address ranges. */
    return x < y + b_bytes && y < x + a_bytes;
}

int a7_average_u8(const struct a7_average_plane *first,
                  const struct a7_average_plane *second,
                  const struct a7_average_plane *output)
{
    struct a7_average_plane a, b, out;
    size_t a_span, b_span, out_span;
    int status;
    if (!first || !second || !output)
        return A7_AVERAGE_INVALID;
    a = *first;
    b = *second;
    out = *output;
    if (a.row_bytes != b.row_bytes || a.row_bytes != out.row_bytes ||
        a.rows != b.rows || a.rows != out.rows)
        return A7_AVERAGE_INVALID;
    status = plane_span(&a, &a_span);
    if (status != A7_AVERAGE_OK)
        return status;
    status = plane_span(&b, &b_span);
    if (status != A7_AVERAGE_OK)
        return status;
    status = plane_span(&out, &out_span);
    if (status != A7_AVERAGE_OK)
        return status;
    if (overlaps(out.data, out_span, a.data, a_span) ||
        overlaps(out.data, out_span, b.data, b_span))
        return A7_AVERAGE_OVERLAP;

    for (size_t row = 0; row < out.rows; ++row) {
        const uint8_t *left = a.data + row * a.stride;
        const uint8_t *right = b.data + row * b.stride;
        uint8_t *dest = out.data + row * out.stride;
        for (size_t x = 0; x < out.row_bytes; ++x)
            dest[x] = (uint8_t)(((unsigned)left[x] + right[x] + 1u) >> 1);
    }
    return A7_AVERAGE_OK;
}
