/* Actual ARM64 shared core, synthetic SDK/AP callbacks and local JPEG files. */
#define _POSIX_C_SOURCE 200809L
#include "native_session.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static void fail(const char *c, unsigned n) { fprintf(stderr,"CHECK line %u: %s\n",n,c); exit(1); }
#define CHECK(c) ((c) ? (void)0 : fail(#c,__LINE__))
static const char *inputs[2], *mode;
static char temporary[4096], destination[4096];
static const char *native_inputs[2] = {"A:/DCIM/100MSDCF/DSC00001.JPG","A:/DCIM/100MSDCF/DSC00002.JPG"};
static FILE *files[16];
static unsigned opens, closes, issues, updates, selects, originals, publications, db_flushes;
static int private_directory, final_directory;
static unsigned find_index, reservations, cache_ready;
static unsigned review_journals, uncertain_uid;
static unsigned sdk_begin_originals;
static unsigned corrupted;
static void *expected_packet;
static void original_sdk_begin(void *packet);
static void original_sdk_finish(void *packet);
static a7_sony_event_function sdk_begin_slot=original_sdk_begin, sdk_finish_slot=original_sdk_finish;
static pthread_mutex_t read_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t read_cond=PTHREAD_COND_INITIALIZER;
static int read_paused, read_release;
static struct a7_sidb_record catalog[3];
static uint32_t get32(const void *p) { uint32_t v; memcpy(&v,p,4); return v; }
static void put32(void *p,uint32_t v) { memcpy(p,&v,4); }
static void put64(void *p,uint64_t v) { memcpy(p,&v,8); }
static int is(const char *name) { return !strcmp(mode,name); }
static int sdk_mode(void) { return is("sdk-forward")||is("sdk-fault")||is("sdk-auto"); }
static uint32_t selected_media(void) { return is("sdk-auto")?7:0; }
static const char *host_path(const char *native)
{
    if (!strcmp(native,native_inputs[0])) return inputs[0];
    if (!strcmp(native,native_inputs[1])) return inputs[1];
    if (strstr(native,"/MEAN.TMP")) return temporary;
    if (strstr(native,"/A7AV0001.JPG")) return destination;
    return NULL;
}
static int32_t file_open(char *path,uint32_t flags,uint64_t *handle)
{
    const char *host = host_path(path);
    if (!host || opens >= 16 || (flags != 1 && flags != 6) || (flags == 6 && !private_directory)) return -10;
    unsigned i = opens++;
    files[i] = fopen(host,flags == 1 ? "rb" : "wbx");
    if (!files[i]) return -11;
    *handle = 0x100000000ull + i; return 0;
}
static FILE *file(uint64_t handle) { unsigned i=(unsigned)(handle-0x100000000ull); return i<16?files[i]:NULL; }
static int32_t file_read(char drive,uint64_t handle,void *p,uint32_t n)
{
    FILE *f=file(handle); if(drive!='A'||!f)return -12;
    if(is("queued-disable")){
        pthread_mutex_lock(&read_mutex);
        if(!read_paused){read_paused=1;pthread_cond_signal(&read_cond);while(!read_release)pthread_cond_wait(&read_cond,&read_mutex);}
        pthread_mutex_unlock(&read_mutex);
    }
    if(n>29)n=29;
    size_t count=fread(p,1,n,f); return ferror(f)?-13:(int32_t)count;
}
static int32_t file_write(char drive,uint64_t handle,void *p,uint32_t n)
{
    FILE *f=file(handle); if(drive!='A'||!f)return -14;
    if(n>23)n=23;
    if(is("corrupt-write")&&!corrupted++){
        unsigned char changed[23];memcpy(changed,p,n);changed[0]^=1;
        size_t count=fwrite(changed,1,n,f);return ferror(f)?-15:(int32_t)count;
    }
    size_t count=fwrite(p,1,n,f); return ferror(f)?-15:(int32_t)count;
}
static int32_t file_close(char drive,uint64_t handle)
{
    FILE *f=file(handle); if(drive!='A'||!f)return -16;
    ++closes; int result=fclose(f); files[(unsigned)(handle-0x100000000ull)]=NULL;
    return result?-17:0;
}
static int32_t file_stat(char *path,uint64_t *bytes)
{ const char *host=host_path(path);struct stat st;if(!host||stat(host,&st))return -18;*bytes=(uint64_t)st.st_size;return 0; }
static int32_t file_flush(uint64_t handle) { FILE *f=file(handle);return !f||fflush(f)?-19:0; }
static int32_t mkdir_native(char *path)
{
    if(strstr(path,"/101A7AVG")){if(final_directory)return -20;final_directory=1;return 0;}
    if(strstr(path,"/A700007B")){if(private_directory)return -20;private_directory=1;return 0;}
    return -20;
}
static int32_t first(char *path,uint8_t flags,void *find)
{ CHECK(!strcmp(path,"A:/DCIM/*")&&flags==0x80);find_index=0;*(const char **)find="100MSDCF";return 0; }
static int32_t next(void *find)
{ if(final_directory && !find_index++){*(const char **)find="101A7AVG";return 0;}return 2; }
static int reserve_number(void *ctx,uint32_t media,uint16_t number,const char *name)
{ (void)ctx;CHECK(media==selected_media()&&number==101&&!strcmp(name,"101A7AVG"));++reservations;return 0; }
static int ready_number(void *ctx,uint32_t media,uint16_t number,const char *name)
{ (void)ctx;CHECK(media==selected_media()&&number==101&&!strcmp(name,"101A7AVG")&&final_directory);++cache_ready;return 0; }
static int32_t move_file(char *source,char *target)
{
    ++publications;
    CHECK(strstr(source,"/MEAN.TMP")&&strstr(target,"/101A7AVG/A7AV0001.JPG"));
    if(is("publish-error"))return -21;
    if(link(temporary,destination)||unlink(temporary))return -22;
    return 0;
}
static void clear(void *p) { memset(p,0,A7_SIDB_RECORD_BYTES); }
static int32_t select_record(uint32_t flags,uint32_t uid,void *p,uint8_t verbose)
{
    CHECK(flags==UINT32_MAX&&!verbose);++selects;
    unsigned i=uid==0?0:uid==2?1:uid==9?2:3;
    if(i==3)return -23;
    memcpy(p,&catalog[i],sizeof(catalog[i]));
    if(i==2&&is("verify-error"))((uint8_t *)p)[0xc1]='B';
    return 0;
}
static int32_t issue(uint32_t media,uint32_t *uid,uint8_t verbose)
{ CHECK(media==selected_media()&&!verbose);++issues;*uid=9;return is("issue-error")?-24:0; }
static int32_t update(uint32_t flags,const void *p,uint8_t a,uint8_t b)
{ CHECK(flags==UINT32_MAX&&!a&&!b);++updates;memcpy(&catalog[2],p,sizeof(catalog[2]));return is("update-error")?-25:0; }
static int32_t media(uint32_t uid,uint32_t *out) { (void)uid;*out=selected_media();return 0; }
static int32_t db_flush(uint32_t media) { CHECK(media==selected_media());++db_flushes;return is("flush-error")?-28:0; }
static void *sdk_open(void *ctx,const char *name,int flags)
{ (void)ctx;CHECK(flags==6);return !strcmp(name,"libmpr.so")?(void *)1:(void *)2; }
static void *sdk_symbol(void *ctx,void *module,const char *name)
{
    (void)ctx;(void)module;
    const char *names[]={"_ZN3mpr4file4OpenEPcNS0_8OpenFlagEPm","_ZN3mpr4file4ReadEcmPvj",
        "_ZN3mpr4file5WriteEcmPvj","_ZN3mpr4file5CloseEcm","_ZN3mpr4file4StatEPcPm","Fsys_Flush","Fsys_Mkdir"};
    void *values[]={(void *)file_open,(void *)file_read,(void *)file_write,(void *)file_close,
        (void *)file_stat,(void *)file_flush,(void *)mkdir_native};
    for(unsigned i=0;i<7;++i)if(!strcmp(name,names[i]))return values[i];
    return NULL;
}
static int sdk_close(void *ctx,void *module) { (void)ctx;(void)module;return 0; }
static int sdk_owner(void *ctx,void *symbol,const char *module) { (void)ctx;(void)symbol;(void)module;return 1; }
static void *sdk_pin(void *ctx) { (void)ctx;return (void *)3; }
static pthread_mutex_t native_mutex=PTHREAD_MUTEX_INITIALIZER;
static struct a7_delegate_object original;
static struct a7_delegate_object *delegate_slot=&original;
static void original_notify(struct a7_delegate_object *object,void *payload)
{ CHECK(object==&original);++originals;free(payload); }
static void (*original_methods[1])(struct a7_delegate_object *,void *)={original_notify};
static int native_lock(void *ctx) { (void)ctx;return pthread_mutex_lock(&native_mutex); }
static int native_unlock(void *ctx) { (void)ctx;return pthread_mutex_unlock(&native_mutex); }
static a7_pipe_sink begin_sink;
static void *begin_context;
static uint64_t epoch,generation;
static uint32_t media_id;
static int begin_attach(a7_pipe_sink sink,void *ctx,uint64_t e,uint32_t m,uint64_t g)
{
    begin_sink=sink;begin_context=ctx;epoch=e;media_id=m;generation=g;
    if(sdk_mode()){
        struct a7_sony_event_slots slots={&sdk_begin_slot,&sdk_finish_slot,original_sdk_begin,original_sdk_finish};
        return a7_sony_events_attach_bound(&slots,sink,ctx,e,m,g);
    }
    return 0;
}
static int begin_detach(void *ctx)
{
    CHECK(ctx==begin_context);if(is("detach-error"))return -26;
    if(sdk_mode()){int status=a7_sony_begin_detach(ctx);if(status)return status;}
    begin_sink=NULL;return 0;
}
static void original_sdk_begin(void *packet)
{ CHECK(packet==expected_packet);++sdk_begin_originals;memset(packet,0x99,0x58); }
static void original_sdk_finish(void *packet)
{ CHECK(packet==expected_packet);++originals;memset(packet,0x99,0x58); }
static void emit_sdk(uint32_t uid,int finish)
{
    uint32_t *packet=calloc(1,0x58);CHECK(packet);
    packet[0]=finish?0x100c:0x100d;packet[1]=1;packet[2]=selected_media();packet[3]=uid;packet[4]=1;
    if(finish&&is("sdk-fault"))packet[0x15]=5;
    expected_packet=packet;
    (finish?sdk_finish_slot:sdk_begin_slot)(packet);
    free(packet);expected_packet=NULL;
}
static void emit_begin(uint32_t uid)
{
    if(sdk_mode()){emit_sdk(uid,0);return;}
    struct a7_pipe_event e={0};e.kind=A7_PIPE_BEGIN;e.epoch=epoch;e.media=media_id;e.generation=generation;
    e.content=uid;e.capture=(uint64_t)uid+1;CHECK(begin_sink);begin_sink(begin_context,&e);
}
static void emit_finish(uint32_t uid)
{
    if(sdk_mode()){emit_sdk(uid,1);return;}
    uint32_t *payload=calloc(1,20);CHECK(payload);payload[0]=0;payload[1]=uid;payload[2]=1;
    CHECK(!pthread_mutex_lock(&native_mutex));
    delegate_slot->vtable[0](delegate_slot,payload);
    CHECK(!pthread_mutex_unlock(&native_mutex));
}
static int journal_pipeline(void *ctx,const struct a7_pipe_snapshot *s)
{ (void)ctx;return is("journal-error")&&s->step==A7_PIPE_ENCODE&&s->intent?-27:0; }
static int journal_request(void *ctx,const struct a7_device_report *s)
{ (void)ctx;if(s->review){++review_journals;uncertain_uid=s->pipeline.catalog_uid;}return 0; }
static int journal_dcf(void *ctx,const struct a7_dcf_state *s) { (void)ctx;(void)s;return 0; }
static void wire(uint8_t out[64],unsigned op,uint64_t id,const uint8_t instance[16])
{
    memset(out,0,64);memcpy(out,"A7DEX001",8);put32(out+8,op);put64(out+16,id);memcpy(out+48,instance,16);
    if(op==A7_DEVICE_ARM){put64(out+24,1);put64(out+32,1);put32(out+44,123);}
}
static struct a7_device_report wait_result(struct a7_native_session *s,unsigned phase)
{
    struct a7_device_report report={0};
    for(unsigned i=0;i<10000;++i){
        int status=a7_native_session_poll(s,&report);
        if(!report.intent&&(status<0||report.pipeline.pair.phase==phase))return report;
        struct timespec delay={0,1000000};nanosleep(&delay,NULL);
    }
    CHECK(0);return report;
}
int main(int argc,char **argv)
{
    if(argc!=5)return 2;
    inputs[0]=argv[1];inputs[1]=argv[2];mode=argv[4];
    CHECK(snprintf(temporary,sizeof(temporary),"%s/MEAN.TMP",argv[3])<(int)sizeof(temporary));
    CHECK(snprintf(destination,sizeof(destination),"%s/A7AV0001.JPG",argv[3])<(int)sizeof(destination));
    original.vtable=original_methods;
    for(unsigned i=0;i<2;++i){uint8_t *r=(uint8_t *)&catalog[i];put32(r,1);put32(r+4,i?2:0);
        for(unsigned j=0;j<12;++j)r[12+j]=(uint8_t)j;
        r[0xc0]=1;strcpy((char *)r+0xc1,native_inputs[i]);}
    struct a7_ap_loader loader={NULL,sdk_open,sdk_symbol,sdk_close,sdk_owner,sdk_pin,NULL};
    struct a7_ap_report runtime;CHECK(!a7_ap_start(&loader,&runtime));
    struct a7_sony_sdk sdk={0};sdk.bound=1;
    sdk.catalog=(struct a7_catalog_api){clear,select_record,issue,update,media,db_flush};
    sdk.dcf.first=first;sdk.dcf.next=next;sdk.dcf.mkdir=mkdir_native;sdk.dcf.move=move_file;
    sdk.dcf.files=(struct a7_mpr_api){file_open,file_read,file_write,file_close,file_stat,file_flush};
    sdk.dcf.reserve=reserve_number;sdk.dcf.ready=ready_number;
    struct a7_native_bindings bindings={&sdk,{NULL,&delegate_slot,native_lock,native_unlock},begin_attach,begin_detach};
    if(sdk_mode())memset(&bindings.finish,0,sizeof(bindings.finish));
    struct a7_native_journal journal={NULL,journal_pipeline,journal_request,journal_dcf};
    const uint8_t instance[16]="INSTANCE-0000001";
    int status=0;struct a7_native_session *session=a7_native_session_create_bound(instance,&bindings,&journal,&status);
    CHECK(session&&!status);
    uint8_t request[64];struct a7_device_report report;
    wire(request,A7_DEVICE_ARM,1,instance);if(is("sdk-auto"))put32(request+40,UINT32_MAX);
    CHECK(!a7_native_session_submit(session,request,64,&report)&&report.intent);
    report=wait_result(session,A7_PAIR_COLLECTING);CHECK(!report.status);
    if(sdk_mode())CHECK(delegate_slot==&original);
    emit_begin(0);emit_begin(2);emit_finish(2);emit_finish(0);
    if(is("queued-disable")){
        pthread_mutex_lock(&read_mutex);
        struct timespec deadline;clock_gettime(CLOCK_REALTIME,&deadline);deadline.tv_sec+=5;
        while(!read_paused)CHECK(!pthread_cond_timedwait(&read_cond,&read_mutex,&deadline));
        wire(request,A7_DEVICE_DISABLE,2,instance);CHECK(!a7_native_session_submit(session,request,64,&report)&&report.intent);
        read_release=1;pthread_cond_signal(&read_cond);pthread_mutex_unlock(&read_mutex);
    }
    report=wait_result(session,A7_PAIR_COMPLETE);
    int success=is("success")||is("detach-error")||is("queued-disable")||is("sdk-forward")||is("sdk-auto");
    if(success){
        CHECK(!report.status&&report.pipeline.pair.phase==A7_PAIR_COMPLETE);
        CHECK(report.pipeline.pair.media_id==selected_media());
        CHECK(issues==1&&updates==1&&db_flushes==1&&publications==1&&originals==2&&reservations==1&&cache_ready==1);
        CHECK(get32((uint8_t *)&catalog[2]+4)==9);
        if(!is("queued-disable")){
            wire(request,A7_DEVICE_DISABLE,2,instance);CHECK(!a7_native_session_submit(session,request,64,&report));
            report=wait_result(session,A7_PAIR_COMPLETE);
        }
        if(is("detach-error")){CHECK(report.review);CHECK(a7_native_session_destroy(session)!=0);}
        else{
            CHECK(!report.status&&!report.pipeline.active&&delegate_slot==&original&&!begin_sink);
            CHECK(!a7_native_session_destroy(session));CHECK(!a7_ap_query(&runtime));
            if(is("sdk-forward")||is("sdk-auto")){
                CHECK(!runtime.jobs&&runtime.callbacks==1);
                CHECK(a7_ap_retire(&runtime)==A7_AP_BUSY&&!runtime.release_handle);
                CHECK(delegate_slot==&original);
                emit_sdk(50,0);emit_sdk(50,1);
                CHECK(sdk_begin_originals==3&&originals==3&&issues==1&&updates==1);
            }else{CHECK(!runtime.jobs&&!runtime.callbacks);CHECK(!a7_ap_retire(&runtime));CHECK(runtime.release_handle);}
        }
    }else{
        CHECK(report.status<0&&report.review&&report.pipeline.pair.phase==A7_PAIR_REVIEW);
        CHECK(review_journals>=1);
        CHECK(a7_native_session_destroy(session)!=0);
        if(is("issue-error"))CHECK(issues==1&&!updates&&uncertain_uid==9);
        if(is("update-error")||is("verify-error"))CHECK(updates==1&&uncertain_uid==9);
        if(is("flush-error"))CHECK(db_flushes==1&&updates==1&&uncertain_uid==9);
        if(is("publish-error")||is("journal-error")||is("corrupt-write"))CHECK(!issues&&!updates);
        if(is("corrupt-write"))CHECK(!reservations&&!publications);
        if(is("sdk-fault")){
            CHECK(!issues&&!updates&&!opens&&delegate_slot==&original);
            unsigned count=review_journals;emit_sdk(50,0);emit_sdk(50,1);
            a7_native_session_poll(session,&report);CHECK(!report.intent&&review_journals==count);
        }
    }
    for(unsigned i=0;i<16;++i)if(files[i])fclose(files[i]); /* local fixture cleanup only */
    printf("{\"backend\":\"synthetic-sdk-and-ap\",\"verified\":true,\"camera_io\":false,"
           "\"issues\":%u,\"updates\":%u,\"original_callbacks\":%u,\"status\":%d}\n",issues,updates,originals,report.status);
    return 0;
}
