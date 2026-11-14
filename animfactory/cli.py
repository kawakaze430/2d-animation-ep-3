"""Small local CLI for the independent product. No billable external services."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import time

from .editing import EditSession
from .project import Project, hash_file


def _project(path):
    return Project.open(path)


def _encode_video(project, scene_id, output, *, mode, frame_limit):
    """Deterministic FFmpeg H.264 export using the authoritative Pillow renderer.

    Explicit short frame_limit is the default development behavior. No voice
    synthesis, paid GPU, AI inference or unseen scene rewrite.
    """
    output = Path(output)
    if output.exists():
        raise FileExistsError("Export output already exists; choose a new filename")
    scene = next((scene for scene in project.doc["scenes"] if scene["id"] == scene_id), None)
    if scene is None:
        raise ValueError(f"Unknown scene {scene_id}")
    width, height = project.doc["canvas"]
    if width % 2 or height % 2:
        raise ValueError("H.264 yuv420p needs even canvas width and height")
    if type(frame_limit) is not int or frame_limit < 1:
        raise ValueError("Export frame count must be positive")
    count = min(frame_limit, scene["frames"])
    if count > 240:
        raise ValueError("Large exports require the existing explicit GitHub Actions workflow")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
           "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", f"{width}x{height}", "-framerate", str(project.doc["fps"]),
           "-i", "pipe:0", "-frames:v", str(count),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    started = time.perf_counter()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(count):
            image = project.render_frame(scene_id, i, mode=mode)
            proc.stdin.write(image.tobytes())
        proc.stdin.close()
        errors = proc.stderr.read().decode(errors="replace")
        code = proc.wait()
        if code:
            raise RuntimeError(f"FFmpeg error: {errors[-900:]}")
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        output.unlink(missing_ok=True)
        raise
    ffprobe = subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames",
        "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames,width,height,r_frame_rate",
        "-of", "json", str(output)], text=True)
    stream = json.loads(ffprobe)["streams"][0]
    if (int(stream["nb_read_frames"]) != count
            or int(stream["width"]) != width
            or int(stream["height"]) != height):
        output.unlink(missing_ok=True)
        raise RuntimeError("FFprobe output does not match source frame count and size")
    report = {
        "schema": "animfactory.render_report.v1",
        "project": project.doc["id"], "scene": scene_id,
        "mode": mode, "frames": count, "fps": project.doc["fps"],
        "canvas": project.doc["canvas"], "status": (
            "TECHNICAL_SILENT_RENDER_NOT_CREATIVE_APPROVAL"
            if mode == "production" else "SCHEMATIC_BLOCKING_TECHNICAL_ONLY"),
        "media_sha256": hash_file(output), "seconds": time.perf_counter()-started,
        "audio": "none", "provider": "local Pillow/FFmpeg; no paid services",
    }
    report_path = output.with_name(output.name + ".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(prog="animfactory", description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Create independent v1 project folder")
    init.add_argument("directory", type=Path)
    init.add_argument("--id", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--size", nargs=2, type=int, default=(960, 540), metavar=("W", "H"))
    init.add_argument("--fps", type=int, default=24)

    rig = commands.add_parser("import-rig", help="Validate/copy 15-part rig and art")
    rig.add_argument("project", type=Path)
    rig.add_argument("source", type=Path)
    rig.add_argument("character")
    rig.add_argument("--license", default="unspecified")
    rig.add_argument("--source-label", default="user-import")

    image = commands.add_parser("import-png", help="Import an image/background/prop PNG")
    image.add_argument("project", type=Path)
    image.add_argument("source", type=Path)
    image.add_argument("id")
    image.add_argument("--kind", default="image", choices=("image", "background", "prop", "reference"))
    image.add_argument("--license", default="unspecified")
    image.add_argument("--source-label", default="user-import")

    motion = commands.add_parser("add-motion", help="Import JSON clip definition")
    motion.add_argument("project", type=Path)
    motion.add_argument("id")
    motion.add_argument("json_file", type=Path)
    motion.add_argument("--pose", action="store_true")

    sc = commands.add_parser("add-scene", help="Create a shot-free scene and camera")
    sc.add_argument("project", type=Path)
    sc.add_argument("id")
    sc.add_argument("--frames", type=int, required=True)

    actor = commands.add_parser("add-actor", help="Place imported rig in a scene")
    actor.add_argument("project", type=Path)
    actor.add_argument("scene")
    actor.add_argument("id")
    actor.add_argument("character")
    actor.add_argument("--x", type=float, required=True)
    actor.add_argument("--y", type=float, required=True)
    actor.add_argument("--scale", type=float, default=1)

    act = commands.add_parser("add-action", help="Assign reusable motion by frames")
    act.add_argument("project", type=Path)
    act.add_argument("scene")
    act.add_argument("actor")
    act.add_argument("id")
    act.add_argument("clip")
    act.add_argument("--start", type=int, required=True)
    act.add_argument("--end", type=int, required=True)
    act.add_argument("--source")
    act.add_argument("--target", nargs=2, type=float)
    act.add_argument("--hand", choices=("left", "right"))

    edit = commands.add_parser("edit", help="Apply one transactional JSON edit")
    edit.add_argument("project", type=Path)
    edit.add_argument("command_json", type=Path)

    check = commands.add_parser("check", help="Validate schema and all asset hashes")
    check.add_argument("project", type=Path)

    catalog = commands.add_parser("motions", help="Search the product's motion catalog")
    catalog.add_argument("project", type=Path)
    catalog.add_argument("--query", default="")
    catalog.add_argument("--category", default="")

    preview = commands.add_parser("frame", help="Save one genuine renderer PNG")
    preview.add_argument("project", type=Path)
    preview.add_argument("scene")
    preview.add_argument("--index", type=int, default=0)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--mode", choices=("blocking", "production"), default="blocking")

    export = commands.add_parser("export", help="Encode short technical H.264 movie")
    export.add_argument("project", type=Path)
    export.add_argument("scene")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--frames", type=int, default=4)
    export.add_argument("--mode", choices=("blocking", "production"), default="blocking")

    server = commands.add_parser("studio", help="Open local browser timeline editor")
    server.add_argument("project", type=Path)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8190)

    args = p.parse_args(argv)
    if args.command == "init":
        project = Project.create(args.directory, args.id, args.title,
                                 canvas=args.size, fps=args.fps)
        result = {"project": project.doc["id"], "path": str(project.root)}
    else:
        project = _project(args.project)
        if args.command == "import-rig":
            result = {"asset": project.import_rig(args.source, args.character,
                      source_label=args.source_label, license_label=args.license)}
        elif args.command == "import-png":
            result = {"asset": project.import_image(args.source, args.id, kind=args.kind,
                      source_label=args.source_label, license_label=args.license)}
        elif args.command == "add-motion":
            definition = json.loads(args.json_file.read_text())
            project.add_motion(args.id, definition, pose=args.pose)
            result = {"motion": args.id}
        elif args.command == "add-scene":
            project.add_scene(args.id, args.frames)
            result = {"scene": args.id, "frames": args.frames}
        elif args.command == "add-actor":
            project.add_actor(args.scene, args.id, args.character,
                              (args.x, args.y), args.scale)
            result = {"actor": args.id}
        elif args.command == "add-action":
            project.add_action(args.scene, args.actor, args.id, args.clip,
                               args.start, args.end, source=args.source,
                               target=args.target, hand=args.hand)
            result = {"action": args.id}
        elif args.command == "edit":
            editor = EditSession(project)
            editor.apply(json.loads(args.command_json.read_text()))
            result = {"edited": True}
        elif args.command == "check":
            result = {"status": "valid", "assets": len(project.doc["assets"]),
                      "scenes": len(project.doc["scenes"])}
        elif args.command == "motions":
            result = {"motions": project.motion_registry(args.query, args.category)}
        elif args.command == "frame":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            project.render_frame(args.scene, args.index, mode=args.mode).save(args.output, format="PNG")
            result = {"frame": args.index, "file": str(args.output)}
        elif args.command == "export":
            result = _encode_video(project, args.scene, args.output,
                                   mode=args.mode, frame_limit=args.frames)
        elif args.command == "studio":
            if args.host not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Studio binds to loopback only; use an authenticated proxy for remote access")
            from .studio import serve
            serve(project, args.host, args.port)
            return
        else:
            p.error("Unknown command")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
