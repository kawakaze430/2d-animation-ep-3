# Reproducible Godot vs Python renderer proof

This experiment is intentionally **small and truthful**. It is not a second production-quality Episode 03 shot. Existing original JPEG character references cannot be used as interchangeable rig layers: the real 15-part PNG rigs and matching viseme sprites for Maya, Dan and Nina are still missing.

**Hypothesis:** Godot 4.7.2's Sprite2D / AnimationPlayer / command-line Movie Writer may be a useful alternative rasterizer to the already-working Python Pillow 2D renderer. We will not replace the Python factory based on a small synthetic test alone.

## Precisely matched inputs

1. Run \`benchmark.py prepare\` once. It deterministically generates **15 transparent PNG bone sprites**. Neither renderer has privileged art assets: both load the same files, including identical hashes of every sprite.
2. The fixture has one visible DAN actor and the same 15-second, 24 FPS, 960×540 timeline. \`Actor.pose\` samples exactly one action stack (\`reach\`, \`look\`, \`blink\`) at all 360 times. It exports each sprite's position, rotation and scale as \`motion.json\`.
3. Python \`engine.render_frame(mode="production")\` composes those 15 same sprites into RGB PNGs. This exercises the **real Pillow cutout renderer**, not the blocking stick figures; the illustration itself is visibly synthetic and not production-approved.
4. Godot 4.7.2 creates 15 \`Sprite2D\` nodes, loads those exact same PNGs directly from disk, and uses a reusable \`AnimationPlayer\` clip to seek the exported keyframes. Godot **does not independently solve IK** in this test; it shares the computed action poses to isolate rendering/backend cost. Godot Movie Writer outputs the 360 PNG frames in fixed-FPS offline mode.
5. The report checks the number and dimensions of PNGs, multiple distinct frame hashes, original artwork hashes, action-pose checksum and five sampled per-pixel difference scores. Pixel-perfect matching is NOT expected: Pillow and Godot have different resamplers.
6. The test measures \`wall_s\` for **rendering + PNG encoding**. Python time excludes fixture preparation; Godot time excludes initial download and includes the Xvfb launcher. Use GitHub runner logs to compare the hardware, and do not infer an end-to-end production-effort winner from the measurements. Neither TTS, lip-sync authoring, quality of original art, artist hours nor complete shots are included.

### Reproduce locally (Linux)

Requires Python 3.11+, NumPy, Pillow, FFmpeg and Godot 4.7.2; for headless Linux CI also requires Xvfb + OpenGL/Mesa.

\`\`\`sh
python -m pip install -r animation2d/project/requirements.txt
python benchmark/godot/benchmark.py prepare --output build/godot-bench
python benchmark/godot/benchmark.py python --output build/godot-bench
mkdir -p build/godot-bench/godot
xvfb-run -a Godot_v4.7.2-stable_linux.x86_64 \
  --path benchmark/godot/godot \
  --rendering-method gl_compatibility \
  --write-movie "$PWD/build/godot-bench/godot/godot.png" \
  --fixed-fps 24 --quit-after 360 \
  -- --fixture="$PWD/build/godot-bench"
python benchmark/godot/benchmark.py report --output build/godot-bench
\`\`\`

Godot's official CLI Movie Writer supports \`--write-movie\`, \`--fixed-fps\`, and \`--quit-after\`. Giving the output a \`.png\` extension tells it to emit numbered lossless image frames (plus WAV), avoiding a fundamentally different codec in the raster benchmark; \`.avi\` would instead use MJPEG.

- [Official Movie Maker documentation](https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html)
- [Godot 4.7.2 stable release](https://godotengine.org/download/archive/4.7.2-stable/)

### Run in GitHub Actions

Open [Actions](https://github.com/kawakaze430/2d-animation-ep-3/actions) > **Godot vs Python fair renderer proof (synthetic artwork)**. The workflow is triggered on changes to this directory and supports manual dispatch. It checks the downloaded upstream Godot ZIP checksum before execution.

Artifacts: \`manifest.json\`, original 15 PNGs and rig JSON, \`motion.json\`, \`python_metrics.json\`, \`godot_metrics.json\`, \`report.json\`, \`REPORT.md\`, \`comparison_contact_sheet.png\`, stdout/stderr, and a few sample PNG frames from each engine. Full 360-frame sequences remain local to the benchmark job to reduce Actions artifact size. Both renderer sequences may be encoded to the same MP4 format independently, but output FPS/PNG-count and sample content are the primary verified measurements.

### Decision policy

**Keep the Python factory for current production.** Reevaluate any Godot migration only after a full SHOT_001 A/B with the **same approved character artwork, lip cue timing, dialogues, scene, props, lighting and camera**, plus recorded artist hours, rendering time, memory, audio/video QA, visual comparisons and creative sign-off.

This small PoC demonstrates Godot's reusability and CLI movie output without risking a costly rewrite. It does not measure full Godot rig IK or prove that Godot has better character animation.
