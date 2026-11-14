"""Reproducible Godot-vs-Python RENDERER bench: same ORIGINAL fixture PNGs and sampled pose.

The deliberately synthetic illustration is generated once by this script, then
both Python Pillow and Godot Sprite2D render it. This is NOT Episode 03 artwork,
not a whole-engine benchmark, and not proof of any creative quality improvement.

Inputs: 960x540, 24 fps, 15 sec, single DAN-shaped articulated fixture and same
source rig/scene/action/IK pose; output frames are PNG in both cases.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

from PIL import Image, ImageDraw
import numpy as np

from animation2d.episode03.engine import Actor, REPO, REQUIRED_BONES, render_frame

FPS, DURATION, SIZE = 24, 15, (960, 540)
BONES = sorted(REQUIRED_BONES)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def drawable_art(bone, ordinal, dest):
    """Transparent 64x128 sprite shared byte-for-byte by both renderers."""
    im = Image.new("RGBA", (64, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    colors = ["#784F88", "#7A9AB9", "#A66A5D", "#60728C", "#C98F7E", "#446F93"]
    c = colors[ordinal % len(colors)]
    d.rounded_rectangle((19, 10, 46, 119), radius=12, fill=c)
    d.rounded_rectangle((19, 10, 46, 119), radius=12, outline="#273C54", width=3)
    if bone == "head":
        d.ellipse((5, 9, 59, 74), fill="#DDB298", outline="#6B4B55", width=3)
        for x in (24, 42):
            d.ellipse((x-3, 39, x+3, 45), fill="#283B43")
        d.arc((23, 43, 43, 60), 0, 175, fill="#60434B", width=2)
    elif bone == "torso":
        d.polygon([(16, 12), (49, 12), (58, 115), (7, 115)], fill=c)
        d.line((32, 16, 32, 112), fill="#EDE9D9", width=3)
    im.save(dest, format="PNG", compress_level=6)


def prepare(output):
    output = Path(output)
    art = output / "art"
    art.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, bone in enumerate(BONES):
        path = art / (bone.replace(".", "_") + ".png")
        drawable_art(bone, i, path)
        parts.append({"id": bone, "bone": bone, "file": path.name,
                      "pivot": [32, 12], "source_end": [32, 112], "depth": i})
    rig = {"version": 1, "parts": parts, "faces": {}}
    json_save(art / "rig.json", rig)
    # Always use a relative path in the checked-out repository, not an external
    # output, so Python's production rig loader uses its existing validation.
    rig_path = (art / "rig.json").resolve()
    if not rig_path.is_relative_to(REPO):
        raise ValueError("Benchmark output must be under the source repository")
    action = {"position": [480, 290], "scale": 0.48, "depth": 100,
              "actions": [
                  {"clip": "reach", "start": 0, "end": 9, "hand": "right",
                   "target": [560, 270], "hold_last": True, "emotion": "curious"},
                  {"clip": "look", "start": 0, "end": 12, "degrees": 8},
                  {"clip": "blink", "start": 4, "end": 4.25},
              ]}
    manifest = {"version": 1, "fps": FPS, "canvas": list(SIZE),
                "characters": {"DAN": {"rig": rig_path.relative_to(REPO).as_posix()}},
                "shots": [{"id": "BENCH_001", "duration": DURATION, "cast": ["DAN"],
                           "actors": {"DAN": action}, "props": [], "foreground": [],
                           "camera": {"zoom": 1, "center": [480, 270]}}]}
    json_save(output / "manifest.json", manifest)
    actor = Actor("DAN", manifest["characters"]["DAN"], action, mode="production")
    keyframes = []
    for index in range(FPS * DURATION):
        pose = actor.pose(index / FPS, DURATION)
        transforms = []
        for part in parts:
            start, end = pose["bones"][part["bone"]]
            vector = end - start
            degrees = math.degrees(math.atan2(float(vector[1]), float(vector[0]))) - 90
            # source_end - pivot == (0,100) in *both* renderers.
            scale = float(np.linalg.norm(vector) / 100)
            transforms.append({"position": [float(v) for v in start],
                               "rotation_degrees": degrees, "scale": scale})
        keyframes.append(transforms)
    json_save(output / "motion.json", {
        "fps": FPS, "duration": DURATION, "size": list(SIZE),
        "parts": parts, "frames": keyframes
    })
    json_save(output / "provenance.json", {
        "source": "GENERATED_SYNTHETIC_FIXTURE_NOT_PRODUCTION_ART",
        "renderer_comparison": "Pillow sprite rendering vs Godot Sprite2D/AnimationPlayer",
        "limitation": "Godot consumes Python-sampled IK to isolate renderer cost; this is not a native Godot IK benchmark",
        "rig_sha256": sha(art / "rig.json"), "manifest_sha256": sha(output / "manifest.json"),
        "motion_sha256": sha(output / "motion.json"),
        "sprite_sha256": {p["file"]: sha(art / p["file"]) for p in parts},
    })
    print(json.dumps({"status": "fixture-prepared", "frame_count": len(keyframes),
                      "source_art": "synthetic (not Episode 03 final art)",
                      "motion_sha256": sha(output / "motion.json")}))


def python_frames(output):
    output = Path(output)
    data = json.loads((output / "manifest.json").read_text())
    shots = output / "python_frames"
    shots.mkdir(exist_ok=True)
    started = time.perf_counter()
    cpu = time.process_time()
    samples = []
    for index in range(FPS * DURATION):
        im = render_frame(data, "BENCH_001", index / FPS, mode="production", size=SIZE)
        path = shots / f"python{index:08d}.png"
        im.save(path, format="PNG", compress_level=6)
        if index in (0, 72, 180, 288, 359):
            samples.append({"index": index, "sha256": sha(path)})
    result = {"renderer": "Python Pillow production-mode drawing with SYNTHETIC input art",
              "frame_count": FPS * DURATION,
              "wall_s": time.perf_counter() - started,
              "cpu_s": time.process_time() - cpu,
              "python_version": sys.version.split()[0], "system": platform.platform(),
              "sample_sha256": samples}
    json_save(output / "python_metrics.json", result)
    print(json.dumps(result))


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames,avg_frame_rate,width,height",
        "-of", "json", str(path)], text=True)
    return json.loads(out)["streams"][0]


def check_outputs(output):
    output = Path(output)
    before = json.loads((output / "python_metrics.json").read_text())
    art = json.loads((output / "provenance.json").read_text())
    if art["motion_sha256"] != sha(output / "motion.json"):
        raise ValueError("Action pose data changed during benchmark")
    if art["manifest_sha256"] != sha(output / "manifest.json"):
        raise ValueError("Scene changed during benchmark")
    from PIL import ImageChops
    px, gd = [], []
    differences = []
    for index in (0, 72, 180, 288, 359):
        a = output / "python_frames" / f"python{index:08d}.png"
        b = output / "godot" / f"godot{index:08d}.png"
        if not a.is_file() or not b.is_file():
            raise ValueError(f"Missing cross-renderer sample index {index}")
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if ia.size != SIZE or ib.size != SIZE:
            raise ValueError("Renderer resolution mismatch")
        aa, bb = np.asarray(ia, dtype=np.int16), np.asarray(ib, dtype=np.int16)
        mae = float(np.abs(aa - bb).mean())
        differences.append({"frame": index, "mean_absolute_rgb_error_255": mae,
                            "python_sha256": sha(a), "godot_sha256": sha(b)})
        px.append(ia.resize((480, 270)))
        gd.append(ib.resize((480, 270)))
    for backend, folder, stem in (("python", "python_frames", "python"),
                                  ("godot", "godot", "godot")):
        found = sorted((output / folder).glob(stem + "*.png"))
        if len(found) != FPS * DURATION:
            raise ValueError(f"{backend}: expected 360 genuine PNG output frames, got {len(found)}")
    if len({x["python_sha256"] for x in differences}) < 2:
        raise ValueError("Python output is static; benchmark is invalid")
    if len({x["godot_sha256"] for x in differences}) < 2:
        raise ValueError("Godot output is static; benchmark is invalid")
    report = {
        "status": "ENGINE_RENDERER_PROOF_ONLY_NOT_FULL_SCENE_PRODUCTION",
        "source_art": art["source"], "motion_sha256": art["motion_sha256"],
        "fps": FPS, "frames": FPS * DURATION, "size": list(SIZE),
        "python": before, "godot": json.loads((output/"godot_metrics.json").read_text()),
        "sample_pixel_difference": differences,
        "fairness": "same synthetic 15-part PNG art, same sampled Episode03 IK, pose and 15s animation; Godot AnimationPlayer replays poses. Both PNG writers include renderer+PNG encode time.",
        "limitations": [
            "Pillow and Godot use different resampling/antialiasing and output is not expected pixel-identical",
            "Godot animation inputs precomputed by Python: comparison isolates graphics backend rather than all-in animation authoring",
            "Shot 001 real character art, lip sprites and approved audio are not present",
            "No switch or migration is authorized by this synthetic test",
        ],
        "migration_decision": "Keep Python by default; revisit only after authentic SHOT_001 A/B and human-reviewed total effort and visual quality.",
    }
    json_save(output / "report.json", report)
    contact = Image.new("RGB", (960, 540 * len(px)))
    for i, (a,b) in enumerate(zip(px,gd)):
        contact.paste(a,(0,i*540))
        contact.paste(b,(480,i*540))
    contact.save(output / "comparison_contact_sheet.png")
    lines = [
        "# Python Pillow vs Godot 4.7.2 renderer proof",
        "", "**Synthetic fixture only — not production Episode 03 or a migration decision.**", "",
        "| Measure | Python | Godot |", "|---|---|---|",
        f"| Frames | {before['frame_count']} | {report['godot']['frame_count']} |",
        f"| 960×540 PNG frame export wall seconds | {before['wall_s']:.2f} | {report['godot']['wall_s']:.2f} |",
        f"| Same synthetic cutout sprites | Yes | Yes |",
        f"| Same Episode03 solved IK, action, timing | Yes | Yes (replayed keyframes) |",
        "", "## Differences on five sampled frames",
        "", *[f"- Frame {d['frame']}: mean absolute RGB error {d['mean_absolute_rgb_error_255']:.3f}/255" for d in differences],
        "", "A pixel-perfect match is **not** expected: PIL and Godot filter differently.",
        "Godot is not sampling independent Godot IK; AnimationPlayer replays the Python-solved rig timeline.",
        "No quality, labor cost, or production superiority can be concluded from this isolated test.",
        "For production, use the existing Python factory until authentic shot art and full creative QA justify a move.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "samples": differences,
                      "migration_decision": report["migration_decision"]}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("prepare", "python", "report"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    {"prepare": prepare, "python": python_frames, "report": check_outputs}[a.command](a.output)


if __name__ == "__main__":
    main()
