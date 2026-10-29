# F2.10 release-candidate validation

Assessment: **Authorized for source publication** to https://github.com/Prunebrother/edgeloop-ai. On 2026-10-29, Prunebrother confirmed authorship of the migrated AI source and character prompts/lore and authorized AGPL-3.0-only publication, public repository creation, the initial release commit and push. Character artwork and model weights remain excluded. Hosting the running application is not authorized.

## Executed checks

| Check | Result |
| --- | --- |
| Fresh Linux Python installation | Passed in a new candidate virtual environment using tools/setup-ai.sh; pip check found no broken requirements. Initial restricted-network attempt failed DNS; retry with network access succeeded. |
| Python suite | 706 passed, 2 explicitly skipped artwork-dependent checks; one FastAPI/Starlette dependency deprecation warning. Tests use isolated temporary data and mocked inference. |
| Fork JavaScript suite | 63 passed, no failures. |
| Upstream JavaScript suite | 1057 passed, no failures or skips in the final complete npm test run. |
| Documentation portability regressions | Backup, engine documentation, version and documentation guards passed individually after following preserved upstream documents. |
| Simulated AI companion session | Existing browser acceptance passed on separate localhost ports, with hardware permissions denied and Handy/Ollama mocked. Session start, pause/resume/stop, read-only observations, model failure, grounding retry, streaming and mobile fallback were exercised. |
| Static-server privacy | Temporary release-only server returned UI 200 and 404 for Git config, private journal, runtime config and Python source URLs. |
| Upstream integrity/provenance | Passed original hash pin plus explicitly reviewed changes and deployment/CI exclusions. LICENSE, original notices and upstream documentation retained. |
| Source preservation | AI Python runtime, hardware drivers, browser engine/watchdog/session rules, read-only bridge, character Modelfiles/lore/manifest and runtime config match the working source snapshot. |
| Private repository preservation | Original HEAD and full working-tree status match the starting state; no source-file changes found. Services and model stores were not managed by this task. |
| Source imports/syntax | Python runtime syntax parsed; no missing relative browser-module imports found. |
| Release privacy audit | No private session storage, model weights, private Git history, private remotes, developer home paths/name/hostname, known private identity strings, recognized provider-token/private-key patterns or actual MAC addresses found in packaged content. Public upstream attribution and clearly synthetic malformed-URL/secret fixtures remain. |
| Public Git identity | Repository-local author and committer: Prunebrother <224366760+Prunebrother@users.noreply.github.com>; useConfigOnly enabled, signing disabled and hooks disabled. Initial commit must be a single root with no private history. |

Private development history was inspected read-only: reachable and reflog-referenced commits and unique blobs, plus tracked/untracked/ignored working files. The private audit and exact exclusion manifest are stored outside this source directory. Pattern scanning is conservative and cannot prove absence of every conceivable secret or identifying phrase; review the staged candidate before approval.

## Release-specific test adaptations

Private Git checkpoints were replaced with standalone AGPL source fixtures for historical bug comparisons. No private history was imported. A checkout-name assertion now checks the actual installation location. Migration checks include only shipped source, excluding development notes. Upstream README/changelog assertions follow their preserved location under docs/upstream. Artwork-dependent checks are skipped with an explicit reason, rather than silently replaced with unlicensed assets. Runtime and character implementation were not changed.

The first unrestricted Python run exposed export portability errors; those were corrected and the complete suite rerun. An initial combined Node run with isolation disabled across all upstream files caused shared-state interference and is not accepted as a suite result. Subsequent full-suite documentation failures were corrected by following the preserved upstream documents. Final results must be interpreted using the final run, not the earlier logs.

## Remaining limits and local follow-up

- Source/character rights, public identity and publication approval were resolved by the maintainer on 2026-10-29. This records the maintainer’s confirmation, not independent verification of authorship. Artwork and model-weight rights remain separate; neither is included.
- Publication uses the maintainer’s existing GitHub account and its existing public associations; anonymity is not guaranteed.
- Real Ollama model pull/create, real-model inference latency/quality, memory semantic quality, sustained Director initiative and physical hardware behavior were not tested. Existing local models were neither loaded for this task nor rebuilt. No physical-safety claim is made.
- Browser UI rendering still depends on external CDNs; model tags and the unversioned Tailwind CDN are mutable. Python and optional Playwright package versions are recorded, but this is not an offline or fully content-addressed distribution.
- Two portrait-source checks remain skipped because art is absent. The existing portrait fallback was exercised in the mocked browser acceptance.
- A dependency warns about FastAPI/Starlette's use of httpx TestClient. Dependencies were not upgraded during release preparation.
- Gitleaks 8.30.1 was downloaded from its official release and its archive SHA-256 verified. The source scan found six generic-api-key matches: two upstream source-integrity hashes and four synthetic tokens in upstream protocol tests. All six were reviewed as false positives; no real credential was found. Custom token/key/MAC/home-path patterns, known-private-identity matching, hostname checks, image-chunk inspection and file allowlist/hash review supplement the scanner. No scanner proves absence of every secret.
- Publication reruns integrity and JavaScript checks and reviews the exact staged tree and initial commit metadata. Earlier Python installation/suite and mocked browser results above are retained preparation evidence; real-model/hardware validation remains unperformed.
- The conservative release validator intentionally rejects any Git history or configured remote. Run it before the initial commit; after publication, separately review the approved remote, single-root history and manifest hashes rather than treating those expected Git warnings as a content failure.

To repeat checks from a clean copy:

```bash
./tools/setup-ai.sh
npm ci
npx playwright install chromium
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
npm test
node --test --test-isolation=none tests/fork/*.test.mjs
python3 tools/fork_validate.py
python3 tools/validate-release.py
FORK_BROWSER_PORT=18770 FORK_OBSERVER_PORT=18768 \
  FORK_BROWSER_REPORT=/tmp/edgeloop-simulation node tests/fork/browser.mjs
```

For an explicit real-model idle smoke on an already running local Ollama, use the command in INSTALL.md with a newly chosen output file. That check is synthetic and does not validate physical safety. Do not run launcher installation/start/stop commands on an existing active development setup merely to repeat release validation.
