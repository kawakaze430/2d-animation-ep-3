"""Reusable, deterministic 2D action mixer. No episode- or character-specific motion code.

Actions specify *intent*; the existing Episode 03 kinematics engine still solves
two-bone IK, gait, sprite pivots, joint limits, expressions and scene depth.
All coordinates are world pixels, x right, y down. Stateless sampling makes
random-access preview, frame caching and parallel jobs deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, sin
from typing import Any

import numpy as np

from .kinematics import ease

# These names are stable public API. A clip's parameters, not its Python class,
# are what differs between actors, props and subsequent episodes.
LIBRARY = {
    "idle": "base",
    "walk": "locomotion", "run": "locomotion", "sit": "posture",
    "talk": "face", "blink": "face", "look": "face",
    "reach": "hands", "hold": "hands", "pick_up": "hands",
    "put_down": "hands", "carry": "hands",
    "pour": "hands", "stir": "hands", "eat": "hands",
    "react": "body", "gesture": "hands",
}
ALIASES = {
    "walking": "walk", "running": "run", "sitting": "sit",
    "talking": "talk", "blinking": "blink", "looking": "look",
    "reaching": "reach", "holding": "hold", "picking_up": "pick_up",
    "putting_down": "put_down", "carrying": "carry",
    "pouring": "pour", "stirring": "stir", "eating": "eat",
    "reacting": "react", "gesturing": "gesture",
}
EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised", "curious", "excited", "worried")
HAND_ACTIONS = {"reach", "hold", "pick_up", "put_down", "carry", "pour", "stir", "eat", "gesture"}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _point(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{label} must be [x,y]")
    return np.array([_number(v, label) for v in value], dtype=float)


def action_name(spec: dict) -> str:
    name = spec.get("clip", spec.get("kind", "idle"))
    name = ALIASES.get(name, name)
    if name not in LIBRARY:
        raise ValueError(f"Unsupported reusable action: {name}")
    return name


def validate_action(spec: dict, duration: float) -> dict:
    """Fail fast on unknown clips, invalid timeline coordinates or unsafe blends."""
    if not isinstance(spec, dict):
        raise ValueError("Action must be a JSON object")
    name = action_name(spec)
    start = _number(spec.get("start", 0), "start")
    end = _number(spec.get("end", duration), "end")
    speed = _number(spec.get("speed", 1), "speed")
    weight = _number(spec.get("weight", 1), "weight")
    blend = _number(spec.get("blend", 0), "blend")
    if not 0 <= start < end <= duration or speed <= 0 or not 0 <= weight <= 1 or not 0 <= blend < (end-start)/2:
        raise ValueError(f"{name}: invalid action start/end, speed, weight or blend")
    if "target" in spec:
        _point(spec["target"], f"{name}.target")
    if "targets" in spec:
        if not isinstance(spec["targets"], dict) or not set(spec["targets"]) <= {"left", "right"}:
            raise ValueError("targets must map left/right hands to world coordinates")
        for side, target in spec["targets"].items():
            _point(target, f"{name}.{side}")
    if spec.get("hand", "right") not in ("left", "right"):
        raise ValueError("hand must be left or right")
    if "emotion" in spec and spec["emotion"] not in EMOTIONS:
        raise ValueError("Unknown emotion")
    if "object" in spec and (not isinstance(spec["object"], str) or not spec["object"]):
        raise ValueError("object must identify a prop")
    return spec


@dataclass
class Motion:
    """Values sampled once per actor and time. Simultaneous layers can affect separate channels."""
    root: np.ndarray
    hand_targets: dict = field(default_factory=dict)  # side -> (world target or None, weight, clip, progress)
    walking: bool = False
    running: bool = False
    sitting: float = 0
    lean: float = 0
    head_turn: float = 0
    look: np.ndarray | None = None
    blink: bool | None = None
    emotion: str = "neutral"
    speaking: bool = False
    active: tuple = ()


class ActionMixer:
    """Parameterised runtime shared by every cast member.

    Old actor.action is accepted unchanged. New actor.actions is a list of
    layered clip objects with start/end/target/hand/speed/weight/blend/priority.
    Clip intervals are shot-local; end-state locomotion is held after completion.
    """

    def __init__(self, placement: dict, duration: float):
        self.placement = placement
        self.duration = _number(duration, "shot duration")
        if self.duration <= 0:
            raise ValueError("Shot duration must be positive")
        if "actions" in placement:
            specs = placement["actions"]
            if not isinstance(specs, list):
                raise ValueError("actions must be an array of clips")
        else:
            original = dict(placement.get("action", {"kind": "idle"}))
            original.setdefault("hold_last", action_name(original) in HAND_ACTIONS)
            original["_legacy"] = True
            specs = [original]
        self.actions = tuple(validate_action(dict(a), self.duration) for a in specs)
        self.origin = _point(placement.get("position", [960, 600]), "actor.position")

    def sample(self, time: float) -> Motion:
        t = _number(time, "sample time")
        if not 0 <= t < self.duration:
            raise ValueError("Sample time is outside the shot")
        result = Motion(root=self.origin.copy(), lean=_number(self.placement.get("lean", 0), "lean"))
        ordered = sorted(enumerate(self.actions), key=lambda pair: (pair[1].get("priority", 0), pair[0]))
        named = []
        for _index, spec in ordered:
            clip = action_name(spec)
            start, end = float(spec.get("start", 0)), float(spec.get("end", self.duration))
            speed, weight = float(spec.get("speed", 1)), float(spec.get("weight", 1))
            p = ease(min(1, max(0, (t - start) * speed / (end - start))))
            if t < start:
                continue
            # Fade only the contribution of short-lived overlays, never the
            # accumulated world-space position at the end of a walking clip.
            blend = float(spec.get("blend", 0))
            envelope = weight
            if blend:
                envelope *= min(1, max(0, (t - start) / blend))
                if t > end - blend:
                    envelope *= min(1, max(0, (end - t) / blend))
            if t >= end and clip not in ("walk", "run") and not spec.get("hold_last", False):
                continue
            if t >= end:
                p = 1.
                if clip not in ("walk", "run"):
                    envelope = weight
            named.append(clip)
            if clip in ("walk", "run"):
                # Sequential locomotion clips are additive rather than pulling
                # previously completed travel back to the original position.
                target = _point(spec.get("target", self.origin), f"{clip}.target")
                result.root += (target - self.origin) * p * weight
                result.walking |= t < end
                result.running |= clip == "run" and t < end
            elif clip == "sit":
                result.sitting = max(result.sitting, p * envelope)
            elif clip in HAND_ACTIONS:
                hand = spec.get("hand", "right")
                targets = spec.get("targets", {})
                selected = {hand: spec.get("target")} if not targets else targets
                for side, target in selected.items():
                    # A scripted target is optional: gesture defaults to a
                    # natural shoulder-space communication pose.
                    effect = (envelope if spec.get("_legacy") and targets else p * envelope)
                    if clip == "gesture" and "target" not in spec and not targets and not spec.get("_legacy"):
                        effect = max(effect, envelope)
                    if side in result.hand_targets:
                        prior_target, prior_weight, prior_clip, prior_p = result.hand_targets[side]
                        effect = max(effect, prior_weight) if target is None else effect
                    result.hand_targets[side] = (None if target is None else _point(target, "hand.target"),
                                                 effect, clip, p)
            elif clip == "look":
                if "target" in spec:
                    result.look = _point(spec["target"], "look.target")
                result.head_turn = _number(spec.get("degrees", 0), "head angle") * p * envelope
            elif clip == "blink":
                result.blink = p >= .4 and p <= .9
            elif clip == "talk":
                result.speaking = True
            elif clip == "react":
                result.lean += _number(spec.get("lean", 8), "react.lean") * sin(p * 3.141592653589793) * envelope
            if "emotion" in spec and envelope > 0.1:
                result.emotion = spec["emotion"]
        result.active = tuple(named)
        return result


def shared_clip_demo(actors=("DAN", "MAYA", "NINA")) -> dict:
    """Three DIFFERENT shots, exactly the same library implementation, no animation duplication."""
    if len(set(actors)) != 3:
        raise ValueError("Three distinct actors are required")
    return {
        actor: {"id": f"DEMO_{index:03}", "actor": actor,
                "position": [560 + index * 400, 650], "scale": 0.6,
                "actions": [
                    {"clip": "reach", "start": 0, "end": 2, "hand": "right",
                     "target": [610 + index * 400, 590], "speed": 1},
                    {"clip": "look", "start": 0, "end": 3, "degrees": -8},
                    {"clip": "blink", "start": 1, "end": 1.2},
                ]}
        for index, actor in enumerate(actors)
    }
