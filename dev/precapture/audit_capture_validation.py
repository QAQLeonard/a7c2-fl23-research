"""Check all three capture-admission boundaries together, strictly offline.

The current snapshot is an existing-file acquisition, not CP RAM or a timing
trace. Passing source checks cannot set any physical verification to true.
"""
import argparse
import hashlib
import json
from pathlib import Path

from support.reference import SPECS
from support.capture_validation import audit,SPANS
from support.capture_acquisition import acquisition as bind_acquisition, policy_observation
from support.backup import scalar_segment
from support.backing_config import audit as audit_backing_stream
from support.pool_notification import SCENARIOS


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--current-snapshot',type=Path,required=True)
    p.add_argument('--acquisition-report',type=Path,required=True)
    p.add_argument('--policy-snapshot',type=Path,
        help='Optional completed one-query vendor policy archive; requires --policy-report')
    p.add_argument('--policy-report',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes()
    if bool(a.policy_snapshot) != bool(a.policy_report):
        p.error('--policy-snapshot and --policy-report must be supplied together')
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Exact original target CP required')
    captured_archive = a.current_snapshot.read_bytes()
    acquisition=json.loads(a.acquisition_report.read_text(encoding='utf-8'))
    files=bind_acquisition(captured_archive,acquisition)
    current=files['cpapp-b.bin']
    if len(current)!=len(cp) or any(current[at:at+size]!=cp[at:at+size] for at,size in SPANS):
        raise ValueError('Current source differs in selected capture-validation spans')
    report=dict(schema='OFFLINE_CAPTURE_ADMISSION_TRIPLE/1',**audit(cp),
        original_CP_sha256=hashlib.sha256(cp).hexdigest(),
        current_CP_sha256=hashlib.sha256(current).hexdigest(),
        snapshot_sha256=hashlib.sha256(captured_archive).hexdigest(),
        acquisition_report_sha256=hashlib.sha256(a.acquisition_report.read_bytes()).hexdigest(),
        completed_existing_file_acquisition_bound=True,
        current_selected_FILE_spans_match=True,loaded_CP_RAM_verified=False,
        physical_completion_claim_allowed=False)
    if a.policy_snapshot:
        if 'DmmCfg.bin' not in files:
            raise ValueError('Combined policy analysis requires a completed current-configuration acquisition')
        archive=a.policy_snapshot.read_bytes()
        observed=policy_observation(archive,json.loads(a.policy_report.read_text(encoding='utf-8')))
        if observed['cpapp-b.bin'] != current:
            raise ValueError('Policy observation and configuration snapshot have different CP source')
        def segments(raw):
            first=scalar_segment(raw,0,[0xfa0182])
            offset=(first['size']+4095)&~4095
            second=scalar_segment(raw,offset,[0xfa0182])
            if offset+second['size'] != len(raw):
                raise ValueError('Unexpected BK4 snapshot tail')
            return first,second
        before=observed['settings-before.bin'];after=observed['settings-after.bin']
        prior,next_values=segments(before),segments(after)
        values=[s['records'][0xfa0182]['data'] for s in prior]
        if values != [s['records'][0xfa0182]['data'] for s in next_values]:
            raise ValueError('Policy scalar changed during vendor observation')
        matching=[s for s in prior if s['records'][0xfa0182]['data'] == observed['policy-scalar.bin']]
        if len(matching) != 1:
            raise ValueError('Ambiguous retained segment for the observed policy scalar')
        selected=matching[0]
        raw_segment=before[selected['offset']:selected['offset']+selected['size']]
        models={}
        for scenario in SCENARIOS:
            result=audit_backing_stream(cp,files['DmmCfg.bin'],notification=scenario,primary_backup=raw_segment)
            if any(current[s['offset']:s['offset']+s['bytes']] != cp[s['offset']:s['offset']+s['bytes']]
                    for s in result['source_spans']):
                raise ValueError('Current CP differs in combined backing/notification source')
            models[scenario]=result
        report['current_configuration_and_policy']=dict(
            current_config_sha256=hashlib.sha256(files['DmmCfg.bin']).hexdigest(),
            CP_vendor_scalar_observed=True,matched_snapshot_segment_offset=hex(selected['offset']),
            policy_archive_sha256=hashlib.sha256(archive).hexdigest(),
            original_models=models,all_selected_CP_FILE_spans_match=True,
            same_boot_between_two_acquisitions_verified=False,
            loaded_policy_stream_bytes_verified=False,physical_resource_ownership_verified=False)
        report['remaining_physical_requirements']=[
            'Loaded policy bytes,live backing-resource ownership and reference lifetime',
            'Matched native completion with no late owner or ingress',
            'Same-capture exposure-end and S2 timestamps linked to retained pixels',
            'Real half-press RAW retention,full-press durable save and cancel/release',
            'Default-off in-camera control and ordinary-shooting/recovery acceptance']
    root=Path(__file__).parent
    report['audit_sources']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),root/'support/capture_validation.py',root/'support/capture_native.py',
            root/'support/capture_acquisition.py')}
    if a.policy_snapshot:
        report['audit_sources'].update({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root/'support/backing_config.py',root/'support/backup_binding.py',
                root/'support/backup.py',root/'support/dmm_config.py',root/'support/pool_notification.py')})
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('All three native source paths checked against the completed readonly snapshot; live pool/completion/exposure verification remains pending.')


if __name__=='__main__':main()
