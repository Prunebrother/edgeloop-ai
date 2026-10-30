# Licensing and attribution

The complete release aggregates separately licensed components. The project's AGPL license does not replace third-party licenses.

| Component | License and provenance |
| --- | --- |
| Original EdgeLoop 1.1.3 | AGPL-3.0-only; LICENSE, upstream hash pin, attribution, original documentation and acknowledgments retained. https://github.com/marshallmims/edgeloop |
| AI source, character prompts/lore | AGPL-3.0-only; maintainer confirmed authorship and authorized publication on 2026-10-29. |
| 48 character portraits | Maintainer-generated artwork; maintainer authorized inclusion on 2026-10-29, distributed with the AGPL-3.0-only project. Original PNG bytes retained. See licenses/ARTWORK.md. |
| Upstream icons | Retained under the upstream repository's declared license. |
| Ollama 0.40.13 | MIT; licenses/OLLAMA-LICENSE. Official binary archive retained, including its third-party license/notice files under runtime/ollama/lib/ollama. https://github.com/ollama/ollama/tree/v0.40.13 |
| CUDA libraries inside Ollama | NVIDIA CUDA redistribution terms; licenses/NVIDIA-CUDA-12.8-EULA.html and NVIDIA-CUDA-13.0-EULA.html. These libraries retain NVIDIA terms rather than Ollama's MIT license. |
| OpenMP library inside Ollama | GPLv3 with GCC Runtime Library Exception; notices in licenses, documented corresponding-source export included under third-party-sources; original pinned RPM provenance retained, with one unrelated Go binary core fixture omitted. See licenses/OPENMP.md. |
| Qwen3 8B weights | Apache-2.0; licenses/models/qwen3_8b.txt and original registry license layer. https://huggingface.co/Qwen/Qwen3-8B |
| Huihui Qwen3.5 9B abliterated weights | Apache-2.0; licenses/models/huihui_ai_qwen3.5-abliterated_9b.txt and original license layer. https://huggingface.co/huihui-ai/Huihui-Qwen3.5-9B-abliterated |
| Portable CPython 3.12.16 | Python Software Foundation and included dependency terms. CPython license under runtime/python/lib/python3.12/LICENSE.txt; build/dependency inventory under licenses/python. https://github.com/astral-sh/python-build-standalone/releases/tag/20261026 |
| Python wheels | Exact versions in requirements.lock and release-inputs.json; each wheel retains its publisher's license/notice metadata, also installed into the environment. Publisher declarations recorded in DEPENDENCY_LICENSES.md. |
| Tailwind browser runtime 3.4.17 | MIT; licenses/TAILWIND-LICENSE. Vendored from https://cdn.tailwindcss.com/3.4.17 to src/js/vendor/tailwind.js. |
| PeerJS 1.5.4 | MIT; licenses/PEERJS-LICENSE. Vendored from https://unpkg.com/peerjs@1.5.4/dist/peerjs.min.js. |
| Playwright | Apache-2.0; optional development/test dependency, not part of the installed app runtime. https://github.com/microsoft/playwright |

`release-inputs.json` pins runtime archive and base-weight hashes; `MANIFEST.json` covers public source/art, and release `BUNDLE.json` covers the complete distribution. Only the two named public base manifests and their referenced blobs are imported; character models are rebuilt from the public source. No private prompts, developer model aliases, user keys or runtime data are imported.

The reduced-filtering model publisher describes the model as experimental. This release retains its source attribution and unchanged model license layers. The bundle changes neither base-weight tensors nor publisher license terms. Character parameters and system prompts are added by the public Modelfiles.

The exact corresponding application source is available at https://github.com/Prunebrother/edgeloop-ai and included in each complete bundle. No public running application is hosted.
