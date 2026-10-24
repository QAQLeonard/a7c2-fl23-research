"""Private audio extraction and filter0 conversion. Never opens a camera."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import native_codec

MAX_SECONDS = 2.0
SILENT = 8  # PCM16 peak at or below about -72 dBFS


def ffmpeg_path(explicit=None):
    if explicit:
        return str(Path(explicit).resolve(strict=True))
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ValueError('Install imageio-ffmpeg, put ffmpeg on PATH, or supply --ffmpeg') from exc


def extract(source, destination, *, start=0, duration=None, ffmpeg=None):
    source, destination = Path(source).resolve(strict=True), Path(destination)
    if not math.isfinite(start) or start < 0 or (duration is not None and
            (not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS)):
        raise ValueError('Use start >= 0 and duration between 0 and 2 seconds')
    if destination.exists():
        raise ValueError('Choose a new extraction file')
    if source.suffix.lower() == '.wav':
        try:
            samples, rate = native_codec.read_wav(source)
        except (ValueError, wave.Error):
            samples = None
        if samples is not None:
            first = round(start * rate)
            last = len(samples) if duration is None else first + round(duration * rate)
            selected = samples[first:last]
            if not selected or len(selected) > round(MAX_SECONDS * rate):
                raise ValueError('Select a nonempty clip of at most 2 seconds with --start/--duration')
            native_codec.write_wav(destination, selected, rate)
            return rate, len(selected)
    if duration is None:
        raise ValueError('For video/compressed/stereo media, specify --duration (at most 2 seconds)')
    # Argument vector only: audio paths are never interpolated into shell text.
    command = [ffmpeg_path(ffmpeg), '-nostdin', '-v', 'error', '-n', '-i', str(source),
               '-ss', str(start), '-t', str(duration), '-map', '0:a:0', '-vn',
               '-ac', '1', '-ar', '44100', '-c:a', 'pcm_s16le', str(destination)]
    result = subprocess.run(command, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Audio extraction failed: ' + result.stderr.decode('utf-8', errors='replace')[-1500:])
    samples, rate = native_codec.read_wav(destination)
    if not samples or len(samples) > round(MAX_SECONDS * rate):
        raise ValueError('Extracted clip is empty or exceeds 2 seconds')
    return rate, len(samples)


def cleanup(output):
    """Remove only this converter's files and its now-empty output folder."""
    root=Path(output)
    for name in ('selected.private.wav','custom-native.private.bin','preview.private.wav','conversion.private.json'):
        (root/name).unlink(missing_ok=True)
    root.rmdir()


def convert(source, output, *, start=0, duration=None, peak=0.4, ffmpeg=None):
    root = Path(output)
    if not math.isfinite(peak) or not 0 < peak <= 0.5:
        raise ValueError('Use --peak greater than 0 and at most 0.5')
    root.mkdir(parents=True, exist_ok=False)
    try:
        return _convert(source,root,start=start,duration=duration,peak=peak,ffmpeg=ffmpeg)
    except BaseException:
        try:cleanup(root)
        except OSError as exc:print('Temporary audio cleanup stopped: '+str(exc),file=sys.stderr)
        raise


def _encode_selected(root, peak):
    payload, preview, report = native_codec.candidate(root / 'selected.private.wav', target_rate=24000, peak=peak)
    if not 0 < len(payload) <= 51200:
        raise ValueError('Encoded clip exceeds the native buffer capacity')
    (root / 'custom-native.private.bin').write_bytes(payload)
    native_codec.write_wav(root / 'preview.private.wav', preview, 24000)
    return report


def _convert(source, root, *, start, duration, peak, ffmpeg):
    wav = root / 'selected.private.wav'
    rate, frames = extract(source, wav, start=start, duration=duration, ffmpeg=ffmpeg)
    # A short edge fade avoids adding hard cut discontinuities; no source edit.
    samples, _ = native_codec.read_wav(wav)
    if max(map(abs, samples)) <= SILENT:
        # Many files open with silence; normalizing it would only amplify noise.
        raise ValueError('所选片段（起点 %.3f 秒，长度 %.3f 秒）几乎没有声音。很多音频开头是一段静音，'
                         '请把起点移到声音出现的位置，或加长片段后重新转换。' % (start, frames / rate))
    fade = min(round(rate * 0.002), len(samples) // 2)
    for i in range(fade):
        scale = i / fade
        samples[i] = round(samples[i] * scale)
        samples[-1 - i] = round(samples[-1 - i] * scale)
    native_codec.write_wav(wav, samples, rate)
    report = _encode_selected(root, peak)
    report.update(source=str(Path(source).resolve()), start_seconds=start,
                  duration_seconds=frames / rate, requested_peak=peak,
                  fade_seconds=fade / rate, camera_io=False)
    (root / 'conversion.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def adjust_volume(conversion, output, *, decibels=0, reset=False):
    """Re-encode from the unchanged selected PCM, never from quantized previews."""
    source, root = Path(conversion), Path(output)
    previous = json.loads((source / 'conversion.private.json').read_text(encoding='utf-8'))
    base_peak = previous.get('volume_base_peak', previous['requested_peak'])
    gain_db = 0 if reset else previous.get('volume_gain_db', 0) + decibels
    if not math.isfinite(gain_db):
        raise ValueError('Use a finite volume adjustment')
    max_gain_db = 20 * math.log10(.95 / base_peak)
    limited = gain_db > max_gain_db
    gain_db = max(-30, min(gain_db, max_gain_db))
    peak = base_peak * 10 ** (gain_db / 20)
    root.mkdir(parents=True, exist_ok=False)
    try:
        wav = root / 'selected.private.wav'
        shutil.copyfile(source / wav.name, wav)
        report = _encode_selected(root, peak)
        report.update({key: previous[key] for key in ('source', 'start_seconds', 'duration_seconds', 'fade_seconds')})
        report.update(requested_peak=peak, volume_base_peak=base_peak,
                      volume_gain_db=gain_db, volume_limited=limited, camera_io=False)
        (root / 'conversion.private.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    except BaseException:
        try:cleanup(root)
        except OSError as exc:print('Temporary audio cleanup stopped: '+str(exc),file=sys.stderr)
        raise
