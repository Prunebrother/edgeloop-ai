# Contributing

Use a separate development checkout and synthetic fixtures. Keep hardware authority in EdgeLoop and AI output read-only. Preserve character/model isolation, opt-in journal recording, explicit history permission, bounded scheduling/context and `think:false`. Default-off experimental features must stay opt-in. Do not rewrite character identities, prompts, lore or art as part of release maintenance.

Run setup, then `.venv/bin/python -m pytest -q`, `npm test`, and `node --test --test-isolation=none tests/fork/*.test.mjs`. Run the mocked browser fixture described in INSTALL.md for UI/connection changes. Run `python3 tools/fork_validate.py` for upstream file provenance and `python3 tools/validate-release.py` for the packaged manifest/privacy checks. Report skipped checks and environment limitations; never describe mocks as live-hardware validation.

Changes to hardware drivers, stop/disconnect behavior, readiness, physiological calculations or safety rules require focused review, meaningful regression tests and an explicit explanation of impact. Simulation evidence is required before considering separately supervised physical testing. No AI action path may control hardware.

Use the issue templates. Include source version, browser/runtime versions, model tag/digest, synthetic steps, expected/actual results and redacted error output. Do not upload private sessions, databases or transcripts. Discuss sensitive security findings privately through an agreed channel before sharing exploit details publicly; no private reporting channel is configured yet.

Preserve AGPL-3.0-only notices and upstream attribution. Contributions must have redistribution rights and compatible licensing; code licensing does not grant model/art rights. Use an intentionally chosen public Git identity. Avoid signing commits with an identifying key or including personal paths in artifacts. No automatic telemetry should be added.
