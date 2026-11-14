"""Deterministic JSON camera animation that reuses motion-clip interpolation.

Camera channels use the shot-world pixel coordinate convention.  This layer
changes no animation code, dialog, cutout rig, or original FFmpeg parameters.
"""
from __future__ import annotations

from math import isfinite
from .motion_clips import evaluate_curve

CHANNELS = frozenset({"center_x", "center_y", "zoom", "angle"})
MODES = frozenset({"linear", "smooth", "step"})


def validate_camera_tracks(spec, duration):
    if spec is None:
        return {}
    if not isinstance(spec, dict) or not spec or set(spec) - CHANNELS:
        raise ValueError("Camera animation requires named center_x/center_y/zoom/angle tracks")
    if type(duration) not in (float, int) or not isfinite(duration) or duration <= 0:
        raise ValueError("Shot duration must be a positive finite number")
    validated = {}
    for channel, track in spec.items():
        if not isinstance(track, dict) or set(track) - {"keys", "mode"}:
            raise ValueError(f"Camera track {channel} requires keys and mode")
        mode = track.get("mode", "smooth")
        if mode not in MODES:
            raise ValueError(f"Camera track {channel} mode is invalid")
        raw = track.get("keys")
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"Camera track {channel} has no keys")
        last = -1.
        points = []
        for pair in raw:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Camera keyframe must be [shot_time, value]")
            t, value = pair
            if any(type(v) not in (int, float) or not isfinite(v) for v in (t, value)):
                raise ValueError("Camera keyframe must contain finite numbers")
            if t <= last or t < 0 or t > duration:
                raise ValueError("Camera key times must be ascending within the shot")
            if channel == "zoom" and value <= 0:
                raise ValueError("Zoom must stay positive")
            if channel == "angle" and abs(value) > 45:
                raise ValueError("Camera roll must remain within 45 degrees")
            points.append((float(t), float(value)))
            last = t
        validated[channel] = (mode, tuple(points))
    return validated


def sample_camera(base, tracks, time, duration):
    """Return one camera at an arbitrary frame time; no mutable history."""
    if not tracks:
        return dict(base)
    if not isfinite(time) or not 0 <= time < duration:
        raise ValueError("Camera sample outside shot")
    curves = validate_camera_tracks(tracks, duration)
    result = dict(base)
    center = list(result.get("center", [960, 540]))
    for channel, (mode, keys) in curves.items():
        value = evaluate_curve(mode, keys, time)
        if channel == "center_x":
            center[0] = value
        elif channel == "center_y":
            center[1] = value
        else:
            result[channel] = value
    result["center"] = center
    if "zoom" in result and result["zoom"] <= 0:
        raise ValueError("Invalid zoom")
    return result
