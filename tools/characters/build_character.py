#!/usr/bin/env python3

import argparse
import os
from ai_observer.config import RuntimeConfig
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'characters'

def build(character, output_name, create):
    source = ROOT / "models" / character / "Modelfile"

    if not source.is_file():
        raise SystemExit(f"Character Modelfile not found: {source}")

    lore_files = [
        ROOT / "lore" / "edgeloop_universe.md",
        ROOT / "lore" / "world_factions.md",
    ]

    lore = "\n\n".join(
        path.read_text(encoding="utf-8")
        for path in lore_files
    )

    original = source.read_text(encoding="utf-8")

    delimiter = 'SYSTEM """'

    if original.count(delimiter) != 1:
        raise SystemExit(
            "Expected exactly one SYSTEM triple-quoted block"
        )

    # Prevent accidental corruption of Ollama's SYSTEM string.
    if '"""' in lore:
        raise SystemExit(
            "Shared lore contains an unsupported triple quote"
        )

    # Shared lore is inserted before character instructions.
    # The character-specific instructions remain intact.
    generated = original.replace(
        delimiter,
        delimiter
        + "\n\n"
        + "=== SHARED EDGELOOP UNIVERSE ===\n"
        + lore
        + "\n\n=== CHARACTER-SPECIFIC INSTRUCTIONS ===\n",
        1
    )

    destination = (
        ROOT / "build" / "generated" / character / "Modelfile"
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generated, encoding="utf-8")

    print(f"Generated: {destination}")
    print(f"Ollama model: {output_name}")

    if create:
        subprocess.run(
            [
                "ollama",
                "create",
                output_name,
                "-f",
                str(destination),
            ],
            check=True,
            env=dict(os.environ,OLLAMA_HOST=RuntimeConfig.load().ollama_url),
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("character")
    parser.add_argument("--name")
    parser.add_argument("--create", action="store_true")

    args = parser.parse_args()

    name = args.name or f"{args.character}-world"

    build(args.character, name, args.create)
