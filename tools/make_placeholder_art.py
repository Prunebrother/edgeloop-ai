#!/usr/bin/env python3
"""AGPL-3.0-only. Make deterministic labelled development placeholders; requires existing Pillow."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

try:
    from story_art import ID, load_registry, validate
except ModuleNotFoundError:
    from tools.story_art import ID, load_registry, validate

ROOT = Path(__file__).resolve().parents[1]
# Neutral scene notes only; these are development labels, not narrative content.
SLOTS = {
    'h_arrival': ('illustration', 'Arrival at Helix Dynamics headquarters (draft scene note)'),
    'h_onboarding': ('illustration', 'Onboarding at the headquarters reception area'),
    'h_mira_eval': ('illustration', 'Evaluation in a clinical assessment room'),
    'h_vex_lab': ('illustration', 'Procedure in an industrial laboratory'),
    'h_breach': ('illustration', 'A security breach in the headquarters systems'),
    'h_detention': ('illustration', 'Detention in a secure holding room'),
    'h_release': ('illustration', 'Release through the headquarters exit'),
    'h_conclusion': ('illustration', 'Conclusion at the headquarters complex'),
    'env_exterior': ('environment', 'Exterior of Helix Dynamics headquarters'),
    'env_reception': ('environment', 'Corporate reception area'),
    'env_lab': ('environment', 'Clinical industrial laboratory'),
    'env_extraction': ('environment', 'Secure extraction room'),
    'env_datacenter': ('environment', 'Datacenter with server racks'),
    'env_interrogation': ('environment', 'Secure interrogation room'),
    'env_intern_desk': ('environment', 'Intern workstation in an office'),
    'env_exec_office': ('environment', 'Executive office at headquarters'),
    'key_art': ('key_art', 'Helix Dynamics headquarters complex'),
    'chapter_1_splash': ('chapter_splash', 'Entrance to Helix Dynamics headquarters'),
}


def generate(campaign, slots, root=ROOT):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise ValueError('Pillow is not installed in this environment; use an existing Pillow environment (no dependency added)')
    if not ID.fullmatch(campaign): raise ValueError('invalid campaign id')
    if not slots or any(not ID.fullmatch(slot) for slot in slots): raise ValueError('invalid slot id')
    folder = Path(root) / 'src/assets/story' / campaign
    if folder.absolute() != folder.resolve(): raise ValueError('symlink directory is not allowed')
    registry_path = folder / 'ASSETS.json'
    if registry_path.is_symlink(): raise ValueError('symlink registry is not allowed')
    registry = load_registry(registry_path) if registry_path.exists() else {'schema_version': 1, 'campaign': campaign, 'slots': {}}
    if registry_path.exists(): validate(registry, folder)
    jobs = []
    for slot in dict.fromkeys(slots):
        previous = registry['slots'].get(slot)
        if previous and previous['status'] != 'placeholder': raise ValueError(f'{slot}: refusing to replace reviewed art')
        kind, description = SLOTS.get(slot, ('illustration', slot.replace('_', ' ').capitalize()))
        if previous: kind, description = previous['kind'], previous['description']
        image = Image.new('RGB', (1536, 864), (24, 25, 28))
        draw = ImageDraw.Draw(image)
        # Pillow's bundled font lacks an em dash: draw that glyph as a line.
        font = ImageFont.load_default(size=48)
        label = 'PLACEHOLDER'; gap = 76
        width = draw.textlength(label, font=font)
        left = 768 - (width + gap + draw.textlength(slot, font=font)) / 2
        draw.text((left, 392), label, font=font, fill=(215, 215, 219), anchor='lm')
        draw.line((left + width + 16, 392, left + width + 60, 392), fill=(215, 215, 219), width=4)
        draw.text((left + width + gap, 392), slot, font=font, fill=(215, 215, 219), anchor='lm')
        draw.text((768, 470), description, font=ImageFont.load_default(size=24), fill=(160, 161, 168), anchor='mm')
        data = io.BytesIO(); image.save(data, format='WEBP', quality=85, method=6)
        content = data.getvalue()
        filename = previous['file'] if previous else f'{slot}.webp'
        if (folder / filename).is_symlink(): raise ValueError(f'{slot}: symlink file is not allowed')
        registry['slots'][slot] = {'kind': kind, 'file': filename, 'status': 'placeholder',
            'sha256': hashlib.sha256(content).hexdigest(), 'source': None, 'approved_by': None,
            'approved_at': None, 'explicit': False, 'description': description}
        jobs.append((filename, content))
    folder.mkdir(parents=True, exist_ok=True)
    for filename, content in jobs: (folder / filename).write_bytes(content)
    registry_path.write_text(json.dumps(registry, indent=2) + '\n', encoding='utf-8')
    return validate(registry, folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', required=True)
    parser.add_argument('--slots', required=True, help='comma-separated slot ids')
    args = parser.parse_args()
    try: generate(args.campaign, args.slots.split(','))
    except (OSError, ValueError) as exc: sys.exit(str(exc))


if __name__ == '__main__': main()
