"""Run a truthfully matched 15-second Episode03 Python/Pygame raster A/B.

Both backends use the EXACT same compiled SHOT_001 source, scene, artwork, audio,
resolution (1920x1080), 360 timesteps, FFmpeg flags, dialogue subtitles.
"blocking" is diagnostics only; production mode MUST pass authentic art preflight.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import numpy as np
from PIL import Image

from animation2d.episode03.engine import REPO, render_frame, production_readiness
from animation2d.episode03.factory_render import file_hash, fingerprint
from animation2d.episode03.render import inspect, planned_subtitles
from animation2d.episode03.scene_factory import compile_scene
from benchmark.pygame.renderer import render_frame_pygame

HERE = Path(__file__).resolve().parent
SOURCE = REPO / "animation2d/episode03/shots.json"
SHOT = REPO / "animation2d/episode03/factory/scenes/SHOT_001.json"
SIZE = (1920, 1080)
FPS = 24
FRAMES = 360
SAMPLES = (0, 90, 180, 270, 359)


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def prepare(output, mode, audio_dir=None):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    doc = compile_scene(SOURCE, SHOT)
    shot = doc["shots"][0]
    if shot["id"] != "SHOT_001" or shot["duration"] != 15 or doc["fps"] != 24:
        raise ValueError("The benchmark is locked to Episode03 SHOT_001 15s 24fps")
    if doc["canvas"] != list(SIZE):
        raise ValueError("Benchmark requires 1920x1080 project and output")
    if mode not in ("blocking", "production"):
        raise ValueError("mode must be blocking or production")
    if mode == "production":
        issues = production_readiness(doc, shot["id"], audio_dir)
        if issues:
            report = {"status": "BLOCKED_AUTHENTIC_PRODUCTION_ASSETS_MISSING",
                      "issues": issues,
                      "rule": "Never substitute schematic or synthetic art for production benchmark."}
            save_json(root / "preflight.json", report)
            raise ValueError("Authentic production asset preflight: " + "; ".join(issues))
    datafile = root / "scene.json"
    save_json(datafile, doc)
    sign = fingerprint(datafile, mode, audio_dir, SIZE)
    source_art = {}
    base = doc["__base_dir__"] if "__base_dir__" in doc else str(REPO)
    bg = shot.get("background")
    if bg:
        p = Path(base) / bg
        source_art[str(bg)] = file_hash(p)
    if mode == "production":
        for actor in shot["cast"]:
            rigfile = Path(base) / doc["characters"][actor]["rig"]
            source_art[str(rigfile.relative_to(REPO))] = file_hash(rigfile)
            rig = json.loads(rigfile.read_text())
            for x in rig["parts"]:
                p = rigfile.parent / x["file"]
                source_art[str(p.relative_to(REPO))] = file_hash(p)
            for filename in rig.get("faces",{}).values():
                p = rigfile.parent / filename
                source_art[str(p.relative_to(REPO))] = file_hash(p)
    save_json(root / "shared_inputs.json", {
        "status": "AUTHENTIC_PRODUCTION" if mode == "production" else "SCHEMATIC_DIAGNOSTIC_ONLY",
        "sha256": sign["fingerprint"], "source_artwork_sha256": source_art,
        "size": list(SIZE), "fps": FPS, "frames": FRAMES,
        "shot": "SHOT_001", "mode": mode,
        "audio_sha256": (file_hash(Path(audio_dir)/"SHOT_001"/"narration.wav")
                         if audio_dir and mode == "production" else "SILENT_TEST_AUDIO"),
        "scene_sha256": file_hash(datafile),
        "screenplay": [{"speaker": d["speaker"], "text": d["text"]}
                        for d in shot["dialogue"]],
        "limitations": [
            "Schematic mode uses the actual Episode03 reference background and scene, but not approved character rigs",
            "Native Pygame-ce cutout/prop raster still shares Pillow camera crop and PNG vector-prop source generation",
            "No end-to-end production effort or artist hours can be inferred from a renderer-only proof",
        ]
    })
    return root


def render_backend(root, backend, mode, audio_dir=None):
    if backend not in ("pillow","pygame"):
        raise ValueError("Unknown backend")
    root = Path(root)
    inputs = json.loads((root/"shared_inputs.json").read_text())
    if inputs["mode"] != mode:
        raise ValueError("Cannot mix blocking and production in the same benchmark")
    sign = fingerprint(root/"scene.json",mode,audio_dir,SIZE)
    if sign["fingerprint"] != inputs["sha256"]:
        raise ValueError("Inputs changed since prepare")
    if backend == "pygame":
        os.environ.setdefault("SDL_VIDEODRIVER","dummy")
        from benchmark.pygame.renderer import pygame_module
        import pygame
        pygame_module()
    doc = json.loads((root/"scene.json").read_text())
    shot = doc["shots"][0]
    if mode == "production":
        issues=production_readiness(doc, shot["id"], audio_dir)
        if issues:
            raise ValueError("Production artwork/audio missing: " + "; ".join(issues))
    srt = root / "dialogue.srt"
    audio = Path(audio_dir)/"SHOT_001"/"narration.wav" if audio_dir and mode=="production" else None
    if audio_dir and mode=="production":
        srt.write_text((Path(audio_dir)/"SHOT_001"/"dialogue.srt").read_text())
    else:
        srt.write_text(planned_subtitles(shot))
    mp4 = root / (f"SHOT_001_{backend}_{mode}_15s.mp4")
    cmd = ["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y",
           "-f","rawvideo","-pix_fmt","rgb24","-s:v","1920x1080",
           "-r",str(FPS),"-i","pipe:0"]
    if audio is not None:
        cmd += ["-i",str(audio)]
    else:
        cmd += ["-f","lavfi","-i","anullsrc=r=48000:cl=stereo"]
    cmd += ["-i",str(srt), "-map","0:v:0","-map","1:a:0","-map","2:s:0",
            "-c:v","libx264","-preset","veryfast","-crf","20","-threads","2",
            "-pix_fmt","yuv420p","-c:a","aac","-ac","2","-ar","48000",
            "-b:a","192k","-c:s","mov_text",
            "-t","15","-frames:v",str(FRAMES),"-movflags","+faststart",str(mp4)]
    ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    wall_start=time.perf_counter()
    cpu_start=time.process_time()
    draw_s=0.
    samples={}
    try:
        for i in range(FRAMES):
            frame_start=time.perf_counter()
            if backend=="pillow":
                frame = render_frame(doc, "SHOT_001", i/FPS, mode=mode,
                                     size=SIZE, audio_dir=audio_dir)
            else:
                frame = render_frame_pygame(doc, "SHOT_001", i/FPS, mode=mode,
                                            size=SIZE, audio_dir=audio_dir)
            draw_s += time.perf_counter()-frame_start
            if frame.size != SIZE or frame.mode != "RGB":
                raise RuntimeError(f"Backend {backend} returned wrong RGB resolution")
            if i in SAMPLES:
                file=root / f"{backend}_frame_{i:03d}.png"
                frame.save(file,format="PNG",compress_level=3)
                samples[str(i)]=file_hash(file)
            ffmpeg.stdin.write(frame.tobytes())
    except Exception:
        ffmpeg.kill()
        ffmpeg.communicate()
        raise
    finally:
        if ffmpeg.stdin is not None and not ffmpeg.stdin.closed:
            ffmpeg.stdin.close()
    stderr=ffmpeg.stderr.read().decode("utf-8",errors="replace")
    code=ffmpeg.wait()
    if code:
        raise RuntimeError(f"FFmpeg failed for {backend}: {stderr[-1500:]}")
    elapsed=time.perf_counter()-wall_start
    validation=inspect(mp4,15,FPS,SIZE)
    result={
        "backend":backend, "status":inputs["status"],
        "source_fingerprint":inputs["sha256"], "audio_sha256":inputs["audio_sha256"],
        "artwork":inputs["source_artwork_sha256"],
        "sample_frame_sha256":samples, "frames":FRAMES,
        "size":list(SIZE),"fps":FPS,
        "time_wall_s_full_pipeline":elapsed,
        "time_wall_s_draw_only":draw_s,
        "time_cpu_s_python_process":time.process_time()-cpu_start,
        "max_rss_kib_python_process":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "ffmpeg_child_memory_included":False,
        "backend_notes":("Pygame Sprite2D alpha/rotation + PIL shared camera crop"
                         if backend=="pygame" else "Unmodified original Episode03 Pillow renderer"),
        "python_version":sys.version.split()[0],
        "runner":platform.platform(),
        "mp4_file":mp4.name,"mp4_sha256":file_hash(mp4),
        "media_qa":validation,
        "authoring_effort_hours":None,
        "human_visual_approval":"NOT_REVIEWED",
    }
    save_json(root / (backend+"_metrics.json"),result)
    print(json.dumps({key:result[key] for key in ("backend","status","frames","time_wall_s_full_pipeline",
                        "time_wall_s_draw_only","max_rss_kib_python_process")}))
    return result


def report(root):
    root=Path(root)
    a=json.loads((root/"pillow_metrics.json").read_text())
    b=json.loads((root/"pygame_metrics.json").read_text())
    shared=json.loads((root/"shared_inputs.json").read_text())
    for field in ("source_fingerprint","audio_sha256","artwork","fps","frames","size"):
        if a[field]!=b[field]:
            raise ValueError(f"Comparison input parity failed for {field}")
    if a["source_fingerprint"]!=shared["sha256"]:
        raise ValueError("Compared engines used different source snapshot")
    if a["frames"]!=360 or a["size"]!=list(SIZE):
        raise ValueError("Not the requested real 15-second 1080p benchmark")
    errors=[]
    for t in SAMPLES:
        pa=root / f"pillow_frame_{t:03d}.png"
        pb=root / f"pygame_frame_{t:03d}.png"
        if file_hash(pa)!=a["sample_frame_sha256"][str(t)] or file_hash(pb)!=b["sample_frame_sha256"][str(t)]:
            raise ValueError("Sample was modified after rendering")
        with Image.open(pa) as i, Image.open(pb) as j:
            x=np.asarray(i.convert("RGB"),dtype=np.int16)
            y=np.asarray(j.convert("RGB"),dtype=np.int16)
        errors.append({"frame":t,"mean_absolute_rgb_error_255":float(np.abs(x-y).mean())})
    if len(set(a["sample_frame_sha256"].values()))<2 or len(set(b["sample_frame_sha256"].values()))<2:
        raise ValueError("Static or invalid renderer output")
    perf_ratio=b["time_wall_s_draw_only"]/max(1e-9,a["time_wall_s_draw_only"])
    result={
        "status": "PRODUCTION_TECHNICAL_QA_CREATIVE_APPROVAL_REQUIRED"
             if shared["mode"]=="production" else "SCHEMATIC_DIAGNOSTIC_ONLY_NOT_PRODUCTION",
        "mode":shared["mode"],
        "shared_inputs_sha256":shared["sha256"], "art_sha256":shared["source_artwork_sha256"],
        "pillow":a,"pygame":b,
        "draw_time_ratio_pygame_to_pillow":perf_ratio,
        "visual_differences":errors,
        "authoring_effort_hours":None,
        "github_actions_runtime_s":None,
        "creative_issues":"Requires review of face identity, mouth shapes, hand contact, depth, camera, deformation and lighting.",
        "decision":"Retain Pillow/FFmpeg. No migration without fully approved art, real A/B, quality and person-hours.",
    }
    save_json(root/"comparison.json",result)
    md=[
        "# Episode 03 SHOT_001 15-second Python Pillow vs Pygame-ce",
        "", "**"+result["status"]+"**", "",
        "Both versions use the same source scene, actual environment art, 1920×1080, 24fps, 360 frames, dialogue/subtitles, and identical FFmpeg parameters.",
        "This does NOT prove final production visual quality: original character cutout art and voice data remain missing unless production mode passed preflight.",
        "",
        "| Metric | Existing Pillow | Pygame-ce experimental |","|---|---:|---:|",
        f"| Renderer drawing time (s) | {a['time_wall_s_draw_only']:.3f} | {b['time_wall_s_draw_only']:.3f} |",
        f"| Full render+FFmpeg wall time (s) | {a['time_wall_s_full_pipeline']:.3f} | {b['time_wall_s_full_pipeline']:.3f} |",
        f"| Python process maximum RSS (KiB) | {a['max_rss_kib_python_process']} | {b['max_rss_kib_python_process']} |",
        f"| Frames | {a['frames']} | {b['frames']} |",
        "", "The Pygame prototype still shares Pillow camera cropping and tiny vector-prop source sprite generation; CPU/FFmpeg memory is not fully isolated.",
        "Quality/authoring effort cannot be extrapolated from frame speed. FFmpeg codecs and soundtrack are identical.",
        "", "## Visual sample error (differences are expected)", "",
        *[f"- Frame {e['frame']}: {e['mean_absolute_rgb_error_255']:.3f}/255 average absolute RGB error" for e in errors],
        "", "## Decision", "",
        result["decision"],
        "",
    ]
    (root/"REPORT.md").write_text("\n".join(md))
    print(json.dumps({"status":result["status"],"ratio":perf_ratio,"decision":result["decision"]}))
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=("prepare","render","report"))
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--mode",choices=("blocking","production"),default="blocking")
    p.add_argument("--backend",choices=("pillow","pygame"))
    p.add_argument("--audio-dir",type=Path)
    args=p.parse_args()
    if args.command=="prepare":
        prepare(args.output,args.mode,args.audio_dir)
    elif args.command=="render":
        if args.backend is None:
            p.error("render requires --backend")
        render_backend(args.output,args.backend,args.mode,args.audio_dir)
    else:
        report(args.output)


if __name__=="__main__":
    main()
