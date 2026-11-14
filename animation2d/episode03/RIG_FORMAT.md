# Episode 03 cutout rigs

`engine.py` reuses the original renderer's affine placement, reach-clamped two-bone IK, wrist limit and travel-driven walking math from `kinematics.py`. Each `Actor` owns its parts, placement, action and mouth cues. It does not import the original renderer or use its single woman as Episode 03 artwork.

The default `blocking` mode draws labeled schematic actors over an unchanged full reference background. It is staging, not character artwork. `production` mode requires real transparent PNG part rigs for every visible actor and rejects missing/incomplete artwork. The committed cast JPEGs remain references. No JPG is cut up, recolored or presented as a finished rig.

## Coordinate and timing contract

The world canvas is 1920 × 1080, X right and Y down. Actor `position` is its pelvis, not its feet. Default local neck is `[0,-195]` and feet are approximately 380 local pixels below the pelvis. At scale 0.65, a pelvis at Y=650 gives feet near Y=897. Character proportions should be authored in each rig rather than replaced by a uniform scale when production models are available.

Shot actions support `idle`, `reach`, `walk` and `gesture`. Action `start`/`end` and `target` control eased movement in shot-local seconds. `hand` is `left` or `right`; the names identify the authored anatomical hand, without automatic mirroring based on camera direction. Optional `targets` provides independent world targets for both hands. Targets are clamped to reachable bone lengths before attachments are evaluated. Body placement `lean` and action `wrist_rotation` are degrees.

`camera: {zoom: 1, center: [960,540]}` applies after composition. `camera_point()` maps world coordinates to exported pixels using the identical center/zoom convention. Actors and props sort by ascending `depth`; equal values retain declaration order. A `foreground` list accepts transparent PNG `file`, pixel `position`, and `depth` entries for island occlusion.

## Real production rig

Configure `characters.DAN.rig` (and the other cast IDs) as a repository-relative `rig.json` path. Every path in that rig's `parts` and `faces` stays inside its rig folder. Example structure:

```json
{
  "version": 1,
  "anchors": {
    "neck": [0,-195],
    "shoulder_left": [-48,-165], "shoulder_right": [48,-165],
    "hip_left": [-30,30], "hip_right": [30,30]
  },
  "lengths": {"upper_arm":135,"forearm":125,"thigh":180,"shin":170},
  "parts": [
    {"id":"head","bone":"head","file":"head.png","pivot":[112,212],"depth":30},
    {"id":"left_upper_arm","bone":"upper_arm.left","file":"upper_arm_left.png",
     "pivot":[37,12],"source_end":[27,155],"depth":10}
  ],
  "faces": {"B":"head_B.png","D":"head_D.png","X_blink":"head_X_blink.png"}
}
```

This example omits required parts for readability and deliberately fails the completeness check. A complete rig contains these 15 bones: `head`, `torso`, `pelvis`, and `upper_arm`, `forearm`, `hand`, `thigh`, `shin`, `foot` with both `.left` and `.right` suffixes. Reusing a sprite file for mirrored limbs is supported with `mirror: true`; pivots are mirrored with the sprite. Author separate art where watches, hair or clothing require asymmetry.

`pivot` is the source pixel that follows the bone start. `source_end` identifies the source pixel that follows the bone end; when provided, length is fitted to the solved bone. Without `source_end`, actor scale is retained and the local sprite-down axis follows the bone. Head, torso and pelvis default to the actor's down axis. Head pivots normally sit at the neck. Hands follow solved forearms and feet follow ankle endpoints. Every PNG needs a real alpha channel with both visible and transparent pixels. Production completeness establishes file structure and pose support, not artistic quality or creator acceptance.

Face entries are complete replacement head PNGs sharing the head pivot. Keys use Rhubarb mouth values `A`–`H`, `X` and optionally `_blink`, such as `D_blink`. Production preflight requires every non-`X` shape used in the actor's supplied cue file. A missing shape fails before rendering; the engine never silently substitutes a neutral head for speech. Blink art is optional and must be authored for actual blinking.

## Speech and attachments

Each actor reads its own `audio_dir/SHOT_001/DAN.cues.json` (and corresponding cast files), containing a Rhubarb `mouthCues` list with `{start,end,value}`. Times are local to the shot. Cues must be finite, ordered, nonoverlapping, positive-duration intervals with recognized mouth values. An actor outside its cues uses `X`; one actor's speech never drives another actor.

A prop may use PNG `file`, `pivot`, `scale`, `position`, `rotation`, and `depth`, or an editable rectangle/ellipse with `size` and `color`. Its optional attachment has `actor`, `hand`, `offset`, `rotation`, `start` and `end`. Offset is in actor-scaled hand-local coordinates and rotates with the solved wrist; the prop pivot follows the result. When the attachment is inactive, its configured world placement applies. No second copy of an attached prop is added.

## Python API

```python
from animation2d.episode03.engine import render_frame, production_readiness
errors = production_readiness(manifest, 'SHOT_001', audio_dir='build/audio')
image = render_frame(manifest, 'SHOT_001', 1.5, mode='blocking', size=(960,540))
```

The manifest can be a parsed mapping or a JSON path. Asset paths default to repository-relative; mappings can specify `__base_dir__` for fixtures/isolated builds. `production_readiness()` returns asset errors for every visible actor. `render_frame()` returns a Pillow RGB image and accepts times in `[0,shot.duration)`. It does not export a movie, generate speech or approve artwork.


## Reusable named clips and foot planting (v2 extension)

The paragraph above describing idle/reach/walk/gesture predates the reusable library. These LEGACY clip names remain valid. The complete action vocabulary is now in [actions.py](actions.py), and the original, independent PySpine-inspired named keyframe/pose library is documented in [factory/PRODUCTION_LIBRARY_GUIDE.md](factory/PRODUCTION_LIBRARY_GUIDE.md). Separate source and license details are in [factory/RESEARCH_PYSPINE.md](factory/RESEARCH_PYSPINE.md) and [factory/PYSPINE_LICENSE_NOTICE.txt](factory/PYSPINE_LICENSE_NOTICE.txt).

Every original bone sprite retains its original required part ID, PNG, pivot, optional source_end, and depth. This remains our CANONICAL rig interchange format; PySpine v2's sprite sheet/normalized attachment points are **not** silently substituted. For new scenes using actor.actions, foot_lock defaults on: reserved knee flexion allows planted-stance targets to remain reachable after IK, rather than sliding because legs are fully extended. Explicit foot_lock=false retains the old behavior, and legacy actor.action shots remain unchanged.

New shot JSON may name the same skeletal clip across characters:

    {
      "position":[960,650],"scale":0.65,"depth":100,
      "actions":[{"clip":"keyframed","source":"greet","start":0,"end":1.2}]
    }

Named source motion values are pelvis-relative local rig units transformed by the actor's scale. The same source is sampled for Dan, Maya and Nina without duplicating Python movement code. Hand/elbow/knee positions are still solved by our kinematics.py at each frame. For full identity, artist-authored reference-matched rig part PNGs and facial visemes remain mandatory.

Camera tracks, object ownership, named poses and 15s parallel rendering are documented in the developer guide. A clip passing geometry tests is NOT equivalent to animation acting, lips, character art or director approval.
