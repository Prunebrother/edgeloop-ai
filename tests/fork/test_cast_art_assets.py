# SPDX-License-Identifier: AGPL-3.0-only
"""Whole-cast frame-zero contract. Decode one frame only; never re-encode source art.

Run directly to also write the per-expression measurements as JSON for author review.
Only ffmpeg/ffprobe and the Python standard library are needed.
"""
import json
from pathlib import Path
import shutil
import struct
import subprocess
from fractions import Fraction

import pytest

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
MEAN_TOLERANCE = 3.0  # RGB levels out of 255; lossless PNG versus lossy VP9.


def png_size(path):
    with path.open('rb') as source:
        header = source.read(24)
    assert header[:8] == b'\x89PNG\r\n\x1a\n', str(path)
    return struct.unpack('>II', header[16:24])


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


def frame_zero(path):
    return run('ffmpeg', '-v', 'error', '-threads', '1', '-i', str(path),
               '-frames:v', '1', '-threads', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1')


def inspect(character, expression):
    definition = CATALOG['characters'][character]
    png = ROOT / definition['expressions'][expression].lstrip('/')
    result = {'character': character, 'expression': expression, 'png': str(png.relative_to(ROOT)),
              'png_size': png_size(png)}
    formats = definition.get('animations', {}).get(expression)
    if not formats:
        result['skip'] = 'No clip declared in the manifest (static-only companion).'
        return result
    clip = ROOT / formats['webm'].lstrip('/')
    assert clip.is_file(), str(clip)
    result['clip'] = str(clip.relative_to(ROOT))
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        result['skip'] = 'ffmpeg and ffprobe are required for metadata and frame-zero comparison.'
        return result
    # For these VP9 WebMs each packet is one coded frame. Count packets without
    # decoding the other 239 frames, and cross-check count against fps and duration.
    probe = json.loads(run('ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0',
                          '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,nb_read_packets:format=duration',
                          '-of', 'json', str(clip)))
    stream = probe['streams'][0]
    result.update(clip_size=(stream['width'], stream['height']), codec=stream['codec_name'],
                  fps=float(Fraction(stream['avg_frame_rate'])), frames=int(stream['nb_read_packets']),
                  duration=float(probe['format']['duration']))
    if result['png_size'] == result['clip_size']:
        still, decoded = frame_zero(png), frame_zero(clip)
        assert len(still) == len(decoded) == result['png_size'][0] * result['png_size'][1] * 3
        result['frame_zero_mean_difference'] = sum(abs(a - b) for a, b in zip(still, decoded)) / len(still)
    return result


def violations(result):
    character = result['character']
    errors = []
    expected = png_size(ROOT / CATALOG['characters'][character]['expressions']['neutral'].lstrip('/'))
    if tuple(result['png_size']) != expected:
        errors.append(f"PNG size {result['png_size']} differs from companion neutral {expected}")
    if result.get('skip'):
        return errors
    if tuple(result['png_size']) != tuple(result['clip_size']):
        errors.append(f"PNG {result['png_size']} / WebM {result['clip_size']} size mismatch")
    if result['codec'] != 'vp9' or result['frames'] != 240 or result['fps'] != 30 or abs(result['duration'] - 8) > .05:
        errors.append(f"Expected VP9, 240 frames, 30 fps, 8 s: {result}")
    mean = result.get('frame_zero_mean_difference')
    if mean is not None and mean > MEAN_TOLERANCE:
        errors.append(f'Frame-zero RGB mean difference {mean:.4f} exceeds {MEAN_TOLERANCE}')
    return errors


CASES = [(character, expression) for character, definition in CATALOG['characters'].items()
         for expression in definition['expressions']]


@pytest.mark.parametrize('character,expression', CASES, ids=['/'.join(case) for case in CASES])
def test_cast_art_frame_zero_contract(character, expression):
    result = inspect(character, expression)
    errors = violations(result)
    assert not errors, '\n'.join(errors)
    if result.get('skip'):
        pytest.skip(result['skip'])


if __name__ == '__main__':
    import sys
    results = []
    for character, expression in CASES:
        result = inspect(character, expression)
        result['violations'] = violations(result)
        results.append(result)
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/edgeloop-cast-art-browser/asset-report.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(results, indent=2) + '\n')
    print(f'{len(results)} expression checks written to {destination}')
    for result in results:
        if result['violations']:
            print(result['character'], result['expression'], '; '.join(result['violations']))
