#!/usr/bin/env python3

import argparse
import os
from ai_observer.config import RuntimeConfig
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'characters'

parser = argparse.ArgumentParser()
parser.add_argument("character")
parser.add_argument("--full-lore", action="store_true")
parser.add_argument("--create", action="store_true")
args = parser.parse_args()

source = ROOT / "models" / args.character / "Modelfile"

if not source.is_file():
    parser.error(f"Character not found: {source}")

lore_files = [ROOT / "lore" / "core_canon.md"]

if args.full_lore:
    lore_files.append(ROOT / "lore" / "world_factions.md")

lore = "\n\n".join(
    path.read_text(encoding="utf-8")
    for path in lore_files
)

original = source.read_text(encoding="utf-8")

marker = 'SYSTEM """'

if original.count(marker) != 1 or original.count('"""') != 2:
    parser.error("Expected one triple-quoted SYSTEM block")

if '"""' in lore:
    parser.error("Unsupported triple quotes in lore")

generated = original.replace(
    marker,
    marker
    + "\n\n=== SHARED WORLD CANON ===\n"
    + lore
    + "\n\n=== CHARACTER PERSONALITY ===\n",
    1,
)

output_name = f"{args.character}-v11"

destination = (
    ROOT / "build" / "generated"
    / output_name / "Modelfile"
)

destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(generated, encoding="utf-8")

print(f"Generated: {destination}")
print(f"Model: {output_name}")

if args.create:
    subprocess.run(
        ["ollama", "create", output_name, "-f", str(destination)],
        check=True,
        env=dict(os.environ,OLLAMA_HOST=RuntimeConfig.load().ollama_url),
    )
