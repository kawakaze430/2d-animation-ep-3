# Delivery status

The selected implementation is the repository's Python 2D cutout pipeline.
All source, reference artwork and generated dialogue data are pushed to this
repository. Generated movies and browser review packs are GitHub Actions artifacts.

| Item | Finished | Still needs review or work |
| --- | --- | --- |
| Artwork | 14 cast references, 5 environment previews, 20 storyboard sheets and editable SVGs preserved | Six separated transparent character rigs, facial sprites and foreground masks |
| Dialogue | All 240 exact screenplay turns committed in the 80-shot manifest | Accepted performed timing and final voice casting |
| Animation code | Independent actors, IK/walking, camera, hand attachments, depth ordering, source validation and persistent cooking state | Detailed acting; most shots deliberately retain idle blocking defaults |
| Voices/lip sync | Six-preset Kokoro backend, separate actor tracks/cues, speaker isolation and cache checks | Actual synthesis and performance acceptance; presets are provisional |
| Browser review | 80-shot gallery, filters, reference images, state inspection and scrubbing; tested in Chromium | Creator acceptance; static packs contain three samples per shot |
| Episode 03 video | 15-second **silent schematic blocking** export succeeded on GitHub | Final character likeness, natural acting, voices, props and finished movie |
| Original toolchain sample | 15-second original painted-character sample with supplied narration succeeded on GitHub | A sample of the original lesson is not Episode 03 |
| Rigby2D comparison | Repository baseline and comparison workflow prepared | Exact Rigby2D product/link required; no installation or head-to-head winner claimed |

The successful [Episode 03 preview run](https://github.com/kawakaze430/2d-animation-ep-3/actions/runs/43631213416)
contains the MP4, browser gallery, source dialogue/state, media checks and logs.
Its artifact is `Episode03-SHOT_001-blocking-43631213416`. It is explicitly
schematic and silent, not an approved performed scene.

The [repository-baseline workflow](https://github.com/kawakaze430/2d-animation-ep-3/actions/workflows/comparison-baseline.yml)
uses the original painted woman and supplied narration. That is a working
toolchain/style sample; a fair comparison with another tool must use matched
characters, dialogue, camera, resolution and shot actions. An unidentified product
must not be represented by a still-image camera move or unrelated substitute.

The [successful original-renderer baseline run](https://github.com/kawakaze430/2d-animation-ep-3/actions/runs/43631893213)
exports 15 seconds / 360 frames at 1920×1080 with supplied narration, an editable
project ZIP and media checks. Its artifact is
`2D-original-included-preview15-43631893213`. A real Actions run exposed an SRT cue
ending at 15.239 seconds; export now clips subtitle packets at the selected end,
and a regression test verifies exact container duration. Timing checks remain strict.

Source revision `13ea1d5` passed [GitHub CI on main](https://github.com/kawakaze430/2d-animation-ep-3/actions/runs/43631891392)
under Python 3.11 and 3.12. Locally, all 60 repository tests and 19 original
renderer tests passed. Full Episode 03 production and fresh Kokoro performances
are still unreviewed. The provisional technical choice is to retain the verified
repository pipeline until the alternative tool can be identified and tested.

Run **Episode 03 browser review and shot preview** manually for a selected shot.
Pushes to `work` touching its source generate silent blocking review automatically.
Choose Kokoro to synthesize provisional voices on the runner; production mode
rejects missing real artwork rather than silently exporting schematics.
