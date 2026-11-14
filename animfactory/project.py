"""Project storage, safe rig imports, generic scene compilation and Pillow renderer.

A project is self-contained: project.json + assets/rigs/<character>/*.png.
The project does not import/modify Episode03 screenplay or save transient
renderer manifests. Assets are local, content-addressed and carry provenance.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .schema import empty_project, safe_path, stable_bytes, validate_project, valid_id, number, point

PROJECT_FILE = "project.json"
BONES = {"head", "torso", "pelvis"} | {
    f"{bone}.{side}" for bone in ("upper_arm", "forearm", "hand", "thigh", "shin", "foot")
    for side in ("left", "right")
}
ACTOR_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def hash_file(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            sha.update(part)
    return sha.hexdigest()


def _contained(root, relative):
    safe_path(relative, "asset")
    root = Path(root).resolve()
    file = (root / relative).resolve()
    if not file.is_relative_to(root):
        raise ValueError("Asset path resolves outside project directory")
    return file


def _image_ok(path):
    from PIL import Image
    with Image.open(path) as img:
        if img.format != "PNG" or "A" not in img.getbands():
            raise ValueError(f"{path.name}: rig parts must be transparent PNGs")
        lo, hi = img.getchannel("A").getextrema()
        if lo >= 255 or hi == 0:
            raise ValueError(f"{path.name}: PNG requires visible and transparent pixels")
        if max(img.size) > 8192 or min(img.size) < 1:
            raise ValueError(f"{path.name}: unreasonably large or empty PNG")


def _read_rig(source):
    root = Path(source).resolve()
    if not root.is_file() or root.suffix.lower() != ".json":
        raise ValueError("Choose an existing version-1 rig.json")
    data = json.loads(root.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Require original Episode03-compatible version-1 rig.json")
    parts = data.get("parts")
    if not isinstance(parts, list):
        raise ValueError("Rig must declare 15 parts")
    seen = set()
    files = {"rig.json": root}
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError("Rig part must be a JSON object")
        bone = part.get("bone")
        if bone not in BONES or bone in seen:
            raise ValueError(f"Unknown or duplicate rig bone: {bone}")
        seen.add(bone)
        point(part.get("pivot"), f"{bone}.pivot")
        if "source_end" in part:
            point(part["source_end"], f"{bone}.source_end")
        filename = safe_path(part.get("file"), "rig part path")
        if not filename.lower().endswith(".png"):
            raise ValueError(f"{bone}: only PNG part art allowed")
        sprite = _contained(root.parent, filename)
        if not sprite.is_file():
            raise ValueError(f"{bone}: missing source PNG {filename}")
        _image_ok(sprite)
        files[filename] = sprite
    if seen != BONES:
        raise ValueError(f"Rig missing required bones: {sorted(BONES-seen)}")
    faces = data.get("faces", {})
    if not isinstance(faces, dict):
        raise ValueError("Rig faces must be a JSON object")
    for key, filename in faces.items():
        if not isinstance(key, str) or not key or len(key) > 32:
            raise ValueError("Invalid facial pose key")
        filename = safe_path(filename, "face path")
        if not filename.lower().endswith(".png"):
            raise ValueError("Face sprites must be PNG")
        sprite = _contained(root.parent, filename)
        if not sprite.is_file():
            raise ValueError(f"Missing face sprite: {filename}")
        _image_ok(sprite)
        files[filename] = sprite
    for key, value in data.get("anchors", {}).items():
        point(value, "anchor " + str(key))
    for key, value in data.get("lengths", {}).items():
        number(value, "bone length " + str(key), minimum=1e-6)
    return data, files


class Project:
    """In-process project facade; never overwrites an imported asset on re-import."""

    def __init__(self, root, doc):
        self.root = Path(root).resolve()
        self.doc = validate_project(doc)

    @classmethod
    def create(cls, directory, project_id, title, *, canvas=(960, 540), fps=24):
        directory = Path(directory).resolve()
        if directory.is_symlink() or (directory.exists() and any(directory.iterdir())):
            raise FileExistsError("Create requires a new/empty project directory")
        directory.mkdir(parents=True, exist_ok=True)
        project = cls(directory, empty_project(project_id, title, canvas=canvas, fps=fps))
        project.save()
        return project

    @classmethod
    def open(cls, directory, *, verify_assets=True):
        root = Path(directory).resolve()
        project = cls(root, json.loads((root / PROJECT_FILE).read_text(encoding="utf-8")))
        if verify_assets:
            project.verify_assets()
        return project

    def save(self):
        payload = stable_bytes(self.doc)
        self.root.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.root,
                                             prefix=".project-", suffix=".tmp",
                                             delete=False) as stream:
                temp = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.root / PROJECT_FILE)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def verify_assets(self):
        for aid, asset in self.doc["assets"].items():
            path = _contained(self.root, asset["path"])
            if not path.is_file() or hash_file(path) != asset["sha256"]:
                raise ValueError(f"{aid}: missing/corrupted asset {path}")
            if "files" in asset:
                for rel, digest in asset["files"].items():
                    data = _contained(path.parent, rel)
                    if not data.is_file() or hash_file(data) != digest:
                        raise ValueError(f"{aid}: missing/corrupted rig layer {rel}")
        return True

    def import_rig(self, source, character_id, *, source_label="user-import",
                   license_label="unspecified"):
        valid_id(character_id, "character ID")
        if any(c not in ACTOR_NAME_CHARS for c in character_id) or len(character_id) > 32:
            raise ValueError("Renderer character IDs must use letters/digits/underscore <=32 characters")
        if character_id in self.doc["characters"]:
            raise FileExistsError(f"Character already registered: {character_id}")
        rig, files = _read_rig(source)
        target = self.root / "assets" / "rigs" / character_id
        if target.exists():
            raise FileExistsError("Destination rig already exists; imports never overwrite")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=".import-") as temp:
            stage = Path(temp)
            for rel, original in files.items():
                output = stage / rel
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, output)
            stage_rig = stage / "rig.json"
            if "rig.json" not in files or stage_rig.read_bytes() != Path(source).read_bytes():
                raise ValueError("Rig source bytes changed during import")
            records = {name: hash_file(stage / name) for name in sorted(files)}
            stage.rename(target)
        asset_id = character_id + "_rig"
        if asset_id in self.doc["assets"]:
            raise FileExistsError(f"Asset ID collision: {asset_id}")
        relative = (target / "rig.json").relative_to(self.root).as_posix()
        updated = deepcopy(self.doc)
        updated["assets"][asset_id] = {
            "kind": "rig", "path": relative, "sha256": records["rig.json"],
            "files": records, "source": source_label, "license": license_label,
        }
        updated["characters"][character_id] = {
            "rig_asset": asset_id, "tags": [], "rig_format": "episode03-cutout-v1",
        }
        try:
            self.doc = validate_project(updated)
            self.save()
        except Exception:
            shutil.rmtree(target)
            raise
        return asset_id

    def import_image(self, source, asset_id, *, kind="image",
                     source_label="user-import", license_label="unspecified"):
        valid_id(asset_id, "asset ID")
        if kind not in ("image", "background", "prop", "reference"):
            raise ValueError("Import source images as image/background/prop/reference")
        if asset_id in self.doc["assets"]:
            raise FileExistsError(f"Duplicate asset ID {asset_id}")
        from PIL import Image
        source = Path(source).resolve()
        with Image.open(source) as im:
            if im.format != "PNG":
                raise ValueError("Current asset importer accepts PNG only; PSD/SVG adapters are pending")
            if max(im.size) > 8192:
                raise ValueError("PNG exceeds current size bound")
        target = self.root / "assets" / "images" / (asset_id + ".png")
        if target.exists():
            raise FileExistsError("Asset already exists on disk")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entry = {"kind": kind, "path": target.relative_to(self.root).as_posix(),
                 "sha256": hash_file(target), "source": source_label,
                 "license": license_label}
        updated = deepcopy(self.doc)
        updated["assets"][asset_id] = entry
        try:
            self.doc = validate_project(updated)
            self.save()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return asset_id

    def add_motion(self, name, clip_definition, *, pose=False):
        valid_id(name, "motion name")
        bucket = "poses" if pose else "clips"
        updated = deepcopy(self.doc)
        if name in updated["motion_library"][bucket]:
            raise FileExistsError(f"Motion already exists: {name}")
        updated["motion_library"][bucket][name] = deepcopy(clip_definition)
        self.doc = validate_project(updated)
        self.save()

    def add_scene(self, scene_id, frames, *, camera=None):
        valid_id(scene_id, "scene ID")
        if type(frames) is not int or frames < 1:
            raise ValueError("Scene duration must be a positive integer frame count")
        new = deepcopy(self.doc)
        new["scenes"].append({
            "id": scene_id, "frames": frames, "camera": camera or {
                "center": [self.doc["canvas"][0]/2, self.doc["canvas"][1]/2],
                "zoom": 1,
            },
            "actors": [], "props": [], "dialogue": [],
        })
        self.doc = validate_project(new)
        self.save()

    def add_actor(self, scene_id, actor_id, character_id, position, scale=1, depth=100):
        valid_id(actor_id, "scene actor ID")
        if actor_id not in {"_"} and (any(c not in ACTOR_NAME_CHARS for c in actor_id)
                                     or len(actor_id) > 32):
            raise ValueError("Actor instance ID must be renderer-compatible")
        new = deepcopy(self.doc)
        scene = next((s for s in new["scenes"] if s["id"] == scene_id), None)
        if scene is None:
            raise ValueError(f"Unknown scene {scene_id}")
        scene["actors"].append({"id": actor_id, "character": character_id,
                                "position": list(position), "scale": scale,
                                "depth": depth, "actions": []})
        self.doc = validate_project(new)
        self.save()

    def add_action(self, scene_id, actor_id, action_id, kind, start_frame, end_frame,
                   *, source=None, target=None, hand=None):
        new = deepcopy(self.doc)
        scene = next((s for s in new["scenes"] if s["id"] == scene_id), None)
        if scene is None:
            raise ValueError("Unknown scene")
        actor = next((a for a in scene["actors"] if a["id"] == actor_id), None)
        if actor is None:
            raise ValueError("Unknown actor")
        item = {"id": action_id, "clip": kind, "start_frame": start_frame,
                "end_frame": end_frame}
        if source is not None:
            item["source"] = source
        if target is not None:
            item["target"] = list(target)
        if hand is not None:
            item["hand"] = hand
        actor["actions"].append(item)
        self.doc = validate_project(new)
        self.save()

    def compile_scene(self, scene_id):
        """Translate product data into an existing engine manifest WITHOUT rewriting it."""
        doc = validate_project(self.doc)
        scene = next((x for x in doc["scenes"] if x["id"] == scene_id), None)
        if scene is None:
            raise ValueError(f"Unknown scene {scene_id}")
        fps = doc["fps"]
        actors, characters = {}, {}
        for instance in scene["actors"]:
            instance_id = instance["id"]
            character = doc["characters"][instance["character"]]
            rig_asset = doc["assets"][character["rig_asset"]]
            characters[instance_id] = {"rig": rig_asset["path"]}
            actions = []
            for action in instance["actions"]:
                selected = {k: deepcopy(v) for k, v in action.items()
                            if k not in ("id", "start_frame", "end_frame")}
                selected["start"] = action["start_frame"] / fps
                selected["end"] = action["end_frame"] / fps
                actions.append(selected)
            actors[instance_id] = {
                "position": instance["position"], "scale": instance.get("scale", 1),
                "depth": instance.get("depth", 100), "foot_lock": True,
                "actions": actions,
            }
        shot = {
            "id": scene["id"], "duration": scene["frames"] / fps,
            "cast": list(actors), "actors": actors,
            "props": deepcopy(scene.get("props", [])),
            "dialogue": deepcopy(scene.get("dialogue", [])),
            "camera": deepcopy(scene["camera"]),
        }
        if "camera_animation" in scene:
            shot["camera_animation"] = deepcopy(scene["camera_animation"])
        if scene.get("background_asset"):
            shot["background"] = doc["assets"][scene["background_asset"]]["path"]
        return {
            "fps": fps, "canvas": deepcopy(doc["canvas"]),
            "characters": characters, "shots": [shot],
            "motion_library": deepcopy(doc["motion_library"]),
            "__base_dir__": str(self.root),
        }

    def render_frame(self, scene_id, frame=0, *, size=None, mode="blocking"):
        from animation2d.episode03.engine import render_frame
        scene = next((s for s in self.doc["scenes"] if s["id"] == scene_id), None)
        if scene is None or type(frame) is not int or not 0 <= frame < scene["frames"]:
            raise ValueError("Choose an existing scene and an in-range integer frame")
        return render_frame(self.compile_scene(scene_id), scene_id, frame/self.doc["fps"],
                            mode=mode, size=tuple(size or self.doc["canvas"]))

    def motion_registry(self, query="", category=""):
        """Product-scoped searchable catalog, no provider/API required."""
        from animation2d.episode03.motion_clips import ClipLibrary
        library = ClipLibrary(self.doc["motion_library"])
        result = []
        for name, clip in library.clips.items():
            info = self.doc["motion_library"]["clips"][name]
            tags = info.get("tags", [])
            title = name.replace("_", " ")
            if query.casefold() not in (name + " " + title + " " + " ".join(tags)).casefold():
                continue
            if category and category not in tags:
                continue
            result.append({"id": name, "kind": "keyframed", "duration": clip.duration,
                           "loop": clip.loop, "tags": tags})
        for name in library.poses:
            if query.casefold() not in name.casefold() or category:
                continue
            result.append({"id": name, "kind": "pose", "duration": None,
                           "loop": False, "tags": []})
        return sorted(result, key=lambda item: item["id"])
