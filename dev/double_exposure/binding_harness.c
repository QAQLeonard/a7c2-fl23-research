/* Real dlopen/dlsym/refcount tests against synthetic SDK libraries. */
#define _GNU_SOURCE
#include <stdlib.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include "ap_runtime.h"
typedef int (*start_fn)(const struct a7_ap_loader *, struct a7_ap_report *);
typedef int (*query_fn)(struct a7_ap_report *);
typedef int (*acquire_fn)(uint32_t, struct a7_ap_lease *, struct a7_ap_report *);
typedef int (*release_fn)(struct a7_ap_lease *, struct a7_ap_report *);
typedef uint32_t (*abi_fn)(void);
typedef unsigned (*count_fn)(void);
static void failed(const char *condition, unsigned line)
{ fprintf(stderr, "CHECK failed at line %u: %s\n", line, condition); exit(1); }
#define CHECK(condition) ((condition) ? (void)0 : failed(#condition, __LINE__))
static int loaded(const char *path)
{
    void *handle = dlopen(path, RTLD_NOW | RTLD_NOLOAD | RTLD_LOCAL);
    if (!handle) return 0;
    CHECK(dlclose(handle) == 0); return 1;
}
int main(int argc, char **argv)
{
    if (argc != 4) return 2;
    const char *mode = argv[3];
    char mpr_path[4096], fsys_path[4096];
    CHECK(snprintf(mpr_path, sizeof(mpr_path), "%s/libmpr.so", argv[2]) < (int)sizeof(mpr_path));
    CHECK(snprintf(fsys_path, sizeof(fsys_path), "%s/libInfraFsys.so", argv[2]) < (int)sizeof(fsys_path));
    CHECK(!loaded(argv[1]) && !loaded(mpr_path) && !loaded(fsys_path));
    void *core = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!core) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    abi_fn abi = (abi_fn)dlsym(core, "a7_ap_runtime_abi");
    start_fn start = (start_fn)dlsym(core, "a7_ap_start");
    query_fn query = (query_fn)dlsym(core, "a7_ap_query");
    query_fn retire = (query_fn)dlsym(core, "a7_ap_retire");
    acquire_fn acquire = (acquire_fn)dlsym(core, "a7_ap_acquire");
    release_fn release = (release_fn)dlsym(core, "a7_ap_release");
    CHECK(abi && start && query && retire && acquire && release && abi() == 1);
    struct a7_ap_report report;
    if (!strcmp(mode, "missing")) {
        CHECK(start(NULL, &report) == A7_AP_MPR_MISSING);
        CHECK(report.phase == A7_AP_IDLE && report.owned_sdk_mask == 0 && report.release_handle);
        CHECK(dlclose(report.release_handle) == 0);
        CHECK(query(&report) == 0 && !report.release_handle);
        CHECK(dlclose(core) == 0 && !loaded(argv[1]));
        puts("{\"backend\":\"synthetic-sdk-libraries\",\"missing_not_loaded\":true}"); return 0;
    }
    void *mpr = dlopen(mpr_path, RTLD_NOW | RTLD_LOCAL); CHECK(mpr);
    count_fn mpr_calls = (count_fn)dlsym(mpr, "a7_fixture_calls"); CHECK(mpr_calls && !mpr_calls());
    if (!strcmp(mode, "partial")) {
        CHECK(start(NULL, &report) == A7_AP_FSYS_MISSING);
        CHECK(report.phase == A7_AP_IDLE && !report.owned_sdk_mask && report.release_handle);
        CHECK(dlclose(report.release_handle) == 0 && !mpr_calls());
        CHECK(loaded(mpr_path)); CHECK(dlclose(core) == 0 && !loaded(argv[1]));
        CHECK(dlclose(mpr) == 0 && !loaded(mpr_path));
        puts("{\"backend\":\"synthetic-sdk-libraries\",\"partial_balanced\":true}"); return 0;
    }
    void *fsys = dlopen(fsys_path, RTLD_NOW | RTLD_LOCAL); CHECK(fsys);
    count_fn fsys_calls = (count_fn)dlsym(fsys, "a7_fixture_calls"); CHECK(fsys_calls && !fsys_calls());
    CHECK(start(NULL, &report) == 0 && report.phase == A7_AP_BOUND && report.bound_mask == 127);
    CHECK(!report.release_handle && !mpr_calls() && !fsys_calls());
    CHECK(start(NULL, &report) == A7_AP_ALREADY);
    struct a7_ap_lease job = {0}, callback = {0};
    CHECK(acquire(A7_AP_JOB, &job, &report) == 0);
    CHECK(acquire(A7_AP_CALLBACK, &callback, &report) == 0);
    CHECK(job.mkdir && !callback.mkdir);
    CHECK(report.jobs == 1 && report.callbacks == 1);
    uint64_t first_generation = report.generation;
    struct a7_ap_lease old_job = job;
    CHECK(dlclose(core) == 0 && loaded(argv[1])); /* only self pin now holds the core */
    core = dlopen(argv[1], RTLD_NOW | RTLD_NOLOAD | RTLD_LOCAL); CHECK(core);
    char buffer[7];
    CHECK(job.api.read('A', 0x100000001ull, buffer, sizeof(buffer)) == 7);
    CHECK(!memcmp(buffer, "RRRRRRR", 7));
    CHECK(job.api.flush(0x100000001ull) == 0);
    CHECK(mpr_calls() == 1 && fsys_calls() == 1);
    CHECK(retire(&report) == A7_AP_BUSY && !report.release_handle);
    CHECK(release(&job, &report) == 0);
    CHECK(retire(&report) == A7_AP_BUSY && report.callbacks == 1);
    CHECK(release(&callback, &report) == 0);
    CHECK(release(&old_job, &report) == A7_AP_LEASE);
    CHECK(retire(&report) == 0 && report.release_handle);
    CHECK(dlclose(report.release_handle) == 0); /* caller drops pin outside the core */
    if (!strcmp(mode, "repeat")) {
        CHECK(start(NULL, &report) == 0 && report.generation != first_generation);
        CHECK(acquire(A7_AP_JOB, &job, &report) == 0);
        CHECK(release(&old_job, &report) == A7_AP_LEASE && report.jobs == 1);
        CHECK(release(&job, &report) == 0);
        CHECK(retire(&report) == 0 && report.release_handle);
        CHECK(dlclose(report.release_handle) == 0);
    }
    CHECK(loaded(mpr_path) && loaded(fsys_path)); /* AP's original refs remain */
    CHECK(dlclose(core) == 0 && !loaded(argv[1]));
    CHECK(mpr_calls() == 1 && fsys_calls() == 1);
    CHECK(dlclose(fsys) == 0 && dlclose(mpr) == 0);
    CHECK(!loaded(fsys_path) && !loaded(mpr_path));
    puts("{\"backend\":\"synthetic-sdk-libraries\",\"self_pin\":true,"
         "\"leases_guarded\":true,\"sdk_refs_preserved\":true,\"core_unloaded\":true}");
    return 0;
}
