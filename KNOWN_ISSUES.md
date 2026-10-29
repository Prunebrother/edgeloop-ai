# Known issues and evidence limits

AI text can hallucinate physiology, actions, feelings and prior events. Grounding filters and explicit uncertainty reduce errors without proving factual correctness. Reported device readiness and engine settings are not confirmation of a physical action.

Story Memory extraction, source revision, hobby recall, semantic retrieval and long-session retention can omit, overgeneralize or misattribute details. Character/model isolation is implemented; semantic quality remains model-dependent. Session Journal is a bounded summary, not a full transcript or medical recording. Permissioned retrieval can miss relevant history and lacks evidence for intervals it did not observe. Clearing or disabling access does not retroactively erase previously displayed dialogue.

Experimental Director idle initiative is off by default. It can generate narrative opportunities between events using cooldowns and repetition budgets. It may still repeat themes, interrupt immersion, misjudge relevance or overstate continuity. It controls dialogue only. Mocked regression checks do not establish long-running live-model conversational quality.

Character art is excluded pending rights evidence. Manifest references remain unchanged, so portraits are missing and existing fallback behavior applies. Asset-dependent checks are explicitly skipped where appropriate. Model definitions are unchanged; tags/digests and model license terms require verification at install time. Ownership/licensing of migrated AI source and character definitions needs confirmation before publication.

Fresh internet installation, fully running browser simulation, real-model inference and physical device behavior must be distinguished in VALIDATION.md. No claim of physical safety follows from automated tests. The JavaScript test dependency is locked in package-lock.json. Unpinned browser CDNs and mutable model tags still limit offline and bit-for-bit reproducibility. The exact local Python lock may be unavailable on other platforms or indexes.
