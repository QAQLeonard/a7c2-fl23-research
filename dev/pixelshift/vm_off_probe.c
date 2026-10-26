#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>
#include <link.h>
#include <string.h>
#include <dlfcn.h>
#include <fcntl.h>
/* Guest-only fixture producer and direct original model-API call.
 * No camera API, transport, allocator or completion function is interposed.
 */
static uintptr_t app;
static uint32_t read32(const unsigned char *p){uint32_t v;memcpy(&v,p,4);return v;}
static void saved_files(FILE *out,const char *stage) {
    const char *paths[]={"/setting/Backup.bin","/setting/Backup.bak","/Backup.bak",0};
    for(unsigned n=0;paths[n];n++) {
        unsigned char h[256],entry[6],property[6],value=0xff;
        int fd=open(paths[n],O_RDONLY);
        if(fd<0){fprintf(out,"FILE_STATE stage=%s path=%s absent=1\n",stage,paths[n]);continue;}
        if(pread(fd,h,sizeof(h),0)!=sizeof(h)){close(fd);continue;}
        uint32_t subsystems=read32(h+16);
        if(memcmp(h+12,"BK4",3)||subsystems<=0x2cf){fprintf(out,"FILE_STATE stage=%s path=%s format_unknown=1\n",stage,paths[n]);close(fd);continue;}
        pread(fd,entry,6,256+0x2cf*6);
        uint32_t index=read32(entry+2)+0x2cf;
        pread(fd,property,6,256+subsystems*6+index*6);
        uint32_t pointer=read32(property+2);
        pread(fd,&value,1,pointer&0xffffff);
        fprintf(out,"FILE_STATE stage=%s path=%s cookie=%u writecomp=%u id1=%u count=%u ptr=%u value=%u\n",stage,paths[n],read32(h+4),read32(h+8),read32(h+40),read32(h+44),pointer&0xffffff,value);
        close(fd);
    }
}
static int saved_byte(void) {
    unsigned char value=0xff;
    int fd=open("/setting/Backup.bin",O_RDONLY);
    if(fd<0)return -1;
    ssize_t n=pread(fd,&value,1,609678);close(fd);
    return n==1?value:-2;
}
static int locate(struct dl_phdr_info *info,size_t size,void *unused) {
    (void)size;(void)unused;
    const char *name=strrchr(info->dlpi_name,'/');
    name=name?name+1:info->dlpi_name;
    if(!strcmp(name,"appFw.so"))app=info->dlpi_addr;
    return 0;
}
static void *probe(void *unused) {
    (void)unused;
    char exe[128];ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
    if(n<0)return 0;exe[n]=0;
    const char *name=strrchr(exe,'/');
    if(!name||strcmp(name+1,"im.elf"))return 0;
    for(unsigned n=0;n<2400;n++) {
        if(!app)dl_iterate_phdr(locate,0);
        if(app && !access("/tmp/pixelshift-off.request",R_OK)) {
            if(access("/simulation/PIXELSHIFT_VM_ONLY",R_OK))return 0;
            FILE *out=fopen("/tmp/pixelshift-off.result","w");
            if(!out)return 0;
            setbuf(out,0);
            volatile uint32_t *mode=(void *)(app+0x7e6f070),*companion=(void *)(app+0x7e82358);
            fprintf(out,"LIVE_BASELINE mode=%u companion=%u enqueue=%u\n",*mode,*companion,*(unsigned char *)(app+0x7e4e608));
            saved_files(out,"baseline");
            int seeded=0;
            int (*read_backup)(unsigned int,void *)=0;
            int (*write_backup)(unsigned short,unsigned int,const void *)=0;
            int (*sync_backup)(unsigned short)=0;
            if(!access("/tmp/pixelshift-off.seed-backup",R_OK)) {
                write_backup=dlsym(RTLD_DEFAULT,"Backup_write");
                read_backup=dlsym(RTLD_DEFAULT,"Backup_read");
                sync_backup=dlsym(RTLD_DEFAULT,"Backup_sync_subsystem");
                if(!write_backup||!read_backup){fprintf(out,"BACKUP_SYMBOL_MISSING\n");fclose(out);return 0;}
                unsigned char on=1,readback=0xff;
                int status=write_backup(0x02cf,0x02cf02cf,&on);
                int read_status=read_backup(0x02cf02cf,&readback);
                fprintf(out,"VIRTUAL_BACKUP_INPUT write=%d read=%d value=%u\n",status,read_status,readback);
                if(status<0||read_status<0||readback!=1){fclose(out);return 0;}
                if(!access("/tmp/pixelshift-off.sync",R_OK)) {
                    int status=sync_backup?sync_backup(0x02cf):-999;
                    fprintf(out,"VIRTUAL_BACKUP_INPUT_SYNC status=%d file_byte=%d\n",status,saved_byte());
                    saved_files(out,"seed-on");
                }
                seeded=1;
            }
            /* Reproduce stale cached ON as input in the disposable guest only.
             * No saved setting or synthesized API/acknowledgement is written.
             */
            if(!access("/tmp/pixelshift-off.native-on",R_OK)) {
                ((void (*)(void *,uint32_t))(app+0x259a194))(0,1);
                usleep(500000);
                fprintf(out,"LIVE_NATIVE_ON_RETURN mode=%u companion=%u\n",*mode,*companion);
                if(read_backup) {
                    unsigned char value=0xff;int status=read_backup(0x02cf02cf,&value);
                    fprintf(out,"VIRTUAL_BACKUP_AFTER_NATIVE_ON read=%d value=%u\n",status,value);
                }
            } else {
                *mode=1;*companion=1;
                fprintf(out,"LIVE_INPUT_FIXTURE mode=%u companion=%u saved_state_untouched=1\n",*mode,*companion);
            }
            ((void (*)(void *,uint32_t))(app+0x259a194))(0,0);
            fprintf(out,"LIVE_NATIVE_OFF_RETURN mode=%u companion=%u\n",*mode,*companion);
            usleep(500000);
            fprintf(out,"LIVE_NATIVE_OFF_LATER mode=%u companion=%u\n",*mode,*companion);
            if(seeded) {
                unsigned char value=0xff;int status=-1;
                for(unsigned n=0;n<40;n++) {
                    status=read_backup(0x02cf02cf,&value);
                    if(status<0||value==0)break;
                    usleep(50000);
                }
                fprintf(out,"VIRTUAL_BACKUP_AFTER_OFF read=%d value=%u flash_sync_tested=0\n",status,value);
                if(!access("/tmp/pixelshift-off.sync",R_OK)) {
                    unsigned char zero=0;
                    int write_status=write_backup(0x02cf,0x02cf02cf,&zero);
                    int sync_status=sync_backup?sync_backup(0x02cf):-999;
                    status=read_backup(0x02cf02cf,&value);
                    fprintf(out,"VIRTUAL_EXPLICIT_OFF write=%d sync=%d read=%d value=%u file_byte=%d\n",write_status,sync_status,status,value,saved_byte());
                    int file_value=saved_byte();
                    for(unsigned n=0;n<100 && file_value!=0;n++){usleep(50000);file_value=saved_byte();}
                    fprintf(out,"VIRTUAL_OFF_AFTER_SUBSYSTEM_SYNC sync=%d file_byte=%d\n",sync_status,file_value);
                    saved_files(out,"off");
                }
            }
            fprintf(out,"LIVE_PROBE_DONE\n");
            fclose(out);return 0;
        }
        usleep(50000);
    }
    return 0;
}
__attribute__((constructor)) static void start_probe(void) {
    if(!getenv("PIXELSHIFT_NATIVE_OFF_PROBE"))return;
    pthread_t thread;
    if(!pthread_create(&thread,0,probe,0))pthread_detach(thread);
}
