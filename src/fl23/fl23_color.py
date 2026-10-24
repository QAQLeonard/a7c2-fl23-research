#!/usr/bin/env python3
"""A7C II FL2／FL3 色彩記錄離線工具：以供體值重寫、核對與檢視色相。

不連相機、不產生安裝包，只讀寫本目錄下的 assets/。

576B 矩陣記錄是三個光源端點（B／A1／A2），每個端點 192B = 16 槽 × 12B
六係數。這 16 槽不是「色溫冗餘」：A7C II 原生外觀在同一端點內就有 15～16
個彼此不同的值，0x780F 也是按這 16 槽逐槽打包，因此它是逐色相分區的判讀
表。0.5.0 起 48 槽全部逐槽複製 FX2 1.01 供體值（assets/fx2_fl23_donor.json）。

歷史填充模式只保留來重現舊資產與回退比對，正式資產一律用 'perslot'：
  0.5.0 perslot   ：48 槽逐槽複製供體值（預設）
  0.4.0 endpoints ：B／A1／A2 各用自己的六係數，各鋪滿該端點 16 槽
  0.3.x unified   ：三個端點都寫 A1 的六係數，48 槽相同
  0.2.0 primary   ：只換三個端點的主槽，其餘 45 槽保留原值

使用方式：
  python fl23_color.py inspect             # 列出目前記錄與供體值的差異
  python fl23_color.py port [--write]      # 依供體值重寫 colors.json（先印出將變更的位元組數）
  python fl23_color.py verify              # 確認 colors.json 等於供體目標且清單雜湊自洽
  python fl23_color.py hue                 # 以 Lab／LCh 顯示矩陣對各色相的位移
  python fl23_color.py hue --per-slot      # 逐槽（色相分區）顯示位移，可看見 0.5.0 的差異
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

BASE = Path(__file__).resolve().parent
ASSETS = BASE / 'assets'
CHROMA_BYTES = 64
MATRIX_BYTES = 576
ENDPOINT_BYTES = 192
SLOT_BYTES = 12
SLOTS_PER_ENDPOINT = ENDPOINT_BYTES // SLOT_BYTES
ENDPOINT_NAMES = ('B', 'A1', 'A2')
ASSET_NAMES = ('colors.json', 'fx2_fl23_donor.json', 'installer.so', 'patches.json', 'probe.so',
               'r5_fl23_reference.json', 'runtime.so', 'wbi.so')
RELEASE = '0.6.0-preview'


def read_json(path):
  return json.loads(Path(path).read_text(encoding='utf-8'))


def save_json(path, data):
  Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(data):
  return hashlib.sha256(data).hexdigest()


def reference():
  return read_json(ASSETS / 'r5_fl23_reference.json')


def reference_by_parameter():
  return {row['target_parameter']: row for row in reference()['looks']}


def donor():
  """FX2 1.01 供體值：CC1 三組差分係數與 48 個逐槽矩陣。"""
  return read_json(ASSETS / 'fx2_fl23_donor.json')


def donor_by_parameter():
  return {row['target_parameter']: row for row in donor()['looks']}


def cc1_from_raw(groups):
  """R5 文件的 0x7842/0x7844/0x7845 八項 -> 機內三組差分係數。"""
  out = []
  for r in groups:
    if len(r) != 8:
      raise ValueError('RAW 色度每組應為八項')
    v = [r[1], r[2], r[3], r[0], r[5] // 2, r[6] // 2, r[7] // 2, r[4] // 2]
    if any(x % 2 for x in (r[5], r[6], r[7], r[4])):
      raise ValueError('RAW 色度反算出現非整數')
    out.append(v)
  return out


def cc1_to_raw(groups):
  """機內三組差分係數 -> RAW 八項，供回歸核對。"""
  out = []
  for v in groups:
    out.append([v[3], v[0], v[1], v[2], 2 * v[7], 2 * v[4], 2 * v[5], 2 * v[6]])
  return out


def matrix_from_ab(ab):
  a, b, c, d, e, f = ab
  return [[a + b + 1024, -a, -b],
          [-c, c + d + 1024, -d],
          [-e, -f, e + f + 1024]]


def ab_from_matrix(m):
  return [-m[0][1], -m[0][2], -m[1][0], -m[1][2], -m[2][0], -m[2][1]]


def endpoint_ab(look):
  """三個光源端點的六係數，順序 B／A1／A2。

  參考檔沒有 endpoint_matrix_ab 時（0.3.x 資產）退回「三端點共用 A1」。
  """
  data = look.get('endpoint_matrix_ab')
  if not data:
    return (tuple(look['matrix_ab']),) * len(ENDPOINT_NAMES)
  return tuple(tuple(data[name]) for name in ENDPOINT_NAMES)


def endpoints(matrix):
  if len(matrix) != MATRIX_BYTES:
    raise ValueError('矩陣記錄長度不符')
  return [matrix[i * ENDPOINT_BYTES:(i + 1) * ENDPOINT_BYTES] for i in range(3)]


def slot0(endpoint):
  return struct.unpack_from('<6h', endpoint, 0)


def describe(matrix):
  """回傳每個端點主槽的 (a..f) 與展開後 3x3。"""
  out = []
  for name, endpoint in zip(ENDPOINT_NAMES, endpoints(matrix)):
    ab = list(slot0(endpoint))
    out.append({'endpoint': name, 'ab': ab, 'matrix': matrix_from_ab(ab)})
  return out


def uniform_primary(matrix):
  """三個光源端點的主槽是否相同（0.2.0／0.3.x 的規則，保留給舊資產檢查）。"""
  blocks = [e[:SLOT_BYTES] for e in endpoints(matrix)]
  return blocks[0] == blocks[1] == blocks[2]


def slot_values(matrix):
  """展開 48 個 12B 槽為 (端點, 槽, 六係數) 清單。"""
  out = []
  for index, block in enumerate(endpoints(matrix)):
    for slot in range(SLOTS_PER_ENDPOINT):
      out.append((index, slot, struct.unpack_from('<6h', block, slot * SLOT_BYTES)))
  return out


def uniform_endpoint(block):
  """單一端點的 16 槽是否全部相同。"""
  if len(block) != ENDPOINT_BYTES:
    raise ValueError('端點長度不符')
  head = block[:SLOT_BYTES]
  return all(block[i:i + SLOT_BYTES] == head for i in range(0, ENDPOINT_BYTES, SLOT_BYTES))


def uniform_all_slots(matrix):
  """48 個槽是否全部相同（0.3.x 的規則，保留給舊資產檢查）。"""
  values = [v for _, _, v in slot_values(matrix)]
  return len(values) == 3 * SLOTS_PER_ENDPOINT and all(v == values[0] for v in values)


def counts_toward_donor(matrix, parameter):
  """回傳與供體逐槽目標相符的槽數，以及未符的 (端點, 槽)。"""
  want = donor_matrix(parameter)
  slots = [matrix[i:i + SLOT_BYTES] for i in range(0, MATRIX_BYTES, SLOT_BYTES)]
  matched, missing = 0, []
  for index, value in enumerate(slots):
    if value == want[index * SLOT_BYTES:(index + 1) * SLOT_BYTES]:
      matched += 1
    else:
      missing.append(f'{ENDPOINT_NAMES[index // SLOTS_PER_ENDPOINT]}:{index % SLOTS_PER_ENDPOINT}')
  return matched, missing


def distinct_slots(matrix):
  """每個端點內 16 槽的不同值數量（原生外觀通常是 15～16）。"""
  return [len({block[i:i + SLOT_BYTES] for i in range(0, ENDPOINT_BYTES, SLOT_BYTES)})
          for block in endpoints(matrix)]


def target_chroma(look):
  values = [x for group in look['cc1_int16'] for x in group]
  if len(values) != 24:
    raise ValueError('色度應為三組共 24 項')
  return struct.pack('<24h', *values) + bytes(CHROMA_BYTES - 48)


def donor_matrix(parameter):
  """供體的 576B 矩陣：B／A1／A2 各 16 槽，逐槽複製。"""
  look = donor_by_parameter()[parameter]
  return b''.join(struct.pack('<6h', *ab)
                  for name in ENDPOINT_NAMES for ab in look['matrix_slots'][name])


def donor_chroma(parameter):
  look = donor_by_parameter()[parameter]
  return struct.pack('<24h', *[x for group in look['cc1_int16'] for x in group]) + bytes(16)


def target_matrix(look, current, fill='perslot'):
  """把目標矩陣寫進 576B 記錄。

  fill='perslot'（0.5.0 預設）：48 槽逐槽複製 FX2 供體值。
  fill='endpoints'（0.4.0）：B／A1／A2 各用自己的六係數，各自鋪滿 16 槽。
  fill='unified'（0.3.x）：三個端點都寫 A1 的六係數，共 48 槽相同。
  fill='primary'（0.2.0）：只換三個端點的主槽，其餘 45 槽保留原值。
  後三者只為重現舊資產與回退比對，正式資產一律用 'perslot'。
  """
  if fill == 'perslot':
    return donor_matrix(look['target_parameter'])
  if fill == 'endpoints':
    return b''.join(struct.pack('<6h', *ab) * SLOTS_PER_ENDPOINT for ab in endpoint_ab(look))
  primary = struct.pack('<6h', *look['matrix_ab'])
  if fill == 'unified':
    return primary * (3 * SLOTS_PER_ENDPOINT)
  if fill == 'primary':
    rebuilt = [primary + block[SLOT_BYTES:] for block in endpoints(current)]
    return b''.join(rebuilt)
  raise ValueError(f'未知填充模式：{fill}')


def row_for(parameter):
  for row in read_json(ASSETS / 'colors.json'):
    if row['parameter'] == parameter:
      return row
  raise KeyError(f'colors.json 缺少參數 {parameter}')


# ---------------------------------------------------------------- 色相試算
# 這裡只做「矩陣作用在線性 sRGB 上」的代數近似：不含去馬賽克、白平衡、
# Gamma 與色度階段的實際處理，不代表機內最終像素，只用來比較端點之間的
# 相對差異與方向。

def _apply(m, v):
  return tuple(sum(m[i][j] * v[j] for j in range(3)) / 1024.0 for i in range(3))


def _deg_to_linear(c):
  return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_deg(c):
  c = max(0.0, min(1.0, c))
  return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def linear_to_lab(rgb):
  r, g, b = [_deg_to_linear(max(0.0, min(1.0, x))) for x in rgb]
  x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
  y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
  z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

  def f(t):
    return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

  fx, fy, fz = f(x / 0.95047), f(y), f(z / 1.08883)
  return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_to_linear(L, a, b):
  fy = (L + 16) / 116
  fx = a / 500 + fy
  fz = fy - b / 200

  def g(t):
    return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

  x, y, z = g(fx) * 0.95047, g(fy), g(fz) * 1.08883
  return (x * 3.2404542 - y * 1.5371385 - z * 0.4985314,
          -x * 0.9692660 + y * 1.8760108 + z * 0.0415560,
          x * 0.0556434 - y * 0.2040259 + z * 1.0572252)


def lch(rgb):
  L, a, b = linear_to_lab(rgb)
  return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def hue_shift(ab, hue, L=55, C=45):
  """給定 Lab 色相角取樣點，回傳矩陣造成的色相位移與彩度變化（度／ΔC）。"""
  a = C * math.cos(math.radians(hue))
  b = C * math.sin(math.radians(hue))
  lin = tuple(_deg_to_linear(_linear_to_deg(c)) for c in lab_to_linear(L, a, b))
  _, c0, h0 = lch(lin)
  _, c1, h1 = lch(_apply(matrix_from_ab(ab), lin))
  return (h1 - h0 + 180) % 360 - 180, c1 - c0


def hue_report(parameters=None, hues=range(0, 360, 15), L=55, C=45):
  ref = reference_by_parameter()
  rows = []
  for parameter in sorted(ref):
    if parameters and parameter not in parameters:
      continue
    look = ref[parameter]
    entries = []
    for name, ab in zip(ENDPOINT_NAMES, endpoint_ab(look)):
      samples = []
      for hue in hues:
        dh, dc = hue_shift(ab, hue, L, C)
        samples.append({'in_hue': hue, 'dh': round(dh, 2), 'dC': round(dc, 2)})
      entries.append({'endpoint': name, 'ab': list(ab), 'samples': samples})
    rows.append({'look': look['look'], 'parameter': parameter, 'endpoints': entries})
  return {'model': 'linear sRGB + CIE Lab D65; matrix only, no gamma/chroma stage',
          'L': L, 'C': C, 'looks': rows}


def print_hue(report):
  print('模型：' + report['model'])
  print(f'取樣：L*={report["L"]} C*={report["C"]}，每 15 度一格；Δh 正值＝往高色相角（綠→青）')
  for look in report['looks']:
    print(f"\n{look['look']}（參數 {look['parameter']}）")
    print('  輸入 h' + ''.join(f" | {e['endpoint']:>13}" for e in look['endpoints']))
    for i, sample in enumerate(look['endpoints'][0]['samples']):
      line = f"  {sample['in_hue']:6d}"
      for entry in look['endpoints']:
        item = entry['samples'][i]
        line += f" | {item['dh']:+6.2f}/{item['dC']:+6.2f}"
      print(line)
    for entry in look['endpoints']:
      print(f"  端點 {entry['endpoint']:<2} 六係數 = " + ' '.join(f'{x:>5d}' for x in entry['ab']))


def slot_hue_report(parameters=None, hues=range(0, 360, 15), L=55, C=45):
  """A1 端點 16 個色相分區各自的位移，以及與「16 槽同值」的差。

  0.4.x 把每個端點的 16 槽填成同一組係數，等於把所有色相分區都用槽 0 的
  判讀。這裡同時列出槽 0 的值，就能看出每個分區被壓平了多少。
  """
  rows = []
  for parameter in sorted(donor_by_parameter()):
    if parameters and parameter not in parameters:
      continue
    look = donor_by_parameter()[parameter]
    reference_ab = tuple(look['matrix_slots']['A1'][0])
    entries = []
    for slot, ab in enumerate(look['matrix_slots']['A1']):
      samples = []
      for hue in hues:
        dh, dc = hue_shift(ab, hue, L, C)
        dh0, dc0 = hue_shift(reference_ab, hue, L, C)
        samples.append({'in_hue': hue, 'dh': round(dh, 2), 'dC': round(dc, 2),
                        'dh_vs_slot0': round(dh - dh0, 2), 'dC_vs_slot0': round(dc - dc0, 2)})
      entries.append({'slot': slot, 'ab': list(ab), 'samples': samples})
    rows.append({'look': look['look'], 'parameter': parameter, 'slots': entries})
  return {'model': 'linear sRGB + CIE Lab D65; matrix only, no gamma/chroma stage',
          'L': L, 'C': C, 'looks': rows}


def print_slot_hue(report):
  print('模型：' + report['model'])
  print(f"取樣：L*={report['L']} C*={report['C']}；A1 端點 16 個色相分區")
  print('Δh 正值＝往高色相角（綠→青）；「對槽0」＝與 0.4.x 全槽同值做法的差')
  for look in report['looks']:
    print(f"\n{look['look']}（參數 {look['parameter']}）")
    print('  槽  ' + ''.join(f" | h{s['in_hue']:>4}" for s in look['slots'][0]['samples']))
    for entry in look['slots']:
      line = f"  {entry['slot']:>2}  "
      for sample in entry['samples']:
        line += f" | {sample['dh']:+6.2f}"
      print(line)
    print('  與槽 0 的差（0.4.x 全槽同值時會失去的量）：')
    print('  槽  ' + ''.join(f" | h{s['in_hue']:>4}" for s in look['slots'][0]['samples']))
    for entry in look['slots']:
      line = f"  {entry['slot']:>2}  "
      for sample in entry['samples']:
        line += f" | {sample['dh_vs_slot0']:+6.2f}"
      print(line)


def inspect():
  ref = reference_by_parameter()
  report = []
  for parameter, look in sorted(ref.items()):
    row = row_for(parameter)
    chroma = bytes.fromhex(row['chroma'])
    matrix = bytes.fromhex(row['matrix'])
    current_cc1 = struct.unpack('<32h', chroma)
    want_chroma = target_chroma(look)
    want_matrix = target_matrix(look, matrix)
    entries = describe(matrix)
    matched, missing = counts_toward_donor(matrix, parameter)
    report.append({
        'look': look['look'],
        'parameter': parameter,
        'slot': row['slot'],
        'endpoints': entries,
        'distinct_slots_per_endpoint': distinct_slots(matrix),
        'reference_endpoints': [{'endpoint': name, 'ab': list(ab),
                                 'matrix': matrix_from_ab(ab)}
                                for name, ab in zip(ENDPOINT_NAMES, endpoint_ab(look))],
        'endpoint_uniform': [uniform_endpoint(block) for block in endpoints(matrix)],
        'primary_uniform': uniform_primary(matrix),
        'all_slots_uniform': uniform_all_slots(matrix),
        'slots_matching_reference': matched,
        'slots_missing_reference': missing,
        'primary_matches_r5': all(e['ab'] == look['matrix_ab'] for e in entries),
        'chroma_matches_r5': chroma[:48] == want_chroma[:48],
        'chroma_diff_int16': [i for i in range(24)
                              if struct.unpack('<32h', want_chroma)[i] != current_cc1[i]],
        'chroma_tail_zero': not any(current_cc1[24:]),
        'matrix_changed_bytes': sum(a != b for a, b in zip(matrix, want_matrix)),
        'chroma_changed_bytes': sum(a != b for a, b in zip(chroma, want_chroma)),
    })
  return {'reference': reference()['reference'], 'records': report}


def port(write=False, fill='perslot'):
  ref = reference_by_parameter()
  changed = []
  rows = read_json(ASSETS / 'colors.json')
  total = 0
  for row in rows:
    look = ref.get(row['parameter'])
    if look is None:
      continue
    chroma = bytes.fromhex(row['chroma'])
    matrix = bytes.fromhex(row['matrix'])
    new_chroma = donor_chroma(row['parameter'])
    new_matrix = target_matrix(look, matrix, fill)
    delta = sum(a != b for a, b in zip(chroma, new_chroma))
    delta += sum(a != b for a, b in zip(matrix, new_matrix))
    total += delta
    changed.append({'look': look['look'], 'parameter': row['parameter'],
                    'slot': row['slot'], 'changed_bytes': delta,
                    'chroma_sha256_before': sha(chroma), 'chroma_sha256_after': sha(new_chroma),
                    'matrix_sha256_before': sha(matrix), 'matrix_sha256_after': sha(new_matrix)})
    if write:
      row['chroma'] = new_chroma.hex()
      row['matrix'] = new_matrix.hex()
  scope = {'perslot': '48 槽逐槽複製 FX2 供體值',
           'endpoints': '3 端點 × 16 槽（各寫自己的六係數）',
           'unified': '48 槽全部寫 A1 六係數',
           'primary': '3 端點主槽'}[fill]
  print(f'將變更 {total} 個位元組（chroma + {scope}）')
  for item in changed:
    print(f"  {item['look']} 參數{item['parameter']} 槽{item['slot']}：{item['changed_bytes']} 位元組")
    print(f"    chroma {item['chroma_sha256_before'][:16]} -> {item['chroma_sha256_after'][:16]}")
    print(f"    matrix {item['matrix_sha256_before'][:16]} -> {item['matrix_sha256_after'][:16]}")
  if not write:
    print('未寫入；加上 --write 才會更新 assets/colors.json 與清單雜湊')
    return changed
  save_json(ASSETS / 'colors.json', rows)
  manifest = read_json(ASSETS / 'manifest.json')
  manifest['release'] = RELEASE
  manifest['colour_donor'] = ('ILCE-FX2 1.01 CP image and colour units; cross-checked against the '
                              'A7R V 4.04 published values in r5_fl23_reference.json')
  manifest['colour_fill'] = ('all 48 block13 slots per look (3 light-source endpoints x 16 hue '
                             'sectors) copied slot by slot from the donor bank')
  manifest['files'] = {name: sha((ASSETS / name).read_bytes()) for name in ASSET_NAMES}
  save_json(ASSETS / 'manifest.json', manifest)
  print('已更新 assets/colors.json 與 assets/manifest.json')
  return changed


def verify():
  ref = reference_by_parameter()
  problems = []
  asset_report = read_json(ASSETS / 'r5_fl23_reference.json')
  for look in asset_report['looks']:
    raw = [look['raw']['0x7842'], look['raw']['0x7844'], look['raw']['0x7845']]
    if cc1_from_raw(raw) != look['cc1_int16']:
      problems.append(f"{look['look']}：cc1_int16 與 RAW 反算不符")
    if cc1_to_raw(look['cc1_int16']) != raw:
      problems.append(f"{look['look']}：RAW 正算與 cc1_int16 不符")
    if matrix_from_ab(look['matrix_ab']) != look['matrix_3x3']:
      problems.append(f"{look['look']}：matrix_3x3 與六項展開不符")
    if ab_from_matrix(look['matrix_3x3']) != look['matrix_ab']:
      problems.append(f"{look['look']}：六項反算與 matrix_3x3 不符")
    for name, matrix in (look.get('endpoint_matrix_3x3') or {}).items():
      ab = look['endpoint_matrix_ab'][name]
      if matrix_from_ab(ab) != matrix:
        problems.append(f"{look['look']}：端點 {name} 六項展開與 3x3 不符")
      if any(sum(row) != 1024 for row in matrix):
        problems.append(f"{look['look']}：端點 {name} 行和不是 1024")
    if (look.get('endpoint_matrix_3x3') or {}).get('A1') != look['matrix_3x3']:
      problems.append(f"{look['look']}：A1 端點與 R5 公布主矩陣不一致")
  for parameter, look in sorted(ref.items()):
    row = row_for(parameter)
    chroma = bytes.fromhex(row['chroma'])
    matrix = bytes.fromhex(row['matrix'])
    if len(chroma) != CHROMA_BYTES or len(matrix) != MATRIX_BYTES:
      problems.append(f"{look['look']}：記錄長度不符")
      continue
    if chroma != donor_chroma(parameter):
      problems.append(f"{look['look']}：色度不等於供體目標值")
    if chroma != target_chroma(look):
      problems.append(f"{look['look']}：色度與 R5 公布值不一致（兩份來源應相同）")
    if matrix != target_matrix(look, matrix):
      problems.append(f"{look['look']}：矩陣未等於供體逐槽目標")
    matched, missing = counts_toward_donor(matrix, parameter)
    if matched != 3 * SLOTS_PER_ENDPOINT:
      problems.append(f"{look['look']}：僅 {matched}/48 槽等於供體值，缺 "
                      f"{','.join(missing[:6])}{'…' if len(missing) > 6 else ''}")
    for index in range(0, MATRIX_BYTES, SLOT_BYTES):
      ab = struct.unpack('<6h', matrix[index:index + SLOT_BYTES])
      if any(sum(row) != 1024 for row in matrix_from_ab(ab)):
        problems.append(f"{look['look']}：第 {index // SLOT_BYTES} 槽展開行和不是 1024")
    # A1 端點槽 0 必須等於 R5 公布的矩陣：兩份獨立來源互相印證端點順序。
    a1 = slot0(endpoints(matrix)[1])
    if list(a1) != look['matrix_ab']:
      problems.append(f"{look['look']}：A1 端點槽 0 不等於 R5 公布六係數")
    for block, name in zip(endpoints(matrix), ENDPOINT_NAMES):
      if slot0(block) != tuple(look['endpoint_matrix_ab'][name]):
        problems.append(f"{look['look']}：端點 {name} 主槽不等於 R5 公布值")
  manifest = read_json(ASSETS / 'manifest.json')
  if set(manifest['files']) != set(ASSET_NAMES):
    problems.append('清單檔案集合與預期資產不符')
  for name, expected in manifest['files'].items():
    if sha((ASSETS / name).read_bytes()) != expected:
      problems.append(f'清單雜湊不符：{name}')
  if problems:
    print('核對失敗：')
    for item in problems:
      print('  - ' + item)
    return False
  print('核對通過：48/48 槽逐槽等於 FX2 供體值、色度一致、每行和 1024、清單雜湊自洽')
  return True


def main():
  parser = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = parser.add_subparsers(dest='command', required=True)
  sub.add_parser('inspect', help='列出目前記錄與參考值的差異')
  port_parser = sub.add_parser('port', help='依參考值重寫 colors.json')
  port_parser.add_argument('--write', action='store_true', help='實際寫入；否則只列出將變更的位元組數')
  port_parser.add_argument('--fill', choices=('perslot', 'endpoints', 'unified', 'primary'),
                           default='perslot',
                           help='perslot：48 槽逐槽複製供體值（0.5.0 預設）；'
                                'endpoints：三端點各寫自己的係數（0.4.0）；'
                                'unified：三端點共用 A1（0.3.x）；primary：只填端點主槽（0.2.0）')
  sub.add_parser('verify', help='確認資產等於供體目標且清單自洽')
  hue_parser = sub.add_parser('hue', help='以 Lab／LCh 顯示矩陣造成的色相位移')
  hue_parser.add_argument('--parameter', type=int, action='append',
                          help='只顯示指定參數（可重複；預設兩個外觀都列）')
  hue_parser.add_argument('--degree', type=int, default=15, help='取樣間隔（預設 15 度）')
  hue_parser.add_argument('--per-slot', action='store_true',
                          help='逐槽（色相分區）顯示 A1 端點 16 槽的位移')
  hue_parser.add_argument('--json', action='store_true', help='輸出 JSON 而不是表格')
  args = parser.parse_args()
  if args.command == 'inspect':
    data = inspect()
    print('參考：' + data['reference']['document'])
    print('機身：' + data['reference']['body'] + ' ' + data['reference']['firmware'])
    for row in data['records']:
      print(f"\n{row['look']}（參數 {row['parameter']}，槽 {row['slot']}）")
      for entry, want in zip(row['endpoints'], row['reference_endpoints']):
        flat = ' '.join(f'{x:>5d}' for x in entry['ab'])
        mark = '' if entry['ab'] == want['ab'] else '  ← 與參考值不同'
        print(f"  端點 {entry['endpoint']:<2} 主槽 a..f ={flat}{mark}")
        for line in entry['matrix']:
          print('       ' + ' '.join(f'{x:>6d}' for x in line))
      print(f"  每個端點 16 槽統一：{'是' if all(row['endpoint_uniform']) else '否'}；"
            f"三端點相同：{'是' if row['primary_uniform'] else '否'}；"
            f"等於供體值的槽：{row['slots_matching_reference']}/48；"
            f"各端點不同槽值數：{row['distinct_slots_per_endpoint']}")
      if row['slots_missing_reference']:
        sample = ','.join(row['slots_missing_reference'][:8])
        print(f"  仍非參考值的槽（前 8 個）：{sample}"
              f"{'…' if len(row['slots_missing_reference']) > 8 else ''}")
      print(f"  色度等於參考值：{'是' if row['chroma_matches_r5'] else '否'}；"
            f"差異項 {len(row['chroma_diff_int16'])}/24；尾八項為零：{'是' if row['chroma_tail_zero'] else '否'}")
      print(f"  與參考目標相差：色度 {row['chroma_changed_bytes']} 位元組、"
            f"矩陣 {row['matrix_changed_bytes']} 位元組")
    return 0
  if args.command == 'port':
    port(args.write, args.fill)
    return 0
  if args.command == 'hue':
    if args.per_slot:
      report = slot_hue_report(args.parameter, range(0, 360, max(1, args.degree)))
      if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
      else:
        print_slot_hue(report)
      return 0
    report = hue_report(args.parameter, range(0, 360, max(1, args.degree)))
    if args.json:
      print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
      print_hue(report)
    return 0
  return 0 if verify() else 1


if __name__ == '__main__':
  raise SystemExit(main())
