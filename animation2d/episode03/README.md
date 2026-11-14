# Episode 03 multi-actor 2D pipeline

This extends the original Python cutout renderer's rotation, inverse-kinematics,
walking and pivot mathematics. The original teaching project remains available
unchanged under `animation2d/project/`.

| Capability | Implemented | Still needs production review |
| --- | --- | --- |
| Six actors | Separate pose/rig instances, scales, cues and artwork paths | Six transparent, reference-matched part sets |
| Six voices | Six distinct Kokoro presets and isolated actor tracks | Actual generated performances and suitable child casting |
| Lip sync | Separate Rhubarb files, gated to each actor's speech | Authored mouth sprites and performed alignment |
| 80 shots | 15-second data records, all 240 exact dialogue turns | Detailed motion authoring beyond initial rough blocking |
| Camera/props | Per-shot camera, hand attachments, stable depth ordering | Contact, occlusion and acting in finished frames |
| Kitchen state | Persistent, validated recipe/cooking/serving ledger | Visual continuity against each rendered shot |
| Browser review | Live scrubbing and portable 80-shot gallery | Creative acceptance; snapshots are not finished movies |

`shots.json` contains source hashes, cast, dialogue, camera, actor placement,
props, state transitions and preserved screenplay directions. Edit `overrides.json`
to author camera, actor actions, depths, props and foreground layers without
losing changes when the screenplay data is refreshed:

```sh
python -m animation2d.episode03.manifest --write
python -m animation2d.episode03.manifest --check
python -m animation2d.episode03.voice --manifest animation2d/episode03/shots.json --shot all --validate
```

The `--check` command validates source consistency and reports missing artwork
separately. Missing production rigs are real outstanding work, not a passing
production-readiness result. See [RIG_FORMAT.md](RIG_FORMAT.md) to supply PNG parts,
anchors and authored mouth sprites. Do not cut up the compressed reference JPGs
automatically or substitute the original teaching character for this cast.

## Review and render on GitHub

Run **Episode 03 browser review and shot preview** in the repository's Actions tab.
Choose a shot ID, `blocking` or `production`, and silent blocking or Kokoro audio.
The workflow produces an offline gallery and a selected 15-second MP4, with logs,
source revision, subtitles, dialogue and media validation reports.

Download and extract the artifact, then open the review pack's `index.html` in a
browser. Each of the 80 shots has three real renderer samples, cast/location
filters, dialogue, directions, state records and separate original character
references. Static sample selection is labelled; continuous scrubbing is available
when the local review server is running:

```sh
python -m animation2d.episode03.preview --manifest animation2d/episode03/shots.json
```

The live review page is silent picture review. Movie rendering runs in GitHub
Actions. Blocking uses labelled schematic actors. Production refuses missing
transparent part rigs, required speech sprites or generated shot narration;
it never treats schematic placeholders as approved character animation.

For Kokoro, the workflow downloads verified model files and six voice tensors.
The voice module synthesizes exact dialogue, retries speed within a bounded range,
and fails when words cannot fit instead of clipping speech. It writes one mixed
track plus six actor WAVs/cue files, measured timings and subtitles for each shot.
The provisional screenplay timings are replaced by those measured speech windows.

## Current delivery status

Committed artwork is the existing reference/still-image package. The new dialogue
delivery is 240 exact text turns, not a claim that all voices have been generated.
The new engine and browser gallery have been tested; actual Kokoro inference and
the full 20-minute Episode 03 movie have not been rendered locally. Most shot
motion remains an explicit idle blocking default with complete screenplay
instructions retained for animators. A static gallery, CI pass or asset-existence
check is not creative approval.
