# Complete release validation

Release v0.3.0 replaces the initial source-only installation experience with a complete Linux x86_64 bundle. The maintainer authorized artwork, open-weight model and Ollama inclusion on 2026-10-29. Original development history, private model aliases and user data remain outside the release. The exact application source is included in the bundle and published at the matching release tag.

| Check | Result |
| --- | --- |
| Python regression suite | 712 passed, no skipped tests. Includes installer integrity, clean-user defaults, preservation of saved selection, bundled desktop paths, credential boundaries, character assets and AI regressions. One existing Starlette/httpx deprecation warning. |
| Upstream browser-engine JavaScript | 1,057 passed, no failures or skips. Hardware behavior exercised with existing mocks; no physical devices. |
| Companion JavaScript | 63 passed, no failures or skips, including the corrected Daisy Lite portrait mapping. |
| Character browser acceptance | Passed all 48 original expression portraits, character/model switching, expression reactions, cancellation, fallback, mobile/desktop layouts and mocked emergency stop. Physical-device access denied. |
| Offline environment installation | Passed with bundled Python and local wheels using pip --no-index. Package installation, editable application imports and clean-user setup succeeded without a package index or system Ollama/Python installation. Desktop writes/start were skipped in this isolated validation. |
| Real bundled-model browser acceptance | Passed with the included Ollama binary and isolated copied weight store: ten character aliases discovered and native prompts matched public Modelfiles; automatic desktop pairing and Nova selection; a real Nova reply; reload/reconnection; 48 portraits served; private runtime/model paths returned 404. External browser requests were blocked and none were attempted. Bluetooth, serial and microphone access were denied. |
| Dependency consistency | pip check passed. Python dependencies remain pinned in requirements.lock; build wheels and runtime archive hashes are pinned in release-inputs.json. |
| Public source integrity | Upstream baseline retained with explicit reviewed file changes. Public source/art MANIFEST.json and complete per-file BUNDLE.json provide SHA-256 inventories. Official Ollama and portable Python archive hashes verified before extraction; both base-weight hashes and every imported blob verified. |
| Redistribution notices | Model license layers, readable model licenses, Python linked-library inventory, Ollama notices, browser-library licenses, CUDA terms and exact matching OpenMP source RPM retained. OpenMP binary was matched byte-for-byte to the official AlmaLinux package. |
| Source and image metadata scan | Gitleaks found the same six reviewed false positives: two upstream integrity hashes and four synthetic protocol-test tokens. PNG ancillary/provenance chunks across all 48 originals contained no matches for developer home paths, private keys or provider-token patterns. Pattern checks do not prove absence of all sensitive information. |

The real-model test used an NVIDIA RTX 3080. This is evidence for a local smoke test, not a performance guarantee, sustained conversational-quality result or physical-safety assessment. Long sessions, semantic memory quality, Director initiative quality and physical hardware behavior require separate evaluation. No physical device was connected by release validation. Session/hardware protections and the read-only AI boundary are preserved.

Generated systemd service files are covered by isolated installer tests and passed systemd-analyze --user verify, including an installation path containing spaces. The real bundle test launched the same programs and environment directly on unused loopback ports; it did not replace or start the developer's installed systemd units. Full desktop login-session behavior across Linux distributions remains a portability limit. Windows, macOS, ARM, musl Linux and ROCm acceleration are outside this bundle's supported scope.

## Repeat developer checks

```bash
./tools/setup-ai.sh
npm ci
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
npm test
node --test --test-isolation=none tests/fork/*.test.mjs
python3 tools/fork_validate.py
python3 tools/validate-release.py
CHARACTER_BROWSER_REPORT=/tmp/edgeloop-character-check node tests/fork/character-browser.mjs
```

Browser acceptance requires a separately installed Playwright Chromium (`npx playwright install chromium`) for development only. With a complete bundle installed into a disposable directory, explicitly opt into real inference:

```bash
EDGELOOP_BUNDLE_ROOT=/path/to/installed-bundle node tests/fork/bundle-browser.mjs
```

That test requires free loopback ports 11435, 8768 and 8770, rejects occupied ports, creates private temporary user data, starts only its own child processes and stops them afterward. It blocks physical-device requests and external browser requests. Reports/screenshots stay outside the public source. Complete build and packaging instructions are in RELEASING.md.
