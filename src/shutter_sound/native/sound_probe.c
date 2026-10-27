/* Read-only sound registry preflight. Reuses the existing libJit model probe.
 * No playback, CP RAM writes, registration calls, settings, mounts or boot
 * changes. The only output files are owned temporary diagnostic reports.
 */
#define _init sound_base_init
#include "probe.c"
#undef _init
#include PATCH_MANIFEST

struct SoundReport {
    u8 magic[8];u32 version,index;i64 status;u64 base;
    u32 audio,reserved;u8 entries[25][176];u8 image_mode[16];
};
static struct SoundReport sound;
_Static_assert(sizeof(struct SoundReport)==4456,"Sound preflight ABI");
static int equal(const u8*a,const u8*b,u32 n) {
    for(u32 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;
}
static i64 get(i64 fd,u64 at,void*out,u32 n) {
    i64 r=sc(67,fd,(i64)out,n,report.base+at,0,0);
    return r==(i64)n?0:(r<0?r:-5);
}
__attribute__((visibility("default"))) void _init(void) {
    sound_base_init();
    const u8 tag[]="A7SND001";for(u32 i=0;i<8;i++)sound.magic[i]=tag[i];
    sound.version=1;sound.index=report.index;sound.base=report.base;
    sound.status=report.status;
    if(!sound.status&&(report.index!=16||report.euid))sound.status=-22;
    i64 fd=-1;
    if(!sound.status) {
        fd=op("/proc/self/mem",0);if(fd<0)sound.status=fd;
    }
    if(!sound.status) {
        u8 code[64];
        sound.status=get(fd,0x286cde8,code,20);
        if(!sound.status&&!equal(code,audio_getter,20))sound.status=-84;
        if(!sound.status)sound.status=get(fd,0x2885488,code,20);
        if(!sound.status&&!equal(code,table_getter,20))sound.status=-84;
#ifdef CHECK_EXTRA_GUARDS
        for(u32 i=0;i<extra_guard_count&&!sound.status;i++) {
            if(extra_guards[i].length>sizeof(code)) {sound.status=-22;break;}
            sound.status=get(fd,extra_guards[i].offset,code,extra_guards[i].length);
            if(!sound.status&&!equal(code,extra_guards[i].bytes,extra_guards[i].length))sound.status=-84;
        }
#endif
        if(!sound.status)sound.status=get(fd,0x7e735b8,&sound.audio,4);
        for(u32 i=0;i<25&&!sound.status;i++)
            sound.status=get(fd,0x7ed2098UL+176UL*i,sound.entries[i],176);
    }
    cl(fd);
    i64 n=read_all("/sys/power/image_mode",sound.image_mode,sizeof(sound.image_mode));
    if(n<0&&!sound.status)sound.status=n;
    fd=op("/tmp/jiritsu/shutter.probe.result",0x241);
    if(fd>=0) {write_all(fd,&sound,sizeof(sound));sc(82,fd,0,0,0,0,0);cl(fd);}
}
