#include "capture_pair.h"

static void clear(void *p, size_t size)
{
    volatile uint8_t *bytes = p;
    while (size--) *bytes++ = 0;
}
static int drive_path(const char *path)
{
    return path && ((path[0] >= 'A' && path[0] <= 'Z') ||
                    (path[0] >= 'a' && path[0] <= 'z')) && path[1] == ':' && path[2] == '/';
}
static size_t path_length(const char *path)
{
    if (!path) return 0;
    size_t prefix = path[0] == '/' ? 1 : drive_path(path) ? 3 : 0;
    if (!prefix) return 0;
    for (size_t i = prefix; i < A7_PAIR_PATH_BYTES; ++i) {
        if (!path[i]) return i > prefix ? i : 0;
        if (path[i] == '\n' || path[i] == '\r') return 0;
    }
    return 0;
}
static int same(const char *a, const char *b)
{
    int fold = drive_path(a) && drive_path(b);
    for (size_t i = 0; i < A7_PAIR_PATH_BYTES; ++i) {
        unsigned char x = a[i], y = b[i];
        if (fold) {
            if (x >= 'A' && x <= 'Z') x += 'a' - 'A';
            if (y >= 'A' && y <= 'Z') y += 'a' - 'A';
        }
        if (x != y) return 0;
        if (!a[i]) return 1;
    }
    return 0;
}
static void copy_path(char *dest, const char *src)
{
    volatile char *out = dest;
    size_t i = 0;
    do { out[i] = src[i]; } while (src[i++]);
}
static void copy_shot(struct a7_pair_shot *out, const struct a7_pair_shot *in)
{
    out->capture_id = in->capture_id; out->content_id = in->content_id;
    out->started = in->started; out->complete = in->complete;
    copy_path(out->path, in->path);
}
static int epoch_matches(const struct a7_pair_session *s, uint64_t epoch)
{
    return s && epoch && s->epoch == epoch;
}
static int conflict(struct a7_pair_session *s)
{
    s->phase = A7_PAIR_REVIEW;
    return A7_PAIR_CONFLICT;
}
static int source_path(const struct a7_pair_session *s, const char *path)
{
    return same(s->shots[0].path, path) || same(s->shots[1].path, path);
}
size_t a7_pair_session_size(void) { return sizeof(struct a7_pair_session); }

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
int a7_pair_decode_capture_result(const uint8_t *raw, size_t size, uint32_t media,
                                 struct a7_pair_capture_identity *out)
{
    if (!raw || !out || size != 56) return A7_PAIR_INVALID;
    uint32_t count = le32(raw + 4);
    if (le32(raw) || !count) return A7_PAIR_IGNORED;
    if (count > 4) return A7_PAIR_INVALID;
    unsigned found = 4;
    for (unsigned i = 0; i < count; ++i) {
        if (le32(raw + 8 + i * 4) != media) continue;
        if (found != 4) return A7_PAIR_CONFLICT;
        found = i;
    }
    if (found == 4) return A7_PAIR_IGNORED;
    uint32_t content = le32(raw + 24 + found * 4);
    uint16_t directory = le16(raw + 40 + found * 2), file = le16(raw + 48 + found * 2);
    out->media_id = media; out->content_id = content;
    out->directory_number = directory; out->file_number = file;
    return A7_PAIR_OK;
}

int a7_pair_arm(struct a7_pair_session *s, uint64_t epoch, uint32_t media, uint64_t generation)
{
    if (!s || !epoch || !generation || epoch <= s->epoch) return A7_PAIR_INVALID;
    if (s->phase != A7_PAIR_IDLE && s->phase != A7_PAIR_COMPLETE &&
        s->phase != A7_PAIR_FAILED && s->phase != A7_PAIR_CANCELLED) return A7_PAIR_BUSY;
    clear(s, sizeof(*s)); s->epoch = epoch; s->media_id = media;
    s->media_generation = generation; s->result_id = A7_PAIR_NO_CONTENT;
    s->phase = A7_PAIR_COLLECTING;
    return A7_PAIR_OK;
}
int a7_pair_begin(struct a7_pair_session *s, uint64_t epoch, uint64_t capture)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (!capture) return A7_PAIR_INVALID;
    if (s->phase != A7_PAIR_COLLECTING) return A7_PAIR_IGNORED;
    for (unsigned i = 0; i < 2; ++i) {
        if (s->shots[i].started && s->shots[i].capture_id == capture) return A7_PAIR_IGNORED;
        if (!s->shots[i].started) {
            s->shots[i].capture_id = capture; s->shots[i].content_id = A7_PAIR_NO_CONTENT;
            s->shots[i].started = 1; return A7_PAIR_OK;
        }
    }
    return A7_PAIR_IGNORED;
}
int a7_pair_saved(struct a7_pair_session *s, uint64_t epoch, uint64_t capture,
                  uint32_t media, uint64_t generation, uint64_t content,
                  const char *path, uint32_t outcome)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (s->phase != A7_PAIR_COLLECTING && s->phase != A7_PAIR_READY)
        return A7_PAIR_IGNORED;
    struct a7_pair_shot *shot = NULL;
    for (unsigned i = 0; i < 2; ++i)
        if (s->shots[i].started && s->shots[i].capture_id == capture) shot = &s->shots[i];
    if (!shot) return A7_PAIR_IGNORED;
    if (outcome > A7_PAIR_UNKNOWN) return A7_PAIR_INVALID;
    if (media != s->media_id || generation != s->media_generation || outcome == A7_PAIR_UNKNOWN)
        return conflict(s);
    if (shot->complete) {
        if (outcome == A7_PAIR_SUCCESS && content == shot->content_id && path_length(path) &&
            same(shot->path, path)) return A7_PAIR_IGNORED;
        return conflict(s);
    }
    if (outcome == A7_PAIR_NO_CHANGE) { s->phase = A7_PAIR_FAILED; return A7_PAIR_OK; }
    if (content == A7_PAIR_NO_CONTENT || !path_length(path)) return A7_PAIR_INVALID;
    struct a7_pair_shot *other = shot == &s->shots[0] ? &s->shots[1] : &s->shots[0];
    if (other->complete && (other->content_id == content || same(other->path, path)))
        return conflict(s);
    shot->content_id = content; copy_path(shot->path, path); shot->complete = 1;
    if (s->shots[0].complete && s->shots[1].complete) s->phase = A7_PAIR_READY;
    return A7_PAIR_OK;
}
int a7_pair_take(struct a7_pair_session *s, uint64_t epoch, const char *staging,
                 struct a7_pair_job *job)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (!job || !path_length(staging) || staging[0] != '/') return A7_PAIR_INVALID;
    if (s->phase != A7_PAIR_READY) return A7_PAIR_BUSY;
    if (source_path(s, staging)) return A7_PAIR_INVALID;
    clear(job, sizeof(*job)); job->epoch = s->epoch; job->media_id = s->media_id;
    job->media_generation = s->media_generation;
    copy_shot(&job->shots[0], &s->shots[0]); copy_shot(&job->shots[1], &s->shots[1]);
    copy_path(job->staging, staging); copy_path(s->staging, staging);
    s->phase = A7_PAIR_PROCESSING;
    return A7_PAIR_OK;
}
int a7_pair_encoded(struct a7_pair_session *s, uint64_t epoch, uint32_t outcome)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (outcome > A7_PAIR_UNKNOWN) return A7_PAIR_INVALID;
    if (s->phase != A7_PAIR_PROCESSING && s->phase != A7_PAIR_CANCELLING) return A7_PAIR_BUSY;
    if (outcome == A7_PAIR_UNKNOWN) return conflict(s);
    s->phase = s->phase == A7_PAIR_CANCELLING ? A7_PAIR_CANCELLED :
               outcome == A7_PAIR_SUCCESS ? A7_PAIR_ENCODED : A7_PAIR_FAILED;
    return A7_PAIR_OK;
}
int a7_pair_register(struct a7_pair_session *s, uint64_t epoch,
                     uint32_t media, uint64_t generation)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (s->phase != A7_PAIR_ENCODED) return A7_PAIR_BUSY;
    if (media != s->media_id || generation != s->media_generation) return conflict(s);
    s->phase = A7_PAIR_REGISTERING;
    return A7_PAIR_OK;
}
int a7_pair_registered(struct a7_pair_session *s, uint64_t epoch, uint32_t outcome,
                       uint64_t content, const char *path)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (outcome > A7_PAIR_UNKNOWN) return A7_PAIR_INVALID;
    if (s->phase != A7_PAIR_REGISTERING) return A7_PAIR_BUSY;
    if (outcome == A7_PAIR_UNKNOWN) return conflict(s);
    if (outcome == A7_PAIR_NO_CHANGE) { s->phase = A7_PAIR_FAILED; return A7_PAIR_OK; }
    if (content == A7_PAIR_NO_CONTENT || content == s->shots[0].content_id ||
        content == s->shots[1].content_id || !path_length(path) || source_path(s, path) ||
        same(s->staging, path)) return conflict(s);
    s->result_id = content; copy_path(s->result, path); s->phase = A7_PAIR_VERIFYING;
    return A7_PAIR_OK;
}
int a7_pair_verified(struct a7_pair_session *s, uint64_t epoch, uint32_t media,
                     uint64_t generation, uint64_t content, const char *path)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (s->phase != A7_PAIR_VERIFYING) return A7_PAIR_BUSY;
    if (media != s->media_id || generation != s->media_generation ||
        content != s->result_id || !path_length(path) || !same(s->result, path)) return conflict(s);
    s->phase = A7_PAIR_COMPLETE;
    return A7_PAIR_OK;
}
int a7_pair_cancel(struct a7_pair_session *s, uint64_t epoch)
{
    if (!epoch_matches(s, epoch)) return A7_PAIR_IGNORED;
    if (s->phase == A7_PAIR_COLLECTING || s->phase == A7_PAIR_READY || s->phase == A7_PAIR_ENCODED)
        s->phase = A7_PAIR_CANCELLED;
    else if (s->phase == A7_PAIR_PROCESSING) s->phase = A7_PAIR_CANCELLING;
    else return A7_PAIR_BUSY;
    return A7_PAIR_OK;
}
