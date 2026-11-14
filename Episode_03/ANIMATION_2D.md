# Episode 03: Python 2D production handoff

The selected production method is generated character/background artwork →
Python cutout animation → Kokoro speech and Rhubarb mouth cues → FFmpeg MP4.
The reusable implementation lives in [animation2d](../animation2d/README.md).
The Blender experiment was discarded; no Blender project is part of this pipeline.

The existing renderer is a working original English-teaching film, with a single
painted character, articulated limbs, two-bone arm IK, walking, expressions,
attached props, camera movement, captions, and mastered narration. Its supplied
audio and mouth cues permit a render without downloading voice models.

That original film is a pipeline reference, not Episode 03. The six Brooks family
members retain the identities, clothing, ages, and relationships in
[CONTINUITY.md](CONTINUITY.md). The [character JPGs](assets/characters/) are
reference sheets, not transparent animation parts. Never substitute the original
woman for these six characters or relabel an original-project render as this story.

Before the first Episode 03 motion render:

1. Generate or prepare six reference-matched transparent part sets: head/face,
   torso, pelvis, upper/lower arms, hands, thighs, shins and shoes. Keep the
   source artwork, generation provenance and named joint anchors. Start with
   Maya, Dan and Nina for SHOT_001; Leo, Ella and Max join subsequent shots.
2. Parameterize the original renderer's per-actor art, anatomy, skin colors,
   face landmarks and expression/mouth layers. Preserve Dan's left-wrist watch.
3. Prepare a separate foreground island layer for correct hands/props occlusion
   against the shared kitchen background. The current kitchen JPG is a viewing
   reference, not a high-resolution production master.
4. Add manifest-driven 15-second shots and speaker-specific Kokoro voices and
   Rhubarb cues. The original teaching renderer uses 10-second vignettes and one
   voice; those assumptions must not silently govern this family story.
5. Stage SHOT_001's exact screenplay dialogue, recipe placement, empty cobalt
   bowl, empty shelf vase, stove OFF and three visible adults. Replace the old
   teaching/drill presentation with the story title and optional dialogue captions.

The new Episode 03 engine implements independent actors, separate voice/cue
tracks, data-driven shots, configurable camera/attachments/depth and a continuous
kitchen-state ledger. Its browser review gallery and dedicated GitHub Action can
export a labelled schematic blocking preview now. Production mode rejects missing
character-part rigs; those assets and detailed acting remain outstanding.

The original-film/Episode 02 render job remains separate. Read the
[Episode 03 pipeline guide](../animation2d/episode03/README.md) for the finished-code
versus production-review status, shot overrides and browser workflow.
