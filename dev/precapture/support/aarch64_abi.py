"""Compile target fcntl.h constants, without executing the generated ELF.

Production constants are checked by independent target-header static asserts.
This catches host-architecture flags accidentally copied into AArch64 code.
"""
import io
import struct
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

FIELDS=('readonly','writeonly','create','exclusive','directory','nofollow','cloexec','direct')


def _constants(zig,folder,source_text,symbol_name,fields,header_directory=None):
    folder=Path(folder);folder.mkdir(exist_ok=False)
    source=folder/'target-open-flags.c';elf=folder/'NOT-EXECUTABLE-open-flags.elf'
    header=Path(header_directory) if header_directory is not None else Path(__file__).resolve().parents[1]
    source.write_text(source_text,encoding='ascii')
    # -lc selects Zig's target libc headers; -c prevents any linking/runtime.
    command=[str(zig),'cc','-target','aarch64-linux-gnu','-lc','-c','-ffreestanding',
        '-I',str(header),'-o',str(elf),str(source)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    if result.returncode:raise RuntimeError(result.stderr[-2500:])
    image=ELFFile(io.BytesIO(elf.read_bytes()))
    assert image['e_machine']=='EM_AARCH64' and image['e_type']=='ET_REL'
    assert image.get_section_by_name('.dynamic') is None
    symbol=next(s for s in image.get_section_by_name('.symtab').iter_symbols() if s.name==symbol_name)
    size=4*len(fields)
    assert symbol['st_info']['type']=='STT_OBJECT' and symbol['st_size']==size
    section=image.get_section(symbol['st_shndx']);offset=symbol['st_value']-section['sh_addr']
    values=struct.unpack('<'+'I'*len(fields),section.data()[offset:offset+size])
    return dict(zip(fields,values))


def open_flags(zig,folder,*,header_directory=None):
    output=_constants(zig,folder,'''#define _GNU_SOURCE 1
#include <fcntl.h>
#include "ap_linux_aarch64.h"
_Static_assert(AP_A64_O_RDONLY==O_RDONLY,"readonly ABI");
_Static_assert(AP_A64_O_WRONLY==O_WRONLY,"write ABI");
_Static_assert(AP_A64_O_CREAT==O_CREAT,"create ABI");
_Static_assert(AP_A64_O_EXCL==O_EXCL,"exclusive ABI");
_Static_assert(AP_A64_O_DIRECTORY==O_DIRECTORY,"AArch64 directory ABI");
_Static_assert(AP_A64_O_NOFOLLOW==O_NOFOLLOW,"AArch64 nofollow ABI");
_Static_assert(AP_A64_O_CLOEXEC==O_CLOEXEC,"cloexec ABI");
_Static_assert(AP_A64_O_DIRECT==O_DIRECT,"AArch64 direct-IO ABI");
const unsigned int precapture_aarch64_open_flags[]={O_RDONLY,O_WRONLY,O_CREAT,O_EXCL,O_DIRECTORY,O_NOFOLLOW,O_CLOEXEC,O_DIRECT};
''','precapture_aarch64_open_flags',FIELDS,header_directory)
    output['read_flags']=output['readonly']|output['nofollow']|output['cloexec']
    output['directory_flags']=output['read_flags']|output['directory']
    output['exclusive_flags']=output['writeonly']|output['create']|output['exclusive']|output['nofollow']|output['cloexec']
    assert output['directory_flags']&output['direct']==0
    return output


def context_abi(zig,folder,*,header_directory=None):
    fields=('rdwr_flags','prot_rw','map_shared','at_nofollow','stat_bytes','mode_offset','dev_offset','inode_offset',
        'rdev_offset','mode_mask','char_type','nr_statat','nr_openat','nr_stat','nr_ioctl','nr_mmap','nr_munmap','nr_close')
    return _constants(zig,folder,'''#define _GNU_SOURCE 1
#include <fcntl.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include "ap_linux_aarch64.h"
_Static_assert(AP_A64_OPEN_RDWR==(O_RDWR|O_NOFOLLOW|O_CLOEXEC),"read-write open ABI");
_Static_assert(AP_A64_PROT_READ==PROT_READ && AP_A64_PROT_WRITE==PROT_WRITE,"map protections ABI");
_Static_assert(AP_A64_MAP_SHARED==MAP_SHARED,"shared map ABI");
_Static_assert(AP_A64_AT_SYMLINK_NOFOLLOW==AT_SYMLINK_NOFOLLOW,"stat nofollow ABI");
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16,"stat shape ABI");
_Static_assert(offsetof(struct stat,st_dev)==0 && offsetof(struct stat,st_ino)==8 && offsetof(struct stat,st_rdev)==32,"stat identity ABI");
_Static_assert(AP_A64_SYS_FSTATAT==SYS_newfstatat && AP_A64_SYS_OPENAT==SYS_openat && AP_A64_SYS_FSTAT==SYS_fstat,"stat/open syscall ABI");
_Static_assert(AP_A64_SYS_IOCTL==SYS_ioctl && AP_A64_SYS_MMAP==SYS_mmap && AP_A64_SYS_MUNMAP==SYS_munmap && AP_A64_SYS_CLOSE==SYS_close,"map/ioctl/close syscall ABI");
const unsigned int precapture_aarch64_context_abi[]={O_RDWR|O_NOFOLLOW|O_CLOEXEC,PROT_READ|PROT_WRITE,MAP_SHARED,AT_SYMLINK_NOFOLLOW,
sizeof(struct stat),offsetof(struct stat,st_mode),offsetof(struct stat,st_dev),offsetof(struct stat,st_ino),offsetof(struct stat,st_rdev),
S_IFMT,S_IFCHR,SYS_newfstatat,SYS_openat,SYS_fstat,SYS_ioctl,SYS_mmap,SYS_munmap,SYS_close};
''','precapture_aarch64_context_abi',fields,header_directory)


def client_binding_abi(zig,folder,*,header_directory=None):
    fields=('getpolicy','getparam','setaffinity','getaffinity','sigmask','getcpu','getpid','getppid',
            'sig_block','sig_setmask','kernel_sigset_bytes','mask_word_bytes','priority_bytes')
    return _constants(zig,folder,'''#define _GNU_SOURCE 1
#include <asm/unistd.h>
#include <asm/signal.h>
#include <sched.h>
_Static_assert(__NR_sched_getscheduler==120 && __NR_sched_getparam==121,"read scheduling ABI");
_Static_assert(__NR_sched_setaffinity==122 && __NR_sched_getaffinity==123,"self affinity ABI");
_Static_assert(__NR_rt_sigprocmask==135 && __NR_getcpu==168,"signal/CPU ABI");
_Static_assert(__NR_getpid==172 && __NR_getppid==173,"process identity ABI");
_Static_assert(SIG_BLOCK==0 && SIG_SETMASK==2 && SIGKILL==9 && SIGSTOP==19,"signal definitions");
_Static_assert(sizeof(sigset_t)==8 && sizeof(unsigned long)==8 && sizeof(struct sched_param)==4,"kernel scalar shapes");
const unsigned int precapture_aarch64_client_abi[]={__NR_sched_getscheduler,__NR_sched_getparam,
__NR_sched_setaffinity,__NR_sched_getaffinity,__NR_rt_sigprocmask,__NR_getcpu,__NR_getpid,__NR_getppid,
SIG_BLOCK,SIG_SETMASK,sizeof(sigset_t),sizeof(unsigned long),sizeof(struct sched_param)};
''','precapture_aarch64_client_abi',fields,header_directory)


def client_cpuset_abi(zig,folder,*,header_directory=None):
    fields=('gettid','getpid','getppid','openat','read','write','close','read_flags','write_flags','getaffinity','getcpu')
    return _constants(zig,folder,'''#define _GNU_SOURCE 1
#include <asm/unistd.h>
#include <fcntl.h>
#include "ap_linux_aarch64.h"
_Static_assert(__NR_gettid==178 && __NR_getpid==172 && __NR_getppid==173,"self identity ABI");
_Static_assert(__NR_openat==56 && __NR_read==63 && __NR_write==64 && __NR_close==57,"bounded file ABI");
_Static_assert(AP_A64_OPEN_READ==(O_RDONLY|O_CLOEXEC|O_NOFOLLOW),"read flags");
_Static_assert((AP_A64_O_WRONLY|AP_A64_O_CLOEXEC|AP_A64_O_NOFOLLOW)==(O_WRONLY|O_CLOEXEC|O_NOFOLLOW),"write flags");
_Static_assert(__NR_sched_getaffinity==123 && __NR_getcpu==168,"affinity readback ABI");
const unsigned int precapture_aarch64_cpuset_abi[]={__NR_gettid,__NR_getpid,__NR_getppid,__NR_openat,
__NR_read,__NR_write,__NR_close,O_RDONLY|O_CLOEXEC|O_NOFOLLOW,O_WRONLY|O_CLOEXEC|O_NOFOLLOW,
__NR_sched_getaffinity,__NR_getcpu};
''','precapture_aarch64_cpuset_abi',fields,header_directory)
