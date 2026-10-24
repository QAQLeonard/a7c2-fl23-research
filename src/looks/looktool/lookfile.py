"""Portable fitted looks. No body backup, firmware program or USB transport.

The writer consumes already fitted coefficients; it must never silently drop
an unsupported native photo stage or fit a supplied look again.
"""
import base64
import json
from pathlib import Path
from . import native

SCHEMA = 'a7c2-creative-look/1'
TARGET = {'model': 'ILCE-7CM2', 'firmware': '2.01'}
FORMAT = 'native-5x9x9-s7-planar'


def validate(document):
    if document.get('schema') != SCHEMA or document.get('table_format') != FORMAT:
        raise ValueError('Unknown compiled creative-look format')
    if document.get('target') != TARGET or document.get('base') != 'ST':
        raise ValueError('Compiled look targets a different camera/version/base')
    name = document.get('name', '')
    if not isinstance(name, str) or not 1 <= len(name.encode('utf-8')) <= 63 or any(ord(c) < 32 for c in name):
        raise ValueError('Compiled look needs a name of 1..63 UTF-8 bytes without controls')
    try:
        table = base64.b64decode(document['table_base64'], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid compiled correction table') from exc
    native.decode(table)
    stages = document.get('native_photo')
    if stages is not None:
        from .photoformat import validate_delta
        validate_delta(stages)
    if document.get('raw_profile') is not None:
        from .rawidentity import source_bytes
        source_bytes(document['raw_profile'])
    return table


def read(path):
    document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(document, dict):
        raise ValueError('Compiled look must contain a JSON object')
    validate(document)
    return document


def writer_table(document):
    table = validate(document)
    if document.get('native_photo') is not None:
        raise ValueError('This writer does not yet install native curve/matrix/chroma stages; no camera connection was started')
    return table


def writer_document(document):
    """Accept supported four-stage files without silently omitting a stage."""
    table=validate(document)
    if document.get('native_photo') is not None:
        from .photobasis import SCHEMA as basis_schema
        if document['native_photo'].get('runtime_basis',{}).get('schema')!=basis_schema:
            raise ValueError('This writer needs the supported native integer basis; no camera connection was started')
    return table


def write(path, name, table, *, method, attribution, metrics=None, native_photo=None,
          physical_validation=False, raw_profile=None,source_reference=None):
    document = {'schema': SCHEMA, 'name': name, 'target': TARGET, 'base': 'ST',
                'table_format': FORMAT, 'table_base64': base64.b64encode(table).decode('ascii'),
                'method': method, 'attribution': attribution,
                'validation': {'camera_photos_and_preview_verified': physical_validation,
                               'metrics': metrics or {}}}
    if native_photo is not None:
        document['native_photo'] = native_photo
    if raw_profile is not None:document['raw_profile']=raw_profile
    if source_reference is not None:document['source_reference']=source_reference
    validate(document)
    content=json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)+'\n'
    # Never overwrite a previous fitted look implicitly.
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)
    return document


def inventory(document):
    table = validate(document)
    result={k:v for k,v in document.items() if k not in ('table_base64','raw_profile','source_reference')}
    if document.get('raw_profile'):
        result['raw_profile']={k:v for k,v in document['raw_profile'].items() if k!='dcp_base64'}
    if document.get('source_reference'):
        result['source_reference']={k:v for k,v in document['source_reference'].items() if not k.endswith('_base64')}
    return result | {
        'table_bytes': len(table), 'needs_native_photo_backend': document.get('native_photo') is not None,
        'camera_io': False}
