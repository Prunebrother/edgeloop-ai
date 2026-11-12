# Changelog

## v0.9.0-rc1 — test build: meet Mira, animated portraits (pre-release)

<!-- Release candidate for play-testing. Linux and Windows. Same as v0.8.0-rc1 plus the changes below. New model: mira-narrative-v1; the other companions' models are unchanged. -->

- New companion: Mira (HELIX-MORPH/09), a shapeshifting synthetic sent by Helix with her own agenda. She has her own personality, twelve portraits, fifteen personal cards and the common deck, like the other companions. She is brand new: tell us how she plays.
- Animated portraits: every companion's portrait now breathes, shifts its weight and blinks, with one loop per expression. If your system is set to reduce motion, the still portraits are shown instead.
- Companions now talk at their own temperature, as set in their model: Nova 0.75, Celeste and Mira 0.7, Evelyn and Daisy 0.6. Before, the app forced 0.4 on all of them. In our tests they repeat themselves far less (repeated phrases down 70 to 100%) and echo you less often.
- Character Builder: new characters draw from the common deck, shuffled together with their own cards, as the built-in companions do. Characters you made earlier keep their setting: open them in the Character Builder and choose "Common deck and own cards" under Shared cards to switch.
- The common deck no longer tells a companion how to feel (tease, marvel, be impressed). It says what to react to, and each character reacts in their own way.

## v0.8.0-rc1 — test build: multiple orgasms, I came button, smarter companions (pre-release)

<!-- Release candidate for testers on the dev repository. Linux and Windows. Same as v0.7.0-rc3 plus the changes below. Models are unchanged since v0.6.0-rc2. -->

- I came: a new button (keyboard C) to report an orgasm at any point of a running session, with or without Force Orgasm. It counts the orgasm, eases the toys down and starts the warm-up again (Survival restarts its climb); the session keeps going. When paused, it counts and resets but stays paused until you press Resume. A double tap counts once. Came Early is for accidents only again.
- Several orgasms per session: History and the Session Journal show how many. Companions react to each one, know this session's count and, if they may read the Journal, your total with them.
- After an orgasm: a recovery period, then the companion starts the next round on its own. With AI Settings Control on, it may change a setting for that round and says what it changed. Two new sliders in AI Settings: Recovery (30 s to 5 min, default 90 s) and how long the companion may not turn Force Orgasm on by itself (0 to 10 min, default 3 min). You can always ask for it sooner.
- Asking to cum again after an earlier orgasm now turns Force Orgasm back on.
- Companions' cards follow the finish: once Force Orgasm is on, they stop talking about the next edges.
- Calibration's Finished me now counts as an orgasm.
- Rewritten session rules for the companions (system prompt v2): no more contradictions with AI Settings Control, less repetition, and they claim a settings change only once EdgeLoop has made it.
- Fixed: a reply that opened by quoting your message could be cut down to just that quote, or lose its real answer. More expression names are understood, so fewer replies fall back to the neutral portrait.
- Fixed: a round change was not announced when spontaneous commentary was off.

## v0.7.0-rc3 — test build: review fixes (pre-release)

<!-- Release candidate for testers on the dev repository. Linux and Windows. Same as v0.7.0-rc2 plus the fixes below. Models are unchanged since v0.6.0-rc2. -->

- Character Builder: pressing Save again before the previous save finished could bring back older card text and later save it. Saves now run one at a time; a second Save or Preview waits and then saves what is on screen.
- AI Settings Control: pressing Cancel while the companion was deciding on a settings change could still send that change and a reply afterwards. Cancel now stops both.
- If conversation history or Story Memory cannot be saved (for example, a full disk), the reply is still shown and spoken, and the diagnostics say what could not be saved. Before, the reply was lost and the companion stayed in its generating state.
- Optional local player app (`node app/host.mjs`, from the source only; not in the release downloads): it now serves only the app's public files, never private data or files outside its folder, and refuses requests from other sites or host names.

## v0.7.0-rc2 — test build: Character Builder fixes (pre-release)

<!-- Release candidate for testers on the dev repository. Linux and Windows. Same as v0.7.0-rc1 plus the fixes below. Models are unchanged since v0.6.0-rc2. -->

- Character Builder: card edits made after saving are now saved too. Before, a second edit to an existing card showed on screen but was silently dropped on the next save. Edits you make while a save is still in progress are kept.
- Event Intelligence settings: preferences for a custom character now show their saved values and can be saved. Before, any save of the event settings failed once a custom character's entry appeared.
- Reactivating a character you edited now uses its new and changed cards right away, not only after switching away or restarting. Its conversation memory is kept.

## v0.7.0-rc1 — test build: Character Builder (pre-release)

<!-- Release candidate for testers on the dev repository. Linux and Windows. Includes everything in v0.6.0-rc3. Models are unchanged since v0.6.0-rc2. -->

- Character Builder: create your own world and companion on this computer. You write the setting, lore, ground rules, name, personality, voice and relationship, choose a portrait, and write up to 16 Character Cards for the Director to deal.
  - It opens in its own workspace from the model picker. "Back to chat" returns you to the same conversation and the same active character.
  - Saving checks everything first and lists each problem by field. A preview shows the persona, the deck, theme weights and the portrait before you activate.
  - The custom persona replaces the model's built-in identity in every request, so no model rebuild is needed and the built-in companion never speaks under the new name.
  - Each custom character has its own conversation history, Story Memory, deck settings and Session Journal. Switching back to a built-in companion through the model picker restores it unchanged.
  - Cards are dialogue only. A card that asks for a speed, setting, device or session change, or mentions the emergency stop, is refused. Session controls and the emergency stop stay with EdgeLoop.
  - The shared start, closing, arrival and milestone cards still play for custom characters.
- AI Settings Control is off for each new custom character, even when it is on for the built-in companions. Turning it on applies to that character only, and switching characters restores each one's own choice.
- Event preferences have a separate entry for each custom character, starting at normal defaults, so a custom character on a built-in companion's model does not inherit that companion's preferences.
- Limits shown in the builder: the card count (up to 16) and the size of each save (up to 16 KiB). An oversize save is refused with an explanation and nothing is written.
- Portraits are added by placing an image (PNG, JPEG or WebP, up to 8 MB) in the art folder the builder shows. One portrait is used for every expression. Portraits are served only to this computer, and only after they pass the image check.
- Not yet included: a set of portraits for different expressions, uploading a portrait directly, and builder controls for heart-rate and story conditions. Conditions written in a character file are kept when the deck is opened and saved in the builder.

## v0.6.0-rc3 — Windows installer recovery fixes (pre-release)

Windows-only packaging update. Models and application behavior are unchanged; the Linux download remains v0.6.0-rc2.

- Windows setup restores the working backup before retrying an interrupted repair, and rolls back if Python preparation or settings configuration fails.
- Previous installations and downloaded parts are kept until Windows setup finishes installing shortcuts and uninstall information. Interrupted cleanup cannot turn a partially deleted backup into a recovery target.
- Truncated Windows downloads retain their partial files and resume on retry. Resumed responses are checked before data is appended.

## v0.6.0-rc2 — test build with Windows installer (pre-release)

<!-- Release candidate for testers, published on the dev repository only. Hardware testing is still to do; v0.5.0 was never released and is folded into this version. -->

- **Windows installer (experimental).** `EdgeLoop-AI-Setup-v0.6.0-rc2.exe` installs the complete app for one Windows user without administrator rights: the same companions, model, Ollama (with NVIDIA CUDA support) and portable Python as the Linux bundle. Start menu shortcuts start and stop the local services; uninstalling keeps your data. Tested on Windows without a GPU or toys; real-hardware testing is still to do. The setup program is not code-signed yet. See INSTALL.md.
- On Windows, the observer and web server claim their ports exclusively, and the web server refuses Windows-style backslash and colon paths.
- Otherwise identical to v0.6.0-rc1, below.

## v0.6.0-rc1 — test build (pre-release)

- **AI Settings Control (new, off by default).** When you turn it on in the *AI Settings Control* panel, the companion may change a few session settings itself, in character: play style, game, endgame, the orgasm toggle, intensity inside a band you set, and pause or stop. Every request passes a local gate (allowlist, your limits, rate limits, a fresh heart-rate signal and a ready toy) and then goes through the same path as the on-page controls. Each change shows a chip with Undo and is announced by the companion with a short in-character card. *Own changes* sets how often the companion may change something on its own initiative (Never, Rarely, Sometimes (default, at most every 5 minutes) or Often); changes you ask for in chat are not held back by it. The companion can never start or resume a session, reset it, change the duration, heart-rate limits, calibration, devices or the speed window. Emergency stop revokes AI control for the rest of the session. See SAFETY.md.
- **Player interactions.** The companion reacts when you open the video player, select a video or start it, through the same Director queue as other events.
- **Player workspace.** The video player moved to the centre column, with Close player, a fixed Theater mode and an Emergency stop inside the player stage, so it stays reachable in Theater and Fullscreen.
- Fix: UI files are always revalidated, so an old cached stylesheet can no longer break the dashboard layout (for example the chat not scrolling) after an update.
- Fix: the companion service restarts cleanly even when the previous run's port is still closing.
- Built on EdgeLoop 1.1.4.31 (previously 1.1.3). New in the original app:
  - a video player that can follow a funscript, with Theater and Fullscreen
  - the Bratty Tease play style
  - an Edged button that pauses and counts an edge
  - adjustable Crawl speed
  - Finisher holds at the heart rate you set
  - No Nut November (renamed from NNN practice), with a midnight day roll
  - an opt-in session log you can download from History
  - updated drivers for The Handy, Intiface/Lovense and T-Code
  - a warning when EdgeLoop is not the focused window
  - Play Style and Session Endgame as compact cards
- The companion follows the new page layout.
- Companions now see Bratty Tease and video/script sessions, and the new card names (Simple Ramp, Ruin & Leak, No Nut November and others).
- Companions can tell why a session is paused. An Edged stop counts as an edge, not a pause, so it is not described as a break.
- Character Card expansion: 48 companion Character Cards, twelve each for Nova, Daisy, Evelyn and Celeste, alongside the 19 Common Cards. The Director deals them as before.
- Earlier conversation reaches a card prompt as background, separate from the card's own instruction, so companions are less likely to answer an old message again.
- Not included: upstream's agent link (AI control through a share link) and starting without a heart-rate sensor. The heart-rate requirement is unchanged.

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
