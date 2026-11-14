# Articulated 2D animation pipeline

This is the repository's original Python/Pillow/NumPy cutout-puppet renderer,
with Kokoro/PyTorch speech, Rhubarb lip sync, and FFmpeg encoding. Blender is not
used. The archived morning-routine project, painted body layers, room backgrounds,
lossless narration, timing and mouth cues are preserved in `project/`.

This reusable toolchain is not yet the six-character Episode 03 production rig.
Its included original video is a pipeline example, not the Episode 03 opening.

## Run with GitHub Actions

Use the root **Render 2D animation** workflow from GitHub's Actions tab. Rendering
runs on the GitHub runner, and the workflow uploads the resulting MP4, editable
build copy, subtitles, timings, quality report and diagnostic logs. See the root
workflow file for its exact supported inputs and artifact retention. Choose the
original episode with included speech to render without downloading voice models;
Episode 02 requires fresh speech because its dialogue differs.

## Local development

Python 3.11/3.12 and FFmpeg/ffprobe are required. From the repository root:

```sh
python -m pip install -r animation2d/project/requirements.txt
python animation2d/run.py prepare --episode original
python animation2d/run.py preview --episode original
python animation2d/run.py smoke --episode original --seconds 1
python animation2d/run.py render --episode original --workers 2
```

All generation uses an ignored copy under `build/original/project/`; tracked
lesson, rig, captions and narration remain unchanged. Repeated preparation reuses
the build. When source files change, explicitly run `prepare --refresh` to replace
that disposable copy. A build folder without our preparation marker is preserved
and causes an error. Save any work from the disposable build before refreshing.
The 1-second smoke renders actual moving frames and supplied audio; it verifies
24 fps, 1920×1080, H.264/AAC, expected frame count, duration and full decode.
The full render produces `output/Everyday_English_2_Minute_Preview.mp4` inside the
build copy. Use one worker on smaller machines.

## Fresh Kokoro speech and Rhubarb lip sync

Follow the root render workflow for the tested installation/download commands.
The voice path uses CPU PyTorch, Kokoro 0.9.4, `transformers<5`, soundfile,
phonemizer, espeakng-loader, and spaCy's English model. It needs official Kokoro
`config.json`, `kokoro-v1_0.pth` and `voices/af_heart.pt` (the last stored as
`af_heart.pt`) and the Rhubarb 1.14.0 executable and companion data. Keep TLS and
artifact integrity verification enabled; `tools/setup_voice.py` manages downloads
when present. No account secret or paid generation service is required.

```sh
python animation2d/run.py voice --episode original \
  --model-dir /absolute/path/models \
  --rhubarb /absolute/path/rhubarb --workers 2 --speed 0.85
python animation2d/run.py render --episode original --workers 2
```

Fresh voices change only the build's lesson timings, captions and audio.
The current original recording makes model downloads unnecessary for the included
workflow. Model installation alone does not prove new voice performance quality.

## Episode 02 continuation

```sh
python animation2d/run.py prepare --episode 02
python animation2d/run.py preview --episode 02
python animation2d/run.py voice --episode 02 \
  --model-dir /absolute/path/models --rhubarb /absolute/path/rhubarb --workers 2
python animation2d/run.py render --episode 02 --workers 2
```

The prepared copy is `build/episode02/project/`. Preparation removes inherited
speech and captions so the original narration cannot leak into Episode 02.
A preview can run with empty cues while voice is pending; rendering refuses
missing audio/captions. Fresh speech supplies the matching cues and dialogue.
The final name is `output/Episode_02_Breakfast_and_Garden_120s.mp4`.
Do not run `build_routine.py` in an Episode 02 build: it resets the lesson.

## Regression checks

```sh
python Episode_03/check.py
python Episode_03/sync.py --check
python -m unittest discover -s tests -v
cd animation2d/project
python -m unittest discover -s . -p 'test_*.py' -v
```

Source checks, geometry tests and a smoke encode catch technical failures.
Watch a full rendered video before release to inspect acting, hand/prop contact,
clipping, continuity, lip sync, voice pacing, caption timing and sound.

The unmodified old preview clips and historical workflow are retained in
`reference/` for provenance. `reference/render-episode2-legacy.yml` is documentation,
not an active Actions workflow; use the root `.github/workflows/` files.
