"""Bind completed existing-file acquisitions to exact private archive bytes.

Only the two recorded read-only report formats are accepted. This admits
retained FILE evidence, never loaded RAM, task ownership or capture completion.
"""
import hashlib
import io
import zipfile

sha = lambda raw: hashlib.sha256(raw).hexdigest()


def acquisition(archive, report):
    events = report.get('events', [])
    names = [e.get('event') for e in events]
    if not names or names[0] != 'NORMAL_BODY_MATCHED' or names[-1] != 'USB_FINISHED':
        raise ValueError('No completed body-bound readonly acquisition')
    if any(name.startswith('STOPPED') for name in names if isinstance(name, str)):
        raise ValueError('Acquisition stopped; retain without physical admission')
    current = report.get('schema') == 'CURRENT_CP_CONFIGURATION_FILES/1'
    flags = ('upload', 'execution', 'direct_CP_request', 'parameter_or_ROM_RAM_write', 'cleanup', 'capture') if current else (
        'upload', 'native_execution', 'parameter_ROM_RAM_write', 'cleanup', 'CP_send')
    if not current and 'schema' in report:
        raise ValueError('Unsupported readonly acquisition format')
    if any(report.get(k) is not False for k in flags):
        raise ValueError('Acquisition is outside the existing-file-only scope')
    packed = [e for e in events if e.get('event') == 'SNAPSHOT_MIRRORS_VERIFIED']
    if len(packed) != 1 or packed[0].get('sha256') != sha(archive):
        raise ValueError('Acquisition archive identity differs')
    if current and packed[0].get('archive') != 'snapshot.private.zip':
        raise ValueError('Not a complete configuration archive')
    if current and report.get('loaded_RAM_verified') is not False:
        raise ValueError('Configuration acquisition is not a loaded-RAM observation')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if len(set(z.namelist())) != len(z.namelist()):
            raise ValueError('Duplicate acquisition archive member')
        if sum(e.file_size for e in z.infolist()) > 200000000:
            raise ValueError('Acquisition archive exceeds source bound')
        files = {name: z.read(name) for name in z.namelist()}
    if current and set(files) != {'DmmCfg.bin', 'tomco.txt', 'mini_ldr.bin', 'loader_spi.bin', 'cpapp-b.bin'}:
        raise ValueError('Unexpected current-configuration archive members')
    checked = files if current else {'cpapp-b.bin': files.get('cpapp-b.bin', b'')}
    event = 'FILE_CAPTURED' if current else 'SOURCE_CAPTURED'
    for name, raw in checked.items():
        receipts = [e for e in events if e.get('event') == event and e.get('name') == name]
        if not raw or len(receipts) != 1 or receipts[0].get('bytes') != len(raw) or receipts[0].get('sha256') != sha(raw):
            raise ValueError('Captured source identity does not bind this snapshot: '+name)
    if current and names.count('ALL_FIVE_FILES_REREAD_UNCHANGED') != 1:
        raise ValueError('Missing current-file reread receipt')
    if current:
        positions=[i for i,e in enumerate(events) if e.get('event') == 'FILE_CAPTURED']
        archive_at=names.index('SNAPSHOT_MIRRORS_VERIFIED')
        if len(positions) != 5 or not max(positions) < archive_at < names.index('ALL_FIVE_FILES_REREAD_UNCHANGED') < names.index('USB_FINISHED'):
            raise ValueError('Current-file observation order differs')
    return files


def policy_observation(archive, report):
    if report.get('schema') != 'ONE_VENDOR_POLICY_SCALAR_READ/1':
        raise ValueError('Unsupported vendor policy observation')
    for key in ('custom_UIPC_requests', 'uploaded_code', 'parameter_write', 'ROM_RAM_patch', 'capture', 'loaded_CP_RAM_verified'):
        if report.get(key) is not False:
            raise ValueError('Policy observation is outside the fixed read scope')
    if report.get('key') != '0x00fa0182' or report.get('bytes') != 8 or report.get('maximum_vendor_READ40_requests') != 1:
        raise ValueError('Vendor policy query scope differs')
    events = report.get('events', [])
    names = [e.get('event') for e in events]
    if not names or names[0] != 'NORMAL_BODY_MATCHED' or names[-1] != 'USB_FINISHED' or any(
            name.startswith('STOPPED') for name in names if isinstance(name, str)):
        raise ValueError('Incomplete vendor policy observation')
    sequence = ('CP_SOURCE_CAPTURED', 'VENDOR_READ40_INTENT', 'VENDOR_READ40_REPLY',
        'POLICY_SNAPSHOT_UNCHANGED', 'CP_FILE_UNCHANGED', 'USB_FINISHED')
    if any(names.count(name) != 1 for name in sequence) or [names.index(name) for name in sequence] != sorted(names.index(name) for name in sequence):
        raise ValueError('Ambiguous vendor query or observation order')
    receipts = [e for e in events if e.get('event') == 'SNAPSHOT_MIRRORS_VERIFIED' and e.get('archive') == 'snapshot.private.zip']
    if len(receipts) != 1 or receipts[0].get('sha256') != sha(archive):
        raise ValueError('Vendor observation archive identity differs')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if len(set(z.namelist())) != len(z.namelist()) or set(z.namelist()) != {
                'cpapp-b.bin', 'settings-before.bin', 'settings-after.bin', 'policy-scalar.bin'}:
            raise ValueError('Unexpected vendor observation archive members')
        if sum(e.file_size for e in z.infolist()) > 30000000:
            raise ValueError('Vendor observation archive exceeds bound')
        files = {name:z.read(name) for name in z.namelist()}
    source = next(e for e in events if e.get('event') == 'CP_SOURCE_CAPTURED')
    reply = next(e for e in events if e.get('event') == 'VENDOR_READ40_REPLY')
    raw = files['policy-scalar.bin']
    if sha(files['cpapp-b.bin']) != source.get('sha256') or len(raw) != 8 or reply.get('bytes') != 8 or reply.get('raw_hex') != raw.hex():
        raise ValueError('Vendor source or scalar response identity differs')
    return files
