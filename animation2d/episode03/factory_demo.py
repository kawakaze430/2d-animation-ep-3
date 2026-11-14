"""Three separate reviewable shots reuse the same action code for Dan, Maya, Nina.

Demonstration is explicitly schematic until real transparent rigs are approved.
No character-specific Python action implementation is created.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .actions import shared_clip_demo
from .motion_clips import default_library
from .engine import REPO
from .scene_factory import compile_scene, TEMPLATES


def manifest_for_demo(base, named_motion=None):
    if named_motion is not None and named_motion not in default_library().clips:
        raise ValueError(f"Unknown named reusable motion clip: {named_motion}")
    data = deepcopy(json.loads(Path(base).read_text()) if isinstance(base, (str, Path)) else base)
    example = shared_clip_demo()
    shots = []
    for name, spec in example.items():
        source = next(s for s in data["shots"] if s["id"] == "SHOT_001")
        shot = {key: deepcopy(source[key]) for key in ("background", "location", "camera", "duration")}
        actions = spec["actions"] if named_motion is None else [
            {"clip": "keyframed", "source": named_motion, "start": 0,
             "end": default_library().clips[named_motion].duration}]
        if named_motion is not None and actions[0]["end"] > shot["duration"]:
            raise ValueError("Named clip is longer than demonstration shot")
        shot.update({
            "id": spec["id"], "title": f"Reusable {named_motion or 'reach + look + blink'} / {name}",
            "cast": [name], "actors": {name: {
                "position": spec["position"], "scale": spec["scale"], "depth": 100,
                "actions": actions,
            }},
            "dialogue": [], "props": [], "blocking_authored": True,
            "production_ready": False,
            "source": {"action": "Same action library, three independently parameterized actors and shots."},
        })
        shots.append(shot)
    data["shots"] = shots
    data["duration"] = sum(x["duration"] for x in shots)
    data["status"] = "SCHEMATIC reuse demonstrations; NOT final Episode 03 production art"
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, default=REPO/"animation2d/episode03/shots.json")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--motion-clip", help="Same named keyframed clip on Dan/Maya/Nina in 3 separate shots")
    a = p.parse_args()
    demo = manifest_for_demo(a.manifest, named_motion=a.motion_clip)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(demo, indent=2) + "\n")
    print(f"{len(demo['shots'])} separate scenes reuse {a.motion_clip or 'reach, look, blink'} without duplicating code")


if __name__ == "__main__":
    main()
