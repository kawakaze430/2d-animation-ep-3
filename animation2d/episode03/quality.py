"""Production-independent articulated-motion quality measurements.

Ideas compared against PySpine v2 motion arcs and planted-range diagnostics.
This is an original implementation using Episode03's solved world-space bones.
No upstream PySpine source is copied.
"""
from __future__ import annotations

from math import isfinite
import numpy as np

from .actions import ActionMixer
from .kinematics import gait_phase


def joint_connections(pose: dict) -> dict:
    """Measure every parent/child attachment gap in world pixels."""
    b = pose["bones"]
    gaps = {
        "neck_to_head": float(np.linalg.norm(b["torso"][0] - b["head"][0])),
        "root_to_pelvis": float(np.linalg.norm(pose["root"] - b["pelvis"][0])),
        "root_to_torso": float(np.linalg.norm(pose["root"] - b["torso"][1])),
    }
    for side in ("left", "right"):
        gaps[f"{side}_upper_forearm"] = float(np.linalg.norm(
            b[f"upper_arm.{side}"][1] - b[f"forearm.{side}"][0]))
        gaps[f"{side}_forearm_hand"] = float(np.linalg.norm(
            b[f"forearm.{side}"][1] - b[f"hand.{side}"][0]))
        gaps[f"{side}_thigh_shin"] = float(np.linalg.norm(
            b[f"thigh.{side}"][1] - b[f"shin.{side}"][0]))
        gaps[f"{side}_shin_foot"] = float(np.linalg.norm(
            b[f"shin.{side}"][1] - b[f"foot.{side}"][0]))
        gaps[f"{side}_wrist_attachment"] = float(np.linalg.norm(
            b[f"forearm.{side}"][1] - pose["hands"][side].position))
    return gaps


def foot_sliding(actor, start: float, end: float, *, fps=24, duration=15, side="left") -> dict:
    """Compute planted-stance ankle drift after leg IK, not just target drift.

    Report only adjacent frame pairs where the foot stays in stance AND pelvis
    translates. This catches the classic bug where a nominally static target
    is silently moved by unreachable full-extension IK.
    """
    if side not in ("left", "right"):
        raise ValueError("side must be left or right")
    if not (0 <= start < end <= duration) or fps < 1:
        raise ValueError("Invalid sampling window or fps")
    mixer = ActionMixer(actor.placement, duration, objects=actor.objects)
    samples = []
    frame_start = int(np.ceil(start * fps))
    frame_end = int(np.ceil(end * fps))
    for frame in range(frame_start, frame_end):
        t = frame / fps
        if t >= duration:
            break
        motion = mixer.sample(t)
        pose = actor.pose(t, duration)
        stride = 160 if motion.running else 96
        if actor.placement.get("foot_lock", "actions" in actor.placement):
            stride *= pose["scale"] / .6
        phase = (gait_phase(float(pose["root"][0]), stride)
                 + (0 if side == "left" else .5)) % 1
        planted = motion.walking and phase < .62
        samples.append((t, float(pose["root"][0]),
                        np.asarray(pose["joints"][f"ankle_{side}"]).copy(), planted))
    pair_errors = []
    for a, b in zip(samples, samples[1:]):
        if a[3] and b[3] and abs(a[1] - b[1]) > 1e-4:
            pair_errors.append(float(np.linalg.norm(a[2] - b[2])))
    if not all(isfinite(v) for v in pair_errors):
        raise ValueError("Invalid solved foot positions")
    return {
        "side": side,
        "planted_transition_pairs": len(pair_errors),
        "max_sliding_px_per_frame": max(pair_errors, default=0.),
        "mean_sliding_px_per_frame": float(np.mean(pair_errors)) if pair_errors else 0.,
        "samples": len(samples),
    }


def hand_prop_release_error(actor, interaction: dict, duration: float):
    """Evaluate hand-to-landing contact just before a scripted release."""
    from .engine import attachment_transform
    release = float(interaction["release_at"])
    hand = attachment_transform(actor, min(release, duration-1e-6), interaction, duration)
    landing = np.asarray(interaction["landing"], dtype=float)
    if landing.shape != (2,) or not np.isfinite(landing).all():
        raise ValueError("Invalid landing")
    return float(np.linalg.norm(hand.position - landing))
