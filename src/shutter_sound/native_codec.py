"""Experimental 32-byte camera-sound block codec, offline only.

Observed native files use a control byte followed by 31 signed-byte residuals.
The low nibble behaves as an expansion exponent. Filter0 encoding deliberately
avoids the still-unconfirmed filter1 predictor. A software round trip is NOT
hardware codec proof; playback rate and hardware decoding remain experimental.
No Sony assets or user audio are included in this source file.
"""
import argparse
import array
import json
import math
from pathlib import Path
import sys
import wave


def decode(raw, *, predictor=60 / 64):
    if not raw or len(raw) % 32:
        raise ValueError('Native hypothesis needs complete 32-byte blocks')
    result, last = [], 0.0
    for offset in range(0, len(raw), 32):
        control = raw[offset]
        if control & ~0x1f or control & 15 > 8:
            raise ValueError('Control byte outside observed native range')
        scale = 1 << (control & 15)
        for byte in raw[offset + 1:offset + 32]:
            residual = byte if byte < 128 else byte - 256
            last = residual * scale + (predictor * last if control & 16 else 0)
            result.append(max(-32768, min(32767, round(last))))
    return result


def encode_filter0(samples):
    samples = list(samples)
    if not samples or any(not -32512 <= x <= 32512 for x in samples):
        raise ValueError('Use nonempty PCM with headroom within +/-32512')
    out = bytearray()
    for at in range(0, len(samples), 31):
        block = samples[at:at + 31]
        block += [0] * (31 - len(block))
        exponent = next(n for n in range(9)
                        if min(block) >= -128 * (1 << n) and max(block) <= 127 * (1 << n))
        step = 1 << exponent
        out.append(exponent)
        out.extend((max(-128, min(127, round(x / step))) & 255) for x in block)
    # Native resource sizes/offsets and our loader use 64-byte units. An extra
    # zero block is silence under filter0, not arbitrary padding as audio data.
    if len(out) % 64:
        out.extend(bytes(32))
    return bytes(out)


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        if (w.getnchannels(), w.getsampwidth(), w.getcomptype()) != (1, 2, 'NONE'):
            raise ValueError('Use an uncompressed mono PCM16 WAV')
        rate = w.getframerate()
        pcm = array.array('h', w.readframes(w.getnframes()))
        if sys.byteorder != 'little':
            pcm.byteswap()
    return list(pcm), rate


def write_wav(path, samples, rate):
    data = array.array('h', samples)
    if sys.byteorder != 'little':
        data.byteswap()
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def candidate(wav_path, *, target_rate=24000, peak=0.12):
    from scipy.signal import resample_poly
    import numpy as np
    source, source_rate = read_wav(wav_path)
    if target_rate <= 0 or not 0 < peak <= 32512 / 32767 or not source or not any(source):
        raise ValueError('Use a positive rate, non-silent audio and PCM headroom within +/-32512')
    divisor = math.gcd(source_rate, target_rate)
    converted = resample_poly(np.array(source, dtype=float), target_rate // divisor, source_rate // divisor)
    gain = 32767 * peak / float(np.max(np.abs(converted)))
    samples = [round(x * gain) for x in converted]
    raw = encode_filter0(samples)
    restored = decode(raw)[:len(samples)]
    error = np.array(restored, dtype=float) - samples
    noise = float(np.sum(error * error))
    signal = float(np.sum(np.array(samples, dtype=float) ** 2))
    report = {'schema': 'a7c2-filter0-native-hypothesis/1', 'camera_io': False,
              'source_rate_hz': source_rate, 'assumed_camera_rate_hz': target_rate,
              'camera_rate_verified': False, 'hardware_decoder_verified': False,
              'wire_format': 0, 'predictor_filter': 0,
              'source_samples_after_resampling': len(samples), 'encoded_bytes': len(raw),
              'block_bytes': 32, 'residuals_per_block': 31,
              'filter1_not_used': True, 'peak_fraction': max(map(abs, samples)) / 32767,
              'software_roundtrip_max_error': float(np.max(np.abs(error))),
              'software_roundtrip_snr_db': 10 * math.log10(signal / noise) if noise else None,
              'software_roundtrip_not_hardware_proof': True}
    if any(raw[at] & 16 for at in range(0, len(raw), 32)):
        raise ValueError('Unexpected predictor in filter0 candidate')
    return raw, restored, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    enc = sub.add_parser('encode')
    enc.add_argument('--wav', type=Path, required=True)
    enc.add_argument('--output', type=Path, required=True)
    enc.add_argument('--assumed-rate', type=int, default=24000)
    enc.add_argument('--peak', type=float, default=0.12,
                     help='Normalize selected audio to this PCM peak fraction, up to 0.5')
    dec = sub.add_parser('decode')
    dec.add_argument('--bin', type=Path, required=True)
    dec.add_argument('--wav', type=Path, required=True)
    dec.add_argument('--assumed-rate', type=int, default=24000)
    a = p.parse_args(argv)
    if a.command == 'decode':
        if a.wav.exists():
            raise ValueError('Choose a new preview WAV')
        write_wav(a.wav, decode(a.bin.read_bytes()), a.assumed_rate)
        print('Experimental decoded preview; no hardware codec/rate proof')
    else:
        raw, samples, report = candidate(a.wav, target_rate=a.assumed_rate, peak=a.peak)
        a.output.mkdir(parents=True, exist_ok=False)
        (a.output / 'custom-native.private.bin').write_bytes(raw)
        write_wav(a.output / 'software-decoded-preview.wav', samples, a.assumed_rate)
        (a.output / 'report.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
