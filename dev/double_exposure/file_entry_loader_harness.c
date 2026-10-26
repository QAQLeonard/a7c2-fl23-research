/* Load the unmodified production helper. Run only in a private /tmp namespace. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "loader check failed: %s\n", #x); return 1; } } while (0)
int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    /* The launcher mounts an owned fixture over /tmp/jiritsu. Never create it. */
    struct stat state;
    CHECK(!stat("/tmp/jiritsu/.a7c2-constructor-fixture", &state));
    void *first = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!first) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    CHECK(!stat("/tmp/jiritsu/a7c2.dex.result", &state));
    if (!strcmp(argv[2], "retained") || !strcmp(argv[2], "reload")) {
        CHECK(!rename("/tmp/jiritsu/a7c2.dex.result", "/tmp/jiritsu/first.receipt"));
        if (!strcmp(argv[2], "reload")) { CHECK(!dlclose(first)); first = NULL; }
        void *second = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL); CHECK(second);
        int present = !stat("/tmp/jiritsu/a7c2.dex.result", &state);
        CHECK(present == !strcmp(argv[2], "reload"));
        CHECK(!dlclose(second));
    } else CHECK(!strcmp(argv[2], "once"));
    if (first) CHECK(!dlclose(first));
    puts("{\"constructor_checked\":true,\"explicit_entry_call\":false,\"camera_io\":false}");
    return 0;
}
