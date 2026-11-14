"""Shared, fail-closed SHOT_001 input contract for both production renderers."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import wave

from PIL import Image, ImageOps

from animation2d.episode03.engine import Actor, production_readiness

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "animation2d/episode03/shots.json"
CAST = ("DAN", "MAYA", "NINA")
SHOT = "SHOT_001"
FPS, DURATION = 24, 15
SIZE = (1920, 1080)
LINES = (
    ("MAYA", "Pancakes, just as promised."),
    ("DAN", "I am ready to help. Sensible quantities, no size records."),
    ("NINA", "Then breakfast has an excellent start."),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def load_contract() -> tuple[dict, dict]:
    data = json.loads(MANIFEST.read_text())
    shot = next((s for s in data["shots"] if s["id"] == SHOT), None)
    if shot is None:
        raise ValueError("Missing Episode 03 SHOT_001")
    assert data["canvas"] == list(SIZE) and data["fps"] == FPS
    assert shot["duration"] == DURATION and tuple(shot["cast"]) == CAST
    assert tuple((d["speaker"], d["text"]) for d in shot["dialogue"]) == LINES
    assert shot["location"] == "HOME_KITCHEN"
    assert shot["camera"] == {"zoom": 1, "center": [960, 540]}
    assert {"recipe_card", "blue_bowl"} <= {p["id"] for p in shot["props"]}
    assert shot["source"]["action"].startswith("Maya places one pancake recipe card")
    # A single shot-specific choreography correction is shared by both engines.
    # The baseline's 15-second reach end would drop the props at 2/2.5 seconds
    # before either hand reached the destination. Nina's left hand was not selected.
    # Move Nina within actual arm reach without altering camera or story/dialogue.
    shot["actors"]["MAYA"]["action"].update({"kind": "reach", "hand": "right", "start": 0, "end": 2.0})
    shot["actors"]["NINA"]["position"] = [1250, 650]
    shot["actors"]["NINA"]["action"].update({"kind": "reach", "hand": "left", "start": 0, "end": 2.5})
    shot["actors"]["DAN"]["action"].update({"kind": "gesture", "hand": "right", "start": 2.72, "end": 7.27})
    for prop in shot["props"]:
        if prop["id"] == "blue_bowl":
            prop.update({"shape": "ellipse", "size": [115, 65], "color": "#2447B9"})
        elif prop["id"] == "yellow_bowl":
            prop.update({"shape": "ellipse", "size": [110, 60], "color": "#D5B33D"})
        elif prop["id"] == "recipe_card":
            prop.update({"shape": "rectangle", "size": [85, 105], "color": "#F1ECE4"})
    shot["props"].append({"id": "recipe_stand", "shape": "rectangle",
                          "size": [105, 15], "color": "#73513A",
                          "position": [590, 680], "depth": 202})
    data["__base_dir__"] = str(ROOT)
    return data, shot


def inputs(audio_dir: Path, require_audio=True) -> dict:
    """Never allow schematic art, silent clips or missing mouth shapes into a benchmark."""
    data, shot = load_contract()
    issues = production_readiness(data, SHOT, audio_dir=audio_dir if require_audio else None)
    folder = audio_dir / SHOT
    narrator = folder / "narration.wav"
    if require_audio:
        if not narrator.is_file():
            issues.append(f"Missing shared narration: {narrator}")
        else:
            with wave.open(str(narrator)) as w:
                if w.getnchannels() != 2 or w.getframerate() != 24000 or w.getnframes() < 24000:
                    issues.append("Shared narration is not nonempty stereo 24 kHz WAV")
        timing = folder / "timings.json"
        if not timing.is_file():
            issues.append("Missing measured speech timings.json")
        else:
            times = json.loads(timing.read_text())
            if tuple((x["speaker"], x["text"]) for x in times.get("dialogue", [])) != LINES:
                issues.append("Synthesized speech texts differ from SHOT_001 screenplay")
            if narrator.is_file() and times.get("narration_sha256") != sha256(narrator):
                issues.append("Narration checksum differs from speech synthesis report")
        for actor in CAST:
            cue_file = folder / f"{actor}.cues.json"
            if not cue_file.is_file():
                issues.append(f"Missing {actor} Rhubarb cues")
                continue
            cues = json.loads(cue_file.read_text()).get("mouthCues", [])
            if not cues or all(c["value"] == "X" for c in cues):
                issues.append(f"{actor}: no nonneutral lip-sync cues")
    if issues:
        raise RuntimeError("PRODUCTION BENCHMARK BLOCKED:\n" + "\n".join(issues))
    paths = [MANIFEST, ROOT / shot["background"]]
    for actor in CAST:
        config = data["characters"][actor]
        for label in ("portrait", "sheet"):
            paths.append(ROOT / config["reference"][label])
        rig_path = ROOT / config["rig"]
        rig = json.loads(rig_path.read_text())
        paths.append(rig_path)
        paths += [rig_path.parent / p["file"] for p in rig["parts"]]
        paths += [rig_path.parent / p for p in rig.get("faces", {}).values()]
        if require_audio:
            paths.append(folder / f"{actor}.cues.json")
    if require_audio:
        paths.extend((narrator, folder / "timings.json"))
    return {
        "shot": SHOT,
        "canvas": list(SIZE),
        "fps": FPS,
        "duration": DURATION,
        "dialogue": [list(row) for row in LINES],
        "shot_choreography_sha256": hashlib.sha256(json.dumps(shot, sort_keys=True).encode()).hexdigest(),
        "input_sha256": {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name: sha256(p)
                         for p in sorted(set(paths))},
        "narration_sha256": sha256(narrator) if require_audio else None,
    }


def stage_rigby(audio_dir: Path, output: Path) -> Path:
    """Translate the *same* production sprites and authored Python action into Rigby bones.

    Rigby evaluates and renders the resulting animated bones; there is no Python
    re-render or substituted labelled/still character in Version B.
    """
    import numpy as np
    data, shot = load_contract()
    inputs(audio_dir)
    output.mkdir(parents=True, exist_ok=True)
    project = {"version": 1, "shot": SHOT, "fps": FPS, "duration": DURATION, "cast": CAST,
               "actors": {}}
    for actor_id in CAST:
        actor = Actor(actor_id, data["characters"][actor_id],
                      shot["actors"][actor_id], mode="production", base_dir=ROOT,
                      cues=json.loads((audio_dir / SHOT / f"{actor_id}.cues.json").read_text())["mouthCues"])
        location = np.asarray(actor.placement["position"], dtype=float)
        pieces = []
        for p in actor.parts:
            source = Path(p["path"])
            img = Image.open(source).convert("RGBA")
            pivot = list(p["pivot"])
            end = list(p.get("source_end", [pivot[0], pivot[1] + 1]))
            if p.get("mirror"):
                img = ImageOps.mirror(img)
                pivot[0] = img.width - 1 - pivot[0]
                end[0] = img.width - 1 - end[0]
            if (np.linalg.norm(np.asarray(end) - pivot) <= 1e-6):
                raise ValueError(f"{actor_id}/{p['id']}: zero source bone length")
            new_path = output / f"{actor_id}_{p['id']}.png"
            img.save(new_path)
            pieces.append({"id": p["id"], "bone": p["bone"], "image": new_path.name,
                           "width": img.width, "height": img.height, "pivot": pivot,
                           "source_end": end, "depth": p.get("depth", 0),
                           "frames": []})
        faces = {}
        for shape, src in actor.face_parts.items():
            img = Image.open(src).convert("RGBA")
            dest = output / f"{actor_id}_face_{shape}.png"
            img.save(dest)
            faces[shape] = {"image": dest.name, "width": img.width, "height": img.height}
        # Six-frame spacing: Rigby interpolates independent bone positions,
        # angles, and scales on its own runtime between authored keys.
        sample_times = [i / FPS for i in range(0, DURATION * FPS, 6)] + [DURATION]
        for t in sample_times:
            pose = actor.pose(min(t, DURATION - 1e-7), DURATION)
            for p in pieces:
                start, end = map(lambda v: np.asarray(v, dtype=float), pose["bones"][p["bone"]])
                pv, src_end = map(lambda v: np.asarray(v, dtype=float), (p["pivot"], p["source_end"]))
                axis = src_end - pv
                vec = end - start
                angle = math.degrees(math.atan2(-vec[1], vec[0]) - math.atan2(-axis[1], axis[0]))
                factor = float(np.linalg.norm(vec) / np.linalg.norm(axis)) if "source_end" in next(
                    x for x in actor.parts if x["id"] == p["id"]) else pose["scale"]
                previous = p["frames"][-1][3] if p["frames"] else angle
                angle += 360 * round((previous - angle) / 360)
                p["frames"].append([round(t, 6), float(start[0] - location[0]),
                                    float(location[1] - start[1]), angle, factor])
        cue_keys = [[0.0, "X"]]
        for c in actor.cues:
            cue_keys.extend(([float(c["start"]), c["value"]], [float(c["end"]), "X"]))
        # Python renders periodic blink if the rig author provided a shape.
        # Keep it explicit for review: the benchmark only tests the same mouth
        # cues; a source-specific blink sprite never gets silently manufactured.
        project["actors"][actor_id] = {
            "origin": location.tolist(), "parts": pieces,
            "faces": faces, "mouth_keys": sorted(cue_keys, key=lambda x: x[0]),
        }
    target = output / "rigby_stage.json"
    target.write_text(json.dumps(project, indent=2) + "\n")
    return target


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--audio-dir", type=Path, default=Path("build/shot001/shared_audio"))
    p.add_argument("--stage", type=Path)
    p.add_argument("--check-art-only", action="store_true")
    args = p.parse_args()
    try:
        report = inputs(args.audio_dir, require_audio=not args.check_art_only)
    except Exception as exc:
        print(str(exc))
        raise SystemExit(2) from exc
    if args.stage:
        report["rigby_stage"] = str(stage_rigby(args.audio_dir, args.stage))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
