# Synthetic portrait decoder fixtures

These clips contain only FFmpeg's procedural `testsrc2` pattern: 64×96, 10 FPS,
0.6 seconds, six frames, no audio. They are test data, not character artwork or
production animation. No model, person, source portrait or external footage was
used. They follow this repository's AGPL-3.0-only test-fixture licensing.

Reproduce with FFmpeg (encoder version can change bytes):

```sh
ffmpeg -f lavfi -i testsrc2=size=64x96:rate=10 -t 0.6 -an -c:v libvpx-vp9 -b:v 40k idle.webm
ffmpeg -f lavfi -i testsrc2=size=64x96:rate=10 -t 0.6 -an -c:v libx264 -profile:v baseline -level:v 3.0 -pix_fmt yuv420p -movflags +faststart idle.mp4
```

The Playwright fixture intercepts declared test URLs and serves these bytes;
neither clip is listed in the runtime character catalog or exposed by the normal
character-art allowlist. All missing/corrupt-video cases are synthetic responses.
