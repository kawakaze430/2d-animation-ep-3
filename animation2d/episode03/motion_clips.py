"""Named character-independent skeletal motion and pose clips.

Original implementation for Episode03; design inspired by PySpine v2's sampled
tracks/pose library (SaxonRah/PySpine, MIT, Robert Valentine 2025).
No upstream PySpine source code is copied into this module.

Local clip coordinates are pelvis-relative SOURCE RIG UNITS, +x right and +y
down. Values are transformed using actor scale at application time. Existing
two-bone IK (kinematics.py) is still the authoritative bone solver.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path

CHANNELS = frozenset({
    "root_x", "root_y",
    "left_x", "left_y", "right_x", "right_y",
    "lean", "head_turn", "sitting", "blink",
})
MODES = frozenset({"linear", "smooth", "step"})
DEFAULT_LIBRARY = Path(__file__).resolve().parent / "factory" / "clip_library.json"


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _curve(channel, spec):
    if not isinstance(spec, dict) or set(spec) - {"keys", "mode"}:
        raise ValueError(f"{channel}: track must specify keys and optional mode")
    mode = spec.get("mode", "linear")
    if mode not in MODES:
        raise ValueError(f"{channel}: unknown interpolation {mode}")
    raw = spec.get("keys")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{channel}: require at least one normalized keyframe")
    points = []
    last = -1.
    for key in raw:
        if not isinstance(key, list) or len(key) != 2:
            raise ValueError(f"{channel}: expected key [normalized_time, value]")
        t = _finite(key[0], f"{channel} time")
        v = _finite(key[1], f"{channel} value")
        if not 0 <= t <= 1 or t <= last:
            raise ValueError(f"{channel}: key times must strictly increase from 0 to 1")
        points.append((t, v))
        last = t
    return mode, tuple(points)


@dataclass(frozen=True)
class Clip:
    name: str
    duration: float
    loop: bool
    tracks: dict

    def sample(self, seconds: float):
        t = max(0., _finite(seconds, "clip sample"))
        phase = (t % self.duration) / self.duration if self.loop else min(1., t / self.duration)
        return {channel: evaluate_curve(mode, keys, phase)
                for channel, (mode, keys) in self.tracks.items()}


def evaluate_curve(mode: str, keys: tuple, phase: float):
    """Sample one timeline deterministically; step mode supports discrete poses."""
    if phase <= keys[0][0]:
        return keys[0][1]
    if phase >= keys[-1][0]:
        return keys[-1][1]
    frames = [p[0] for p in keys]
    right = bisect_right(frames, phase)
    a, b = keys[right - 1], keys[right]
    u = (phase - a[0]) / (b[0] - a[0])
    if mode == "step":
        u = 0.
    elif mode == "smooth":
        u = u*u*(3 - 2*u)
    return a[1] + (b[1] - a[1])*u


class ClipLibrary:
    """Validated immutable library of named motion clips and reusable poses."""

    def __init__(self, source: dict):
        if not isinstance(source, dict) or source.get("version") != 1:
            raise ValueError("Motion clip library must have version 1")
        if not isinstance(source.get("clips"), dict) or not isinstance(source.get("poses", {}), dict):
            raise ValueError("Clip library needs clips/poses JSON dictionaries")
        self.clips = {}
        for name, item in source["clips"].items():
            if not isinstance(name, str) or not name or not isinstance(item, dict):
                raise ValueError("Clip entries must have names and objects")
            duration = _finite(item.get("duration"), f"{name}.duration")
            if duration <= 0 or duration > 300:
                raise ValueError(f"{name}: duration out of range")
            if type(item.get("loop", False)) is not bool:
                raise ValueError(f"{name}: loop must be boolean")
            tracks = self._tracks(item.get("tracks", {}))
            if item.get("loop", False):
                for channel, (_mode, keys) in tracks.items():
                    if keys[0][0] != 0 or keys[-1][0] != 1 or abs(keys[0][1]-keys[-1][1]) > 1e-6:
                        raise ValueError(f"{name}.{channel}: looping track must join seamlessly at 0 and 1")
            self.clips[name] = Clip(name, duration, item.get("loop", False), tracks)
        self.poses = {}
        for name, values in source.get("poses", {}).items():
            if not isinstance(name, str) or not name or not isinstance(values, dict):
                raise ValueError("Pose entries must be named dictionaries")
            if set(values) - CHANNELS:
                raise ValueError(f"{name}: unsupported pose channel")
            self.poses[name] = {key: _finite(value, f"{name}.{key}") for key, value in values.items()}

    @staticmethod
    def _tracks(raw):
        if not isinstance(raw, dict) or not raw or set(raw) - CHANNELS:
            raise ValueError("Clips require recognized motion channels")
        return {name: _curve(name, spec) for name, spec in raw.items()}

    @classmethod
    def load(cls, path: str | Path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def sample(self, kind: str, source: str, seconds: float):
        if kind == "pose":
            if source not in self.poses:
                raise ValueError(f"Unknown shared pose: {source}")
            return dict(self.poses[source])
        if kind == "keyframed":
            if source not in self.clips:
                raise ValueError(f"Unknown shared motion clip: {source}")
            return self.clips[source].sample(seconds)
        raise ValueError(f"Only pose/keyframed are loaded from a clip library; got {kind}")


@lru_cache(maxsize=1)
def default_library():
    return ClipLibrary.load(DEFAULT_LIBRARY)
