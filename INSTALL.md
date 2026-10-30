# Install EdgeLoop AI

## Complete Linux bundle

F2.10.1 regenerates runtime bytecode with neutral filenames and preserves the installer hotfix. Application behavior, character definitions and the model inventory are unchanged. The bundled OpenMP source export preserves build sources and notices while omitting one unrelated Go binary test core containing captured environment data.

Supported target: Linux x86_64, a working systemd user session, glibc Linux (not Alpine/musl), and an installed current Chromium browser. The browser and hardware drivers remain system requirements. Plan for approximately 40 GB free during download/extraction. Model inference needs enough RAM/VRAM for an 8B/9B model plus context; CPU execution may be slow. No sudo or system-wide Ollama service is required.

```bash
curl -fLO https://github.com/Prunebrother/edgeloop-ai/releases/download/v0.3.1/install.sh
bash install.sh
```

The installer downloads all release parts with resume support, checks SHA-256 sums, extracts and verifies the bundle, creates a Python environment from offline wheels, installs user services and application shortcuts, starts the dedicated stack and opens http://127.0.0.1:8770/. Accept the adult-use gate and finish or skip the existing hardware setup wizard. Desktop pairing and saved model selection happen automatically; Nova is selected on a new installation. Choosing another installed character uses the Chat model menu.

The bundle includes both base-model weights, ten character model definitions already registered with Ollama, 48 expression portraits, portable Python, Ollama, Python wheels and browser libraries. No package manager, Git, Node, model pull or manual token is required. The small downloader needs standard `bash`, `curl`, `tar`, `gzip`, `sha256sum` and `flock` tools.

Installation location: `~/.local/share/edgeloop-ai/releases/v0.3.1`. Model weights live inside that version's `models/`; this avoids changing a separate Ollama installation. User settings/history live at `~/.local/share/edgeloop-ai/data`. Downloads are cached under `${XDG_CACHE_HOME:-~/.cache}/edgeloop-ai/v0.3.1`; remove that cache after successful installation to reclaim disk space. Rerunning installation preserves user settings. It does not enable login startup.

Use **EdgeLoop AI** to start and **Stop EdgeLoop AI** to stop. The command `~/.local/bin/edgeloop-ai status` reports service status. End hardware sessions in the browser before stopping services. Services use loopback ports 11435 (Ollama), 8768 (observer) and 8770 (web). An occupied port produces an error; unrelated processes are never killed. Stop an existing EdgeLoop installation before replacing its user service definitions.

`bash install.sh --no-start` installs without launching. `--no-desktop` prepares the environment without installing services; it is intended for validation/custom integration, not the normal desktop experience.

## Offline transfer

On another machine, download `SHA256SUMS` and **all** `edgeloop-ai-linux-x86_64.tar.gz.partNN` assets from the same release. Copy them together to the target machine, then:

```bash
sha256sum --ignore-missing -c SHA256SUMS
mkdir edgeloop-ai
cat edgeloop-ai-linux-x86_64.tar.gz.part* | tar -xz -C edgeloop-ai
cd edgeloop-ai
PYTHONDONTWRITEBYTECODE=1 bash tools/install-bundle.sh
```

Every listed part must be present. The extracted bundle verifies its file hashes again before installing. This path needs no internet for installation or local AI/UI. Optional peer/device cloud features still need their respective network services. The extraction directory is the permanent application location; do not move or delete it after installing shortcuts.

## Simulation first

Leave physical devices disconnected. Use the heart-rate card's Manual Simulator with a fictional value such as 98 BPM. Idle AI dialogue works without a toy. Simulated heart rate alone does not bypass the original toy readiness gate for a running session. For a fully running mocked simulation, use the developer fixture below; it denies hardware permissions and mocks Handy/Ollama.

## Developer source installation

The Git source includes art and character definitions, but the multi-gigabyte runtime/weight files are Release assets. For manual development with Python 3.12+ and an existing Ollama:

```bash
./tools/setup-ai.sh
EDGELOOP_OLLAMA_URL=http://127.0.0.1:11434 ./tools/serve-ai.sh
./tools/serve-local.sh
```

The unchanged configuration default is 11435; explicitly select 11434 if using standard Ollama. Install the intended models with the commands in MODELS_AND_ASSETS.md. Pair manually using the observer token, select the installed model and press Switch model. Launchers do not automatically load `.env` files. Never share pairing tokens.

For browser regression tests only:

```bash
npm ci
npx playwright install chromium
FORK_BROWSER_PORT=18770 FORK_OBSERVER_PORT=18768 \
  FORK_BROWSER_REPORT=/tmp/edgeloop-demo node tests/fork/browser.mjs
```

## Troubleshooting and uninstall

If an older v0.3.0 installer reports `Bundled file failed integrity check` for a file under `__pycache__`, run `PYTHONDONTWRITEBYTECODE=1 bash install.sh`, or download the updated installer using the command above and rerun it. The installer reuses verified cached downloads. This prevents Python from rewriting bundled bytecode before verification; all integrity checks remain enabled. For an extracted offline bundle, extract it afresh and use the offline command above.

Run `~/.local/bin/edgeloop-ai status` and inspect `journalctl --user -u edgeloop-ai-ollama -u edgeloop-ai-observer -u edgeloop-ai-web`. A failed checksum causes installation to stop; rerun to retry/resume. `systemctl --user` requires a desktop user session. Browser Bluetooth/serial permissions and device setup remain explicit user actions. Never expose Ollama or the observer on a public interface.

To uninstall, end hardware sessions, stop EdgeLoop AI, remove its three user service files and `edgeloop-ai.target` from `~/.config/systemd/user`, remove the two EdgeLoop desktop files from `~/.local/share/applications` and the `~/.local/bin/edgeloop-ai` link, then run `systemctl --user daemon-reload`. Remove the version directory and download cache. User history is retained in the separate data directory; delete it and browser site data only if you intend to erase them. See PRIVACY.md.
