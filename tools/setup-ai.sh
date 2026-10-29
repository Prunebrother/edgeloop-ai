#!/usr/bin/env bash
# AGPL-3.0-only. Explicit dependency setup; no service/model/hardware starts.
set -euo pipefail
fork_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$fork_root"
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock 'setuptools>=77'
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
