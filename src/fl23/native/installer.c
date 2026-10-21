/* Fixed-window, inode-preserving installer/restore worker. No raw flash,
 * arbitrary files, process memory writes, shell, Backup settings or WBI.
 * Mode0 only checks originals; mode1 installs; mode2 restores originals.
 * Legacy builds use complete hashes; BYTE_WINDOWS_ONLY builds verify edited
 * bytes and require complete byte readback on the host.
 */
typedef unsigned long u64;typedef unsigned int u32;typedef long i64;typedef unsigned char u8;
static i64 sc(i64 no,i64 a,i64 b,i64 c,i64 d,i64 e,i64 f) {
    register i64 x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c;
    register i64 x3 __asm__("x3")=d,x4 __asm__("x4")=e,x5 __asm__("x5")=f,x8 __asm__("x8")=no;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5),"r"(x8) : "memory","cc");return x0;
}
static i64 op(const char *p,i64 flags) {return sc(56,-100,(i64)p,flags,0644,0,0);}
static i64 closefd(i64 *fd) {if(*fd<0)return 0;i64 r=sc(57,*fd,0,0,0,0,0);*fd=-1;return r;}
static int same(const u8*a,const u8*b,u32 n) {for(u32 i=0;i<n;i++)if(a[i]!=b[i])return 0;return 1;}
#include "sha256.h"
struct Window {u64 offset;u32 length,chip;const u8 *before,*after;};
#ifndef PATCH_MANIFEST
#define PATCH_MANIFEST "patch_manifest.h"
#endif
#include PATCH_MANIFEST
#ifndef INSTALL_REQUEST
#define INSTALL_REQUEST "/tmp/jiritsu/a7c2.install.request"
#define INSTALL_RESULT "/tmp/jiritsu/a7c2.install.result"
#endif
static u8 buffer[65536],mounts[8192],checkbytes[4096];
struct Stat {u64 dev,ino;u32 mode,nlink,uid,gid;u64 rdev,pad1;i64 size;u32 blksize,pad2;u64 blocks;u64 rest[7];};
_Static_assert(sizeof(struct Stat)==128,"AArch64 Linux stat ABI");
struct Request {u8 magic[8];u32 mode,reserved;};
struct Report {
    u8 magic[8];u32 version,mode,phase,writes;
    i64 status,rollback,remount,readonly,cleanup,euid,pid;
    u64 ap_inode,cp_inode,ap_size,cp_size;
    u8 before_hash[2][32],after_hash[2][32];
};
static struct Report r;static struct Request req;static struct Stat initial[2];
static i64 fd[2]={-1,-1};static int mounted_rw=0;
static const char *path(u32 i) {return i?"/cp/cpapp-b.bin":"/usr/lib/appFw.so";}
static i64 exact_read(i64 file,void *out,u32 n,u64 offset) {
    u32 done=0,retries=0;
    while(done<n) {
        i64 v=sc(67,file,(i64)((u8*)out+done),n-done,offset+done,0,0);
        if(v==-4 && retries++<3)continue;
        if(v<=0 || (u64)v>n-done)return v<0?v:-5;
        done+=(u32)v;
    }return 0;
}
static i64 exact_write(i64 file,const void *data,u32 n,u64 offset,int sequential) {
    u32 done=0,retries=0;
    while(done<n) {
        i64 v=sc(sequential?64:68,file,(i64)((const u8*)data+done),n-done,offset+done,0,0);
        if(v==-4 && retries++<3)continue;
        if(v<=0 || (u64)v>n-done)return v<0?v:-5;
        done+=(u32)v;
    }return 0;
}
static i64 hash_file(i64 file,u32 chip,u8 *out) {
    SHA256 s;sha_init(&s);u64 at=0;
    while(at<file_sizes[chip]) {
        u32 n=(file_sizes[chip]-at)>sizeof(buffer)?sizeof(buffer):(u32)(file_sizes[chip]-at);
        i64 v=exact_read(file,buffer,n,at);if(v)return v;
        sha_add(&s,buffer,n);at+=n;
    }
    i64 v=sc(67,file,(i64)buffer,1,at,0,0);if(v!=0)return v<0?v:-27;
    sha_end(&s,out);return 0;
}
static i64 mount_state(int wanted_ro) {
    i64 file=op("/proc/mounts",0);if(file<0)return file;
    i64 n=sc(63,file,(i64)mounts,sizeof(mounts),0,0,0);i64 c=closefd(&file);
    if(c)return c;if(n<=0 || n>=(i64)sizeof(mounts))return -75;
    const u8 prefix[]="/dev/nflasha15 /usr ext2 ";u32 size=sizeof(prefix)-1;
    u32 matches=0;
    for(u32 i=0;i+size+3<=(u32)n;i++)if((i==0||mounts[i-1]=='\n')&&same(mounts+i,prefix,size)) {
        u8 a=wanted_ro?'o':'w';
        if(mounts[i+size]!='r'||mounts[i+size+1]!=a||mounts[i+size+2]!=',')return -30;
        matches++;
    }
    return matches==1?0:-22;
}
static i64 remount(int ro) {
    i64 v=sc(40,0,(i64)"/usr",0,0xc30UL+(ro?1:0),0,0);
    if(v)return v;return mount_state(ro);
}
static i64 inspect(u32 chip,int writable) {
    fd[chip]=op(path(chip),writable?2:0);if(fd[chip]<0)return fd[chip];
    struct Stat st;i64 v=sc(80,fd[chip],(i64)&st,0,0,0,0);if(v)return v;
    if((st.mode&0170000)!=0100000 || st.size!=(i64)file_sizes[chip])return -22;
    if(writable) {
        if(st.ino!=initial[chip].ino || st.dev!=initial[chip].dev)return -116;
    } else initial[chip]=st;
    return 0;
}
static i64 verify_windows(int after) {
    for(u32 i=0;i<window_count;i++) {
        const struct Window *w=&windows[i];
        if(w->chip>1||!w->length||w->length>sizeof(checkbytes)||w->offset>file_sizes[w->chip]||w->length>file_sizes[w->chip]-w->offset)return -22;
        i64 v=exact_read(fd[w->chip],checkbytes,w->length,w->offset);if(v)return v;
        if(!same(checkbytes,after?w->after:w->before,w->length))return -84;
    }return 0;
}
static i64 patch(int after,int reverse) {
    for(u32 j=0;j<window_count;j++) {
        u32 i=reverse?window_count-1-j:j;const struct Window*w=&windows[i];
        r.writes++;
        i64 v=exact_write(fd[w->chip],after?w->after:w->before,w->length,w->offset,0);
        if(v)return v;
    }
    for(u32 chip=0;chip<2;chip++) {i64 v=sc(82,fd[chip],0,0,0,0,0);if(v)return v;}
    return verify_windows(after);
}
static i64 verify_hashes(int after,u8 out[2][32]) {
#ifdef BYTE_WINDOWS_ONLY
    return verify_windows(after);
#else
    for(u32 chip=0;chip<2;chip++) {
        i64 v=hash_file(fd[chip],chip,out[chip]);if(v)return v;
        if(!same(out[chip],after?final_hashes[chip]:original_hashes[chip],32))return -84;
    }return 0;
#endif
}
static void work(void) {
    i64 request=op(INSTALL_REQUEST,0);
    if(request<0) {r.status=request;return;}
    r.status=exact_read(request,&req,sizeof(req),0);i64 c=closefd(&request);
    const u8 magic[]="A7INS001";
    if(r.status)return;if(c) {r.status=c;return;}
    if(!same(req.magic,magic,8)||req.mode>2||req.reserved) {r.status=-22;return;}
    r.mode=req.mode;
    if(r.euid!=0) {r.status=-13;return;}
    r.phase=1;r.status=mount_state(1);if(r.status)return;
    for(u32 chip=0;chip<2;chip++) {r.status=inspect(chip,0);if(r.status)return;}
    r.ap_inode=initial[0].ino;r.cp_inode=initial[1].ino;r.ap_size=initial[0].size;r.cp_size=initial[1].size;
    r.phase=2;r.status=verify_hashes(req.mode==2,r.before_hash);if(r.status)return;
    r.status=verify_windows(req.mode==2);if(r.status)return;
    if(!req.mode) {r.phase=9;return;}
    for(u32 chip=0;chip<2;chip++) {r.status=closefd(&fd[chip]);if(r.status)return;}
    r.phase=3;
    /* Mark restoration as required before attempting the mount. Even a
       successful syscall followed by failed state readback must restore ro. */
    mounted_rw=1;r.remount=remount(0);if(r.remount) {r.status=r.remount;return;}
    for(u32 chip=0;chip<2;chip++) {r.status=inspect(chip,1);if(r.status)return;}
    r.status=verify_hashes(req.mode==2,r.before_hash);if(r.status)return;
    r.phase=4;r.status=patch(req.mode==1,0);
    if(!r.status) {r.phase=5;r.status=verify_hashes(req.mode==1,r.after_hash);}
    if(r.status) {
        r.phase=6;r.rollback=patch(req.mode==2,1);
        if(!r.rollback)r.rollback=verify_hashes(req.mode==2,r.after_hash);
        return;
    }
    r.phase=9;
}
__attribute__((visibility("default"))) void _init(void) {
    const u8 magic[]="A7IRP001";for(u32 i=0;i<8;i++)r.magic[i]=magic[i];
    r.version=1;r.euid=sc(175,0,0,0,0,0,0);r.pid=sc(172,0,0,0,0,0,0);
    r.cleanup=sc(35,-100,(i64)"/tmp/jiritsu/libJit.so",0,0,0,0);
    work();
    for(u32 chip=0;chip<2;chip++) {i64 c=closefd(&fd[chip]);if(c&&!r.status)r.status=c;}
    if(mounted_rw) {r.readonly=remount(1);if(r.readonly&&!r.status)r.status=r.readonly;}
    else {r.readonly=mount_state(1);if(r.readonly&&!r.status)r.status=r.readonly;}
    i64 out=op(INSTALL_RESULT,0x241);
    if(out>=0) {exact_write(out,&r,sizeof(r),0,1);sc(82,out,0,0,0,0,0);closefd(&out);}
    /* Return to the original native Jiritsu loader. */
}
