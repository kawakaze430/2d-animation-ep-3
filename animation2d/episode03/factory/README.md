# Reusable 2D animation factory — production handoff

This is a data-driven architecture built over the EXISTING Episode03 Python renderer. The original screenplay, continuity ledger, dialogue, IK and pivot transforms, character rig loader, lip cues, camera, props, depth sorting, preview server and FFmpeg renderer remain intact. No new Python module should be needed for a new shot.

**Status:** the factory works in schematic blocking and has production asset/voice preflight, but a final SHOT_001 cannot yet be delivered: Dan, Maya and Nina still lack identity-matched transparent 15-part PNG rigs, suitable mouth and expression sprites, approved performance audio and creative QA. Reference JPEGs do not count as a rig.

## Source organization

- ../actions.py: one deterministic ActionMixer; named actions and layered clip sampling.
- ../kinematics.py: original two-bone IK, walking, wrist and sprite placement math.
- ../engine.py: original Python cutout compositor, actual PNG part rigs, per-actor speech cues, sorted props and camera.
- ../scene_factory.py: compile one JSON scene onto the immutable screenplay/cast/continuity, validate hand contact on prop releases.
- scenes/SHOT_001.json: first 15-second original Episode03 scene, with Maya, Dan, Nina action tracks and single-object attachments.
- templates.json: shared kitchen/table environments and named camera presets.
- ../factory_demo.py: THREE SEPARATE schematic scenes for DAN/MAYA/NINA, reusing identical reach/look/blink code.
- ../factory_render.py: content-hashed deterministic frame chunks, independent workers, checksum verification, FFmpeg MP4/QA reports.
- ../preview.py and ../web/: existing browser scene library, live scrubbing and action timeline chips.
- ../../../benchmark/godot/: real Godot 4.7.2 Sprite2D/AnimationPlayer vs Pillow renderer test with the same SYNTHETIC PNG artwork and exact shared poses; NOT final Episode03 artwork.
- ../../../.github/workflows/animation-factory.yml: manually dispatched six-way parallel frame rendering with cache.
- ../RIG_FORMAT.md: the authoritative production rig file and pivot contract.

## Reusable action API

One actor placement in a JSON scene:

    {
      "position": [960,650], "scale": 0.6, "depth": 100,
      "actions": [
        {"clip":"walk","start":0,"end":4,"target":[1200,650],"speed":1},
        {"clip":"talk","start":1,"end":5,"emotion":"curious"},
        {"clip":"reach","start":2,"end":3,"hand":"left",
         "target":[1130,580],"weight":1,"blend":0.1,"hold_last":true},
        {"clip":"look","start":0,"end":10,"degrees":-7},
        {"clip":"blink","start":4,"end":4.2}
      ]
    }

Action names (and alias spellings) are defined in ../actions.py:
idle, walk, run, sit, talk, blink, look, reach, hold, pick_up,
put_down, carry, pour, stir, eat, react, gesture.

Parameters: start/end are shot-local seconds; target/targets use world pixels (X right, Y down); hand is left/right; speed determines progression; weight (0–1) and blend set contribution/fade; priority orders competing clips; hold_last maintains a final grip; emotion selects intent. A legacy singular action entry still works. Motion is stateless: sampling the same time returns the same pose, including in parallel chunk jobs.

Current limitations: several manipulation clips reuse reach IK plus simple periodic movement; they are functional action primitives, not a large authored acting library. look rotates the head but needs distinct pupil artwork/eye rig for full eye acting. Expressive production visemes, blink and emotions require matching authored face sprite images. The object parameter is semantic only; use world-coordinate target plus prop interaction to establish contact. No claim of cinematic motion quality follows from a CI test.

## Rig JSON: one rig per character, reused by every shot

See ../RIG_FORMAT.md. A version-1 rig contains 15 required anatomical bones (head, torso, pelvis plus 6 left/right segments: upper_arm, forearm, hand, thigh, shin, foot) with transparent, genuinely visible PNG layers. Each part records bone, file, pivot, optional source_end, mirror and depth. Additional authored head sprites provide X/A–H mouth poses and optional blinking. No JPEG reference is substituted for production art. Rig path is stored once in characters[ACTOR].rig; all shots reference the same art.

The existing engine validates missing/invalid sprites and lip cues; production_readiness() fails closed on incomplete rigs. For future story characters, configure distinct art and voice entries; the old six-actor voice synthesis configuration is not itself a generic casting interface.

## Scene JSON: one file per shot, never one Python file per shot

Example top-level scene:

    {
      "version": 1,
      "shot": "SHOT_001",
      "environment": "home_kitchen",
      "camera": "three_shot",
      "actors": {"DAN": {"position":[960,650], "scale":0.6,
                          "actions":[{"clip":"gesture","start":2,"end":6,"target":[1030,570]}]}},
      "props": []
    }

Real SHOT_001 additionally includes Maya, Nina and their prop releases; use scenes/SHOT_001.json as the example. For existing Episode03 shots, dialogue, cast and story continuity are immutable: compiler only changes staging. For an entirely new episode, supply a separate story manifest with new actor definitions and dialogue, and set new_story=true in its JSON scene.

Camera templates are in templates.json. Scene coordinates are on a 1920x1080 world canvas; pelvis is actor position, and output camera center/zoom is applied AFTER composition.

## Hand attachment and depth ordering

Modern prop interaction:

    {
      "id":"blue_bowl", "position":[1120,650],"depth":204,
      "interaction":{
        "actor":"NINA","hand":"left",
        "attach_at":0,"release_at":2.5,
        "offset":[0,0],"landing":[1120,650],
        "contact_tolerance":24
      }
    }

The SAME object is visible before attachment, follows the solved/clamped wrist when attached, then rests at landing. scene_factory validates release contact and rejects teleporting objects. Legacy attachment fields remain supported. Actors, props and foreground PNGs are rendered by ascending depth, with insertion order tie-breaks. Current depth is actor/prop-level: finger-over-object occlusion and nuanced physical interactions still need art passes and creative review.

## Commands from repository root

    python -m animation2d.episode03.manifest --check
    python -m unittest discover -s tests -p 'test_*.py'
    python -m animation2d.episode03.scene_factory --scene animation2d/episode03/factory/scenes/SHOT_001.json --output build/factory/scene.json
    python -m animation2d.episode03.preview --manifest build/factory/scene.json

    python -m animation2d.episode03.factory_demo --output build/factory/demo.json
    python -m animation2d.episode03.preview --manifest build/factory/demo.json

    python -m animation2d.episode03.factory_render prepare --manifest build/factory/scene.json --mode blocking
    python -m animation2d.episode03.factory_render chunk --manifest build/factory/scene.json --mode blocking --start 0 --count 60 --output build/factory/chunks/part_0
    # Parallel chunks: starts 60, 120, 180, 240, 300, each count 60.
    python -m animation2d.episode03.factory_render assemble --manifest build/factory/scene.json --mode blocking --chunks build/factory/chunks --output build/factory/final

The GitHub workflow has six independently cached 60-frame jobs and a final FFmpeg assembly. Production requires approved transparent part rigs, narration.wav and lip cue JSON files; changing the source manifest/actor rig PNG/cues invalidates cached frames. All output is validated at 24fps x 15s x 360 frames, and production MP4s require creative approval beyond technical QA.

The live browser preview can select actors and click their action chips; local frame scrubbing is real Python rendering. The portable static pack contains sample images, NOT a video or continuous animation.

## Renderer migration gate

Godot PoC: same deterministic 15-part synthetic transparent PNG sprites + exactly the same Python-solved 360 IK poses + Godot AnimationPlayer with command-line Movie Writer. The test verifies identical inputs, non-static output and sample pixel differences. It isolates sprite renderer cost and does not separately benchmark Godot IK, original voice/lip sync, artist hours or authentic Episode03 art.

Keep the Python renderer unless a real SHOT_001 A/B with approved art, audio and independent human quality sign-off establishes a significant improvement in overall production work, visual quality or runtime. The prior Rigby2D comparison is also only a synthetic headless-export smoke test until original art is available.

## Episode03 SHOT_001 creative acceptance gate

- Authentic reusable transparent Dan/Maya/Nina rigs and facial assets; real original-character identity.
- Correct Maya recipe-card transfer, Nina cobalt bowl transfer and Dan gestures, with no hand/prop teleport or occlusion failure.
- Exact original spoken words for all three actors, accepted 15s narration, ordered mouth cues and dialogue subtitles.
- 1920x1080, 24fps, 360 frames; FFmpeg full decode, frame integrity and audio/continuity checks.
- Human acting, eye expressions, lip sync, compositing and story QA approval.
- No rendered blocking stick figures or generic rig fixtures represented as the finished episode.

The root SOUND_GUIDE_KOKORO.txt describes a *different repository's* Vegetable Adventure ONNX voice pipeline, not an already-integrated Episode03 sound implementation.
