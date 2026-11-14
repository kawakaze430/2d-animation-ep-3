# English teaching animation — Python 2D

**Render on GitHub Actions:** open [Render 2D animation](https://github.com/kawakaze430/2d-animation-ep-3/actions/workflows/render-2d.yml),
choose **Run workflow**, then select the episode, narration mode, scope and worker count.
Download the MP4 and editable project from the successful run's **Artifacts**.
The default `preview15` scope produces a 15-second pipeline sample; `full` renders
the selected 120-second lesson. The workflow is manually triggered; ordinary contributions run validation instead
of starting an expensive movie render.

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

Episode 03's six JPG character references are not separated animation rigs.
The render job currently supports the original film and Episode 02. It does not
relabel the original character or teaching routine as the Brooks family movie.
Episode 03 needs its own six character-part sets and 15-second scene implementation.

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
