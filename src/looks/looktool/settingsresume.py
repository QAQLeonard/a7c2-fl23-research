"""Account for a completed native binding update rejected by old array checks."""
import json
from pathlib import Path
import re
from .runtimebindings import BASE_KEYS


def eligible(state):
    if (state.get('schema')!='a7c2-direct-job/1' or state.get('mode')!='install_all'
            or state.get('phase')!='NEEDS_REVIEW' or state.get('failed_during')!='RESTORING_SETTINGS'):
        return False
    error=re.search(r'chip0/(0x[0-9a-fA-F]+)',state.get('error',''))
    journal=state.get('journal')
    if not error or not isinstance(journal,list) or not journal:return False
    proof=[i for i,e in enumerate(journal) if e.get('event')=='complete_program_and_name_bytes_verified']
    if not proof:return False
    batches=state.get('program_builds',[])
    written=[e.get('result',{}).get('windows') for e in journal[:proof[-1]]
             if e.get('event')=='native_result_verified' and e.get('stage')=='checkpoint.staged.so'
             and e.get('mode')==1 and 'windows' in e.get('result',{})]
    if written!=[b.get('windows') for b in batches]:return False
    if not batches and not state.get('settings_resume_from'):return False
    tail=journal[proof[-1]+1:]
    # These events are emitted only after invoke has decoded the complete
    # report and removed its exact worker/request/results. No unknown replay.
    if [e.get('event') for e in tail] != ['native_stage_intent','native_intent',
            'native_extra_result','native_result_verified','native_cleanup_verified']:
        return False
    if any(e.get('stage')!='lut-runtime-staged.so' or e.get('mode')!=1 for e in (tail[0],tail[1],tail[3],tail[4])):
        return False
    result=tail[3].get('result',{})
    targets=result.get('targets',[]);before=result.get('before',[]);after=result.get('after',[])
    if not targets or len(before)!=18 or len(after)!=18:return False
    expected=list(before);mask=0;companions=set();seen=set()
    for row in targets:
        key,index,value=row.get('key'),row.get('index'),row.get('value')
        if (key not in BASE_KEYS or index!=BASE_KEYS[key] or key in seen
                or type(value) is not int or value not in range(12)):
            return False
        seen.add(key);companions.add(key+1);expected[index]=value
        if before[index]!=value:mask|=1<<index
    session_fields={0x02cf191c,0x02cf191d,0x02cf196f,0x02cf1970,
                    0x02cf1492,0x02cf1494,0x02cf1496,
                    0x02cf1498,0x02cf149a,0x02cf149c}
    return (int(error[1],16) in companions|session_fields and after==expected
            and result.get('changed_mask')==mask and type(result.get('current')) is int)


def source(folder):
    root=Path(folder).resolve()
    state=json.loads((root/'direct.private.json').read_text(encoding='utf-8'))
    if not eligible(state):raise ValueError('No completed look-setting array failure to continue')
    if not isinstance(state.get('identity'),dict) or not isinstance(state.get('bundle_options'),dict):
        raise ValueError('Saved body binding or installation selection is missing')
    return root,state
