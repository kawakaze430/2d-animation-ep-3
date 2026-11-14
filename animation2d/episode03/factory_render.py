"""Deterministic, content-addressed, chunk-parallel Episode 03 renderer.

Usage:
  python -m animation2d.episode03.factory_render prepare --manifest BUILD.json --mode blocking
  python -m animation2d.episode03.factory_render chunk --manifest BUILD.json --start 0 --count 60 --output CHUNK
  python -m animation2d.episode03.factory_render assemble --manifest BUILD.json --chunks CHUNKS --output OUTPUT

Every worker samples frames by absolute shot-local time. There are no mutable
animation histories, so incremental cache hits and parallel frame ranges cannot
change motion continuity. Production fails closed on missing rigs/audio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import wave

from PIL import Image, ImageDraw

from .engine import REPO, production_readiness, render_frame
from .render import inspect, planned_subtitles


def load(path):
    result = json.loads(Path(path).read_text())
    if len(result.get("shots", [])) != 1:
        raise ValueError("Factory render expects one compiled JSON scene")
    return result, result["shots"][0]


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def fingerprint(manifest_path, mode="blocking", audio_dir=None, size=(1920, 1080)):
    data, shot = load(manifest_path)
    if mode not in ("blocking", "production"):
        raise ValueError("Unsupported factory mode")
    fps, duration = data.get("fps"), shot.get("duration")
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError("Factory frame rate must be an integer from 1 to 60")
    if type(duration) not in (int, float) or not 0 < duration <= 300:
        raise ValueError("Factory shot duration must be within (0, 300] seconds")
    if abs(duration * fps - round(duration * fps)) > 1e-6:
        raise ValueError("Duration must be an exact whole number of frames")
    if not 1 <= round(duration * fps) <= 18000:
        raise ValueError("Factory frame count must be 1..18000")
    # Avoid cache collisions for changes to physics, compositing, camera or export.
    mandatory = [
        Path(manifest_path), Path(__file__),
        REPO/"animation2d/episode03/engine.py",
        REPO/"animation2d/episode03/actions.py",
        REPO/"animation2d/episode03/motion_clips.py",
        REPO/"animation2d/episode03/factory/clip_library.json",
        REPO/"animation2d/episode03/camera_clips.py",
        REPO/"animation2d/episode03/kinematics.py",
        REPO/"animation2d/episode03/render.py",
    ]
    if shot.get("background"):
        mandatory.append(REPO / shot["background"])
    for actor in shot["cast"]:
        config = data["characters"].get(actor)
        if config is None:
            raise ValueError(f"Missing cast configuration for {actor}")
        rigpath = REPO / config.get("rig", "_missing_rig_")
        if mode == "production":
            mandatory.append(rigpath)
            if rigpath.is_file():
                rig = json.loads(rigpath.read_text())
                for part in rig.get("parts", []):
                    mandatory.append(rigpath.parent / part["file"])
                for file in rig.get("faces", {}).values():
                    mandatory.append(rigpath.parent / file)
    for p in shot.get("props", []) + shot.get("foreground", []):
        if p.get("file"):
            mandatory.append(REPO / p["file"])
    audio = Path(audio_dir) / shot["id"] if audio_dir else None
    if mode == "production":
        if audio is None:
            raise ValueError("Production factory must supply generated speech data")
        for name in ("narration.wav", "dialogue.srt"):
            mandatory.append(audio/name)
        for actor in shot["cast"]:
            mandatory.append(audio/f"{actor}.cues.json")
        errors = production_readiness(data, shot["id"], audio_dir)
        if errors:
            raise ValueError("Production art/cues not ready: " + "; ".join(errors))
        with wave.open(str(audio/"narration.wav")) as w:
            if w.getnchannels() != 2 or abs(w.getnframes()/w.getframerate()-duration) > .02:
                raise ValueError("Production WAV must be stereo and exactly 15 seconds")
    missing = [str(p) for p in mandatory if not p.is_file()]
    if missing:
        raise FileNotFoundError("Factory required source inputs missing: " + ", ".join(missing))
    hashes = {str(p): file_hash(p) for p in sorted(set(mandatory))}
    digest = hashlib.sha256(json.dumps({
        "mode": mode, "size": size, "fps": fps, "duration": duration,
        "sha256": hashes,
    }, sort_keys=True).encode()).hexdigest()
    return {"fingerprint": digest, "assets_sha256": hashes, "mode": mode,
            "shot": shot["id"], "fps": fps, "duration": duration, "size": list(size)}


def _preflight(data, shot, mode, audio_dir):
    if mode != "production":
        return
    errors = production_readiness(data, shot["id"], audio_dir)
    if errors:
        raise RuntimeError("Production mode blocked: " + "; ".join(errors))
    if audio_dir is None or not (Path(audio_dir) / shot["id"] / "narration.wav").is_file():
        raise RuntimeError("Production requires approved real shot audio")


def chunk(manifest, mode, start, count, output, audio_dir=None, size=(1920, 1080)):
    data, shot = load(manifest)
    signature = fingerprint(manifest, mode, audio_dir, size)
    _preflight(data, shot, mode, audio_dir)
    frames = int(round(shot["duration"] * data["fps"]))
    if not 0 <= start < frames or not 0 < count <= frames-start:
        raise ValueError("Chunk range out of bounds")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    expected = [output / f"frame_{i:04}.png" for i in range(start, start+count)]
    report_file = output / "chunk.json"
    if report_file.is_file() and all(p.is_file() for p in expected):
        old = json.loads(report_file.read_text())
        if old.get("fingerprint") == signature["fingerprint"] and old.get("start") == start and old.get("count") == count:
            if all(old.get("hashes", {}).get(p.name) == file_hash(p) for p in expected):
                print(json.dumps({"status": "incremental-cache-hit", "start": start, "count": count}))
                return old
    source = {**data, "__base_dir__": str(REPO)}
    before_wall, before_cpu = time.perf_counter(), time.process_time()
    hashes = {}
    for i, target in enumerate(expected, start=start):
        image = render_frame(source, shot["id"], i / data["fps"], mode=mode,
                             audio_dir=audio_dir, size=size)
        tmp = target.with_suffix(".tmp")
        image.save(tmp, format="PNG", compress_level=1)
        tmp.replace(target)
        hashes[target.name] = file_hash(target)
    result = {
        "status": "rendered-real-production-frames" if mode == "production" else "SCHEMATIC-BLOCKING-NOT-FINAL",
        "fingerprint": signature["fingerprint"],
        "start": start, "count": count, "size": list(size),
        "fps": data["fps"], "frame_render_wall_s": time.perf_counter()-before_wall,
        "frame_render_cpu_s": time.process_time()-before_cpu,
        "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "hashes": hashes,
    }
    report_file.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({key: result[key] for key in ("status","start","count","frame_render_wall_s","max_rss_kb")}))
    return result


def assemble(manifest, mode, chunks_dir, output, audio_dir=None, size=(1920,1080)):
    data, shot = load(manifest)
    signature = fingerprint(manifest, mode, audio_dir, size)
    _preflight(data, shot, mode, audio_dir)
    fps, total = data["fps"], int(round(shot["duration"] * data["fps"]))
    reports, seen = [], {}
    for report_path in Path(chunks_dir).rglob("chunk.json"):
        report = json.loads(report_path.read_text())
        if report["fingerprint"] != signature["fingerprint"] or report["size"] != list(size):
            raise ValueError("Chunk source fingerprint or resolution mismatch")
        for i in range(report["start"], report["start"] + report["count"]):
            frame_path = report_path.parent / f"frame_{i:04}.png"
            if i in seen or not frame_path.is_file():
                raise ValueError("Duplicate or missing rendered frame")
            if file_hash(frame_path) != report["hashes"][frame_path.name]:
                raise ValueError("Cached frame checksum failed")
            seen[i] = frame_path
        reports.append(report)
    if set(seen) != set(range(total)):
        raise ValueError(f"Incomplete frame timeline: {len(seen)}/{total}")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Symlink source frames without copying hundreds of large PNG files.
    frames_folder = output / "frames"
    frames_folder.mkdir(exist_ok=True)
    for i in range(total):
        link = frames_folder / f"frame_{i:04d}.png"
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(seen[i].resolve())
    wav = Path(audio_dir) / shot["id"] / "narration.wav" if audio_dir else None
    srt = Path(audio_dir) / shot["id"] / "dialogue.srt" if audio_dir else None
    srt_output = output / f"{shot['id']}.srt"
    srt_output.write_text(srt.read_text() if srt and srt.is_file() else planned_subtitles(shot))
    video = output / f"{shot['id']}_factory_{mode}.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-framerate", str(fps), "-i", str(frames_folder / "frame_%04d.png")]
    if wav and wav.is_file():
        cmd += ["-i", str(wav)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-i", str(srt_output), "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0",
            "-vsync", "cfr", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", "-ar", "48000", "-c:s", "mov_text",
            "-t", str(shot["duration"]), "-frames:v", str(total),
            "-movflags", "+faststart", str(video)]
    begin = time.perf_counter()
    subprocess.run(cmd, check=True)
    encode_time = time.perf_counter()-begin
    validation = inspect(video, shot["duration"], fps, size)
    contact = Image.new("RGB", (960, 540), "white")
    pen = ImageDraw.Draw(contact)
    for j, index in enumerate([round(i * (total - 1) / 8) for i in range(9)]):
        with Image.open(seen[index]) as source:
            cell = source.convert("RGB").resize((320,180), Image.Resampling.LANCZOS)
        x,y=(j%3)*320,(j//3)*180
        contact.paste(cell, (x,y))
        pen.rectangle((x,y,x+100,y+20),fill="#19242B")
        pen.text((x+7,y+3),f"{index/fps:.2f}s",fill="white")
    contact.save(output/"contact_sheet.png")
    report = {
        "status": "PRODUCTION_TECHNICAL_QA_PASSED_CREATIVE_REVIEW_PENDING"
                    if mode == "production" else "SCHEMATIC_BLOCKING_ONLY",
        "fingerprint": signature["fingerprint"], "mode": mode,
        "output_file": video.name, "output_sha256": file_hash(video),
        "output_bytes": video.stat().st_size,
        "unique_sample_frames": len({file_hash(seen[round(i*(total-1)/3)]) for i in range(4)}),
        "frame_render_wall_s_sum_workers": sum(r["frame_render_wall_s"] for r in reports),
        "encoding_wall_s": encode_time, "workers": reports,
        "media_validation": validation, "creative_review": "PENDING",
        "human_rigging_hours": None,
    }
    (output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"status": report["status"], "file": str(video),
                      "encoder_seconds": encode_time, "bytes": report["output_bytes"]}))
    return report


def main():
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="command", required=True)
    for name in ("prepare","chunk","assemble"):
        sub = s.add_parser(name)
        sub.add_argument("--manifest", type=Path, required=True)
        sub.add_argument("--mode", choices=("blocking","production"), default="blocking")
        sub.add_argument("--audio-dir", type=Path)
        sub.add_argument("--size", default="1920x1080")
        if name == "chunk":
            sub.add_argument("--start", type=int, required=True)
            sub.add_argument("--count", type=int, required=True)
            sub.add_argument("--output", type=Path, required=True)
        if name == "assemble":
            sub.add_argument("--chunks", type=Path, required=True)
            sub.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    size = tuple(int(x) for x in args.size.split("x"))
    if len(size) != 2 or not all(0 < x <= 4096 for x in size):
        p.error("size must be WIDTHxHEIGHT of positive integers up to 4096")
    if args.command == "prepare":
        print(json.dumps(fingerprint(args.manifest, args.mode, args.audio_dir, size), indent=2))
    elif args.command == "chunk":
        chunk(args.manifest, args.mode, args.start, args.count, args.output, args.audio_dir, size)
    else:
        assemble(args.manifest, args.mode, args.chunks, args.output, args.audio_dir, size)


if __name__ == "__main__":
    main()
