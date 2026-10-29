# Licensing and attribution findings

Reviewed for this candidate; this is a provenance inventory, not a legal clearance opinion.

| Component | Evidence / boundary |
| --- | --- |
| Original EdgeLoop 1.1.3 | LICENSE contains GNU Affero General Public License v3; package.json declares AGPL-3.0-only. Upstream pin and source notices retained. Original README/changelog are preserved under docs/upstream, including acknowledgments. |
| AI modifications / migrated source | pyproject.toml and inherited notices declare AGPL-3.0-only. Prunebrother confirmed authorship and explicitly authorized AGPL-3.0-only publication on 2026-10-29. |
| Character Modelfiles and lore | Included byte-for-byte under the existing fork's declared source license; Prunebrother confirmed authorship and authorized AGPL-3.0-only publication of prompts/lore on 2026-10-29. No grant for art or weights is inferred. |
| Character art | Excluded in full: no clear asset-specific redistribution grant located. Some files have embedded C2PA provenance. Source images were neither altered nor replaced. |
| Upstream icons | Existing upstream assets retained under the upstream repository's declared license; no separate license found. PNG chunks reviewed for identifying metadata; SVG source retained. |
| Model weights | Excluded. Download directly from the chosen registry and comply with its license/terms. |
| qwen3:8b | Registry page lists Apache 2.0: https://ollama.com/library/qwen3:8b. |
| huihui_ai/qwen3.5-abliterated:9b | Registry page lists Apache 2.0: https://ollama.com/huihui_ai/qwen3.5-abliterated:9b. Reduced filtering and experimental-use warnings apply. |
| Python dependencies | Installed separately using requirements.lock; no vendored package copies. Obtain each distribution's license/notice with installation. See pyproject.toml for direct dependencies and DEPENDENCY_LICENSES.md for installed publisher license declarations. |
| Tailwind CSS / PeerJS | Browser fetches Tailwind CDN and PeerJS 1.5.4 from unpkg. Upstream projects declare MIT licenses; copies are not vendored. External requests remain. See https://github.com/tailwindlabs/tailwindcss and https://github.com/peers/peerjs. |
| Playwright | Optional browser-test dependency, Apache-2.0 upstream: https://github.com/microsoft/playwright. Browser binaries installed separately carry their own notices. |

Model registry tags are mutable. Registry license display was checked during preparation; this does not establish prompt/art ownership or certify every derivative's provenance. No automatic model download, weight packaging or new external telemetry is introduced. Include license/notice materials if dependencies or assets are later vendored. For actual legal conclusions about disputed rights, obtain appropriate review.

Before making the modified application available to remote users, configure a prominent offer of its exact corresponding source. Existing UI GitHub links identify upstream, not a future fork repository. No fork URL or public deployment is configured in this candidate; see PUBLICATION_CHECKLIST.md.
