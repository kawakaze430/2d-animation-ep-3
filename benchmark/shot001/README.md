# Episode 03 SHOT_001 — matched render benchmark (development branch)

## Status and scope

**The repository's SHOT_001 is not production-ready.** Its Maya, Dan and Nina
JPG portraits/sheets are references, NOT transparent segmented 2D character
art. The three complete rigs listed in characters.json do not exist at present.
Consequently **neither genuine 15-second production MP4 nor a winning benchmark
has been produced**. This branch adds the *implementation and fail-closed
cloud workflow*; it does not falsely label the old 15-second schematic clip,
the Everyday English lesson or a reference-sheet pan as Version B.

Source of truth: animation2d/episode03/shots.json, SHOT_001.
Both versions use only Maya, Dan and Nina and the three *exact* screenplay lines:

- Maya: "Pancakes, just as promised."
- Dan: "I am ready to help. Sensible quantities, no size records."
- Nina: "Then breakfast has an excellent start."

Locked scene: 1920 x 1080, 24 fps, 15 seconds = 360 frames, one fixed
camera, kitchen source background, same recipes/bowls, SAME master narration
and per-actor mouth cues. No unrelated character or lesson footage.

## Headless Rigby2D feasibility — source verified

Rigby2D upstream: https://github.com/jaisurya-dev-art/rigby2d
Documentation: https://rigby2d.com/docs/mcp.html

Pinned reviewed upstream commit:
b1792f67896de7d30503ffc8340801699b73f08d (0.5.1 develop snapshot).

The official Node >=20 MCP server and its export_sprite_sheet handler call
buildSpriteSheet in src/editor/spritesheet.js. That function samples the real
Rigby2D animation state and Pose and draws each skeleton through
src/editor/raster.js (SoftRenderer). This does NOT require Tauri,
a local computer, a browser window or a GPU. Format "frames" writes
name/SHOT_001_000.png ... _359.png in transparent RGBA; unlike a still pan,
they are generated from keyed Rigby2D bones, slot attachments and speaking
head swaps. The source also explicitly rejects exporting a Rigby scene
via that particular tool: export individual actor rigs and compose the
scene afterwards with Python, as done here.

The official MCP handler is called from Node in rigby.mjs via createTools
and Workspace. This is the same handler the stdio MCP server dispatches,
not a replacement or Python-drawn imitation. Editable .rigby files with
source art are built using Rigby2D's own Skeleton, Animation and ZIP
libraries. Bounds and origin use the upstream framesBounds function.

A GitHub-hosted Linux runner is therefore a reasonable deployment target.
**End-to-end success on the full shot remains unverified** until authored
character part files and speech sprites are installed, and both jobs have
completed. An alternate browser/WebGL path may be compared only if the
official software-raster MCP export fails; it must not be silently substituted.

## What is intentionally unchanged

The existing Everyday English working renderer, its assets and its GitHub
render workflow have not been modified. The A implementation calls the
existing Episode 03 engine.render_frame in production mode (Pillow/NumPy IK).
The B implementation calls the SAME engine.render_frame for stage,
background, props, hand-attached objects and camera but replaces only the
actor draw with the output of Rigby2D's original RGBA sprite animation.

Rigby actors have an actual hierarchy of pelvis/torso/head,
shoulder/upper arm/forearm/hand, hip/thigh/shin/foot. The same source PNG
parts, pivots, Rhubarb cues and Python-authored action timing produce sparse
bone/face keys, then **Rigby interpolates and renders the character frames**
through its own rasterizer. This does not test Rigby AutoRig, mesh weights
or its UI workflow; those require a separate production study.

Both engines receive a **single** corrected SHOT_001 staging contract:
Maya reaches the recipe position by 2.0 s; Nina uses her LEFT hand and
moves within reachable distance to set the blue bowl by 2.5 s; Dan readies
his right hand during his line. This fixes source-blocking hand/contact
errors and is identical for A/B. The old manifest is not overwritten.
The same reference kitchen background is currently a low-resolution JPEG;
a production-quality master and island foreground may be needed to pass
creative approval.

## Cloud workflow

Open GitHub Actions > "Episode 03 SHOT_001 - fair A/B comparison" > Run workflow.

The manually-triggered top-level workflow:
1. Checks for real rigs FIRST, before downloading any large speech model.
   Missing art emits a preflight diagnostic artifact and blocks renders.
2. Generates a single narration.wav using the existing Kokoro and Rhubarb
   toolchain, and freezes speech data in the shared-master artifact.
3. Calls two separate reusable workflows in parallel:
   - shot001-python.yml generates the Python-only clip.
   - shot001-rigby.yml checks out pinned Rigby, builds three skeletal projects,
     exports REAL Rigby PNG frames using format=frames, composites and encodes.
4. Verifies that both videos are real, 360 frames, 15 s, H.264, AAC stereo,
   1920x1080 at 24 fps. Rejects unequal source art/audio hashes, differing
   encoding profiles or missing Rigby project/frame provenance.
5. Publishes a paired report **only if both variants passed**.

Expected artifact names:
- SHOT_001-Version-A with SHOT_001_Python_Only_15s.mp4
- SHOT_001-Version-B with SHOT_001_Python_Rigby2D_15s.mp4
- SHOT_001-Paired-Benchmark (JSON, Markdown)
- SHOT_001-preflight and shot001-shared-master

Version A/B artifacts also contain contact sheets, selected source and
SHA-256 manifests. Version B includes three editable .rigby project files.
Do not infer the files exist until a successful Actions run actually
reports them. Artifacts expire after 30 days.

## Artwork and acceptance gates

For each of MAYA/DAN/NINA, provide:
- Episode_03/assets/rigs/<ID>/rig.json with all 15 part bone roles.
- Transparent, correctly joint-pivoted PNG parts; approved face sprites for
  A-H Rhubarb visemes actually spoken; preserve Dan's wristwatch, actor
  wardrobe, faces, eyes, and the permanent cast reference likeness.
- Measured source rig-building person-hours, artist revisions and notes.
- Actual shared WAV and nonneutral cue files are generated once in Actions.

Follow animation2d/episode03/RIG_FORMAT.md. A complete file tree is
necessary but not sufficient: creator review must approve facial animation,
eye/blink behavior, shoulders/elbows, prop contact, lip-sync, and consistent
identity against the source reference sheets. A waveform, motion statistic,
CPU timer or passing CI job cannot make that creative decision.

## Measurements and cost comparison

On genuine output, benchmark.json in each variant records separate
scene-frame composition vs FFmpeg encoding wall time, MP4 bytes/SHA,
input identity and media validation. Rigby additionally records skeletal
project setup and *Rigby character frame export* time, engine commit and
per-actor project/frame evidence. /usr/bin/time -v captures process CPU,
elapsed time and peak RSS in artifact resource files. Runner start/end
timestamps are included; actual complete GitHub Actions elapsed time must
be measured from completed workflow job timestamps rather than guessed.

Human rig-building effort and voice/asset approval are NOT captured by
machine wall-clock timers. Add person-hours in the final study. Do not
multiply 15 s of animation by 80 without accounting for differing cast
coverage, art reuse, repeated takes, audio generation, QA and retries.
Both may fit GitHub-hosted runners, but the winner is unselected until
true output and manual matched-frame reviews exist.

Local validation (no film render):
    python -m unittest discover -s tests -p 'test_shot001_comparison.py' -v
    python -m benchmark.shot001.common --check-art-only

The latter is EXPECTED TO FAIL until the real artist-authored production rigs
have been added to this repository.
