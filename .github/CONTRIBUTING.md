# Contributing safely

Work in the existing checkout. The supported pipeline is AI source artwork → transparent body-part PNG layers → Python/Pillow joint rotations, walking and props → included narration or Kokoro voices with Rhubarb mouth cues → FFmpeg. Keep the six Episode 03 cast identities, W01 wardrobe, story dialogue and recipe quantities consistent with `Episode_03/CONTINUITY.md`. New animation should remain editable and reproducible; include source layers and scripts rather than only a video.

Install Python dependencies with `python -m pip install -r animation2d/project/requirements.txt` and install FFmpeg/ffprobe. Before pushing, run from the repository root:

```sh
python Episode_03/check.py
python Episode_03/sync.py --check
python -m unittest discover -s tests -p 'test_*.py' -v
(cd animation2d/project && python -m unittest discover -s . -p 'test_*.py' -v)
```

Edit `Episode_03/STORY.md` before regenerating written handoff files with `python Episode_03/sync.py`. Review the derived diff, then rerun checks. Do not regenerate captions over approved performed timings without review.

`Episode_03/assets/reference_checksums.json` pins the 16 existing JPG cast and home previews. These hashes protect this repository's baseline, not missing owner archive originals. Review any intentional baseline changes alongside the images; do not update hashes merely to silence a failed check.

The **Validate contributions** workflow runs on every push and pull request and fails if any command fails. Negative tests deliberately corrupt images, dialogue, subtitles, recipe text and links. The real rendering smoke uses original PNG layers, checks that joint-motion frames differ, and encodes and probes H.264 video with AAC narration in a temporary directory. These checks cannot certify visual likeness, acting, lip sync or creative quality; inspect the rendered video separately.

Repository administrators should require `Story and animation / Python 3.11` and `Story and animation / Python 3.12` checks in the branch protection/ruleset before merging. A workflow alone cannot prevent administrators or direct pushes from bypassing checks. Changes to workflows, tests and the reference baseline also require human review.


# Rendering in GitHub Actions

Open Actions → **Render 2D animation** → Run workflow. Select `original` with `included` audio for the smallest setup, or select `kokoro` to generate fresh CPU speech and Rhubarb mouth cues. Episode `02` always requires `kokoro` because its dialogue differs. Select `preview15` (default) for a 15-second pipeline preview or `full` for the complete 120-second lesson, then choose one or two workers. These choices render existing lessons; the original puppet is not the six-character Episode 03 cast.

The workflow downloads optional Kokoro files at a resolved upstream commit and verifies their LFS SHA-256 or Git blob digest on every run, including cache hits. Rhubarb 1.14.0 is checked against the pinned SHA-256 of its official HTTPS release. It keeps TLS verification enabled. The Kokoro model revision and checksums are retained in `verified_downloads.json`.

Successful runs upload the MP4, an editable project ZIP, validation JSON and logs. Failed runs upload available diagnostics and remain failed. Artifacts expire after 14 days; download them from the workflow run. Rendering happens in GitHub Actions and never pushes generated output back into source control.
