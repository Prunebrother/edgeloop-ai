#!/usr/bin/env bash
# AGPL-3.0-only. Install explicit, user-owned services; do not start or enable them.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$root/tools/install_desktop.py"
