"""Derive selected-slot writes from fresh descriptors; preserve unrelated data."""
import struct

PROTECTED=(0x02a40000,0x02a40001,0x02a40002,0x02a4000d)
SAVED_TELEMETRY=0x02cf0b6e
PRESERVATION_SCOPE={'schema':'a7c2-lut-settings/2','AP_group':'02cf','protected_CP_units':[hex(k) for k in PROTECTED],
    'diagnostic_only_AP_field':hex(SAVED_TELEMETRY),'other_runtime_groups':'backed-up; not compared or written'}

def plan(ap,ram,saved,slots,*,hash_checks=True):
    from .device_layout import identify_ap,structural_ap
    (identify_ap if hash_checks else structural_ap)(ap)
    if not slots or any(type(s) is not int or s not in range(1,7) for s in slots):raise ValueError('Select slots 1..6')
    def descriptor(attribute):
        at=0x57c6710+(attribute-0x14ea)*32
        row=struct.unpack_from('<8I',ap,at)
        if row[6]!=attribute or row[1]>>16!=0x02cf:raise ValueError('Descriptor identity/group mismatch')
        return row
    fields=[]
    for slot in sorted(set(slots)):
        selector=slot+9;row=descriptor(0x14ea+selector);key=row[1]
        if row[0]!=3 or row[2]!=0x10000 or len(ram[0][key].data)!=1 or len(saved[0][key].data)!=1:raise ValueError('Invalid base-look descriptor/value')
        fields.append({'slot':slot,'key':key,'before_ram':ram[0][key].data.hex(),'before_saved':saved[0][key].data.hex(),'after':'00'})
        for i in range(8):
            row=descriptor(0x1520+i*18+selector);base=descriptor(0x1520+i*18);key=row[1]
            value=ram[0][base[1]].data
            if row[0]!=0 or row[2]!=0x40000 or len(value)!=4 or len(ram[0][key].data)!=4 or len(saved[0][key].data)!=4:raise ValueError('Invalid adjustment descriptor/value')
            fields.append({'slot':slot,'key':key,'before_ram':ram[0][key].data.hex(),'before_saved':saved[0][key].data.hex(),'after':value.hex()})
    if len({f['key'] for f in fields})!=len(fields):raise ValueError('Duplicate selected settings')
    if any(f['before_ram']!=f['before_saved'] for f in fields):raise ValueError('Save selected camera recipes before importing; RAM/storage differ')
    return fields

def require_save_preserves_unsaved(ram,saved,selected):
    # The stored-only field is known to have a separate live representation;
    # its layout is checked; its volatile value is never written here.
    for key,value in ram[0].items():
        if key>>16==0x02cf and key not in selected and key!=0x02cf0b6e:
            other=saved[0].get(key)
            if other is None or (value.data,value.attr)!=(other.data,other.attr):
                raise ValueError('Unselected unsaved AP settings would be persisted; save them first')

def compare(before,after,expected,core,*,expected_cp=None):
    """Preserve writable AP settings and protected CP units, not telemetry.

    Other AP groups are never written by this importer. Complete original
    snapshots remain in both private backups.
    """
    if any(int(k)>>16!=0x02cf or int(k)==SAVED_TELEMETRY for k in expected):
        raise ValueError('Expected setting outside writable AP preservation scope')
    if any(int(k) not in before[0] or int(k) not in after[0] for k in expected):
        raise ValueError('Selected setting missing')
    allowed={(0,int(k)):bytes.fromhex(v) for k,v in expected.items()}
    # FL23 intentionally updates these two color units. The caller guards the
    # exact color windows; the other protected units remain immutable.
    expected_cp=expected_cp or {}
    if any(k not in (0x02a40001,0x02a4000d) for k in expected_cp):
        raise ValueError('Expected CP setting outside FL23 color units')
    allowed.update({(1,k):bytes.fromhex(v) for k,v in expected_cp.items()})
    for state in [before,after]:
        if any(k not in state[1] for k in PROTECTED):raise ValueError('Protected CP unit missing')
    if SAVED_TELEMETRY in before[0] or SAVED_TELEMETRY in after[0]:
        a,b=before[0].get(SAVED_TELEMETRY),after[0].get(SAVED_TELEMETRY)
        if a is None or b is None or a.attr!=b.attr or len(a.data)!=len(b.data):raise ValueError('Diagnostic AP field layout differs')
    scope=lambda state:[{k:v for k,v in state[0].items() if k>>16==0x02cf and k!=SAVED_TELEMETRY},
        {k:state[1][k] for k in PROTECTED}]
    return core.verify_preservation(scope(before),scope(after),allowed)


def protected_equal(before,after):
    for key in PROTECTED:
        if (before[1][key].data,before[1][key].attr)!=(after[1][key].data,after[1][key].attr):raise ValueError('Protected CP unit changed')
