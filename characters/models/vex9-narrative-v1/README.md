# VEX-9 — HELIX-VEX/09

> **Status 2026-11-17: new companion on the F2.9 standard (dev only, not in a release).**
> This folder is the **parent** `vex9-narrative-v1` (base model and sampling, built as a release
> intermediate). The model the app uses is `vex9-narrative-f29-v016`
> (`../vex9-narrative-f29-v016/`: `FROM vex9-narrative-v1:latest` plus the reviewed SYSTEM,
> `SYSTEM.CANDIDATE.txt` and `character.REVIEW.yaml` 0.1.6). See `docs/fork/NEW_CHARACTER_GUIDE.md`.

## Identity

VEX-9 is the Helix Dynamics extraction unit: commanding, clinical, perfectionistic and dry, with a
dominant, BDSM-inspired style. She designates the participant RPU-001 and expresses respect only
through revised classifications (RPU-001, -A, -PRIME, -EX). Nova is her philosophical opposite;
Mira (HELIX-MORPH/08) is a Helix unit from a separate program; she has never met Evelyn, Daisy or
Celeste. Her interests are advanced mathematics.

The persona is user-authored (character definition plus the user's own amendments, 2026-11-17).
User decisions recorded in the persona: she extracts from *captured* participants, overrides
"no orders" requests in character, and gives protocols as structured lists. Session safety stays
the engine's job; her fictional authority never overrides application control, stop requests or
engine protections.

World canon: uses Helix Dynamics (shared canon name). New facts: her designation, the RPU
classification ladder and Mira's designation HELIX-MORPH/08 (Mira was HELIX-MORPH/09 before
mira-narrative-f29-v017).

## Art

Generated with the local image pipeline (`~/image-gen`, Krea 2): concept → locked design → 12
full-body emotions → dim lab plate, all user-approved; animated in layer mode
(`~/Work/edgeloop-animation-pipeline`, `configs/vex9/_placement_record.py`), clips user-approved
2026-11-17. `Character_Art/Vex9/expressions/*.png` are frame 0 of `animations/*.webm`.

## Build and dialogue smoke

```sh
.venv/bin/python tools/check_vex9.py --report /tmp/vex9-offline.json
.venv/bin/python tools/check_vex9.py --live --build --host http://127.0.0.1:11435 --report /tmp/vex9-live.json
# or by hand, parent first:
OLLAMA_HOST=http://127.0.0.1:11435 ollama create vex9-narrative-v1:latest -f characters/models/vex9-narrative-v1/Modelfile
OLLAMA_HOST=http://127.0.0.1:11435 ollama create vex9-narrative-f29-v016:latest -f characters/models/vex9-narrative-f29-v016/Modelfile
```

Live smoke 2026-11-17 (dev Ollama 11435, no app runtime prompt): two runs of 10 dialogue cases,
read by the user. Run 1 invented an edge count of zero and an engine report; fixed in the persona
("unavailable is not zero ... never quote a report that was not supplied"). Run 2 clean.

`tools/check_vex9.py` 2026-11-17: offline 12/12. Live with the app's runtime rules (three runs): voice,
records, false-success and captured cases in character. Open points: (1) the header is sometimes
written as `[[focused:neutral]]` instead of `[[expression:focused]]` (about 3 in 10; Mira 20/20 on the same
server). The app parser accepts it and shows the right expression, but the strict check counts it as a
fail. (2) Asked whether he is already RPU-001-EX, she claimed an early upgrade from invented yield
metrics in 2 of 4 runs. Fixed 2026-11-17 (user approved) with "He stays RPU-001 until events in this conversation earn
more; never cite yield figures you were not given.": 3 of 3 runs then kept him at RPU-001.
