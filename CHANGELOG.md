# Changelog

## v0.4.0 — companion conversation update

- Four current companions: Nova, Evelyn, Daisy and Celeste, rebuilt with revised character prompts. Nova is the default for new installs; existing selections of older models need choosing again.
- The Director card deck is on by default: companions occasionally bring in a short story or character moment. There is no settings switch yet; it can be turned off per companion in `deck-settings.json` in the data folder.
- Story Memory now keeps what the participant said and no longer stores the companion's own lines, which reduces repeated phrasing. Only the participant's previous message is replayed, as background.
- Reply cleanup: removes a restatement of your message at the start of a reply, unwraps quoted replies, drops stage narration between quoted speech and caps reply length.
- Smaller download (about 9 GB): a single base model (qwen3.5 9B). The qwen3 8B weights are no longer included.

## F2.10 — public release preparation (unpublished)

Separate source snapshot, privacy exclusions, public documentation and issue templates. No private Git history, model weights, private sessions or character artwork is included. Upstream licensing and acknowledgments are retained. Publication remains gated by validation and provenance findings.

## F2.8 series — context and memory

Context compilation and budgets, narrative objectives, durable sourced facts, character-scoped Story Memory, opt-in Session Journal and permission-controlled historical retrieval. Significant-memory extraction and experimental Director initiative have current working-tree regression coverage; live quality remains under evaluation.

## F2.2–F2.7 — local companion

Self-contained read-only observer, local Ollama integration, streamed conversation, model selection, bounded Director scheduling, event intelligence, grounding safeguards, character menus and expression presentation, launcher and pairing support. Thinking remains disabled.

## Original EdgeLoop 1.1.3

Inherited browser engine, device drivers, physiological calculations, session rules, protections and manual controls. See the preserved [upstream changelog](docs/upstream/CHANGELOG.md) and [attribution](NOTICE_FORK.md). Historical upstream release claims are not new validation of this fork.
