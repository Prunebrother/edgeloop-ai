# EdgeLoop AI

EdgeLoop AI adds local AI companions to [EdgeLoop by marshallmims](https://github.com/marshallmims/edgeloop), based on version 1.1.3, upstream commit `d351e011249079b368ebdc8d46f83b260be7d2a5`. Maintained by Prunebrother. Experimental software for adults; physical safety has not been verified.

## Install the complete Linux release

On Linux x86_64 with a systemd user session and a current Chromium browser:

```bash
curl -fLO https://github.com/Prunebrother/edgeloop-ai/releases/download/v0.3.1/install.sh
bash install.sh
```

The installer downloads and verifies the complete release, installs into your account without sudo, creates **EdgeLoop AI** and **Stop EdgeLoop AI** application shortcuts, and opens the app. Accept the adult-use gate, then chat with Nova or choose another companion. No Python, Node, Ollama or model commands are needed. Keep approximately 40 GB free during installation; the download contains both substantial base-model weight sets. Downloads resume when you rerun the installer. You can remove its download cache after installation.

The complete bundle includes all 48 original character portraits, ten prepared character models for Evelyn, Daisy, Celeste and Nova, both base-model weight sets, Ollama 0.40.13, portable Python 3.12.16, pinned Python dependencies and local browser libraries. A source ZIP or Git clone includes the artwork and model definitions; use the **Release installer** for runtimes and weights.

Inference runs locally. A CPU can run the models slowly; compatible NVIDIA hardware can accelerate the bundled runtime. Available RAM/VRAM must accommodate the model and its context. No universal minimum or latency guarantee has been established. AMD ROCm acceleration, Windows, macOS, ARM and non-systemd installation are outside this bundle's tested scope.

[Installation, offline use and troubleshooting](INSTALL.md) · [Models and artwork](MODELS_AND_ASSETS.md) · [Validation](VALIDATION.md) · [Licenses](THIRD_PARTY_NOTICES.md)

## What it does

The browser engine controls biofeedback sessions and hardware. The AI receives read-only observations, provides local dialogue and uses a bounded Conversation Director. It cannot send device commands. Story Memory is isolated by character/model. Session Journal recording and historical AI access require separate opt-ins. Experimental Director initiative is off by default. Use the [simulation-first instructions](INSTALL.md) before considering hardware.

No automatic session upload is added. Browser libraries are served locally. Optional peer signaling, device cloud APIs and external links can still use the network; see [privacy](PRIVACY.md), [safety](SAFETY.md) and [known issues](KNOWN_ISSUES.md).

## Development and source

For development, install Python 3.12+, run `./tools/setup-ai.sh`, and follow the manual workflow in [INSTALL.md](INSTALL.md). Node 22+ is needed only for tests. Release inputs and model weight hashes are pinned in `release-inputs.json`; [building instructions](RELEASING.md) explain how to recreate the bundle.

Source and maintainer-generated artwork are distributed under AGPL-3.0-only. Aggregated third-party runtimes, libraries and model weights retain their own licenses and notices. Original documentation and acknowledgments are retained in [docs/upstream](docs/upstream/README.md). This fork is not an upstream release or endorsement. The repository and release downloads provide the source and local application; no running application is hosted.
