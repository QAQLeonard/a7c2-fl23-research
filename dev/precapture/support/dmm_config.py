"""Bounded original DMM configuration format; no device access or address admission."""
import struct

CP_CONFIG_SHA256 = "d3466cee62fd86d927236a2c6c37dd633f76cdc181b4ad07a9863696aab76660"


def config_tables(raw):
    """Original config stream: two 80/20-byte table sets, then 8/4-byte units.

    Source bounds from dmm_ext_tbl_Init/dmm_unit_tbl_Init. Numeric IDs and
    rule bytes retain raw names; this parser does not infer runtime addresses.
    """
    at = 0

    def take(n):
        nonlocal at
        if at + n > len(raw):
            raise ValueError('Truncated DMM configuration')
        offset, data = at, raw[at:at+n]
        at += n
        return offset, data

    def extents(limit):
        groups, entries = [], 0
        for _ in range(limit + 1):
            offset, data = take(80)
            head = struct.unpack_from('<4I', data)
            if head[2] == 0xffffffff:
                return groups
            if len(groups) == limit:
                raise ValueError('DMM group count exceeds native capacity')
            children = []
            for _ in range(3073):
                pos, child = take(20)
                values = struct.unpack('<5I', child)
                entries += 1
                if entries > 3072:
                    raise ValueError('DMM extent entry capacity exceeded')
                if values[2] == 0xffffffff:
                    break
                if values[2] > 0x8ff:
                    raise ValueError('DMM extent ID exceeds native index')
                children.append(dict(offset=pos, words=list(values)))
            else:
                raise ValueError('Missing extent terminator')
            groups.append(dict(offset=offset, header=list(head), children=children))
        raise ValueError('Missing group terminator')

    root = extents(2)
    groups = extents(1024)
    units, entries = [], 0
    for _ in range(1025):
        offset, data = take(8)
        kind, flags = struct.unpack('<2I', data)
        if kind == 0xffffffff:
            version_offset, version = take(44)
            if at != len(raw):
                raise ValueError('Unexpected bytes after native version field')
            return dict(roots=root, groups=groups, units=units,
                version_offset=version_offset, version=version.rstrip(b'\0').decode('ascii'))
        if len(units) == 1024:
            raise ValueError('DMM unit table capacity exceeded')
        ids = []
        for _ in range(3073):
            _, data = take(4)
            value = struct.unpack('<I', data)[0]
            entries += 1
            if entries > 3072:
                raise ValueError('DMM unit references exceed native capacity')
            if value == 0xffffffff:
                break
            ids.append(value)
        else:
            raise ValueError('Missing unit terminator')
        units.append(dict(offset=offset, type=kind, flags=flags, extent_ids=ids))
    raise ValueError('Missing unit table terminator')
