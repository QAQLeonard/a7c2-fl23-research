"""Execute original DMM rule handling on official configuration, offline only.

Kernel sections are relocated, internal calls remain original, memcpy/memset
resolve to original firmware libc. Other undefined functions stay unavailable.
The configuration source and registered control-memory backing are fixtures.
"""
import argparse,json,struct
from pathlib import Path
from collections import Counter
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_INVALID,UC_HOOK_CODE
import unicorn.arm64_const as arm

def prepare(corpus, config_path):
 corpus=Path(corpus)
 paths={}
 for key,pattern in [('libc','*-libc-2.25.so'),('dmm','*-dmm.ko')]:
  matches=list(corpus.glob(pattern))
  if len(matches)!=1:raise ValueError('Needs one original '+pattern+' in the private corpus files directory')
  paths[key]=matches[0]
 cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
 report=dict(camera_io=False,installable=False,api_results_replaced=False,stages=[],invalid=[],
             registered_control_backing_and_config_source_are_fixtures=True)
 cpu.reg_write(arm.UC_ARM64_REG_CPACR_EL1,0x300000)
 external={};symbols={};section_bases={};relocation_types=Counter()
 with paths['libc'].open('rb') as stream:
  elf=ELFFile(stream);libcbase=0x14000000
  for segment in elf.iter_segments():
   if segment['p_type']!='PT_LOAD':continue
   at=libcbase+segment['p_vaddr'];lo=at&~4095;size=(at+segment['p_memsz']-lo+4095)&~4095
   cpu.mem_map(lo,size);cpu.mem_write(at,segment.data())
  for symbol in elf.get_section_by_name('.dynsym').iter_symbols():
   if symbol.name in ('memset','memcpy'):external[symbol.name]=libcbase+symbol['st_value']
 with paths['dmm'].open('rb') as stream:
  elf=ELFFile(stream);cursor=0x10000000
  for index,section in enumerate(elf.iter_sections()):
   if not section['sh_flags']&2 or not section['sh_size']:continue
   size=(section['sh_size']+4095)&~4095
   cpu.mem_map(cursor,size);section_bases[index]=cursor
   if section['sh_type']!='SHT_NOBITS':cpu.mem_write(cursor,section.data())
   if section.name=='.text':textbase=cursor
   cursor+=size+0x10000
  table=elf.get_section_by_name('.symtab')
  unknown={}
  def address(symbol):
   index=symbol['st_shndx']
   if index=='SHN_UNDEF':
    if symbol.name in external:return external[symbol.name]
    if symbol.name not in unknown:unknown[symbol.name]=0x16000000+16*len(unknown)
    return unknown[symbol.name]
   if index=='SHN_ABS':return symbol['st_value']
   return section_bases[index]+symbol['st_value']
  for symbol in table.iter_symbols():
   if symbol.name and symbol['st_shndx'] in section_bases:symbols[symbol.name]=address(symbol)
  for section in elf.iter_sections():
   if section['sh_type']!='SHT_RELA' or section['sh_info'] not in section_bases:continue
   target=section_bases[section['sh_info']];table=elf.get_section(section['sh_link'])
   for relocation in section.iter_relocations():
    at=target+relocation['r_offset'];typ=relocation['r_info_type'];relocation_types[typ]+=1
    symbol=table.get_symbol(relocation['r_info_sym']);value=address(symbol)+relocation['r_addend']
    if typ==257:cpu.mem_write(at,struct.pack('<Q',value&0xffffffffffffffff))
    elif typ==261:cpu.mem_write(at,struct.pack('<I',(value-at)&0xffffffff))
    elif typ in (282,283):
     delta=value-at
     if delta%4 or not -(1<<27)<=delta<(1<<27):raise ValueError('Branch relocation out of range')
     op=struct.unpack('<I',cpu.mem_read(at,4))[0]
     cpu.mem_write(at,struct.pack('<I',(op&0xfc000000)|((delta//4)&0x3ffffff)))
    else:raise ValueError('Unhandled ELF relocation '+str(typ))
 report['relocation_types']=dict(relocation_types)
 config=config_path.read_bytes();source=0x18000000
 cpu.mem_map(source,(len(config)+4095)&~4095);cpu.mem_write(source,config)
 cpu.mem_map(0x19000000,0x100000);cpu.mem_map(0x1a000000,0x40000)
 # Original reader's memory-backed source input, not a read result.
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
 reader=symbols['dmm_module_GetConfigData']
 instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(bytes(cpu.mem_read(reader,0x24)),reader))
 loads=[int(row.op_str.split('#')[1],0) for row in instructions
        if row.mnemonic=='ldr' and row.op_str.startswith('x19, #')]
 if len(loads)!=1:raise ValueError('Original DMM configuration-source binding changed')
 module_state=struct.unpack('<Q',cpu.mem_read(loads[0],8))[0]
 cpu.mem_write(module_state+8,struct.pack('<QQ',0,source))
 def invalid(uc,access,at,size,value,_):
  report['invalid'].append(dict(pc=hex(uc.reg_read(arm.UC_ARM64_REG_PC)),lr=hex(uc.reg_read(arm.UC_ARM64_REG_LR)),address=hex(at),
    unavailable_symbol=next((name for name,p in unknown.items() if p==at),None)))
  return False
 cpu.hook_add(UC_HOOK_MEM_INVALID,invalid)
 def run(entry,*args,end=0x1a03f000):
  for index,value in enumerate(args):cpu.reg_write(getattr(arm,'UC_ARM64_REG_X'+str(index)),value)
  cpu.reg_write(arm.UC_ARM64_REG_SP,0x1a03e000);cpu.reg_write(arm.UC_ARM64_REG_LR,0x1a03f000)
  cpu.emu_start(entry,end,count=2000000)
  pc=cpu.reg_read(arm.UC_ARM64_REG_PC)
  report['stages'].append(dict(entry=hex(entry),pc=hex(pc),result=hex(cpu.reg_read(arm.UC_ARM64_REG_X0))))
  if pc!=end:raise ValueError('Native stage did not reach its boundary')
  return cpu.reg_read(arm.UC_ARM64_REG_X0)
 return cpu,report,symbols,textbase,module_state,run

class RuleReceiver:
 """Native handler with persistent native rule stack, never camera access."""
 def __init__(self,corpus,config):
  self.cpu,self.report,self.symbols,self.text,self.module,self.run=prepare(corpus,Path(config))
  status=self.run(self.symbols['dmm_unit_ctrl_Init'],0,0x19000000)
  if status:raise ValueError('Original DMM initialization rejected its input: '+hex(status))
  consumed=struct.unpack('<Q',self.cpu.mem_read(self.module+8,8))[0]
  if consumed!=Path(config).stat().st_size:raise ValueError('Original DMM reader did not consume the complete configuration')
  self.report['config_consumed']=consumed
  self.handler=struct.unpack('<Q',self.cpu.mem_read(self.symbols['msg_hdlr']+0x14*8,8))[0]

 def current_rule(self):
  output=0x1a002000
  status=self.run(self.symbols['dmm_ext_ctrl_GetCurrentAllocRule'],output)
  if status:raise ValueError('Native current-rule getter rejected state')
  return struct.unpack('<H',self.cpu.mem_read(output,2))[0]

 def transact(self,rule=0,option=0,component=0x55,*,packet=None):
  if packet is None:
   packet=bytearray(40)
   if not 0<=rule<=255 or not 0<=option<=65535 or not 0<=component<=65535:
    raise ValueError('Request field exceeds its native storage')
   struct.pack_into('<HB',packet,0,0x14,rule)
   struct.pack_into('<HH',packet,20,component,option)
  if len(packet)!=40 or struct.unpack_from('<H',packet)[0]!=0x14:
   raise ValueError('This receiver handles one 40-byte original 0x14 request')
  request,reply=0x1a000000,0x1a001000
  self.cpu.mem_write(request,bytes(64));self.cpu.mem_write(request+12,bytes(packet))
  self.cpu.mem_write(reply,bytes(40))
  disposition=self.run(self.handler,request,reply)
  payload=bytes(self.cpu.mem_read(reply,40))
  return dict(reply=payload.hex(),disposition=disposition,
    response=struct.unpack_from('<H',payload)[0],status=struct.unpack_from('<h',payload,2)[0],
    component=struct.unpack_from('<H',payload,6)[0],raw_status=struct.unpack_from('<h',payload,10)[0],
    rule_attribute=struct.unpack_from('<H',payload,12)[0],current_rule=self.current_rule())

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--corpus',type=Path,required=True,help='Private extracted corpus files directory')
 parser.add_argument('--config',type=Path,required=True,help='Same-model official DmmCfg.bin')
 parser.add_argument('--rule',type=lambda v:int(v,0),default=0)
 parser.add_argument('--option',type=lambda v:int(v,0),default=0)
 parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args()
 receiver=RuleReceiver(args.corpus,args.config)
 result=receiver.transact(args.rule,args.option)
 report=dict(receiver.report,result=result,full_capture_or_transport_executed=False,
             positioning_or_exposure_executed=False)
 with args.output.open('x',encoding='utf-8') as handle:json.dump(report,handle,indent=2)
 print(json.dumps(result))

if __name__=='__main__':main()
