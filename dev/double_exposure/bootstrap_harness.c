/* Real loader control tests, with synthetic SDKs; no camera transport. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bootstrap.h"
static void failed(const char *condition, unsigned line)
{ fprintf(stderr, "CHECK failed at line %u: %s\n", line, condition); exit(1); }
#define CHECK(condition) ((condition) ? (void)0 : failed(#condition, __LINE__))
typedef int (*dispatch_fn)(const char *, uint32_t, const struct a7_boot_loader *, struct a7_boot_report *);
typedef int (*acquire_fn)(uint32_t, struct a7_ap_lease *, struct a7_ap_report *);
typedef int (*release_fn)(struct a7_ap_lease *, struct a7_ap_report *);
typedef unsigned (*count_fn)(void);
static int loaded(const char *path)
{
    void *h = dlopen(path, RTLD_NOW | RTLD_NOLOAD);
    if (!h) return 0;
    CHECK(!dlclose(h)); return 1;
}
int main(int argc, char **argv)
{
    if (argc != 5) return 2;
    const char *core = argv[3], *mode = argv[4];
    void *helper = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!helper) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    dispatch_fn dispatch = (dispatch_fn)dlsym(helper, "a7_boot_dispatch"); CHECK(dispatch);
    CHECK(!loaded(core));
    struct a7_boot_report report;
    CHECK(dispatch(core, A7_BOOT_QUERY, NULL, &report) == A7_BOOT_NOT_RESIDENT);
    CHECK(!report.called && !loaded(core));
    CHECK(dispatch(core, A7_BOOT_RETIRE, NULL, &report) == A7_BOOT_NOT_RESIDENT);
    CHECK(!report.called && !loaded(core));
    if (!strcmp(mode, "absent")) goto done;
    if (!strcmp(mode, "missing-sdk")) {
        CHECK(dispatch(core, A7_BOOT_START, NULL, &report) == A7_AP_MPR_MISSING);
        CHECK(report.called && report.close_attempts == 3 && !report.runtime.release_handle);
        CHECK(!loaded(core)); goto done;
    }
    char mpr_path[4096], fsys_path[4096];
    CHECK(snprintf(mpr_path, sizeof(mpr_path), "%s/libmpr.so", argv[2]) < (int)sizeof(mpr_path));
    CHECK(snprintf(fsys_path, sizeof(fsys_path), "%s/libInfraFsys.so", argv[2]) < (int)sizeof(fsys_path));
    void *mpr = dlopen(mpr_path, RTLD_NOW | RTLD_LOCAL); CHECK(mpr);
    void *fsys = dlopen(fsys_path, RTLD_NOW | RTLD_LOCAL); CHECK(fsys);
    count_fn mpr_calls = (count_fn)dlsym(mpr, "a7_fixture_calls"); CHECK(mpr_calls);
    count_fn fsys_calls = (count_fn)dlsym(fsys, "a7_fixture_calls"); CHECK(fsys_calls);
    CHECK(dispatch(core, A7_BOOT_START, NULL, &report) == 0);
    CHECK(report.called && report.runtime.phase == A7_AP_BOUND && report.runtime.bound_mask == 127);
    CHECK(loaded(core) && report.close_attempts == 2 && !report.runtime.release_handle);
    CHECK(dispatch(core, A7_BOOT_START, NULL, &report) == A7_AP_ALREADY);
    CHECK(dispatch(core, A7_BOOT_QUERY, NULL, &report) == 0 && report.runtime.phase == A7_AP_BOUND);
    if (!strcmp(mode, "busy")) {
        void *temporary = dlopen(core, RTLD_NOW | RTLD_NOLOAD); CHECK(temporary);
        acquire_fn acquire = (acquire_fn)dlsym(temporary, "a7_ap_acquire"); CHECK(acquire);
        release_fn release = (release_fn)dlsym(temporary, "a7_ap_release"); CHECK(release);
        struct a7_ap_report runtime;
        struct a7_ap_lease job = {0}, callback = {0};
        CHECK(!acquire(A7_AP_JOB, &job, &runtime));
        CHECK(!acquire(A7_AP_CALLBACK, &callback, &runtime));
        CHECK(dispatch(core, A7_BOOT_RETIRE, NULL, &report) == A7_AP_BUSY);
        CHECK(report.runtime.jobs == 1 && report.runtime.callbacks == 1 && loaded(core));
        CHECK(!release(&job, &runtime));
        CHECK(dispatch(core, A7_BOOT_RETIRE, NULL, &report) == A7_AP_BUSY);
        CHECK(report.runtime.jobs == 0 && report.runtime.callbacks == 1);
        CHECK(!release(&callback, &runtime));
        CHECK(!dlclose(temporary));
    }
    CHECK(dispatch(core, A7_BOOT_RETIRE, NULL, &report) == 0);
    CHECK(report.close_attempts == 3 && !report.runtime.release_handle && !report.review);
    CHECK(!loaded(core) && loaded(mpr_path) && loaded(fsys_path));
    CHECK(!mpr_calls() && !fsys_calls()); /* no SDK I/O/initialization */
    CHECK(dispatch(core, A7_BOOT_QUERY, NULL, &report) == A7_BOOT_NOT_RESIDENT);
    CHECK(!dlclose(fsys) && !dlclose(mpr));
done:
    CHECK(!dlclose(helper));
    puts("{\"backend\":\"synthetic-sdk-libraries\",\"control_verified\":true,\"camera_io\":false}");
    return 0;
}
