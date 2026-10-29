#!/usr/bin/env bash
# AGPL-3.0-only. Self-contained observer; never starts Ollama or hardware.
set -euo pipefail
fork_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python="$fork_root/.venv/bin/python"
if [[ ! -x "$python" ]] || ! "$python" -I -c 'import ai_observer, companion_ai' 2>/dev/null; then
  echo "AI environment missing. From $fork_root run ./tools/setup-ai.sh" >&2
  exit 1
fi
exec "$python" -I -m ai_observer.server "$@"
