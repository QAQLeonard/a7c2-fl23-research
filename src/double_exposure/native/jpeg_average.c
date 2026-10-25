/* Camera-side two-JPEG mean processor.  No firmware addresses or USB access.
 * This software is based in part on the work of the Independent JPEG Group.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <setjmp.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <process.h>
#include <windows.h>
#define close _close
#define unlink _unlink
#define fdopen _fdopen
#define fileno _fileno
#define fsync _commit
#define getpid _getpid
#ifndef S_ISREG
#define S_ISREG(m) (((m) & S_IFMT) == S_IFREG)
#endif
#else
#include <unistd.h>
#include <sys/syscall.h>
#endif
#include <jpeglib.h>
#include "average.h"

#define MAX_PIXELS 40000000u
#define MAX_INPUT_BYTES (96u * 1024u * 1024u)
#define STRING_VALUE_INNER(x) #x
#define STRING_VALUE(x) STRING_VALUE_INNER(x)

struct job;
struct jpeg_error {
    struct jpeg_error_mgr base;
    struct job *job;
};
struct job {
    struct jpeg_decompress_struct input[2];
    struct jpeg_compress_struct output;
    struct jpeg_error error[3];
    FILE *source[2], *destination;
    struct stat before[2];
    unsigned char *rows;
    int created[3], temporary, committed;
    unsigned width, height, orientation;
    char temp[4096], message[512];
    jmp_buf failed;
};
static volatile sig_atomic_t cancelled;

static void cancel_job(int signal_number) { (void)signal_number; cancelled = 1; }
static void fail(struct job *j, const char *message)
{
    snprintf(j->message, sizeof(j->message), "%s", message);
    longjmp(j->failed, 1);
}
static void jpeg_failure(j_common_ptr codec)
{
    struct jpeg_error *error = (struct jpeg_error *)codec->err;
    (*codec->err->format_message)(codec, error->job->message);
    longjmp(error->job->failed, 1);
}
static void jpeg_message(j_common_ptr codec, int level)
{
    /* A truncated JPEG must fail rather than silently synthesize an EOI. */
    if (level < 0) jpeg_failure(codec);
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
static int publish(const char *temporary, const char *destination, char *error, size_t capacity)
{
#ifdef _WIN32
    /* No REPLACE_EXISTING: an existing result/source is never replaced. */
    if (MoveFileExA(temporary, destination, MOVEFILE_WRITE_THROUGH)) return 0;
    unsigned long code = GetLastError();
    snprintf(error, capacity, "Cannot publish output JPEG (Win32 error %lu)", code);
    return -1;
#else
    /* Avoid hard links, which FAT/exFAT cannot provide. Unsupported
     * no-replace rename operations fail without an overwrite fallback. */
    int result = (int)syscall(SYS_renameat2, AT_FDCWD, temporary, AT_FDCWD,
                              destination, 1u);
    if (result) {
        int code = errno;
        snprintf(error, capacity, "Cannot publish output JPEG: %s (errno %d)",
                 strerror(code), code);
    }
    return result;
#endif
}
static void open_input(struct job *j, const char *path, int index)
{
    struct jpeg_decompress_struct *codec = &j->input[index];
    j->source[index] = fopen(path, "rb");
    if (!j->source[index]) fail(j, "Cannot open input JPEG");
    if (fstat(fileno(j->source[index]), &j->before[index]) ||
        !S_ISREG(j->before[index].st_mode) || j->before[index].st_size <= 0 ||
        (uint64_t)j->before[index].st_size > MAX_INPUT_BYTES)
        fail(j, "Input must be a completed regular JPEG of at most 96 MiB");
    j->created[index] = 1;
    jpeg_create_decompress(codec);
    codec->mem->max_memory_to_use = 16 * 1024 * 1024;
    jpeg_save_markers(codec, JPEG_APP0 + 1, 0xffff);
    jpeg_save_markers(codec, JPEG_APP0 + 2, 14);
    jpeg_stdio_src(codec, j->source[index]);
    if (jpeg_read_header(codec, TRUE) != JPEG_HEADER_OK)
        fail(j, "Invalid JPEG header");
    if (codec->data_precision != 8 || codec->progressive_mode ||
        codec->arith_code || codec->num_components != 3 || jpeg_has_multiple_scans(codec) ||
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
static void process(struct job *j, char **paths)
{
    open_input(j, paths[0], 0); open_input(j, paths[1], 1);
    size_t bytes = (size_t)j->width * 3;
    if (bytes > SIZE_MAX / 3) fail(j, "JPEG row size overflow");
    j->rows = malloc(bytes * 3);
    if (!j->rows) fail(j, "Cannot allocate JPEG scanlines");
    int n = snprintf(j->temp, sizeof(j->temp), "%s.a7c2-%lu.part",
                     paths[2], (unsigned long)getpid());
    if (n < 0 || (size_t)n >= sizeof(j->temp)) fail(j, "Output path is too long");
    int flags = O_WRONLY | O_CREAT | O_EXCL;
#ifdef _WIN32
    flags |= O_BINARY;
#endif
    int fd = open(j->temp, flags, 0600);
    if (fd < 0) fail(j, "Cannot create exclusive output staging file");
    j->temporary = 1;
    j->destination = fdopen(fd, "wb");
    if (!j->destination) { close(fd); fail(j, "Cannot open output stream"); }
    j->created[2] = 1;
    jpeg_create_compress(&j->output);
    jpeg_stdio_dest(&j->output, j->destination);
    j->output.image_width = j->width; j->output.image_height = j->height;
    j->output.input_components = 3; j->output.in_color_space = JCS_RGB;
    jpeg_set_defaults(&j->output); jpeg_set_quality(&j->output, 95, TRUE);
    for (int i = 0; i < 3; ++i) {
        j->output.comp_info[i].h_samp_factor = 1;
        j->output.comp_info[i].v_samp_factor = 1;
    }
    jpeg_start_compress(&j->output, TRUE); write_metadata(j);
    for (unsigned y = 0; y < j->height; ++y) {
        if (cancelled) fail(j, "Composition cancelled");
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
    for (int i = 0; i < 2; ++i) {
        struct stat after;
        if (!jpeg_finish_decompress(&j->input[i]) ||
            fstat(fileno(j->source[i]), &after) ||
            j->before[i].st_size != after.st_size || j->before[i].st_mtime != after.st_mtime)
            fail(j, "Input changed or was incomplete during composition");
    }
    jpeg_finish_compress(&j->output);
    if (fflush(j->destination) || fsync(fileno(j->destination)))
        fail(j, "Cannot flush output JPEG");
    int close_result = fclose(j->destination); j->destination = NULL;
    if (close_result) fail(j, "Cannot close output JPEG");
    if (cancelled) fail(j, "Composition cancelled");
    char publish_error[256];
    if (publish(j->temp, paths[2], publish_error, sizeof(publish_error)))
        fail(j, publish_error);
    j->temporary = 0; j->committed = 1;
}
int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        puts("a7c2-average 0.1; libjpeg-turbo " STRING_VALUE(LIBJPEG_TURBO_VERSION));
        return 0;
    }
    if (argc != 4) {
        fputs("Usage: a7c2-average first.jpg second.jpg new-result.jpg\n", stderr);
        return 2;
    }
    struct job *j = calloc(1, sizeof(*j));
    if (!j) { fputs("Cannot allocate composition state\n", stderr); return 1; }
    for (int i = 0; i < 3; ++i) {
        struct jpeg_error_mgr *error = jpeg_std_error(&j->error[i].base);
        j->error[i].job = j; error->error_exit = jpeg_failure;
        error->emit_message = jpeg_message;
        if (i < 2) j->input[i].err = error; else j->output.err = error;
    }
    signal(SIGINT, cancel_job); signal(SIGTERM, cancel_job);
    if (!setjmp(j->failed)) process(j, argv + 1);
    for (int i = 0; i < 2; ++i) {
        if (j->created[i]) jpeg_destroy_decompress(&j->input[i]);
        if (j->source[i]) fclose(j->source[i]);
    }
    if (j->created[2]) jpeg_destroy_compress(&j->output);
    if (j->destination) fclose(j->destination);
    if (j->temporary && unlink(j->temp))
        fprintf(stderr, "Staging cleanup failed: %s\n", strerror(errno));
    int result = j->committed ? 0 : 1;
    if (result) fprintf(stderr, "%s\n", j->message);
    else printf("{\"status\":\"saved\",\"width\":%u,\"height\":%u,"
                "\"orientation\":%u,\"mode\":\"mean-50-50\"}\n",
                j->width, j->height, j->orientation);
    free(j->rows); free(j);
    return result;
}
