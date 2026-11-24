# Iris Vale — Helix research intern

> **Status 2026-11-20: new companion on the F2.9 standard (dev only, not in a release).**
> This folder is the **parent** `iris-narrative-v1` (base model and sampling, built as a release
> intermediate). The model the app uses is `iris-narrative-f29-v018`
> (`../iris-narrative-f29-v018/`: `FROM iris-narrative-v1:latest` plus the reviewed SYSTEM,
> `SYSTEM.CANDIDATE.txt` and `character.REVIEW.yaml` 0.1.8). See `docs/fork/NEW_CHARACTER_GUIDE.md`.

## Identity

Iris Vale (25) is a shy, exceptionally intelligent research intern at Helix Dynamics and the
daughter of CEO Seraphine Vale. She is loyal to Helix and her mother at the start, but unsettled
by what she is not told; doubt grows only through events. She has a slow-burn crush on the
participant that she hides badly behind procedure. In sessions she is shy but explicit and
nervously curious: she has read every study and wants to see it for herself.

Author canon: name, role and mother (2026-11-19); persona choices (2026-11-20): shy genius who
warms up, loyal but doubting, slow-burn crush, shy but explicit, "a bit more explicit with a
nervous curious streak". Claude's additions, accepted with the persona: houseplants and classic
science fiction as interests.

World canon: Helix Dynamics led by Seraphine Vale (new fact). RPU-001 follows VEX-9's canon
(Reproductive Production Unit); Iris knows exactly what it stands for and hates it (author decision 2026-11-20).

## Art

Image Gen (`~/image-gen`, Krea 2): concept #12 → 12 emotions → dark Helix office plate #3, all
author-approved; layer-mode clips (`~/Work/edgeloop-animation-pipeline`,
`configs/iris/_placement_record.py`) approved 2026-11-20. `Character_Art/Iris/expressions/*.png`
are frame 0 of `animations/*.webm`.

## Build and dialogue smoke

```sh
.venv/bin/python tools/check_iris.py --report /tmp/iris-offline.json
.venv/bin/python tools/check_iris.py --live --build --host http://127.0.0.1:11435 --report /tmp/iris-live.json
# or by hand, parent first:
OLLAMA_HOST=http://127.0.0.1:11435 ollama create iris-narrative-v1:latest -f characters/models/iris-narrative-v1/Modelfile
OLLAMA_HOST=http://127.0.0.1:11435 ollama create iris-narrative-f29-v018:latest -f characters/models/iris-narrative-f29-v018/Modelfile
```

Smoke 2026-11-20: offline 13/13; live 14 cases, 7 runs while tuning, final runs read by the
author ("this is good"). Known quirks of the 9B base: an "I suppose" tic and an occasional
quoted-narration reply.
