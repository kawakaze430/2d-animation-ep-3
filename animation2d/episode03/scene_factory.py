"""Compile immutable Episode 03 screenplay + reusable JSON staging into a scene.

Legacy 80-shot manifest stays untouched. New episodes can supply a scene with
new_story=true, their own cast config, dialogue and background, without Python
code changes. All paths are anchored to the repository for security.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .actions import ActionMixer
from .engine import REPO

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "factory/templates.json"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_asset(path, root):
    """No traversal, absolute paths or paths outside the configured workspace."""
    if not isinstance(path, str) or not path:
        raise ValueError("Image path must be a nonempty string")
    p = Path(path)
    if p.is_absolute() or not (root / p).resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Asset escapes project root: {path}")
    return str(p)


def compile_scene(manifest, scene, *, templates=None, root=REPO):
    """Compile only data, with no rendered animation or mutable global state."""
    doc = deepcopy(read_json(manifest) if isinstance(manifest, (str, Path)) else manifest)
    conf = deepcopy(read_json(scene) if isinstance(scene, (str, Path)) else scene)
    if conf.get("version") != 1:
        raise ValueError("Scene format requires version 1")
    lib = templates or read_json(TEMPLATES)
    name = conf.get("shot")
    shots = [s for s in doc["shots"] if s.get("id") == name]
    if shots:
        if conf.get("new_story") or "dialogue" in conf or "cast" in conf:
            raise ValueError("Existing screenplay dialogue and cast are immutable")
        shot = deepcopy(shots[0])
    else:
        if not conf.get("new_story"):
            raise ValueError("Unknown shot; new scenes must declare new_story=true")
        cast = conf.get("cast")
        for actor, config in conf.get("characters", {}).items():
            doc["characters"][actor] = deepcopy(config)
        dialogue = conf.get("dialogue")
        if not isinstance(cast, list) or not cast or not all(a in doc["characters"] for a in cast):
            raise ValueError("New story cast must be configured in characters")
        if not isinstance(dialogue, list) or not all(
            d.get("speaker") in cast and isinstance(d.get("text"), str)
            and 0 <= d.get("start", -1) < d.get("end", -1) <= conf.get("duration", 15)
            for d in dialogue
        ):
            raise ValueError("New story needs valid timed dialogue")
        shot = {"id": name, "duration": conf.get("duration", 15),
                "cast": cast, "dialogue": dialogue, "actors": {},
                "props": [], "camera": {}, "location": "",
                "blocking_authored": False, "production_ready": False}
    if not isinstance(name, str) or not name:
        raise ValueError("Shot must have a nonempty ID")
    environment = conf.get("environment")
    if environment:
        template = lib["environments"].get(environment)
        if not template:
            raise ValueError(f"Unknown reusable environment template {environment}")
        shot["location"] = template["location"]
        shot["background"] = _resolve_asset(template["background"], Path(root))
        shot["foreground"] = deepcopy(template.get("foreground", []))
    camera = conf.get("camera")
    if isinstance(camera, str):
        if camera not in lib["cameras"]:
            raise ValueError(f"Unknown camera template: {camera}")
        shot["camera"] = deepcopy(lib["cameras"][camera])
    elif isinstance(camera, dict):
        if not set(camera) <= {"zoom", "center", "angle"}:
            raise ValueError("Unknown camera parameter")
        shot.setdefault("camera", {}).update(deepcopy(camera))
    elif camera is not None:
        raise ValueError("camera must be a preset or parameter object")
    for name, change in conf.get("actors", {}).items():
        if name not in shot["cast"]:
            raise ValueError(f"Action targets invisible actor {name}")
        if not isinstance(change, dict) or not set(change) <= {
            "position", "scale", "depth", "actions", "action", "lean", "rig"
        }:
            raise ValueError(f"{name}: invalid actor parameters")
        defaults = {"position": [960, 650], "scale": .6, "depth": 100, "action": {"kind": "idle"}}
        actor = {**defaults, **shot.get("actors", {}).get(name, {})}
        actor.update(deepcopy(change))
        if "actions" in change:
            actor.pop("action", None)
        ActionMixer(actor, shot["duration"])
        shot["actors"][name] = actor
    for actor in shot["cast"]:
        if actor not in shot["actors"]:
            raise ValueError(f"Visible actor {actor} missing placement")
        ActionMixer(shot["actors"][actor], shot["duration"])
    props = {p["id"]: deepcopy(p) for p in shot.get("props", [])}
    for prop in conf.get("props", []):
        if not isinstance(prop, dict) or not isinstance(prop.get("id"), str):
            raise ValueError("Prop must have a named ID")
        original = props.get(prop["id"], {})
        original.update(deepcopy(prop))
        if "interaction" in prop:
            original.pop("attachment", None)  # modern interaction supersedes legacy binding
        if "file" in original:
            original["file"] = _resolve_asset(original["file"], Path(root))
        interaction = original.get("interaction")
        if interaction:
            if interaction["actor"] not in shot["cast"] or interaction.get("hand", "right") not in ("left", "right"):
                raise ValueError("Prop interaction must reference a visible actor and hand")
            begin, end = interaction.get("attach_at"), interaction.get("release_at")
            if not isinstance(begin, (int, float)) or not isinstance(end, (int, float)) or not 0 <= begin < end <= shot["duration"]:
                raise ValueError("Prop interaction needs valid attach_at and release_at")
            if "landing" not in interaction:
                raise ValueError("Prop interaction requires a final landing position")
            from .engine import Actor, attachment_transform
            cast_actor = Actor(interaction["actor"], placement=shot["actors"][interaction["actor"]])
            hand = attachment_transform(cast_actor, min(end, shot["duration"] - 1e-6),
                                        interaction, shot["duration"])
            landing = interaction["landing"]
            distance = float(((hand.position[0]-landing[0])**2 +
                              (hand.position[1]-landing[1])**2)**.5)
            if distance > float(interaction.get("contact_tolerance", 24)):
                raise ValueError(f"{prop['id']}: object would teleport {distance:.1f}px on release")
        props[prop["id"]] = original
    shot["props"] = list(props.values())
    if "foreground" in conf:
        shot["foreground"] = deepcopy(conf["foreground"])
    shot["blocking_authored"] = True
    # Preserve original dialogue bytes and scene continuity; only staging changes.
    doc["shots"] = [shot]
    doc["duration"] = shot["duration"]
    doc["factory_scene_version"] = 1
    doc["factory_scene_sha256"] = hashlib.sha256(
        json.dumps(conf, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return doc


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--manifest", type=Path, default=HERE / "shots.json")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = compile_scene(a.manifest, a.scene)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"scene": a.scene.as_posix(), "shot": result["shots"][0]["id"],
                      "actions": {name: len(s.get("actions", [s.get("action")]))
                                  for name, s in result["shots"][0]["actors"].items()},
                      "manifest": str(a.output)}))


if __name__ == "__main__":
    main()
