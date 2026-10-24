"""Check all three capture-admission boundaries together, strictly offline.

The current snapshot is an existing-file acquisition, not CP RAM or a timing
trace. Passing source checks cannot set any physical verification to true.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from support.reference import SPECS
from support.capture_validation import audit,SPANS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--current-snapshot',type=Path,required=True)
    p.add_argument('--acquisition-report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes()
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original target CP required')
    with zipfile.ZipFile(a.current_snapshot) as z:
        if z.namelist().count('cpapp-b.bin')!=1:raise ValueError('Ambiguous CP snapshot')
        current=z.read('cpapp-b.bin')
    if len(current)!=len(cp) or any(current[at:at+size]!=cp[at:at+size] for at,size in SPANS):
        raise ValueError('Current source differs in selected capture-validation spans')
    acquisition=json.loads(a.acquisition_report.read_text(encoding='utf-8'))
    events=acquisition.get('events',[])
    if any(acquisition.get(k) is not False for k in ('upload','native_execution',
            'parameter_ROM_RAM_write','cleanup','CP_send')):
        raise ValueError('Acquisition is outside the existing-file-only scope')
    names=[e.get('event') for e in events]
    if not names or names[0]!='NORMAL_BODY_MATCHED' or names[-1]!='USB_FINISHED' or 'STOPPED_NO_REPLAY' in names:
        raise ValueError('No completed body-bound readonly acquisition')
    captured=[e for e in events if e.get('event')=='SOURCE_CAPTURED' and e.get('name')=='cpapp-b.bin']
    if len(captured)!=1 or captured[0].get('sha256')!=hashlib.sha256(current).hexdigest() or captured[0].get('bytes')!=len(current):
        raise ValueError('Captured CP identity does not bind this snapshot')
    packed=[e for e in events if e.get('event')=='SNAPSHOT_MIRRORS_VERIFIED']
    if len(packed)!=1 or packed[0].get('sha256')!=hashlib.sha256(a.current_snapshot.read_bytes()).hexdigest():
        raise ValueError('Acquisition archive identity differs')
    report=dict(schema='OFFLINE_CAPTURE_ADMISSION_TRIPLE/1',**audit(cp),
        original_CP_sha256=hashlib.sha256(cp).hexdigest(),
        current_CP_sha256=hashlib.sha256(current).hexdigest(),
        snapshot_sha256=hashlib.sha256(a.current_snapshot.read_bytes()).hexdigest(),
        acquisition_report_sha256=hashlib.sha256(a.acquisition_report.read_bytes()).hexdigest(),
        completed_existing_file_acquisition_bound=True,
        current_selected_FILE_spans_match=True,loaded_CP_RAM_verified=False,
        physical_completion_claim_allowed=False)
    root=Path(__file__).parent
    report['audit_sources']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),root/'support/capture_validation.py',root/'support/capture_native.py')}
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('All three native source paths checked against the completed readonly snapshot; live pool/completion/exposure verification remains pending.')


if __name__=='__main__':main()
