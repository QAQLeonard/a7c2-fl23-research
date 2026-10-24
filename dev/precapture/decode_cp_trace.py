"""Decode a finalized trace file offline; never connects to a camera.

Requires the exact source/epoch/owner/capacity/clock-domain/nonce manifest.
Even a complete file does not prove native owner, clock or camera operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
from support.trace import decode


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('lane',type=Path);p.add_argument('--binding',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.lane.read_bytes();binding=json.loads(a.binding.read_text(encoding='utf-8'))
    report=dict(schema='OFFLINE_CP_OWNER_TRACE/1',**decode(raw,binding),
        lane_sha256=hashlib.sha256(raw).hexdigest(),camera_IO=False)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(str(len(report['records']))+' records decoded; physical capture remains unverified.')


if __name__=='__main__':main()
