# Campaign save matrix

Regenerate with `python3 tests/ai/fixtures/campaign_progress/make_fixtures.py` from the repository root. The generator only writes this fixture directory (or `--output-dir`); timestamps are fixed. Mission ids and earned rewards come from the shipped Asterion definition, never from a live save.

Each of v1, v2 and v3 has fresh, mid-Ch3 (missions 1–11 completed, Mission 12 active), Ch3-done (missions 1–14 completed), and malformed fixtures. V1 has a wrong completion count type; v2 has an unknown record key; v3 is truncated JSON.

Hand checks against the historical migration code:

- **v1-mid-ch3:** has missions, rewards, completion marker and records, but no chapters, flags, solved puzzles, choices or routes. `_v1_to_v2` clears completion markers/rewards and adds chapters; `_v2_to_v3` clears the old campaign completion again and adds flags. The service reconstructs chapter rewards from completed missions. The original records, non-completion rewards, mission timestamps and active Mission 12 survive.
- **v2-ch3-done:** has chapters but no flags or solved-puzzle fields. `_v2_to_v3` resets the legacy completion marker/rewards; the service reconstructs the same three completed chapters and campaign completion from Mission 14. Existing chapter timestamps survive.
- **v3-partial-puzzles:** has flags and saved puzzle progress, but no choices or routes. `_v3_to_v4` adds only those two empty maps. Mission 14 remains active with `log` and `money` solved. This extra fixture is necessary because the matrix's active Mission 12 has no puzzles.

The v1/v2 Ch3 fixtures deliberately put later mission ids into their old storage formats: they test migration compatibility rather than claim those missions shipped with those builds. No mission text is included.

`v4-round-trip.json` uses SettingsStore's canonical indentation, field order and trailing newline. Loading and saving an unchanged Progress must preserve its bytes. Arbitrary user formatting is not promised to survive a save.
