#!/usr/bin/env bash
# Explicit local inference smoke. Never starts an Ollama daemon or touches hardware.
set -euo pipefail
fork_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$fork_root/.venv/bin/python" -I -m ai_observer.smoke "$@"
