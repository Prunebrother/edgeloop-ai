#!/usr/bin/env bash
# AGPL-3.0-only. Inspect only an existing local runtime.
set -euo pipefail
fork_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$fork_root/.venv/bin/python" -I -m ai_observer.diagnostics "$@"
