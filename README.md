# EdgeLoop AI

EdgeLoop AI adds local AI companions to [EdgeLoop by marshallmims](https://github.com/marshallmims/edgeloop), based on version 1.1.4.33, upstream commit `d3c5df33834f6106796e3768ad283d0eb5ab1ef9`. Maintained by Prunebrother. Experimental software for adults; physical safety has not been verified.

## Current release: v0.8.0-rc1 (Linux and Windows)

[v0.8.0-rc1](https://github.com/Prunebrother/edgeloop-ai/releases/tag/v0.8.0-rc1) brings the Character Builder, several orgasms per session with an **I came** button, companions that run the next round on their own, and an experimental Windows installer. The Windows build has not been hardware tested yet, so keep your toy's own stop button within reach. The previous release, [v0.4.0](https://github.com/Prunebrother/edgeloop-ai/releases/tag/v0.4.0), stays available. Install instructions for both platforms are in [INSTALL.md](INSTALL.md) and on the release page.

**Windows 10/11 (experimental):** download `EdgeLoop-AI-Setup-v0.8.0-rc1.exe` from the [release page](https://github.com/Prunebrother/edgeloop-ai/releases/tag/v0.8.0-rc1) and run it.

## Install the complete Linux release

On Linux x86_64 with a systemd user session and a current Chromium browser:

```bash
curl -fLO https://github.com/Prunebrother/edgeloop-ai/releases/download/v0.8.0-rc1/install.sh
bash install.sh
```

The installer downloads and verifies the complete release, installs into your account without sudo, creates **EdgeLoop AI** and **Stop EdgeLoop AI** application shortcuts, and opens the app. Accept the adult-use gate, then chat with Nova or choose another companion. No Python, Node, Ollama or model commands are needed. Keep approximately 25 GB free during installation; the download is about 9 GB, most of it base-model weights. Downloads resume when you rerun the installer. You can remove its download cache after installation.

The complete bundle includes all 48 original character portraits, four prepared character models for Evelyn, Daisy, Celeste and Nova, the base-model weight set, Ollama 0.40.13, portable Python 3.12.16, pinned Python dependencies and local browser libraries. A source ZIP or Git clone includes the artwork and model definitions; use the **Release installer** for runtimes and weights.

Inference runs locally. A CPU can run the models slowly; compatible NVIDIA hardware can accelerate the bundled runtime. Available RAM/VRAM must accommodate the model and its context. No universal minimum or latency guarantee has been established. Windows is supported experimentally through its own setup program. AMD ROCm acceleration, macOS, ARM and non-systemd installation are outside this bundle's tested scope.

[Installation, offline use and troubleshooting](INSTALL.md) · [Models and artwork](MODELS_AND_ASSETS.md) · [Validation](VALIDATION.md) · [Licenses](THIRD_PARTY_NOTICES.md)

## What it does

The browser engine controls biofeedback sessions and hardware. The AI receives read-only observations, provides local dialogue and uses a bounded Conversation Director. It cannot send device commands. Optional AI Settings Control (off by default) lets a companion request a small set of session-setting changes through a local engine gate; see [SAFETY.md](SAFETY.md). Story Memory is isolated by character/model. Session Journal recording and historical AI access require separate opt-ins. Experimental Director initiative is off by default. Use the [simulation-first instructions](INSTALL.md) before considering hardware.

No automatic session upload is added. Browser libraries are served locally. Optional peer signaling, device cloud APIs and external links can still use the network; see [privacy](PRIVACY.md), [safety](SAFETY.md) and [known issues](KNOWN_ISSUES.md).

## Development and source

For development, install Python 3.12+, run `./tools/setup-ai.sh`, and follow the manual workflow in [INSTALL.md](INSTALL.md). Node 22+ is needed only for tests. Release inputs and model weight hashes are pinned in `release-inputs.json`; [building instructions](RELEASING.md) explain how to recreate the bundle.

Source and maintainer-generated artwork are distributed under AGPL-3.0-only. Aggregated third-party runtimes, libraries and model weights retain their own licenses and notices. Original documentation and acknowledgments are retained in [docs/upstream](docs/upstream/README.md). This fork is not an upstream release or endorsement. The repository and release downloads provide the source and local application; no running application is hosted.
