"""Two real SHOT_001 scene render paths with one composer and one encoding profile.

Version A uses Episode 03's Pillow / NumPy / two-bone-IK character renderer.
Version B substitutes *only* its character draw operation with Rigby2D's
export_sprite_sheet(format=frames) PNGs; the existing Python scene composition,
camera, props and audio path are therefore literally the same functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

from PIL import Image, ImageDraw

from animation2d.episode03 import engine
from animation2d.episode03.render import inspect
from benchmark.shot001.common import (
    CAST, DURATION, FPS, ROOT, SHOT, SIZE, inputs, load_contract, sha256,
)

VIRTUAL_PARTS = {
    "python": "SHOT_001_Python_Only_15s.mp4",
    "rigby": "SHOT_001_Python_Rigby2D_15s.mp4",
}
VIDEO = ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-threads", "2", "-pix_fmt", "yuv420p")
AUDIO = ("-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000")
STILLS = (0, 24, 48, 72, 120, 168, 216, 264, 336)


def png_actors(meta_path: Path):
    """Construct a draw callback for *actual* Rigby-generated RGBA PNGs."""
    meta = json.loads(meta_path.read_text())
    if (meta["shot"], meta["fps"], meta["duration"], tuple(meta["cast"])) != (SHOT, FPS, DURATION, CAST):
        raise ValueError("Rigby2D output metadata differs from locked shot")
    if "MCP" not in meta.get("source", "") or meta.get("rigby_source_commit") in ("UNPINNED", None):
        raise ValueError("Not a verified/pinned Rigby MCP frame export")
    actors = meta["actors"]
    if set(actors) != set(CAST):
        raise ValueError("Rigby did not render all three SHOT_001 characters")

    def draw(self, canvas, t, duration=15):
        info = actors[self.name]
        frame = round(t * FPS)
        if not 0 <= frame < FPS * DURATION:
            raise ValueError("Invalid frame index")
        source = Path(info["frames_folder"]) / f"SHOT_001_{frame:03d}.png"
        if not source.is_file():
            raise ValueError(f"Missing true Rigby2D animation frame: {source}")
        with Image.open(source) as image:
            rgba = image.convert("RGBA")
        if rgba.size != (info["width"], info["height"]):
            raise ValueError(f"{self.name}: Rigby source frame geometry changed")
        root = info["actor_world_origin"]
        ox, oy = info["origin_px"]
        # Rigby local Y is up. After export PNG Y is down, and the calculated
        # origin is a single fixed pivot for the *entire* animation.
        canvas.alpha_composite(rgba, (round(root[0] - ox), round(root[1] - oy)))
    return draw, meta


def make_contact_sheet(frames_dir: Path, out: Path) -> None:
    sheet = Image.new("RGB", (1920, 1080), "white")
    d = ImageDraw.Draw(sheet)
    for j, frame in enumerate(STILLS):
        with Image.open(frames_dir / f"frame_{frame:03d}.png") as source:
            thumb = source.convert("RGB").resize((640, 360), Image.Resampling.LANCZOS)
        x, y = (j % 3) * 640, (j // 3) * 360
        sheet.paste(thumb, (x, y))
        d.rectangle((x, y, x + 160, y + 25), fill="#17202A")
        d.text((x + 8, y + 5), f"SHOT_001 | {frame / FPS:.2f}s", fill="white")
    sheet.save(out)


def render(version: str, audio_dir: Path, output: Path, rigby_meta: Path | None) -> dict:
    contract = inputs(audio_dir)
    manifest, shot = load_contract()
    output.mkdir(parents=True, exist_ok=True)
    frames = output / "scene_frames"
    frames.mkdir(exist_ok=True)
    expected = FPS * DURATION
    if any(frames.iterdir()):
        raise ValueError(f"Nonempty frame directory: {frames}; use a clean output directory")

    prior = engine.Actor.draw
    rigby_output = None
    if version == "rigby":
        if rigby_meta is None:
            raise ValueError("Rigby version must supply actual Rigby export metadata")
        rigby_draw, rigby_output = png_actors(rigby_meta)
        engine.Actor.draw = rigby_draw
    elif version != "python":
        raise ValueError("Unknown renderer")
    started = time.perf_counter()
    cpu_started = time.process_time()
    signatures = []
    try:
        for i in range(expected):
            rgb = engine.render_frame(manifest, SHOT, i / FPS,
                                      mode="production", size=SIZE, audio_dir=audio_dir)
            # Lossless PNG frames keep frame rendering and FFmpeg encoding
            # measurable as independent, nonoverlapping phases.
            p = frames / f"frame_{i:03d}.png"
            rgb.save(p, compress_level=1)
            if i in STILLS:
                signatures.append({"frame": i, "rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest()})
    finally:
        engine.Actor.draw = prior
    render_seconds = time.perf_counter() - started
    cpu_seconds = time.process_time() - cpu_started

    if len(list(frames.glob("frame_*.png"))) != expected:
        raise RuntimeError("Frame rendering incomplete")
    if len({item["rgb_sha256"] for item in signatures}) < 2:
        raise RuntimeError("Static animation rejected: scene frames are identical")
    contact = output / ("SHOT_001_" + version + "_contact_sheet.png")
    make_contact_sheet(frames, contact)
    mp4 = output / VIRTUAL_PARTS[version]
    wav = audio_dir / SHOT / "narration.wav"
    srt = audio_dir / SHOT / "dialogue.srt"
    if not srt.exists():
        raise RuntimeError("Missing identical source dialogue subtitles")

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-framerate", str(FPS), "-i", str(frames / "frame_%03d.png"),
               "-i", str(wav), "-i", str(srt),
               "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
               *VIDEO, *AUDIO, "-c:s", "mov_text", "-t", str(DURATION),
               "-frames:v", str(expected), "-movflags", "+faststart",
               "-metadata", "title=Episode 03 SHOT_001 benchmark", str(mp4)]
    encode_at = time.perf_counter()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    subprocess.run(command, check=True)
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    encode_seconds = time.perf_counter() - encode_at
    ffmpeg_user_seconds = child_after.ru_utime - child_before.ru_utime
    ffmpeg_system_seconds = child_after.ru_stime - child_before.ru_stime
    ffmpeg_rss_kb = child_after.ru_maxrss
    validation = inspect(mp4, DURATION, FPS, SIZE)

    report = {
        "status": "technical export passed; creator visual acceptance pending",
        "shot": SHOT, "version": version,
        "character_renderer": "Episode 03 Pillow/NumPy IK" if version == "python"
                              else "Rigby2D official skeletal software renderer",
        "scene_compositor": "animation2d.episode03.engine.render_frame (same in both)",
        "encoder": {"video_args": VIDEO, "audio_args": AUDIO, "fps": FPS,
                    "width": SIZE[0], "height": SIZE[1], "duration": DURATION},
        "source_input": contract,
        "rigby_evidence": rigby_output,
        "frame_render_seconds": render_seconds,
        "frame_render_cpu_seconds_python_process": cpu_seconds,
        "encode_seconds": encode_seconds,
        "encode_cpu_user_seconds_ffmpeg": ffmpeg_user_seconds,
        "encode_cpu_system_seconds_ffmpeg": ffmpeg_system_seconds,
        "ffmpeg_peak_rss_kb": ffmpeg_rss_kb,
        "max_python_process_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "mp4_sha256": sha256(mp4),
        "mp4_bytes": mp4.stat().st_size,
        "frame_sample_hashes": signatures,
        "media_validation": validation,
        "visual_assessment": {
            "facial_expressions": "pending manual matched-frame review",
            "lip_sync": "pending manual matched-frame and audio review",
            "shoulders_elbows": "pending manual joint seam inspection",
            "hand_object_contact": "pending manual contact and release inspection",
            "motion_smoothness": "pending temporal review",
            "character_identity": "pending reference comparison",
        },
    }
    (output / "benchmark.json").write_text(json.dumps(report, indent=2, default=list) + "\n")
    (output / "source_contract.json").write_text(json.dumps(contract, indent=2) + "\n")
    print(json.dumps({
        "mp4": str(mp4), "sha256": report["mp4_sha256"], "bytes": report["mp4_bytes"],
        "frames": expected, "frame_render_s": render_seconds, "encoding_s": encode_seconds,
        "creative_review": "PENDING",
    }, indent=2))
    if os.getenv("KEEP_ALL_FRAMES", "0") != "1":
        shutil.rmtree(frames)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--version", choices=["python", "rigby"], required=True)
    p.add_argument("--audio-dir", type=Path, default=Path("build/shot001/shared_audio"))
    p.add_argument("--rigby-meta", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    render(a.version, a.audio_dir, a.output, a.rigby_meta)
