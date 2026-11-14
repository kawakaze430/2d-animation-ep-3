"""Pure articulated-cutout math extracted from project/action_render.py.

No artwork, episode timeline, audio, or renderer globals are imported here.
Angles are degrees; coordinates use the image convention X right, Y down.
"""
import math
import numpy as np
from PIL import Image


def ease(value):
    value = max(0.0, min(1.0, float(value)))
    return value ** 3 * (value * (value * 6 - 15) + 10)


def rot(point, degrees):
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    x, y = point
    return np.array([c*x-s*y, s*x+c*y], dtype=float)


def angle(vector):
    return math.degrees(math.atan2(vector[1], vector[0])) - 90


def wrist_angle(forearm_angle, desired=None):
    if desired is None:
        return forearm_angle
    delta = (desired-forearm_angle+180) % 360-180
    return forearm_angle + float(np.clip(delta, -40, 40))


def ik(shoulder, target, upper, lower, bend=-1):
    """Clamp reach before solving, keeping both bone lengths invariant."""
    if upper <= 0 or lower <= 0 or not all(math.isfinite(v) for v in (*shoulder, *target, upper, lower)):
        raise ValueError('IK requires finite points and positive bone lengths')
    shoulder, target = np.asarray(shoulder, dtype=float), np.asarray(target, dtype=float)
    vector = target-shoulder
    length = float(np.linalg.norm(vector))
    direction = vector/length if length > 1e-8 else np.array([0., 1.])
    distance = float(np.clip(length, abs(upper-lower)+1e-5, upper+lower-1e-5))
    target = shoulder+direction*distance
    theta = math.atan2(direction[1], direction[0]) + bend*math.acos(
        float(np.clip((upper*upper+distance*distance-lower*lower)/(2*upper*distance), -1, 1)))
    elbow = shoulder+np.array([math.cos(theta), math.sin(theta)])*upper
    return elbow, target


def gait_phase(x, stride=96):
    if stride <= 0:
        raise ValueError('stride must be positive')
    return x*.62/stride


def walk_foot(root, hip_offset, scale, side, ground_y, stride=96):
    """Travel-driven stance/swing from the original renderer; no time sliding."""
    q = (gait_phase(root[0], stride) + (0 if side == 'left' else .5)) % 1
    if q < .62:
        dx, lift = stride*(.5-q/.62), 0
    else:
        u = (q-.62)/.38
        dx, lift = stride*(-.5+ease(u)), 35*math.sin(math.pi*u)**2
    return np.array([root[0]+hip_offset*scale+dx, ground_y-lift])


def place(canvas, picture, pivot, target, degrees=0, scale=1):
    """Affine sprite placement with the original pivot-preserving transform."""
    if scale <= 0 or not math.isfinite(scale):
        raise ValueError('sprite scale must be finite and positive')
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    target, pivot = np.asarray(target, dtype=float), np.asarray(pivot, dtype=float)
    corners = np.array([[0,0], [picture.width,0], [0,picture.height], [picture.width,picture.height]], float)
    rotation = np.array([[c,-s], [s,c]])
    corners = (corners-pivot) @ rotation.T * scale + target
    low, high = np.floor(corners.min(0)).astype(int)-2, np.ceil(corners.max(0)).astype(int)+2
    dx, dy = low-target
    coeff = (c/scale, s/scale, pivot[0]+(c*dx+s*dy)/scale,
             -s/scale, c/scale, pivot[1]+(-s*dx+c*dy)/scale)
    transformed = picture.transform(tuple(high-low), Image.Transform.AFFINE, coeff, Image.Resampling.BICUBIC)
    canvas.alpha_composite(transformed, tuple(low))


def camera_point(point, camera, size=(1920,1080), canvas=(1920,1080)):
    zoom = float(camera.get('zoom', 1))
    center = np.asarray(camera.get('center', [canvas[0]/2, canvas[1]/2]), dtype=float)
    if zoom <= 0 or not math.isfinite(zoom):
        raise ValueError('camera zoom must be finite and positive')
    return (np.asarray(point)-center)*zoom*np.array(size)/np.array(canvas)+np.array(size)/2
