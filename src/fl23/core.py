"""Portable, offline validation and per-body planning. No USB imports here."""
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys

BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/'vendor'))
MODEL='ILCE-7CM2'
VERSION='2.01'
ORIGINAL=['2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
          'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428']
FINAL=['1aaeb8fbe0297950cab454d498d1a5ba874f91542aa2737aae27a73971e324d7',
       '442c9261d7c76c30f65e5b66ae133fea40fc31ee6c0046ff78b6b45df8ab455c']
PROGRAMS=['appFw.so','cpapp-b.bin']
CP_KEYS=[0x02a40001,0x02a4000d]
AP_KEYS=[0x02cf1287,0x02cf1289]
# FL2／FL3 的目標參數與記錄槽；merge_colors 只會改動這些位址。
COLOUR_SLOTS=[(55,23),(56,25)]
NATIVE_PATHS={'libJit.so','a7c2.install.request','a7c2.install.result','a7c2.probe.result',
              'a7c2.wbi.request','a7c2.wbi.result','a7c2.runtime.result','a7c2-preview-staged.so'}

def sha(data):return hashlib.sha256(data).hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.flush()
        __import__('os').fsync(f.fileno())
    temp.replace(path)

def assets():
    manifest=read_json(BASE/'assets/manifest.json')
    names={'installer.so','probe.so','wbi.so','runtime.so','patches.json','colors.json',
           'r5_fl23_reference.json','fx2_fl23_donor.json'}
    if set(manifest['files'])!=names:raise ValueError('套件資產清單不符')
    for name,expected in manifest['files'].items():
        if sha((BASE/'assets'/name).read_bytes())!=expected:raise ValueError('套件檔案雜湊不符：'+name)
    return manifest

def backup_records(raw):
    from pmca.backup import BackupFile
    result=[]
    for m in re.finditer(b'BK4\0',raw):
        try:b=BackupFile(io.BytesIO(raw[m.start()-12:]))
        except Exception:continue
        result.append(dict(b.listProperties()))
    if len(result)!=2:raise ValueError('機身備份必須包含兩份校驗有效的 BK4')
    return result

def patch_program(original,chip,reverse=False):
    data=read_json(BASE/'assets/patches.json')[chip]
    expected=FINAL[chip] if reverse else ORIGINAL[chip]
    target=ORIGINAL[chip] if reverse else FINAL[chip]
    if sha(original)!=expected:raise ValueError('不支援此程式版本，或已經修改／安裝')
    spans=[]
    for w in data['writes']:
        offset=int(w['file_offset'],16)
        before=bytes.fromhex(w['after_hex'] if reverse else w['before_hex'])
        after=bytes.fromhex(w['before_hex'] if reverse else w['after_hex'])
        if (not before or len(before)!=len(after) or offset<0 or offset+len(before)>len(original)
            or original[offset:offset+len(before)]!=before):raise ValueError('補丁窗口前置條件不符')
        spans.append((offset,before,after))
    spans.sort()
    if any(a[0]+len(a[1])>b[0] for a,b in zip(spans,spans[1:])):raise ValueError('補丁窗口重疊')
    result=bytearray(original)
    for offset,before,after in spans:result[offset:offset+len(before)]=after
    if len(result)!=len(original) or sha(result)!=target:raise ValueError('整體候選檔驗證失敗')
    return bytes(result)

def slot_row_sums(block):
    """12B 槽六係數展開成 3x3 後的三個行和（中性輸入不偏色時都應是 1024）。"""
    a,b,c,d,e,f=struct.unpack('<6h',block)
    return (a+b+1024-a-b, -c+c+d+1024-d, -e-f+e+f+1024)


def colour_record(row):
    """檢查色彩記錄：長度、色度尾八項為零、48 個槽的展開行和、等於供體目標。

    576B 矩陣記錄 = B／A1／A2 三個 192B 端點，每端點 16 槽 × 12B 六係數。
    0.4.x 之前每個端點的 16 槽被填成同一組係數；實機原生外觀的 16 槽彼此
    不同（同一 bank、同一端點內有 15～16 個不同值），0x780F 也是按這 16 槽
    逐槽打包，因此 0.5.0 改為逐槽複製供體值（說明見 git 歷史
    提交 05f3cd2 的 src/fl23/docs/fl23-v050-gamma-and-perslot-matrix.md）。

    這裡不再要求端點內部統一，改為：每個槽展開後行和必須是 1024（結構
    檢查），且整份記錄必須逐位元組等於 assets/fx2_fl23_donor.json 的目標
    值（內容檢查）。後者沿用本工具一貫的嚴格立場：不接受「部分槽新、部分
    槽舊」或任何未經供體佐證的數值進入安裝流程。
    """
    chroma=bytes.fromhex(row['chroma']);matrix=bytes.fromhex(row['matrix'])
    if len(chroma)!=64 or len(matrix)!=576:raise ValueError('色彩記錄長度不符')
    if any(chroma[48:]):raise ValueError('色彩記錄色度尾八項非零')
    for index in range(0,576,12):
        if any(s!=1024 for s in slot_row_sums(matrix[index:index+12])):
            raise ValueError(f'第 {index//12} 個槽展開後行和不是 1024，拒絕寫入')
    for look in read_json(BASE/'assets/fx2_fl23_donor.json')['looks']:
        if look['target_parameter']!=row['parameter'] or look['target_slot']!=row['slot']:
            continue
        want_chroma=b''.join(struct.pack('<8h',*group) for group in look['cc1_int16'])+bytes(16)
        want_matrix=b''.join(struct.pack('<6h',*ab)
                             for name in ('B','A1','A2') for ab in look['matrix_slots'][name])
        if chroma!=want_chroma:raise ValueError('色度不等於供體目標值')
        if matrix!=want_matrix:raise ValueError('矩陣不等於供體目標值（逐槽）')
        return chroma,matrix
    raise ValueError('未知的色彩參數／槽組合，拒絕寫入')

def colour_write_spans():
    """merge_colors 會覆寫的位元組範圍，依 CP 單元索引分組（半開區間）。

    索引 0 對應 unit-02a40001（8192B），1 對應 unit-02a4000d（28672B）。
    用途是讓回復流程能分辨「本工具某一版寫入的色彩」與「來源不明的內容」：
    只要窗口以外與原版一致，窗口內無論屬於哪一版都可安全覆寫回原版。
    """
    spans={0:[],1:[]}
    for parameter,slot in COLOUR_SLOTS:
        spans[0].append((0x1200+parameter,0x1201+parameter))
        spans[0].append((0x1250+slot*64,0x1250+slot*64+64))
        spans[1].append((0x196+parameter,0x197+parameter))
        spans[1].append((0x1e0+slot*768,0x1e0+slot*768+576))
    merged={}
    for index,regions in spans.items():
        out=[]
        for start,end in sorted(regions):
            if out and start<=out[-1][1]:out[-1]=(out[-1][0],max(out[-1][1],end))
            else:out.append((start,end))
        merged[index]=out
    return merged

def matches_outside_colour(current,original,index):
    """current 在色彩寫入窗口以外是否與 original 完全一致。"""
    if len(current)!=len(original):return False
    cursor=0
    for start,end in colour_write_spans()[index]:
        if current[cursor:start]!=original[cursor:start]:return False
        cursor=max(cursor,end)
    return current[cursor:]==original[cursor:]

def colour_window_diff(current,original,index):
    """第一個落在色彩寫入窗口以外的差異偏移；沒有則回傳 None。"""
    if len(current)!=len(original):return 'len'
    skip=[]
    for start,end in colour_write_spans()[index]:skip.append((start,end))
    for offset in range(len(current)):
        if current[offset]==original[offset]:continue
        if any(start<=offset<end for start,end in skip):continue
        return offset
    return None

def merge_colors(unit01,unit0d):
    if len(unit01)!=8192 or len(unit0d)!=28672:raise ValueError('色彩單元長度不符')
    a,b=bytearray(unit01),bytearray(unit0d)
    for row in read_json(BASE/'assets/colors.json'):
        parameter,slot=row['parameter'],row['slot']
        if (parameter,slot) not in COLOUR_SLOTS:raise ValueError('色彩映射不符')
        if unit01[0x1200+parameter] or unit0d[0x196+parameter]:raise ValueError('目標參數已使用，拒絕覆蓋')
        if slot in unit01[0x1200:0x1250] or slot in unit0d[0x196:0x196+74]:raise ValueError('目標色彩槽已有其他參數引用')
        c=0x1250+slot*64;m=0x1e0+slot*768
        if any(unit01[c:c+64]) or any(unit0d[m:m+576]):raise ValueError('目標色彩槽已有資料')
        chroma,matrix=colour_record(row)
        a[0x1200+parameter]=slot;b[0x196+parameter]=slot
        a[c:c+64]=chroma;b[m:m+576]=matrix
    # Check every existing look's mapping and complete referenced records.
    for p in range(55):
        c=unit01[0x1200+p];m=unit0d[0x196+p]
        if a[0x1200+p]!=c or b[0x196+p]!=m:raise ValueError('既有風格映射被改動')
        if a[0x1250+c*64:0x1250+c*64+64]!=unit01[0x1250+c*64:0x1250+c*64+64]:raise ValueError('既有色彩記錄被改動')
        if m<32 and b[0x1e0+m*768:0x1e0+m*768+576]!=unit0d[0x1e0+m*768:0x1e0+m*768+576]:raise ValueError('既有矩陣被改動')
    return bytes(a),bytes(b)

def native_focus_dimension_change(chip,key,a,b):
    # Native 2.01 attributes 02b7..02bc: registered AF boxes 1..3 OSD H/W.
    # Sony rescales these display dimensions against its current YUV area.
    # Their adjacent 13-setting arrays and source coordinates stay compared.
    return (chip==0 and key in (0x02cf1492,0x02cf1494,0x02cf1496,
                               0x02cf1498,0x02cf149a,0x02cf149c)
            and a.attr==b.attr==0x60 and len(a.data)==len(b.data)==4)


def runtime_counter(chip,key,a,b):
    if chip or a.attr!=b.attr:return False
    if key in (0x02cf191c,0x02cf191d,0x02cf196f,0x02cf1970):
        return len(a.data)==len(b.data)==4
    if key==0x01070000 and len(a.data)==len(b.data)==8:return True
    if key==0x02780000 and len(a.data)==len(b.data)==256:
        return a.data[:24]==b.data[:24] and a.data[28:]==b.data[28:]
    return False

def verify_preservation(before,after,expected):
    kept=0;telemetry=[];focus_dimensions=[]
    for chip in [0,1]:
        if set(before[chip])!=set(after[chip]):raise ValueError('設定項目集合改變')
        for key,a in before[chip].items():
            b=after[chip][key]
            if (chip,key) in expected:
                if b.data!=expected[chip,key] or b.attr!=a.attr:raise ValueError('目標設定讀回不符')
            elif (a.data,a.attr)==(b.data,b.attr):kept+=1
            elif native_focus_dimension_change(chip,key,a,b):
                focus_dimensions.append(hex(key))
                print(f'原厂对焦框显示尺寸变化：chip{chip}/{key:#x} data {a.data.hex()}->{b.data.hex()}',flush=True)
            elif runtime_counter(chip,key,a,b):
                telemetry.append(hex(key))
                print(f'会话字段变化：chip{chip}/{key:#x} attr {a.attr}->{b.attr} data {a.data.hex()}->{b.data.hex()}',flush=True)
            else:raise ValueError(f'發現額外設定變動：chip{chip}/{key:#x}，請保存紀錄後檢查')
    return {'preserved_properties':kept,'runtime_counters':telemetry,'native_focus_dimensions':focus_dimensions}

def parse_native(name,raw,mode=None):
    if name=='installer':
        if len(raw)!=240:raise ValueError('安裝器結果長度不符')
        v=struct.unpack_from('<8sIIIIqqqqqqqQQQQ',raw)
        if v[:3]!=(b'A7IRP001',1,mode) or v[3]!=9 or any(v[i] for i in [5,6,7,8,9,10]):
            raise ValueError('安裝器未完整成功；請勿重試或重新開機')
        before=[raw[112:144].hex(),raw[144:176].hex()]
        after=[raw[176:208].hex(),raw[208:240].hex()]
        if before!=(FINAL if mode==2 else ORIGINAL):raise ValueError('寫入前完整檔案雜湊不符')
        if mode and after!=(ORIGINAL if mode==2 else FINAL):raise ValueError('寫入後完整檔案雜湊不符')
        if mode==0 and v[4]!=0:raise ValueError('只校驗模式出現非零寫入')
        return {'mode':mode,'window_writes':v[4],'before':before,'after':after,'readonly_verified':True}
    if name=='probe':
        if len(raw)<72:raise ValueError('診斷結果過短')
        v=struct.unpack_from('<8sIIqqqqQIIII',raw)
        if v[:3]!=(b'A7PRB001',1,16) or any(v[i] for i in [3,4,6]) or len(raw)!=72+sum(v[8:11]):
            raise ValueError('型號欄位、權限或診斷結果不符')
        return {'model_index':v[2],'product_column':9,'root_verified':True}
    if name=='wbi':
        if len(raw)!=192:raise ValueError('開機快照結果長度不符')
        v=struct.unpack('<8sII9q16s16s32s32sII',raw)
        if v[:3]!=(b'A7WBR001',1,mode) or any(v[i] for i in [3,4,5]):raise ValueError('開機快照處理未驗證，請勿重複執行')
        if v[12].rstrip(b'\0')!=b'2\n' or v[14].rstrip(b'\0')!=b'*wbi4\n':raise ValueError('不支援此開機快照起始狀態')
        if mode and (v[7]!=1 or v[9]!=1 or any(v[i] for i in [8,10,11]) or not v[16]
                     or v[13].rstrip(b'\0')!=b'0\n' or v[15].rstrip(b'\0')!=b'*wbi4\n'):
            raise ValueError('開機快照寫入或讀回不完整')
        return {'mode':mode,'verified':True,'fresh_drop_log':bool(v[16])}
    if name=='runtime':
        if len(raw)!=1832:raise ValueError('執行期結果長度不符')
        v=struct.unpack_from('<8sIIqqqQII',raw)
        if v[:3]!=(b'A7RUN001',1,6) or v[3] or v[4] or v[7]!=16:raise ValueError('執行期身分／結果不符')
        spans=[]
        for i,(offset,n) in enumerate([(0x3528804,112),(0x4b2ed19,2),(0x59892b8,40),(0x5989370,40),(0x4b4a5e4,12),(0x4b3b544,12)]):
            spans.append({'offset':offset,'length':n,'memory':raw[56+i*256:56+i*256+n].hex(),
                          'disk':raw[56+i*256+128:56+i*256+128+n].hex()})
        return {'spans':spans,'image_mode':raw[1592:1608].split(b'\0')[0].decode('ascii','replace')}
    raise ValueError('未知原生模組')
