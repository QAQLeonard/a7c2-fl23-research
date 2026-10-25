/* Sequential JPEG mean core; caller-owned stream I/O.
 * This software is based in part on the work of the Independent JPEG Group.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <jpeglib.h>
#include <jerror.h>
#include "average.h"
#include "jpeg_stream.h"
#define IO_BYTES 16384
#define MAX_PIXELS 40000000u
#define MAX_OUTPUT (256ull * 1024 * 1024)
struct job;
struct jpeg_error { struct jpeg_error_mgr base; struct job *job; };
struct source {
    struct jpeg_source_mgr base;
    struct job *job;
    struct a7_jpeg_input io;
    unsigned index;
    unsigned char buffer[IO_BYTES];
};
struct destination {
    struct jpeg_destination_mgr base;
    struct job *job;
    struct a7_jpeg_output io;
    unsigned char buffer[IO_BYTES];
};
struct job {
    struct jpeg_decompress_struct input[2];
    struct jpeg_compress_struct output;
    struct jpeg_error error[3];
    struct source source[2];
    struct destination destination;
    struct a7_jpeg_control control;
    struct a7_jpeg_result *result;
    unsigned char *rows;
    int created[3];
    unsigned width, height, orientation;
    char message[512];
    jmp_buf failed;
};
static void fail(struct job *j, const char *message)
{
    if (!j->result->status) j->result->status = A7_JPEG_FORMAT;
    snprintf(j->message, sizeof(j->message), "%s", message);
    longjmp(j->failed, 1);
}
static void io_fail(struct job *j, int64_t code, const char *message)
{
    j->result->status = A7_JPEG_IO; j->result->io_error = code;
    snprintf(j->message, sizeof(j->message), "%s (I/O code %lld)", message, (long long)code);
    longjmp(j->failed, 1);
}
static void check_cancel(struct job *j)
{
    if (j->control.cancelled && j->control.cancelled(j->control.context)) {
        j->result->status = A7_JPEG_CANCELLED; fail(j, "Composition cancelled");
    }
}
static void jpeg_failure(j_common_ptr codec)
{
    struct job *j = ((struct jpeg_error *)codec->err)->job;
    if (!j->result->status) j->result->status =
        codec->err->msg_code == JERR_OUT_OF_MEMORY ? A7_JPEG_MEMORY : A7_JPEG_FORMAT;
    (*codec->err->format_message)(codec, j->message);
    longjmp(j->failed, 1);
}
static void jpeg_message(j_common_ptr codec, int level)
{
    if (level < 0) jpeg_failure(codec);
}
static void source_init(j_decompress_ptr codec) { (void)codec; }
static void source_term(j_decompress_ptr codec) { (void)codec; }
static boolean source_fill(j_decompress_ptr codec)
{
    struct source *s = (struct source *)codec->src;
    struct job *j = s->job;
    check_cancel(j);
    uint64_t consumed = j->result->input_bytes[s->index];
    if (consumed >= s->io.length) fail(j, "Input ended before JPEG completion");
    uint64_t remaining = s->io.length - consumed;
    size_t request = remaining < IO_BYTES ? (size_t)remaining : IO_BYTES;
    int64_t count = s->io.read(s->io.context, s->buffer, request);
    if (count < 0) io_fail(j, count, "Input read failed");
    if ((uint64_t)count > request) io_fail(j, count, "Input callback exceeded requested size");
    if (!count) fail(j, "Input ended before declared JPEG length");
    j->result->input_bytes[s->index] += (uint64_t)count;
    s->base.next_input_byte = s->buffer; s->base.bytes_in_buffer = (size_t)count;
    return TRUE;
}
static void source_skip(j_decompress_ptr codec, long bytes)
{
    if (bytes <= 0) return;
    struct jpeg_source_mgr *s = codec->src;
    while ((uint64_t)bytes > s->bytes_in_buffer) {
        bytes -= (long)s->bytes_in_buffer;
        source_fill(codec);
    }
    s->next_input_byte += bytes; s->bytes_in_buffer -= (size_t)bytes;
}
static void destination_init(j_compress_ptr codec)
{
    struct destination *d = (struct destination *)codec->dest;
    d->base.next_output_byte = d->buffer; d->base.free_in_buffer = IO_BYTES;
}
static void write_bytes(struct destination *d, size_t bytes)
{
    struct job *j = d->job;
    size_t at = 0;
    while (at < bytes) {
        check_cancel(j);
        if (bytes - at > MAX_OUTPUT - j->result->output_bytes)
            fail(j, "Encoded JPEG exceeds output limit");
        int64_t count = d->io.write(d->io.context, d->buffer + at, bytes - at);
        if (count < 0) io_fail(j, count, "Output write failed");
        if (!count || (uint64_t)count > bytes - at)
            io_fail(j, count, "Output callback returned invalid byte count");
        at += (size_t)count; j->result->output_bytes += (uint64_t)count;
    }
}
static boolean destination_empty(j_compress_ptr codec)
{
    struct destination *d = (struct destination *)codec->dest;
    write_bytes(d, IO_BYTES); destination_init(codec); return TRUE;
}
static void destination_term(j_compress_ptr codec)
{
    struct destination *d = (struct destination *)codec->dest;
    write_bytes(d, IO_BYTES - d->base.free_in_buffer);
}
static uint16_t get16(const unsigned char *p, int little)
{
    return little ? (uint16_t)(p[0] | p[1] << 8) :
                    (uint16_t)(p[1] | p[0] << 8);
}
static uint32_t get32(const unsigned char *p, int little)
{
    return little ? (uint32_t)get16(p, 1) | (uint32_t)get16(p + 2, 1) << 16 :
                    (uint32_t)get16(p + 2, 0) | (uint32_t)get16(p, 0) << 16;
}
struct metadata { unsigned orientation, color; int exif; };

static uint32_t read_ifd(struct job *j, const unsigned char *tiff, size_t size,
                         uint32_t offset, int little, int sub,
                         struct metadata *meta)
{
    uint32_t exif = 0;
    if (offset > size || size - offset < 2) fail(j, "Invalid EXIF directory");
    unsigned count = get16(tiff + offset, little);
    if ((size - offset - 2) / 12 < count) fail(j, "Truncated EXIF directory");
    for (unsigned i = 0; i < count; ++i) {
        const unsigned char *p = tiff + offset + 2 + i * 12;
        unsigned tag = get16(p, little), type = get16(p + 2, little);
        if ((!sub && tag == 0x112) || (sub && tag == 0xa001)) {
            if (type != 3 || get32(p + 4, little) != 1)
                fail(j, "Unsupported EXIF orientation/color field");
            unsigned value = get16(p + 8, little);
            if (tag == 0x112) {
                if (value < 1 || value > 8) fail(j, "Invalid EXIF orientation");
                meta->orientation = value;
            } else meta->color = value;
        } else if (!sub && tag == 0x8769) {
            if (type != 4 || get32(p + 4, little) != 1)
                fail(j, "Invalid EXIF subdirectory");
            exif = get32(p + 8, little);
        }
    }
    return exif;
}
static struct metadata metadata(struct job *j, int index)
{
    struct metadata meta = {1, 1, 0};
    for (jpeg_saved_marker_ptr marker = j->input[index].marker_list;
         marker; marker = marker->next) {
        const unsigned char *data = marker->data;
        size_t size = marker->data_length;
        if (marker->marker == JPEG_APP0 + 2 && size >= 12 &&
            !memcmp(data, "ICC_PROFILE\0", 12))
            fail(j, "ICC-tagged JPEG is not supported in the initial sRGB processor");
        if (marker->marker != JPEG_APP0 + 1 || size < 6 ||
            memcmp(data, "Exif\0\0", 6)) continue;
        if (meta.exif++) fail(j, "Multiple EXIF headers are not supported");
        data += 6; size -= 6;
        if (size < 8 || (memcmp(data, "II", 2) && memcmp(data, "MM", 2)))
            fail(j, "Invalid EXIF byte order");
        int little = data[0] == 'I';
        if (get16(data + 2, little) != 42) fail(j, "Invalid EXIF TIFF header");
        uint32_t offset = read_ifd(j, data, size, get32(data + 4, little), little, 0, &meta);
        if (offset) read_ifd(j, data, size, offset, little, 1, &meta);
    }
    if (meta.color != 1) fail(j, "Only sRGB/untagged JPEG is supported initially");
    return meta;
}
static void put16(unsigned char *p, unsigned x) { p[0] = x; p[1] = x >> 8; }
static void put32(unsigned char *p, unsigned x) { put16(p, x); put16(p + 2, x >> 16); }
static void tag(unsigned char *p, unsigned id, unsigned type, unsigned value)
{
    put16(p, id); put16(p + 2, type); put32(p + 4, 1); put32(p + 8, value);
}
static void write_metadata(struct job *j)
{
    /* Fresh metadata, with no stale thumbnail, source GPS or camera serial. */
    unsigned char marker[62] = {0}, *t = marker + 6;
    memcpy(marker, "Exif\0\0", 6); t[0] = 'I'; t[1] = 'I';
    put16(t + 2, 42); put32(t + 4, 8); put16(t + 8, 2);
    tag(t + 10, 0x112, 3, j->orientation); tag(t + 22, 0x8769, 4, 38);
    put16(t + 38, 1); tag(t + 40, 0xa001, 3, 1);
    jpeg_write_marker(&j->output, JPEG_APP0 + 1, marker, sizeof(marker));
}

static void open_input(struct job *j, unsigned index)
{
    struct jpeg_decompress_struct *codec = &j->input[index];
    struct source *s = &j->source[index];
    j->created[index] = 1; jpeg_create_decompress(codec);
    codec->mem->max_memory_to_use = 16 * 1024 * 1024;
    s->job = j; s->index = index;
    s->base.init_source = source_init; s->base.fill_input_buffer = source_fill;
    s->base.skip_input_data = source_skip; s->base.resync_to_restart = jpeg_resync_to_restart;
    s->base.term_source = source_term; codec->src = &s->base;
    jpeg_save_markers(codec, JPEG_APP0 + 1, 0xffff);
    jpeg_save_markers(codec, JPEG_APP0 + 2, 14);
    if (jpeg_read_header(codec, TRUE) != JPEG_HEADER_OK) fail(j, "Invalid JPEG header");
    if (codec->data_precision != 8 || codec->progressive_mode || codec->arith_code ||
        codec->num_components != 3 || jpeg_has_multiple_scans(codec) ||
        (codec->jpeg_color_space != JCS_YCbCr && codec->jpeg_color_space != JCS_RGB))
        fail(j, "Initial processor requires interleaved baseline 8-bit RGB/YCbCr JPEG");
    if (!codec->image_width || !codec->image_height ||
        (uint64_t)codec->image_width * codec->image_height > MAX_PIXELS)
        fail(j, "JPEG dimensions exceed the 40-megapixel limit");
    struct metadata meta = metadata(j, index);
    if (!index) {
        j->width = codec->image_width; j->height = codec->image_height;
        j->orientation = meta.orientation;
    } else if (j->width != codec->image_width || j->height != codec->image_height ||
               j->orientation != meta.orientation)
        fail(j, "Both JPEGs must have identical dimensions and EXIF orientation");
    codec->out_color_space = JCS_RGB;
    if (!jpeg_start_decompress(codec) || codec->output_components != 3)
        fail(j, "Cannot start JPEG decoding");
}
static void process(struct job *j)
{
    check_cancel(j); open_input(j, 0); open_input(j, 1);
    j->result->width = j->width; j->result->height = j->height;
    j->result->orientation = j->orientation;
    size_t bytes = (size_t)j->width * 3;
    if (bytes > SIZE_MAX / 3) fail(j, "JPEG row size overflow");
    j->rows = malloc(bytes * 3);
    if (!j->rows) { j->result->status = A7_JPEG_MEMORY; fail(j, "Cannot allocate scanlines"); }
    j->created[2] = 1; jpeg_create_compress(&j->output);
    struct destination *d = &j->destination; d->job = j;
    d->base.init_destination = destination_init;
    d->base.empty_output_buffer = destination_empty; d->base.term_destination = destination_term;
    j->output.dest = &d->base; j->output.image_width = j->width;
    j->output.image_height = j->height; j->output.input_components = 3;
    j->output.in_color_space = JCS_RGB;
    jpeg_set_defaults(&j->output); jpeg_set_quality(&j->output, 95, TRUE);
    for (int i = 0; i < 3; ++i) {
        j->output.comp_info[i].h_samp_factor = 1; j->output.comp_info[i].v_samp_factor = 1;
    }
    jpeg_start_compress(&j->output, TRUE); write_metadata(j);
    for (unsigned y = 0; y < j->height; ++y) {
        check_cancel(j);
        JSAMPROW rows[3] = {j->rows, j->rows + bytes, j->rows + bytes * 2};
        for (int i = 0; i < 2; ++i)
            if (jpeg_read_scanlines(&j->input[i], &rows[i], 1) != 1)
                fail(j, "Incomplete JPEG scanline");
        struct a7_average_plane a = {rows[0], bytes, bytes, bytes, 1};
        struct a7_average_plane b = {rows[1], bytes, bytes, bytes, 1};
        struct a7_average_plane out = {rows[2], bytes, bytes, bytes, 1};
        if (a7_average_u8(&a, &b, &out)) fail(j, "Mean scanline validation failed");
        if (jpeg_write_scanlines(&j->output, &rows[2], 1) != 1)
            fail(j, "Cannot encode output scanline");
    }
    for (int i = 0; i < 2; ++i)
        if (!jpeg_finish_decompress(&j->input[i])) fail(j, "Incomplete input JPEG");
    jpeg_finish_compress(&j->output); check_cancel(j);
}
int a7_jpeg_mean(const struct a7_jpeg_input *a, const struct a7_jpeg_input *b,
                 const struct a7_jpeg_output *out, const struct a7_jpeg_control *control,
                 struct a7_jpeg_result *result)
{
    if (!result) return A7_JPEG_INVALID;
    memset(result, 0, sizeof(*result));
    if (!a || !b || !out || !a->read || !b->read || !out->write ||
        !a->length || !b->length || a->length > A7_JPEG_MAX_INPUT || b->length > A7_JPEG_MAX_INPUT) {
        result->status = A7_JPEG_INVALID;
        snprintf(result->message, sizeof(result->message), "Invalid JPEG stream contract");
        return result->status;
    }
    struct job *j = calloc(1, sizeof(*j));
    if (!j) {
        result->status = A7_JPEG_MEMORY;
        snprintf(result->message, sizeof(result->message), "Cannot allocate composition state");
        return result->status;
    }
    j->result = result; j->source[0].io = *a; j->source[1].io = *b;
    j->destination.io = *out;
    if (control) j->control = *control;
    for (int i = 0; i < 3; ++i) {
        struct jpeg_error_mgr *error = jpeg_std_error(&j->error[i].base);
        j->error[i].job = j; error->error_exit = jpeg_failure; error->emit_message = jpeg_message;
        if (i < 2) j->input[i].err = error; else j->output.err = error;
    }
    if (!setjmp(j->failed)) process(j);
    for (int i = 0; i < 2; ++i) if (j->created[i]) jpeg_destroy_decompress(&j->input[i]);
    if (j->created[2]) jpeg_destroy_compress(&j->output);
    snprintf(result->message, sizeof(result->message), "%s", j->message);
    free(j->rows); free(j);
    return result->status;
}
