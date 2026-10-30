#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
# Keep the verified runtime unchanged throughout installation and reinstallation.
export PYTHONDONTWRITEBYTECODE=1
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'This bundle requires Linux x86_64.' >&2; exit 1; }
[[ -x runtime/python/bin/python3 && -x runtime/ollama/bin/ollama && -d models && -d wheelhouse ]] || {
  echo 'Use the complete Linux bundle from Releases. This source checkout does not contain the runtimes and weights.' >&2; exit 1;
}
echo 'Verifying bundled files…'
runtime/python/bin/python3 tools/bundle.py verify
echo 'Installing the offline Python environment…'
runtime/python/bin/python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --no-index --find-links wheelhouse -r requirements.lock setuptools==84.2.1 wheel==0.48.0
.venv/bin/python -m pip install --disable-pip-version-check --no-index --find-links wheelhouse --no-build-isolation --no-deps -e .
.venv/bin/python tools/bundle.py configure "$@"
