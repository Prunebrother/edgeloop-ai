# Release publication record

On 2026-10-29 the maintainer authorized the public repository and initial AGPL source publication. In the follow-up release request the maintainer confirmed project-generated art and authorized rebuilding the release to include artwork, open model weights and Ollama with minimal end-user setup. This authorization covers the complete local-app release and its GitHub assets. No public running application is hosted.

Use the repository-local Prunebrother identity and approved origin. Preserve public history; publish a new release commit/tag without rewriting the original source release. Never copy private Git history, runtime data, user keys or arbitrary developer model aliases.

1. Include exactly the manifest-referenced 48 portraits and public source. Preserve character lore/Modelfiles, original hardware logic, notices and upstream provenance.
2. Pin runtime inputs and model-weight hashes. Import only the public base-model manifests/blobs; rebuild character aliases from source. Keep all original license layers and notices.
3. Run source, installer, static privacy, browser/artwork and real local model checks. Validate an extracted bundle with network package indexes disabled. Record limits in VALIDATION.md.
4. Refresh reviewed upstream changes and public source manifest. Inspect staged paths/diff/identity and scan source/art metadata before committing. Keep private audit/build logs outside Git and release assets.
5. Build the complete bundle from the explicit source manifest, seal BUNDLE.json, split archive below GitHub's per-file limit, and generate SHA256SUMS. Publish matching source commit/tag and all assets, then verify the public commit and asset metadata.
6. Keep the original development checkout/model store untouched. Do not stop unrelated services or publish any pairing credentials or user history.
