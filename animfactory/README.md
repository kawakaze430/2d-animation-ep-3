# AnimFactory — independent animation product core (milestone 1)

This Python package is a standalone **project and editing surface** above the existing
Pillow/NumPy cutout engine. It is not an Episode 03 storyboard or a replacement
for the established animation/math/audio/render pipelines. Its project IDs, scene
IDs, actor IDs, motion tracks and filenames do not contain episode-specific rules.

Status: **functional technical core + local web timeline editor**, not a complete
commercial animation editor. No source file in this milestone changes the
repository's license. No AI provider, paid GPU or network service is required.

## Versioned product JSON

The source of truth is a project folder with the following layout:

    MyFilm/
      project.json                    # animfactory.project, schema version 1
      assets/
        rigs/
          ARTIST_ONE/
            rig.json                  # proven Episode03 15-bone rig v1
            head.png
            torso.png
            ...
        images/
          kitchen.png                 # imported background PNG
      (outputs should be saved under an ignored build folder)

The project contains registries for assets (ID, kind, project-relative
path, sha256, source/rights/provenance and per-part hashes), characters
(rig asset references), a project-owned motion library (normalized keyframes
and pose presets), and scenes. A scene has exact integer duration in frames,
a reusable camera, cast instances, per-actor layered action tracks, props and
dialogue. Timeline actions are stored with integer start_frame and end_frame;
translation to seconds happens only at the engine adapter boundary.

Open/save validates version, asset cross-references, clip sources, numeric
bounds, camera tracks, prop/actor bindings, legal relative file paths and
identity uniqueness. File reads are restricted to the project root. Saving
project.json is atomic. Imported content is not overwritten on re-import.

For now, our compatible rig model is the **existing 15-part PNG cutout rig**,
not a fully general skeletal hierarchy or a PSD importer. SVG/PSD parsing,
independent facial rigging, bone/pivot GUI, general retargeting and SAM/rembg
are explicitly separate milestones. An image alone cannot supply occluded
body geometry.

## Start a COMPLETELY NEW project (no Episode 03 dependency in its saved data)

All commands run from repository root with Python 3.11+ and dependencies from
animation2d/project/requirements.txt.

    python -m pip install -r animation2d/project/requirements.txt
    python -m animfactory init build/new-film --id new_film --title "New Film" --size 640 360 --fps 24
    python -m animfactory import-rig build/new-film /path/to/ARTIST/rig.json ARTIST --license "original-user-art"
    python -m animfactory add-scene build/new-film intro --frames 48
    python -m animfactory add-actor build/new-film intro ACTOR1 ARTIST --x 340 --y 250 --scale 0.6
    python -m animfactory add-action build/new-film intro ACTOR1 greet1 keyframed --source greet --start 0 --end 29
    python -m animfactory motions build/new-film --query greet
    python -m animfactory check build/new-film

The new project is initialized with an OWNED SNAPSHOT of existing generic
motion presets; edits to its motion library do not change Episode 03 or any
other project. Additional clips can be imported through:

    python -m animfactory add-motion build/new-film my_gesture path/to/clip.json

Clip JSON uses the pre-existing strict named track shape from
animation2d/episode03/motion_clips.py. Poses use a simple channel→number map;
pass --pose when importing a pose.

## Visual 15-layer rigging: real browser import and pivot authoring

The existing 15-part cutout-v1 schema and authoritative Pillow/IK solver remain
unchanged. Rig authoring is integrated into the same local browser studio.

1. Create a new independent project, launch studio, click **Rig studio · Import & edit**.
2. Drag/drop or select 15 transparent PNG body-part images. Filenames must map to
   head.png, torso.png, pelvis.png and six left/six right roles such as
   upper_arm_left.png, forearm_left.png, hand_right.png, thigh_right.png,
   shin_left.png and foot_right.png. Both dot and underscore side names work.
3. Confirm all 15 thumbnails and missing-layer warnings. Enter a character ID,
   source and rights metadata; click **Import verified 15-part rig**.
4. Select a character and bone. The full character preview is rendered by the
   real Python IK/renderer. The separate source PNG canvas lets you **drag the
   red pivot or cyan bone end**. Hold Shift to select the bone end, or change
   numeric pivot/end coordinates, sprite mirror and depth explicitly.
5. Adjust neck/shoulder/hip joint anchors and thigh/shin/arm lengths as needed;
   use the right-arm reach toggle to preview IK after saving.
6. Each save creates a content-addressed immutable rig JSON revision. The
   original sprite PNGs and rig.json remain unchanged; choose a previous version
   to restore it or use Undo/Redo. Project changes survive reopening the project.

Source sprite control-point coordinates differ from world coordinates. Complete
technical rigs are NOT visually reviewed character art: current bone hierarchy
is fixed to 15 anatomical roles, and custom parent roles/rotation limits,
two-handed physics, PSD/SVG, facial sprites, fully automatic segmentation or
reconstruction of hidden anatomy are NOT implemented here.

Rig revisions are stored as rig_edit_<SHA256>.json within the character's
assets/rigs/<ID>/ directory; checksums, source and license metadata are
retained. Rig selection and restoration remain valid after app restarts.
Artwork import is intentionally NOT undone by general timeline undo, because
its immutable physical source files remain registered. Import resets the
session's in-memory undo stack; reimporting replacement artwork under the same
character ID is a subsequent milestone. A new ID is always safe.

Security/limits: exact 15-role whitelist, validated base64/PNG/alpha, 4 MiB
per layer, at most 48 MiB decoded artwork combined, 16M image-pixel bound,
local-only service, strict same-origin edits, project revision guard, and
no user-controlled file paths. All operations run offline/CPU without AI.

Technical verification:

    python -m unittest discover -s tests -p 'test_rigging_studio.py' -v
    node --check animfactory/web/rig.js

Konva's maintained MIT canvas library was evaluated for a future sophisticated
bone hierarchy editor. This milestone deliberately reuses native browser
Canvas for source-pivot edits rather than introducing a new dependency or CDN.
See issue #8 for PSD/SVG and deeper bone relationships.

## Browser editor — local, no desktop installation

    python -m animfactory studio build/new-film --port 8190

Open http://127.0.0.1:8190 in a browser. The editor exposes:
- Project browser and scene selection.
- Imported asset/character registry.
- Searchable project-owned named keyframe and pose clips.
- Character placement, position and scale inspector.
- Clip timeline with frame-range editing, add and remove.
- Deterministic frame scrubbing in schematic or actual rig rendering mode.
- Save-on-edit with revision conflicts, atomic JSON validation, undo/redo.
- Export current PNG preview with the same authoritative Pillow engine.

**Security:** this MVP server deliberately accepts loopback only; it is not
a public multi-user or cloud-hosted studio. A hosted deployment needs
authentication, CSRF/origin hardening, user/project permissions, quotas,
storage isolation, worker job cancellation and secure transport. The
browser editor cannot read arbitrary files or run Python/AI plugins.
A separate hosted service and Konva bone editor are later milestones.

**Preview** is frame-on-demand (not guaranteed full-speed 24fps playback).
The same Pillow renderer is used to create exported frames, and schematic
blocking is labeled. Production mode refuses incomplete rig art; it never
silently swaps schematic artwork into a production export.

## Short technical renders, NOT production movie creation

    python -m animfactory frame build/new-film intro --index 12 --mode production --output build/intro_12.png
    python -m animfactory export build/new-film intro --mode production --frames 4 --output build/intro_4frames.mp4

The product CLI creates a true H.264/yuv420p video with FFmpeg and verifies
actual frame count and dimensions with FFprobe. This initial CLI is
intentionally limited to 240 frames per invocation to prevent unnecessary
full-resolution CI charges. Exports contain no audio unless the existing
Episode03 audio pipeline is configured externally; a *silent render is
reported as silent*. No clip is represented as creative approval. For large
jobs, continue using the validated cached GitHub Actions renderer.

Use two compatible imported rigs:

    python -m animfactory import-rig build/new-film /path/to/OTHER/rig.json OTHER --license original
    python -m animfactory add-actor build/new-film intro ACTOR2 OTHER --x 480 --y 250 --scale 0.75
    python -m animfactory add-action build/new-film intro ACTOR2 greet2 keyframed --source greet --start 0 --end 29

Both characters use ONE stored motion clip. The per-actor rig, pivot/IK,
position, scale and face art stay independent. No new actor-specific action
script is needed.

## Browser/CLI editing API

    from animfactory import Project, EditSession
    project = Project.open("build/new-film")
    session = EditSession(project)
    session.apply({"op":"set","path":"/scenes/0/actors/0/position","value":[365,260]})
    session.undo()
    session.redo()
    frame = project.render_frame("intro",12,mode="production")

Atomic batch command:

    {"op":"batch","commands":[
      {"op":"set","path":"/scenes/0/actors/0/position","value":[365,260]},
      {"op":"set","path":"/scenes/0/actors/0/scale","value":0.65}
    ]}

A failed command changes neither saved project.json nor edit history. Arbitrary
file paths, imports/metadata/license changes and code execution cannot happen
through general timeline JSON edits. Import/asset changes use separate methods.
The session's undo history is in-memory, while successful edits are persisted
to disk. A restart loads saved project data but not prior undo stack.

## Validation

    python -m unittest discover -s tests -p 'test_animfactory_product.py' -v
    python -m unittest discover -s tests -p 'test_*.py' -v

Technical acceptance uses **synthetic, original and deliberately unpolished
15-part PNG test rigs**. Tests create a brand-new project, import two compatible
characters, assign the same named reusable animation, render changed real
Pillow PNG frames, check joint continuity, perform two-frame studio preview,
exercise origin/path sanitization, undo/redo persistence and run a three-frame
real FFmpeg/FFprobe export. No episode screenplay, speech synthesis, paid
provider calls or 15-second full movie is generated.

For prior capabilities and their licenses, read
animation2d/episode03/factory/RESEARCH_PYSPINE.md and the original upstream
copyright notices. No overall product license has been chosen or changed.
