#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <dlfcn.h>
/* Disposable guest only. Runs after the original Backup driver is loaded,
 * before AP starts. It never changes or calls a physical camera transport. */
int main(void) {
    if (access("/simulation/PIXELSHIFT_VM_ONLY", R_OK)) return 70;
    void *ipc = dlopen("/usr/lib/libosal_uipc.so", RTLD_NOW | RTLD_GLOBAL);
    if (!ipc) { fprintf(stderr,"BOOT_OFF_IPC %s\n",dlerror()); return 76; }
    int (*initialize_ipc)(void)=dlsym(ipc,"u_osal_init");
    if (!initialize_ipc) return 77;
    int ipc_status=initialize_ipc();
    printf("BOOT_OFF_IPC_INIT status=%d\n",ipc_status); fflush(stdout);
    if(ipc_status) return 78;
    void *lib = dlopen("/usr/lib/libbackup.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib) { fprintf(stderr,"BOOT_OFF_LIBRARY %s\n",dlerror()); return 71; }
    int (*read_value)(unsigned,void *)=dlsym(lib,"Backup_read");
    int (*write_value)(unsigned short,unsigned,const void *)=dlsym(lib,"Backup_write");
    int (*sync_value)(unsigned short)=dlsym(lib,"Backup_sync_subsystem");
    if (!read_value || !write_value || !sync_value) return 72;
    unsigned char before=0xff,after=0xff,off=0;
    int initial=read_value(0x02cf02cf,&before);
    printf("BOOT_OFF_BEFORE read=%d value=%u\n",initial,before); fflush(stdout);
    if(initial!=1) return 73;
    int written=write_value(0x02cf,0x02cf02cf,&off);
    printf("BOOT_OFF_WRITE status=%d\n",written); fflush(stdout);
    if(written!=1) return 74;
    int synced=sync_value(0x02cf);
    int readback=read_value(0x02cf02cf,&after);
    printf("BOOT_OFF_AFTER sync=%d read=%d value=%u\n",synced,readback,after); fflush(stdout);
    if(synced!=0 || readback!=1 || after) return 75;
    puts("BOOT_OFF_DONE before_ap_start=1");
    return 0;
}
extern int __libc_start_main(int (*)(int,char **,char **),int,char **,
    void (*)(void),void (*)(void),void (*)(void),void *);
static int main_entry(int argc,char **argv,char **envp) {
    (void)argc;(void)argv;(void)envp;return main();
}
void start_entry(unsigned long *stack) {
    __libc_start_main(main_entry,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    _exit(79);
}
__asm__(".global _start\n_start:\n mov x0,sp\n bl start_entry\n brk #0\n");
