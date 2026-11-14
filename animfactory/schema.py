"""Strict, editor-friendly v1 animation PROJECT format; no episode terminology.

All coordinates are X-right, Y-down canvas/world pixels. Clip ranges are
[integer start_frame, integer end_frame); each scene has its own exact frame
count. No implicit LLM/service/model dependency.

This file is intentionally stdlib-only: opening/validating projects must not
import PIL/NumPy, download models, access the network or start render jobs.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

FORMAT = "animfactory.project"
VERSION = 1
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
ASSET_KINDS = frozenset({"rig", "image", "background", "prop", "audio", "reference"})
MOTION_KINDS = frozenset({"walk", "run", "idle", "sit", "talk", "blink", "look",
                           "reach", "hold", "pick_up", "put_down", "carry",
                           "pour", "stir", "eat", "react", "gesture",
                           "keyframed", "pose"})
CORE_KEYS = frozenset({"format", "version", "id", "title", "canvas", "fps",
                        "assets", "characters", "motion_library", "scenes", "metadata"})


def _fail(message):
    raise ValueError("Invalid animation project: " + message)


def valid_id(value, where="ID"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(f"{where} must match {_ID.pattern}")
    return value


def number(value, where, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail(f"{where}: finite number required")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        _fail(f"{where}: value outside permitted range")
    return float(value)


def point(value, where):
    if not isinstance(value, list) or len(value) != 2:
        _fail(f"{where}: expected [x,y]")
    return [number(v, where) for v in value]


def safe_path(value, where):
    """Only project-relative POSIX paths; no symlink resolution here (I/O stage)."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        _fail(f"{where}: invalid path")
    p = Path(value)
    if p.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")) or ":" in value:
        _fail(f"{where}: unsafe project-relative path")
    return value


def empty_project(project_id, title, *, canvas=(960, 540), fps=24):
    valid_id(project_id, "project.id")
    if not isinstance(title, str) or not title.strip() or len(title) > 180:
        _fail("project.title required")
    doc = {
        "format": FORMAT, "version": VERSION, "id": project_id,
        "title": title.strip(), "canvas": list(canvas), "fps": fps,
        "assets": {}, "characters": {},
        "motion_library": {"version": 1, "clips": {}, "poses": {}},
        "scenes": [], "metadata": {"created_by": "animfactory", "license": "unspecified"},
    }
    return validate_project(doc)


def validate_project(source):
    """Return a deep copy of fully checked JSON data, never mutate caller state."""
    if not isinstance(source, dict):
        _fail("expected JSON object")
    if set(source) != CORE_KEYS:
        _fail(f"top-level keys mismatch (missing={sorted(CORE_KEYS-set(source))}; "
              f"unknown={sorted(set(source)-CORE_KEYS)})")
    if source["format"] != FORMAT or type(source["version"]) is not int or source["version"] != VERSION:
        _fail(f"expected {FORMAT} version {VERSION}; migration needed for other versions")
    valid_id(source["id"], "project.id")
    if not isinstance(source["title"], str) or not source["title"].strip():
        _fail("title required")
    canvas = source["canvas"]
    if not isinstance(canvas, list) or len(canvas) != 2 or any(
            type(v) is not int or not 16 <= v <= 8192 for v in canvas):
        _fail("canvas must contain integer dimensions 16..8192")
    fps = source["fps"]
    if type(fps) is not int or not 1 <= fps <= 60:
        _fail("fps must be an integer 1..60")
    if not isinstance(source["metadata"], dict):
        _fail("metadata must be an object")
    assets, chars = source["assets"], source["characters"]
    if not isinstance(assets, dict) or not isinstance(chars, dict):
        _fail("assets and characters must be registries")
    for aid, asset in assets.items():
        valid_id(aid, "asset ID")
        if not isinstance(asset, dict) or asset.get("kind") not in ASSET_KINDS:
            _fail(f"{aid}: unsupported asset kind")
        safe_path(asset.get("path"), f"{aid}.path")
        if not isinstance(asset.get("sha256"), str) or not HASH.fullmatch(asset["sha256"]):
            _fail(f"{aid}: sha256 required")
        if not isinstance(asset.get("source"), str) or not isinstance(asset.get("license"), str):
            _fail(f"{aid}: source/license provenance required (use 'unspecified' if unknown)")
        if "files" in asset:
            files = asset["files"]
            if not isinstance(files, dict) or not files:
                _fail(f"{aid}: files must be a nonempty hash registry")
            for name, digest in files.items():
                safe_path(name, f"{aid}.files")
                if not isinstance(digest, str) or not HASH.fullmatch(digest):
                    _fail(f"{aid}: invalid file checksum")
    for cid, config in chars.items():
        valid_id(cid, "character ID")
        if not isinstance(config, dict) or config.get("rig_asset") not in assets:
            _fail(f"{cid}: rig_asset must reference registered asset")
        if assets[config["rig_asset"]]["kind"] != "rig":
            _fail(f"{cid}: rig_asset has wrong kind")
        if "tags" in config and (not isinstance(config["tags"], list) or
                                any(not isinstance(t, str) for t in config["tags"])):
            _fail(f"{cid}: tags must be strings")
    from animation2d.episode03.motion_clips import ClipLibrary
    ClipLibrary(source["motion_library"])

    scenes = source["scenes"]
    if not isinstance(scenes, list):
        _fail("scenes must be an array")
    scene_ids = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            _fail("scene must be object")
        sid = valid_id(scene.get("id"), "scene ID")
        if sid in scene_ids:
            _fail(f"duplicate scene ID {sid}")
        scene_ids.add(sid)
        length = scene.get("frames")
        if type(length) is not int or not 1 <= length <= fps * 300:
            _fail(f"{sid}: frames must be a positive integer up to 5 minutes")
        camera = scene.get("camera")
        if not isinstance(camera, dict):
            _fail(f"{sid}: camera must be object")
        point(camera.get("center"), f"{sid}.camera.center")
        number(camera.get("zoom"), f"{sid}.camera.zoom", 0.05, 30)
        if "camera_animation" in scene:
            from animation2d.episode03.camera_clips import validate_camera_tracks
            validate_camera_tracks(scene["camera_animation"], length / fps)
        for optional in ("background_asset",):
            if optional in scene and scene[optional] is not None:
                if scene[optional] not in assets or assets[scene[optional]]["kind"] not in ("background", "image"):
                    _fail(f"{sid}: background must reference image/background")
        actors = scene.get("actors")
        if not isinstance(actors, list):
            _fail(f"{sid}: actors must be array")
        seen_actors = set()
        for actor in actors:
            if not isinstance(actor, dict):
                _fail(f"{sid}: actor entry must be object")
            actor_id = valid_id(actor.get("id"), f"{sid}.actor.id")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", actor_id):
                _fail(f"{sid}: actor ID must match existing renderer contract")
            if actor_id in seen_actors:
                _fail(f"{sid}: duplicated actor {actor_id}")
            seen_actors.add(actor_id)
            if actor.get("character") not in chars:
                _fail(f"{sid}/{actor_id}: unknown character")
            point(actor.get("position"), f"{sid}/{actor_id}.position")
            number(actor.get("scale", 1), f"{sid}/{actor_id}.scale", .01, 100)
            number(actor.get("depth", 100), f"{sid}/{actor_id}.depth")
            tracks = actor.get("actions")
            if not isinstance(tracks, list):
                _fail(f"{sid}/{actor_id}: actions must be array")
            action_ids = set()
            for action in tracks:
                if not isinstance(action, dict):
                    _fail("action must be object")
                valid_id(action.get("id"), "action ID")
                if action["id"] in action_ids:
                    _fail(f"{sid}/{actor_id}: duplicate action ID")
                action_ids.add(action["id"])
                if action.get("clip") not in MOTION_KINDS:
                    _fail(f"{sid}/{actor_id}: unsupported action")
                start, end = action.get("start_frame"), action.get("end_frame")
                if (type(start) is not int or type(end) is not int or
                        not 0 <= start < end <= length):
                    _fail(f"{sid}/{actor_id}: action frames outside scene")
                if action["clip"] in ("keyframed", "pose"):
                    name = action.get("source")
                    library = source["motion_library"]["clips" if action["clip"] == "keyframed" else "poses"]
                    if name not in library:
                        _fail(f"{sid}/{actor_id}: unknown named motion {name}")
                if "weight" in action:
                    number(action["weight"], "action.weight", 0, 1)
                if "speed" in action:
                    number(action["speed"], "action.speed", .01, 10)
                if "target" in action:
                    point(action["target"], "action.target")
                if action.get("hand", "right") not in ("left", "right"):
                    _fail("action hand must be left or right")
        props = scene.get("props", [])
        if not isinstance(props, list):
            _fail(f"{sid}: props must be array")
        prop_ids = set()
        for prop in props:
            if not isinstance(prop, dict) or set(prop) - {
                "id", "position", "depth", "rotation", "size", "color",
                "shape", "asset", "interaction"
            }:
                _fail(f"{sid}: prop must use recognized safe fields; raw file paths forbidden")
            pid = valid_id(prop.get("id"), "prop ID")
            if pid in prop_ids:
                _fail(f"{sid}: duplicate prop ID")
            prop_ids.add(pid)
            point(prop.get("position"), f"{pid}.position")
            number(prop.get("depth", 110), f"{pid}.depth")
            number(prop.get("rotation", 0), f"{pid}.rotation", -360, 360)
            if "asset" in prop:
                if prop["asset"] not in assets or assets[prop["asset"]]["kind"] not in ("prop", "image"):
                    _fail(f"{pid}: prop artwork must reference an imported image/prop asset")
            elif ("size" not in prop or "color" not in prop):
                _fail(f"{pid}: vector props require size and color")
            if "size" in prop:
                size = point(prop["size"], f"{pid}.size")
                if min(size) <= 0 or max(size) > 8192:
                    _fail(f"{pid}: invalid prop size")
            if "shape" in prop and prop["shape"] not in ("rectangle", "ellipse"):
                _fail(f"{pid}: unsupported vector shape")
            if "color" in prop and (not isinstance(prop["color"], str)
                                    or not re.fullmatch(r"#[0-9A-Fa-f]{6}", prop["color"])):
                _fail(f"{pid}: color must be a six-digit hex code")
            binding = prop.get("interaction")
            if binding is not None:
                if not isinstance(binding, dict) or set(binding) - {
                    "actor", "hand", "attach_at", "release_at", "landing",
                    "offset", "rotation", "rotate_with_hand", "follow_actor_scale",
                    "contact_tolerance"
                }:
                    _fail(f"{pid}: invalid interaction")
                if binding.get("actor") not in seen_actors or binding.get("hand", "right") not in ("left", "right"):
                    _fail(f"{pid}: interaction references unknown hand/actor")
                t0, t1 = binding.get("attach_at"), binding.get("release_at")
                if (type(t0) not in (float,int) or type(t1) not in (float,int) or
                    not math.isfinite(t0) or not math.isfinite(t1)
                    or not 0 <= t0 < t1 <= length/fps):
                    _fail(f"{pid}: interaction times outside scene duration")
                point(binding.get("landing"), f"{pid}.landing")
                if "offset" in binding:
                    point(binding["offset"], f"{pid}.offset")
                if "contact_tolerance" in binding:
                    number(binding["contact_tolerance"], f"{pid}.contact_tolerance", 0, 10000)
                for flag in ("rotate_with_hand", "follow_actor_scale"):
                    if flag in binding and type(binding[flag]) is not bool:
                        _fail(f"{pid}: {flag} must be boolean")
        for actor in actors:
            for action in actor["actions"]:
                if "object" in action and action["object"] not in prop_ids:
                    _fail(f"{sid}: action references missing prop ID")
        dialogue = scene.get("dialogue", [])
        if not isinstance(dialogue, list):
            _fail(f"{sid}: dialogue must be array")
        previous_end = 0
        for turn in dialogue:
            if not isinstance(turn, dict) or set(turn) != {
                "speaker", "text", "start_frame", "end_frame"
            }:
                _fail(f"{sid}: dialogue needs speaker/text/start_frame/end_frame")
            if turn["speaker"] not in seen_actors or not isinstance(turn["text"], str) or not turn["text"].strip():
                _fail(f"{sid}: dialogue speaker/text invalid")
            start, end = turn["start_frame"], turn["end_frame"]
            if (type(start) is not int or type(end) is not int or
                    not previous_end <= start < end <= length):
                _fail(f"{sid}: dialogue overlaps or exceeds scene")
            previous_end = end
    return deepcopy(source)


def stable_bytes(doc):
    validated = validate_project(doc)
    return (json.dumps(validated, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")
