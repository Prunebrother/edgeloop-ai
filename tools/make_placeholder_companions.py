#!/usr/bin/env python3
"""AGPL-3.0-only. Draw labelled dev silhouettes, without proposing character designs.

Use an existing Pillow environment (e.g. system Python); Pillow is not a runtime dependency.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Iris (2026-11-20) and Seraphine (2026-11-21) got author-approved art; no companion uses a silhouette now.
# Add an entry here for a future companion that needs a dev stand-in before her art exists.
NAMES = {}


def generate(root=ROOT):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print('Skipped: Pillow is unavailable; use an existing Pillow environment.')
        return []
    paths = []
    for cid, (folder, name) in NAMES.items():
        image = Image.new('RGB', (1024, 1536), (128, 128, 128))
        draw = ImageDraw.Draw(image)
        # The same featureless head and torso for both: no design, face, hair or clothes.
        shade = (52, 52, 58)
        draw.ellipse((392, 150, 632, 420), fill=shade)
        draw.rectangle((470, 375, 554, 500), fill=shade)
        draw.rounded_rectangle((300, 450, 724, 1200), radius=120, fill=shade)
        draw.polygon([(300, 990), (724, 990), (760, 1506), (264, 1506)], fill=shade)
        for y, text in [(650, 'PLACEHOLDER'), (730, name), (785, 'not final')]:
            draw.text((512, y), text, anchor='mm', font=ImageFont.load_default(size=26), fill=(235, 235, 235))
        path = Path(root) / f'Character_Art/{folder}/expressions/{cid}_placeholder.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format='PNG')
        paths.append(path)
    return paths


if __name__ == '__main__':
    for path in generate(): print(path)
