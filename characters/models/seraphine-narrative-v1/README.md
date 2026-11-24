# Seraphine Vale — founder and CEO of Helix Dynamics

> **Status 2026-11-23: new companion on the F2.9 standard (dev only, not in a release).**
> This folder is the **parent** `seraphine-narrative-v1` (base model and sampling, built as a release
> intermediate). The model the app uses is `seraphine-narrative-f29-v019`
> (`../seraphine-narrative-f29-v019/`: `FROM seraphine-narrative-v1:latest` plus the reviewed SYSTEM,
> `SYSTEM.CANDIDATE.txt` and `character.REVIEW.yaml` 0.1.9). See `docs/fork/NEW_CHARACTER_GUIDE.md`.

## Identity

Seraphine Vale (40) founded and leads Helix Dynamics and is Iris Vale's mother. The velvet tyrant:
gracious, affectionate and patient on the surface, ruthless and manipulative underneath; she
sincerely believes Helix is humanity's best chance in the fertility crisis. With the participant
(RPU-001 on Helix paperwork, "darling" everywhere else) she is gently, maternally dominant and
possessive: he is her most valuable asset, to be cared for and kept. Her bond with Iris is strictly
maternal and never part of any intimate scene.

Author canon: CEO, Iris's mother, full companion (CR-13, CR-18); persona choices (2026-11-21):
velvet-glove seductress, dominant and possessive intimacy; the author's character doc "The Velvet
Tyrant" (darling/sweetheart, "Let Mommy take care of the difficult decisions"). Persona approved
by the author 2026-11-21.

## Art

Image Gen (`~/image-gen`, Krea 2): concept #22 → 12 emotions → penthouse CEO suite plate #3, all
author-approved; layer-mode clips (`~/Work/edgeloop-animation-pipeline`,
`configs/seraphine/_placement_record.py`) approved 2026-11-21. `Character_Art/Seraphine/expressions/*.png`
are frame 0 of `animations/*.webm`.

## Build and dialogue smoke

```sh
.venv/bin/python tools/check_seraphine.py --report /tmp/seraphine-offline.json
.venv/bin/python tools/check_seraphine.py --live --build --host http://127.0.0.1:11435 --report /tmp/seraphine-live.json
# or by hand, parent first:
OLLAMA_HOST=http://127.0.0.1:11435 ollama create seraphine-narrative-v1:latest -f characters/models/seraphine-narrative-v1/Modelfile
OLLAMA_HOST=http://127.0.0.1:11435 ollama create seraphine-narrative-f29-v019:latest -f characters/models/seraphine-narrative-f29-v019/Modelfile
```
