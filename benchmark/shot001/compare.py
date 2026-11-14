"""Reject mismatched or schematic renders; report paired, reproducible measurements."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.shot001.common import CAST, DURATION, FPS, SIZE, sha256


def compare(a_dir: Path, b_dir: Path, output: Path):
    a = json.loads((a_dir / "benchmark.json").read_text())
    b = json.loads((b_dir / "benchmark.json").read_text())
    expected = {"python": a, "rigby": b}
    assert a["version"] == "python" and b["version"] == "rigby"
    assert a["source_input"] == b["source_input"], "Art, narration, cues or shot contract differ"
    assert a["encoder"] == b["encoder"], "Encoding settings differ"
    assert a["media_validation"] == b["media_validation"], "MP4 frame/codec verification differs"
    assert b["rigby_evidence"], "No real Rigby export evidence"
    for actor in CAST:
        evidence = b["rigby_evidence"]["actors"][actor]
        assert evidence["frames"] == 360 and evidence["rig_structure"]["bones"] >= 16
    assert b["rigby_evidence"]["rigby_source_commit"] != "UNPINNED"
    assert a["media_validation"]["full_decode"] == "passed"
    for mode, folder in (("python", a_dir), ("rigby", b_dir)):
        filename = {
            "python": "SHOT_001_Python_Only_15s.mp4",
            "rigby": "SHOT_001_Python_Rigby2D_15s.mp4",
        }[mode]
        movie = folder / filename
        assert movie.is_file() and sha256(movie) == expected[mode]["mp4_sha256"]
        assert expected[mode]["media_validation"]["frames"] == FPS * DURATION
        assert expected[mode]["media_validation"]["width"] == SIZE[0]
        assert expected[mode]["media_validation"]["height"] == SIZE[1]

    output.mkdir(parents=True, exist_ok=True)
    heading = "# SHOT_001 — fair production comparison\n\n"
    intro = ("**Technical render QA: both passed.** All three actors used the same "
             "validated source PNG artwork, screenplay, camera, audio master and encoding settings. "
             "**Creative quality and identity acceptance remain subject to human review.**\n\n")
    def row(label, key, unit=""):
        return f"| {label} | {a.get(key, 'not measured')} {unit} | {b.get(key, 'not measured')} {unit} |\n"
    table = ("| Metric | A: Pillow/NumPy IK | B: Rigby2D MCP + Python |\n"
             "|---|---:|---:|\n"
             + row("Scene-frame generation (s)", "frame_render_seconds")
             + row("FFmpeg encoding (s)", "encode_seconds")
             + row("Python peak RSS (KiB)", "max_python_process_rss_kb")
             + row("MP4 bytes", "mp4_bytes")
             + row("MP4 SHA-256", "mp4_sha256")
             )
    rigby_seconds = sum(float(b["rigby_evidence"]["actors"][c]["rigby_character_export_seconds"]) for c in CAST)
    rigbuild_seconds = sum(float(b["rigby_evidence"]["actors"][c]["rig_build_seconds"]) for c in CAST)
    caveats = (
        f"\nRigby character PNG export: **{rigby_seconds:.3f}s** for all three actors; "
        f"building their real Rigby project structures: **{rigbuild_seconds:.3f}s**. "
        "These stages are separate from shared scene composition.\n\n"
        "Original character artwork separation, rigging cleanup, voice casting, manual face/hand QA, "
        "and full GitHub Actions scheduling/setup time are **not** measured by these render-process "
        "timers. Extract total Actions duration from the completed run's GitHub job timestamps; "
        "do not replace it with the video encoding time.\n\n"
        "Quality rubric: inspect exact corresponding MP4 frames and played audio for facial expressions, "
        "mouth/phoneme timing, elbow and shoulder gaps, hand-to-recipe and hand-to-bowl contact, "
        "movement arcs and cast likeness. Neither renderer wins until that review is recorded. "
        "An 80-shot cost forecast must include art/rig creation, review retries, voice and "
        "runner minutes, not just multiplying one frame-render time by eighty.\n"
    )
    report = {"status": "COMPARABLE_TECHNICAL_EXPORTS__CREATIVE_REVIEW_PENDING",
              "inputs_identical": True,
              "frame_settings_identical": True,
              "audio_identical": True,
              "rigby_real_skeletal_frames": True,
              "winner": None,
              "reason": "Manual paired-animation quality acceptance and measured artwork setup effort pending",
              "rigby_export_seconds": rigby_seconds,
              "rigby_project_creation_seconds": rigbuild_seconds,
              "A": a, "B": b}
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "COMPARISON.md").write_text(heading + intro + table + caveats)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--rigby", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    v = p.parse_args()
    report = compare(v.python, v.rigby, v.output)
    print(json.dumps({"status": report["status"], "winner": report["winner"]}, indent=2))
