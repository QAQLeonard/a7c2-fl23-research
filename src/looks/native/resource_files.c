/* Fixed-allowlist resource cleanup and chunked atomic voice restoration.
 * Sources and expected digests are compiled from this request's fresh inventory.
 * No file outside that allowlist, its exact staging names and Jiritsu mailbox is
 * accepted. Every mutation requires the reviewed disable guards already loaded.
 */
#define _init resource_probe_init
#include "probe.c"
#undef _init
#include "sha256.h"
struct Request {u8 magic[8];u32 mode,index;u64 offset;u32 count,reserved;u8 prefix[32];};
struct Info {i64 status;u64 size,allocated;u8 hash[32];};
#include PATCH_MANIFEST
struct ResourceReport {u8 magic[8];u32 version,mode; i64 status,readonly,cleanup;
    u32 index,changed;u64 progress;struct Info files[FILE_COUNT],stages[FILE_COUNT];};
static struct Request req;
static struct ResourceReport out;
static u8 buffer[65536];
static int equal(const void*a,const void*b,u32 n) {const u8*x=a,*y=b;for(u32 i=0;i<n;i++)if(x[i]!=y[i])return 0;return 1;}
static i64 close_fd(i64 *fd) {if(*fd<0)return 0;i64 v=sc(57,*fd,0,0,0,0,0);*fd=-1;return v;}
static i64 regular(i64 fd,u64 *st) {
    i64 v=sc(80,fd,(i64)st,0,0,0,0);if(v)return v;
    return (((u32*)st)[4]&0170000)==0100000&&((u32*)st)[5]==1&&
        !((u32*)st)[6]&&!((u32*)st)[7]&&st[6]<=41943040?0:-22;
}
static i64 inspect(const char*path,struct Info *info) {
    i64 fd=op(path,0x20000);info->status=fd<0?fd:0;if(fd<0)return fd;
    u64 st[16];i64 v=regular(fd,st);SHA256 hash;sha_init(&hash);u64 at=0;
    if(!v){info->size=st[6];info->allocated=st[8]*512;}
    while(!v&&at<info->size) {
        u32 n=info->size-at>sizeof(buffer)?sizeof(buffer):info->size-at;
        i64 got=sc(67,fd,(i64)buffer,n,at,0,0);
        if(got==-4)continue;
        if(got<=0||(u64)got>n)v=got<0?got:-5;
        else {sha_add(&hash,buffer,got);at+=got;}
    }
    if(!v)sha_end(&hash,info->hash);
    i64 c=close_fd(&fd);if(!v)v=c;info->status=v;return v;
}
static int matches(const struct Info*a,const struct Info*b) {
    return a->status==b->status&&(a->status==-2||(!a->status&&a->size==b->size&&equal(a->hash,b->hash,32)));
}
static i64 mount_state(int ro) {
    i64 n=read_all("/proc/mounts",mounts,sizeof(mounts));if(n<0)return n;
    const u8 prefix[]="/dev/nflasha15 /usr ext2 ";u32 count=0,len=sizeof(prefix)-1;
    for(u32 i=0;i+len+3<=(u32)n;i++)if((!i||mounts[i-1]=='\n')&&equal(mounts+i,prefix,len)) {
        if(mounts[i+len]!='r'||mounts[i+len+1]!=(ro?'o':'w')||mounts[i+len+2]!=',')return -30;count++;
    }
    return count==1?0:-22;
}
static i64 remount(int ro) {i64 v=sc(40,0,(i64)"/usr",0,0xc30UL+(ro?1:0),0,0);return v?v:mount_state(ro);}
static i64 check_guards(void) {
    i64 fd=op("/proc/self/mem",0);if(fd<0)return fd;i64 v=0;
    for(u32 i=0;i<guard_count&&!v;i++) {
        if(guards[i].size>sizeof(buffer)){v=-22;break;}
        i64 n=sc(67,fd,(i64)buffer,guards[i].size,report.base+guards[i].offset,0,0);
        if(n!=(i64)guards[i].size||!equal(buffer,guards[i].bytes,guards[i].size))v=-84;
    }
#ifdef RESOURCE_PORTRAIT
    if(!v&&req.mode) {
        u32 value=0;
        i64 n=sc(67,fd,(i64)&value,4,report.base+0x7e732b8,0,0);
        if(n!=4||value!=1)v=-84;
    }
#endif
    close_fd(&fd);return v;
}
static i64 sync_dir(void) {
    i64 fd=op(resource_directory,0x10000);if(fd<0)return fd;
    i64 v=sc(82,fd,0,0,0,0,0),c=close_fd(&fd);return v?v:c;
}
static i64 current(u32 i,int stage,struct Info *value) {
    i64 v=inspect(stage?staging[i]:paths[i],value);
    if(v&&v!=-2)return v;
    return matches(value,stage?&expected_stages[i]:&expected_files[i])?0:-116;
}
static i64 append_chunk(u32 i) {
    if(!target_sizes[i]||!req.count||req.count>1048576||req.offset>target_sizes[i]||req.count>target_sizes[i]-req.offset)return -22;
    i64 input=op("/tmp/jiritsu/resource.chunk",0x20000);if(input<0)return input;
    u64 st[16];i64 v=regular(input,st);if(!v&&st[6]!=req.count)v=-22;
    struct Info previous;if(!v){v=inspect(staging[i],&previous);if(v==-2)v=0;}
    if(!v&&((!req.offset&&previous.status!=-2)||(req.offset&&(previous.status||previous.size!=req.offset))))v=-116;
    if(!v&&req.offset&&!equal(previous.hash,req.prefix,32))v=-84;
    if(!v&&!req.offset) {
        u64 fs[16];v=sc(43,(i64)resource_directory,(i64)fs,0,0,0,0);
        if(!v&&(!fs[1]||fs[4]*fs[1]<target_sizes[i]+fs[1]||!fs[6]))v=-28;
    }
    i64 output=-1;
    if(!v)output=op(staging[i],req.offset?0x20001:0x200c1);
    if(output<0&&!v)v=output;
    u64 at=0;
    while(!v&&at<req.count) {
        u32 want=req.count-at>sizeof(buffer)?sizeof(buffer):req.count-at;
        i64 n=sc(67,input,(i64)buffer,want,at,0,0);
        if(n==-4)continue;if(n<=0||(u64)n>want){v=n<0?n:-5;break;}
        u32 done=0;
        while(!v&&done<(u32)n) {
            i64 written=sc(68,output,(i64)(buffer+done),n-done,req.offset+at+done,0,0);
            if(written==-4)continue;
            if(written<=0||written>n-done)v=written<0?written:-5;else done+=written;
        }
        at+=done;out.progress=req.offset+at;
    }
    if(output>=0&&!v)v=sc(82,output,0,0,0,0,0);
    i64 c=close_fd(&output);if(!v)v=c;c=close_fd(&input);if(!v)v=c;return v;
}
__attribute__((visibility("default"))) void _init(void) {
    resource_probe_init();const u8 magic[]="A7RSR001";for(u32 i=0;i<8;i++)out.magic[i]=magic[i];out.version=1;
    out.status=report.status?report.status:report.index!=16||report.euid?-22:0;
    out.cleanup=report.cleanup;if(!out.status&&out.cleanup)out.status=out.cleanup;
    i64 n=read_all("/tmp/jiritsu/a7c2.install.request",(u8*)&req,sizeof(req)+0);
    /* read_all rejects exact-capacity files; request includes an explicit EOF check below. */
    if(n==-75) {
        i64 fd=op("/tmp/jiritsu/a7c2.install.request",0);u8 extra;
        n=fd<0?fd:sc(67,fd,(i64)&extra,1,sizeof(req),0,0);close_fd(&fd);if(!n)n=sizeof(req);
    }
    if(!out.status&&(n!=sizeof(req)||!equal(req.magic,"A7RSQ001",8)||req.reserved||req.mode>4||req.index>=FILE_COUNT))out.status=-22;
    out.mode=req.mode;out.index=req.index;
    if(!out.status)out.status=mount_state(1);
    if(!out.status)out.status=check_guards();
    for(u32 i=0;i<FILE_COUNT&&!out.status&&!req.mode;i++) {
        i64 v=inspect(paths[i],&out.files[i]);if(v&&v!=-2)out.status=v;
        v=inspect(staging[i],&out.stages[i]);if(v&&v!=-2)out.status=v;
    }
    int rw=0;
    if(!out.status&&req.mode) {
        /* Refuse any target/staging change since this request's fresh inventory. */
        struct Info value;out.status=current(req.index,req.mode==4,&value);
        if(!out.status){rw=1;out.status=remount(0);}
        if(!out.status&&req.mode==1) {
            if(!deletable[req.index])out.status=-22;
            else if(!out.files[req.index].status)out.status=sc(35,-100,(i64)paths[req.index],0,0,0,0);
        } else if(!out.status&&req.mode==2)out.status=append_chunk(req.index);
        else if(!out.status&&req.mode==3) {
            struct Info value;out.status=inspect(staging[req.index],&value);
            if(!out.status&&(value.status||value.size!=target_sizes[req.index]||!equal(value.hash,target_hashes[req.index],32)))out.status=-84;
            if(!out.status)out.status=sc(38,-100,(i64)staging[req.index],-100,(i64)paths[req.index],0,0);
        } else if(!out.status&&req.mode==4&&!out.stages[req.index].status)
            out.status=sc(35,-100,(i64)staging[req.index],0,0,0,0);
        if(!out.status){out.changed=1;out.status=sync_dir();}
    }
    out.readonly=rw?remount(1):mount_state(1);if(out.readonly&&!out.status)out.status=out.readonly;
    i64 fd=op("/tmp/jiritsu/a7c2.runtime.result",0x241);
    if(fd>=0){write_all(fd,&out,sizeof(out));sc(82,fd,0,0,0,0,0);cl(fd);}
}
