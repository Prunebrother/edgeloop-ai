# Building a complete release

Release target: Linux x86_64. Build on Linux x86_64 with Python 3.12+, curl, tar, zstd, gzip and split. Model/runtime inputs are recorded in release-inputs.json. The build workspace must be outside the public checkout and have approximately 40 GB free. Prepare a model store containing the exact two base models whose weight hashes match release-inputs.json.

After updating source/art, run `python3 tools/refresh-release-manifest.py`, review the diff and run the checks in VALIDATION.md:

```bash
python3 tools/build-release.py --work /path/to/build-workspace --model-store /path/to/base-model-store
```

The builder verifies official Ollama and portable Python archive hashes, downloads pinned wheels, copies only reviewed source/art and the two public base manifests/blobs, verifies every blob hash, and creates ten public character aliases with a temporary isolated Ollama server on an ephemeral loopback port. It never imports private aliases or changes the source model store. Model license layers are also retained as readable notices. Runtime libraries and wheels retain their upstream notices.

The result is an offline distribution under `stage/` with a per-file BUNDLE.json, plus `dist/install.sh`, SHA256SUMS, BUNDLE.json and archive parts below 2 GB each. `--pack-only` reseals and packs an already prepared stage; it does not update its source files. Only explicit reviewed source paths from MANIFEST.json enter the stage. Start with a fresh workspace when changing runtime/model inputs; do not reuse a stage with unknown contents.

Test the extracted archive at its permanent path using `bash tools/install-bundle.sh --no-desktop --no-start --home /path/to/test-home`. Use a disposable desktop user session for full systemd install/start/stop testing. Source tests and actual model inference are separate checks; neither certifies physical hardware behavior.

Publish the new source commit on main and tag v0.3.0, then upload all dist assets to the matching GitHub Release. The generated installer references that immutable version URL. Retain historical release commits; do not force-push or replace original history. The complete bundle includes exact application source. Do not enable Pages or deploy a running app as part of publication.
