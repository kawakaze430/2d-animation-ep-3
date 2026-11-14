# Source audit: PySpine v2, pygame-ce, Skia-Python, Pymunk

Audit of actual source (not package names): [SaxonRah/PySpine at 6c32bfc](https://github.com/SaxonRah/PySpine/tree/6c32bfc50fcdf4f94bfe066e23a9486f1abac0c7/PySpine_v2).

**We studied upstream design but did not copy PySpine implementation code or artwork.** Our new Python modules are independent implementations on the already-tested Episode03 rig/IK and Pillow pipeline. PySpine MIT copyright (c) 2025 Robert Valentine; the full upstream notice is retained in [PYSPINE_LICENSE_NOTICE.txt](PYSPINE_LICENSE_NOTICE.txt).

## PySpine v2 source findings

| Source | Actual behavior | Decision |
| --- | --- | --- |
| [core/model.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/core/model.py) | SpriteSheet crops, normalized AttachmentPoint, Instance parent/self named points, hierarchy, Clip tracks and keys | Preserve our individual 15-part PNG rig contract; do not silently import a mismatched sprite sheet. Add actor-independent clip data. |
| [core/solver.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/core/solver.py) | Topological parent-before-child transforms, fixed attachment pivots, z, valid sprite swaps, opt-in breakable attachments | Keep original anatomical endpoints and source_end; add solved-joint continuity tests. No unreviewed automatic sprite swapping. |
| [core/animation.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/core/animation.py) | Time-sampled keyed channels; step sprite/visible/break tracks; linear/eased numeric tracks and looping | Independently implement named local-space keyframed motion clips and pose presets with smooth/linear/step interpolation. Continue using shared ActionMixer and IK. |
| [core/ik.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/core/ik.py) | Screen-space planar two-bone IK with reachability and bend direction | Retain proven Episode03 reach-clamped kinematics.py IK, no duplication. |
| [editor/animation_quality.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/editor/animation_quality.py) | CCD full-chain keyframing helper; named pose operations, onion skin and motion arcs; foot-lock helper that keys root x/y to retain a planted point | Use the foot-plant and posing ideas in new diagnostics and motion tracks; no GUI port or entire CCD solver migration now. |
| [core/motion.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/core/motion.py) | Detects low-velocity planted ranges from sampled motion arcs; itself does not fix sliding | Our quality.py inspects the ankle AFTER the authoritative IK solution and quantifies actual stance sliding. |
| [runtime/renderer_pillow.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/runtime/renderer_pillow.py) | Headless Pillow cutout exporter independent from pygame editor | Episode03 Pillow and FFmpeg already provide a proven headless pipeline, retain it. |
| [exporting/frames.py](https://github.com/SaxonRah/PySpine/blob/main/PySpine_v2/pyspine/exporting/frames.py) | Fixed-bound clip PNG frames, PNG strips and GIF previews | Keep our frame-keyed incremental and parallel rendering and browser/MP4 review. |

PySpine's included PySpineGuy sprite sheet and Aseprite art are not the Dan/Maya/Nina production rigs. No automatic replacement or source-art repackaging is claimed. Its README refers to tests, but the inspected repository tree did not include a corresponding v2 tests directory.

## Licensing and alternative libraries

| Library | Verified upstream license | Scope and decision |
| --- | --- | --- |
| [PySpine v2](https://github.com/SaxonRah/PySpine/blob/main/LICENSE) | MIT, Robert Valentine 2025 | Design inspiration; original code written separately; full notice retained. |
| [pygame-ce](https://github.com/pygame-community/pygame-ce) | LGPL v2.1 as declared in pyproject.toml; stable [2.5.8](https://github.com/pygame-community/pygame-ce/releases/tag/2.5.8) dated 2026-08-09 | Optional pinned SDL sprite backend for same-shot comparison; no source vendored. Distribution must comply with LGPL terms. |
| [skia-python](https://github.com/skia-python/skia-python/blob/main/LICENSE) | BSD 3-Clause, Kota Yamaguchi 2020 | Alternative CPU/GPU vector raster, higher integration cost. No migration or copied source. |
| [pymunk](https://github.com/viblo/pymunk/blob/master/LICENSE.txt) | MIT, Victor Blomqvist 2007–2026 | Useful optional physics for secondary props, not a replacement for art-directed character clips. |

Dependency licenses do not automatically grant rights to other artwork and code. Before redistributing packaged third-party runtimes, review their licenses and transitives.

## Actual Episode03 gaps identified

- The existing ActionMixer has procedural action intents but lacked named, reusable, explicitly keyed skeletal clip data and named pose presets. motion_clips.py and clip_library.json now address this without new character-specific Python.
- The compiler previously validated modern JSON prop interaction, but render_frame ignored it, leaving a static item. That bug is fixed, retaining legacy attachment. A single item follows the hand and remains at the authored release location.
- Walking target was world-space planted in walk_foot, but a fully extended leg could make two-bone IK clamp the ankle and generate visible sliding. New modern-scene foot_lock reserves knee reach; legacy unchanged. quality.py tests the actual solved ankle.
- JSON camera presets were static; camera_clips.py now supports pan/zoom/roll with validated time tracks.
- Source file and named pose changes now invalidate cached frames in factory_render.py.

## Benchmark validity and migration

Required production A/B: same approved Dan/Maya/Nina 15-part PNG rigs plus authored mouth/eye sprites, same original screenplay and approved audio, SHOT_001, 1920x1080, 24fps, 360 frames, same scene, props, camera and FFmpeg flags. The optional pygame backend and compare.py enforce source/audio checksums, frame count, validation and per-sample image difference reports.

**Current blocker:** the original-character transparent part rigs and approved dialogue performances are not in the project repository. Production mode fails closed; no synthetic cutouts can be substituted and called production-ready. A full SHOT_001 SCHEMATIC blocking benchmark may still run with the repository's actual kitchen environment image. It is a backend diagnostic, NOT a creative quality, production-art or cost comparison.

The Pygame prototype deliberately shares Pillow camera cropping and vector-prop source generation and the existing Python IK, so its performance results measure a partial renderer alternative, not a full independent animation engine. Reported Python RSS excludes the FFmpeg subprocess. Human rigging/acting hours and visual sign-off remain unknown. **Keep Pillow/FFmpeg unless an authentic paired production render establishes a significant, reviewed benefit.**

## Source files checked

Episode03: actions.py, engine.py, kinematics.py, scene_factory.py, state.py, factory_render.py, preview.py, voice.py, factory/scenes/SHOT_001.json, RIG_FORMAT.md, tests/test_episode03_engine.py. New work: motion_clips.py, camera_clips.py, quality.py, factory/clip_library.json, tests/test_motion_clips.py, benchmark/pygame/ and .github/workflows/pygame-benchmark.yml.
