# Episode 02 — Breakfast and Garden

This continuation reuses the original painted puppet, body-part layers, rooms,
Pillow/NumPy articulated renderer, Kokoro `af_heart` voice and Rhubarb mouth cues.
It contains twelve ten-second actions: window, bed, wash hands, comb hair, enter
kitchen, wash apple, prepare/eat breakfast, drink, pack, go outside, water flowers.

Run the root GitHub Actions **Render 2D animation** workflow with Episode 02 and
fresh speech. The runner prepares a separate build, generates all 36 new lines,
aligns mouth cues, renders 1920×1080 at 24 fps and uploads the result. No Episode 02
finished video is claimed merely from preparing its source.

Local equivalent from the repository root:

```sh
python animation2d/run.py prepare --episode 02
python animation2d/run.py preview --episode 02
python animation2d/run.py voice --episode 02 --model-dir /absolute/models \
  --rhubarb /absolute/rhubarb --workers 2
python animation2d/run.py render --episode 02 --workers 2
```

Read [the pipeline guide](../README.md) for dependencies and verified download
instructions. Builds live at `build/episode02/project/`; tracked original sources
remain intact. Preparation deliberately removes original narration and captions;
rendering needs the new voice output. Previews before voice generation have empty
mouth cues. The final file is
`output/Episode_02_Breakfast_and_Garden_120s.mp4` inside the build.

Do not run the original `build_routine.py` in this build. It would replace the
continuation timeline. Watch the complete render for contact, clipping, flicker,
continuity, caption alignment, voice pacing and mouth timing before accepting it.
