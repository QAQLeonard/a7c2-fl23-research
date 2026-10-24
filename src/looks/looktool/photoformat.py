"""Native photo-stage records, without USB, firmware patching or pixel claims.

These codecs describe the CP gamma/matrix/chroma loaders. A decoded record is
not an ISP simulator: sample scaling, the 16 matrix selectors and the eight
chroma channels must be established separately before fitting their effects.
"""
from dataclasses import dataclass
import struct


GAMMA_BYTES = 576
MATRIX_BYTES = 576  # three planes, sixteen selectors, six signed coefficients
CHROMA_BYTES = 64
BANK_BYTES = 2 * GAMMA_BYTES + MATRIX_BYTES + CHROMA_BYTES
DELTA_SCHEMA = 'a7c2-native-photo-relative/1'
WIDTHS = (32, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)
BASES = (0, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)


def signed16(value):
    return (int(value) + 32768) % 65536 - 32768


def gamma_coordinates(record):
    if len(record) != GAMMA_BYTES:
        raise ValueError('Expected a 576-byte gamma record')
    nodes, consumed = [0], 0
    for width, base, shift in zip(WIDTHS, BASES, record[0x204:0x210]):
        step = width >> shift
        if not step:
            raise ValueError('Gamma record requires the native fallback')
        count = width // step
        nodes.extend(min(base + j * step, 65535)
                     for j in range(1, min(count, 128 - consumed) + 1))
        consumed += count
    if len(nodes) != 129 or consumed < 128 or any(a >= b for a, b in zip(nodes, nodes[1:])):
        raise ValueError('Gamma coordinates do not fill 129 increasing nodes')
    return tuple(nodes)


def gamma_values(record):
    gamma_coordinates(record)
    return struct.unpack_from('<129I', record)


def replace_gamma_values(template, values):
    """Keep native metadata; caller supplies values in established native units.

    Do not normalize by 65535 or the final ordinate here: neither has been
    established as a universal JPEG normalization. Pointer-bearing templates
    are local evidence only, never a portable firmware payload.
    """
    original = gamma_values(template)
    values = tuple(values)
    if len(values) != 129 or any(int(v) != v or not 0 <= v <= 0x3ffff for v in values):
        raise ValueError('Expected 129 unsigned native ordinates in 0..0x3ffff')
    if any(a > b for a, b in zip(values, values[1:])):
        raise ValueError('Gamma ordinates must be monotone')
    if struct.unpack_from('<I', template, 0x220)[0] != original[-1]:
        raise ValueError('Gamma template has different endpoint metadata semantics')
    result = bytearray(template)
    struct.pack_into('<129I', result, 0, *values)
    struct.pack_into('<I', result, 0x220, values[-1])
    return bytes(result)


def expand_matrix(coefficients, row_sums):
    a, b, c, d, e, f = map(int, coefficients)
    r, g, blue = map(int, row_sums)
    return tuple(signed16(v) for v in
                 (r + a + b, -a, -b, -c, g + c + d, -d, -e, -f, blue + e + f))


def encode_matrix(matrix, row_sums):
    matrix, row_sums = tuple(matrix), tuple(row_sums)
    if len(matrix) != 9 or len(row_sums) != 3:
        raise ValueError('Expected a 3x3 matrix and three row sums')
    if any(int(v) != v or not -32768 <= v <= 32767 for v in matrix):
        raise ValueError('Matrix is outside signed16 encoding')
    if any(sum(matrix[j * 3:j * 3 + 3]) != row_sums[j] for j in range(3)):
        raise ValueError('Native matrix row sums come from the current context')
    coefficients = tuple(-int(matrix[j]) for j in (1, 2, 3, 5, 6, 7))
    if any(not -32768 <= v <= 32767 for v in coefficients):
        raise ValueError('Native matrix coefficient overflows signed16')
    if expand_matrix(coefficients, row_sums) != matrix:
        raise ValueError('Native matrix expansion differs')
    return struct.pack('<6h', *coefficients)


def expand_chroma(record, adjustment=(0,) * 8):
    if len(record) != CHROMA_BYTES or len(adjustment) != 8:
        raise ValueError('Expected a 64-byte chroma record and eight adjustments')
    values = struct.unpack_from('<24h', record)
    base = [signed16(a + b) for a, b in zip(values[:8], adjustment)]
    return tuple(base + [signed16(a + b) for a, b in zip(base, values[8:16])] +
                 [signed16(a + b) for a, b in zip(base, values[16:24])])


def encode_chroma(planes, template):
    if len(planes) != 24 or len(template) != CHROMA_BYTES:
        raise ValueError('Expected three eight-channel planes and a 64-byte template')
    if any(int(v) != v or not -32768 <= v <= 32767 for v in planes):
        raise ValueError('Chroma plane is outside signed16 encoding')
    base = tuple(planes[:8])
    d1 = tuple(signed16(a - b) for a, b in zip(planes[8:16], base))
    d2 = tuple(signed16(a - b) for a, b in zip(planes[16:24], base))
    return struct.pack('<24h', *(base + d1 + d2)) + template[48:]


def secondary_chroma(record, unit, domain, adjustment=(0,) * 8):
    """Second native loader: common color base plus shared domain parameters.

    The second eight values come from unit+0xf00/domain*16, not from the
    color record's two difference planes. Keep these global values separate
    from per-look coefficients.
    """
    if len(unit) != 8192 or domain not in (0, 1):
        raise ValueError('Expected an 8192-byte unit and native domain 0 or 1')
    base = expand_chroma(record, adjustment)[:8]
    return base + struct.unpack_from('<8h', unit, 0xf00 + domain * 16)


@dataclass(frozen=True)
class PhotoBank:
    """An offline record bundle, not an installable CP bank or allocation."""
    regular_curve: bytes
    still_curve: bytes
    matrices: bytes
    chroma: bytes

    def __post_init__(self):
        for record in (self.regular_curve, self.still_curve):
            gamma_coordinates(record)
        if len(self.matrices) != MATRIX_BYTES or len(self.chroma) != CHROMA_BYTES:
            raise ValueError('Wrong native matrix/chroma record extent')

    def pack(self):
        return self.regular_curve + self.still_curve + self.matrices + self.chroma

    @classmethod
    def unpack(cls, blob):
        if len(blob) != BANK_BYTES:
            raise ValueError('Wrong offline photo-bank extent')
        return cls(blob[:576], blob[576:1152], blob[1152:1728], blob[1728:])

    def matrix(self, plane, selector, row_sums):
        if plane not in range(3) or selector not in range(16):
            raise ValueError('Expected plane 0..2 and selector 0..15')
        coefficients = struct.unpack_from('<6h', self.matrices, plane * 192 + selector * 12)
        return expand_matrix(coefficients, row_sums)

    def replace_matrix(self, plane, selector, matrix, row_sums):
        self.matrix(plane, selector, row_sums)
        result = bytearray(self.matrices)
        result[plane * 192 + selector * 12:plane * 192 + selector * 12 + 12] = encode_matrix(matrix, row_sums)
        return PhotoBank(self.regular_curve, self.still_curve, bytes(result), self.chroma)

    def perturb(self, *, curve_gain=0., curve_toe=0., curve_shoulder=0.,
                matrix_delta=(0,) * 6, chroma_delta=(0,) * 8):
        """Make a parameter-isolation probe, without predicting its RGB effect.

        Curve changes are relative to each native record's own ordinate range,
        not JPEG normalization. Matrix deltas apply identically to all 3x16
        native records; chroma deltas change the common base, keeping the two
        native difference planes and trailing metadata intact.
        """
        if len(matrix_delta) != 6 or len(chroma_delta) != 8:
            raise ValueError('Expected six matrix and eight chroma deltas')
        if any(int(v) != v for v in tuple(matrix_delta) + tuple(chroma_delta)):
            raise ValueError('Native matrix/chroma deltas must be integer coefficients')

        def tone(record):
            values = gamma_values(record)
            top = values[-1]
            if not top:
                raise ValueError('Cannot perturb a zero-range gamma template')
            changed = []
            for value in values:
                x = value / top
                offset = curve_gain * x + curve_toe * x * (1 - x) ** 2
                offset += curve_shoulder * x ** 2 * (1 - x)
                changed.append(round(value + top * offset))
            return replace_gamma_values(record, changed)

        coefficients = struct.unpack('<288h', self.matrices)
        changed = [v + matrix_delta[j % 6] for j, v in enumerate(coefficients)]
        if any(not -32768 <= v <= 32767 for v in changed):
            raise ValueError('Matrix perturbation overflows native coefficients')
        matrices = struct.pack('<288h', *changed)
        base = struct.unpack_from('<8h', self.chroma)
        base = tuple(v + d for v, d in zip(base, chroma_delta))
        if any(not -32768 <= v <= 32767 for v in base):
            raise ValueError('Chroma perturbation overflows native coefficients')
        chroma = struct.pack('<8h', *base) + self.chroma[16:]
        return PhotoBank(tone(self.regular_curve), tone(self.still_curve), matrices, chroma)


def custom_gamma_rows(original, *, resolve_null=True):
    """Copy ST's two domains, preserving the native null-record fallback.

    Native gamma 0x42b44c resolves a null row/column through row0,column6.
    The custom wrapper copies the selected record before entering that
    function, so its added rows must already contain the effective pointer.
    Keep the fifty native rows unchanged. The legacy variant is solely for
    recognizing an exact old installed layout during an in-place upgrade.
    """
    if len(original) != 50*28:
        raise ValueError('Expected fifty native gamma rows')
    fallback = struct.unpack_from('<I', original, 24)[0]
    result = bytearray()
    for _ in range(6):
        for row in (0, 10):
            for column in range(7):
                pointer = struct.unpack_from('<I', original, row*28+column*4)[0]
                if resolve_null and not pointer:
                    if not fallback:
                        raise ValueError('Native ST gamma fallback is unavailable')
                    pointer = fallback
                result.extend(struct.pack('<I', pointer))
    return bytes(result)


def extract_bank(cp, chroma_unit, matrix_unit, *, gamma_table_va,
                 regular_row, still_row, color_parameter, link_base=0x108000):
    """Extract explicit native bindings; do not infer ownership of unused slots."""
    if len(chroma_unit) != 8192 or len(matrix_unit) != 28672:
        raise ValueError('Wrong native CP unit extents')
    if not 0 <= color_parameter < 74 or min(regular_row, still_row) < 0:
        raise ValueError('Native selector is outside the audited lookup extent')

    def curve(row, column):
        at = gamma_table_va - link_base + row * 28 + column * 4
        if not 0 <= at <= len(cp) - 4:
            raise ValueError('Gamma lookup is outside the supplied program')
        pointer = struct.unpack_from('<I', cp, at)[0]
        offset = pointer - link_base
        if not pointer or not 0 <= offset <= len(cp) - GAMMA_BYTES:
            raise ValueError('Gamma record requires native fallback or lies outside the program')
        return cp[offset:offset + GAMMA_BYTES], pointer

    regular, regular_pointer = curve(regular_row, 0)
    still, still_pointer = curve(still_row, 6)
    chroma_slot = chroma_unit[0x1200 + color_parameter]
    matrix_slot = matrix_unit[0x196 + color_parameter]
    if chroma_slot > 39 or matrix_slot >= 32:
        raise ValueError('Expected non-fallback chroma and full 3x16 matrix banks')
    cstart, mstart = 0x1250 + chroma_slot * 64, 0x1e0 + matrix_slot * 768
    bank = PhotoBank(regular, still, matrix_unit[mstart:mstart + 576],
                     chroma_unit[cstart:cstart + 64])
    return bank, {'regular_row': regular_row, 'still_row': still_row,
                  'regular_pointer': hex(regular_pointer), 'still_pointer': hex(still_pointer),
                  'color_parameter': color_parameter, 'matrix_slot': matrix_slot,
                  'chroma_slot': chroma_slot,
                  'regular_runtime_metadata': regular[0x228:0x23c].hex(),
                  'still_runtime_metadata': still[0x228:0x23c].hex(),
                  'ISP_pixel_model_verified': False}


def validate_delta(document):
    """Full record freedom, expressed relative to fresh camera ST records.

    Unlike the seventeen-control measurement basis, this format carries every
    ordinate, 3x16x6 matrix coefficient and 3x8 expanded chroma coefficient.
    Native metadata, per-body matrices and pointers are never copied into it.
    """
    if not isinstance(document, dict) or document.get('schema') != DELTA_SCHEMA:
        raise ValueError('Unknown native photo delta format')

    def integers(values, shape, bound):
        if not isinstance(values, list) or len(values) != shape[0]:
            raise ValueError('Wrong native photo delta dimensions')
        if len(shape) > 1:
            for row in values:
                integers(row, shape[1:], bound)
        elif any(type(v) is not int or abs(v) > bound for v in values):
            raise ValueError('Native photo deltas must be bounded integer coefficients')

    curves = document.get('curves')
    if not isinstance(curves, dict) or set(curves) != {'regular', 'still'}:
        raise ValueError('Both native curve domains must be explicit')
    for record in curves.values():
        if not isinstance(record, dict) or set(record) != {'coordinates', 'ordinate_delta'}:
            raise ValueError('Expected native curve coordinates and ordinate deltas')
        nodes = record['coordinates']
        integers(nodes, (129,), 65535)
        if nodes[0] != 0 or nodes[-1] != 65535 or any(a >= b for a, b in zip(nodes, nodes[1:])):
            raise ValueError('Native curve coordinates must increase from 0 to 65535')
        integers(record['ordinate_delta'], (129,), 0x3ffff)
    integers(document.get('matrix_coefficient_delta'), (3, 16, 6), 65535)
    integers(document.get('chroma_plane_delta'), (3, 8), 65535)


def difference(before, after):
    """Describe authored stage changes; do not serialize native body templates."""
    curves = {}
    for domain, old, new in (('regular', before.regular_curve, after.regular_curve),
                             ('still', before.still_curve, after.still_curve)):
        if old[0x204:0x220] != new[0x204:0x220] or old[0x224:] != new[0x224:]:
            raise ValueError('Portable curve deltas cannot change native metadata or pointers')
        curves[domain] = {'coordinates': list(gamma_coordinates(old)),
                          'ordinate_delta': [b - a for a, b in zip(gamma_values(old), gamma_values(new))]}
    if before.chroma[48:] != after.chroma[48:]:
        raise ValueError('Portable chroma deltas cannot change trailing native metadata')
    a, b = struct.unpack('<288h', before.matrices), struct.unpack('<288h', after.matrices)
    matrix = [[[b[p * 96 + s * 6 + j] - a[p * 96 + s * 6 + j] for j in range(6)]
               for s in range(16)] for p in range(3)]
    a, b = expand_chroma(before.chroma), expand_chroma(after.chroma)
    result = {'schema': DELTA_SCHEMA, 'curves': curves, 'matrix_coefficient_delta': matrix,
              'chroma_plane_delta': [[b[p * 8 + j] - a[p * 8 + j] for j in range(8)] for p in range(3)]}
    validate_delta(result)
    return result


def apply_delta(baseline, document):
    """Rebuild records using this body's baseline; no settings/firmware writes."""
    validate_delta(document)
    curves = []
    for domain, record in (('regular', baseline.regular_curve), ('still', baseline.still_curve)):
        change = document['curves'][domain]
        if tuple(change['coordinates']) != gamma_coordinates(record):
            raise ValueError('Camera gamma coordinates differ from the fitted look')
        curves.append(replace_gamma_values(record, [v + d for v, d in
                      zip(gamma_values(record), change['ordinate_delta'])]))
    delta = document['matrix_coefficient_delta']
    flat = [v for plane in delta for selector in plane for v in selector]
    coefficients = [v + d for v, d in zip(struct.unpack('<288h', baseline.matrices), flat)]
    if any(not -32768 <= v <= 32767 for v in coefficients):
        raise ValueError('Reconstructed native matrix coefficients overflow')
    flat = [v for plane in document['chroma_plane_delta'] for v in plane]
    chroma = encode_chroma([v + d for v, d in zip(expand_chroma(baseline.chroma), flat)], baseline.chroma)
    return PhotoBank(*curves, struct.pack('<288h', *coefficients), chroma)
