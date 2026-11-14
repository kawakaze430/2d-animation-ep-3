# AnimFactory — reusable Python 2D animation platform (in development)

**New independent product core:** [animfactory/](animfactory/README.md).
Build a completely new animation project with a versioned JSON format,
safe transparent rig/PNG import, project-owned reusable motion clips,
frame-accurate timeline, editable browser studio and local Pillow/FFmpeg
technical exports. See [milestones and implementation ledger](animfactory/ROADMAP.md).
This is a product foundation, not a claim that all rigging, hosted, AI,
facial animation or production film tools are complete.

The existing English teaching renderer, Episode 02 and Episode 03 projects
remain preserved as compatibility fixtures and real-world acceptance tests.
No product license has been selected or changed. Local rendering works
without external AI services or paid subscriptions.

## Existing film/episode workflows


**Render on GitHub Actions:** open [Render 2D animation](https://github.com/kawakaze430/2d-animation-ep-3/actions/workflows/render-2d.yml),
choose **Run workflow**, then select the episode, narration mode, scope and worker count.
Download the MP4 and editable project from the successful run's **Artifacts**.
The default `preview15` scope produces a 15-second pipeline sample; `full` renders
the selected 120-second lesson. The workflow is manually triggered; ordinary contributions run validation instead
of starting an expensive movie render.

## Reusable animation factory (Episode 03 and future episodes)

**Architecture first:** the Episode03 multi-actor engine now supports layered, parameterized action clips, named prop targets, reusable hand/prop interactions, per-character PNG rigs, JSON scene/camera/environment presets, live browser action review, and hash-cached incremental/parallel frame rendering. Add new scene JSON and art, not a new Python animation file for every shot.

- [Factory developer handoff: API, rigs, JSON scenes and rendering](animation2d/episode03/factory/README.md)
- [SHOT_001 reusable action scene](animation2d/episode03/factory/scenes/SHOT_001.json)
- [Action engine and mixer](animation2d/episode03/actions.py)
- [15-second SHOT_001 schematic pilot — real 360-frame GitHub Actions render](https://github.com/kawakaze430/2d-animation-ep-3/actions/runs/43642814793)
- [Godot vs Python renderer proof, same 15 synthetic sprites and shared action poses](https://github.com/kawakaze430/2d-animation-ep-3/actions/runs/43642367029)

**Verified synthetic renderer-only benchmark:** Python/Pillow 25.69 s vs Godot 4.7.2 16.12 s for 360 frames at 960x540; Godot was about 37% faster at this **limited** task. It replays Python-solved IK, so this does not measure native Godot animation authoring or total production work, and no migration is authorized.

**Production is NOT complete:** the 15-second SHOT_001 pilot is a **640x360 schematic blocking movie**, not the target 1920x1080 final animation. Real transparent, reference-matched Dan/Maya/Nina 15-part rigs, mouth sprites and approved recorded speech are missing. The production pipeline correctly rejects synthetic placeholders. The JSON scene is the reproducible production specification to fill with accepted character assets.

The pipeline is:

1. AI-generated character and background images.
2. Python/Pillow/NumPy character animation: separate body parts, rotation,
   two-bone IK, walking, reaching, expressions, props and camera moves.
3. Kokoro speech with Rhubarb lip-sync, or the original included narration/cues.
4. FFmpeg encoding and audio mastering to a finished 1920×1080, 24 fps 2D MP4.

| Location | Purpose |
| --- | --- |
| [animation2d/](animation2d/README.md) | Reusable 2D pipeline and command wrapper |
| [animation2d/project/](animation2d/project/README.md) | Original source, character parts, backgrounds, speech and mouth cues |
| [animation2d/episode2/](animation2d/episode2/README.md) | Existing continuation prepared from the same renderer |
| `animation2d/reference/` | Preserved original videos |
| [Episode_03/](Episode_03/README.md) | Six-character screenplay, storyboards and visual references |
| [Episode_03/ANIMATION_2D.md](Episode_03/ANIMATION_2D.md) | Episode 03 adaptation requirements and current asset readiness |
| `.github/workflows/` | Contribution validation and manual movie-render jobs |
| `build/` | Ignored working copies, audio generation, logs and finished renders |

For the original film, choose **original + included** to use its supplied narration
and Rhubarb cues without model downloads. Choose **kokoro** to regenerate speech.
Episode **02** requires **kokoro**, because its dialogue differs from the original.
Voice/model downloads use public official sources; no personal API key is required.

Episode 03 has a separate [browser review and shot-preview action](https://github.com/kawakaze430/2d-animation-ep-3/actions/workflows/episode03-preview.yml)
and [multi-actor engine](animation2d/episode03/README.md), with all 80 shots and
240 exact dialogue turns. It can export labelled schematic blocking; production
requires six reference-matched transparent character-part rigs and reviewed acting.
The six JPG sheets remain references. Detailed motion and performed voices are
pending; the original teaching routine is never relabelled as the family movie.

Run the contribution checks locally with Python 3.11/3.12 and FFmpeg installed:

```sh
python -m pip install -r animation2d/project/requirements.txt
python Episode_03/check.py
python Episode_03/sync.py --check
python -m unittest discover -s tests -v
cd animation2d/project
python -m unittest discover -s . -p 'test_*.py' -v
```

Checks validate actual animated frames and media encoding as well as artwork,
story consistency, joint geometry and hand contact. See the
[contribution guide](.github/CONTRIBUTING.md) for required-check settings and visual review.
Passing CI does not replace watching a finished film.

See [delivery status](DELIVERY_STATUS.md) for successful preview runs, finished
code, committed artwork/dialogue and remaining production-review work.
