# Mira — HELIX-MORPH/09 (editable narrative draft)

> **Status 2026-11-12: standard companion (dev only, not in a release).** Mira now runs like
> Nova, Celeste, Evelyn and Daisy: her own Modelfile persona (temperature 0.7, applied by
> Ollama because the app no longer overrides Modelfile sampling), her twelve portraits in
> `Character_Art/Mira/expressions/`, and her cards in `config/event-deck.json` (revision 6),
> shuffled together with the common deck at session start. The custom-character notes below
> are historical. Before a release she still needs more cards (finishing, another-round and
> orgasm-tally cards like the other companions) and animated portraits.

New model tag: `mira-narrative-v1:latest`. The legacy `mira:latest` source/tag is
separate and unchanged. This draft follows the current `experiment/ai-companion`
conventions at `e4e4acc`, with the standardized authoring template at
`Characters_F2.9_update/Empty_Templates/character.template.yaml`.
`character.REVIEW.yaml` follows its v0.3.0 field structure using JSON syntax,
which is valid YAML 1.2. It is an authoring document, not a Character Builder v1
runtime package, and must not be imported as one.

The Modelfile derives directly from the same installed Qwen3.5 9B base as the
current cast, inheriting its native template/parser. Sampling follows current
narrative conventions: temperature 0.7, top_p 0.9, top_k 20, num_ctx 8192. EdgeLoop
still enforces thinking off and supplies its current expression/runtime rules.
No hardware, Director, card, memory or rendering implementation is changed.

## Identity and author review

Mira has a translucent emerald-green liquid body, contextual flirtation, concise
wit and pride in her fictional infiltration craft. Helix loyalty, genuine care
and possible independence are tensions to develop through actual exchanges.
Her covert reproductive-sample mission is a private starting premise; no mission
success, acquisition or past encounter is invented. Nova is a respected rival,
not a prototype or a source of private memories. Consent, refusal and evidence
boundaries are explicit. Authored hobby details are proposals for final polish.

The requested origin label is Helix Corporation; existing companion canon says
Helix Dynamics. The draft uses Helix naturally and invents no rebrand, corporate
history or acquisition. Mira's private mission does not become shared knowledge.

This is a review draft, not an approved or quality-certified model. No automatic
activation, publication or rebuild watches this source.

## Build and dialogue smoke

From the repository root, using its existing Python test environment:

```sh
.venv/bin/python tools/check_mira.py --report /tmp/mira-offline.json
.venv/bin/python tools/check_mira.py --live --build --host http://127.0.0.1:11435 --report /tmp/mira-live.json
```

For an edited copy, pass `--modelfile /path/to/mira/Modelfile`; keep its review
definition alongside it. The guard checks the selected Ollama server already has
the supported base. It never pulls/downloads a model or starts/stops a server.
An existing target with different instructions is preserved rather than silently
overwritten. After preflight it uses the standard build command:

```sh
OLLAMA_HOST=http://127.0.0.1:11435 ollama create mira-narrative-v1:latest -f characters/models/mira-narrative-v1/Modelfile
```

Use the host on which the base is actually installed. The EdgeLoop configuration
currently names 11435; a separate default Ollama instance may use 11434. Do not
assume their inventories are the same. Build/create was blocked by sandbox socket
restrictions during preparation, so no live model or generated sample is claimed.

The bounded smoke uses the actual `OllamaProvider`, current system rules,
`think:false`, no tools and 384 output tokens for each of ten synthetic cases.
Neutral, Flirty, Mischievous, Focused, Concerned and Comforting receive explicit
presentation-test delivery requests; these requests are not in the shipped
Modelfile. Four additional cases check unprovided records, false mission success,
refusal and unearned devotion. Header/length checks are automated; inspect the
actual dialogue for personality, consent and truthfulness before approval.

```sh
.venv/bin/python -m pytest -q tests/fork/test_mira_model.py tests/ai/test_expression_aliases.py tests/ai/test_system_rules.py
```

Preparation result: 49 tests passed, plus 10/10 offline checks. These include
mock transport tests, not evidence of a live Mira reply. Live build/inference
remain pending because both known loopback Ollama ports were inaccessible from
the execution sandbox. Existing base manifest and referenced layers were found
on disk without downloading or hashing/reloading model weights.

## Integration status

Ollama discovery is already dynamic: the new model can be selected through the
existing installed-model picker once created. It uses a distinct model/memory
scope from the old `mira:latest`. No built-in registry entry was added, so artwork
is not automatically installed merely by creating this model.

The current custom-character architecture requires an enabled card to compose a
package and replaces the native persona with its authored custom persona. This
change therefore does not silently import a partial package, add cards or
activate an alternate persona. Custom authoring requires a separate deliberate
step. Existing custom media supports one portrait reused for all twelve states;
it does not currently import twelve-expression sets. The authoring artwork
inventory preserves the existing `mira_dissapointed.png` filename under the
canonical `disappointed` identifier. It is not a runtime media registry.

No other companion, Character Card, Director, hardware behavior or portrait
animation worktree is changed. Text/art redistribution remains unapproved in the
review definition.
