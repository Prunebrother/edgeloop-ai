# Linux installation

Use a separate checkout and a fresh browser profile. Python 3.12+ with venv/pip and Node 22+ are required. Install those using your distribution's package manager. Install Ollama using its [official Linux instructions](https://docs.ollama.com/linux); review commands before running them. No model weights are bundled.

From this source directory:

```bash
./tools/setup-ai.sh
./tools/serve-local.sh
```

The UI is at http://127.0.0.1:8770/. In this release package, `npm start` also invokes the existing protected loopback launcher. This explicitly replaces the upstream general-purpose HTTP-server alias, which could serve private files from the checkout. The normal launcher, hardware defaults and runtime configuration are unchanged. The setup script installs pinned Python requirements and this package in a local `.venv`; network access to package repositories is required on a fresh system. Fresh installation into a new virtual environment succeeded during candidate validation. Dependencies remain separately downloaded; this is not an offline package. No JavaScript build is required. The UI currently loads Tailwind and PeerJS from CDNs; offline UI rendering is not guaranteed.

Use an existing Ollama instance if available. The unchanged project default is port 11435. Standard Ollama installations commonly use 11434; explicitly select the intended endpoint:

```bash
EDGELOOP_OLLAMA_URL=http://127.0.0.1:11434 ./tools/serve-ai.sh --check
EDGELOOP_OLLAMA_URL=http://127.0.0.1:11434 ./tools/serve-ai.sh
```

If running a new dedicated Ollama manually on an unused port:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama serve
```

Do not start another instance on an occupied port or stop an unrelated instance. Run `./tools/ollama-status.sh --url http://127.0.0.1:11435` to diagnose connections. Pair through Chat with the observer's printed token, select an installed model and press Switch model. Tokens are sensitive and should never be copied into issues. `.env.example` documents environment variables; launchers do not automatically load `.env` files. Shell exports or explicit command prefixes work.

Model installation commands and alias mapping are in [MODELS_AND_ASSETS.md](MODELS_AND_ASSETS.md). No private local model files are required by the source definitions. Registry tags may change, so record model digests and Ollama version when reproducing results.

## Simulation first

Leave every physical device disconnected. Open the heart-rate card, choose Manual Simulator, set a fictional value such as 98 and engage it. The original readiness gate still requires a toy for a running session; simulated HR alone does not bypass it. Explore idle AI dialogue without a toy. For a fully running simulation, use the existing mocked browser fixture, which denies hardware permissions and mocks Handy and Ollama:

```bash
npm ci
npx playwright install chromium
FORK_BROWSER_PORT=18770 FORK_OBSERVER_PORT=18768 \
  FORK_BROWSER_REPORT=/tmp/edgeloop-demo node tests/fork/browser.mjs
```

Use unused ports. Screenshots and fixture reports must be reviewed before sharing. The fixture uses fictional data and an isolated browser context. A local real-model idle smoke is optional, explicit, and writes to a new output path:

```bash
./tools/smoke-ai.sh --url http://127.0.0.1:11435 \
  --models nova-narrative-v1:latest --thinking off --output /tmp/edgeloop-model-smoke.json
```

## Existing desktop launcher

After setup, `./tools/install-desktop.sh` installs user systemd units, desktop entries and `edgeloop-ai`. This changes user configuration and reloads systemd, but does not start services or enable login startup. Inspect existing units before installation to avoid replacing another checkout's launcher. `edgeloop-ai start`, `status` and `stop` manage the dedicated stack on 11435 / 8768 / 8770 using the user's Ollama model store. End hardware sessions with EdgeLoop first. These commands were not run during release preparation.

## Troubleshooting

Check `ss -ltnp` for occupied ports. Never kill an unknown process to free a port. `EDGELOOP_OBSERVER_PORT` changes the observer port; the UI observer URL must match. `./tools/serve-local.sh PORT` changes the web port; observer origin validation may require code-reviewed configuration for a nonstandard web origin. An arbitrary port change is not sufficient to establish pairing. Keep normal use at 8770 unless using the fixtures.

A missing model requires an explicit pull/create on the same Ollama endpoint used by the observer. A token rejection can mean expiration, an incorrect origin, or a restarted observer; pair again. Never expose the observer or Ollama on a public interface. Missing character images are expected in this package. If dependencies cannot resolve, retain the pip error locally and redact paths/tokens before filing an installation issue.
