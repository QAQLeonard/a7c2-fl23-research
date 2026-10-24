"""Isolated 2.01 trial: keep a live LUT pending until each hardware write.

No new RAM, padding fields, loader extents or allocations. The existing dirty
byte stays truthy, with bit 7 marking this live custom path and bits 1/2/3/5
acknowledging the four native hardware destinations. Building a bank resets
the acknowledgments. Copying to a host buffer does not acknowledge hardware.

The native uploader's saved frame identifies our caller. Its final callback
acknowledges matching banks in both native parameter frames before the existing
multi-core unlock. The filter reads the published owner, not acknowledgment bits
in an older parameter copy. Returning from these synchronous writes is not a
frame-display ack. Equivalent loops replace two original unrolled config-byte
copies; their exact code ranges host the scoped helpers. No zero-filled storage
is treated as an allocation. The original native repeat bit bypasses tagging.
"""
import struct
from . import uploadgate

BASE = 0x108000

# Exact reviewed before/after instructions. Names identify the storage audit.
TRIAL2_WINDOWS = (
    ('producer_islands', 0x1354bc,
     '00bf00bf00bf00bf00bf00bf00bf',
     '05e0f2f12698eff145fc42e000bf'),
    ('initial_branch', 0x13550c,
     '1fd1',
     'd9d1'),
    ('cache_branch', 0x13554c,
     '24e0',
     'b7e7'),
    ('first', 0xb2750e,
     'd4bbb5f8880140f20121884234d100f02cb8',
     'dcbbb5f88811a1f20121b1bb00f02db800bf'),
    ('tail', 0xb27578,
     'd8f80c00d0f8b00608b10df6f39f42f6b0100df6d89f',
     '95f8241041f0800185f824100df6e39f0ef6069800bf'),
    ('consumer_copy', 0x324d3a,
     '30788df80c0070788df80d00f0788df80e0030798df80f0070798df81000b0798df81100f0798df81200307a8df81300707a8df81400b07a8df81500f07a8df81600307b8df81700707b8df81800b07b8df81900f07b8df81a00307c8df81b00707c8df81c00b07c8df81d00',
     '03a90022022a02d0b05c01f8010b0132132af7d32ae074b9b5f88811a1f2012149b942f6b011c0f27911097d490602d4812180f82410704705980ff2910188420ad1039a107e010606d551696b68994202d10199084310767746daf116eb384700bf00bf00bf00bf00bf00bf'),
    ('consume', 0x324de4,
     'd8b17069c8b19af8041019b14aa017f3c2f3706900218df80410029001a920465df30cfe9af8040038b16268029940f22060c0f2f90017f3aef3',
     'd8b16168c1f3025102228a40104214d1706990b100210191029001a9204614465df30cfe09e000bf00bf00bf00bf00bf00bf00bf00bf00bf00bf'),
    ('unlock_hook', 0x682ac8,
     '7cf67cec',
     'a2f453f9'),
)


# Trial 3 reads acknowledgment state from the published native frame and
# mirrors completed uploads into both native frames. Trial 2 remains reversible.
_REPLACEMENTS = {
    'consumer_copy': '03a90022022a02d0b05c01f8010b0132132af7d32ae074b9b5f88811a1f2012149b942f6b011c0f27911097d490602d4812180f824107047010638d51ff33bfa00f2646595f82400010630d5296a726991422cd16168c1f30251032927d0042925d802228a4010423cd121e0',
    'consume': 'd8b1c4e700227069b8b100210191029001a92046144600bf00bf00bf00bf00bf5df30cfe09e000bf00bf00bf00bf00bf00bf00bf00bf00bf00bf',
    'unlock_hook': 'a2f4e3f9',
}
WINDOWS = tuple((name, at, before, _REPLACEMENTS.get(name, after))
                for name, at, before, after in TRIAL2_WINDOWS) + (
    ('consumer_override_copy', 0x324e62,
     '90f895108df80c1090f896108df80d1090f898108df80e1090f899108df80f1090f89a108df8101090f89b108df8111090f89c108df8121090f89d108df8131090f89e108df8141090f89f108df8151090f8a0108df8161090f8a1108df8171090f8a2108df8181090f8a3108df8191090f8a4108df81a1090f8a5108df81b1090f8a61090f897008df81c108df81d00',
     '90f895108df80c1090f896108df80d1000f298000df10e010f2210f8013b01f8013b013af9d110f8100c8df81d002fe0d0b50998aff28f01884214d1059e96b143f6a852c0f200220223107e010605d551696c68a14201d13043107641f6fc142244013bf1d1daf17cead0bd00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf'),
)

# Unchanged context proves the source frame layout, pending-byte producer,
# copied-buffer path, uploader body and native device mapping used above.
GUARDS = (
    (0x1354fa, 'd8f80800012180f82410d9f8041089790129'),
    (0x13550e, 'd8f80c105c3143e0'),
    (0x135548, 'd8f80800'),
    (0x324d28, 'f0b503af2de9000788b01e46814692468846'),
    (0x682a20,
     'f0b503af4df804bd04460d464af640560121606881517cf616ec606869684ff4967200f5504093f6e2ed'
     '69686068f02200f5524001f5967193f6d8ed69686068f02200f5534001f5077193f6d0ed'
     '69686068c02200f5544001f5437193f6c6ed69686068c82200f5554001f5737193f6beed'
     '69686068a02200f5564001f2944193f6b4ed69686068a02200f5574001f2345193f6aced'
     '69686068802200f5584001f2d45193f6a2ed'),
    (0x682acc, '6068002181515df804bbf0bd'),
    (0x324f44,
     '80b56f4690b190f86026002a18bf022200ebc200d0f88421002a0bd000f5c0703df628fe'
     '03280ad8c0b280bd012906d10ca002e0012902d102a017f3fcf2042080bd00bf'
     '43433a2047657443616d204465764c7574536574746572204e554c4c00000000'),
    (0x162bb8, '406800f1406000f5fa004fea3050042803d803a151f8200070470420704700bf0000000001000000020000000400000003000000'),
    # Native two-frame owner, state offset and publication, not guessed RAM.
    (0x6441f0, '4df2137043f2387141f6fc12c0f2ac10c0f20021007810fb02107047'),
    (0x134f36, '08f5597b4ff4b56205f559715846e1f362eb08f60c1a05f60c114ff488725046e1f35aeb'),
    (0x135012, '08f5627617901a9608f614161c9603f17c061b9605f52c761d9601f110061e96'),
    (0x64429e, '4df2137543f238714bf2383441f6fc12c0f2ac15c0f20021c0f22814287880f0010010fb02112046f0f613f654f8c82f2878636880f0010061692870'),
)


def active(cp):
    return any(cp[at:at + len(bytes.fromhex(after))] == bytes.fromhex(after)
               for _, at, _, after in WINDOWS + TRIAL2_WINDOWS)


def normalize(cp):
    """Validate a complete old/trial layout and return its old native underlay."""
    source = uploadgate._source(cp)
    pending = active(source)
    offset, size, address = struct.unpack_from('<3I', source, 0x20124)
    if address != BASE + 0x20000 + offset or 0x20000 + offset + size > len(source):
        raise ValueError('Pending LUT trial loaded text mapping differs')
    for at, text in GUARDS:
        raw = bytes.fromhex(text)
        if source[at:at + len(raw)] != raw:
            raise ValueError('Pending LUT trial context differs at ' + hex(at))
    result = bytearray(source)
    layout = WINDOWS
    if pending:
        layout = next((rows for rows in (WINDOWS, TRIAL2_WINDOWS)
                       if all(source[at:at + len(bytes.fromhex(after))] == bytes.fromhex(after)
                              for _, at, _, after in rows)), None)
        if layout is None:
            raise ValueError('Incomplete or conflicting pending LUT trial')
    expected = {at: bytes.fromhex(after) for _, at, _, after in layout} if pending else {}
    for name, at, before, after in WINDOWS:
        old, new = bytes.fromhex(before), bytes.fromhex(after)
        if len(old) != len(new) or not (0x20000 + offset <= at < at + len(new) <= 0x20000 + offset + size
                and address <= at + BASE < at + BASE + len(new) <= address + size):
            raise ValueError('Pending LUT trial exceeds allocated text')
        if source[at:at + len(new)] != expected.get(at, old):
            raise ValueError('Incomplete or conflicting pending LUT trial: ' + name)
        result[at:at + len(old)] = old
    if pending and source[uploadgate.OFFSET:uploadgate.OFFSET + 4] != uploadgate.NATIVE:
        raise ValueError('Pending LUT trial needs the native repeat gate')
    result = bytes(result)
    uploadgate.validate(result)
    return result


def install(cp):
    """Return one bounded candidate; installation/readback belongs to DirectJob."""
    target = bytearray(uploadgate.restore(normalize(cp)))
    for _, at, _, after in WINDOWS:
        raw = bytes.fromhex(after)
        target[at:at + len(raw)] = raw
    target = bytes(target)
    normalize(target)
    return target


def factory_windows():
    """Six Sony originals supplement the existing factory-owned regions."""
    result = []
    for name, at, before, _ in WINDOWS:
        if name in ('initial_branch', 'cache_branch', 'consumer_copy', 'consume',
                    'unlock_hook', 'consumer_override_copy'):
            result.append((at, bytes.fromhex(before)))
    return result
